from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import sha1
from typing import Any

from app.content.identity import parse_stable_key, reference_to_stable_key
from app.content.registry import ContentRegistry
from app.content.schemas import ContentEntry
from app.domain.character.schemas import (
    CharacterBuild,
    FeatureGrantSource,
    SpellAccessEntry,
)
from app.domain.character_builder.choices import deterministic_choice_id
from app.domain.character_builder.schemas import (
    BuilderChoice,
    BuilderChoiceOption,
    BuilderDraft,
    BuilderIssue,
    BuilderIssueSeverity,
    BuilderOptionKind,
)


@dataclass(frozen=True)
class M01JSubclassRuntime:
    registry: "M01JSubclassRegistry"
    choices: tuple[BuilderChoice, ...]
    issues: tuple[BuilderIssue, ...]
    selected_option_feature_refs: tuple[str, ...]
    selected_feature_sources: tuple[tuple[str, str], ...]
    spell_access_entries: tuple[SpellAccessEntry, ...]


def m01j_choice_id(subclass_ref: str, choice_key: str) -> str:
    parsed = parse_stable_key(subclass_ref, kinds={"subclass"})
    return deterministic_choice_id("m01-j", parsed.source, parsed.index, choice_key)


def _class_state(draft: BuilderDraft) -> tuple[Counter[str], dict[str, str]]:
    levels: Counter[str] = Counter()
    selected: dict[str, str] = {}
    for level in draft.draft_payload.level_choices:
        levels[level.class_ref] += 1
        if level.subclass_ref is not None:
            selected[level.class_ref] = level.subclass_ref
    return levels, selected


def _choice_total(raw: dict[str, Any], class_level: int) -> int:
    total = raw.get("choose_total")
    result = total if isinstance(total, int) and total >= 1 else 1
    progression = raw.get("progression")
    if isinstance(progression, (list, tuple)):
        for step in progression:
            if not isinstance(step, dict):
                continue
            threshold = step.get("class_level")
            choose_total = step.get("choose_total")
            if (
                isinstance(threshold, int)
                and isinstance(choose_total, int)
                and threshold <= class_level
            ):
                result = choose_total
    return result


def _entry_label(entry: ContentEntry) -> str:
    return f"{entry.name} · {entry.source_label or entry.source}"


def _issue(
    code: str,
    path: str,
    message: str,
    *related_refs: str,
) -> BuilderIssue:
    return BuilderIssue(
        code=code,
        severity=BuilderIssueSeverity.BLOCKING_ERROR,
        path=path,
        message=message,
        related_refs=tuple(related_refs),
    )


def _record_minimum_level(record: dict[str, Any]) -> int:
    prerequisites = record.get("prerequisites")
    if not isinstance(prerequisites, list):
        return 1
    minimum = 1
    for prerequisite in prerequisites:
        if not isinstance(prerequisite, dict) or prerequisite.get("type") != "level":
            continue
        index = prerequisite.get("index")
        if not isinstance(index, str):
            continue
        match = index.rsplit("-", 1)
        if len(match) != 2:
            continue
        try:
            minimum = max(minimum, int(match[1]))
        except ValueError:
            continue
    return minimum


def _record_choice_is_active(
    draft: BuilderDraft,
    subclass_ref: str,
    record: dict[str, Any],
) -> bool:
    choice_key = record.get("choice_key")
    option_ref = record.get("option_ref")
    if choice_key is None and option_ref is None:
        return True
    if not isinstance(choice_key, str) or not isinstance(option_ref, str):
        return False
    choice_id = m01j_choice_id(subclass_ref, choice_key)
    selection = draft.draft_payload.choice_selections.get(choice_id)
    return selection is not None and option_ref in selection.selected_option_ids


def _spell_entry_id(
    subclass_ref: str,
    access_type: str,
    spell_ref: str,
    option_ref: str | None,
) -> str:
    subclass = parse_stable_key(subclass_ref, kinds={"subclass"})
    spell = parse_stable_key(spell_ref, kinds={"spell"})
    digest = sha1(
        f"{subclass_ref}|{access_type}|{spell_ref}|{option_ref or ''}".encode("utf-8")
    ).hexdigest()[:10]
    return f"m01j:{subclass.source}:{subclass.index}:{access_type}:{spell.index}:{digest}"[:120]


class M01JSubclassRegistry:
    """Overlay active subclass expanded spell lists without mutating spell data."""

    def __init__(
        self,
        base: ContentRegistry,
        expanded_by_spell: dict[str, tuple[str, ...]],
    ) -> None:
        self.base = base
        self.expanded_by_spell = expanded_by_spell
        self.enabled_pack_ids = base.enabled_pack_ids

    @property
    def manifest(self):
        return self.base.manifest

    @property
    def pack_count(self) -> int:
        return self.base.pack_count

    def get_source_manifest(self, source: str):
        return self.base.get_source_manifest(source)

    def source_label(self, source: str) -> str:
        return self.base.source_label(source)

    def _overlay_subclass(self, entry: ContentEntry) -> ContentEntry:
        provenance = entry.provenance if isinstance(entry.provenance, dict) else {}
        if provenance.get("type") != "repository-reference":
            return entry
        # The legacy P1 spell compiler assumes every subclass.spells row is
        # always-prepared. M01-J supports granted and conditional spell access,
        # so generated rows are compiled by this extension instead.
        if "spells" not in entry.data and "expanded_spells" not in entry.data:
            return entry
        data = dict(entry.data)
        data.pop("spells", None)
        data.pop("expanded_spells", None)
        return entry.model_copy(update={"data": data})

    def _overlay_spell(self, entry: ContentEntry) -> ContentEntry:
        class_refs = self.expanded_by_spell.get(entry.key)
        if not class_refs:
            return entry
        existing = entry.data.get("classes")
        classes = list(existing) if isinstance(existing, list) else []
        known: set[str] = set()
        for reference in classes:
            if not isinstance(reference, dict):
                continue
            try:
                key = reference_to_stable_key(reference, kinds={"class"})
            except ValueError:
                continue
            if key is not None:
                known.add(key)
        for class_ref in class_refs:
            if class_ref in known:
                continue
            parent = self.base.get_optional(class_ref)
            if parent is None:
                continue
            classes.append({"key": parent.key, "index": parent.index, "name": parent.name})
            known.add(class_ref)
        data = dict(entry.data)
        data["classes"] = classes
        data["m01_j_expanded_spell_sources"] = class_refs
        return entry.model_copy(update={"data": data})

    def _overlay(self, entry: ContentEntry) -> ContentEntry:
        kind = parse_stable_key(entry.key).kind
        if kind == "subclass":
            return self._overlay_subclass(entry)
        if kind == "spell":
            return self._overlay_spell(entry)
        return entry

    def get(self, key: str) -> ContentEntry:
        return self._overlay(self.base.get(key))

    def get_optional(self, key: str) -> ContentEntry | None:
        entry = self.base.get_optional(key)
        return None if entry is None else self._overlay(entry)

    def resolve(self, *parts: str) -> ContentEntry:
        return self._overlay(self.base.resolve(*parts))

    def list_kind(self, kind: str, *, source: str | None = None) -> tuple[ContentEntry, ...]:
        return tuple(self._overlay(entry) for entry in self.base.list_kind(kind, source=source))

    def __len__(self) -> int:
        return len(self.base)

    def __getattr__(self, name: str):
        return getattr(self.base, name)


def prepare_m01j_subclasses(
    draft: BuilderDraft,
    registry: ContentRegistry,
) -> M01JSubclassRuntime:
    class_levels, selected_subclasses = _class_state(draft)
    choices: list[BuilderChoice] = []
    issues: list[BuilderIssue] = []
    active_choice_ids: set[str] = set()
    selected_option_refs: list[str] = []
    selected_sources: list[tuple[str, str]] = []
    spell_entries: dict[str, SpellAccessEntry] = {}
    expanded_by_spell: dict[str, list[str]] = defaultdict(list)

    for class_ref, subclass_ref in sorted(selected_subclasses.items()):
        subclass = registry.get_optional(subclass_ref)
        if subclass is None:
            continue
        class_level = class_levels.get(class_ref, 0)
        raw_choices = subclass.data.get("persistent_choices", [])
        if isinstance(raw_choices, list):
            for raw in raw_choices:
                if not isinstance(raw, dict):
                    continue
                minimum = raw.get("minimum_class_level")
                choice_key = raw.get("choice_key")
                option_refs = raw.get("option_refs")
                if (
                    not isinstance(minimum, int)
                    or minimum > class_level
                    or not isinstance(choice_key, str)
                    or not isinstance(option_refs, (list, tuple))
                ):
                    continue
                choice_id = m01j_choice_id(subclass_ref, choice_key)
                active_choice_ids.add(choice_id)
                choose_total = _choice_total(raw, class_level)
                options: list[BuilderChoiceOption] = []
                legal_refs: set[str] = set()
                for option_ref in option_refs:
                    if not isinstance(option_ref, str):
                        continue
                    target = registry.get_optional(option_ref)
                    if target is None:
                        continue
                    legal_refs.add(option_ref)
                    options.append(
                        BuilderChoiceOption(
                            option_id=option_ref,
                            label=_entry_label(target),
                            kind=BuilderOptionKind.REFERENCE,
                            reference_id=option_ref,
                            category="subclass_choice",
                        )
                    )
                selection = draft.draft_payload.choice_selections.get(choice_id)
                selected = selection.selected_option_ids if selection is not None else ()
                choices.append(
                    BuilderChoice(
                        choice_id=choice_id,
                        label=str(raw.get("label") or subclass.name),
                        source_ref=(
                            str(raw["feature_ref"])
                            if isinstance(raw.get("feature_ref"), str)
                            else subclass_ref
                        ),
                        required=True,
                        choose_count=choose_total,
                        option_source="content:m01-j-subclass-choice",
                        options=tuple(options),
                        selected_option_ids=selected,
                    )
                )
                if len(selected) != choose_total:
                    issues.append(
                        _issue(
                            "invalid_subclass_choice_count",
                            f"draft_payload.choice_selections.{choice_id}",
                            f"{subclass.name} requires exactly {choose_total} selections; got {len(selected)}.",
                            subclass_ref,
                        )
                    )
                if len(selected) != len(set(selected)):
                    issues.append(
                        _issue(
                            "duplicate_subclass_choice",
                            f"draft_payload.choice_selections.{choice_id}",
                            f"{subclass.name} subclass choices cannot contain duplicates.",
                            subclass_ref,
                        )
                    )
                illegal = tuple(ref for ref in selected if ref not in legal_refs)
                if illegal:
                    issues.append(
                        _issue(
                            "illegal_subclass_choice",
                            f"draft_payload.choice_selections.{choice_id}",
                            f"{subclass.name} contains unavailable subclass options.",
                            subclass_ref,
                            *illegal,
                        )
                    )
                for option_ref in selected:
                    if option_ref not in legal_refs:
                        continue
                    selected_option_refs.append(option_ref)
                    source_ref = str(raw.get("feature_ref") or subclass_ref)
                    selected_sources.append((option_ref, source_ref))

        for field in ("spells", "expanded_spells"):
            raw_records = subclass.data.get(field, [])
            if not isinstance(raw_records, list):
                continue
            for record in raw_records:
                if not isinstance(record, dict):
                    continue
                if class_level < _record_minimum_level(record):
                    continue
                if not _record_choice_is_active(draft, subclass_ref, record):
                    continue
                spell = record.get("spell")
                if not isinstance(spell, dict):
                    continue
                try:
                    spell_ref = reference_to_stable_key(spell, kinds={"spell"})
                except ValueError:
                    continue
                if spell_ref is None or registry.get_optional(spell_ref) is None:
                    continue
                if field == "expanded_spells":
                    if class_ref not in expanded_by_spell[spell_ref]:
                        expanded_by_spell[spell_ref].append(class_ref)
                    continue
                access_type = record.get("access_type")
                if access_type not in {"always_prepared", "granted", "known"}:
                    continue
                option_ref = record.get("option_ref") if isinstance(record.get("option_ref"), str) else None
                entry = SpellAccessEntry(
                    entry_id=_spell_entry_id(subclass_ref, str(access_type), spell_ref, option_ref),
                    spell_key=spell_ref,
                    source_type="subclass",
                    source_key=subclass_ref,
                    access_type=str(access_type),
                )
                spell_entries[entry.entry_id] = entry

    for choice_id, selection in draft.draft_payload.choice_selections.items():
        if choice_id.startswith("m01-j:") and choice_id not in active_choice_ids:
            issues.append(
                _issue(
                    "stale_subclass_choice",
                    f"draft_payload.choice_selections.{choice_id}",
                    "A subclass choice remains selected after its subclass/branch is no longer active.",
                    *(selection.selected_option_ids or ()),
                )
            )

    expanded = {
        spell_ref: tuple(dict.fromkeys(class_refs))
        for spell_ref, class_refs in expanded_by_spell.items()
    }
    return M01JSubclassRuntime(
        registry=M01JSubclassRegistry(registry, expanded),
        choices=tuple(choices),
        issues=tuple(issues),
        selected_option_feature_refs=tuple(dict.fromkeys(selected_option_refs)),
        selected_feature_sources=tuple(dict.fromkeys(selected_sources)),
        spell_access_entries=tuple(spell_entries.values()),
    )


def apply_m01j_subclass_runtime(
    build: CharacterBuild,
    runtime: M01JSubclassRuntime,
) -> CharacterBuild:
    """Persist selected subclass options and source-aware spell access in Build."""

    feature_refs = tuple(
        dict.fromkeys((*build.feature_refs, *runtime.selected_option_feature_refs))
    )
    grant_sources = list(build.feature_grant_sources)
    existing_grants = {
        (grant.feature_ref, grant.source_ref, grant.grant_kind)
        for grant in grant_sources
    }
    for feature_ref, source_ref in runtime.selected_feature_sources:
        identity = (feature_ref, source_ref, "choice")
        if identity in existing_grants:
            continue
        grant_sources.append(
            FeatureGrantSource(
                feature_ref=feature_ref,
                source_ref=source_ref,
                grant_kind="choice",
            )
        )
        existing_grants.add(identity)

    spell_entries = {
        entry.entry_id: entry
        for entry in (*build.spell_access_entries, *runtime.spell_access_entries)
    }
    return build.model_copy(
        update={
            "feature_refs": feature_refs,
            "feature_grant_sources": tuple(grant_sources),
            "spell_access_entries": tuple(spell_entries.values()),
        }
    )
