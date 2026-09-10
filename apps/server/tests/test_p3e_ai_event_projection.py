from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import create_engine, insert, update
from sqlalchemy.pool import StaticPool

from app.db import metadata
from app.domain.rooms.ai_controller_tokens import mint_ai_controller_token
from app.domain.rooms.ai_controllers import AIControllerService
from app.domain.rooms.ai_tools import AIToolApplicationService, EventsInput, WaitEventsInput
from app.domain.rooms.table_events import TableEventService
from app.persistence.characters import characters
from app.persistence.rooms.ai_controllers import AIControllerGrantRepository
from app.persistence.rooms.table_runtime import TableEventRepository
from app.persistence.rooms.tables import (
    campaign_seats,
    campaigns,
    room_access_sessions,
    rooms,
    session_participants,
    sessions,
)


def _engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata.create_all(engine)
    return engine


def _seed_ai_player(engine):
    now = datetime.now(timezone.utc)
    room_id, campaign_id, session_id = uuid4(), uuid4(), uuid4()
    dm_access_id, player_access_id = uuid4(), uuid4()
    dm_seat_id, player_seat_id, other_seat_id = uuid4(), uuid4(), uuid4()
    character_id = uuid4()

    with engine.begin() as connection:
        connection.execute(
            insert(rooms).values(
                id=room_id,
                code="P3EEVT1",
                name="P3E event projection",
                password_salt=b"s" * 32,
                password_hash=b"p" * 64,
                owner_key_hash=b"o" * 32,
                dm_key_hash=b"d" * 32,
                active_campaign_id=None,
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            insert(room_access_sessions),
            [
                {
                    "id": dm_access_id,
                    "room_id": room_id,
                    "authority": "dm",
                    "token_hash": b"d" * 32,
                    "display_name": "DM",
                    "created_at": now,
                    "last_seen_at": now,
                    "revoked_at": None,
                },
                {
                    "id": player_access_id,
                    "room_id": room_id,
                    "authority": "member",
                    "token_hash": b"p" * 32,
                    "display_name": "Player",
                    "created_at": now,
                    "last_seen_at": now,
                    "revoked_at": None,
                },
            ],
        )
        connection.execute(
            insert(characters).values(
                id=character_id,
                name="P3E Hero",
                ruleset="dnd5e-2014",
                current_version_id=None,
                archived_at=None,
            )
        )
        connection.execute(
            insert(campaigns).values(
                id=campaign_id,
                room_id=room_id,
                name="P3E Campaign",
                ruleset="dnd5e-2014",
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            update(rooms).where(rooms.c.id == room_id).values(active_campaign_id=campaign_id)
        )
        connection.execute(
            insert(campaign_seats),
            [
                {
                    "id": dm_seat_id,
                    "campaign_id": campaign_id,
                    "role": "dm",
                    "label": "DM",
                    "controller_kind": "human",
                    "controller_access_session_id": dm_access_id,
                    "ai_controller_grant_id": None,
                    "controller_epoch": 1,
                    "selected_character_id": None,
                    "archived_at": None,
                    "created_at": now,
                    "updated_at": now,
                },
                {
                    "id": player_seat_id,
                    "campaign_id": campaign_id,
                    "role": "player",
                    "label": "Player",
                    "controller_kind": "human",
                    "controller_access_session_id": player_access_id,
                    "ai_controller_grant_id": None,
                    "controller_epoch": 1,
                    "selected_character_id": character_id,
                    "archived_at": None,
                    "created_at": now,
                    "updated_at": now,
                },
                {
                    "id": other_seat_id,
                    "campaign_id": campaign_id,
                    "role": "player",
                    "label": "Other Player",
                    "controller_kind": "none",
                    "controller_access_session_id": None,
                    "ai_controller_grant_id": None,
                    "controller_epoch": 0,
                    "selected_character_id": None,
                    "archived_at": None,
                    "created_at": now,
                    "updated_at": now,
                },
            ],
        )
        connection.execute(
            insert(sessions).values(
                id=session_id,
                campaign_id=campaign_id,
                status="active",
                dm_seat_id=dm_seat_id,
                dm_controller_kind="human",
                dm_controller_access_session_id=dm_access_id,
                dm_controller_ai_grant_id=None,
                dm_controller_generation=None,
                started_at=now,
                ended_at=None,
                created_at=now,
            )
        )
        connection.execute(
            insert(session_participants).values(
                id=uuid4(),
                session_id=session_id,
                seat_id=player_seat_id,
                role_snapshot="player",
                controller_kind_at_join="human",
                controller_access_session_id_at_join=player_access_id,
                controller_ai_grant_id_at_join=None,
                controller_generation_at_join=None,
                active_character_id=character_id,
                joined_at=now,
                left_at=None,
            )
        )

    grant_repo = AIControllerGrantRepository(engine)
    token = mint_ai_controller_token()
    with engine.begin() as connection:
        grant_repo.player_handoff_in_transaction(
            connection,
            grant_id=token.grant_id,
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            seat_id=player_seat_id,
            caller_access_session_id=player_access_id,
            secret_hash=token.secret_hash,
            secret_prefix=token.display_hint,
            temporary_instruction="Keep the scout safe",
            now=now,
        )
    return {
        "room_id": room_id,
        "campaign_id": campaign_id,
        "session_id": session_id,
        "player_seat_id": player_seat_id,
        "other_seat_id": other_seat_id,
        "token": token.plaintext,
        "grant_repo": grant_repo,
    }


def _facade(controller: AIControllerService, events: TableEventService) -> AIToolApplicationService:
    return AIToolApplicationService(
        ai_controller_service=controller,
        session_service=None,  # type: ignore[arg-type]
        stage_service=None,  # type: ignore[arg-type]
        action_service=None,  # type: ignore[arg-type]
        roll_service=None,  # type: ignore[arg-type]
        state_service=None,  # type: ignore[arg-type]
        pending_action_service=None,  # type: ignore[arg-type]
        event_service=events,
        workspace_service=None,  # type: ignore[arg-type]
    )


def _append(
    repository: TableEventRepository,
    ids: dict,
    *,
    kind: str,
    visibility: str,
    payload: dict,
    acting_seat_id=None,
    recipients=(),
):
    return repository.append(
        room_id=ids["room_id"],
        campaign_id=ids["campaign_id"],
        session_id=ids["session_id"],
        kind=kind,
        acting_seat_id=acting_seat_id,
        subject_seat_id=None,
        subject_character_id=None,
        execution_mode="system",
        visibility=visibility,
        recipient_seat_ids=recipients,
        payload_version=1,
        payload=payload,
        idempotency_key=None,
    )


def test_ai_pending_events_use_server_side_audience_projection_and_durable_cursor() -> None:
    engine = _engine()
    try:
        ids = _seed_ai_player(engine)
        event_repo = TableEventRepository(engine)
        events = TableEventService(event_repo)
        controller = AIControllerService(ids["grant_repo"], events)
        facade = _facade(controller, events)

        _append(
            event_repo,
            ids,
            kind="p3e.public",
            visibility="public",
            payload={"value": "public"},
        )
        _append(
            event_repo,
            ids,
            kind="p3e.dm_secret",
            visibility="dm_only",
            payload={"secret_dc": 23},
        )
        _append(
            event_repo,
            ids,
            kind="p3e.actor_private",
            visibility="actor_and_dm",
            acting_seat_id=ids["player_seat_id"],
            payload={"value": "own actor event"},
        )
        _append(
            event_repo,
            ids,
            kind="p3e.other_private",
            visibility="seat_private",
            recipients=(ids["other_seat_id"],),
            payload={"private": "other seat"},
        )
        _append(
            event_repo,
            ids,
            kind="p3e.own_private",
            visibility="seat_private",
            recipients=(ids["player_seat_id"],),
            payload={"private": "own seat"},
        )

        page = facade.get_pending_events(
            ids["token"],
            EventsInput(after_seq=0, limit=50),
        )

        assert [event["kind"] for event in page["events"]] == [
            "p3e.public",
            "p3e.actor_private",
            "p3e.own_private",
        ]
        serialized = str(page)
        assert "secret_dc" not in serialized
        assert "other seat" not in serialized
        assert page["cursor"] == 5
        assert page["current_seq"] == 5
        assert page["has_more"] is False

        resumed = facade.get_pending_events(
            ids["token"],
            EventsInput(after_seq=page["cursor"], limit=50),
        )
        assert resumed["events"] == []
        assert resumed["cursor"] == 5
        assert resumed["current_seq"] == 5
    finally:
        engine.dispose()


def test_ai_wait_timeout_is_normal_empty_result_and_preserves_cursor() -> None:
    engine = _engine()
    try:
        ids = _seed_ai_player(engine)
        event_repo = TableEventRepository(engine)
        events = TableEventService(event_repo)
        controller = AIControllerService(ids["grant_repo"], events)
        facade = _facade(controller, events)

        _append(
            event_repo,
            ids,
            kind="p3e.hidden",
            visibility="dm_only",
            payload={"secret": True},
        )
        first = facade.get_pending_events(
            ids["token"],
            EventsInput(after_seq=0, limit=50),
        )
        assert first["events"] == []
        assert first["cursor"] == 1

        waited = asyncio.run(
            facade.wait_for_event(
                ids["token"],
                WaitEventsInput(after_seq=first["cursor"], limit=50, timeout=0),
            )
        )
        assert waited["events"] == []
        assert waited["after_seq"] == 1
        assert waited["cursor"] == 1
        assert waited["current_seq"] == 1
        assert waited["has_more"] is False
    finally:
        engine.dispose()


def test_ai_reconnect_replays_events_missed_while_no_process_local_waiter_exists() -> None:
    engine = _engine()
    try:
        ids = _seed_ai_player(engine)
        first_repo = TableEventRepository(engine)
        first_events = TableEventService(first_repo)
        first_controller = AIControllerService(AIControllerGrantRepository(engine), first_events)
        first_facade = _facade(first_controller, first_events)

        first_event = _append(
            first_repo,
            ids,
            kind="p3e.before_disconnect",
            visibility="public",
            payload={"value": "seen before disconnect"},
        )
        first_page = first_facade.get_pending_events(
            ids["token"],
            EventsInput(after_seq=0, limit=50),
        )
        assert [event["id"] for event in first_page["events"]] == [str(first_event.id)]
        disconnect_cursor = first_page["cursor"]

        # No notifier/waiter is alive here. Persist one event while the AI is
        # disconnected, then rebuild all P3-E service objects as a fresh process
        # would and resume strictly from the durable cursor.
        disconnected_repo = TableEventRepository(engine)
        missed_event = _append(
            disconnected_repo,
            ids,
            kind="p3e.while_disconnected",
            visibility="public",
            payload={"value": "must replay after reconnect"},
        )

        fresh_events = TableEventService(TableEventRepository(engine))
        fresh_controller = AIControllerService(AIControllerGrantRepository(engine), fresh_events)
        fresh_facade = _facade(fresh_controller, fresh_events)
        resumed = fresh_facade.get_pending_events(
            ids["token"],
            EventsInput(after_seq=disconnect_cursor, limit=50),
        )

        assert [event["id"] for event in resumed["events"]] == [str(missed_event.id)]
        assert resumed["events"][0]["kind"] == "p3e.while_disconnected"
        assert resumed["events"][0]["payload"]["value"] == "must replay after reconnect"
        assert resumed["cursor"] == missed_event.seq
    finally:
        engine.dispose()
