from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import Request
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, func, insert, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_database_engine
from app.api.errors import APIError
from app.api.rooms.access import get_room_access_context
from app.api.rooms.dependencies import (
    get_combat_service,
    get_session_service,
    get_table_event_service,
)
from app.content import load_default_content_registry
from app.db import metadata
from app.domain.character.fixture import (
    build_p0_fighter_wizard_fixture,
    build_p0_fighter_wizard_state,
)
from app.domain.combat.lifecycle import AddMonsterInput, CombatService, StartCombatInput
from app.domain.rooms.access import hash_secret
from app.domain.rooms.ai_controllers import AIControllerService
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.sessions import SessionService
from app.domain.rooms.table_events import TableEventService
from app.main import app
from app.persistence.characters import (
    CharacterRepository,
    character_states,
    characters,
)
from app.persistence.combat.lifecycle import CombatRepository
from app.persistence.combat.repository import MonsterRepository
from app.persistence.combat.tables import combat_entries, combats
from app.persistence.rooms.ai_controllers import AIControllerGrantRepository
from app.persistence.rooms.session_live import SessionLiveRepository
from app.persistence.rooms.sessions import SessionRepository
from app.persistence.rooms.table_runtime import TableEventRepository, session_events
from app.persistence.rooms.tables import (
    campaign_roster_entries,
    campaign_seats,
    campaigns,
    room_access_sessions,
    room_characters,
    rooms,
    session_participants,
    sessions,
)


@dataclass(frozen=True)
class M05BFixture:
    engine: Engine
    room_id: UUID
    campaign_id: UUID
    s1_id: UUID
    s2_id: UUID
    dm_seat_id: UUID
    p1_seat_id: UUID
    p2_seat_id: UUID
    p3_seat_id: UUID
    archived_seat_id: UUID
    owner_access_id: UUID
    h_dm_access_id: UUID
    h1_access_id: UUID
    h2_access_id: UUID
    h3_access_id: UUID
    h_no_seat_access_id: UUID
    h_archived_access_id: UUID
    h9_access_id: UUID
    tokens: dict[str, str]
    event_service: TableEventService
    session_service: SessionService
    combat_service: CombatService
    client: TestClient


def _seed_room_and_campaign(connection, *, room_id: UUID, campaign_id: UUID, code: str, name: str, now: datetime) -> None:
    connection.execute(
        insert(rooms).values(
            id=room_id,
            code=code,
            name=name,
            password_salt=b"s" * 32,
            password_hash=b"h" * 64,
            owner_key_hash=b"o" * 32,
            dm_key_hash=b"d" * 32,
            active_campaign_id=None,
            created_at=now,
            updated_at=now,
        )
    )
    connection.execute(
        insert(campaigns).values(
            id=campaign_id,
            room_id=room_id,
            name="M05-B Campaign",
            ruleset="dnd5e-2014",
            status="active",
            created_at=now,
            updated_at=now,
        )
    )
    connection.execute(
        update(rooms).where(rooms.c.id == room_id).values(active_campaign_id=campaign_id)
    )


def _insert_access_session(
    connection,
    *,
    access_id: UUID,
    room_id: UUID,
    authority: str,
    display_name: str,
    token: str,
    now: datetime,
) -> None:
    connection.execute(
        insert(room_access_sessions).values(
            id=access_id,
            room_id=room_id,
            authority=authority,
            token_hash=hash_secret(token),
            display_name=display_name,
            created_at=now,
            last_seen_at=now,
            revoked_at=None,
        )
    )


@pytest.fixture
def m05b_fixture():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata.create_all(engine)

    event_repository = TableEventRepository(engine)
    event_service = TableEventService(event_repository)
    session_repository = SessionRepository(engine)
    session_live_repository = SessionLiveRepository(engine)
    session_service = SessionService(session_repository, session_live_repository, event_service)
    grant_repository = AIControllerGrantRepository(engine)
    controller_service = AIControllerService(grant_repository, event_service)

    registry = load_default_content_registry()
    character_repository = CharacterRepository(engine, registry)
    monster_repository = MonsterRepository(engine)
    combat_repository = CombatRepository(engine, event_repository)
    combat_service = CombatService(
        repository=combat_repository,
        table_event_service=event_service,
        character_repository=character_repository,
        monster_repository=monster_repository,
        registry=registry,
    )

    now = datetime.now(timezone.utc)
    room_id, campaign_id = uuid4(), uuid4()
    owner_access_id = uuid4()
    h_dm_access_id = uuid4()
    h1_access_id = uuid4()
    h2_access_id = uuid4()
    h3_access_id = uuid4()
    h_no_seat_access_id = uuid4()
    h_archived_access_id = uuid4()
    h9_access_id = uuid4()

    tokens = {
        "owner": "token-owner",
        "h_dm": "token-h-dm",
        "h1": "token-h1",
        "h2": "token-h2",
        "h3": "token-h3",
        "h_no_seat": "token-no-seat",
        "h_archived": "token-archived",
        "h9": "token-h9",
    }

    dm_seat_id = uuid4()
    p1_seat_id = uuid4()
    p2_seat_id = uuid4()
    p3_seat_id = uuid4()
    archived_seat_id = uuid4()
    p1_build = build_p0_fighter_wizard_fixture()
    p1_char = character_repository.create_character(
        name="Fighter P1",
        build=p1_build,
        state=build_p0_fighter_wizard_state(p1_build),
    )
    p1_character_id = p1_char.id

    with engine.begin() as conn:
        _seed_room_and_campaign(conn, room_id=room_id, campaign_id=campaign_id, code="M05B", name="M05-B Room", now=now)

        for acc_id, auth, name, tok_key in [
            (owner_access_id, "owner", "Owner", "owner"),
            (h_dm_access_id, "dm", "Human DM", "h_dm"),
            (h1_access_id, "member", "Player 1", "h1"),
            (h2_access_id, "member", "Player 2", "h2"),
            (h3_access_id, "member", "Player 3", "h3"),
            (h_no_seat_access_id, "member", "No Seat Member", "h_no_seat"),
            (h_archived_access_id, "member", "Archived Seat Member", "h_archived"),
            (h9_access_id, "member", "Player 9", "h9"),
        ]:
            _insert_access_session(
                conn,
                access_id=acc_id,
                room_id=room_id,
                authority=auth,
                display_name=name,
                token=tokens[tok_key],
                now=now,
            )

        # Attach character for P1
        conn.execute(insert(room_characters).values(room_id=room_id, character_id=p1_character_id, created_at=now))
        conn.execute(insert(campaign_roster_entries).values(campaign_id=campaign_id, character_id=p1_character_id, status="active", added_at=now, updated_at=now))

        # Seats
        conn.execute(
            insert(campaign_seats).values(
                id=dm_seat_id,
                campaign_id=campaign_id,
                role="dm",
                label="DM Seat",
                controller_kind="none",
                controller_access_session_id=None,
                ai_controller_grant_id=None,
                controller_epoch=0,
                selected_character_id=None,
                archived_at=None,
                created_at=now,
                updated_at=now,
            )
        )
        conn.execute(
            insert(campaign_seats).values(
                id=p1_seat_id,
                campaign_id=campaign_id,
                role="player",
                label="Seat P1",
                controller_kind="none",
                controller_access_session_id=None,
                ai_controller_grant_id=None,
                controller_epoch=0,
                selected_character_id=p1_character_id,
                archived_at=None,
                created_at=now,
                updated_at=now,
            )
        )
        conn.execute(
            insert(campaign_seats).values(
                id=p2_seat_id,
                campaign_id=campaign_id,
                role="player",
                label="Seat P2",
                controller_kind="none",
                controller_access_session_id=None,
                ai_controller_grant_id=None,
                controller_epoch=0,
                selected_character_id=None,
                archived_at=None,
                created_at=now,
                updated_at=now,
            )
        )
        conn.execute(
            insert(campaign_seats).values(
                id=p3_seat_id,
                campaign_id=campaign_id,
                role="player",
                label="Seat P3",
                controller_kind="none",
                controller_access_session_id=None,
                ai_controller_grant_id=None,
                controller_epoch=0,
                selected_character_id=None,
                archived_at=None,
                created_at=now,
                updated_at=now,
            )
        )
        conn.execute(
            insert(campaign_seats).values(
                id=archived_seat_id,
                campaign_id=campaign_id,
                role="player",
                label="Archived Seat",
                controller_kind="human",
                controller_access_session_id=h_archived_access_id,
                ai_controller_grant_id=None,
                controller_epoch=0,
                selected_character_id=None,
                archived_at=now,
                created_at=now,
                updated_at=now,
            )
        )

    # Start Session 1 as AI DM
    dm_issued = controller_service.configure_pre_session_ai_dm(
        room_id=room_id,
        campaign_id=campaign_id,
        seat_id=dm_seat_id,
    )
    s1 = session_service.start_session_as_ai_dm(
        room_id,
        campaign_id,
        grant_id=dm_issued.grant_id,
        generation=dm_issued.generation,
    )

    with engine.begin() as conn:
        # P1 is already in session_participants from start_session_as_ai_dm lobby snapshot
        # P2 is participant in s1 (no character selected during start, so add participant explicitly)
        conn.execute(
            insert(session_participants).values(
                id=uuid4(),
                session_id=s1.id,
                seat_id=p2_seat_id,
                role_snapshot="player",
                controller_kind_at_join="none",
                controller_access_session_id_at_join=None,
                controller_ai_grant_id_at_join=None,
                controller_generation_at_join=None,
                active_character_id=None,
                joined_at=now,
                left_at=None,
            )
        )
        # P3 is NOT participant in s1

    # Append events in s1
    event_repository.append(
        room_id=room_id,
        campaign_id=campaign_id,
        session_id=s1.id,
        kind="exploration.narration",
        acting_seat_id=dm_seat_id,
        subject_seat_id=None,
        subject_character_id=None,
        execution_mode="self",
        visibility="public",
        recipient_seat_ids=(),
        payload_version=1,
        payload={"text": "A dark cave opens before you."},
        idempotency_key="s1-narration",
    )
    event_repository.append(
        room_id=room_id,
        campaign_id=campaign_id,
        session_id=s1.id,
        kind="exploration.secret",
        acting_seat_id=dm_seat_id,
        subject_seat_id=None,
        subject_character_id=None,
        execution_mode="self",
        visibility="dm_only",
        recipient_seat_ids=(),
        payload_version=1,
        payload={"text": "A trap is hidden on the floor."},
        idempotency_key="s1-secret",
    )
    event_repository.append(
        room_id=room_id,
        campaign_id=campaign_id,
        session_id=s1.id,
        kind="exploration.whisper",
        acting_seat_id=dm_seat_id,
        subject_seat_id=None,
        subject_character_id=None,
        execution_mode="self",
        visibility="seat_private",
        recipient_seat_ids=(p1_seat_id,),
        payload_version=1,
        payload={"text": "You hear a faint ticking sound."},
        idempotency_key="s1-whisper",
    )
    event_repository.append(
        room_id=room_id,
        campaign_id=campaign_id,
        session_id=s1.id,
        kind="combat.damage_applied",
        acting_seat_id=dm_seat_id,
        subject_seat_id=None,
        subject_character_id=None,
        execution_mode="self",
        visibility="public",
        recipient_seat_ids=(),
        payload_version=1,
        payload={
            "target_is_hostile": True,
            "amount": 5,
            "target_entry_id": str(uuid4()),
            "target_injury_level": "healthy",
            "after": {"current_hp": 15, "max_hp": 20},
            "current_hp": 15,
            "max_hp": 20,
        },
        idempotency_key="s1-combat",
    )

    # Owner End session 1
    owner_context = RoomAccessContext(
        room_id=room_id,
        access_session_id=owner_access_id,
        authority=RoomAccessAuthority.OWNER,
    )
    session_service.end_session(room_id, campaign_id, s1.id, owner_context)

    # Reassign seats to humans
    with engine.begin() as conn:
        conn.execute(
            update(campaign_seats)
            .where(campaign_seats.c.id == dm_seat_id)
            .values(
                controller_kind="human",
                controller_access_session_id=h_dm_access_id,
                ai_controller_grant_id=None,
                controller_epoch=1,
            )
        )
        conn.execute(
            update(campaign_seats)
            .where(campaign_seats.c.id == p1_seat_id)
            .values(
                controller_kind="human",
                controller_access_session_id=h1_access_id,
                ai_controller_grant_id=None,
                controller_epoch=1,
            )
        )
        conn.execute(
            update(campaign_seats)
            .where(campaign_seats.c.id == p2_seat_id)
            .values(
                controller_kind="human",
                controller_access_session_id=h2_access_id,
                ai_controller_grant_id=None,
                controller_epoch=1,
            )
        )
        conn.execute(
            update(campaign_seats)
            .where(campaign_seats.c.id == p3_seat_id)
            .values(
                controller_kind="human",
                controller_access_session_id=h3_access_id,
                ai_controller_grant_id=None,
                controller_epoch=1,
            )
        )

    # Start Session 2 with human DM
    h_dm_context = RoomAccessContext(
        room_id=room_id,
        access_session_id=h_dm_access_id,
        authority=RoomAccessAuthority.DM,
    )
    s2 = session_service.start_session(room_id, campaign_id, h_dm_context)

    # Append a public event in s2
    event_repository.append(
        room_id=room_id,
        campaign_id=campaign_id,
        session_id=s2.id,
        kind="exploration.narration",
        acting_seat_id=dm_seat_id,
        subject_seat_id=None,
        subject_character_id=None,
        execution_mode="self",
        visibility="public",
        recipient_seat_ids=(),
        payload_version=1,
        payload={"text": "Session 2 begins."},
        idempotency_key="s2-narration",
    )

    # Start Quick Combat in s2
    dm_actor_s2 = event_service.resolve_human_actor(
        room_id=room_id,
        campaign_id=campaign_id,
        session_id=s2.id,
        context=h_dm_context,
    )
    combat_service.start_quick_combat(dm_actor_s2, StartCombatInput(idempotency_key="s2-combat-start"))
    monster_inst = monster_repository.create_instance(
        campaign_id=campaign_id,
        name="Orc Raider",
        rules_snapshot={"armor_class": 13, "max_hp": 15, "speed": {"walk": 30}},
        current_hp=15,
    )
    combat_service.add_monster(
        dm_actor_s2,
        AddMonsterInput(monster_instance_id=monster_inst.id, idempotency_key="s2-add-orc"),
    )

    token_to_context = {
        tokens["owner"]: owner_context,
        tokens["h_dm"]: h_dm_context,
        tokens["h1"]: RoomAccessContext(room_id=room_id, access_session_id=h1_access_id, authority=RoomAccessAuthority.MEMBER),
        tokens["h2"]: RoomAccessContext(room_id=room_id, access_session_id=h2_access_id, authority=RoomAccessAuthority.MEMBER),
        tokens["h3"]: RoomAccessContext(room_id=room_id, access_session_id=h3_access_id, authority=RoomAccessAuthority.MEMBER),
        tokens["h_no_seat"]: RoomAccessContext(room_id=room_id, access_session_id=h_no_seat_access_id, authority=RoomAccessAuthority.MEMBER),
        tokens["h_archived"]: RoomAccessContext(room_id=room_id, access_session_id=h_archived_access_id, authority=RoomAccessAuthority.MEMBER),
        tokens["h9"]: RoomAccessContext(room_id=room_id, access_session_id=h9_access_id, authority=RoomAccessAuthority.MEMBER),
    }

    def _override_access_context(request: Request) -> RoomAccessContext:
        auth = request.headers.get("authorization", "")
        scheme, _, token = auth.partition(" ")
        token_clean = token.strip()
        if token_clean in token_to_context:
            return token_to_context[token_clean]
        raise APIError(401, "room_access_required", "Room access token is required")

    app.state._state.clear()
    app.state.content_registry = registry
    app.state.character_engine = engine
    app.state.table_event_service = event_service
    app.state.session_service = session_service
    app.state.combat_service = combat_service
    app.dependency_overrides[get_database_engine] = lambda: engine
    app.dependency_overrides[get_room_access_context] = _override_access_context
    app.dependency_overrides[get_table_event_service] = lambda: event_service
    app.dependency_overrides[get_session_service] = lambda: session_service
    app.dependency_overrides[get_combat_service] = lambda: combat_service

    client = TestClient(app)
    fixture_obj = M05BFixture(
        engine=engine,
        room_id=room_id,
        campaign_id=campaign_id,
        s1_id=s1.id,
        s2_id=s2.id,
        dm_seat_id=dm_seat_id,
        p1_seat_id=p1_seat_id,
        p2_seat_id=p2_seat_id,
        p3_seat_id=p3_seat_id,
        archived_seat_id=archived_seat_id,
        owner_access_id=owner_access_id,
        h_dm_access_id=h_dm_access_id,
        h1_access_id=h1_access_id,
        h2_access_id=h2_access_id,
        h3_access_id=h3_access_id,
        h_no_seat_access_id=h_no_seat_access_id,
        h_archived_access_id=h_archived_access_id,
        h9_access_id=h9_access_id,
        tokens=tokens,
        event_service=event_service,
        session_service=session_service,
        combat_service=combat_service,
        client=client,
    )

    try:
        yield fixture_obj
    finally:
        app.dependency_overrides.clear()
        app.state._state.clear()
        engine.dispose()


def test_human_dm_seat_holder_reads_ended_ai_dm_session_with_dm_audience(m05b_fixture: M05BFixture) -> None:
    url = f"/api/rooms/{m05b_fixture.room_id}/campaigns/{m05b_fixture.campaign_id}/sessions/{m05b_fixture.s1_id}/events/history?before=999"
    resp = m05b_fixture.client.get(url, headers={"Authorization": f"Bearer {m05b_fixture.tokens['h_dm']}"})
    assert resp.status_code == 200
    events = resp.json()["events"]
    kinds = [e["kind"] for e in events]
    assert "exploration.narration" in kinds
    assert "exploration.secret" in kinds
    assert "exploration.whisper" in kinds
    assert "combat.damage_applied" in kinds
    combat_event = next(e for e in events if e["kind"] == "combat.damage_applied")
    assert combat_event["payload"]["after"]["current_hp"] == 15
    assert combat_event["payload"]["current_hp"] == 15
    assert combat_event["payload"]["max_hp"] == 20


def test_player_seat_holder_reads_ended_session_seat_scoped(m05b_fixture: M05BFixture) -> None:
    url = f"/api/rooms/{m05b_fixture.room_id}/campaigns/{m05b_fixture.campaign_id}/sessions/{m05b_fixture.s1_id}/events/history?before=999"
    resp = m05b_fixture.client.get(url, headers={"Authorization": f"Bearer {m05b_fixture.tokens['h1']}"})
    assert resp.status_code == 200
    events = resp.json()["events"]
    kinds = [e["kind"] for e in events]
    assert "exploration.narration" in kinds
    assert "exploration.whisper" in kinds
    assert "combat.damage_applied" in kinds
    assert "exploration.secret" not in kinds
    combat_event = next(e for e in events if e["kind"] == "combat.damage_applied")
    assert "after" not in combat_event["payload"]
    assert "current_hp" not in combat_event["payload"]
    assert "max_hp" not in combat_event["payload"]
    assert combat_event["payload"]["amount"] == 5


def test_other_player_cannot_see_p1_private_events_in_ended_session(m05b_fixture: M05BFixture) -> None:
    url = f"/api/rooms/{m05b_fixture.room_id}/campaigns/{m05b_fixture.campaign_id}/sessions/{m05b_fixture.s1_id}/events/history?before=999"
    resp = m05b_fixture.client.get(url, headers={"Authorization": f"Bearer {m05b_fixture.tokens['h2']}"})
    assert resp.status_code == 200
    events = resp.json()["events"]
    kinds = [e["kind"] for e in events]
    assert "exploration.narration" in kinds
    assert "combat.damage_applied" in kinds
    assert "exploration.secret" not in kinds
    assert "exploration.whisper" not in kinds


def test_reader_without_campaign_seat_gets_404_on_ended_session(m05b_fixture: M05BFixture) -> None:
    url = f"/api/rooms/{m05b_fixture.room_id}/campaigns/{m05b_fixture.campaign_id}/sessions/{m05b_fixture.s1_id}/events/history?before=999"
    resp = m05b_fixture.client.get(url, headers={"Authorization": f"Bearer {m05b_fixture.tokens['h_no_seat']}"})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "session_not_found"


def test_archived_seat_does_not_grant_history_scope(m05b_fixture: M05BFixture) -> None:
    url = f"/api/rooms/{m05b_fixture.room_id}/campaigns/{m05b_fixture.campaign_id}/sessions/{m05b_fixture.s1_id}/events/history?before=999"
    resp = m05b_fixture.client.get(url, headers={"Authorization": f"Bearer {m05b_fixture.tokens['h_archived']}"})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "session_not_found"


def test_seat_holder_who_never_joined_ended_session_reads_public_only(m05b_fixture: M05BFixture) -> None:
    url = f"/api/rooms/{m05b_fixture.room_id}/campaigns/{m05b_fixture.campaign_id}/sessions/{m05b_fixture.s1_id}/events/history?before=999"
    resp = m05b_fixture.client.get(url, headers={"Authorization": f"Bearer {m05b_fixture.tokens['h3']}"})
    assert resp.status_code == 200
    events = resp.json()["events"]
    kinds = [e["kind"] for e in events]
    assert "exploration.narration" in kinds
    assert "combat.damage_applied" in kinds
    assert "exploration.secret" not in kinds
    assert "exploration.whisper" not in kinds


def test_history_scope_recomputed_after_seat_reassignment(m05b_fixture: M05BFixture) -> None:
    url = f"/api/rooms/{m05b_fixture.room_id}/campaigns/{m05b_fixture.campaign_id}/sessions/{m05b_fixture.s1_id}/events/history?before=999"
    resp1 = m05b_fixture.client.get(url, headers={"Authorization": f"Bearer {m05b_fixture.tokens['h1']}"})
    assert resp1.status_code == 200

    # Reassign P1 to H9
    with m05b_fixture.engine.begin() as conn:
        conn.execute(
            update(campaign_seats)
            .where(campaign_seats.c.id == m05b_fixture.p1_seat_id)
            .values(
                controller_access_session_id=m05b_fixture.h9_access_id,
                controller_epoch=campaign_seats.c.controller_epoch + 1,
            )
        )

    # H1 now gets 404
    resp_h1 = m05b_fixture.client.get(url, headers={"Authorization": f"Bearer {m05b_fixture.tokens['h1']}"})
    assert resp_h1.status_code == 404
    assert resp_h1.json()["error"]["code"] == "session_not_found"

    # H9 now sees P1's seat_private
    resp_h9 = m05b_fixture.client.get(url, headers={"Authorization": f"Bearer {m05b_fixture.tokens['h9']}"})
    assert resp_h9.status_code == 200
    events = resp_h9.json()["events"]
    kinds = [e["kind"] for e in events]
    assert "exploration.whisper" in kinds


def test_active_session_history_endpoint_unchanged(m05b_fixture: M05BFixture) -> None:
    url = f"/api/rooms/{m05b_fixture.room_id}/campaigns/{m05b_fixture.campaign_id}/sessions/{m05b_fixture.s2_id}/events/history?before=999&limit=100"
    resp = m05b_fixture.client.get(url, headers={"Authorization": f"Bearer {m05b_fixture.tokens['h_dm']}"})
    assert resp.status_code == 200

    dm_context = RoomAccessContext(
        room_id=m05b_fixture.room_id,
        access_session_id=m05b_fixture.h_dm_access_id,
        authority=RoomAccessAuthority.DM,
    )
    actor_s2 = m05b_fixture.event_service.resolve_human_actor(
        room_id=m05b_fixture.room_id,
        campaign_id=m05b_fixture.campaign_id,
        session_id=m05b_fixture.s2_id,
        context=dm_context,
    )
    expected_page = m05b_fixture.event_service.list_before(actor_s2, before_seq=999, limit=100)
    assert resp.json() == expected_page.model_dump(mode="json")

    binding_s1_before = m05b_fixture.event_service.repository.resolve_human_actor(
        room_id=m05b_fixture.room_id,
        campaign_id=m05b_fixture.campaign_id,
        session_id=m05b_fixture.s1_id,
        access_session_id=m05b_fixture.h_dm_access_id,
    )
    binding_s2_before = m05b_fixture.event_service.repository.resolve_human_actor(
        room_id=m05b_fixture.room_id,
        campaign_id=m05b_fixture.campaign_id,
        session_id=m05b_fixture.s2_id,
        access_session_id=m05b_fixture.h_dm_access_id,
    )
    assert binding_s1_before is not None
    assert binding_s2_before is not None
    assert m05b_fixture.event_service.repository.actor_binding_is_current(binding_s1_before) is True
    assert m05b_fixture.event_service.repository.actor_binding_is_current(binding_s2_before) is True

    # Hit history route for s1 and s2
    m05b_fixture.client.get(
        f"/api/rooms/{m05b_fixture.room_id}/campaigns/{m05b_fixture.campaign_id}/sessions/{m05b_fixture.s1_id}/events/history?before=999",
        headers={"Authorization": f"Bearer {m05b_fixture.tokens['h_dm']}"},
    )
    m05b_fixture.client.get(
        f"/api/rooms/{m05b_fixture.room_id}/campaigns/{m05b_fixture.campaign_id}/sessions/{m05b_fixture.s2_id}/events/history?before=999",
        headers={"Authorization": f"Bearer {m05b_fixture.tokens['h_dm']}"},
    )

    binding_s1_after = m05b_fixture.event_service.repository.resolve_human_actor(
        room_id=m05b_fixture.room_id,
        campaign_id=m05b_fixture.campaign_id,
        session_id=m05b_fixture.s1_id,
        access_session_id=m05b_fixture.h_dm_access_id,
    )
    binding_s2_after = m05b_fixture.event_service.repository.resolve_human_actor(
        room_id=m05b_fixture.room_id,
        campaign_id=m05b_fixture.campaign_id,
        session_id=m05b_fixture.s2_id,
        access_session_id=m05b_fixture.h_dm_access_id,
    )
    assert binding_s1_after == binding_s1_before
    assert binding_s2_after == binding_s2_before
    assert m05b_fixture.event_service.repository.actor_binding_is_current(binding_s1_after) is True
    assert m05b_fixture.event_service.repository.actor_binding_is_current(binding_s2_after) is True


def test_ended_session_rejects_writes_for_history_reader(m05b_fixture: M05BFixture) -> None:
    headers = {"Authorization": f"Bearer {m05b_fixture.tokens['h_dm']}"}
    base_s1 = f"/api/rooms/{m05b_fixture.room_id}/campaigns/{m05b_fixture.campaign_id}/sessions/{m05b_fixture.s1_id}"

    stage_before = m05b_fixture.client.get(f"{base_s1}/stage", headers=headers).json()
    with m05b_fixture.engine.connect() as conn:
        events_count_before = conn.execute(select(func.count(session_events.c.id))).scalar_one()
        combats_count_before = conn.execute(select(func.count(combats.c.id))).scalar_one()
        combat_entries_count_before = conn.execute(select(func.count(combat_entries.c.id))).scalar_one()

    # 1. exploration input POST
    resp_exp = m05b_fixture.client.post(f"{base_s1}/exploration", json={"kind": "narration", "text": "Hello world"}, headers=headers)
    assert resp_exp.status_code in (403, 404, 409)

    # 2. stage PUT
    resp_stage = m05b_fixture.client.put(
        f"{base_s1}/stage",
        json={"text": "New stage", "expected_revision": 0},
        headers=headers,
    )
    assert resp_stage.status_code in (403, 404, 409)

    # 3. roll request POST
    resp_roll = m05b_fixture.client.post(
        f"{base_s1}/checks",
        json={"target_seat_ids": [str(m05b_fixture.p1_seat_id)], "request_type": "ability", "ability_ref": "strength"},
        headers=headers,
    )
    assert resp_roll.status_code in (403, 404, 409)

    # 4. late-join POST
    resp_join = m05b_fixture.client.post(f"{base_s1}/late-join", json={"seat_id": str(m05b_fixture.p3_seat_id)}, headers=headers)
    assert resp_join.status_code in (404, 409)

    # 5. Combat mutation route with s1 session id
    resp_combat = m05b_fixture.client.post(f"{base_s1}/combat/turn/advance", json={}, headers=headers)
    assert resp_combat.status_code in (403, 409), resp_combat.json()

    stage_after = m05b_fixture.client.get(f"{base_s1}/stage", headers=headers).json()
    with m05b_fixture.engine.connect() as conn:
        events_count_after = conn.execute(select(func.count(session_events.c.id))).scalar_one()
        combats_count_after = conn.execute(select(func.count(combats.c.id))).scalar_one()
        combat_entries_count_after = conn.execute(select(func.count(combat_entries.c.id))).scalar_one()

    assert stage_after["revision"] == stage_before["revision"]
    assert events_count_after == events_count_before
    assert combats_count_after == combats_count_before
    assert combat_entries_count_after == combat_entries_count_before


def test_history_scope_does_not_grant_combat_detail_on_old_session_url(m05b_fixture: M05BFixture) -> None:
    resp_h3 = m05b_fixture.client.get(
        f"/api/rooms/{m05b_fixture.room_id}/campaigns/{m05b_fixture.campaign_id}/sessions/{m05b_fixture.s1_id}/combat/detail",
        headers={"Authorization": f"Bearer {m05b_fixture.tokens['h3']}"},
    )
    assert resp_h3.status_code == 404
    assert resp_h3.json()["error"]["code"] == "session_not_found"

    resp_h_dm = m05b_fixture.client.get(
        f"/api/rooms/{m05b_fixture.room_id}/campaigns/{m05b_fixture.campaign_id}/sessions/{m05b_fixture.s1_id}/combat/detail",
        headers={"Authorization": f"Bearer {m05b_fixture.tokens['h_dm']}"},
    )
    # Pre-M05 behaviour, unchanged: the DM Seat was a participant of s1, so the
    # existing actor path resolves H_DM, but s1 was run by an AI DM so
    # is_current_dm is False and the Campaign's active Combat is the Player view.
    assert resp_h_dm.status_code == 200
    hostile = [c for c in resp_h_dm.json()["combatants"] if c["is_hostile"]]
    assert len(hostile) == 1
    assert "current_hp" not in hostile[0]["projection"]
    assert "max_hp" not in hostile[0]["projection"]

    resp_hist = m05b_fixture.client.get(
        f"/api/rooms/{m05b_fixture.room_id}/campaigns/{m05b_fixture.campaign_id}/sessions/{m05b_fixture.s1_id}/events/history?before=999",
        headers={"Authorization": f"Bearer {m05b_fixture.tokens['h_dm']}"},
    )
    assert resp_hist.status_code == 200
    kinds = [e["kind"] for e in resp_hist.json()["events"]]
    assert "exploration.secret" in kinds


def test_history_scope_does_not_grant_stage_roll_pending_reads_on_old_session_url(m05b_fixture: M05BFixture) -> None:
    base_s1 = f"/api/rooms/{m05b_fixture.room_id}/campaigns/{m05b_fixture.campaign_id}/sessions/{m05b_fixture.s1_id}"
    headers_h3 = {"Authorization": f"Bearer {m05b_fixture.tokens['h3']}"}
    headers_h_dm = {"Authorization": f"Bearer {m05b_fixture.tokens['h_dm']}"}

    resp_h3_stage = m05b_fixture.client.get(f"{base_s1}/stage", headers=headers_h3)
    assert resp_h3_stage.status_code == 404
    assert resp_h3_stage.json()["error"]["code"] == "session_not_found"

    resp_h3_rolls = m05b_fixture.client.get(f"{base_s1}/roll-requests", headers=headers_h3)
    assert resp_h3_rolls.status_code == 404
    assert resp_h3_rolls.json()["error"]["code"] == "session_not_found"

    resp_h3_pending = m05b_fixture.client.get(f"{base_s1}/pending-actions", headers=headers_h3)
    assert resp_h3_pending.status_code == 404
    assert resp_h3_pending.json()["error"]["code"] == "session_not_found"

    resp_h_dm_stage = m05b_fixture.client.get(f"{base_s1}/stage", headers=headers_h_dm)
    assert resp_h_dm_stage.status_code == 200, resp_h_dm_stage.json()

    resp_h_dm_rolls = m05b_fixture.client.get(f"{base_s1}/roll-requests", headers=headers_h_dm)
    assert resp_h_dm_rolls.status_code == 200

    resp_h_dm_pending = m05b_fixture.client.get(f"{base_s1}/pending-actions", headers=headers_h_dm)
    assert resp_h_dm_pending.status_code == 200
