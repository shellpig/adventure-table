from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from app.api.rooms.dependencies import get_combat_core_roll_service
from app.domain.combat.core_rolls import (
    CombatCoreRollService,
    pending_combat_roll_request_type,
)
from app.domain.rooms.schemas import EnterRoomRequest
from app.domain.rooms.service import RoomService
from app.main import app
from app.persistence.combat.core_rolls import (
    CombatCoreRollRepository,
    StoredCombatCoreRollRequest,
)
from app.persistence.rooms.p3c_runtime import roll_requests
from app.persistence.rooms.repository import RoomRepository
from tests.test_p4e_adjudication_routes import adjudication_routes_fixture


def _wire_core_roll_service(table) -> CombatCoreRollService:
    service = CombatCoreRollService(
        repository=CombatCoreRollRepository(table.engine, table.events.repository),
        combat_repository=table.combat.repository,
        combat_service=table.combat,
        monster_repository=table.monsters,
        roll_service=table.rolls,
        table_event_service=table.events,
    )
    app.dependency_overrides[get_combat_core_roll_service] = lambda: service
    return service


def _combat_url(table) -> str:
    return (
        f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
        f"/sessions/{table.session_id}/combat"
    )


def _create_attack_roll_request(
    client: TestClient,
    table,
    char_entry_id,
    target_entry_id,
    attack_service,
    *,
    key: str,
) -> str:
    attacks = attack_service.available_attacks(table.player_actor, char_entry_id)
    assert attacks
    attack_response = client.post(
        f"{_combat_url(table)}/attacks/request",
        json={
            "attacker_entry_id": str(char_entry_id),
            "target_entry_id": str(target_entry_id),
            "source_ref": attacks[0].source_ref,
            "idempotency_key": f"{key}-attack",
        },
        headers={"Authorization": f"Bearer {table.player_token}"},
    )
    assert attack_response.status_code == 200
    attack = attack_response.json()
    assert attack["status"] == "dm_adjudication_required"
    assert attack["roll_request_id"] is None

    adjudication_response = client.post(
        f"{_combat_url(table)}/attacks/adjudicate",
        json={
            "action_id": attack["action_id"],
            "in_range": True,
            "idempotency_key": f"{key}-adjudicate",
        },
        headers={"Authorization": f"Bearer {table.dm_token}"},
    )
    assert adjudication_response.status_code == 200
    adjudicated = adjudication_response.json()
    assert adjudicated["roll_request_id"] is not None
    return adjudicated["roll_request_id"]


def _stored_request(
    *,
    request_type: str,
    action_kind: str | None = None,
    label: str | None = None,
) -> StoredCombatCoreRollRequest:
    return StoredCombatCoreRollRequest(
        id=uuid4(),
        roll_group_id=uuid4(),
        session_id=uuid4(),
        target_seat_id=uuid4(),
        target_character_id=uuid4(),
        target_combat_entry_id=uuid4(),
        request_type=request_type,
        ability_ref=None,
        dc=None,
        modifier_mode="normal",
        flat_adjustment=0,
        visibility="public",
        status="pending",
        roll_group_label=label,
        action_kind=action_kind,
    )


@pytest.mark.parametrize(
    ("request", "expected"),
    (
        (_stored_request(request_type="other", action_kind="attack"), "attack"),
        (_stored_request(request_type="other", action_kind="death_save"), "death_save"),
        (_stored_request(request_type="skill", action_kind="grapple"), "grapple"),
        (_stored_request(request_type="skill", action_kind="shove"), "shove"),
        (_stored_request(request_type="other", label="Concentration"), "concentration"),
        (_stored_request(request_type="other", label="Initiative"), "initiative"),
        (_stored_request(request_type="saving_throw", label="Saving Throw"), "saving_throw"),
    ),
)
def test_pending_combat_roll_request_type_is_canonical(
    request: StoredCombatCoreRollRequest,
    expected: str,
) -> None:
    assert pending_combat_roll_request_type(request) == expected


def test_1_player_get_lists_attack_roll_with_hidden_dc(adjudication_routes_fixture) -> None:
    table, char_entry_id, target_entry_id, _p2_token, _adjudication_repo, attack_service = (
        adjudication_routes_fixture
    )
    _wire_core_roll_service(table)
    client = TestClient(app)

    roll_request_id = _create_attack_roll_request(
        client,
        table,
        char_entry_id,
        target_entry_id,
        attack_service,
        key="pending-roll-1",
    )

    response = client.get(
        f"{_combat_url(table)}/pending-rolls",
        headers={"Authorization": f"Bearer {table.player_token}"},
    )
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    assert items[0]["id"] == roll_request_id
    assert items[0]["request_type"] == "attack"
    assert items[0]["target_entry_id"] == str(char_entry_id)
    assert items[0]["dc"] is None
    assert items[0]["modifier_mode"] == "normal"


def test_2_dm_get_includes_save_dc_and_unrelated_player_get_is_empty(
    adjudication_routes_fixture,
) -> None:
    table, char_entry_id, target_entry_id, p2_token, _adjudication_repo, attack_service = (
        adjudication_routes_fixture
    )
    _wire_core_roll_service(table)
    client = TestClient(app)

    attack_roll_request_id = _create_attack_roll_request(
        client,
        table,
        char_entry_id,
        target_entry_id,
        attack_service,
        key="pending-roll-2",
    )
    save_response = client.post(
        f"{_combat_url(table)}/saving-throws/request",
        json={
            "target_entry_ids": [str(char_entry_id)],
            "ability_ref": "dexterity",
            "dc": 16,
            "idempotency_key": "pending-roll-2-save",
        },
        headers={"Authorization": f"Bearer {table.dm_token}"},
    )
    assert save_response.status_code == 200
    save_roll_request_id = save_response.json()["requests"][0]["id"]

    dm_response = client.get(
        f"{_combat_url(table)}/pending-rolls",
        headers={"Authorization": f"Bearer {table.dm_token}"},
    )
    assert dm_response.status_code == 200
    items = dm_response.json()
    by_id = {item["id"]: item for item in items}
    assert attack_roll_request_id in by_id
    assert save_roll_request_id in by_id
    assert by_id[attack_roll_request_id]["request_type"] == "attack"
    assert by_id[save_roll_request_id]["request_type"] == "saving_throw"
    assert by_id[save_roll_request_id]["dc"] == 16

    p2_response = client.get(
        f"{_combat_url(table)}/pending-rolls",
        headers={"Authorization": f"Bearer {p2_token}"},
    )
    assert p2_response.status_code == 200
    assert p2_response.json() == []


def test_3_non_participant_token_is_rejected_without_roll_side_effects(
    adjudication_routes_fixture,
) -> None:
    table, _char_entry_id, _target_entry_id, _p2_token, _adjudication_repo, _attack_service = (
        adjudication_routes_fixture
    )
    _wire_core_roll_service(table)
    client = TestClient(app)

    room_repo = RoomRepository(table.engine)
    room = room_repo.get_room(table.room_id)
    assert room is not None
    outsider = RoomService(room_repo).enter_room(
        EnterRoomRequest(
            code=room.code,
            password="secret",
            display_name="Outsider",
        ),
        remote_addr="127.0.0.44",
    )
    headers = {"Authorization": f"Bearer {outsider.access_token}"}

    with table.engine.connect() as connection:
        before = tuple(connection.execute(select(roll_requests.c.id)).scalars())

    reference = client.get(f"{_combat_url(table)}/detail", headers=headers)
    response = client.get(f"{_combat_url(table)}/pending-rolls", headers=headers)

    # Same rejection as GET /detail (E4a asserts {403, 404} for an unseated Room member).
    assert reference.status_code in {403, 404}
    assert response.status_code == reference.status_code
    assert response.json() == reference.json()
    with table.engine.connect() as connection:
        after = tuple(connection.execute(select(roll_requests.c.id)).scalars())
    assert after == before


def test_4_player_get_lists_saving_throw_and_death_save_discriminators(
    adjudication_routes_fixture,
) -> None:
    table, char_entry_id, _target_entry_id, _p2_token, _adjudication_repo, _attack_service = (
        adjudication_routes_fixture
    )
    _wire_core_roll_service(table)
    client = TestClient(app)

    save_response = client.post(
        f"{_combat_url(table)}/saving-throws/request",
        json={
            "target_entry_ids": [str(char_entry_id)],
            "ability_ref": "wisdom",
            "dc": 15,
            "idempotency_key": "pending-roll-4-save",
        },
        headers={"Authorization": f"Bearer {table.dm_token}"},
    )
    assert save_response.status_code == 200
    save_roll_request_id = save_response.json()["requests"][0]["id"]

    character = table.combat.character_repository.load_character(table.character_id)
    character.state.current_hp = 0
    table.combat.character_repository.save_state(table.character_id, character.state)

    death_response = client.post(
        f"{_combat_url(table)}/death-saves/request",
        json={
            "entry_id": str(char_entry_id),
            "idempotency_key": "pending-roll-4-death",
        },
        headers={"Authorization": f"Bearer {table.player_token}"},
    )
    assert death_response.status_code == 200
    death_roll_request_id = death_response.json()["roll_request_id"]

    response = client.get(
        f"{_combat_url(table)}/pending-rolls",
        headers={"Authorization": f"Bearer {table.player_token}"},
    )
    assert response.status_code == 200
    by_id = {item["id"]: item for item in response.json()}

    assert by_id[save_roll_request_id]["request_type"] == "saving_throw"
    assert by_id[save_roll_request_id]["dc"] is None
    assert by_id[death_roll_request_id]["request_type"] == "death_save"
