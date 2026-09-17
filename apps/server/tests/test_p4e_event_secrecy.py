from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.dependencies import get_database_engine
from app.api.rooms.access import get_room_service
from app.api.rooms.dependencies import (
    get_combat_resolution_service,
    get_combat_service,
    get_table_event_service,
)
from app.domain.combat.attacks import AttackAdjudicationInput, AttackRequestInput
from app.domain.combat.event_projection import project_combat_event_payload
from app.domain.combat.resolution import DamageRollPart, DamageType
from app.domain.combat.semantic_hp import SemanticDamageInput
from app.domain.rooms.rolls import FormalRollInput, FormalRollSource
from app.domain.rooms.service import RoomService
from app.main import app
from app.persistence.combat.lifecycle import actor_binding
from app.persistence.rooms.repository import RoomRepository
import tests.test_p4c_adjudication as attack_support
import tests.test_p4c_core_rolls as core_support

HOSTILE_HP_KEYS = {
    "before", "after", "before_hp", "after_hp", "before_temp_hp", "after_temp_hp",
    "current_hp", "temp_hp", "max_hp", "target_ac", "affinities", "adjusted_by_type",
    "hp_lost", "temp_hp_absorbed", "resources",
}


def _last(events, kind: str):
    matches = [event for event in events if event.kind == kind]
    assert matches, f"no {kind} event"
    return matches[-1]


def _damage(semantic, actor, entry_id, amount: int, key: str):
    return semantic.apply_damage(
        actor,
        SemanticDamageInput(
            target_entry_id=entry_id,
            amount=amount,
            damage_type=DamageType.UNTYPED,
            idempotency_key=key,
        ),
    )


def test_player_event_stream_hides_monster_hp_but_keeps_damage_amount() -> None:
    table, _core, semantic, _char_id, monster_id = core_support._running_table()
    try:
        _damage(semantic, table.dm_actor, monster_id, 3, "dm-hits-monster")

        dm_payload = _last(
            table.events.list_after(table.dm_actor, after_seq=0, limit=200).events,
            "combat.damage_applied",
        ).payload
        assert dm_payload["after"]["current_hp"] == 6
        assert dm_payload["target_is_hostile"] is True

        player_payload = _last(
            table.events.list_after(table.player_actor, after_seq=0, limit=200).events,
            "combat.damage_applied",
        ).payload
        assert not HOSTILE_HP_KEYS & player_payload.keys()
        assert player_payload["amount"] == 3
        assert player_payload["target_injury_level"] == "healthy"
        assert player_payload["target_entry_id"] == str(monster_id)
    finally:
        table.engine.dispose()


def test_long_poll_path_projects_identically_to_list() -> None:
    import asyncio

    table, _core, semantic, _char_id, monster_id = core_support._running_table()
    try:
        _damage(semantic, table.dm_actor, monster_id, 4, "dm-hits-monster-poll")
        listed = _last(
            table.events.list_after(table.player_actor, after_seq=0, limit=200).events,
            "combat.damage_applied",
        )
        waited = asyncio.run(
            table.events.wait_after(table.player_actor, after_seq=listed.seq - 1, limit=50, timeout=0.1)
        )
        assert _last(waited.events, "combat.damage_applied").payload == listed.payload
    finally:
        table.engine.dispose()


def test_friendly_character_damage_stays_exact_for_player() -> None:
    table, _core, semantic, char_id, _monster_id = core_support._running_table()
    try:
        _damage(semantic, table.dm_actor, char_id, 2, "dm-hits-character")
        payload = _last(
            table.events.list_after(table.player_actor, after_seq=0, limit=200).events,
            "combat.damage_applied",
        ).payload
        assert payload["target_is_hostile"] is False
        assert payload["after"]["current_hp"] == payload["before"]["current_hp"] - 2
    finally:
        table.engine.dispose()


def test_semantic_damage_response_is_projected_for_player_but_not_dm() -> None:
    table, _core, semantic, _char_id, monster_id = core_support._running_table()
    try:
        # Only the DM may apply raw semantic damage to a Monster (P4-C); the
        # Player-facing projection of the same stored resolution is what a
        # Player sees when an attack of theirs lands on a hostile target.
        stored = semantic.repository.apply_damage(
            binding=actor_binding(table.dm_actor),
            combat_id=table.combat.get_active_combat(table.dm_actor).id,
            target_entry_id=monster_id,
            subject_seat_id=None,
            execution_mode="self",
            damage_parts=(DamageRollPart(damage_type=DamageType.UNTYPED, dice=(), flat_modifier=2),),
            critical=False,
            source_entry_id=None,
            idempotency_key="stored-hits-monster",
        )
        player_view = semantic._project_resolution(table.player_actor, stored)
        assert player_view.after_hp is None and player_view.before_hp is None
        assert player_view.amount == 2
        assert player_view.target_injury_level == "healthy"
        assert not HOSTILE_HP_KEYS & player_view.payload.keys()
        assert player_view.model_dump(mode="json", exclude_none=True).get("after_hp") is None

        dm_view = semantic._project_resolution(table.dm_actor, stored)
        assert dm_view.after_hp == 7
        assert dm_view.payload["after"]["current_hp"] == 7

        room_service = RoomService(RoomRepository(table.engine))
        app.dependency_overrides[get_database_engine] = lambda: table.engine
        app.dependency_overrides[get_room_service] = lambda: room_service
        app.dependency_overrides[get_combat_service] = lambda: table.combat
        app.dependency_overrides[get_table_event_service] = lambda: table.events
        app.dependency_overrides[get_combat_resolution_service] = lambda: semantic
        client = TestClient(app)
        url = (
            f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
            f"/sessions/{table.session_id}/combat/damage"
        )
        body = {
            "target_entry_id": str(monster_id),
            "amount": 1,
            "damage_type": "untyped",
            "idempotency_key": "rest-dm-hits-monster",
        }
        response = client.post(url, json=body, headers={"Authorization": f"Bearer {table.dm_token}"})
        assert response.status_code == 200, response.text
        assert response.json()["after_hp"] == 6
    finally:
        app.dependency_overrides.clear()
        table.engine.dispose()


def test_attack_result_hides_monster_ac_and_hp_from_player_but_not_dm() -> None:
    table, attacks, attacker_id, target_id, source_ref = attack_support._running_table()
    try:
        pending = attacks.request_attack(
            table.player_actor,
            AttackRequestInput(
                attacker_entry_id=attacker_id,
                target_entry_id=target_id,
                source_ref=source_ref,
                idempotency_key="secrecy-attack",
            ),
        )
        resumed = attacks.adjudicate_attack(
            table.dm_actor,
            AttackAdjudicationInput(action_id=pending.action_id, in_range=True, idempotency_key="secrecy-range"),
        )
        assert resumed.roll_request_id is not None
        player_result = attacks.complete_attack(
            table.player_actor,
            FormalRollInput(
                roll_request_id=resumed.roll_request_id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(20,),
                idempotency_key="secrecy-attack-roll",
            ),
        )
        assert player_result.hit is True
        assert player_result.target_ac is None
        assert player_result.after_hp is None
        assert player_result.target_injury_level is not None
        assert "target_ac" not in player_result.resolution_result["attack"]
        assert "after" not in player_result.resolution_result["damage"]

        # The DM replaying the same request gets the canonical, unredacted result.
        dm_result = attacks.complete_attack(
            table.dm_actor,
            FormalRollInput(
                roll_request_id=resumed.roll_request_id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(1,),
                idempotency_key="secrecy-attack-roll",
            ),
        )
        assert dm_result.target_ac == 12
        assert dm_result.after_hp is not None
        assert dm_result.resolution_result["attack"]["target_ac"] == 12

        # The attack lands on the table as a roll.resolved event carrying the
        # attack resolution; the Player copy is projected the same way.
        player_event = _last(
            table.events.list_after(table.player_actor, after_seq=0, limit=200).events,
            "roll.resolved",
        ).payload
        assert "target_ac" not in player_event["attack_resolution"]["attack"]
        assert "after" not in player_event["attack_resolution"]["damage"]
        assert player_event["attack_resolution"]["attack"]["hit"] is True
        dm_event = _last(
            table.events.list_after(table.dm_actor, after_seq=0, limit=200).events,
            "roll.resolved",
        ).payload
        assert dm_event["attack_resolution"]["attack"]["target_ac"] == 12
    finally:
        table.engine.dispose()


def test_hostile_caster_spell_payload_hides_dc_and_modifier() -> None:
    payload = {
        "spell_ref": "srd5.1:spell:fire-bolt",
        "spell_level": 0,
        "cast_mode": "attack",
        "caster_is_hostile": True,
        "target_is_hostile": False,
        "save_dc": 15,
        "attack_modifier": 6,
        "slot_level": 3,
        "roll": {"total": 18, "modifier": 6, "raw_dice": [12]},
        "target_current_hp": 4,
    }
    projected = project_combat_event_payload("combat.spell_cast_resolved", payload, audience="player")
    assert projected["spell_ref"] == "srd5.1:spell:fire-bolt"
    assert projected["cast_mode"] == "attack"
    assert "save_dc" not in projected and "attack_modifier" not in projected
    assert "modifier" not in projected["roll"] and projected["roll"]["total"] == 18
    # The Character target is friendly, so its HP stays visible.
    assert projected["target_current_hp"] == 4
    assert project_combat_event_payload("combat.spell_cast_resolved", payload, audience="dm") == payload


def test_non_combat_payloads_are_never_touched() -> None:
    payload = {"text": "hello", "current_hp": 3, "target_is_hostile": True}
    assert project_combat_event_payload("chat.dialogue", payload, audience="player") == payload
