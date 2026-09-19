from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select, update

from app.api.dependencies import get_content_registry, get_database_engine
from app.api.rooms.access import get_room_service
from app.api.rooms.dependencies import (
    get_combat_adjudication_service,
    get_combat_attack_service,
    get_combat_reaction_service,
    get_combat_service,
    get_combat_special_attack_service,
    get_room_workspace_service,
    get_table_event_service,
)
from app.content import load_default_content_registry
from app.domain.combat.adjudication_service import CombatAdjudicationService
from app.domain.combat.attack_definitions import AttackDefinitionResolver
from app.domain.combat.attacks import CombatAttackService
from app.domain.combat.initiative import FinalizeInitiativeInput, RequestInitiativeInput
from app.domain.combat.lifecycle import AddMonsterInput, StartCombatInput
from app.domain.combat.reaction_service import CombatReactionService
from app.domain.combat.special_attacks import CombatSpecialAttackService
from app.domain.rooms.rolls import FormalRollInput, FormalRollSource
from app.domain.rooms.schemas import EnterRoomRequest
from app.domain.rooms.seats import ControllerKind, SeatControllerPatch, SeatCreate, SeatRole, SeatService
from app.domain.rooms.service import RoomService
from app.main import app
from app.persistence.combat.adjudication import CombatAdjudicationRepository
from app.persistence.combat.attacks import CombatAttackRepository
from app.persistence.combat.core_rolls import CombatCoreRollRepository
from app.persistence.combat.reactions import CombatReactionRepository
from app.persistence.combat.special_attacks import SpecialAttackRepository
from app.persistence.combat.tables import combat_actions, combat_entries, monster_instances
from app.persistence.rooms.p3c_runtime import roll_requests
from app.persistence.rooms.repository import RoomRepository
from app.persistence.rooms.seats import SeatRepository
from app.persistence.rooms.tables import session_participants
import tests.test_p4b_combat_lifecycle as support
from tests.test_p4c_special_attacks import _unequip_shield


@pytest.fixture
def adjudication_routes_fixture():
    table = support._setup()
    try:
        room_repo = RoomRepository(table.engine)
        room_service = RoomService(room_repo)
        seat_repo = SeatRepository(table.engine)
        seat_service = SeatService(seat_repo)

        # Create Player 2 seat and actor
        room = room_repo.get_room(table.room_id)
        assert room is not None
        p2_enter = room_service.enter_room(
            EnterRoomRequest(
                code=room.code,
                password="secret",
                display_name="Player 2",
            ),
            remote_addr="127.0.0.3",
        )
        p2_seat = seat_service.create_seat(
            table.room_id,
            table.campaign_id,
            SeatCreate(role=SeatRole.PLAYER, label="Player 2"),
        )
        seat_service.set_controller(
            table.room_id,
            table.campaign_id,
            p2_seat.id,
            SeatControllerPatch(
                controller_kind=ControllerKind.HUMAN,
                controller_access_session_id=p2_enter.access_session_id,
            ),
        )
        with table.engine.begin() as connection:
            connection.execute(
                session_participants.insert().values(
                    id=uuid4(),
                    session_id=table.session_id,
                    seat_id=p2_seat.id,
                    role_snapshot="player",
                    controller_kind_at_join="human",
                    controller_access_session_id_at_join=p2_enter.access_session_id,
                    joined_at=datetime.now(timezone.utc),
                )
            )
        p2_token = p2_enter.access_token

        # Start combat
        table.combat.start_quick_combat(
            table.dm_actor,
            StartCombatInput(idempotency_key="adj-test-start"),
        )
        enemy = support._quick_enemy(table, "Adjudication Goblin")
        table.combat.add_monster(
            table.dm_actor,
            AddMonsterInput(
                monster_instance_id=enemy.id,
                idempotency_key="adj-add-enemy",
            ),
        )
        requested = table.initiative.request_initiative(
            table.dm_actor,
            RequestInitiativeInput(idempotency_key="adj-test-init"),
        )
        for index, req in enumerate(requested.requests):
            actor = table.player_actor if req.target_seat_id is not None else table.dm_actor
            raw = 20 if req.target_seat_id is not None else 1
            table.initiative.complete_initiative(
                actor,
                FormalRollInput(
                    roll_request_id=req.id,
                    source=FormalRollSource.PHYSICAL,
                    raw_dice=(raw,),
                    idempotency_key=f"adj-init-roll-{index}",
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
        target_entry = next(r for r in rows if r["monster_instance_id"] == enemy.id)
        char_entry = next(r for r in rows if r["character_id"] == table.character_id)

        # Character first in turn order
        table.initiative.finalize_initiative(
            table.dm_actor,
            FinalizeInitiativeInput(
                ordered_entry_ids=(char_entry["id"], target_entry["id"]),
                idempotency_key="adj-finalize-init",
            ),
        )

        registry = load_default_content_registry()
        adjudication_repo = CombatAdjudicationRepository(table.engine, table.events.repository)
        attack_repo = CombatAttackRepository(table.engine, table.events.repository)
        reaction_repo = CombatReactionRepository(table.engine, table.events.repository)

        attack_service = CombatAttackService(
            repository=attack_repo,
            adjudication_repository=adjudication_repo,
            combat_repository=table.combat.repository,
            combat_service=table.combat,
            definition_resolver=AttackDefinitionResolver(
                table.combat.character_repository,
                table.monsters,
                registry,
            ),
            roll_service=table.rolls,
            table_event_service=table.events,
        )
        reaction_service = CombatReactionService(
            repository=reaction_repo,
            combat_repository=table.combat.repository,
            combat_service=table.combat,
            table_event_service=table.events,
        )
        adjudication_service = CombatAdjudicationService(
            repository=adjudication_repo,
            combat_repository=table.combat.repository,
            combat_service=table.combat,
            table_event_service=table.events,
        )
        special_attack_service = CombatSpecialAttackService(
            repository=SpecialAttackRepository(table.engine, table.events.repository),
            core_roll_repository=CombatCoreRollRepository(table.engine, table.events.repository),
            combat_repository=table.combat.repository,
            combat_service=table.combat,
            character_repository=table.combat.character_repository,
            monster_repository=table.monsters,
            registry=registry,
            roll_service=table.rolls,
            table_event_service=table.events,
        )

        app.dependency_overrides[get_database_engine] = lambda: table.engine
        app.dependency_overrides[get_room_service] = lambda: room_service
        app.dependency_overrides[get_combat_service] = lambda: table.combat
        app.dependency_overrides[get_table_event_service] = lambda: table.events
        app.dependency_overrides[get_combat_attack_service] = lambda: attack_service
        app.dependency_overrides[get_combat_reaction_service] = lambda: reaction_service
        app.dependency_overrides[get_combat_adjudication_service] = lambda: adjudication_service
        app.dependency_overrides[get_combat_special_attack_service] = lambda: special_attack_service

        yield table, char_entry["id"], target_entry["id"], p2_token, adjudication_repo, attack_service
    finally:
        app.dependency_overrides.clear()
        table.engine.dispose()


def test_1_player_attack_pending_range_adjudication_and_secrecy(adjudication_routes_fixture) -> None:
    """1. Player attack -> pending range adjudication appears in GET /adjudications for DM

    (with dm_hints.target_ac) and for the acting Player (dm_hints is None / absent in raw JSON);
    a second Player on another seat does not see it.
    """
    table, char_entry_id, target_entry_id, p2_token, adjudication_repo, attack_service = adjudication_routes_fixture
    client = TestClient(app)
    base_combat_url = (
        f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
        f"/sessions/{table.session_id}/combat"
    )

    available = attack_service.available_attacks(table.player_actor, char_entry_id)
    assert available
    source_ref = available[0].source_ref

    # Player 1 declares attack without authoritative range -> pending adjudication
    attack_res = client.post(
        f"{base_combat_url}/attacks/request",
        json={
            "attacker_entry_id": str(char_entry_id),
            "target_entry_id": str(target_entry_id),
            "source_ref": source_ref,
            "range_confirmed": True,
            "idempotency_key": "test-1-attack-req",
        },
        headers={"Authorization": f"Bearer {table.player_token}"},
    )
    assert attack_res.status_code == 200
    attack_data = attack_res.json()
    action_id = attack_data["action_id"]
    assert attack_data["status"] == "dm_adjudication_required"

    # DM calls GET /adjudications -> sees it with dm_hints.target_ac
    dm_res = client.get(
        f"{base_combat_url}/adjudications",
        headers={"Authorization": f"Bearer {table.dm_token}"},
    )
    assert dm_res.status_code == 200
    dm_items = dm_res.json()
    dm_item = next(item for item in dm_items if item["action_id"] == action_id)
    assert dm_item["kind"] == "range"
    assert dm_item["status"] == "pending"
    assert dm_item["dm_hints"] is not None
    assert isinstance(dm_item["dm_hints"]["target_ac"], int)
    assert "resolved_attack" in dm_item["dm_hints"]

    # Acting Player calls GET /adjudications -> sees it with dm_hints being None
    player_res = client.get(
        f"{base_combat_url}/adjudications",
        headers={"Authorization": f"Bearer {table.player_token}"},
    )
    assert player_res.status_code == 200
    player_items = player_res.json()
    player_item = next(item for item in player_items if item["action_id"] == action_id)
    assert player_item["kind"] == "range"
    assert player_item["status"] == "pending"
    assert player_item["dm_hints"] is None

    # Second Player on another seat does NOT see it
    p2_res = client.get(
        f"{base_combat_url}/adjudications",
        headers={"Authorization": f"Bearer {p2_token}"},
    )
    assert p2_res.status_code == 200
    p2_items = p2_res.json()
    assert all(item["action_id"] != action_id for item in p2_items)


def test_2_dm_resolves_range_with_disadvantage_and_clears_from_pending(adjudication_routes_fixture) -> None:
    """2. DM resolves range with in_range=True, roll_mode='disadvantage':

    the created Attack RollRequest has disadvantage modifier mode;
    the resolved row's decision carries roll_mode;
    the adjudication no longer appears in GET /adjudications.
    """
    table, char_entry_id, target_entry_id, _p2_token, adjudication_repo, attack_service = adjudication_routes_fixture
    client = TestClient(app)
    base_combat_url = (
        f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
        f"/sessions/{table.session_id}/combat"
    )

    available = attack_service.available_attacks(table.player_actor, char_entry_id)
    source_ref = available[0].source_ref

    attack_res = client.post(
        f"{base_combat_url}/attacks/request",
        json={
            "attacker_entry_id": str(char_entry_id),
            "target_entry_id": str(target_entry_id),
            "source_ref": source_ref,
            "range_confirmed": True,
            "idempotency_key": "test-2-attack-req",
        },
        headers={"Authorization": f"Bearer {table.player_token}"},
    )
    assert attack_res.status_code == 200
    action_id = attack_res.json()["action_id"]

    # DM resolves range with disadvantage and a note
    adj_res = client.post(
        f"{base_combat_url}/attacks/adjudicate",
        json={
            "action_id": action_id,
            "in_range": True,
            "roll_mode": "disadvantage",
            "note": "Target has half cover behind rubble",
            "idempotency_key": "test-2-adjudicate",
        },
        headers={"Authorization": f"Bearer {table.dm_token}"},
    )
    assert adj_res.status_code == 200
    adj_data = adj_res.json()
    assert adj_data["status"] == "waiting_for_roll"
    roll_request_id = adj_data["roll_request_id"]
    assert roll_request_id is not None

    # Check roll request in DB has disadvantage modifier_mode
    with table.engine.connect() as connection:
        rr = connection.execute(
            select(roll_requests.c.modifier_mode).where(
                roll_requests.c.id == UUID(roll_request_id)
            )
        ).mappings().one()
        assert rr["modifier_mode"] == "disadvantage"

    # Check action row payload carries roll_mode in adjudication
    action_row = adjudication_repo.get_action(
        session_id=table.session_id,
        action_id=UUID(action_id),
    )
    assert action_row is not None
    adjudication = action_row.payload["adjudication"]
    assert adjudication["in_range"] is True
    assert adjudication["roll_mode"] == "disadvantage"
    assert adjudication["note"] == "Target has half cover behind rubble"

    # The adjudication no longer appears in GET /adjudications
    get_res = client.get(
        f"{base_combat_url}/adjudications",
        headers={"Authorization": f"Bearer {table.dm_token}"},
    )
    assert get_res.status_code == 200
    assert all(item["action_id"] != action_id for item in get_res.json())


def test_3_opportunity_attack_trigger_true_opens_reaction_window_atomic(adjudication_routes_fixture) -> None:
    """3. Opportunity attack: Player who controls the reactor declares;

    DM resolves trigger=True -> reactor now has an open reaction window of kind opportunity_attack
    (GET /entries/{id}/reaction) and the action row is resolved in the same transaction
    (assert both after one call; then assert that a forced failure in the window write
    - e.g. reactor entry not active - leaves the row still pending: zero side effects).
    """
    table, char_entry_id, target_entry_id, _p2_token, adjudication_repo, _ = adjudication_routes_fixture
    client = TestClient(app)
    base_combat_url = (
        f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
        f"/sessions/{table.session_id}/combat"
    )

    # Player 1 declares OA
    oa_res = client.post(
        f"{base_combat_url}/adjudications/opportunity-attack",
        json={
            "mover_entry_id": str(target_entry_id),
            "reactor_entry_id": str(char_entry_id),
            "question": "Enemy moved past me, can I take an opportunity attack?",
            "idempotency_key": "test-3-oa-req",
        },
        headers={"Authorization": f"Bearer {table.player_token}"},
    )
    assert oa_res.status_code == 200
    oa_data = oa_res.json()
    action_id = oa_data["action_id"]
    assert oa_data["kind"] == "opportunity_attack"
    assert oa_data["status"] == "pending"
    assert oa_data["question"] == "Enemy moved past me, can I take an opportunity attack?"

    # DM resolves trigger=True
    resolve_res = client.post(
        f"{base_combat_url}/adjudications/{action_id}/resolve",
        json={
            "trigger": True,
            "ruling": "Goblin moved without disengaging",
            "idempotency_key": "test-3-oa-resolve",
        },
        headers={"Authorization": f"Bearer {table.dm_token}"},
    )
    assert resolve_res.status_code == 200
    resolved_data = resolve_res.json()
    assert resolved_data["status"] == "resolved"
    assert resolved_data["decision"]["trigger"] is True
    assert resolved_data["note"] == "Goblin moved without disengaging"

    # Reactor now has an open reaction window of kind opportunity_attack
    reaction_res = client.get(
        f"{base_combat_url}/entries/{char_entry_id}/reaction",
        headers={"Authorization": f"Bearer {table.player_token}"},
    )
    assert reaction_res.status_code == 200
    reaction_data = reaction_res.json()
    assert reaction_data is not None
    assert reaction_data["status"] == "open"
    assert reaction_data["kind"] == "opportunity_attack"

    # Assert action row in DB is resolved
    action_row = adjudication_repo.get_action(session_id=table.session_id, action_id=UUID(action_id))
    assert action_row is not None
    assert action_row.resolution_status == "resolved"

    # Now test forced failure in window write leaves row still pending (zero side effects)
    oa_fail_res = client.post(
        f"{base_combat_url}/adjudications/opportunity-attack",
        json={
            "mover_entry_id": str(target_entry_id),
            "reactor_entry_id": str(char_entry_id),
            "question": "Second OA test",
            "idempotency_key": "test-3-oa-fail-req",
        },
        headers={"Authorization": f"Bearer {table.player_token}"},
    )
    assert oa_fail_res.status_code == 200
    fail_action_id = oa_fail_res.json()["action_id"]

    # Deactivate reactor entry to trigger a forced failure in write_reaction_window
    with table.engine.begin() as connection:
        connection.execute(
            update(combat_entries)
            .where(combat_entries.c.id == char_entry_id)
            .values(status="withdrawn")
        )

    # DM resolves trigger=True -> should fail because reactor is inactive
    fail_resolve_res = client.post(
        f"{base_combat_url}/adjudications/{fail_action_id}/resolve",
        json={
            "trigger": True,
            "ruling": "Should fail",
            "idempotency_key": "test-3-oa-fail-resolve",
        },
        headers={"Authorization": f"Bearer {table.dm_token}"},
    )
    assert fail_resolve_res.status_code in (404, 409)

    # Assert fail_action_id is STILL pending (resolution_status == "dm_adjudication_required")
    fail_row = adjudication_repo.get_action(session_id=table.session_id, action_id=UUID(fail_action_id))
    assert fail_row is not None
    assert fail_row.resolution_status == "dm_adjudication_required"

    # Restore entry status
    with table.engine.begin() as connection:
        connection.execute(
            update(combat_entries)
            .where(combat_entries.c.id == char_entry_id)
            .values(status="active")
        )


def test_4_opportunity_attack_trigger_false_resolves_without_reaction_window(adjudication_routes_fixture) -> None:
    """4. Opportunity attack trigger=False -> no reaction window, row resolved."""
    table, char_entry_id, target_entry_id, _p2_token, adjudication_repo, _ = adjudication_routes_fixture
    client = TestClient(app)
    base_combat_url = (
        f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
        f"/sessions/{table.session_id}/combat"
    )

    # Player 1 declares OA
    oa_res = client.post(
        f"{base_combat_url}/adjudications/opportunity-attack",
        json={
            "mover_entry_id": str(target_entry_id),
            "reactor_entry_id": str(char_entry_id),
            "question": "Can I OA?",
            "idempotency_key": "test-4-oa-req",
        },
        headers={"Authorization": f"Bearer {table.player_token}"},
    )
    assert oa_res.status_code == 200
    action_id = oa_res.json()["action_id"]

    # DM resolves trigger=False
    resolve_res = client.post(
        f"{base_combat_url}/adjudications/{action_id}/resolve",
        json={
            "trigger": False,
            "ruling": "Target used Disengage",
            "idempotency_key": "test-4-oa-resolve",
        },
        headers={"Authorization": f"Bearer {table.dm_token}"},
    )
    assert resolve_res.status_code == 200
    resolved_data = resolve_res.json()
    assert resolved_data["status"] == "resolved"
    assert resolved_data["decision"]["trigger"] is False
    assert resolved_data["note"] == "Target used Disengage"

    # Reactor has NO open reaction window
    reaction_res = client.get(
        f"{base_combat_url}/entries/{char_entry_id}/reaction",
        headers={"Authorization": f"Bearer {table.player_token}"},
    )
    assert reaction_res.status_code == 200
    assert reaction_res.json() is None

    # Row is resolved in DB
    action_row = adjudication_repo.get_action(session_id=table.session_id, action_id=UUID(action_id))
    assert action_row is not None
    assert action_row.resolution_status == "resolved"


def test_5_special_adjudication_declaration_and_resolution(adjudication_routes_fixture) -> None:
    """5. Special: Player declares with question; Player cannot resolve (403, row still pending);

    DM resolve without ruling rejected; DM resolve with ruling resolves;
    combat.adjudication_resolved event visible to the Player via the table events list with the ruling.
    """
    table, char_entry_id, target_entry_id, _p2_token, adjudication_repo, _ = adjudication_routes_fixture
    client = TestClient(app)
    base_combat_url = (
        f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
        f"/sessions/{table.session_id}/combat"
    )

    # Player declares special adjudication with question
    spec_res = client.post(
        f"{base_combat_url}/adjudications/special",
        json={
            "subject_entry_id": str(char_entry_id),
            "target_entry_ids": [str(target_entry_id)],
            "question": "Can I swing from the chandelier onto the goblin?",
            "idempotency_key": "test-5-special-req",
        },
        headers={"Authorization": f"Bearer {table.player_token}"},
    )
    assert spec_res.status_code == 200
    spec_data = spec_res.json()
    action_id = spec_data["action_id"]
    assert spec_data["kind"] == "special"
    assert spec_data["status"] == "pending"
    assert spec_data["question"] == "Can I swing from the chandelier onto the goblin?"

    # Player cannot resolve (403, row still pending)
    player_resolve_res = client.post(
        f"{base_combat_url}/adjudications/{action_id}/resolve",
        json={"ruling": "Yes I can"},
        headers={"Authorization": f"Bearer {table.player_token}"},
    )
    assert player_resolve_res.status_code == 403

    # Row still pending in DB
    action_row = adjudication_repo.get_action(session_id=table.session_id, action_id=UUID(action_id))
    assert action_row is not None
    assert action_row.resolution_status == "dm_adjudication_required"

    # DM resolve without ruling rejected (422)
    dm_no_ruling_res = client.post(
        f"{base_combat_url}/adjudications/{action_id}/resolve",
        json={"ruling": ""},
        headers={"Authorization": f"Bearer {table.dm_token}"},
    )
    assert dm_no_ruling_res.status_code == 422

    # DM resolve with ruling resolves
    dm_resolve_res = client.post(
        f"{base_combat_url}/adjudications/{action_id}/resolve",
        json={
            "ruling": "Yes, make a DC 13 Acrobatics check.",
            "idempotency_key": "test-5-dm-resolve",
        },
        headers={"Authorization": f"Bearer {table.dm_token}"},
    )
    assert dm_resolve_res.status_code == 200
    dm_resolve_data = dm_resolve_res.json()
    assert dm_resolve_data["status"] == "resolved"
    assert dm_resolve_data["decision"]["ruling"] == "Yes, make a DC 13 Acrobatics check."
    assert dm_resolve_data["note"] == "Yes, make a DC 13 Acrobatics check."

    # combat.adjudication_resolved event visible to the Player via table events list
    events_res = client.get(
        f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}/sessions/{table.session_id}/events",
        headers={"Authorization": f"Bearer {table.player_token}"},
    )
    assert events_res.status_code == 200
    events_data = events_res.json()
    # List of events in session
    adjudication_event = next(
        e for e in events_data["events"]
        if e["kind"] == "combat.adjudication_resolved" and e["payload"].get("combat_action_id") == action_id
    )
    assert adjudication_event["payload"]["decision"]["ruling"] == "Yes, make a DC 13 Acrobatics check."
    assert adjudication_event["payload"]["note"] == "Yes, make a DC 13 Acrobatics check."


def test_6_resolve_refuses_range_row_and_unknown_action_id(adjudication_routes_fixture) -> None:
    """6. Resolve route refuses a pending range row with 409 and the row stays pending;

    unknown action_id -> 404.
    """
    table, char_entry_id, target_entry_id, _p2_token, adjudication_repo, attack_service = adjudication_routes_fixture
    client = TestClient(app)
    base_combat_url = (
        f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
        f"/sessions/{table.session_id}/combat"
    )

    available = attack_service.available_attacks(table.player_actor, char_entry_id)
    source_ref = available[0].source_ref

    attack_res = client.post(
        f"{base_combat_url}/attacks/request",
        json={
            "attacker_entry_id": str(char_entry_id),
            "target_entry_id": str(target_entry_id),
            "source_ref": source_ref,
            "range_confirmed": True,
            "idempotency_key": "test-6-attack-req",
        },
        headers={"Authorization": f"Bearer {table.player_token}"},
    )
    assert attack_res.status_code == 200
    range_action_id = attack_res.json()["action_id"]

    # Try to resolve range action via generic resolve route -> 409
    resolve_range_res = client.post(
        f"{base_combat_url}/adjudications/{range_action_id}/resolve",
        json={"ruling": "I approve range"},
        headers={"Authorization": f"Bearer {table.dm_token}"},
    )
    assert resolve_range_res.status_code == 409
    assert (
        "Range adjudication must be resolved through attack adjudication (combat_adjudicate_attack / POST .../attacks/adjudicate)"
        in resolve_range_res.json()["error"]["message"]
    )

    # Row stays pending
    range_row = adjudication_repo.get_action(session_id=table.session_id, action_id=UUID(range_action_id))
    assert range_row is not None
    assert range_row.resolution_status == "dm_adjudication_required"

    # Unknown action_id -> 404
    unknown_id = str(uuid4())
    unknown_res = client.post(
        f"{base_combat_url}/adjudications/{unknown_id}/resolve",
        json={"ruling": "Some ruling"},
        headers={"Authorization": f"Bearer {table.dm_token}"},
    )
    assert unknown_res.status_code == 404
    assert "combat_not_found" in unknown_res.json()["error"]["code"] or unknown_res.status_code == 404


def test_7_player_cannot_declare_opportunity_attack_for_uncontrolled_reactor(adjudication_routes_fixture) -> None:
    """7. Player cannot declare an opportunity attack for a reactor they do not control (403, no row created)."""
    table, char_entry_id, target_entry_id, p2_token, adjudication_repo, _ = adjudication_routes_fixture
    client = TestClient(app)
    base_combat_url = (
        f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
        f"/sessions/{table.session_id}/combat"
    )

    # Player 2 controls neither char_entry_id (Player 1) nor target_entry_id (Monster)
    oa_res = client.post(
        f"{base_combat_url}/adjudications/opportunity-attack",
        json={
            "mover_entry_id": str(target_entry_id),
            "reactor_entry_id": str(char_entry_id),
            "question": "Can Mira take an OA?",
            "idempotency_key": "test-7-oa-req",
        },
        headers={"Authorization": f"Bearer {p2_token}"},
    )
    assert oa_res.status_code == 403
    assert "table_actor_unauthorized" in oa_res.json()["error"]["code"]

    # Assert no row created in combat_actions
    with table.engine.connect() as connection:
        oa_count = connection.scalar(
            select(combat_actions.c.id).where(
                combat_actions.c.idempotency_key == "test-7-oa-req"
            )
        )
        assert oa_count is None


def test_8_shove_prone_adjudication_is_reach_with_hints_and_resolve_refuses(
    adjudication_routes_fixture,
) -> None:
    """8. Pending grapple and shove_prone requests are listed with kind == 'reach' for DM

    with identical dm_hints structure; generic resolve_adjudication on each raises the
    'dedicated special-attack route' conflict.
    """
    table, char_entry_id, target_entry_id, _p2_token, _adjudication_repo, _attack_service = (
        adjudication_routes_fixture
    )
    client = TestClient(app)
    base_combat_url = (
        f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
        f"/sessions/{table.session_id}/combat"
    )

    _unequip_shield(table)
    with table.engine.begin() as connection:
        connection.execute(
            update(monster_instances).values(
                rules_snapshot={
                    "armor_class": 12,
                    "max_hp": 9,
                    "speed": {"walk": "30 ft."},
                    "size": "Small",
                }
            )
        )

    # 1. Declare grapple
    grapple_res = client.post(
        f"{base_combat_url}/special-attacks/request",
        json={
            "attacker_entry_id": str(char_entry_id),
            "target_entry_id": str(target_entry_id),
            "kind": "grapple",
            "idempotency_key": "test-8-grapple-req",
        },
        headers={"Authorization": f"Bearer {table.player_token}"},
    )
    assert grapple_res.status_code == 200
    grapple_action_id = grapple_res.json()["action_id"]

    dm_res_1 = client.get(
        f"{base_combat_url}/adjudications",
        headers={"Authorization": f"Bearer {table.dm_token}"},
    )
    assert dm_res_1.status_code == 200
    grapple_item = next(i for i in dm_res_1.json() if i["action_id"] == grapple_action_id)
    assert grapple_item["kind"] == "reach"
    assert grapple_item["status"] == "pending"
    assert grapple_item["dm_hints"] is not None
    assert "attacker_size" in grapple_item["dm_hints"]
    assert "target_size" in grapple_item["dm_hints"]
    assert "attacker_has_free_hand" in grapple_item["dm_hints"]
    assert "attacker_skill" in grapple_item["dm_hints"]
    assert "defender_skill" in grapple_item["dm_hints"]

    grapple_resolve_res = client.post(
        f"{base_combat_url}/adjudications/{grapple_action_id}/resolve",
        json={"ruling": "approve"},
        headers={"Authorization": f"Bearer {table.dm_token}"},
    )
    assert grapple_resolve_res.status_code == 409
    assert (
        "Reach adjudication must be resolved through special-attack adjudication (combat_adjudicate_special_attack / POST .../special-attacks/adjudicate)"
        in grapple_resolve_res.json()["error"]["message"]
    )

    # 2. Declare shove_prone
    shove_res = client.post(
        f"{base_combat_url}/special-attacks/request",
        json={
            "attacker_entry_id": str(char_entry_id),
            "target_entry_id": str(target_entry_id),
            "kind": "shove_prone",
            "idempotency_key": "test-8-shove-req",
        },
        headers={"Authorization": f"Bearer {table.player_token}"},
    )
    assert shove_res.status_code == 200
    shove_action_id = shove_res.json()["action_id"]

    dm_res_2 = client.get(
        f"{base_combat_url}/adjudications",
        headers={"Authorization": f"Bearer {table.dm_token}"},
    )
    assert dm_res_2.status_code == 200
    shove_item = next(i for i in dm_res_2.json() if i["action_id"] == shove_action_id)
    assert shove_item["kind"] == "reach"
    assert shove_item["status"] == "pending"
    assert shove_item["dm_hints"] == grapple_item["dm_hints"]

    shove_resolve_res = client.post(
        f"{base_combat_url}/adjudications/{shove_action_id}/resolve",
        json={"ruling": "approve"},
        headers={"Authorization": f"Bearer {table.dm_token}"},
    )
    assert shove_resolve_res.status_code == 409
    assert (
        "Reach adjudication must be resolved through special-attack adjudication (combat_adjudicate_special_attack / POST .../special-attacks/adjudicate)"
        in shove_resolve_res.json()["error"]["message"]
    )

