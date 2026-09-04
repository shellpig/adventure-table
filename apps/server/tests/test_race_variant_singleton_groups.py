"""Replacement groups with one option are answered by the server, not the user.

MTF Tiefling bloodlines reuse the M01-E replacement-group skeleton, but each
bloodline binds exactly one Legacy, so the group has choose=1 over a single
option. Asking the player to confirm that is friction, and leaving it required
blocks any client that does not know to answer it. SCAG keeps real branches and
must be untouched, so every assertion here is per group, never per race.
"""

from __future__ import annotations

import pytest

import m01k_support as S
import m01m_support as M

from app.domain.character_builder.race_variants import (
    RACE_VARIANT_REPLACEMENT_OPTION_SOURCE,
    autofill_singleton_replacement_groups,
)


# (variant, the only legal option, the Legacy it grants)
BLOODLINES = [
    ("mtf:race-variant:baalzebul-tiefling", "baalzebul", "mtf:feature:legacy-of-baalzebul"),
    ("mtf:race-variant:dispater-tiefling", "dispater", "mtf:feature:legacy-of-dispater"),
    ("mtf:race-variant:fierna-tiefling", "fierna", "mtf:feature:legacy-of-fierna"),
    ("mtf:race-variant:glasya-tiefling", "glasya", "mtf:feature:legacy-of-glasya"),
    ("mtf:race-variant:levistus-tiefling", "levistus", "mtf:feature:legacy-of-levistus"),
    ("mtf:race-variant:mammon-tiefling", "mammon", "mtf:feature:legacy-of-mammon"),
    (
        "mtf:race-variant:mephistopheles-tiefling",
        "mephistopheles",
        "mtf:feature:legacy-of-mephistopheles",
    ),
    ("mtf:race-variant:zariel-tiefling", "zariel", "mtf:feature:legacy-of-zariel"),
]

HALF_ELF = "srd5.1:race:half-elf"
HALF_ELF_WOOD_VARIANT = "scag:race-variant:half-elf-wood-descent"


def _replacement_choices(result) -> tuple:
    return tuple(
        choice
        for choice in result.choices
        if choice.option_source == RACE_VARIANT_REPLACEMENT_OPTION_SOURCE
    )


@pytest.mark.parametrize(("variant", "option", "legacy"), BLOODLINES)
def test_bloodline_compiles_without_the_player_answering_its_group(
    variant: str,
    option: str,
    legacy: str,
) -> None:
    # No options passed: the draft never records a bloodline selection itself.
    result, _ = M.ancestry(race=M.TIEFLING, variant=variant)
    build = result.build_candidate

    assert result.validation.issues == ()
    assert build is not None
    assert legacy in build.feature_refs
    assert [
        (selection.race_variant_ref, selection.replacement_group_id, selection.selected_option_id)
        for selection in build.race_variant_group_selections
    ] == [(variant, "bloodline", option)]


@pytest.mark.parametrize(("variant", "option", "legacy"), BLOODLINES)
def test_bloodline_group_is_not_offered_as_a_question(
    variant: str,
    option: str,
    legacy: str,
) -> None:
    result, _ = M.ancestry(race=M.TIEFLING, variant=variant)

    assert _replacement_choices(result) == ()


@pytest.mark.parametrize(("variant", "option", "legacy"), BLOODLINES)
def test_an_explicit_selection_still_compiles_to_the_same_build(
    variant: str,
    option: str,
    legacy: str,
) -> None:
    # Older drafts and the Build Edit reseed both arrive with the group filled.
    auto, _ = M.ancestry(race=M.TIEFLING, variant=variant)
    explicit, _ = M.ancestry(race=M.TIEFLING, variant=variant, options={"bloodline": option})

    assert explicit.validation.issues == ()
    assert _replacement_choices(explicit) == ()
    assert (
        explicit.build_candidate.race_variant_group_selections
        == auto.build_candidate.race_variant_group_selections
    )


def test_scag_tiefling_keeps_both_branching_groups() -> None:
    result, _ = M.ancestry(race=M.TIEFLING, variant=M.SCAG_TIEFLING_VARIANT)

    offered = {choice.choice_id: choice for choice in _replacement_choices(result)}
    ability_id = M.group_choice_id(M.SCAG_TIEFLING_VARIANT, M.ABILITY_GROUP)
    legacy_id = M.group_choice_id(M.SCAG_TIEFLING_VARIANT, M.LEGACY_GROUP)

    assert set(offered) == {ability_id, legacy_id}
    assert len(offered[ability_id].options) == 2
    assert len(offered[legacy_id].options) == 4
    assert all(choice.required for choice in offered.values())


def test_scag_tiefling_groups_stay_the_players_call() -> None:
    # Leave the branching groups deliberately unanswered; nothing fills them.
    content = S.registry()
    payload = M.with_variant(M.base_payload(race=M.TIEFLING), M.SCAG_TIEFLING_VARIANT)
    payload = S.auto_fill(
        payload,
        content,
        skip_sources={RACE_VARIANT_REPLACEMENT_OPTION_SOURCE},
    )
    result, _ = S.compile_payload(payload, content)

    assert result.validation.issues != ()
    assert not result.validation.can_confirm


def test_scag_half_elf_keeps_its_branching_group() -> None:
    result, _ = M.ancestry(race=HALF_ELF, variant=HALF_ELF_WOOD_VARIANT)

    offered = _replacement_choices(result)
    assert len(offered) == 1
    assert len(offered[0].options) == 5
    assert offered[0].required


def test_autofill_leaves_a_draft_without_a_variant_untouched() -> None:
    content = S.registry()
    payload = M.base_payload(race=M.TIEFLING)
    draft = S.draft(payload)

    assert autofill_singleton_replacement_groups(draft, content) is draft


def test_autofill_is_idempotent() -> None:
    content = S.registry()
    variant, option, _ = BLOODLINES[-1]
    payload = M.with_variant(M.base_payload(race=M.TIEFLING), variant)
    once = autofill_singleton_replacement_groups(S.draft(payload), content)
    twice = autofill_singleton_replacement_groups(once, content)

    choice_id = M.group_choice_id(variant, "bloodline")
    assert once.draft_payload.choice_selections[choice_id].selected_option_ids == (option,)
    assert twice is once
