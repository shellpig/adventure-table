from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.content import load_default_content_registry
from app.domain.character_builder.m01j_runtime import prepare_m01j_subclasses
from app.domain.character_builder.schemas import (
    BuilderChoiceSelection,
    BuilderDraft,
    BuilderDraftPayload,
    BuilderLevelChoice,
    BuilderMode,
    BuilderSpellChoiceInput,
)


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


def _single_class_payload(
    class_index: str,
    subclass_ref: str,
    class_level: int,
    *,
    choice_selections: dict[str, BuilderChoiceSelection] | None = None,
    spell_choices: dict[str, BuilderSpellChoiceInput] | None = None,
) -> BuilderDraftPayload:
    hit_die = {
        "cleric": 8,
        "sorcerer": 6,
        "wizard": 6,
    }[class_index]
    levels = tuple(
        BuilderLevelChoice(
            character_level=level,
            class_ref=f"srd5.1:class:{class_index}",
            hp_method="first_level" if level == 1 else "fixed_average",
            hp_base_gain=hit_die if level == 1 else hit_die // 2 + 1,
            subclass_ref=subclass_ref if level == (
                1 if class_index == "sorcerer" else 2 if class_index == "wizard" else 1
            ) else None,
        )
        for level in range(1, class_level + 1)
    )
    return BuilderDraftPayload(
        target_level=class_level,
        level_choices=levels,
        choice_selections=choice_selections or {},
        spell_choices=spell_choices or {},
    )


def test_arcana_mastery_has_four_exact_wizard_spell_level_choices() -> None:
    registry = load_default_content_registry()
    subclass = registry.get("scag:subclass:arcana")
    choices = {
        raw["choice_key"]: raw
        for raw in subclass.data.get("grant_choices", [])
        if isinstance(raw, dict) and isinstance(raw.get("choice_key"), str)
    }
    for spell_level in (6, 7, 8, 9):
        raw = choices[f"arcane-mastery-{spell_level}"]
        assert raw["minimum_class_level"] == 17
        assert raw["choose_total"] == 1
        assert raw["grant_target"] == "spell"
        assert raw["access_type"] == "always_prepared"
        assert raw["option_refs"]
        assert all(registry.get(ref).data.get("level") == spell_level for ref in raw["option_refs"])


def test_clockwork_spell_replacements_are_optional_and_same_level() -> None:
    registry = load_default_content_registry()
    payload = _single_class_payload("sorcerer", "tce:subclass:clockwork-soul", 1)
    runtime = prepare_m01j_subclasses(_draft(payload), registry)
    choices = [
        choice
        for choice in runtime.choices
        if choice.option_source == "content:m01-j-subclass-spell-replacement"
    ]
    assert len(choices) == 2
    assert all(not choice.required for choice in choices)
    for choice in choices:
        assert len(choice.options) > 1
        levels = {registry.get(option.option_id).data.get("level") for option in choice.options}
        assert len(levels) == 1


def test_clockwork_cannot_replace_two_new_feature_spells_at_level_one() -> None:
    registry = load_default_content_registry()
    initial = prepare_m01j_subclasses(
        _draft(_single_class_payload("sorcerer", "tce:subclass:clockwork-soul", 1)),
        registry,
    )
    choices = [
        choice
        for choice in initial.choices
        if choice.option_source == "content:m01-j-subclass-spell-replacement"
    ]
    assert len(choices) == 2
    selected_refs: set[str] = set()
    selections: dict[str, BuilderChoiceSelection] = {}
    for choice in choices:
        alternative = next(
            option.option_id
            for option in choice.options[1:]
            if option.option_id not in selected_refs
        )
        selected_refs.add(alternative)
        selections[choice.choice_id] = BuilderChoiceSelection(
            choice_id=choice.choice_id,
            source_ref=choice.source_ref,
            selected_option_ids=(alternative,),
        )
    runtime = prepare_m01j_subclasses(
        _draft(
            _single_class_payload(
                "sorcerer",
                "tce:subclass:clockwork-soul",
                1,
                choice_selections=selections,
            )
        ),
        registry,
    )
    assert any(
        issue.code == "subclass_spell_replacement_timing_exceeded"
        for issue in runtime.issues
    )


def test_aberrant_replacement_contract_is_divination_or_enchantment() -> None:
    registry = load_default_content_registry()
    subclass = registry.get("tce:subclass:aberrant-mind")
    spec = subclass.data["subclass_spell_replacement"]
    assert set(spec["school_indices"]) == {"divination", "enchantment"}
    assert set(spec["eligible_class_refs"]) == {
        "srd5.1:class:sorcerer",
        "srd5.1:class:warlock",
        "srd5.1:class:wizard",
    }
    assert spec["one_replacement_per_class_level"] is True


def test_improved_minor_illusion_is_conditional_bonus_cantrip() -> None:
    registry = load_default_content_registry()
    payload = _single_class_payload("wizard", "phb2014:subclass:illusion", 2)
    runtime = prepare_m01j_subclasses(_draft(payload), registry)
    assert any(
        grant.target == "spell" and "srd5.1:spell:minor-illusion" in grant.refs
        for grant in runtime.conditional_grants
    )
    assert not any(
        choice.option_source == "content:m01-j-conditional-grant"
        and "Improved Minor Illusion" in choice.label
        for choice in runtime.choices
    )

    already_known = _single_class_payload(
        "wizard",
        "phb2014:subclass:illusion",
        2,
        spell_choices={
            "test:wizard": BuilderSpellChoiceInput(
                cantrip_keys=("srd5.1:spell:minor-illusion",),
            )
        },
    )
    fallback = prepare_m01j_subclasses(_draft(already_known), registry)
    choices = [
        choice
        for choice in fallback.choices
        if choice.option_source == "content:m01-j-conditional-grant"
        and "Improved Minor Illusion" in choice.label
    ]
    assert len(choices) == 1
    assert choices[0].required
    assert all(
        option.option_id != "srd5.1:spell:minor-illusion"
        for option in choices[0].options
    )
