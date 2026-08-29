from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.content import load_default_content_registry
from app.domain.character.schemas import ResourceCounter
from app.domain.character_builder.schemas import (
    BuilderDraft,
    BuilderDraftPayload,
    BuilderLevelChoice,
    BuilderMode,
    BuilderSpellChoiceInput,
)
from app.domain.character_builder.spellcasting import (
    calculate_multiclass_spell_slots,
    compile_spellcasting,
)
from app.domain.rules.spellcasting import resource_counter_matches_capacity


def _draft(
    levels: tuple[BuilderLevelChoice, ...],
    *,
    spell_choices: dict[str, BuilderSpellChoiceInput] | None = None,
) -> BuilderDraft:
    now = datetime.now(UTC)
    return BuilderDraft(
        id=uuid4(),
        mode=BuilderMode.CREATE,
        revision=1,
        draft_payload=BuilderDraftPayload(
            target_level=len(levels),
            level_choices=levels,
            spell_choices=spell_choices or {},
        ),
        created_at=now,
        updated_at=now,
    )


def _level(character_level: int, class_index: str, *, subclass: str | None = None) -> BuilderLevelChoice:
    hit_die = {
        "cleric": 8,
        "fighter": 10,
        "paladin": 10,
        "sorcerer": 6,
        "warlock": 8,
        "wizard": 6,
    }.get(class_index, 8)
    return BuilderLevelChoice(
        character_level=character_level,
        class_ref=f"srd5.1:class:{class_index}",
        hp_method="first_level" if character_level == 1 else "fixed_average",
        hp_base_gain=hit_die if character_level == 1 else hit_die // 2 + 1,
        subclass_ref=f"srd5.1:subclass:{subclass}" if subclass else None,
    )


def _class_spells(registry, class_index: str, *, level: int) -> list[str]:
    result: list[str] = []
    for spell in registry.list_kind("spell"):
        if spell.data.get("level") != level:
            continue
        classes = spell.data.get("classes")
        if not isinstance(classes, list):
            continue
        if any(isinstance(item, dict) and item.get("index") == class_index for item in classes):
            result.append(spell.key)
    return sorted(result)


def _codes(result) -> set[str]:
    return {issue.code for issue in result.issues}


def test_wizard_spellbook_and_prepared_state_are_separate() -> None:
    registry = load_default_content_registry()
    cantrips = _class_spells(registry, "wizard", level=0)[:3]
    spellbook = _class_spells(registry, "wizard", level=1)[:6]
    prepared = spellbook[:2]
    draft = _draft(
        (_level(1, "wizard"),),
        spell_choices={
            "class:wizard": BuilderSpellChoiceInput(
                cantrip_keys=tuple(cantrips),
                spellbook_spell_keys=tuple(spellbook),
                prepared_spell_keys=tuple(prepared),
            )
        },
    )

    result = compile_spellcasting(
        draft,
        registry,
        effective_abilities={"intelligence": 16},
    )

    assert result.issues == ()
    profile = result.profiles[0]
    assert profile.access_model == "spellbook"
    assert profile.spellbook_count == 6
    assert profile.prepared_limit == 4
    assert {entry.access_type for entry in result.spell_access_entries} == {"known", "spellbook"}
    assert not any(entry.access_type == "prepared" for entry in result.spell_access_entries)
    assert {item.spell_key for item in result.initial_prepared_spells} == set(prepared)
    assert all(item.source_access_entry_id is not None for item in result.initial_prepared_spells)
    assert calculate_multiclass_spell_slots(draft, registry) == {1: 2}


def test_wizard_rejects_wrong_spellbook_count_and_non_spellbook_prepared_spell() -> None:
    registry = load_default_content_registry()
    cantrips = _class_spells(registry, "wizard", level=0)[:3]
    wizard_spells = _class_spells(registry, "wizard", level=1)
    draft = _draft(
        (_level(1, "wizard"),),
        spell_choices={
            "class:wizard": BuilderSpellChoiceInput(
                cantrip_keys=tuple(cantrips),
                spellbook_spell_keys=tuple(wizard_spells[:5]),
                prepared_spell_keys=(wizard_spells[5],),
            )
        },
    )

    result = compile_spellcasting(
        draft,
        registry,
        effective_abilities={"intelligence": 16},
    )

    assert "invalid_spell_choice_count" in _codes(result)
    assert "prepared_spell_not_in_spellbook" in _codes(result)


def test_prepared_cleric_does_not_materialize_daily_class_list_access_in_build() -> None:
    registry = load_default_content_registry()
    cantrips = _class_spells(registry, "cleric", level=0)[:3]
    prepared = _class_spells(registry, "cleric", level=1)[:2]
    draft = _draft(
        (_level(1, "cleric", subclass="life"),),
        spell_choices={
            "class:cleric": BuilderSpellChoiceInput(
                cantrip_keys=tuple(cantrips),
                prepared_spell_keys=tuple(prepared),
            )
        },
    )

    result = compile_spellcasting(
        draft,
        registry,
        effective_abilities={"wisdom": 16},
    )

    assert result.issues == ()
    profile = result.profiles[0]
    assert profile.access_model == "prepared"
    assert profile.prepared_limit == 4
    class_entries = [entry for entry in result.spell_access_entries if entry.source_type == "class"]
    assert {entry.spell_key for entry in class_entries} == set(cantrips)
    assert all(entry.access_type == "known" for entry in class_entries)
    assert {item.spell_key for item in result.initial_prepared_spells} == set(prepared)
    assert all(item.source_access_entry_id is None for item in result.initial_prepared_spells)

    life_entries = [entry for entry in result.spell_access_entries if entry.source_key == "srd5.1:subclass:life"]
    assert {entry.spell_key for entry in life_entries} == {
        "srd5.1:spell:bless",
        "srd5.1:spell:cure-wounds",
    }
    assert all(entry.access_type == "always_prepared" for entry in life_entries)


def test_prepared_caster_allows_less_than_limit_but_rejects_over_limit() -> None:
    registry = load_default_content_registry()
    cantrips = tuple(_class_spells(registry, "cleric", level=0)[:3])
    level_one = _class_spells(registry, "cleric", level=1)

    less = compile_spellcasting(
        _draft(
            (_level(1, "cleric"),),
            spell_choices={
                "class:cleric": BuilderSpellChoiceInput(
                    cantrip_keys=cantrips,
                    prepared_spell_keys=(level_one[0],),
                )
            },
        ),
        registry,
        effective_abilities={"wisdom": 16},
    )
    assert "prepared_spell_limit_exceeded" not in _codes(less)

    over = compile_spellcasting(
        _draft(
            (_level(1, "cleric"),),
            spell_choices={
                "class:cleric": BuilderSpellChoiceInput(
                    cantrip_keys=cantrips,
                    prepared_spell_keys=tuple(level_one[:5]),
                )
            },
        ),
        registry,
        effective_abilities={"wisdom": 16},
    )
    assert "prepared_spell_limit_exceeded" in _codes(over)


def test_known_sorcerer_compiles_known_access_and_enforces_count() -> None:
    registry = load_default_content_registry()
    cantrips = tuple(_class_spells(registry, "sorcerer", level=0)[:4])
    spells = tuple(_class_spells(registry, "sorcerer", level=1)[:2])
    draft = _draft(
        (_level(1, "sorcerer"),),
        spell_choices={
            "class:sorcerer": BuilderSpellChoiceInput(
                cantrip_keys=cantrips,
                known_spell_keys=spells,
            )
        },
    )

    result = compile_spellcasting(draft, registry, effective_abilities={"charisma": 16})

    assert result.issues == ()
    assert result.profiles[0].access_model == "known"
    assert result.profiles[0].known_spell_count == 2
    assert len(result.spell_access_entries) == 6
    assert all(entry.access_type == "known" for entry in result.spell_access_entries)

    missing = compile_spellcasting(
        _draft(
            (_level(1, "sorcerer"),),
            spell_choices={
                "class:sorcerer": BuilderSpellChoiceInput(
                    cantrip_keys=cantrips,
                    known_spell_keys=spells[:1],
                )
            },
        ),
        registry,
        effective_abilities={"charisma": 16},
    )
    assert "invalid_spell_choice_count" in _codes(missing)


def test_multiclass_combined_slots_use_full_and_half_contributions_and_ignore_noncaster() -> None:
    registry = load_default_content_registry()
    levels = (
        _level(1, "wizard"),
        _level(2, "wizard"),
        _level(3, "wizard"),
        _level(4, "paladin"),
        _level(5, "paladin"),
        _level(6, "fighter"),
    )
    draft = _draft(levels)

    # Wizard 3 + floor(Paladin 2 / 2) = combined caster level 4.
    assert calculate_multiclass_spell_slots(draft, registry) == {1: 4, 2: 3}


def test_warlock_pact_magic_stays_out_of_combined_slots() -> None:
    registry = load_default_content_registry()
    levels = (
        _level(1, "wizard"),
        _level(2, "warlock"),
        _level(3, "warlock"),
        _level(4, "warlock"),
    )
    draft = _draft(levels)

    result = compile_spellcasting(
        draft,
        registry,
        effective_abilities={"intelligence": 16, "charisma": 16},
    )

    assert calculate_multiclass_spell_slots(draft, registry) == {1: 2}
    normal = next(pool for pool in result.resource_pools if pool.pool_type == "normal_multiclass_slots")
    pact = next(pool for pool in result.resource_pools if pool.pool_type == "pact_magic")
    assert [(slot.level, slot.count) for slot in normal.slots] == [(1, 2)]
    # Production Warlock 3 stores this in spell_slots_level_2; source identity
    # keeps it in Pact Magic instead of feeding the combined-slot calculator.
    assert [(slot.level, slot.count) for slot in pact.slots] == [(2, 2)]


def test_same_spell_from_wizard_and_warlock_keeps_distinct_source_identity() -> None:
    registry = load_default_content_registry()
    wizard_level_one = set(_class_spells(registry, "wizard", level=1))
    warlock_level_one = set(_class_spells(registry, "warlock", level=1))
    common = sorted(wizard_level_one & warlock_level_one)
    assert common
    shared = common[0]

    wizard_cantrips = tuple(_class_spells(registry, "wizard", level=0)[:3])
    wizard_book = [shared]
    wizard_book.extend(spell for spell in sorted(wizard_level_one) if spell != shared)
    wizard_book = wizard_book[:6]

    warlock_cantrips = tuple(_class_spells(registry, "warlock", level=0)[:2])
    warlock_known = [shared]
    warlock_known.extend(spell for spell in sorted(warlock_level_one) if spell != shared)
    warlock_known = warlock_known[:2]

    draft = _draft(
        (_level(1, "wizard"), _level(2, "warlock")),
        spell_choices={
            "class:wizard": BuilderSpellChoiceInput(
                cantrip_keys=wizard_cantrips,
                spellbook_spell_keys=tuple(wizard_book),
            ),
            "class:warlock": BuilderSpellChoiceInput(
                cantrip_keys=warlock_cantrips,
                known_spell_keys=tuple(warlock_known),
            ),
        },
    )
    result = compile_spellcasting(
        draft,
        registry,
        effective_abilities={"intelligence": 16, "charisma": 16},
    )

    shared_entries = [entry for entry in result.spell_access_entries if entry.spell_key == shared]
    assert len(shared_entries) == 2
    assert len({entry.entry_id for entry in shared_entries}) == 2
    assert {entry.source_key for entry in shared_entries} == {
        "srd5.1:class:wizard",
        "srd5.1:class:warlock",
    }


def test_resource_counter_capacity_invariant() -> None:
    assert resource_counter_matches_capacity(ResourceCounter(used=1, remaining=2), 3)
    assert not resource_counter_matches_capacity(ResourceCounter(used=1, remaining=1), 3)
