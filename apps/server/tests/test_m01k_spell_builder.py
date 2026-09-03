"""M01-K K.10 — the 42 PHB spells travel the existing P1 spellcasting paths."""

from __future__ import annotations

import m01k_support as S


CHROMATIC_ORB = "phb2014:spell:chromatic-orb"
WITCH_BOLT = "phb2014:spell:witch-bolt"
BLADE_WARD = "phb2014:spell:blade-ward"
SEARING_SMITE = "phb2014:spell:searing-smite"
PHANTASMAL_FORCE = "phb2014:spell:phantasmal-force"
AURA_OF_VITALITY = "phb2014:spell:aura-of-vitality"


def _caster(content, class_index, target, *, first_hp, later_hp, subclass_ref, subclass_level, prefer=()):
    levels = S.class_levels(
        class_index,
        target,
        first_hp=first_hp,
        later_hp=later_hp,
        subclass_ref=subclass_ref,
        subclass_level=subclass_level,
    )
    payload = S.fill_spell_choices(
        S.auto_fill(S.payload(levels), content, skip_sources=set()), content, prefer=prefer
    )
    result, _ = S.compile_payload(payload, content)
    return result, payload


# --- Known caster -------------------------------------------------------------


def test_known_caster_can_select_and_persist_a_phb_only_spell() -> None:
    content = S.registry()
    result, payload = _caster(
        content,
        "sorcerer",
        5,
        first_hp=6,
        later_hp=4,
        subclass_ref="srd5.1:subclass:draconic",
        subclass_level=1,
        prefer=(CHROMATIC_ORB, WITCH_BOLT, BLADE_WARD),
    )
    profile = S.spell_profile(result, "class:sorcerer")

    assert S.issue_codes(result) == set()
    assert profile.access_model == "known"
    assert CHROMATIC_ORB in profile.selected_known_spell_keys
    assert WITCH_BOLT in profile.selected_known_spell_keys
    assert BLADE_WARD in profile.selected_cantrip_keys

    persisted = {
        entry.spell_key
        for entry in result.build_candidate.spell_access_entries
        if entry.source_type == "class"
    }
    assert {CHROMATIC_ORB, WITCH_BOLT, BLADE_WARD} <= persisted

    # Reload of the same payload keeps the same permanent selections.
    again, _ = S.compile_payload(payload, content)
    assert again.build_candidate.spell_access_entries == result.build_candidate.spell_access_entries


def test_known_caster_rejects_a_spell_outside_its_class_list() -> None:
    content = S.registry()
    _, payload = _caster(
        content,
        "sorcerer",
        5,
        first_hp=6,
        later_hp=4,
        subclass_ref="srd5.1:subclass:draconic",
        subclass_level=1,
        prefer=(CHROMATIC_ORB,),
    )
    plan = dict(payload.spell_choices)
    current = plan["class:sorcerer"]
    plan["class:sorcerer"] = current.model_copy(
        update={"known_spell_keys": (SEARING_SMITE, *current.known_spell_keys[1:])}
    )
    illegal, _ = S.compile_payload(payload.model_copy(update={"spell_choices": plan}), content)

    assert "spell_not_on_source_list" in S.issue_codes(illegal)
    assert illegal.validation.can_confirm is False


# --- Wizard Spellbook ---------------------------------------------------------


def test_wizard_spellbook_accepts_a_phb_only_wizard_spell() -> None:
    content = S.registry()
    result, payload = _caster(
        content,
        "wizard",
        5,
        first_hp=6,
        later_hp=4,
        subclass_ref="srd5.1:subclass:evocation",
        subclass_level=2,
        prefer=(CHROMATIC_ORB, BLADE_WARD),
    )
    profile = S.spell_profile(result, "class:wizard")

    assert S.issue_codes(result) == set()
    assert profile.access_model == "spellbook"
    assert CHROMATIC_ORB in profile.selected_spellbook_spell_keys
    assert BLADE_WARD in profile.selected_cantrip_keys

    sources = {
        entry.access_type
        for entry in result.build_candidate.spell_access_entries
        if entry.spell_key == CHROMATIC_ORB
    }
    assert "spellbook" in sources

    again, _ = S.compile_payload(payload, content)
    assert (
        S.spell_profile(again, "class:wizard").selected_spellbook_spell_keys
        == profile.selected_spellbook_spell_keys
    )


def test_wizard_spellbook_rejects_a_non_wizard_phb_spell() -> None:
    content = S.registry()
    _, payload = _caster(
        content,
        "wizard",
        5,
        first_hp=6,
        later_hp=4,
        subclass_ref="srd5.1:subclass:evocation",
        subclass_level=2,
        prefer=(CHROMATIC_ORB,),
    )
    plan = dict(payload.spell_choices)
    current = plan["class:wizard"]
    plan["class:wizard"] = current.model_copy(
        update={"spellbook_spell_keys": (SEARING_SMITE, *current.spellbook_spell_keys[1:])}
    )
    illegal, _ = S.compile_payload(payload.model_copy(update={"spell_choices": plan}), content)

    assert "spell_not_on_source_list" in S.issue_codes(illegal)


# --- Prepared caster ----------------------------------------------------------


def test_prepared_caster_sees_phb_spells_in_eligibility_without_moving_them_into_build() -> None:
    content = S.registry()
    result, _ = _caster(
        content,
        "cleric",
        5,
        first_hp=8,
        later_hp=5,
        subclass_ref="srd5.1:subclass:life",
        subclass_level=1,
    )
    profile = S.spell_profile(result, "class:cleric")
    available = {option.spell_key for option in profile.available_spells}

    assert S.issue_codes(result) == set()
    assert profile.access_model == "prepared"
    assert profile.prepared_limit is not None
    assert any(key.startswith("phb2014:spell:") for key in available)

    # Daily preparation is Current State, not part of the immutable Build.
    assert profile.selected_prepared_spell_keys == ()
    assert all(
        entry.access_type != "prepared"
        for entry in result.build_candidate.spell_access_entries
    )


# --- Always Prepared / granted dependency -------------------------------------


def test_a_subclass_granted_phb_spell_stays_isolated_to_that_subclass() -> None:
    content = S.registry()

    def patron(subclass_ref: str):
        result, _ = _caster(
            content,
            "warlock",
            3,
            first_hp=8,
            later_hp=5,
            subclass_ref=subclass_ref,
            subclass_level=1,
        )
        assert S.issue_codes(result) == set(), subclass_ref
        return {
            option.spell_key
            for option in S.spell_profile(result, "class:warlock").available_spells
        }

    archfey = patron("phb2014:subclass:archfey")
    fiend = patron("srd5.1:subclass:fiend")

    assert PHANTASMAL_FORCE in archfey
    assert PHANTASMAL_FORCE not in fiend


def test_a_scag_subclass_can_grant_a_phb_spell_without_duplicating_it() -> None:
    content = S.registry()
    subclass = content.get("scag:subclass:crown")
    granted = [
        value
        for value in _iter_strings(subclass.data)
        if value.startswith("phb2014:spell:")
    ]

    assert AURA_OF_VITALITY in granted
    # One canonical identity; the grant references it rather than cloning it.
    assert content.get(AURA_OF_VITALITY).source == "phb2014"
    assert content.get_optional("scag:spell:aura-of-vitality") is None


def _iter_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_strings(item)


# --- One resolver, not two ----------------------------------------------------


def test_phb_spells_use_the_same_eligibility_resolver_as_srd_spells() -> None:
    content = S.registry()
    result, _ = _caster(
        content,
        "wizard",
        5,
        first_hp=6,
        later_hp=4,
        subclass_ref="srd5.1:subclass:evocation",
        subclass_level=2,
    )
    profile = S.spell_profile(result, "class:wizard")
    by_source: dict[str, set[int]] = {}
    for option in profile.available_spells:
        by_source.setdefault(option.spell_key.split(":", 1)[0], set()).add(option.level)

    assert "phb2014" in by_source and "srd5.1" in by_source
    # Both packs are filtered by the same level ceiling, so neither leaks a spell
    # the wizard cannot yet learn.
    assert max(by_source["phb2014"]) <= profile.max_spell_level
    assert max(by_source["srd5.1"]) <= profile.max_spell_level
