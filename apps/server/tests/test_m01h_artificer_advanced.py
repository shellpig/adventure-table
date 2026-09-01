from __future__ import annotations

import pytest

from app.content import load_default_content_registry
from app.domain.character.schemas import (
    AbilityScores,
    ActiveInfusion,
    CharacterBuild,
    CharacterState,
    InventoryEntry,
    SpellStoringItemState,
    SubclassSelection,
)
from app.domain.character_builder.reconciliation import reconcile_character_state
from app.domain.rules.artificer import (
    ARMOR_MODEL_FEATURE_REF,
    ARMORER_REF,
    ARTIFICER_REF,
    attunement_capacity,
    infused_item_capacity,
    infusion_matches_inventory_item,
    known_infusion_count,
    spell_storing_item_capacity,
    validate_artificer_state,
)
from app.domain.rules.spellcasting import spell_is_on_class_list


KNOWN_LEVEL2 = (
    "tce:infusion:enhanced-defense",
    "tce:infusion:enhanced-weapon",
    "tce:infusion:enhanced-arcane-focus",
    "tce:infusion:returning-weapon",
)


def _build(
    level: int,
    *,
    intelligence: int = 14,
    infusion_refs: tuple[str, ...] = (),
    subclass_ref: str | None = None,
) -> CharacterBuild:
    return CharacterBuild(
        content_sources=("srd5.1", "tce"),
        race_ref="srd5.1:race:human",
        character_level=level,
        class_progression=(ARTIFICER_REF,) * level,
        subclasses=(
            (SubclassSelection(class_ref=ARTIFICER_REF, subclass_ref=subclass_ref),)
            if subclass_ref is not None
            else ()
        ),
        ability_scores=AbilityScores(
            strength=10,
            dexterity=14,
            constitution=10,
            intelligence=intelligence,
            wisdom=10,
            charisma=10,
        ),
        infusion_refs=infusion_refs,
        hp_progression=(8,) + (5,) * (level - 1),
    )


def _state(
    build: CharacterBuild,
    *,
    inventory_state: list[InventoryEntry] | None = None,
    active_infusions: list[ActiveInfusion] | None = None,
    feature_modes: dict[str, str] | None = None,
    spell_storing_item: SpellStoringItemState | None = None,
) -> CharacterState:
    return CharacterState(
        current_hp=8 + 5 * (build.character_level - 1),
        hit_dice_state={"d8": build.character_level},
        inventory_state=inventory_state or [],
        active_infusions=active_infusions or [],
        feature_modes=feature_modes or {},
        spell_storing_item=spell_storing_item,
    )


def test_m01h_infusions_are_first_class_content_with_expected_minimum_set() -> None:
    registry = load_default_content_registry()
    infusions = registry.list_kind("infusion", source="tce")

    assert len(infusions) == 16
    assert {
        "enhanced-defense",
        "enhanced-weapon",
        "enhanced-arcane-focus",
        "returning-weapon",
        "repeating-shot",
        "mind-sharpener",
        "homunculus-servant",
        "armor-of-magical-strength",
        "replicate-magic-item-bag-of-holding",
        "boots-of-the-winding-path",
        "radiant-weapon",
        "repulsion-shield",
        "resistant-armor",
        "spell-refueling-ring",
        "helm-of-awareness",
        "arcane-propulsion-armor",
    } == {entry.index for entry in infusions}

    for entry in infusions:
        assert isinstance(entry.data.get("minimum_artificer_level"), int)
        assert isinstance(entry.data.get("requires_attunement"), bool)
        assert isinstance(entry.data.get("item_filter"), dict)
        assert entry.data.get("description")


@pytest.mark.parametrize(
    ("level", "known", "active"),
    [
        (1, 0, 0),
        (2, 4, 2),
        (5, 4, 2),
        (6, 6, 3),
        (9, 6, 3),
        (10, 8, 4),
        (13, 8, 4),
        (14, 10, 5),
        (17, 10, 5),
        (18, 12, 6),
        (20, 12, 6),
    ],
)
def test_known_and_active_infusion_capacity_matrix(level: int, known: int, active: int) -> None:
    assert known_infusion_count(level) == known
    assert infused_item_capacity(level) == active


@pytest.mark.parametrize(
    ("level", "expected"),
    [(9, 3), (10, 4), (13, 4), (14, 5), (17, 5), (18, 6), (20, 6)],
)
def test_artificer_attunement_capacity_matrix(level: int, expected: int) -> None:
    assert attunement_capacity(_build(level)) == expected


def test_shared_spell_list_contract_recognizes_tce_artificer_cross_pack_spells() -> None:
    registry = load_default_content_registry()

    assert spell_is_on_class_list("srd5.1:spell:cure-wounds", ARTIFICER_REF, registry)
    assert not spell_is_on_class_list("srd5.1:spell:magic-missile", ARTIFICER_REF, registry)


def test_mind_sharpener_accepts_srd_robes_even_though_robes_are_not_armor() -> None:
    registry = load_default_content_registry()
    infusion = registry.get("tce:infusion:mind-sharpener")

    assert infusion_matches_inventory_item(
        infusion.data,
        "srd5.1:equipment:robes",
        registry,
    )


def test_homunculus_servant_rejects_cheap_focus_crystal_below_100_gp() -> None:
    registry = load_default_content_registry()
    infusion = registry.get("tce:infusion:homunculus-servant")
    crystal = registry.get("srd5.1:equipment:crystal")

    assert crystal.data["cost"] == {"quantity": 10, "unit": "gp"}
    assert not infusion_matches_inventory_item(infusion.data, crystal.key, registry)


def test_armor_model_is_live_state_and_rejects_unknown_modes() -> None:
    registry = load_default_content_registry()
    build = _build(3, subclass_ref=ARMORER_REF)

    validate_artificer_state(
        _state(build, feature_modes={ARMOR_MODEL_FEATURE_REF: "guardian"}),
        build,
        registry,
    )

    with pytest.raises(ValueError, match="unsupported Armor Model mode"):
        validate_artificer_state(
            _state(build, feature_modes={ARMOR_MODEL_FEATURE_REF: "invalid"}),
            build,
            registry,
        )


def test_spell_storing_item_accepts_artificer_action_spell_and_weapon_target() -> None:
    registry = load_default_content_registry()
    build = _build(11, intelligence=16)
    capacity = spell_storing_item_capacity(build)
    state = _state(
        build,
        inventory_state=[
            InventoryEntry(
                entry_id="inventory:longsword",
                item_ref="srd5.1:equipment:longsword",
                quantity=1,
                equipped=True,
                carried=True,
            )
        ],
        spell_storing_item=SpellStoringItemState(
            inventory_entry_id="inventory:longsword",
            spell_ref="srd5.1:spell:cure-wounds",
            remaining_uses=capacity,
        ),
    )

    validate_artificer_state(state, build, registry)
    assert capacity == 6


@pytest.mark.parametrize(
    ("spell_ref", "message"),
    [
        ("srd5.1:spell:magic-missile", "Artificer spell list"),
        ("srd5.1:spell:spiritual-weapon", "Artificer spell list"),
    ],
)
def test_spell_storing_item_rejects_non_artificer_spells(spell_ref: str, message: str) -> None:
    registry = load_default_content_registry()
    build = _build(11, intelligence=16)
    state = _state(
        build,
        inventory_state=[
            InventoryEntry(
                entry_id="inventory:longsword",
                item_ref="srd5.1:equipment:longsword",
                quantity=1,
            )
        ],
        spell_storing_item=SpellStoringItemState(
            inventory_entry_id="inventory:longsword",
            spell_ref=spell_ref,
            remaining_uses=1,
        ),
    )

    with pytest.raises(ValueError, match=message):
        validate_artificer_state(state, build, registry)


def test_build_edit_conflict_does_not_silently_remove_active_infusion() -> None:
    registry = load_default_content_registry()
    old_build = _build(2, infusion_refs=KNOWN_LEVEL2)
    new_build = _build(
        2,
        infusion_refs=(
            "tce:infusion:enhanced-weapon",
            "tce:infusion:enhanced-arcane-focus",
            "tce:infusion:returning-weapon",
            "tce:infusion:repeating-shot",
        ),
    )
    old_state = _state(
        old_build,
        inventory_state=[
            InventoryEntry(
                entry_id="inventory:leather",
                item_ref="srd5.1:equipment:leather-armor",
                quantity=1,
            )
        ],
        active_infusions=[
            ActiveInfusion(
                inventory_entry_id="inventory:leather",
                infusion_ref="tce:infusion:enhanced-defense",
            )
        ],
    )

    preview = reconcile_character_state(old_build, old_state, new_build, registry)

    assert not preview.can_apply
    assert any(
        issue.code == "active_infusion_reconciliation_required"
        for issue in preview.blocking_issues
    )
    assert preview.proposed_state.active_infusions == old_state.active_infusions


def test_spell_storing_item_capacity_reconciliation_preserves_used_count() -> None:
    registry = load_default_content_registry()
    old_build = _build(11, intelligence=14)
    new_build = _build(11, intelligence=18)
    old_state = _state(
        old_build,
        inventory_state=[
            InventoryEntry(
                entry_id="inventory:longsword",
                item_ref="srd5.1:equipment:longsword",
                quantity=1,
            )
        ],
        spell_storing_item=SpellStoringItemState(
            inventory_entry_id="inventory:longsword",
            spell_ref="srd5.1:spell:cure-wounds",
            remaining_uses=1,
        ),
    )

    preview = reconcile_character_state(old_build, old_state, new_build, registry)

    assert preview.can_apply
    assert spell_storing_item_capacity(old_build) == 4
    assert spell_storing_item_capacity(new_build) == 8
    assert preview.proposed_state.spell_storing_item is not None
    assert preview.proposed_state.spell_storing_item.remaining_uses == 5
    assert any(
        change.path == "state.spell_storing_item.remaining_uses"
        for change in preview.changes
    )
