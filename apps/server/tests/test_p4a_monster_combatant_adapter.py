from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import create_engine, insert

from app.db import metadata
from app.domain.combat import project_combatant
from app.persistence.combat.combatants import MonsterRevealState, monster_instance_to_combatant
from app.persistence.combat.repository import MonsterRepository
from app.persistence.combat.tables import monster_instances, monster_templates
from app.persistence.rooms.tables import campaigns, rooms


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
                code="ADAPTER",
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


def test_monster_instance_adapter_preserves_dm_mechanics_and_visibility_partition() -> None:
    repository, engine, campaign_id = _repository()
    try:
        monster = repository.create_instance(
            campaign_id=campaign_id,
            name="Hidden Mage",
            rules_snapshot={
                "armor_class": 15,
                "max_hp": 44,
                "speed": {"walk": "30 ft."},
                "description": "A robed enemy.",
                "traits": [{"name": "Arcane Ward"}],
                "actions": [{"name": "Staff"}],
                "bonus_actions": [{"name": "Misty Step"}],
                "reactions": [{"name": "Shield"}],
            },
            current_hp=19,
            temp_hp=4,
            conditions=["prone", {"name": "secret-mark", "visibility": "hidden"}],
            effects=[{"name": "bless", "visibility": "public"}, {"name": "doom", "visibility": "hidden"}],
            initiative=14,
            reaction_available=False,
            resources={"spell_slots": {"1": 2}},
            position_note="upper balcony",
        )
        state = monster_instance_to_combatant(monster)
        dm = project_combatant(state, audience="dm", enemy=True)
        assert dm is not None
        assert dm["current_hp"] == 19
        assert dm["temp_hp"] == 4
        assert dm["bonus_actions"] == [{"name": "Misty Step"}]
        assert dm["resources"] == {"spell_slots": {"1": 2}}
        assert set(dm["conditions"]) == {"prone", "secret-mark"}
        assert set(dm["effects"]) == {"bless", "doom"}
    finally:
        engine.dispose()


def test_quick_enemy_attack_reaches_canonical_combatant_dm_view() -> None:
    repository, engine, campaign_id = _repository()
    try:
        monster = repository.create_quick_enemy(
            campaign_id=campaign_id,
            name="Club Guard",
            armor_class=13,
            max_hp=11,
            speed={"walk": "30 ft."},
            attack={"name": "Club", "attack_bonus": 4, "damage": "1d6+2"},
        )
        state = monster_instance_to_combatant(monster)
        assert len(state.actions) == 1
        action = state.actions[0]
        assert action["name"] == "Club"
        assert action["kind"] == "attack"
        assert action["attack_bonus"] == 4
        assert action["damage_parts"] == [{"dice": "1d6+2", "damage_type": None}]

        dm = project_combatant(state, audience="dm", enemy=True)
        assert dm is not None
        assert dm["actions"][0]["name"] == "Club"
        assert dm["actions"][0]["attack_bonus"] == 4
        assert dm["actions"][0]["damage_parts"][0]["dice"] == "1d6+2"
    finally:
        engine.dispose()


def test_adapter_and_projection_keep_enemy_private_state_server_side() -> None:
    repository, engine, campaign_id = _repository()
    try:
        monster = repository.create_instance(
            campaign_id=campaign_id,
            name="Hidden Mage",
            rules_snapshot={
                "armor_class": 15,
                "max_hp": 44,
                "speed": {"walk": "30 ft."},
                "description": "A robed enemy.",
                "traits": [{"name": "Arcane Ward"}],
            },
            current_hp=19,
            conditions=["prone", {"name": "secret-mark", "visibility": "hidden"}],
            resources={"spell_slots": {"1": 2}},
            reaction_available=False,
            position_note="upper balcony",
        )
        state = monster_instance_to_combatant(
            monster,
            reveals=MonsterRevealState(armor_class=True, description=True),
        )
        player = project_combatant(state, audience="player", enemy=True)
        assert player is not None
        assert player["armor_class"] == 15
        assert player["description"] == "A robed enemy."
        assert player["conditions"] == ["prone"]
        assert "current_hp" not in player
        assert "max_hp" not in player
        assert "resources" not in player
        assert "reaction_available" not in player
        assert "traits" not in player
        assert "position_note" not in player
    finally:
        engine.dispose()


def test_structured_visibility_defaults_to_hidden() -> None:
    repository, engine, campaign_id = _repository()
    try:
        monster = repository.create_instance(
            campaign_id=campaign_id,
            name="Guard",
            rules_snapshot={
                "armor_class": 13,
                "max_hp": 11,
                "speed": {"walk": "30 ft."},
            },
            conditions=[{"name": "dm-only-without-flag"}],
            effects=[{"name": "explicit-public", "visibility": "public"}],
        )
        state = monster_instance_to_combatant(monster)
        player = project_combatant(state, audience="player", enemy=True)
        assert player is not None
        assert player["conditions"] == []
        assert player["effects"] == ["explicit-public"]
        dm = project_combatant(state, audience="dm", enemy=True)
        assert dm is not None
        assert dm["conditions"] == ["dm-only-without-flag"]
    finally:
        engine.dispose()


def test_position_note_requires_its_own_reveal_flag() -> None:
    repository, engine, campaign_id = _repository()
    try:
        monster = repository.create_quick_enemy(
            campaign_id=campaign_id,
            name="Guard",
            armor_class=13,
            max_hp=11,
            speed={"walk": "30 ft."},
            position_note="behind the gate",
        )
        hidden_note = project_combatant(
            monster_instance_to_combatant(monster),
            audience="player",
            enemy=True,
        )
        assert hidden_note is not None and "position_note" not in hidden_note
        revealed_note = project_combatant(
            monster_instance_to_combatant(
                monster,
                reveals=MonsterRevealState(position_note=True),
            ),
            audience="player",
            enemy=True,
        )
        assert revealed_note is not None
        assert revealed_note["position_note"] == "behind the gate"
    finally:
        engine.dispose()
