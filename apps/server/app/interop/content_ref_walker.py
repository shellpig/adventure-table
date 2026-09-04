from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.content.identity import parse_stable_key
from app.domain.character.schemas import CharacterBuild, CharacterState


BUILD_STABLE_KEY_PATHS = frozenset(
    {
        "race_ref",
        "race_variant_ref",
        "race_variant_group_selections[].race_variant_ref",
        "subrace_ref",
        "lineage_ref",
        "ancestral_origin_ref",
        "ancestral_legacy.retained_skill_refs[]",
        "background_ref",
        "alignment_ref",
        "class_progression[]",
        "subclasses[].class_ref",
        "subclasses[].subclass_ref",
        "proficiencies[]",
        "saving_throw_proficiencies[]",
        "skill_choices[]",
        "skill_expertise_refs[]",
        "language_refs[]",
        "feature_refs[]",
        "feature_grant_sources[].feature_ref",
        "feature_grant_sources[].source_ref",
        "feat_refs[]",
        "feat_acquisitions[].feat_ref",
        "static_derived_modifiers[].source_ref",
        "feat_resource_grants[].source_ref",
        "infusion_refs[]",
        "spellcasting_profiles[].source_key",
        "spellcasting_profiles[].class_ref",
        "spell_access_entries[].spell_key",
        "spell_access_entries[].source_key",
        "starting_equipment[].item_ref",
        "numeric_overrides[skill_modifier:*].key",
        "numeric_overrides[spell_save_dc:*].key",
    }
)

STATE_STABLE_KEY_PATHS = frozenset(
    {
        "conditions[].condition_ref",
        "prepared_spells[].spell_key",
        "inventory_state[].item_ref",
        "active_infusions[].infusion_ref",
        "spell_storing_item.spell_ref",
    }
)

_IDENTITY_FIELD_SUFFIXES = ("_ref", "_refs", "_key", "_keys")


@dataclass(frozen=True, order=True)
class ContentRef:
    stable_key: str
    pack: str
    kind: str


def _collect(keys: Iterable[str | None]) -> tuple[ContentRef, ...]:
    refs: dict[str, ContentRef] = {}
    for key in keys:
        if key is None:
            continue
        parsed = parse_stable_key(key)
        refs[key] = ContentRef(stable_key=key, pack=parsed.source, kind=parsed.kind)
    return tuple(sorted(refs.values()))


def _stable_key_if_valid(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parse_stable_key(value)
    except ValueError:
        return None
    return value


def assert_no_unwalked_stable_keys(
    payload: object,
    walked_keys: set[str],
    *,
    root: str,
) -> None:
    """Fail if a ref-like field contains a StableKey the explicit walker missed.

    The explicit walker remains the portability contract. This recursive audit is
    deliberately only a guard: adding a future ``*_ref``/``*_key`` model field
    cannot silently disappear from ``content_requirements`` once populated.
    """

    missing: list[str] = []

    def visit(value: object, path: str, field_name: str | None = None) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                visit(child, f"{path}.{key}", key)
            return
        if isinstance(value, (list, tuple)):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]", field_name)
            return
        if field_name is None or not field_name.endswith(_IDENTITY_FIELD_SUFFIXES):
            return
        stable_key = _stable_key_if_valid(value)
        if stable_key is not None and stable_key not in walked_keys:
            missing.append(f"{path}={stable_key}")

    visit(payload, root)
    if missing:
        raise RuntimeError(
            "StableKey walker inventory is stale; unwalked ref-like fields: "
            + ", ".join(sorted(missing))
        )


def collect_build_refs(
    build_payload: CharacterBuild | dict[str, object],
) -> tuple[ContentRef, ...]:
    """Collect the explicit StableKey portability contract for CharacterBuild."""

    build = (
        build_payload
        if isinstance(build_payload, CharacterBuild)
        else CharacterBuild.model_validate(build_payload)
    )
    keys: list[str | None] = [
        build.race_ref,
        build.race_variant_ref,
        build.subrace_ref,
        build.lineage_ref,
        build.ancestral_origin_ref,
        build.background_ref,
        build.alignment_ref,
    ]
    keys.extend(item.race_variant_ref for item in build.race_variant_group_selections)
    if build.ancestral_legacy is not None:
        keys.extend(build.ancestral_legacy.retained_skill_refs)
    keys.extend(build.class_progression)
    for item in build.subclasses:
        keys.extend((item.class_ref, item.subclass_ref))
    keys.extend(build.proficiencies)
    keys.extend(build.saving_throw_proficiencies)
    keys.extend(build.skill_choices)
    keys.extend(build.skill_expertise_refs)
    keys.extend(build.language_refs)
    keys.extend(build.feature_refs)
    for item in build.feature_grant_sources:
        keys.extend((item.feature_ref, item.source_ref))
    keys.extend(build.feat_refs)
    keys.extend(item.feat_ref for item in build.feat_acquisitions)
    keys.extend(item.source_ref for item in build.static_derived_modifiers)
    keys.extend(item.source_ref for item in build.feat_resource_grants)
    keys.extend(build.infusion_refs)
    for profile in build.spellcasting_profiles:
        keys.extend((profile.source_key, profile.class_ref))
    for entry in build.spell_access_entries:
        keys.extend((entry.spell_key, entry.source_key))
    keys.extend(item.item_ref for item in build.starting_equipment)

    for override in build.numeric_overrides:
        for prefix in ("skill_modifier:", "spell_save_dc:"):
            if override.key.startswith(prefix):
                keys.append(override.key.removeprefix(prefix))
                break

    refs = _collect(keys)
    assert_no_unwalked_stable_keys(
        build.model_dump(mode="python"),
        {ref.stable_key for ref in refs},
        root="build",
    )
    return refs


def collect_state_refs(
    state_payload: CharacterState | dict[str, object],
) -> tuple[ContentRef, ...]:
    """Collect StableKeys owned by live Current State, not immutable Build."""

    state = (
        state_payload
        if isinstance(state_payload, CharacterState)
        else CharacterState.model_validate(state_payload)
    )
    keys: list[str | None] = []
    keys.extend(item.condition_ref for item in state.conditions)
    keys.extend(item.spell_key for item in state.prepared_spells)
    keys.extend(item.item_ref for item in state.inventory_state)
    keys.extend(item.infusion_ref for item in state.active_infusions)
    if state.spell_storing_item is not None:
        keys.append(state.spell_storing_item.spell_ref)
    refs = _collect(keys)
    assert_no_unwalked_stable_keys(
        state.model_dump(mode="python"),
        {ref.stable_key for ref in refs},
        root="state",
    )
    return refs
