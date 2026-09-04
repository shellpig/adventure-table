"""The starting-duplicate check must stay on for everything except Expertise.

M01-J originally silenced ``duplicate_starting_choice`` for every choice whose
option source began ``content:feature:``. The case that needed it was Bard and
Rogue Expertise, which by rule picks a proficiency the character already has.
Excluding all feature choices also switched off duplicate detection for feature
choices that really do grant a proficiency.
"""

from __future__ import annotations

import pytest

from app.content import load_default_content_registry
from app.domain.character_builder.m01i_compiler import compile_builder_draft
from app.domain.character_builder.schemas import BuilderChoiceSelection
from app.domain.character_builder.validation import EXPERTISE_OPTION_SOURCE

from tests.test_m01j_subclasses import (
    _complete_required_choices,
    _draft,
    _payload_for_subclass,
)


@pytest.fixture(scope="module")
def registry():
    return load_default_content_registry()


@pytest.mark.parametrize(
    ("class_index", "subclass_ref", "timing"),
    (
        ("bard", "phb2014:subclass:valor", 3),
        ("rogue", "phb2014:subclass:assassin", 3),
    ),
)
def test_expertise_may_reselect_an_existing_proficiency(
    registry, class_index: str, subclass_ref: str, timing: int
) -> None:
    """Expertise doubles a proficiency, so repeating an earlier pick is legal."""

    draft = _complete_required_choices(
        _payload_for_subclass(class_index, subclass_ref, timing), registry
    )
    result = compile_builder_draft(draft, registry)

    # Rogue Expertise branches, so the branch not taken contributes a child
    # choice that is deliberately unanswerable. Only live choices carry a
    # selection to compare against the starting proficiencies.
    expertise = [
        choice
        for choice in result.choices
        if (choice.option_source or "").startswith(EXPERTISE_OPTION_SOURCE)
        and choice.disabled_reason_code is None
    ]
    assert expertise, f"{class_index} should offer an Expertise choice"

    selected_refs = set()
    for choice in expertise:
        selection = draft.draft_payload.choice_selections.get(choice.choice_id)
        assert selection is not None
        by_id = {option.option_id: option for option in choice.options}
        selected_refs.update(
            by_id[option_id].reference_id for option_id in selection.selected_option_ids
        )

    starting_refs = set()
    for choice in result.choices:
        if (choice.option_source or "") != "content:class-proficiency":
            continue
        selection = draft.draft_payload.choice_selections.get(choice.choice_id)
        if selection is None:
            continue
        by_id = {option.option_id: option for option in choice.options}
        starting_refs.update(
            by_id[option_id].reference_id for option_id in selection.selected_option_ids
        )

    assert selected_refs & starting_refs, (
        "fixture no longer exercises the overlap this test is about"
    )
    assert "duplicate_starting_choice" not in {
        issue.code for issue in result.validation.issues
    }
    assert result.build_candidate is not None


def test_non_expertise_choices_still_reject_duplicate_references(registry) -> None:
    """A granting choice that repeats another choice's pick is still blocked."""

    draft = _complete_required_choices(
        _payload_for_subclass("cleric", "phb2014:subclass:knowledge", 1), registry
    )
    result = compile_builder_draft(draft, registry)

    granting = next(
        choice
        for choice in result.choices
        if (choice.option_source or "") == "content:class-proficiency"
        and choice.choose_count >= 2
    )
    duplicate = granting.options[0].option_id
    payload = draft.draft_payload.model_copy(
        update={
            "choice_selections": {
                **draft.draft_payload.choice_selections,
                granting.choice_id: BuilderChoiceSelection(
                    choice_id=granting.choice_id,
                    source_ref=granting.source_ref,
                    selected_option_ids=(duplicate,) * granting.choose_count,
                ),
            }
        }
    )
    duplicated = compile_builder_draft(_draft(payload), registry)
    assert "duplicate_starting_choice" in {
        issue.code for issue in duplicated.validation.issues
    }
