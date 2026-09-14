from __future__ import annotations

from uuid import uuid4

import pytest

from app.domain.combat import CombatantState, injury_level, project_combatant


def _enemy(**overrides) -> CombatantState:
    values = {
        "id": uuid4(),
        "kind": "monster",
        "name": "Young Red Dragon",
        "description": "A scarred dragon circles overhead.",
        "armor_class": 18,
        "max_hp": 178,
        "current_hp": 41,
        "temp_hp": 7,
        "speed": {"walk": "40 ft.", "fly": "80 ft."},
        "initiative": 16,
        "public_conditions": ("prone",),
        "hidden_conditions": ("marked-by-dm",),
        "public_effects": ("on-fire",),
        "hidden_effects": ("secret-curse",),
        "traits": ({"name": "Fire Immunity"},),
        "actions": ({"name": "Multiattack"},),
        "bonus_actions": ({"name": "Wing Feint"},),
        "reactions": ({"name": "Parry"},),
        "legendary_actions": ({"name": "Detect"},),
        "resources": {"spell_slots": {"3": 2}, "recharge": {"breath": False}},
        "reaction_available": False,
        "position_note": "behind the ruined tower",
        "dm_notes": "flees at 20 HP",
    }
    values.update(overrides)
    return CombatantState(**values)


def test_dm_projection_contains_complete_enemy_state() -> None:
    enemy = _enemy()
    projected = project_combatant(enemy, audience="dm", enemy=True)
    assert projected is not None
    assert projected["current_hp"] == 41
    assert projected["max_hp"] == 178
    assert projected["temp_hp"] == 7
    assert projected["armor_class"] == 18
    assert projected["resources"]["spell_slots"] == {"3": 2}
    assert projected["reaction_available"] is False
    assert "marked-by-dm" in projected["conditions"]
    assert projected["traits"] == [{"name": "Fire Immunity"}]
    assert projected["dm_notes"] == "flees at 20 HP"


def test_enemy_player_projection_is_allowlist_only() -> None:
    enemy = _enemy()
    projected = project_combatant(enemy, audience="player", enemy=True)
    assert projected == {
        "id": str(enemy.id),
        "kind": "monster",
        "name": "Young Red Dragon",
        "combat_status": "active",
        "injury_level": "critical",
        "conditions": ["prone"],
        "effects": ["on-fire"],
        "initiative": 16,
    }
    forbidden = {
        "current_hp",
        "max_hp",
        "temp_hp",
        "armor_class",
        "speed",
        "traits",
        "actions",
        "bonus_actions",
        "reactions",
        "legendary_actions",
        "resources",
        "reaction_available",
        "dm_notes",
        "position_note",
        "description",
    }
    assert forbidden.isdisjoint(projected)


def test_enemy_reveals_are_explicit_and_do_not_unlock_other_private_state() -> None:
    enemy = _enemy(
        armor_class_revealed=True,
        description_revealed=True,
        position_note_revealed=True,
    )
    projected = project_combatant(enemy, audience="player", enemy=True)
    assert projected is not None
    assert projected["armor_class"] == 18
    assert projected["description"] == "A scarred dragon circles overhead."
    assert projected["position_note"] == "behind the ruined tower"
    assert "current_hp" not in projected
    assert "resources" not in projected
    assert "reaction_available" not in projected
    assert "marked-by-dm" not in projected["conditions"]
    assert "secret-curse" not in projected["effects"]


def test_hidden_enemy_has_no_player_projection() -> None:
    enemy = _enemy(visibility="hidden")
    assert project_combatant(enemy, audience="player", enemy=True) is None
    assert project_combatant(enemy, audience="dm", enemy=True) is not None


def test_friendly_player_projection_keeps_mechanics_but_drops_dm_notes() -> None:
    ally = _enemy(kind="character", name="Grey")
    projected = project_combatant(ally, audience="player", enemy=False)
    assert projected is not None
    assert projected["current_hp"] == 41
    assert projected["armor_class"] == 18
    assert projected["resources"]["spell_slots"] == {"3": 2}
    assert "dm_notes" not in projected


@pytest.mark.parametrize(
    ("current_hp", "max_hp", "status", "expected"),
    [
        (12, 12, "active", "healthy"),
        (6, 12, "active", "wounded"),
        (3, 12, "active", "critical"),
        (0, 12, "down", "down"),
    ],
)
def test_injury_level_is_coarse(
    current_hp: int,
    max_hp: int,
    status: str,
    expected: str,
) -> None:
    assert injury_level(_enemy(current_hp=current_hp, max_hp=max_hp, combat_status=status)) == expected


def test_combatant_state_rejects_negative_mechanical_values() -> None:
    with pytest.raises(ValueError, match="HP"):
        _enemy(current_hp=-1)
    with pytest.raises(ValueError, match="armor_class"):
        _enemy(armor_class=-1)
