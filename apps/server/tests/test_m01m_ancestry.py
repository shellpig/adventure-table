"""M01-M M.2 / M.9 / M.10 — planar parent inheritance, racial casting, structural grants."""

from __future__ import annotations

import pytest
from typing import get_args

import m01m_support as M

from app.content import load_default_content_registry
from app.content.m01l_models import RuntimeExecution
from app.domain.character.schemas import SpellAccessEntry
from app.domain.rules.m01m_ancestry import racial_spell_runtime_metadata


DUERGAR = "mtf:subrace:duergar"
ELADRIN = "mtf:subrace:eladrin"
SEA_ELF = "mtf:subrace:sea-elf"
SHADAR_KAI = "mtf:subrace:shadar-kai"
GITHYANKI = "mtf:subrace:githyanki"
GITHZERAI = "mtf:subrace:githzerai"


@pytest.mark.parametrize(
    ("race", "subrace", "parent_grant"),
    [
        (M.DWARF, DUERGAR, "srd5.1:trait:dwarven-resilience"),
        (M.ELF, ELADRIN, "srd5.1:trait:fey-ancestry"),
        (M.ELF, SEA_ELF, "srd5.1:trait:fey-ancestry"),
        (M.ELF, SHADAR_KAI, "srd5.1:trait:fey-ancestry"),
        (M.GITH, GITHYANKI, "mtf:language:gith"),
        (M.GITH, GITHZERAI, "mtf:language:gith"),
    ],
)
def test_parent_base_grants_land_exactly_once_under_each_subrace(
    race: str,
    subrace: str,
    parent_grant: str,
) -> None:
    result, _ = M.ancestry(race=race, subrace=subrace)
    build = result.build_candidate

    assert result.validation.issues == ()
    assert build is not None
    assert build.race_ref == race
    assert build.subrace_ref == subrace

    granted = M.grant_refs(result)
    assert granted.count(parent_grant) == 1, granted
    # No ref may be compiled twice: a parent grant plus a subrace repeat would
    # double a proficiency or language without any visible error.
    assert len(build.feature_refs) == len(set(build.feature_refs))
    assert len(build.language_refs) == len(set(build.language_refs))
    assert len(build.proficiencies) == len(set(build.proficiencies))


def test_switching_subrace_leaves_no_grant_from_the_previous_branch() -> None:
    sea_elf, _ = M.ancestry(race=M.ELF, subrace=SEA_ELF)
    eladrin, _ = M.ancestry(race=M.ELF, subrace=ELADRIN)

    assert "mtf:feature:child-of-the-sea" in sea_elf.build_candidate.feature_refs
    assert "mtf:feature:child-of-the-sea" not in eladrin.build_candidate.feature_refs
    assert "mtf:feature:eladrin-seasonal-aspect" not in sea_elf.build_candidate.feature_refs
    assert eladrin.build_candidate.swim_speed is None


def test_sea_elf_swim_uses_the_generic_movement_substrate() -> None:
    registry = load_default_content_registry()
    result, _ = M.ancestry(race=M.ELF, subrace=SEA_ELF)

    # The speed is declared as a generic movement grant on the subrace, not as a
    # source-specific rule keyed off the ancestry's name.
    assert registry.get(SEA_ELF).data["movement_grants"] == [{"mode": "swim", "speed": 30}]
    assert result.build_candidate.swim_speed == 30
    assert result.build_candidate.walking_speed == 30


def test_githyanki_grants_martial_proficiencies_and_two_open_choices() -> None:
    result, _ = M.ancestry(race=M.GITH, subrace=GITHYANKI)
    build = result.build_candidate

    for proficiency in (
        "srd5.1:proficiency:light-armor",
        "srd5.1:proficiency:medium-armor",
        "srd5.1:proficiency:shortswords",
        "srd5.1:proficiency:longswords",
        "srd5.1:proficiency:greatswords",
    ):
        assert proficiency in build.proficiencies, proficiency

    choices = {
        choice.choice_id: choice
        for choice in result.choices
        if choice.source_ref == GITHYANKI
    }
    assert len(choices) == 2, sorted(choices)
    assert {choice.choose_count for choice in choices.values()} == {1}
    assert all(choice.required for choice in choices.values())


@pytest.mark.parametrize(
    ("subrace", "spell", "min_level", "ability"),
    [
        (DUERGAR, "srd5.1:spell:enlarge-reduce", 3, None),
        (DUERGAR, "srd5.1:spell:invisibility", 5, None),
        (GITHYANKI, "srd5.1:spell:mage-hand", 1, "intelligence"),
        (GITHYANKI, "srd5.1:spell:jump", 3, "intelligence"),
        (GITHYANKI, "srd5.1:spell:misty-step", 5, "intelligence"),
        (GITHZERAI, "srd5.1:spell:shield", 3, "wisdom"),
        (GITHZERAI, "srd5.1:spell:see-invisibility", 5, "wisdom"),
    ],
)
def test_racial_casting_is_gated_by_character_level_and_keeps_its_ability(
    subrace: str,
    spell: str,
    min_level: int,
    ability: str | None,
) -> None:
    race = M.DWARF if subrace == DUERGAR else M.GITH

    below, _ = M.ancestry(race=race, subrace=subrace, level=min_level - 1) if min_level > 1 else (None, None)
    if below is not None:
        assert spell not in M.spell_access(below), f"{spell} leaked below level {min_level}"

    at_level, _ = M.ancestry(race=race, subrace=subrace, level=min_level)
    entry = M.spell_access(at_level).get(spell)
    assert entry is not None, f"{spell} missing at level {min_level}"
    assert entry.source_type == "race"
    if ability is not None:
        assert entry.casting_ability == ability


def test_duergar_and_gith_casting_waive_components_and_never_spend_slots() -> None:
    registry = load_default_content_registry()

    for race, subrace, spell in (
        (M.DWARF, DUERGAR, "srd5.1:spell:invisibility"),
        (M.GITH, GITHYANKI, "srd5.1:spell:misty-step"),
        (M.GITH, GITHZERAI, "srd5.1:spell:see-invisibility"),
    ):
        result, _ = M.ancestry(race=race, subrace=subrace, level=5)
        entry = M.spell_access(result)[spell]
        metadata = racial_spell_runtime_metadata(entry, registry)

        assert metadata is not None, spell
        assert metadata.uses_spell_slot is False
        assert set(metadata.waive_components) == {"V", "S", "M"}


def test_duergar_enlarge_keeps_its_closed_casting_modifier() -> None:
    registry = load_default_content_registry()
    result, _ = M.ancestry(race=M.DWARF, subrace=DUERGAR, level=5)

    metadata = racial_spell_runtime_metadata(
        M.spell_access(result)["srd5.1:spell:enlarge-reduce"], registry
    )
    assert metadata is not None
    assert metadata.casting_modifiers == ("enlarge_effect_only",)


def test_racial_spell_metadata_is_only_resolved_for_racial_sources() -> None:
    registry = load_default_content_registry()
    forged = SpellAccessEntry(
        entry_id="race:forged:granted",
        spell_key="srd5.1:spell:misty-step",
        source_type="class",
        source_key="mtf:feature:githyanki-psionics",
        access_type="granted",
    )

    assert racial_spell_runtime_metadata(forged, registry) is None


@pytest.mark.parametrize(
    ("subrace", "feature"),
    [
        (SHADAR_KAI, "mtf:feature:shadar-kai-necrotic-resistance"),
        (DUERGAR, "mtf:feature:superior-darkvision"),
        (DUERGAR, "mtf:feature:duergar-sunlight-sensitivity"),
        (ELADRIN, "mtf:feature:fey-step"),
        (SEA_ELF, "mtf:feature:friend-of-the-sea"),
    ],
)
def test_scope_features_are_granted_and_classify_their_automation(
    subrace: str,
    feature: str,
) -> None:
    registry = load_default_content_registry()
    race = {DUERGAR: M.DWARF}.get(subrace, M.ELF)
    result, _ = M.ancestry(race=race, subrace=subrace, level=3)

    assert feature in result.build_candidate.feature_refs
    # Deferred effects must say so rather than being presented as automated.
    assert registry.get(feature).data["runtime_execution"] in get_args(RuntimeExecution)


def test_every_mtf_feature_declares_a_closed_runtime_execution() -> None:
    registry = load_default_content_registry()
    allowed = set(get_args(RuntimeExecution))

    undeclared = [
        entry.key
        for entry in registry.list_kind("feature", source="mtf")
        if entry.data.get("runtime_execution") not in allowed
    ]
    assert undeclared == [], undeclared
