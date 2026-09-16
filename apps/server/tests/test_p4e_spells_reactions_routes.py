from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select, update

from app.api.dependencies import get_database_engine
from app.api.rooms.access import get_room_service
from app.api.rooms.dependencies import (
    get_combat_concentration_service,
    get_combat_reaction_service,
    get_combat_service,
    get_combat_spell_service,
    get_room_workspace_service,
    get_table_event_service,
)
from app.content import load_default_content_registry
from app.content.p4a_combat_templates import monster_to_reusable_rules
from app.content.p4a_monsters import MonsterData
from app.domain.character.schemas import (
    CharacterBuild,
    CharacterConcentrationState,
    CharacterState,
    PersistentTemporaryEffect,
    ResourceCounter,
    SpellAccessEntry,
    SpellResourcePool,
    SpellSlotCapacity,
    SpellcastingProfile,
)
from app.domain.combat.concentration import CombatConcentrationService
from app.domain.combat.initiative import FinalizeInitiativeInput, RequestInitiativeInput
from app.domain.combat.lifecycle import AddMonsterInput, StartCombatInput
from app.domain.combat.reaction_service import CombatReactionService
from app.domain.combat.resolution import DamageRollPart, DamageType, RollMode
from app.domain.combat.spell_resolver import SaveDamageMode, SpellCastMode
from app.domain.combat.spell_service import CombatSpellService
from app.domain.rooms.rolls import FormalRollInput, FormalRollSource
from app.domain.rooms.service import RoomService
from app.main import app
from app.persistence.characters import character_states, character_versions, characters
from app.persistence.combat.concentration import CombatConcentrationRepository
from app.persistence.combat.reactions import CombatReactionRepository
from app.persistence.combat.spells import CombatSpellRepository
from app.persistence.combat.tables import combat_entries, combats, monster_instances
from app.persistence.rooms.p3c_runtime import roll_requests
from app.persistence.rooms.repository import RoomRepository
import tests.test_p4b_combat_lifecycle as support


def _mage_rules_and_resources() -> tuple[dict[str, Any], dict[str, int]]:
    registry = load_default_content_registry()
    mage_entry = registry.get("srd5.1:monster:mage")
    rules = monster_to_reusable_rules(MonsterData.model_validate(mage_entry.data))
    slots = rules["traits"][0]["spellcasting"]["slots"]
    resources = {f"spell_slot:{level}": count for level, count in slots.items()}
    return rules, resources


def _enable_wizard_spells(table) -> None:
    with table.engine.begin() as connection:
        version_id = connection.scalar(
            select(characters.c.current_version_id).where(
                characters.c.id == table.character_id
            )
        )
        build_row = connection.execute(
            select(character_versions.c.build_payload).where(
                character_versions.c.id == version_id
            )
        ).mappings().one()
        build = CharacterBuild.model_validate(build_row["build_payload"])
        profile = SpellcastingProfile(
            profile_id="wizard",
            source_type="class",
            source_key="srd5.1:class:wizard",
            class_ref="srd5.1:class:wizard",
            ability="intelligence",
            access_model="spellbook",
            resource_pool_type="normal_multiclass_slots",
            max_spell_level=3,
            prepared_limit=8,
        )
        pool = SpellResourcePool(
            pool_id="normal_multiclass",
            pool_type="normal_multiclass_slots",
            slots=(
                SpellSlotCapacity(level=1, capacity=4),
                SpellSlotCapacity(level=2, capacity=3),
                SpellSlotCapacity(level=3, capacity=2),
            ),
        )
        hold_person_access = SpellAccessEntry(
            entry_id="wizard:hold-person",
            spell_key="srd5.1:spell:hold-person",
            source_type="class",
            source_key="srd5.1:class:wizard",
            access_type="spellbook",
        )
        fireball_access = SpellAccessEntry(
            entry_id="wizard:fireball",
            spell_key="srd5.1:spell:fireball",
            source_type="class",
            source_key="srd5.1:class:wizard",
            access_type="spellbook",
        )
        magic_missile_access = SpellAccessEntry(
            entry_id="wizard:magic-missile",
            spell_key="srd5.1:spell:magic-missile",
            source_type="class",
            source_key="srd5.1:class:wizard",
            access_type="spellbook",
        )
        existing_entry_ids = {item.entry_id for item in build.spell_access_entries}
        new_entries = [
            item for item in (hold_person_access, fireball_access, magic_missile_access)
            if item.entry_id not in existing_entry_ids
        ]
        next_build = build.model_copy(
            update={
                "spellcasting_profiles": (profile,),
                "spell_resource_pools": (pool,),
                "spell_access_entries": (
                    *build.spell_access_entries,
                    *new_entries,
                ),
            },
            deep=True,
        )
        connection.execute(
            update(character_versions)
            .where(character_versions.c.id == version_id)
            .values(build_payload=next_build.model_dump(mode="json"))
        )
        state_row = connection.execute(
            select(character_states.c.state_payload, character_states.c.state_revision).where(
                character_states.c.character_id == table.character_id
            )
        ).mappings().one()
        state = CharacterState.model_validate(state_row["state_payload"])
        prepared = list(state.prepared_spell_entry_ids)
        for eid in ["wizard:hold-person", "wizard:fireball", "wizard:magic-missile"]:
            if eid not in prepared:
                prepared.append(eid)
        next_state = state.model_copy(
            update={
                "prepared_spell_entry_ids": prepared,
                "spell_slots": {
                    1: ResourceCounter(used=0, remaining=4),
                    2: ResourceCounter(used=0, remaining=3),
                    3: ResourceCounter(used=0, remaining=2),
                },
            },
            deep=True,
        )
        connection.execute(
            update(character_states)
            .where(character_states.c.character_id == table.character_id)
            .values(
                state_payload=next_state.model_dump(mode="json"),
                state_revision=int(state_row["state_revision"]) + 1,
            )
        )


@pytest.fixture
def combat_routes_fixture():
    table = support._setup()
    try:
        _enable_wizard_spells(table)
        table.combat.start_quick_combat(
            table.dm_actor,
            StartCombatInput(idempotency_key="routes-test-start"),
        )
        rules, resources = _mage_rules_and_resources()
        mage_instance = table.monsters.create_instance(
            campaign_id=table.campaign_id,
            name="SRD Mage",
            rules_snapshot=rules,
            resources=resources,
        )
        table.combat.add_monster(
            table.dm_actor,
            AddMonsterInput(
                monster_instance_id=mage_instance.id,
                idempotency_key="routes-add-mage",
            ),
        )
        requested = table.initiative.request_initiative(
            table.dm_actor,
            RequestInitiativeInput(idempotency_key="routes-test-init"),
        )
        for index, request in enumerate(requested.requests):
            actor = table.player_actor if request.target_seat_id is not None else table.dm_actor
            raw = 20 if request.target_seat_id is not None else 1
            table.initiative.complete_initiative(
                actor,
                FormalRollInput(
                    roll_request_id=request.id,
                    source=FormalRollSource.PHYSICAL,
                    raw_dice=(raw,),
                    idempotency_key=f"routes-init-roll-{index}",
                ),
            )

        with table.engine.connect() as connection:
            rows = connection.execute(
                select(
                    combat_entries.c.id,
                    combat_entries.c.character_id,
                    combat_entries.c.monster_instance_id,
                ).where(
                    combat_entries.c.combat_id
                    == table.combat.get_active_combat(table.dm_actor).id
                )
            ).mappings().all()
        mage_entry = next(r for r in rows if r["monster_instance_id"] == mage_instance.id)
        char_entry = next(r for r in rows if r["character_id"] == table.character_id)

        # Character first in turn order
        table.initiative.finalize_initiative(
            table.dm_actor,
            FinalizeInitiativeInput(
                ordered_entry_ids=(char_entry["id"], mage_entry["id"]),
                idempotency_key="routes-finalize-init",
            ),
        )

        room_service = RoomService(RoomRepository(table.engine))
        spell_repo = CombatSpellRepository(table.engine, table.events.repository)
        reaction_repo = CombatReactionRepository(table.engine, table.events.repository)
        conc_repo = CombatConcentrationRepository(table.engine, table.events.repository)

        spell_service = CombatSpellService(
            repository=spell_repo,
            combat_repository=table.combat.repository,
            combat_service=table.combat,
            table_event_service=table.events,
            monster_repository=table.monsters,
            character_repository=table.combat.character_repository,
            roll_service=table.rolls,
            registry=load_default_content_registry(),
        )
        reaction_service = CombatReactionService(
            repository=reaction_repo,
            combat_repository=table.combat.repository,
            combat_service=table.combat,
            table_event_service=table.events,
        )
        conc_service = CombatConcentrationService(
            repository=conc_repo,
            combat_repository=table.combat.repository,
            monster_repository=table.monsters,
            roll_service=table.rolls,
            table_event_service=table.events,
        )

        app.dependency_overrides[get_database_engine] = lambda: table.engine
        app.dependency_overrides[get_room_service] = lambda: room_service
        app.dependency_overrides[get_combat_service] = lambda: table.combat
        app.dependency_overrides[get_table_event_service] = lambda: table.events
        app.dependency_overrides[get_combat_spell_service] = lambda: spell_service
        app.dependency_overrides[get_combat_reaction_service] = lambda: reaction_service
        app.dependency_overrides[get_combat_concentration_service] = lambda: conc_service

        yield table, char_entry["id"], mage_entry["id"], mage_instance.id
    finally:
        app.dependency_overrides.clear()
        table.engine.dispose()


def test_character_cast_spell_via_rest_and_player_redaction(combat_routes_fixture) -> None:
    table, char_entry_id, mage_entry_id, _ = combat_routes_fixture
    client = TestClient(app)
    url = (
        f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
        f"/sessions/{table.session_id}/combat/spells/cast"
    )

    # Player casts single-target save spell (hold-person) on hostile mage
    # Rule parameters (DC, save modifier, d20, concentration) are all derived by server!
    cast_payload = {
        "caster_entry_id": str(char_entry_id),
        "target_entry_id": str(mage_entry_id),
        "spell_ref": "srd5.1:spell:hold-person",
        "slot_level": 2,
        "idempotency_key": "routes-cast-hp-1",
    }
    response = client.post(
        url,
        json=cast_payload,
        headers={"Authorization": f"Bearer {table.player_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "resolved"
    assert data["spell_ref"] == "srd5.1:spell:hold-person"
    assert data["cast_mode"] == "save"
    res = data["resolution_result"]
    assert res is not None
    # Player audience: hostile target exact HP should be omitted
    assert "target_hp" not in res or res.get("target_hp") is None
    assert res["concentration_started"] is True


def test_cast_spell_rejects_raw_rule_fields_with_422(combat_routes_fixture) -> None:
    table, char_entry_id, mage_entry_id, _ = combat_routes_fixture
    client = TestClient(app)
    url = (
        f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
        f"/sessions/{table.session_id}/combat/spells/cast"
    )

    # Attempting to supply raw rule overrides like save_dc or attack_modifier is rejected with 422
    for forbidden_field in ("save_dc", "attack_modifier", "target_ac", "damage_parts"):
        payload = {
            "caster_entry_id": str(char_entry_id),
            "target_entry_id": str(mage_entry_id),
            "spell_ref": "srd5.1:spell:hold-person",
            "slot_level": 2,
            forbidden_field: 15,
        }
        resp = client.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {table.player_token}"},
        )
        assert resp.status_code == 422, f"Expected 422 when providing {forbidden_field}"


def test_monster_cast_spell_via_rest_and_authorization(combat_routes_fixture) -> None:
    table, char_entry_id, mage_entry_id, _ = combat_routes_fixture
    client = TestClient(app)

    # Advance turn to mage so mage can cast
    table.combat.advance_turn(table.dm_actor)

    url = (
        f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
        f"/sessions/{table.session_id}/combat/spells/cast"
    )

    # Clean payload without raw rule overrides
    cast_payload = {
        "caster_entry_id": str(mage_entry_id),
        "target_entry_id": str(char_entry_id),
        "spell_ref": "srd5.1:spell:fire-bolt",
        "idempotency_key": "routes-mage-firebolt-1",
    }
    forbidden_resp = client.post(
        url,
        json=cast_payload,
        headers={"Authorization": f"Bearer {table.player_token}"},
    )
    assert forbidden_resp.status_code == 403

    # DM casts for monster -> 200 OK
    dm_resp = client.post(
        url,
        json=cast_payload,
        headers={"Authorization": f"Bearer {table.dm_token}"},
    )
    assert dm_resp.status_code == 200
    dm_data = dm_resp.json()
    assert dm_data["status"] == "resolved"
    assert dm_data["spell_ref"] == "srd5.1:spell:fire-bolt"
    assert dm_data["cast_mode"] == "attack"
    assert dm_data["resolution_result"] is not None


def test_aoe_propose_and_resolve_via_rest(combat_routes_fixture) -> None:
    table, char_entry_id, mage_entry_id, _ = combat_routes_fixture
    client = TestClient(app)

    propose_url = (
        f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
        f"/sessions/{table.session_id}/combat/spells/aoe/propose"
    )
    resolve_url = (
        f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
        f"/sessions/{table.session_id}/combat/spells/aoe/resolve"
    )

    # 1. Propose AoE by Player - clean payload without client-specified DC
    propose_payload = {
        "caster_entry_id": str(char_entry_id),
        "spell_ref": "srd5.1:spell:fireball",
        "slot_level": 3,
        "proposed_target_ids": [str(mage_entry_id)],
        "idempotency_key": "routes-propose-fb-1",
    }
    prop_resp = client.post(
        propose_url,
        json=propose_payload,
        headers={"Authorization": f"Bearer {table.player_token}"},
    )
    assert prop_resp.status_code == 200
    prop_data = prop_resp.json()
    assert prop_data["status"] == "dm_adjudication_required"
    action_id = prop_data["action_id"]

    # 2. Player attempts to resolve AoE -> 403
    resolve_payload = {
        "action_id": action_id,
        "confirmed_target_ids": [str(mage_entry_id)],
        "idempotency_key": "routes-resolve-fb-1",
    }
    forbidden_resp = client.post(
        resolve_url,
        json=resolve_payload,
        headers={"Authorization": f"Bearer {table.player_token}"},
    )
    assert forbidden_resp.status_code == 403

    # 3. DM resolves AoE -> 200 (server resolves default damage and d20s)
    dm_resp = client.post(
        resolve_url,
        json=resolve_payload,
        headers={"Authorization": f"Bearer {table.dm_token}"},
    )
    assert dm_resp.status_code == 200
    res_data = dm_resp.json()
    assert res_data["status"] == "resolved"
    assert res_data["resolution_result"] is not None



def test_reaction_window_open_resolve_and_get(combat_routes_fixture) -> None:
    table, char_entry_id, _, _ = combat_routes_fixture
    client = TestClient(app)

    open_url = (
        f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
        f"/sessions/{table.session_id}/combat/reactions/open"
    )
    resolve_url = (
        f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
        f"/sessions/{table.session_id}/combat/reactions/resolve"
    )
    get_url = (
        f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
        f"/sessions/{table.session_id}/combat/entries/{char_entry_id}/reaction"
    )

    # 1. Player cannot open reaction window -> 403
    open_payload = {
        "entry_id": str(char_entry_id),
        "kind": "shield",
        "reason": "Hit by magic missile",
        "idempotency_key": "routes-open-shield-1",
    }
    forbidden_resp = client.post(
        open_url,
        json=open_payload,
        headers={"Authorization": f"Bearer {table.player_token}"},
    )
    assert forbidden_resp.status_code == 403

    # 2. DM opens reaction window -> 200
    dm_open_resp = client.post(
        open_url,
        json=open_payload,
        headers={"Authorization": f"Bearer {table.dm_token}"},
    )
    assert dm_open_resp.status_code == 200
    open_data = dm_open_resp.json()
    assert open_data["status"] == "open"
    assert open_data["kind"] == "shield"

    # 3. GET reaction window -> 200
    get_resp = client.get(
        get_url,
        headers={"Authorization": f"Bearer {table.player_token}"},
    )
    assert get_resp.status_code == 200
    get_data = get_resp.json()
    assert get_data is not None
    assert get_data["status"] == "open"

    # 4. Player resolves reaction window -> 200
    resolve_payload = {
        "owner_entry_id": str(char_entry_id),
        "accept": True,
        "idempotency_key": "routes-resolve-shield-1",
    }
    resolve_resp = client.post(
        resolve_url,
        json=resolve_payload,
        headers={"Authorization": f"Bearer {table.player_token}"},
    )
    assert resolve_resp.status_code == 200
    resolve_data = resolve_resp.json()
    assert resolve_data["accepted"] is True
    assert resolve_data["status"] == "resolved"

    # 5. GET reaction window after resolve -> null
    get_after = client.get(
        get_url,
        headers={"Authorization": f"Bearer {table.player_token}"},
    )
    assert get_after.status_code == 200
    assert get_after.json() is None


def test_concentration_roll_and_drop_via_rest(combat_routes_fixture) -> None:
    table, char_entry_id, mage_entry_id, mage_instance_id = combat_routes_fixture
    client = TestClient(app)

    # Set up character concentration
    with table.engine.begin() as connection:
        state_row = connection.execute(
            select(character_states.c.state_payload).where(
                character_states.c.character_id == table.character_id
            )
        ).mappings().one()
        st = CharacterState.model_validate(state_row["state_payload"])
        st.concentration = CharacterConcentrationState(
            source_ref="srd5.1:spell:bless",
            effect_ids=("eff-bless-1",),
        )
        st.temporary_effects = [PersistentTemporaryEffect(effect_id="eff-bless-1", tag="Bless")]
        connection.execute(
            update(character_states)
            .where(character_states.c.character_id == table.character_id)
            .values(state_payload=st.model_dump(mode="json"))
        )

    # 1. Drop concentration for Character via REST
    drop_char_url = (
        f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
        f"/sessions/{table.session_id}/combat/entries/{char_entry_id}/concentration/drop"
    )
    drop_resp = client.post(
        drop_char_url,
        json={"idempotency_key": "routes-drop-bless-1"},
        headers={"Authorization": f"Bearer {table.player_token}"},
    )
    assert drop_resp.status_code == 200
    drop_data = drop_resp.json()
    assert drop_data["dropped"] is True
    assert "eff-bless-1" in drop_data["linked_effect_ids"]

    # 2. Player cannot drop Monster concentration -> 403
    drop_monster_url = (
        f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
        f"/sessions/{table.session_id}/combat/entries/{mage_entry_id}/concentration/drop"
    )
    forbidden_drop = client.post(
        drop_monster_url,
        headers={"Authorization": f"Bearer {table.player_token}"},
    )
    assert forbidden_drop.status_code == 403

    # 3. DM drops Monster concentration -> 200
    dm_drop = client.post(
        drop_monster_url,
        headers={"Authorization": f"Bearer {table.dm_token}"},
    )
    assert dm_drop.status_code == 200
