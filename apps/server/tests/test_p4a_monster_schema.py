from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.content.p4a_monsters import MonsterData


def _ref(index: str, name: str, route: str) -> dict[str, str]:
    return {"index": index, "name": name, "url": f"/api/2014/{route}/{index}"}


def _wolf() -> dict[str, object]:
    return {
        "index": "wolf",
        "name": "Wolf",
        "size": "Medium",
        "type": "beast",
        "alignment": "unaligned",
        "armor_class": [{"type": "natural", "value": 13}],
        "hit_points": 11,
        "hit_dice": "2d8",
        "hit_points_roll": "2d8+2",
        "speed": {"walk": "40 ft."},
        "strength": 12,
        "dexterity": 15,
        "constitution": 12,
        "intelligence": 3,
        "wisdom": 12,
        "charisma": 6,
        "proficiencies": [
            {"value": 3, "proficiency": _ref("skill-perception", "Skill: Perception", "proficiencies")}
        ],
        "damage_vulnerabilities": [],
        "damage_resistances": [],
        "damage_immunities": [],
        "condition_immunities": [],
        "senses": {"passive_perception": 13},
        "languages": "",
        "challenge_rating": 0.25,
        "proficiency_bonus": 2,
        "xp": 50,
        "special_abilities": [{"name": "Keen Hearing and Smell", "desc": "The wolf has advantage."}],
        "actions": [{
            "name": "Bite",
            "desc": "Melee Weapon Attack.",
            "attack_bonus": 4,
            "damage": [{
                "damage_type": _ref("piercing", "Piercing", "damage-types"),
                "damage_dice": "2d4+2",
            }],
            "dc": {
                "dc_type": _ref("str", "STR", "ability-scores"),
                "dc_value": 11,
                "success_type": "none",
            },
        }],
        "bonus_actions": [{
            "name": "Phase Step",
            "desc": "The wolf teleports 10 ft.",
            "usage": {"type": "per day", "times": 2},
        }],
        "url": "/api/2014/monsters/wolf",
    }


def test_monster_schema_preserves_structured_combat_fields() -> None:
    monster = MonsterData.model_validate(_wolf())
    assert monster.is_beast is True
    assert monster.armor_class[0].value == 13
    assert monster.actions is not None
    assert monster.actions[0].attack_bonus == 4
    assert monster.actions[0].damage is not None
    damage = monster.actions[0].damage[0]
    assert getattr(damage, "damage_dice") == "2d4+2"
    assert monster.actions[0].dc is not None
    assert monster.actions[0].dc.dc_value == 11
    assert monster.bonus_actions is not None
    assert monster.bonus_actions[0].name == "Phase Step"
    assert monster.bonus_actions[0].usage is not None
    assert monster.bonus_actions[0].usage.times == 2


def test_monster_schema_rejects_unknown_top_level_fields() -> None:
    payload = _wolf()
    payload["future_unreviewed_field"] = True
    with pytest.raises(ValidationError):
        MonsterData.model_validate(payload)


def test_monster_schema_rejects_duplicate_damage_traits() -> None:
    payload = _wolf()
    payload["damage_resistances"] = ["fire", "fire"]
    with pytest.raises(ValidationError, match="damage trait values must be unique"):
        MonsterData.model_validate(payload)
