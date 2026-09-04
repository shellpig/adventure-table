from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
import re
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import select

from app.domain.character.schemas import CharacterBuild, CharacterState
from app.interop.content_ref_walker import collect_build_refs, collect_state_refs
from app.interop.json_schema import (
    CharacterExport,
    Envelope,
    ExportedCharacter,
    ExportedState,
    ExportedVersion,
    ExportPayload,
    PackRequirement,
    SourceApp,
)
from app.persistence.characters import (
    CharacterNotFoundError,
    CharacterRepository,
    characters,
    character_states,
    character_versions,
)


ExportChannel = Literal["web", "standalone"]
_FILENAME_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")
_LEGACY_MANIFEST_VERSION = "1.0.0"


@dataclass(frozen=True)
class CharacterExportArtifact:
    document: CharacterExport
    filename: str
    archived: bool


def _source_app(channel: ExportChannel) -> SourceApp:
    commit = os.getenv("ADVENTURE_TABLE_COMMIT") or os.getenv("GIT_COMMIT")
    build = os.getenv("ADVENTURE_TABLE_BUILD") or os.getenv("BUILD_NUMBER")
    return SourceApp(channel=channel, commit=commit, build=build)


def _safe_filename(name: str, version_no: int, exported_at: datetime) -> str:
    stem = _FILENAME_SAFE.sub("_", name.strip()).strip("._-")[:60] or "character"
    timestamp = exported_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stem}-v{version_no}-{timestamp}.json"


def _mapped_version_no(
    version_id: UUID | None,
    id_to_no: dict[UUID, int],
    *,
    relation: str,
) -> int | None:
    if version_id is None:
        return None
    try:
        return id_to_no[version_id]
    except KeyError as exc:
        raise RuntimeError(f"character version {relation} points outside the exported chain") from exc


def build_character_export(
    repository: CharacterRepository,
    character_id: UUID,
    *,
    channel: ExportChannel = "web",
) -> CharacterExportArtifact:
    """Build one server-authoritative, read-only Character JSON export."""

    with repository.engine.connect() as connection:
        character_row = connection.execute(
            select(
                characters.c.id,
                characters.c.name,
                characters.c.ruleset,
                characters.c.current_version_id,
                characters.c.archived_at,
            ).where(characters.c.id == character_id)
        ).mappings().one_or_none()
        if character_row is None or character_row["current_version_id"] is None:
            raise CharacterNotFoundError(str(character_id))

        version_rows = connection.execute(
            select(character_versions)
            .where(character_versions.c.character_id == character_id)
            .order_by(character_versions.c.version_no)
        ).mappings().all()
        state_row = connection.execute(
            select(character_states.c.state_payload).where(
                character_states.c.character_id == character_id
            )
        ).mappings().one_or_none()

    if not version_rows or state_row is None:
        raise RuntimeError(f"character {character_id} has an incomplete persistence chain")

    id_to_no = {row["id"]: int(row["version_no"]) for row in version_rows}
    current_version_no = _mapped_version_no(
        character_row["current_version_id"],
        id_to_no,
        relation="current_version_id",
    )
    if current_version_no is None:
        raise RuntimeError("character current version cannot be null")

    build_key_sets: list[set[str]] = []
    exported_versions: list[ExportedVersion] = []
    for row in version_rows:
        build = CharacterBuild.model_validate(row["build_payload"])
        build_key_sets.append({ref.stable_key for ref in collect_build_refs(build)})
        exported_versions.append(
            ExportedVersion(
                version_no=int(row["version_no"]),
                version_kind=row["version_kind"],
                parent_version_no=_mapped_version_no(
                    row["parent_version_id"], id_to_no, relation="parent_version_id"
                ),
                superseded_by_version_no=_mapped_version_no(
                    row["superseded_by_version_id"],
                    id_to_no,
                    relation="superseded_by_version_id",
                ),
                change_note=row["change_note"],
                build_payload=build.model_dump(mode="json"),
                builder_provenance=row["builder_provenance"],
                created_at=row["created_at"],
            )
        )

    state = CharacterState.model_validate(state_row["state_payload"])
    state_keys = {ref.stable_key for ref in collect_state_refs(state)}
    build_keys: set[str] = set().union(*build_key_sets) if build_key_sets else set()
    all_keys = build_keys | state_keys
    packs = sorted({key.split(":", 1)[0] for key in all_keys})
    requirements: list[PackRequirement] = []
    for pack in packs:
        manifest = repository.registry.get_source_manifest(pack)
        requirements.append(
            PackRequirement(
                pack=pack,
                # Pre-M03 manifests did not require an explicit version. Treat
                # that frozen baseline as 1.0.0 while honoring explicit manifest
                # versions as soon as packs begin declaring them.
                version=manifest.version or _LEGACY_MANIFEST_VERSION,
            )
        )

    exported_at = datetime.now(timezone.utc)
    document = CharacterExport(
        envelope=Envelope(
            ruleset=character_row["ruleset"],
            content_requirements=requirements,
            # Keep build/state origins separate in the summary contract. A key
            # present in both counts once for immutable Build and once for live
            # State, matching the M03 interchange definition.
            stable_key_refs_summary=len(build_keys) + len(state_keys),
            source_character_id=character_row["id"],
            source_export_id=uuid4(),
            source_app=_source_app(channel),
            exported_at=exported_at,
        ),
        payload=ExportPayload(
            character=ExportedCharacter(
                name=character_row["name"],
                ruleset=character_row["ruleset"],
            ),
            current_version_no=current_version_no,
            versions=exported_versions,
            current_state=ExportedState(
                state_payload=state.model_dump(mode="json")
            ),
        ),
    )
    return CharacterExportArtifact(
        document=document,
        filename=_safe_filename(character_row["name"], current_version_no, exported_at),
        archived=character_row["archived_at"] is not None,
    )
