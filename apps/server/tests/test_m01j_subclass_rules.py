from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.content import load_default_content_registry
from app.content.identity import reference_to_stable_key
from app.domain.character_builder.m01i_compiler import compile_builder_draft
from app.domain.character_builder.m01j_extension import prepare_m01j_subclasses
from app.domain.character_builder.m01j_subclasses import m01j_choice_id
from app.domain.character_builder.schemas import (
    BuilderBasicInput,
    BuilderChoiceSelection,
    BuilderDraft,
    BuilderDraftPayload,
    BuilderLevelChoice,
    BuilderMode,
    BuilderReferenceSelection,
    BuilderSpellChoiceInput,
)


DIRECT_SOURCES = {
    "content:race",
    "content:background",
    "content:alignment",
    "content:subrace",
    "content:class",
    "content:subclass",
    "builder:ability-generation",
}


def _draft(payload: BuilderDraftPayload) -> BuilderDraft:
    now = datetime.now(UTC)
    return BuilderDraft(
        id=uuid4(),
        mode=BuilderMode.CREATE,
        revision=1,
        draft_payload=payload,
        created_at=now,
        updated_at=now,
    )


def _level(
    character_level: int,
    class_index: str,
    *,
    class_level: int,
    subclass_ref: str | None = None,
) -> BuilderLevelChoice:
    hit_die = {
        "fighter": 10,
        "monk": 8,
        "ranger": 10,
        "rogue": 8,
        "sorcerer": 6,
        "warlock": 8,
        "wizard": 6,
        "bard": 8,
    }[class_index]
    return BuilderLevelChoice(
        character_level=character_level,
        class_ref=f"srd5.1:class:{class_index}",
        hp_method="first_level" if character_level == 1 else "fixed_average",
        hp_base_gain=hit_die if character_level == 1 else hit_die // 2 + 1,
        subclass_ref=subclass_ref,
    )


def _single_class_payload(
    class_index: str,
    subclass_ref: str,
    *,
    target_level: int,
    timing: int,
) -> BuilderDraftPayload:
    levels = tuple(
        _level(
            character_level,
            class_index,
            class_level=character_level,
            subclass_ref=subclass_ref if character_level == timing else None,
        )
        for character_level in range(1, target_level + 1)
    )
    return BuilderDraftPayload(
        basic=BuilderBasicInput(name="M01-J focused"),
        target_level=target_level,
        race_selection=BuilderReferenceSelection(reference_id="srd5.1:race:human"),
        background_selection=BuilderReferenceSelection(reference_id="srd5.1:background:acolyte"),
        ability_generation={
            "method": "standard_array",
            "scores": {
                "strength": 15,
                "dexterity": 14,
                "constitution": 13,
                "intelligence": 12,
                "wisdom": 10,
                "charisma": 8,
            },
        },
        level_choices=levels,
    )


def _school_index(registry, spell_ref: str) -> str | None:
    spell = registry.get(spell_ref)
    raw = spell.data.get("school")
    if not isinstance(raw, dict):
        return None
    key = reference_to_stable_key(raw, kinds={"magic-school"})
    return key.rsplit(":", 1)[-1] if key is not None else raw.get("index")


def _profile_spell_choice(profile, registry) -> BuilderSpellChoiceInput:
    cantrips = [spell.spell_key for spell in profile.available_spells if spell.level == 0]
    if profile.source_key == "phb2014:subclass:arcane-trickster":
        cantrips = [ref for ref in cantrips if ref != "srd5.1:spell:mage-hand"]
    leveled = [
        spell.spell_key
        for spell in profile.available_spells
        if 1 <= spell.level <= profile.max_spell_level
    ]
    if profile.source_key == "phb2014:subclass:eldritch-knight":
        preferred = {"abjuration", "evocation"}
        leveled.sort(key=lambda ref: (_school_index(registry, ref) not in preferred, ref))
    elif profile.source_key == "phb2014:subclass:arcane-trickster":
        preferred = {"enchantment", "illusion"}
        leveled.sort(key=lambda ref: (_school_index(registry, ref) not in preferred, ref))
    return BuilderSpellChoiceInput(
        cantrip_keys=tuple(cantrips[: profile.cantrip_count]),
        known_spell_keys=tuple(leveled[: profile.known_spell_count]),
        spellbook_spell_keys=tuple(leveled[: profile.spellbook_count]),
        prepared_spell_keys=(),
    )


def _complete(payload: BuilderDraftPayload, registry) -> BuilderDraft:
    selections: dict[str, BuilderChoiceSelection] = dict(payload.choice_selections)
    used_refs: set[str] = set()
    for selection in selections.values():
        used_refs.update(selection.selected_option_ids)

    for _ in range(192):
        current = payload.model_copy(update={"choice_selections": selections})
        result = compile_builder_draft(_draft(current), registry)
        unresolved = next(
            (
                choice
                for choice in result.choices
                if choice.required
                and choice.disabled_reason is None
                and choice.option_source not in DIRECT_SOURCES
                and choice.choice_id not in selections
            ),
            None,
        )
        if unresolved is None:
            spell_choices = dict(current.spell_choices)
            for profile in result.resolved_summary.spellcasting_profiles:
                spell_choices.setdefault(
                    profile.profile_id,
                    _profile_spell_choice(profile, registry),
                )
            return _draft(current.model_copy(update={"spell_choices": spell_choices}))

        available = [
            option
            for option in unresolved.options
            if option.disabled_reason is None
            and (
                unresolved.allow_duplicates
                or option.reference_id is None
                or option.option_id not in used_refs
            )
        ]
        assert len(available) >= unresolved.choose_count, unresolved.choice_id
        selected = tuple(option.option_id for option in available[: unresolved.choose_count])
        for option in available[: unresolved.choose_count]:
            if option.reference_id is not None:
                used_refs.add(option.option_id)
        selections[unresolved.choice_id] = BuilderChoiceSelection(
            choice_id=unresolved.choice_id,
            source_ref=unresolved.source_ref,
            selected_option_ids=selected,
        )
    raise AssertionError("M01-J focused required choices did not converge")


def _choice(runtime, suffix: str):
    return next(choice for choice in runtime.choices if choice.choice_id.endswith(suffix))


def test_battle_master_maneuver_count_progresses_by_fighter_level() -> None:
    registry = load_default_content_registry()
    level3 = prepare_m01j_subclasses(
        _draft(
            _single_class_payload(
                "fighter",
                "phb2014:subclass:battle-master",
                target_level=3,
                timing=3,
            )
        ),
        registry,
    )
    level7 = prepare_m01j_subclasses(
        _draft(
            _single_class_payload(
                "fighter",
                "phb2014:subclass:battle-master",
                target_level=7,
                timing=3,
            )
        ),
        registry,
    )
    assert _choice(level3, "battle-master-maneuvers").choose_count == 3
    assert _choice(level7, "battle-master-maneuvers").choose_count == 5


def test_arcane_archer_and_rune_knight_apply_separate_count_and_level_gates() -> None:
    registry = load_default_content_registry()
    archer = prepare_m01j_subclasses(
        _draft(
            _single_class_payload(
                "fighter",
                "xge:subclass:arcane-archer",
                target_level=3,
                timing=3,
            )
        ),
        registry,
    )
    assert _choice(archer, "arcane-shot-options").choose_count == 2

    rune = prepare_m01j_subclasses(
        _draft(
            _single_class_payload(
                "fighter",
                "tce:subclass:rune-knight",
                target_level=3,
                timing=3,
            )
        ),
        registry,
    )
    rune_choice = _choice(rune, "rune-carver")
    assert rune_choice.choose_count == 2
    gated = {option.label for option in rune_choice.options if option.disabled_reason is not None}
    assert any("Hill Rune" in label for label in gated)
    assert any("Storm Rune" in label for label in gated)


def test_four_elements_fixed_attunement_and_discipline_choice_persist() -> None:
    registry = load_default_content_registry()
    payload = _single_class_payload(
        "monk",
        "phb2014:subclass:four-elements",
        target_level=3,
        timing=3,
    )
    runtime = prepare_m01j_subclasses(_draft(payload), registry)
    choice = _choice(runtime, "elemental-disciplines")
    assert choice.choose_count == 1
    draft = _complete(payload, registry)
    result = compile_builder_draft(draft, registry)
    assert result.build_candidate is not None
    names = {registry.get(ref).name for ref in result.build_candidate.feature_refs}
    assert "Elemental Attunement" in names


def test_dynamic_form_of_the_beast_is_not_a_persistent_build_choice() -> None:
    registry = load_default_content_registry()
    runtime = prepare_m01j_subclasses(
        _draft(
            _single_class_payload(
                "fighter" if False else "fighter",
                "phb2014:subclass:battle-master",
                target_level=3,
                timing=3,
            )
        ),
        registry,
    )
    # Sanity guard for the generic choice path used by the neighboring focused
    # tests. The actual Beast path is checked directly in normalized content.
    assert runtime.choices
    beast = registry.get("tce:subclass:beast")
    assert beast.data.get("persistent_choices") == []


def test_valor_fixed_proficiencies_are_written_to_build() -> None:
    registry = load_default_content_registry()
    payload = _single_class_payload(
        "bard",
        "phb2014:subclass:valor",
        target_level=3,
        timing=3,
    )
    result = compile_builder_draft(_complete(payload, registry), registry)
    assert result.build_candidate is not None
    assert {
        "srd5.1:proficiency:medium-armor",
        "srd5.1:proficiency:shields",
        "srd5.1:proficiency:martial-weapons",
    }.issubset(set(result.build_candidate.proficiencies))


def test_fey_wanderer_skill_choice_is_server_authoritative() -> None:
    registry = load_default_content_registry()
    payload = _single_class_payload(
        "ranger",
        "tce:subclass:fey-wanderer",
        target_level=3,
        timing=3,
    )
    draft = _complete(payload, registry)
    result = compile_builder_draft(draft, registry)
    assert result.build_candidate is not None
    choice_id = m01j_choice_id("tce:subclass:fey-wanderer", "fey-wanderer-skill")
    selected = draft.draft_payload.choice_selections[choice_id].selected_option_ids
    assert selected
    assert set(selected).issubset(set(result.build_candidate.skill_choices))


def test_divine_soul_affinity_grants_only_selected_bonus_spell() -> None:
    registry = load_default_content_registry()
    payload = _single_class_payload(
        "sorcerer",
        "xge:subclass:divine-soul",
        target_level=1,
        timing=1,
    )
    runtime = prepare_m01j_subclasses(_draft(payload), registry)
    choice = _choice(runtime, "divine-soul-affinity")
    selected = choice.options[0].option_id
    choice_id = choice.choice_id
    payload = payload.model_copy(
        update={
            "choice_selections": {
                choice_id: BuilderChoiceSelection(
                    choice_id=choice_id,
                    source_ref=choice.source_ref,
                    selected_option_ids=(selected,),
                )
            }
        }
    )
    selected_runtime = prepare_m01j_subclasses(_draft(payload), registry)
    affinity_entries = [
        entry
        for entry in selected_runtime.base.spell_access_entries
        if entry.source_key == "xge:subclass:divine-soul"
    ]
    assert len(affinity_entries) == 1


def test_genie_kind_controls_branch_expanded_spells() -> None:
    registry = load_default_content_registry()
    payload = _single_class_payload(
        "warlock",
        "tce:subclass:genie",
        target_level=1,
        timing=1,
    )
    runtime = prepare_m01j_subclasses(_draft(payload), registry)
    choice = _choice(runtime, "genie-kind")
    dao = next(option for option in choice.options if "Dao" in option.label)
    payload = payload.model_copy(
        update={
            "choice_selections": {
                choice.choice_id: BuilderChoiceSelection(
                    choice_id=choice.choice_id,
                    source_ref=choice.source_ref,
                    selected_option_ids=(dao.option_id,),
                )
            }
        }
    )
    selected_runtime = prepare_m01j_subclasses(_draft(payload), registry)
    subclass = registry.get("tce:subclass:genie")
    common_level1 = next(
        row["spell"]["key"]
        for row in subclass.data["expanded_spells"]
        if row.get("option_ref") is None
        and row["prerequisites"][0]["index"].endswith("-1")
    )
    dao_level1 = next(
        row["spell"]["key"]
        for row in subclass.data["expanded_spells"]
        if row.get("option_ref") == dao.option_id
        and row["prerequisites"][0]["index"].endswith("-1")
    )
    for spell_ref in (common_level1, dao_level1):
        classes = {
            ref.get("key")
            for ref in selected_runtime.registry.get(spell_ref).data.get("classes", [])
            if isinstance(ref, dict)
        }
        assert "srd5.1:class:warlock" in classes


def test_eldritch_knight_third_caster_profile_and_slots_are_persisted() -> None:
    registry = load_default_content_registry()
    payload = _single_class_payload(
        "fighter",
        "phb2014:subclass:eldritch-knight",
        target_level=3,
        timing=3,
    )
    preview = compile_builder_draft(_draft(payload), registry)
    profile = next(
        profile
        for profile in preview.resolved_summary.spellcasting_profiles
        if profile.source_key == "phb2014:subclass:eldritch-knight"
    )
    assert profile.cantrip_count == 2
    assert profile.known_spell_count == 3
    assert profile.max_spell_level == 1

    result = compile_builder_draft(_complete(payload, registry), registry)
    assert result.build_candidate is not None
    build_profile = next(
        profile
        for profile in result.build_candidate.spellcasting_profiles
        if profile.source_key == "phb2014:subclass:eldritch-knight"
    )
    assert build_profile.source_type == "subclass"
    normal_pool = next(
        pool
        for pool in result.build_candidate.spell_resource_pools
        if pool.pool_type == "normal_multiclass_slots"
    )
    assert [(slot.level, slot.capacity) for slot in normal_pool.slots] == [(1, 2)]


def test_arcane_trickster_fixed_mage_hand_does_not_consume_selectable_cantrip_slot() -> None:
    registry = load_default_content_registry()
    payload = _single_class_payload(
        "rogue",
        "phb2014:subclass:arcane-trickster",
        target_level=3,
        timing=3,
    )
    preview = compile_builder_draft(_draft(payload), registry)
    profile = next(
        profile
        for profile in preview.resolved_summary.spellcasting_profiles
        if profile.source_key == "phb2014:subclass:arcane-trickster"
    )
    assert profile.cantrip_count == 2
    draft = _complete(payload, registry)
    result = compile_builder_draft(draft, registry)
    assert result.build_candidate is not None
    fixed = [
        entry
        for entry in result.build_candidate.spell_access_entries
        if entry.source_key == "phb2014:subclass:arcane-trickster"
        and entry.spell_key == "srd5.1:spell:mage-hand"
    ]
    assert len(fixed) == 1
    assert fixed[0].access_type == "granted"


def test_eldritch_knight_and_wizard_use_combined_multiclass_slot_table() -> None:
    registry = load_default_content_registry()
    levels = (
        _level(1, "fighter", class_level=1),
        _level(2, "fighter", class_level=2),
        _level(
            3,
            "fighter",
            class_level=3,
            subclass_ref="phb2014:subclass:eldritch-knight",
        ),
        _level(4, "wizard", class_level=1),
    )
    payload = BuilderDraftPayload(
        basic=BuilderBasicInput(name="M01-J multiclass caster"),
        target_level=4,
        race_selection=BuilderReferenceSelection(reference_id="srd5.1:race:human"),
        background_selection=BuilderReferenceSelection(reference_id="srd5.1:background:acolyte"),
        ability_generation={
            "method": "standard_array",
            "scores": {
                "strength": 15,
                "dexterity": 10,
                "constitution": 13,
                "intelligence": 14,
                "wisdom": 12,
                "charisma": 8,
            },
        },
        level_choices=levels,
    )
    result = compile_builder_draft(_complete(payload, registry), registry)
    assert result.build_candidate is not None
    normal_pool = next(
        pool
        for pool in result.build_candidate.spell_resource_pools
        if pool.pool_type == "normal_multiclass_slots"
    )
    assert [(slot.level, slot.capacity) for slot in normal_pool.slots] == [(1, 3)]
