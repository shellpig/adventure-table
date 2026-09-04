"""Rogue Expertise offers both SRD branches, including the bundled one.

The SRD models the level 1 Rogue Expertise as a choice between two skill
proficiencies and one skill proficiency plus thieves' tools. The second branch
is an ``option_type: "multiple"`` bundle, which the canonical rule builder used
to skip, so it never reached the builder at all: rogues could not take it, and
what was left was a required question with a single meaningless option gating
the real one.
"""

from __future__ import annotations

import m01k_support as S

from app.domain.character_builder.structural import compile_structural_selections


EXPERTISE_SUFFIX = "feature-specific-expertise_options"
THIEVES_TOOLS = "srd5.1:proficiency:thieves-tools"
ROGUE_LEVELS = S.class_levels("rogue", 1, first_hp=8, later_hp=5)


def _rogue(selections=None):
    payload = S.payload(
        ROGUE_LEVELS,
        race="srd5.1:race:human",
        background="srd5.1:background:acolyte",
        selections=selections or {},
    )
    result, content = S.compile_payload(payload, S.registry())
    return result, payload, content


def _parent(result):
    return next(
        choice for choice in result.choices if choice.choice_id.endswith(EXPERTISE_SUFFIX)
    )


def _live_child(result, parent_id: str):
    return next(
        choice
        for choice in result.choices
        if choice.choice_id.startswith(parent_id)
        and choice.choice_id != parent_id
        and choice.disabled_reason_code is None
    )


def _resolve(option_id: str):
    """Pick the branch, answer its child choice, fill the rest, compile."""

    result, _, content = _rogue()
    parent = _parent(result)
    selections = {parent.choice_id: S.selection(parent.choice_id, option_id)}

    branched, _, _ = _rogue(selections)
    child = _live_child(branched, parent.choice_id)
    picks = [option.option_id for option in child.options[: child.choose_count]]
    selections[child.choice_id] = S.selection(child.choice_id, *picks)

    payload = S.payload(
        ROGUE_LEVELS,
        race="srd5.1:race:human",
        background="srd5.1:background:acolyte",
        selections=selections,
    )
    filled = S.auto_fill(payload, content, skip_sources=set())
    final, _ = S.compile_payload(filled, content)
    return final, child, picks


def test_both_srd_branches_are_offered() -> None:
    result, _, _ = _rogue()
    parent = _parent(result)

    assert parent.required
    assert parent.choose_count == 1
    assert len(parent.options) == 2

    two_skills, bundle = parent.options
    assert two_skills.count == 2
    assert two_skills.granted_reference_ids == ()
    assert bundle.count == 1
    assert bundle.granted_reference_ids == (THIEVES_TOOLS,)
    assert [item.reference_id for item in bundle.presentation_items] == [THIEVES_TOOLS]
    assert bundle.presentation_has_choice


def test_each_branch_asks_for_its_own_number_of_skills() -> None:
    result, _, _ = _rogue()
    parent = _parent(result)
    two_skills, bundle = parent.options

    _, child_a, picks_a = _resolve(two_skills.option_id)
    _, child_b, picks_b = _resolve(bundle.option_id)

    assert child_a.choose_count == 2
    assert len(picks_a) == 2
    assert child_b.choose_count == 1
    assert len(picks_b) == 1


def _structural(option_id: str):
    """Compile only the structural layer, so class grants cannot mask the branch.

    A Rogue is proficient with thieves' tools from the class anyway, so asserting
    on the finished Build proves nothing about where the tools came from.
    """

    result, _, content = _rogue()
    parent = _parent(result)
    selections = {parent.choice_id: S.selection(parent.choice_id, option_id)}
    branched, payload, _ = _rogue(selections)
    child = _live_child(branched, parent.choice_id)
    picks = [option.option_id for option in child.options[: child.choose_count]]
    selections[child.choice_id] = S.selection(child.choice_id, *picks)

    payload = S.payload(
        ROGUE_LEVELS,
        race="srd5.1:race:human",
        background="srd5.1:background:acolyte",
        selections=selections,
    )
    final, _ = S.compile_payload(payload, content)
    return compile_structural_selections(S.draft(payload), content, final.choices), picks


def test_the_bundled_branch_grants_thieves_tools() -> None:
    result, _, _ = _rogue()
    bundle = _parent(result).options[1]

    compiled, picks = _structural(bundle.option_id)

    assert THIEVES_TOOLS in compiled.proficiencies
    assert len(compiled.skill_choices) == len(picks) == 1


def test_the_two_skill_branch_grants_no_tools_of_its_own() -> None:
    result, _, _ = _rogue()
    two_skills = _parent(result).options[0]

    compiled, picks = _structural(two_skills.option_id)

    assert THIEVES_TOOLS not in compiled.proficiencies
    assert len(compiled.skill_choices) == len(picks) == 2
    assert two_skills.granted_reference_ids == ()


def test_the_whole_draft_confirms_on_either_branch() -> None:
    result, _, _ = _rogue()
    for option in _parent(result).options:
        final, _, _ = _resolve(option.option_id)
        assert final.validation.issues == ()
        assert final.build_candidate is not None


def test_neither_branch_is_answerable_before_it_is_picked() -> None:
    result, _, _ = _rogue()
    parent = _parent(result)
    children = [
        choice
        for choice in result.choices
        if choice.choice_id.startswith(parent.choice_id)
        and choice.choice_id != parent.choice_id
    ]

    assert len(children) == 2
    assert all(
        choice.disabled_reason_code == "nested_choice_parent_required" for choice in children
    )
