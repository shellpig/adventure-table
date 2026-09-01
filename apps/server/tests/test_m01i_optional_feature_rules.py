from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.content import load_default_content_registry
from app.domain.character_builder.m01i_runtime import prepare_optional_class_features_for_m01i
from app.domain.character_builder.optional_class_features import (
    _choice_id,
    apply_optional_feature_replacements,
    build_optional_nested_choices,
    compile_nested_feature_selections,
    compile_nested_spell_access,
)
from app.domain.character_builder.schemas import (
    BuilderChoice,
    BuilderChoiceOption,
    BuilderChoiceSelection,
    BuilderDraft,
    BuilderDraftPayload,
    BuilderHPMethod,
    BuilderLevelChoice,
    BuilderMode,
    BuilderOptionKind,
)


FIGHTER = "srd5.1:class:fighter"
PALADIN = "srd5.1:class:paladin"
RANGER = "srd5.1:class:ranger"


def _level(character_level: int, class_ref: str) -> BuilderLevelChoice:
    hit_die = 10
    return BuilderLevelChoice(
        character_level=character_level,
        class_ref=class_ref,
        hp_method=(
            BuilderHPMethod.FIRST_LEVEL
            if character_level == 1
            else BuilderHPMethod.FIXED_AVERAGE
        ),
        hp_base_gain=hit_die if character_level == 1 else 6,
    )


def _create_draft(class_ref: str, level: int) -> BuilderDraft:
    now = datetime.now(UTC)
    return BuilderDraft(
        id=uuid4(),
        mode=BuilderMode.CREATE,
        revision=1,
        draft_payload=BuilderDraftPayload(
            target_level=level,
            level_choices=tuple(_level(index, class_ref) for index in range(1, level + 1)),
        ),
        created_at=now,
        updated_at=now,
    )


def _with_selection(
    draft: BuilderDraft,
    choice_id: str,
    *option_ids: str,
    source_ref: str | None = None,
) -> BuilderDraft:
    selections = dict(draft.draft_payload.choice_selections)
    selections[choice_id] = BuilderChoiceSelection(
        choice_id=choice_id,
        source_ref=source_ref,
        selected_option_ids=tuple(option_ids),
    )
    payload = draft.draft_payload.model_copy(update={"choice_selections": selections})
    return draft.model_copy(update={"draft_payload": payload})


def _style_parent(draft: BuilderDraft, style_ref: str) -> tuple[BuilderDraft, BuilderChoice]:
    choice_id = "fixture:fighting-style"
    draft = _with_selection(draft, choice_id, style_ref, source_ref="srd5.1:feature:fighting-style")
    return draft, BuilderChoice(
        choice_id=choice_id,
        label="Fighting Style",
        source_ref="srd5.1:feature:fighting-style",
        required=True,
        choose_count=1,
        option_source="content:feature:fighting-style",
        options=(
            BuilderChoiceOption(
                option_id=style_ref,
                label=style_ref,
                kind=BuilderOptionKind.REFERENCE,
                reference_id=style_ref,
            ),
        ),
        selected_option_ids=(style_ref,),
    )


@pytest.mark.parametrize(
    ("class_ref", "level", "style_ref", "choose", "ability"),
    [
        (PALADIN, 2, "tce:feature:blessed-warrior", 2, "charisma"),
        (RANGER, 2, "tce:feature:druidic-warrior", 2, "wisdom"),
    ],
)
def test_spell_fighting_styles_use_required_cantrip_count_and_casting_ability(
    class_ref: str,
    level: int,
    style_ref: str,
    choose: int,
    ability: str,
) -> None:
    registry = load_default_content_registry()
    draft, parent = _style_parent(_create_draft(class_ref, level), style_ref)

    children = build_optional_nested_choices(draft, registry, (parent,))

    assert len(children) == 1
    child = children[0]
    assert child.required is True
    assert child.choose_count == choose
    assert child.option_source == "content:optional-feature:cantrip"
    assert child.options
    assert all(
        registry.get(option.reference_id).data.get("level") == 0
        for option in child.options
        if option.reference_id is not None
    )

    selected = tuple(option.reference_id for option in child.options[:choose] if option.reference_id)
    assert len(selected) == choose
    draft = _with_selection(draft, child.choice_id, *selected, source_ref=style_ref)
    spell_entries = compile_nested_spell_access(draft, registry, children)

    assert {entry.spell_key for entry in spell_entries} == set(selected)
    assert {entry.source_key for entry in spell_entries} == {style_ref}
    assert {entry.casting_ability for entry in spell_entries} == {ability}


def test_superior_technique_has_exactly_one_shared_maneuver_choice_and_stale_child_is_ignored() -> None:
    registry = load_default_content_registry()
    style_ref = "tce:feature:superior-technique"
    draft, parent = _style_parent(_create_draft(FIGHTER, 1), style_ref)

    children = build_optional_nested_choices(draft, registry, (parent,))

    assert len(children) == 1
    child = children[0]
    assert child.choose_count == 1
    assert child.option_source == "content:feature:optional-nested"
    assert len(child.options) == 23
    assert {option.reference_id for option in child.options if option.reference_id} >= {
        "phb2014:feature:maneuver-parry",
        "tce:feature:maneuver-ambush",
    }

    maneuver = "tce:feature:maneuver-ambush"
    draft = _with_selection(draft, child.choice_id, maneuver, source_ref=style_ref)
    compiled = compile_nested_feature_selections(draft, registry, children)
    assert maneuver in compiled.feature_refs

    # The stale child value may remain in the Draft for convenience, but once
    # the parent Style changes it is no longer an active choice and cannot enter Build.
    blind = "tce:feature:blind-fighting"
    draft = _with_selection(draft, parent.choice_id, blind, source_ref=parent.source_ref)
    blind_parent = parent.model_copy(
        update={
            "options": (
                BuilderChoiceOption(
                    option_id=blind,
                    label="Blind Fighting",
                    kind=BuilderOptionKind.REFERENCE,
                    reference_id=blind,
                ),
            ),
            "selected_option_ids": (blind,),
        }
    )
    active_children = build_optional_nested_choices(draft, registry, (blind_parent,))
    assert active_children == ()
    assert compile_nested_feature_selections(draft, registry, active_children).feature_refs == ()


def test_ranger_replacement_chain_removes_base_features_from_compiled_refs() -> None:
    registry = load_default_content_registry()
    draft = _create_draft(RANGER, 10)
    replacements = (
        "tce:feature:deft-explorer",
        "tce:feature:favored-foe",
        "tce:feature:primal-awareness",
        "tce:feature:natures-veil",
    )
    for feature_ref in replacements:
        choice_id = _choice_id(draft, "optional-feature", feature_ref)
        draft = _with_selection(draft, choice_id, feature_ref, source_ref=feature_ref)

    runtime = prepare_optional_class_features_for_m01i(draft, registry)
    assert set(replacements) <= set(runtime.active_feature_refs)

    base_refs = (
        "srd5.1:feature:natural-explorer-1",
        "srd5.1:feature:natural-explorer-6",
        "srd5.1:feature:favored-enemy-1",
        "srd5.1:feature:favored-enemy-6",
        "srd5.1:feature:primeval-awareness",
        "srd5.1:feature:hide-in-plain-sight",
        "srd5.1:feature:extra-attack",
    )
    compiled, issues = apply_optional_feature_replacements(base_refs, runtime)

    assert issues == ()
    assert "srd5.1:feature:extra-attack" in compiled
    assert not any("natural-explorer-" in ref for ref in compiled)
    assert not any("favored-enemy-" in ref for ref in compiled)
    assert "srd5.1:feature:primeval-awareness" not in compiled
    assert "srd5.1:feature:hide-in-plain-sight" not in compiled
    assert set(replacements) <= set(compiled)
