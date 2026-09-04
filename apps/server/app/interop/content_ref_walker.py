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

# Numeric override keys carry a StableKey after one of these semantic prefixes.
# The stored value itself stays an ordinary number.
_OVERRIDE_REFERENCE_PREFIXES = ("skill_modifier:", "spell_save_dc:")
_OVERRIDE_PATH_PREFIX = "numeric_overrides["

# Persisted payload subtrees that hold free-form text authored by the player.
# They are deliberately never interpreted as content references, matching the
# contract already stated in ``app.content.identity``.
_FREE_FORM_SUBTREES = frozenset({"roleplay_profile"})


def _leaf_field_names(paths: frozenset[str]) -> frozenset[str]:
    """Reduce the declared path inventory to the field names the audit checks.

    Deriving this from the inventory keeps one source of truth: a path removed
    from the inventory stops being audited, and a path added starts being
    audited, without a second list to maintain.
    """

    names: set[str] = set()
    for path in paths:
        if path.startswith(_OVERRIDE_PATH_PREFIX):
            continue
        names.add(path.rsplit(".", 1)[-1].removesuffix("[]"))
    return frozenset(names)


BUILD_REF_FIELD_NAMES = _leaf_field_names(BUILD_STABLE_KEY_PATHS)
STATE_REF_FIELD_NAMES = _leaf_field_names(STATE_STABLE_KEY_PATHS)


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


def assert_no_unwalked_stable_keys(
    payload: object,
    walked_keys: set[str],
    *,
    root: str,
    field_names: frozenset[str],
) -> None:
    """Fail if a contractual reference field holds a StableKey the walk missed.

    The audit only inspects the field names the path inventory declares, so
    free-form player text (a roleplay custom field that happens to be named
    ``patron_ref``) can never be mistaken for a portability requirement. Its job
    is to catch the opposite mistake: an inventory path that the explicit walk
    stopped collecting. A brand-new model field is caught by the schema
    inventory test instead, where the developer can classify it deliberately.
    """

    missing: list[str] = []

    def check(value: object, path: str) -> None:
        if isinstance(value, (list, tuple)):
            for index, child in enumerate(value):
                check(child, f"{path}[{index}]")
            return
        if not isinstance(value, str):
            return
        try:
            parse_stable_key(value)
        except ValueError:
            return
        if value not in walked_keys:
            missing.append(f"{path}={value}")

    def visit(value: object, path: str) -> None:
        if isinstance(value, dict):
            override_key = value.get("key")
            if isinstance(override_key, str) and "value" in value:
                for prefix in _OVERRIDE_REFERENCE_PREFIXES:
                    if override_key.startswith(prefix):
                        check(override_key.removeprefix(prefix), f"{path}.key")
                        break
            for name, child in value.items():
                if name in _FREE_FORM_SUBTREES:
                    continue
                child_path = f"{path}.{name}"
                if name in field_names:
                    check(child, child_path)
                visit(child, child_path)
            return
        if isinstance(value, (list, tuple)):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]")

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
        field_names=BUILD_REF_FIELD_NAMES,
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
        field_names=STATE_REF_FIELD_NAMES,
    )
    return refs
