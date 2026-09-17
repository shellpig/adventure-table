from __future__ import annotations

from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import update

from app.api.dependencies import get_database_engine
from app.api.rooms.access import get_room_service
from app.api.rooms.dependencies import get_combat_service, get_table_event_service
from app.domain.character.schemas import (
    CharacterConcentrationState,
    CharacterDeathSaveState,
    ConditionState,
    PersistentTemporaryEffect,
)
from app.domain.combat.lifecycle import AddMonsterInput, StartCombatInput
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.service import RoomService
from app.main import app
from app.persistence.combat.tables import monster_instances
from app.persistence.rooms.repository import RoomRepository
import tests.test_p4b_combat_lifecycle as support


@pytest.fixture
def secrecy_table():
    table = support._setup()
    try:
        # Start combat
        table.combat.start_quick_combat(
            table.dm_actor,
            StartCombatInput(idempotency_key="secrecy-test-start"),
        )

        # Configure Character state with rich runtime facts
        char = table.combat.character_repository.load_character(table.character_id)
        char.state.current_hp = 20
        char.state.temporary_hp = 5
        char.state.conditions = [ConditionState(condition_ref="srd5.1:condition:prone")]
        char.state.temporary_effects = [
            PersistentTemporaryEffect(effect_id="eff-bless", tag="Bless")
        ]
        char.state.concentration = CharacterConcentrationState(
            source_ref="srd5.1:spell:bless",
            effect_ids=("eff-bless",),
        )
        char.state.death_saves = CharacterDeathSaveState(successes=1, failures=0)
        char.state.exhaustion_level = 1
        table.combat.character_repository.save_state(table.character_id, char.state)

        # Create hostile visible monster
        evil_mage = table.monsters.create_instance(
            campaign_id=table.campaign_id,
            name="Evil Mage",
            rules_snapshot={
                "armor_class": 15,
                "max_hp": 44,
                "speed": {"walk": 30},
                "description": "A sinister spellcaster.",
            },
            current_hp=19,
            temp_hp=4,
            resources={"spell_slot:1": 2},
            conditions=["prone", {"name": "secret-mark", "visibility": "hidden"}],
            position_note="behind pillar",
        )
        with table.engine.begin() as conn:
            conn.execute(
                update(monster_instances)
                .where(monster_instances.c.id == evil_mage.id)
                .values(
                    concentration={"spell_ref": "srd5.1:spell:fly", "effect_ids": ["eff-fly"]}
                )
            )

        table.combat.add_monster(
            table.dm_actor,
            AddMonsterInput(
                monster_instance_id=evil_mage.id,
                idempotency_key="secrecy-add-mage",
            ),
        )

        # Create hostile hidden monster
        hidden_assassin = table.monsters.create_instance(
            campaign_id=table.campaign_id,
            name="Stealth Assassin",
            rules_snapshot={
                "armor_class": 16,
                "max_hp": 25,
                "speed": {"walk": 35},
            },
            current_hp=25,
            visibility="hidden",
        )
        table.combat.add_monster(
            table.dm_actor,
            AddMonsterInput(
                monster_instance_id=hidden_assassin.id,
                idempotency_key="secrecy-add-assassin",
            ),
        )

        # Wire dependency overrides for TestClient
        room_service = RoomService(RoomRepository(table.engine))
        app.dependency_overrides[get_database_engine] = lambda: table.engine
        app.dependency_overrides[get_room_service] = lambda: room_service
        app.dependency_overrides[get_combat_service] = lambda: table.combat
        app.dependency_overrides[get_table_event_service] = lambda: table.events

        yield table, evil_mage, hidden_assassin
    finally:
        app.dependency_overrides.clear()
        table.engine.dispose()


def test_dm_detail_contains_exact_monster_mechanics_and_secrets(secrecy_table) -> None:
    table, evil_mage, _ = secrecy_table
    client = TestClient(app)
    url = (
        f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
        f"/sessions/{table.session_id}/combat/detail"
    )

    response = client.get(url, headers={"Authorization": f"Bearer {table.dm_token}"})
    assert response.status_code == 200
    data = response.json()
    assert data is not None

    # Find the monster combatant
    mage_combatant = next(
        c for c in data["combatants"]
        if c["subject_kind"] == "monster" and c["projection"]["name"] == "Evil Mage"
    )
    assert mage_combatant["is_hostile"] is True
    proj = mage_combatant["projection"]

    # (1) DM detail contains exact current_hp / max_hp / temp_hp / armor_class / resources / hidden conditions / concentration
    assert proj["current_hp"] == 19
    assert proj["max_hp"] == 44
    assert proj["temp_hp"] == 4
    assert proj["armor_class"] == 15
    assert proj["resources"] == {"spell_slot:1": 2}
    assert "secret-mark" in proj["conditions"]
    assert "prone" in proj["conditions"]
    assert proj["concentration"] == {
        "spell_ref": "srd5.1:spell:fly",
        "effect_ids": ["eff-fly"],
    }
    assert proj["position_note"] == "behind pillar"


def test_player_detail_redacts_monster_secrecy_and_preserves_injury_level(secrecy_table) -> None:
    table, _, _ = secrecy_table
    client = TestClient(app)
    url = (
        f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
        f"/sessions/{table.session_id}/combat/detail"
    )

    response = client.get(url, headers={"Authorization": f"Bearer {table.player_token}"})
    assert response.status_code == 200
    data = response.json()
    assert data is not None

    # Find monster entry in player view
    mage_combatant = next(
        c for c in data["combatants"]
        if c["subject_kind"] == "monster" and c["projection"]["name"] == "Evil Mage"
    )
    assert mage_combatant["is_hostile"] is True
    raw_proj = mage_combatant["projection"]

    # (2) Player detail for the same combat: the Monster projection has NO
    # current_hp, max_hp, temp_hp, armor_class (unless revealed), resources,
    # hidden_conditions, dm_notes, concentration, death_saves, exhaustion_level.
    # Assert on the raw JSON of the REST response (key absence, not just None).
    forbidden_keys = [
        "current_hp",
        "max_hp",
        "temp_hp",
        "armor_class",
        "resources",
        "hidden_conditions",
        "dm_notes",
        "concentration",
        "death_saves",
        "exhaustion_level",
        "speed",
        "traits",
        "actions",
        "bonus_actions",
        "reactions",
        "legendary_actions",
        "reaction_available",
    ]
    for key in forbidden_keys:
        assert key not in raw_proj, f"Forbidden key '{key}' leaked into player monster projection: {raw_proj}"

    # Secret conditions must be filtered out
    assert "secret-mark" not in raw_proj["conditions"]

    # Has injury_level + public conditions
    assert raw_proj["injury_level"] == "wounded"  # 19 / 44 is ~0.43 <= 0.5
    assert "prone" in raw_proj["conditions"]


def test_player_detail_contains_exact_own_character_mechanics(secrecy_table) -> None:
    table, _, _ = secrecy_table
    client = TestClient(app)
    url = (
        f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
        f"/sessions/{table.session_id}/combat/detail"
    )

    response = client.get(url, headers={"Authorization": f"Bearer {table.player_token}"})
    assert response.status_code == 200
    data = response.json()
    assert data is not None

    # Find player character entry
    char_combatant = next(
        c for c in data["combatants"]
        if c["subject_kind"] == "character"
    )
    assert char_combatant["is_hostile"] is False
    proj = char_combatant["projection"]

    # (3) Player detail for their own Character entry has exact HP, conditions,
    # temporary effects, concentration, death saves
    assert proj["current_hp"] == 20
    assert proj["temp_hp"] == 5
    assert proj["max_hp"] > 0
    assert proj["armor_class"] is not None

    # Conditions & temporary effects as public names
    assert "srd5.1:condition:prone" in proj["conditions"]
    assert "Bless" in proj["effects"]

    # Concentration & death saves as dicts
    assert proj["concentration"] is not None
    assert proj["concentration"]["source_ref"] == "srd5.1:spell:bless"
    assert proj["concentration"]["effect_ids"] == ["eff-bless"]

    assert proj["death_saves"] is not None
    assert proj["death_saves"]["successes"] == 1
    assert proj["death_saves"]["failures"] == 0
    assert proj["death_saves"]["stable"] is False
    assert proj["death_saves"]["dead"] is False

    assert proj["exhaustion_level"] == 1


def test_hidden_visibility_monster_omitted_for_player_but_present_for_dm(secrecy_table) -> None:
    table, _, _ = secrecy_table
    client = TestClient(app)
    url = (
        f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
        f"/sessions/{table.session_id}/combat/detail"
    )

    # (4) a hidden-visibility Monster is absent from the Player tuple but present for the DM
    dm_res = client.get(url, headers={"Authorization": f"Bearer {table.dm_token}"})
    assert dm_res.status_code == 200
    dm_names = [c["projection"]["name"] for c in dm_res.json()["combatants"]]
    assert "Stealth Assassin" in dm_names

    player_res = client.get(url, headers={"Authorization": f"Bearer {table.player_token}"})
    assert player_res.status_code == 200
    player_names = [c["projection"]["name"] for c in player_res.json()["combatants"]]
    assert "Stealth Assassin" not in player_names


def test_unseated_room_actor_is_rejected_same_as_get_combat(secrecy_table) -> None:
    table, _, _ = secrecy_table
    client = TestClient(app)

    # (5) an actor who is in the Room but not a current participant of this Session
    # is rejected (same rule as GET "").
    # Create a room-level token for an unseated spectator / member not in session
    outsider_rooms = RoomService(RoomRepository(table.engine))
    outsider_grant = outsider_rooms.enter_room(
        support.EnterRoomRequest(
            code=outsider_rooms.repository.get_room(table.room_id).code,
            password="secret",
            display_name="Spectator",
        ),
        remote_addr="127.0.0.99",
    )

    base_url = (
        f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
        f"/sessions/{table.session_id}/combat"
    )
    detail_url = f"{base_url}/detail"

    # Both routes reject the unseated actor with identical status and error code
    res_base = client.get(
        base_url,
        headers={"Authorization": f"Bearer {outsider_grant.access_token}"},
    )
    res_detail = client.get(
        detail_url,
        headers={"Authorization": f"Bearer {outsider_grant.access_token}"},
    )

    assert res_base.status_code == res_detail.status_code
    assert res_base.json() == res_detail.json()
    assert res_detail.status_code in {403, 404}
    assert res_detail.json()["error"]["code"] in {"session_not_found", "table_actor_unauthorized"}


def test_rest_level_token_authentication_for_dm_and_player(secrecy_table) -> None:
    table, _, _ = secrecy_table
    client = TestClient(app)

    # Hit the detail path with the DM and Player tokens
    url = (
        f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
        f"/sessions/{table.session_id}/combat/detail"
    )
    res_dm = client.get(url, headers={"Authorization": f"Bearer {table.dm_token}"})
    assert res_dm.status_code == 200
    assert res_dm.headers["content-type"].startswith("application/json")
    dm_json = res_dm.json()
    assert dm_json["status"] == "initiative_pending"
    assert len(dm_json["combatants"]) == 3  # Character + Evil Mage + Stealth Assassin

    res_pl = client.get(url, headers={"Authorization": f"Bearer {table.player_token}"})
    assert res_pl.status_code == 200
    assert res_pl.headers["content-type"].startswith("application/json")
    pl_json = res_pl.json()
    assert pl_json["status"] == "initiative_pending"
    assert len(pl_json["combatants"]) == 2  # Character + Evil Mage (Stealth Assassin omitted)


def test_combat_detail_returns_none_when_no_active_combat() -> None:
    table = support._setup()
    try:
        room_service = RoomService(RoomRepository(table.engine))
        app.dependency_overrides[get_database_engine] = lambda: table.engine
        app.dependency_overrides[get_room_service] = lambda: room_service
        app.dependency_overrides[get_combat_service] = lambda: table.combat
        app.dependency_overrides[get_table_event_service] = lambda: table.events

        client = TestClient(app)
        url = (
            f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
            f"/sessions/{table.session_id}/combat/detail"
        )
        response = client.get(url, headers={"Authorization": f"Bearer {table.dm_token}"})
        assert response.status_code == 200
        assert response.json() is None
    finally:
        app.dependency_overrides.clear()
        table.engine.dispose()
