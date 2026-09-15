from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Engine

from app.content.registry import ContentRegistry
from app.domain.character.schemas import CharacterBuild, CharacterState
from app.domain.character.validation import (
    CharacterValidationError,
    validate_build_references,
    validate_state_against_build,
)
from app.domain.character_builder.schemas import BuilderDraftPayload
from app.interop.content_ref_walker import ContentRef, collect_build_refs, collect_state_refs
from app.interop.json_schema import CharacterExport, ExportedVersion
from app.persistence.builder_drafts import character_build_drafts
from app.persistence.character_imports import ImportLandingMode, character_import_records
from app.persistence.characters import characters, character_states, character_versions


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CharacterImportError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        params: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.params = params


class ImportUnresolvedRef(StrictModel):
    stable_key: str
    pack: str
    kind: str
    origin: Literal["build", "state"]
    version_no: int | None = None


class ImportDuplicateHint(StrictModel):
    count: int
    latest_imported_at: datetime | None = None


class ImportCharacterPreview(StrictModel):
    name: str
    level: int
    class_summary: str


class CharacterImportResult(StrictModel):
    dry_run: bool
    committed: bool
    landing_mode: ImportLandingMode
    resolved_ref_count: int
    unresolved_ref_count: int
    unresolved_refs: tuple[ImportUnresolvedRef, ...]
    duplicate_hint: ImportDuplicateHint | None = None
    character_preview: ImportCharacterPreview
    character_id: UUID | None = None
    draft_id: UUID | None = None
    character_path: str | None = None
    draft_path: str | None = None


@dataclass(frozen=True)
class _PreparedImport:
    document: CharacterExport
    versions: tuple[ExportedVersion, ...]
    builds: dict[int, CharacterBuild]
    provenances: dict[int, BuilderDraftPayload | None]
    state: CharacterState
    landing_mode: ImportLandingMode
    resolved_ref_count: int
    unresolved_refs: tuple[ImportUnresolvedRef, ...]
    draft_payload: BuilderDraftPayload | None
    character_preview: ImportCharacterPreview


def _fail(
    code: str,
    message: str,
    *,
    params: dict[str, Any] | None = None,
) -> None:
    raise CharacterImportError(code, message, params=params)


def _check_cycle(versions: tuple[ExportedVersion, ...], field: str) -> None:
    edges = {
        version.version_no: getattr(version, field)
        for version in versions
        if getattr(version, field) is not None
    }
    for start in edges:
        seen: set[int] = set()
        cursor: int | None = start
        while cursor is not None and cursor in edges:
            if cursor in seen:
                _fail(
                    "version_lineage_cycle",
                    f"{field} contains a cycle at version {cursor}",
                    params={"field": field, "version_no": cursor},
                )
            seen.add(cursor)
            cursor = edges.get(cursor)


def _validate_version_chain(document: CharacterExport) -> tuple[ExportedVersion, ...]:
    versions = tuple(document.payload.versions)
    if not versions:
        _fail("invalid_payload_shape", "payload.versions must contain at least one version")

    version_nos = [version.version_no for version in versions]
    if version_nos != sorted(version_nos):
        _fail("version_chain_out_of_order", "versions must be ordered by version_no")
    if version_nos != list(range(1, len(versions) + 1)):
        _fail("version_chain_gap", "versions must form a continuous 1..N chain")

    known = set(version_nos)
    if document.payload.current_version_no not in known:
        _fail(
            "current_state_version_missing",
            "current_version_no does not identify a version in the imported chain",
            params={"current_version_no": document.payload.current_version_no},
        )

    for version in versions:
        for field in ("parent_version_no", "superseded_by_version_no"):
            target = getattr(version, field)
            if target is not None and target not in known:
                _fail(
                    "version_lineage_invalid",
                    f"version {version.version_no} {field} points outside the imported chain",
                    params={
                        "field": field,
                        "version_no": version.version_no,
                        "target_version_no": target,
                    },
                )
            if target == version.version_no:
                _fail(
                    "version_lineage_self_reference",
                    f"version {version.version_no} {field} points to itself",
                    params={"field": field, "version_no": version.version_no},
                )

    _check_cycle(versions, "parent_version_no")
    _check_cycle(versions, "superseded_by_version_no")

    for version in versions:
        if (
            version.parent_version_no is not None
            and version.parent_version_no >= version.version_no
        ):
            _fail(
                "version_lineage_direction_invalid",
                f"version {version.version_no} parent must be an earlier version",
                params={
                    "field": "parent_version_no",
                    "version_no": version.version_no,
                    "target_version_no": version.parent_version_no,
                },
            )
        if (
            version.superseded_by_version_no is not None
            and version.superseded_by_version_no <= version.version_no
        ):
            _fail(
                "version_lineage_direction_invalid",
                f"version {version.version_no} superseded target must be a later version",
                params={
                    "field": "superseded_by_version_no",
                    "version_no": version.version_no,
                    "target_version_no": version.superseded_by_version_no,
                },
            )
    return versions


def _unresolved_row(
    ref: ContentRef,
    *,
    origin: Literal["build", "state"],
    version_no: int | None,
) -> ImportUnresolvedRef:
    return ImportUnresolvedRef(
        stable_key=ref.stable_key,
        pack=ref.pack,
        kind=ref.kind,
        origin=origin,
        version_no=version_no,
    )


def _sanitize_draft_payload(
    provenance: BuilderDraftPayload,
    unresolved_current_build_refs: set[str],
) -> BuilderDraftPayload:
    data = provenance.model_dump(mode="json")

    for field in (
        "race_selection",
        "race_variant_selection",
        "subrace_selection",
        "lineage_selection",
        "background_selection",
        "alignment_selection",
    ):
        selection = data.get(field)
        if (
            isinstance(selection, dict)
            and selection.get("reference_id") in unresolved_current_build_refs
        ):
            data[field] = None

    level_choices: list[dict[str, Any]] = []
    for raw_level in data.get("level_choices") or []:
        if not isinstance(raw_level, dict):
            continue
        level = dict(raw_level)
        if level.get("class_ref") in unresolved_current_build_refs:
            break
        if level.get("subclass_ref") in unresolved_current_build_refs:
            level["subclass_ref"] = None
        level_choices.append(level)
    data["level_choices"] = level_choices

    selections = data.get("choice_selections") or {}
    if isinstance(selections, dict):
        kept: dict[str, Any] = {}
        for choice_id, raw_selection in selections.items():
            if not isinstance(raw_selection, dict):
                continue
            source_ref = raw_selection.get("source_ref")
            selected = raw_selection.get("selected_option_ids") or []
            encoded_unresolved = any(
                unresolved in str(choice_id)
                for unresolved in unresolved_current_build_refs
            )
            if (
                source_ref in unresolved_current_build_refs
                or any(item in unresolved_current_build_refs for item in selected)
                or encoded_unresolved
            ):
                continue
            kept[choice_id] = raw_selection
        data["choice_selections"] = kept

    spell_choices = data.get("spell_choices") or {}
    if isinstance(spell_choices, dict):
        for profile_id, raw_choice in spell_choices.items():
            if not isinstance(raw_choice, dict):
                continue
            for field in (
                "cantrip_keys",
                "known_spell_keys",
                "spellbook_spell_keys",
                "prepared_spell_keys",
            ):
                raw_choice[field] = [
                    key
                    for key in raw_choice.get(field) or []
                    if key not in unresolved_current_build_refs
                ]
            spell_choices[profile_id] = raw_choice
        data["spell_choices"] = spell_choices

    if any(
        ref.split(":", 2)[1] in {"equipment", "item"}
        for ref in unresolved_current_build_refs
        if ref.count(":") >= 2
    ):
        data["starting_equipment_choices"] = {}

    numeric_overrides = data.get("numeric_overrides") or []
    if isinstance(numeric_overrides, list):
        data["numeric_overrides"] = [
            override
            for override in numeric_overrides
            if not (
                isinstance(override, dict)
                and isinstance(override.get("key"), str)
                and any(
                    override["key"].endswith(ref)
                    for ref in unresolved_current_build_refs
                )
            )
        ]

    data["initial_state_seed"] = {}
    return BuilderDraftPayload.model_validate(data)


class CharacterImportService:
    def __init__(self, engine: Engine, registry: ContentRegistry) -> None:
        self.engine = engine
        self.registry = registry

    def _duplicate_hint(self, source_character_id: UUID) -> ImportDuplicateHint | None:
        query = select(
            func.count(character_import_records.c.id).label("count"),
            func.max(character_import_records.c.imported_at).label("latest"),
        ).where(character_import_records.c.source_character_id == source_character_id)
        with self.engine.connect() as connection:
            row = connection.execute(query).mappings().one()
        count = int(row["count"] or 0)
        if count == 0:
            return None
        return ImportDuplicateHint(count=count, latest_imported_at=row["latest"])

    def _class_summary(self, build: CharacterBuild) -> str:
        counts: dict[str, int] = {}
        for class_ref in build.class_progression:
            counts[class_ref] = counts.get(class_ref, 0) + 1
        labels: list[str] = []
        for class_ref, level in counts.items():
            entry = self.registry.get_optional(class_ref)
            fallback = class_ref.split(":", 2)[-1].replace("-", " ").title()
            labels.append(f"{entry.name if entry is not None else fallback} {level}")
        return " / ".join(labels)

    def _supported_rulesets(self) -> set[str]:
        return {
            self.registry.get_source_manifest(pack_id).ruleset
            for pack_id in self.registry.enabled_pack_ids
        }

    def _prepare(self, document: CharacterExport) -> _PreparedImport:
        supported_rulesets = self._supported_rulesets()
        if document.envelope.ruleset not in supported_rulesets:
            _fail(
                "unsupported_ruleset",
                f"unsupported ruleset: {document.envelope.ruleset}",
                params={
                    "ruleset": document.envelope.ruleset,
                    "supported_rulesets": sorted(supported_rulesets),
                },
            )

        versions = _validate_version_chain(document)
        builds: dict[int, CharacterBuild] = {}
        provenances: dict[int, BuilderDraftPayload | None] = {}
        for version in versions:
            try:
                builds[version.version_no] = CharacterBuild.model_validate(version.build_payload)
            except Exception as exc:
                raise CharacterImportError(
                    "invalid_build_shape",
                    f"version {version.version_no} build_payload is invalid: {exc}",
                    params={"version_no": version.version_no},
                ) from exc
            if version.builder_provenance is None:
                provenances[version.version_no] = None
            else:
                try:
                    provenances[version.version_no] = BuilderDraftPayload.model_validate(
                        version.builder_provenance
                    )
                except Exception as exc:
                    raise CharacterImportError(
                        "invalid_builder_provenance",
                        f"version {version.version_no} builder_provenance is invalid: {exc}",
                        params={"version_no": version.version_no},
                    ) from exc

        try:
            state = CharacterState.model_validate(document.payload.current_state.state_payload)
        except Exception as exc:
            raise CharacterImportError(
                "state_shape_invalid",
                f"current_state.state_payload is invalid: {exc}",
            ) from exc

        rulesets = {
            document.envelope.ruleset,
            document.payload.character.ruleset,
            *(build.ruleset for build in builds.values()),
        }
        if len(rulesets) != 1:
            _fail(
                "ruleset_mismatch",
                "envelope, character, and every Build must use the same ruleset",
                params={"rulesets": sorted(rulesets)},
            )

        unresolved: list[ImportUnresolvedRef] = []
        resolved_count = 0
        unresolved_build_keys: set[str] = set()
        unresolved_current_build_keys: set[str] = set()
        current_version_no = document.payload.current_version_no

        for version in versions:
            for ref in collect_build_refs(builds[version.version_no]):
                if self.registry.get_optional(ref.stable_key) is None:
                    unresolved.append(
                        _unresolved_row(
                            ref,
                            origin="build",
                            version_no=version.version_no,
                        )
                    )
                    unresolved_build_keys.add(ref.stable_key)
                    if version.version_no == current_version_no:
                        unresolved_current_build_keys.add(ref.stable_key)
                else:
                    resolved_count += 1

        unresolved_state_keys: set[str] = set()
        for ref in collect_state_refs(state):
            if self.registry.get_optional(ref.stable_key) is None:
                unresolved.append(_unresolved_row(ref, origin="state", version_no=None))
                unresolved_state_keys.add(ref.stable_key)
            else:
                resolved_count += 1

        current_build = builds[current_version_no]
        current_provenance = provenances[current_version_no]
        landing_mode: ImportLandingMode
        draft_payload: BuilderDraftPayload | None = None

        if unresolved_build_keys:
            if current_provenance is None:
                _fail(
                    "draft_reconstruction_unavailable",
                    "unresolved Build references require current-version builder_provenance",
                )
            landing_mode = "draft"
            draft_payload = _sanitize_draft_payload(
                current_provenance,
                unresolved_current_build_keys,
            )
        elif unresolved_state_keys:
            if current_provenance is None:
                _fail(
                    "draft_reconstruction_unavailable",
                    "unresolved State references require current-version builder_provenance",
                )
            landing_mode = "draft_with_history_loss"
            draft_payload = _sanitize_draft_payload(current_provenance, set())
        else:
            for version in versions:
                try:
                    validate_build_references(builds[version.version_no], self.registry)
                except (CharacterValidationError, ValueError) as exc:
                    raise CharacterImportError(
                        "build_references_invalid",
                        f"version {version.version_no} Build references are invalid: {exc}",
                        params={"version_no": version.version_no},
                    ) from exc
            try:
                validate_state_against_build(state, current_build, self.registry)
            except (CharacterValidationError, ValueError) as exc:
                raise CharacterImportError(
                    "state_inconsistent_with_build",
                    f"Current State is inconsistent with the current Build: {exc}",
                ) from exc
            landing_mode = "character"

        unresolved_rows = tuple(
            sorted(
                unresolved,
                key=lambda item: (
                    item.origin,
                    item.version_no or 0,
                    item.stable_key,
                ),
            )
        )
        return _PreparedImport(
            document=document,
            versions=versions,
            builds=builds,
            provenances=provenances,
            state=state,
            landing_mode=landing_mode,
            resolved_ref_count=resolved_count,
            unresolved_refs=unresolved_rows,
            draft_payload=draft_payload,
            character_preview=ImportCharacterPreview(
                name=document.payload.character.name,
                level=max(build.character_level for build in builds.values()),
                class_summary=self._class_summary(current_build),
            ),
        )

    def _result(
        self,
        prepared: _PreparedImport,
        *,
        dry_run: bool,
        character_id: UUID | None = None,
        draft_id: UUID | None = None,
    ) -> CharacterImportResult:
        return CharacterImportResult(
            dry_run=dry_run,
            committed=not dry_run,
            landing_mode=prepared.landing_mode,
            resolved_ref_count=prepared.resolved_ref_count,
            unresolved_ref_count=len(prepared.unresolved_refs),
            unresolved_refs=prepared.unresolved_refs,
            duplicate_hint=self._duplicate_hint(
                prepared.document.envelope.source_character_id
            ),
            character_preview=prepared.character_preview,
            character_id=character_id,
            draft_id=draft_id,
            character_path=(
                f"/characters/{character_id}" if character_id is not None else None
            ),
            draft_path=(
                f"/character-builder/{draft_id}" if draft_id is not None else None
            ),
        )

    def preview(self, document: CharacterExport) -> CharacterImportResult:
        return self._result(self._prepare(document), dry_run=True)

    def commit(self, document: CharacterExport) -> CharacterImportResult:
        prepared = self._prepare(document)
        source_character_id = document.envelope.source_character_id
        source_export_id = document.envelope.source_export_id

        character_id: UUID | None = None
        draft_id: UUID | None = None
        with self.engine.begin() as connection:
            if prepared.landing_mode == "character":
                character_id = uuid4()
                version_ids = {
                    version.version_no: uuid4() for version in prepared.versions
                }
                connection.execute(
                    insert(characters).values(
                        id=character_id,
                        name=document.payload.character.name.strip(),
                        ruleset=document.payload.character.ruleset,
                        current_version_id=None,
                        archived_at=None,
                    )
                )
                for version in prepared.versions:
                    connection.execute(
                        insert(character_versions).values(
                            id=version_ids[version.version_no],
                            character_id=character_id,
                            version_no=version.version_no,
                            build_payload=prepared.builds[version.version_no].model_dump(
                                mode="json"
                            ),
                            builder_provenance=(
                                prepared.provenances[version.version_no].model_dump(
                                    mode="json"
                                )
                                if prepared.provenances[version.version_no] is not None
                                else None
                            ),
                            version_kind=version.version_kind.value,
                            parent_version_id=None,
                            superseded_by_version_id=None,
                            change_note=version.change_note,
                            created_at=version.created_at,
                        )
                    )
                for version in prepared.versions:
                    values: dict[str, UUID | None] = {}
                    if version.parent_version_no is not None:
                        values["parent_version_id"] = version_ids[
                            version.parent_version_no
                        ]
                    if version.superseded_by_version_no is not None:
                        values["superseded_by_version_id"] = version_ids[
                            version.superseded_by_version_no
                        ]
                    if values:
                        connection.execute(
                            update(character_versions)
                            .where(
                                character_versions.c.id
                                == version_ids[version.version_no]
                            )
                            .values(**values)
                        )
                connection.execute(
                    insert(character_states).values(
                        character_id=character_id,
                        state_payload=prepared.state.model_dump(mode="json"),
                    )
                )
                connection.execute(
                    update(characters)
                    .where(characters.c.id == character_id)
                    .values(
                        current_version_id=version_ids[
                            document.payload.current_version_no
                        ],
                        updated_at=func.now(),
                    )
                )
            else:
                if prepared.draft_payload is None:
                    raise RuntimeError("draft landing requires a reconstructed payload")
                draft_id = uuid4()
                connection.execute(
                    insert(character_build_drafts).values(
                        id=draft_id,
                        mode="create",
                        character_id=None,
                        base_version_id=None,
                        revision=1,
                        draft_payload=prepared.draft_payload.model_dump(mode="json"),
                        confirmed_character_id=None,
                        confirmed_version_id=None,
                        confirmed_at=None,
                    )
                )

            if (character_id is None) == (draft_id is None):
                raise RuntimeError("import commit must create exactly one landing target")
            connection.execute(
                insert(character_import_records).values(
                    id=uuid4(),
                    character_id=character_id,
                    draft_id=draft_id,
                    source_character_id=source_character_id,
                    source_export_id=source_export_id,
                    landing_mode=prepared.landing_mode,
                )
            )

        return self._result(
            prepared,
            dry_run=False,
            character_id=character_id,
            draft_id=draft_id,
        )


__all__ = [
    "CharacterImportError",
    "CharacterImportResult",
    "CharacterImportService",
    "ImportDuplicateHint",
    "ImportUnresolvedRef",
]
