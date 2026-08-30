from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.content import load_default_content_registry
from app.domain.character_builder.equipment import compile_starting_equipment
from app.domain.character_builder.schemas import (
    BuilderDraft,
    BuilderDraftPayload,
    BuilderLevelChoice,
    BuilderMode,
    BuilderReferenceSelection,
)


def _draft(*, choices: dict[str, object] | None = None) -> BuilderDraft:
    now = datetime.now(UTC)
    return BuilderDraft(
        id=uuid4(),
        mode=BuilderMode.CREATE,
        revision=1,
        draft_payload=BuilderDraftPayload(
            background_selection=BuilderReferenceSelection(
                reference_id="srd5.1:background:acolyte"
            ),
            level_choices=(
                BuilderLevelChoice(
                    character_level=1,
                    class_ref="srd5.1:class:barbarian",
                    hp_method="first_level",
                    hp_base_gain=12,
                ),
            ),
            starting_equipment_choices=choices or {},
        ),
        created_at=now,
        updated_at=now,
    )


def _with_choices(draft: BuilderDraft, choices: dict[str, object]) -> BuilderDraft:
    return draft.model_copy(
        update={
            "draft_payload": draft.draft_payload.model_copy(
                update={"starting_equipment_choices": choices}
            )
        }
    )


def test_starting_equipment_resolves_nested_category_and_quantities_deterministically() -> None:
    registry = load_default_content_registry()
    draft = _draft()

    first = compile_starting_equipment(draft, registry)
    assert first.choices
    assert {
        entry.item_ref: entry.quantity for entry in first.starting_equipment
    }["srd5.1:equipment:javelin"] == 4

    parent = next(
        choice
        for choice in first.choices
        if any(option.kind == "nested_choice" for option in choice.options)
    )
    nested_option = next(option for option in parent.options if option.kind == "nested_choice")
    parent_selected = {parent.choice_id: [nested_option.option_id]}

    second = compile_starting_equipment(_with_choices(draft, parent_selected), registry)
    nested_choice = next(
        choice for choice in second.choices if choice.choice_id != parent.choice_id
    )
    assert nested_choice.option_source == "equipment"
    assert nested_choice.options
    assert all(option.reference_id for option in nested_choice.options)

    selected = {
        **parent_selected,
        nested_choice.choice_id: [nested_choice.options[0].option_id],
    }
    resolved_draft = _with_choices(draft, selected)
    resolved = compile_starting_equipment(resolved_draft, registry)
    repeated = compile_starting_equipment(resolved_draft, registry)

    selected_item = nested_choice.options[0].reference_id
    assert selected_item is not None
    assert selected_item in {entry.item_ref for entry in resolved.starting_equipment}
    assert resolved.starting_equipment == repeated.starting_equipment
    assert resolved.summary == repeated.summary


def test_starting_equipment_ignores_starting_gold_and_rejects_injected_selection_keys() -> None:
    registry = load_default_content_registry()

    result = compile_starting_equipment(
        _draft(choices={"not-a-real-equipment-choice": ["injected"]}),
        registry,
    )

    assert "stale_equipment_choice" in {issue.code for issue in result.issues}
    item_refs = {entry.item_ref for entry in result.starting_equipment}
    assert all("gold" not in item_ref for item_ref in item_refs)
    assert all("coin" not in item_ref for item_ref in item_refs)
