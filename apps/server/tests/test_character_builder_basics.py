from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.content import load_default_content_registry
from app.content.registry import ContentRegistry
from app.domain.character_builder.compiler import compile_builder_draft
from app.domain.character_builder.schemas import (
    BuilderBasicInput,
    BuilderChoiceSelection,
    BuilderDraft,
    BuilderDraftPayload,
    BuilderMode,
    BuilderReferenceSelection,
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


def _scores(*values: int) -> dict[str, int]:
    names = ("strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma")
    return dict(zip(names, values, strict=True))


def _base_payload(*, race: str = "srd5.1:race:human") -> BuilderDraftPayload:
    return BuilderDraftPayload(
        basic=BuilderBasicInput(name="P1-B Hero"),
        target_level=1,
        race_selection=BuilderReferenceSelection(reference_id=race),
        background_selection=BuilderReferenceSelection(reference_id="srd5.1:background:acolyte"),
        ability_generation={"method": "standard_array", "scores": _scores(15, 14, 13, 12, 10, 8)},
    )


def _with_generation(
    payload: BuilderDraftPayload,
    method: str,
    scores: dict[str, int],
) -> BuilderDraftPayload:
    raw = payload.model_dump(mode="python")
    raw["ability_generation"] = {"method": method, "scores": scores}
    return BuilderDraftPayload.model_validate(raw)


def _codes(result) -> set[str]:
    return {issue.code for issue in result.validation.issues}


def test_standard_array_and_racial_bonuses_resolve_once() -> None:
    registry = load_default_content_registry()
    result = compile_builder_draft(_draft(_base_payload()), registry)

    by_ability = {score.ability: score for score in result.resolved_summary.ability_scores}
    assert by_ability["strength"].base == 15
    assert by_ability["strength"].permanent_bonus == 1
    assert by_ability["strength"].resolved == 16
    assert by_ability["strength"].effective == 16

    invalid = _with_generation(
        _base_payload(), "standard_array", _scores(15, 15, 13, 12, 10, 8)
    )
    assert "invalid_standard_array_assignment" in _codes(
        compile_builder_draft(_draft(invalid), registry)
    )


def test_point_buy_is_server_validated_for_budget_and_range() -> None:
    registry = load_default_content_registry()
    legal = _with_generation(
        _base_payload(), "point_buy", _scores(15, 14, 13, 12, 10, 8)
    )
    legal_result = compile_builder_draft(_draft(legal), registry)
    assert "point_buy_budget_exceeded" not in _codes(legal_result)
    assert "point_buy_score_out_of_range" not in _codes(legal_result)

    over_budget = _with_generation(
        _base_payload(), "point_buy", _scores(15, 15, 15, 15, 15, 15)
    )
    assert "point_buy_budget_exceeded" in _codes(
        compile_builder_draft(_draft(over_budget), registry)
    )

    out_of_range = _with_generation(
        _base_payload(), "point_buy", _scores(16, 14, 13, 12, 10, 8)
    )
    assert "point_buy_score_out_of_range" in _codes(
        compile_builder_draft(_draft(out_of_range), registry)
    )


def test_manual_input_preserves_non_standard_values_without_creating_override() -> None:
    registry = load_default_content_registry()
    payload = _with_generation(
        _base_payload(), "manual", _scores(19, 14, 13, 12, 10, 8)
    )
    result = compile_builder_draft(_draft(payload), registry)

    assert "manual_ability_outside_standard_generation" in _codes(result)
    assert payload.numeric_overrides == ()
    strength = next(
        score for score in result.resolved_summary.ability_scores if score.ability == "strength"
    )
    assert strength.base == 19
    assert strength.overridden is False


def test_subrace_must_belong_to_selected_race_and_is_preserved_in_summary() -> None:
    registry = load_default_content_registry()
    raw = _base_payload(race="srd5.1:race:dwarf").model_dump(mode="python")
    raw["subrace_selection"] = {"reference_id": "srd5.1:subrace:high-elf"}
    mismatched = BuilderDraftPayload.model_validate(raw)
    mismatched_result = compile_builder_draft(_draft(mismatched), registry)
    assert "subrace_race_mismatch" in _codes(mismatched_result)

    raw["subrace_selection"] = {"reference_id": "srd5.1:subrace:hill-dwarf"}
    valid = BuilderDraftPayload.model_validate(raw)
    valid_result = compile_builder_draft(_draft(valid), registry)
    assert "subrace_race_mismatch" not in _codes(valid_result)
    assert valid_result.resolved_summary.subrace_name == "Hill Dwarf"
    wisdom = next(
        score for score in valid_result.resolved_summary.ability_scores if score.ability == "wisdom"
    )
    assert wisdom.permanent_bonus == 1


def test_background_and_race_structured_choices_validate_count_and_option() -> None:
    registry = load_default_content_registry()
    draft = _draft(_base_payload(race="srd5.1:race:dragonborn"))
    result = compile_builder_draft(draft, registry)
    background_choice = next(
        choice
        for choice in result.choices
        if choice.source_ref == "srd5.1:background:acolyte"
        and choice.option_source == "content:language_options"
    )
    assert background_choice.choose_count == 2
    assert len(background_choice.options) > 2

    one_language = draft.draft_payload.model_copy(
        update={
            "choice_selections": {
                background_choice.choice_id: BuilderChoiceSelection(
                    choice_id=background_choice.choice_id,
                    source_ref=background_choice.source_ref,
                    selected_option_ids=(background_choice.options[0].option_id,),
                )
            }
        }
    )
    assert "invalid_choice_count" in _codes(
        compile_builder_draft(_draft(one_language), registry)
    )

    illegal = draft.draft_payload.model_copy(
        update={
            "choice_selections": {
                background_choice.choice_id: BuilderChoiceSelection(
                    choice_id=background_choice.choice_id,
                    source_ref=background_choice.source_ref,
                    selected_option_ids=("not-an-option", "also-not-an-option"),
                )
            }
        }
    )
    assert "invalid_choice_option" in _codes(
        compile_builder_draft(_draft(illegal), registry)
    )


def test_background_selector_capability_is_not_hardcoded_to_acolyte() -> None:
    registry = load_default_content_registry()
    acolyte = registry.get("srd5.1:background:acolyte")
    custom = acolyte.model_copy(
        update={
            "key": "srd5.1:background:test-scholar",
            "index": "test-scholar",
            "name": "Test Scholar",
            "data": {
                **acolyte.data,
                "index": "test-scholar",
                "name": "Test Scholar",
                "url": "/api/2014/backgrounds/test-scholar",
            },
        }
    )

    by_kind: dict[str, tuple] = {}
    entries = {}
    for category in registry.manifest.categories:
        kind_entries = list(registry.list_kind(category.kind))
        if category.kind == "background":
            kind_entries.append(custom)
        by_kind[category.kind] = tuple(kind_entries)
        entries.update({entry.key: entry for entry in kind_entries})
    test_registry = ContentRegistry(registry.manifest, entries, by_kind)

    result = compile_builder_draft(_draft(BuilderDraftPayload()), test_registry)
    background_choice = next(
        choice for choice in result.choices if choice.option_source == "content:background"
    )
    assert {option.option_id for option in background_choice.options} >= {
        "srd5.1:background:acolyte",
        "srd5.1:background:test-scholar",
    }
