from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.content import load_default_content_registry
from app.domain.character_builder.schemas import BuilderDraft, BuilderDraftPayload, BuilderLevelChoice, BuilderMode
from app.domain.character_builder.spellcasting import calculate_multiclass_spell_slots


def _level(character_level: int, class_index: str) -> BuilderLevelChoice:
    hit_die = {"paladin": 10, "warlock": 8, "wizard": 6}[class_index]
    return BuilderLevelChoice(
        character_level=character_level,
        class_ref=f"srd5.1:class:{class_index}",
        hp_method="first_level" if character_level == 1 else "fixed_average",
        hp_base_gain=hit_die if character_level == 1 else hit_die // 2 + 1,
    )


def _draft(class_indexes: tuple[str, ...]) -> BuilderDraft:
    now = datetime.now(UTC)
    levels = tuple(_level(index + 1, class_index) for index, class_index in enumerate(class_indexes))
    return BuilderDraft(
        id=uuid4(),
        mode=BuilderMode.CREATE,
        revision=1,
        draft_payload=BuilderDraftPayload(target_level=len(levels), level_choices=levels),
        created_at=now,
        updated_at=now,
    )


def test_single_half_caster_uses_its_own_class_slot_table() -> None:
    registry = load_default_content_registry()
    paladin_three = _draft(("paladin", "paladin", "paladin"))

    assert calculate_multiclass_spell_slots(paladin_three, registry) == {1: 3}


def test_pact_magic_does_not_force_single_normal_caster_onto_multiclass_table() -> None:
    registry = load_default_content_registry()
    paladin_three_warlock_three = _draft(
        ("paladin", "paladin", "paladin", "warlock", "warlock", "warlock")
    )

    assert calculate_multiclass_spell_slots(paladin_three_warlock_three, registry) == {1: 3}


def test_two_normal_spellcasting_classes_use_combined_caster_level_table() -> None:
    registry = load_default_content_registry()
    wizard_three_paladin_three = _draft(
        ("wizard", "wizard", "wizard", "paladin", "paladin", "paladin")
    )

    # Wizard 3 + floor(Paladin 3 / 2) = combined caster level 4.
    assert calculate_multiclass_spell_slots(wizard_three_paladin_three, registry) == {1: 4, 2: 3}
