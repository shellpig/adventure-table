from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.content.identity import parse_stable_key
from app.domain.character.schemas import CharacterBuild, CharacterState


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


def collect_build_refs(build_payload: CharacterBuild | dict[str, object]) -> tuple[ContentRef, ...]:
    """Collect every contractually StableKey-backed field in CharacterBuild.

    Validation happens before walking. CharacterBuild forbids unknown fields, so
    a future persisted schema addition fails loudly until this walker is reviewed
    instead of silently disappearing from portability requirements.
    """

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

    # Numeric override keys can carry a StableKey after one of the established
    # semantic prefixes. The value remains an ordinary number.
    for override in build.numeric_overrides:
        for prefix in ("skill_modifier:", "spell_save_dc:"):
            if override.key.startswith(prefix):
                keys.append(override.key.removeprefix(prefix))
                break

    return _collect(keys)


def collect_state_refs(state_payload: CharacterState | dict[str, object]) -> tuple[ContentRef, ...]:
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
    return _collect(keys)
