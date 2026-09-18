from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, insert

from app.db import metadata
from app.domain.combat.monster_instances import QuickEnemyAttackInput
from app.persistence.combat.repository import MonsterPersistenceError, MonsterRepository
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
                code="P4ATEST",
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


def test_quick_enemy_persists_minimum_rules_and_structured_canonical_action() -> None:
    repository, engine, campaign_id = _repository()
    try:
        enemy = repository.create_quick_enemy(
            campaign_id=campaign_id,
            name="Bandit Lookout",
            armor_class=12,
            max_hp=11,
            speed={"walk": "30 ft."},
            attack={"name": "Scimitar", "attack_bonus": 3, "damage": "1d6+1"},
            position_note="near the stairs",
        )
        assert enemy.template_key is None
        assert enemy.custom_template_id is None
        assert enemy.current_hp == 11
        assert enemy.rules_snapshot["armor_class"] == 12
        assert "attacks" not in enemy.rules_snapshot
        action = enemy.rules_snapshot["actions"][0]
        assert action["name"] == "Scimitar"
        assert action["kind"] == "attack"
        assert action["attack_kind"] == "melee_weapon"
        assert action["attack_bonus"] == 3
        assert action["damage_parts"] == [{"dice": "1d6+1", "damage_type": None}]
        assert action["automation_level"] == "structured"

        updated = repository.update_live_state(
            enemy.id,
            current_hp=4,
            temp_hp=2,
            conditions=["poisoned"],
            initiative=17,
            reaction_available=False,
            resources={"recharge": {"breath": False}},
        )
        assert updated.current_hp == 4
        assert updated.temp_hp == 2
        assert updated.conditions == ["poisoned"]
        assert updated.initiative == 17
        assert updated.reaction_available is False
    finally:
        engine.dispose()


def test_quick_enemy_preserves_explicit_ranged_attack_kind() -> None:
    repository, engine, campaign_id = _repository()
    try:
        enemy = repository.create_quick_enemy(
            campaign_id=campaign_id,
            name="Archer",
            armor_class=12,
            max_hp=9,
            speed={"walk": "30 ft."},
            attack={
                "name": "Shortbow",
                "attack_kind": "ranged_weapon",
                "attack_bonus": 4,
                "damage": "1d6+2",
            },
        )
        action = enemy.rules_snapshot["actions"][0]
        assert action["attack_kind"] == "ranged_weapon"
        assert action["automation_level"] == "structured"
    finally:
        engine.dispose()


def test_quick_enemy_maps_melee_attack_kind_alias() -> None:
    # The alias lives in the shared input model (REST + MCP); the repository only
    # sees the validated dump and defaults a missing kind to melee_weapon.
    assert (
        QuickEnemyAttackInput(name="Scimitar", damage="1d6+2", attack_kind="melee").attack_kind
        == "melee_weapon"
    )
    assert (
        QuickEnemyAttackInput(name="Bow", damage="1d6", attack_kind="ranged").attack_kind
        == "ranged_weapon"
    )


def test_quick_enemy_damage_with_type_persists_split_parts() -> None:
    repository, engine, campaign_id = _repository()
    try:
        enemy = repository.create_quick_enemy(
            campaign_id=campaign_id,
            name="Scimitar Bandit",
            armor_class=12,
            max_hp=11,
            speed={"walk": "30 ft."},
            attack={
                "name": "Scimitar",
                "attack_bonus": 4,
                "damage": "1d6+2 slashing",
            },
        )
        action = enemy.rules_snapshot["actions"][0]
        assert action["damage_parts"] == [{"dice": "1d6+2", "damage_type": "slashing"}]
    finally:
        engine.dispose()


def test_goblin_template_instances_keep_independent_live_state() -> None:
    repository, engine, campaign_id = _repository()
    try:
        rules = {
            "armor_class": 15,
            "max_hp": 7,
            "speed": {"walk": "30 ft."},
            "actions": [
                {
                    "name": "Scimitar",
                    "kind": "attack",
                    "attack_kind": "melee_weapon",
                    "attack_bonus": 4,
                    "damage_parts": [{"dice": "1d6+2", "damage_type": "slashing"}],
                    "automation_level": "structured",
                }
            ],
        }
        template = repository.create_template(
            campaign_id=campaign_id,
            name="Goblin",
            source_key="srd5.1:monster:goblin",
            rules=rules,
        )
        instance_a = repository.create_instance_from_template(template.id, name="Goblin A")
        instance_b = repository.create_instance_from_template(template.id, name="Goblin B")

        changed_a = repository.update_live_state(
            instance_a.id,
            current_hp=2,
            initiative=18,
            reaction_available=False,
        )
        unchanged_b = repository.get_instance(instance_b.id)
        unchanged_template = repository.get_template(template.id)

        assert changed_a.current_hp == 2
        assert changed_a.initiative == 18
        assert changed_a.reaction_available is False
        assert unchanged_b is not None
        assert unchanged_b.current_hp == 7
        assert unchanged_b.initiative is None
        assert unchanged_b.reaction_available is True
        assert unchanged_b.rules_snapshot == rules
        assert unchanged_template is not None
        assert unchanged_template.rules == rules
    finally:
        engine.dispose()


def test_save_as_template_copies_rules_but_not_live_state() -> None:
    repository, engine, campaign_id = _repository()
    try:
        enemy = repository.create_quick_enemy(
            campaign_id=campaign_id,
            name="Clockwork Guard",
            armor_class=16,
            max_hp=24,
            speed={"walk": "25 ft."},
        )
        repository.update_live_state(
            enemy.id,
            current_hp=3,
            initiative=21,
            reaction_available=False,
            conditions=["restrained"],
            resources={"spent": 2},
        )
        template = repository.save_instance_as_template(enemy.id)
        assert template.rules == {
            "armor_class": 16,
            "max_hp": 24,
            "speed": {"walk": "25 ft."},
        }
        spawned = repository.create_instance_from_template(template.id)
        assert spawned.current_hp == 24
        assert spawned.initiative is None
        assert spawned.reaction_available is True
        assert spawned.conditions == []
        assert spawned.resources == {}
        assert spawned.custom_template_id == template.id
    finally:
        engine.dispose()


def test_instance_snapshot_is_immutable_when_template_rules_change() -> None:
    repository, engine, campaign_id = _repository()
    try:
        rules = {"armor_class": 13, "max_hp": 9, "speed": {"walk": "30 ft."}}
        template = repository.create_template(campaign_id=campaign_id, name="Scout", rules=rules)
        instance = repository.create_instance_from_template(template.id)
        rules["max_hp"] = 999
        assert repository.get_instance(instance.id).rules_snapshot["max_hp"] == 9
    finally:
        engine.dispose()


def test_list_instances_is_campaign_scoped() -> None:
    repository, engine, campaign_id = _repository()
    try:
        other_campaign = uuid4()
        with engine.connect() as connection:
            room_id = connection.execute(rooms.select()).mappings().one()["id"]
        now = datetime(2026, 9, 14, tzinfo=timezone.utc)
        with engine.begin() as connection:
            connection.execute(
                insert(campaigns).values(
                    id=other_campaign,
                    room_id=room_id,
                    name="Other",
                    ruleset="dnd5e-2014",
                    status="active",
                    created_at=now,
                    updated_at=now,
                )
            )
        first = repository.create_quick_enemy(
            campaign_id=campaign_id,
            name="First",
            armor_class=10,
            max_hp=5,
            speed={"walk": "30 ft."},
        )
        repository.create_quick_enemy(
            campaign_id=other_campaign,
            name="Other",
            armor_class=10,
            max_hp=5,
            speed={"walk": "30 ft."},
        )
        assert [item.id for item in repository.list_instances(campaign_id)] == [first.id]
    finally:
        engine.dispose()


def test_rules_and_template_source_validation() -> None:
    repository, engine, campaign_id = _repository()
    try:
        with pytest.raises(MonsterPersistenceError, match="missing required fields"):
            repository.create_instance(
                campaign_id=campaign_id,
                name="Broken",
                rules_snapshot={"max_hp": 1},
            )
        with pytest.raises(MonsterPersistenceError, match="only one template source"):
            repository.create_instance(
                campaign_id=campaign_id,
                name="Broken",
                rules_snapshot={"armor_class": 10, "max_hp": 1, "speed": {"walk": "30 ft."}},
                template_key="srd5.1:monster:goblin",
                custom_template_id=uuid4(),
            )
    finally:
        engine.dispose()


def test_quick_enemy_rejects_malformed_attack() -> None:
    repository, engine, campaign_id = _repository()
    try:
        with pytest.raises(MonsterPersistenceError, match="invalid quick enemy attack"):
            repository.create_quick_enemy(
                campaign_id=campaign_id,
                name="Broken",
                armor_class=10,
                max_hp=1,
                speed={"walk": "30 ft."},
                attack={"attack_bonus": 4, "damage": "1d6+2"},
            )
    finally:
        engine.dispose()


def test_custom_template_cannot_cross_campaign_boundary() -> None:
    repository, engine, campaign_id = _repository()
    try:
        template = repository.create_template(
            campaign_id=campaign_id,
            name="Campaign One",
            rules={"armor_class": 12, "max_hp": 8, "speed": {"walk": "30 ft."}},
        )
        other_campaign = uuid4()
        with engine.connect() as connection:
            room_id = connection.execute(rooms.select()).mappings().one()["id"]
        now = datetime(2026, 9, 14, tzinfo=timezone.utc)
        with engine.begin() as connection:
            connection.execute(
                insert(campaigns).values(
                    id=other_campaign,
                    room_id=room_id,
                    name="Other",
                    ruleset="dnd5e-2014",
                    status="active",
                    created_at=now,
                    updated_at=now,
                )
            )
        with pytest.raises(MonsterPersistenceError, match="same campaign"):
            repository.create_instance(
                campaign_id=other_campaign,
                name="Leak",
                rules_snapshot=template.rules,
                custom_template_id=template.id,
            )
    finally:
        engine.dispose()
