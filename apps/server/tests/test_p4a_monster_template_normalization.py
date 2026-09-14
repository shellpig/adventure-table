from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import create_engine, insert

from app.content.p4a_combat_templates import (
    MonsterTemplateNormalizationError,
    monster_to_reusable_rules,
)
from app.db import metadata
from app.persistence.combat.repository import MonsterRepository
from app.persistence.combat.tables import monster_instances, monster_templates
from app.persistence.rooms.tables import campaigns, rooms


class FakeMonster:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def model_dump(self, *, mode: str, exclude_none: bool) -> dict[str, object]:
        assert mode == "python"
        assert exclude_none is True
        return self.payload


def _payload() -> dict[str, object]:
    return {
        "index": "arcane-beast",
        "name": "Arcane Beast",
        "desc": "A test monster.",
        "size": "Large",
        "type": "beast",
        "subtype": "magical",
        "alignment": "unaligned",
        "armor_class": [
            {"type": "natural", "value": 15},
            {"type": "condition", "value": 18, "desc": "while warded"},
        ],
        "hit_points": 52,
        "hit_dice": "7d10",
        "hit_points_roll": "7d10+14",
        "speed": {"walk": "40 ft.", "climb": "20 ft."},
        "strength": 18,
        "dexterity": 14,
        "constitution": 15,
        "intelligence": 8,
        "wisdom": 12,
        "charisma": 10,
        "proficiencies": [{"value": 4, "proficiency": {"index": "skill-perception"}}],
        "damage_vulnerabilities": [],
        "damage_resistances": ["force"],
        "damage_immunities": [],
        "condition_immunities": [],
        "senses": {"passive_perception": 13, "darkvision": "60 ft."},
        "languages": "understands Common",
        "challenge_rating": 3,
        "proficiency_bonus": 2,
        "xp": 700,
        "special_abilities": [
            {
                "name": "Spellcasting",
                "spellcasting": {
                    "ability": {"index": "wis"},
                    "dc": 13,
                    "modifier": 5,
                    "slots": {"1": 3},
                    "spells": [{"name": "Bless", "level": 1, "url": "/api/2014/spells/bless"}],
                },
            },
            {"name": "Recharge Ward", "usage": {"type": "recharge on roll", "dice": "1d6", "min_value": 5}},
        ],
        "actions": [
            {
                "name": "Bite",
                "attack_bonus": 6,
                "dc": {"dc_type": {"index": "str"}, "dc_value": 14, "success_type": "none"},
                "damage": [{"damage_type": {"index": "piercing"}, "damage_dice": "2d8+4"}],
            }
        ],
        "bonus_actions": [{"name": "Phase Step", "usage": {"type": "per day", "times": 2}}],
        "reactions": [{"name": "Arcane Deflection", "desc": "Raises its ward."}],
        "legendary_actions": [{"name": "Detect", "desc": "Makes a Perception check."}],
        "forms": [
            {
                "index": "arcane-beast-alpha",
                "name": "Arcane Beast Alpha",
                "url": "/api/2014/monsters/arcane-beast-alpha",
            }
        ],
        "image": "/api/images/monsters/arcane-beast.png",
        "url": "/api/2014/monsters/arcane-beast",
    }


def _repository() -> tuple[MonsterRepository, object, object]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine, tables=[rooms, campaigns, monster_templates, monster_instances])
    room_id = uuid4()
    campaign_id = uuid4()
    now = datetime(2026, 9, 14, tzinfo=timezone.utc)
    with engine.begin() as connection:
        connection.execute(
            insert(rooms).values(
                id=room_id,
                code="NORMALIZE",
                name="P4-A",
                password_salt=b"0" * 32,
                password_hash=b"1" * 64,
                owner_key_hash=b"2" * 32,
                dm_key_hash=b"3" * 32,
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            insert(campaigns).values(
                id=campaign_id,
                room_id=room_id,
                name="Campaign",
                ruleset="dnd5e-2014",
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
    return MonsterRepository(engine), engine, campaign_id


def test_normalizer_preserves_structured_monster_mechanics() -> None:
    rules = monster_to_reusable_rules(FakeMonster(_payload()))
    assert rules["armor_class"] == 15
    assert rules["armor_class_options"][1]["value"] == 18
    assert rules["max_hp"] == 52
    assert rules["ability_scores"]["strength"] == 18
    assert rules["traits"][0]["spellcasting"]["slots"] == {"1": 3}
    assert rules["traits"][1]["usage"]["min_value"] == 5
    assert rules["actions"][0]["dc"]["dc_value"] == 14
    assert rules["actions"][0]["damage"][0]["damage_dice"] == "2d8+4"
    assert rules["bonus_actions"][0]["name"] == "Phase Step"
    assert rules["reactions"][0]["name"] == "Arcane Deflection"
    assert rules["legendary_actions"][0]["name"] == "Detect"


def test_normalizer_copies_reusable_rules_and_introduces_no_live_state() -> None:
    payload = _payload()
    rules = monster_to_reusable_rules(FakeMonster(payload))
    original_rules = deepcopy(rules)
    payload["armor_class"][0]["value"] = 99  # type: ignore[index]
    payload["actions"][0]["name"] = "Changed"  # type: ignore[index]
    assert rules == original_rules
    for forbidden in (
        "current_hp",
        "temp_hp",
        "initiative",
        "reaction_available",
        "combat_status",
        "conditions",
        "effects",
        "resources",
        "position_note",
        "visibility",
    ):
        assert forbidden not in rules


def test_normalized_rules_are_accepted_by_monster_repository() -> None:
    repository, engine, campaign_id = _repository()
    try:
        rules = monster_to_reusable_rules(FakeMonster(_payload()))
        instance = repository.create_instance(
            campaign_id=campaign_id,
            name="Arcane Beast",
            template_key="srd5.1:monster:arcane-beast",
            rules_snapshot=rules,
        )
        assert instance.current_hp == 52
        assert instance.rules_snapshot["armor_class"] == 15
        assert instance.rules_snapshot["bonus_actions"][0]["name"] == "Phase Step"
    finally:
        engine.dispose()


def test_normalizer_rejects_missing_default_ac() -> None:
    payload = _payload()
    payload["armor_class"] = []
    try:
        monster_to_reusable_rules(FakeMonster(payload))
    except MonsterTemplateNormalizationError as exc:
        assert "armor_class" in str(exc)
    else:
        raise AssertionError("missing armor class must fail")
