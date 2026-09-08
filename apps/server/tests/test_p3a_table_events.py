from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, insert, update
from sqlalchemy.pool import StaticPool

from app.db import metadata
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.table_events import (
    TableEventAppend,
    TableEventNotFoundError,
    TableEventService,
    TableEventSessionNotActiveError,
    TableEventVisibility,
)
from app.persistence.rooms.table_runtime import (
    MAX_EVENT_SCAN_LIMIT,
    TableEventRepository,
)
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


def _seed_session(engine):
    now = datetime.now(timezone.utc)
    room_id = uuid4()
    campaign_id = uuid4()
    session_id = uuid4()
    access_ids = {
        "owner": uuid4(),
        "dm": uuid4(),
        "player1": uuid4(),
        "player2": uuid4(),
    }
    seat_ids = {
        "dm": uuid4(),
        "player1": uuid4(),
        "player2": uuid4(),
    }

    with engine.begin() as connection:
        connection.execute(
            insert(rooms).values(
                id=room_id,
                code="P3ATEST001",
                name="P3-A table",
                password_salt=b"s" * 32,
                password_hash=b"p" * 64,
                owner_key_hash=b"o" * 32,
                dm_key_hash=b"d" * 32,
                active_campaign_id=None,
                created_at=now,
                updated_at=now,
            )
        )
        for key, authority in (
            ("owner", "owner"),
            ("dm", "dm"),
            ("player1", "member"),
            ("player2", "member"),
        ):
            connection.execute(
                insert(room_access_sessions).values(
                    id=access_ids[key],
                    room_id=room_id,
                    authority=authority,
                    token_hash=(key.encode("utf-8") + b"x" * 32)[:32],
                    display_name=key,
                    created_at=now,
                    last_seen_at=now,
                    revoked_at=None,
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
        connection.execute(
            update(rooms)
            .where(rooms.c.id == room_id)
            .values(active_campaign_id=campaign_id)
        )
        connection.execute(
            insert(campaign_seats),
            [
                {
                    "id": seat_ids["dm"],
                    "campaign_id": campaign_id,
                    "role": "dm",
                    "label": "DM",
                    "controller_kind": "human",
                    "controller_access_session_id": access_ids["dm"],
                    "selected_character_id": None,
                    "archived_at": None,
                    "created_at": now,
                    "updated_at": now,
                },
                {
                    "id": seat_ids["player1"],
                    "campaign_id": campaign_id,
                    "role": "player",
                    "label": "Player 1",
                    "controller_kind": "human",
                    "controller_access_session_id": access_ids["player1"],
                    "selected_character_id": None,
                    "archived_at": None,
                    "created_at": now,
                    "updated_at": now,
                },
                {
                    "id": seat_ids["player2"],
                    "campaign_id": campaign_id,
                    "role": "player",
                    "label": "Player 2",
                    "controller_kind": "human",
                    "controller_access_session_id": access_ids["player2"],
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
                dm_seat_id=seat_ids["dm"],
                dm_controller_kind="human",
                dm_controller_access_session_id=access_ids["dm"],
                started_at=now,
                ended_at=None,
                created_at=now,
            )
        )
        connection.execute(
            insert(session_participants),
            [
                {
                    "id": uuid4(),
                    "session_id": session_id,
                    "seat_id": seat_ids["dm"],
                    "role_snapshot": "dm",
                    "controller_kind_at_join": "human",
                    "controller_access_session_id_at_join": access_ids["dm"],
                    "active_character_id": None,
                    "joined_at": now,
                    "left_at": None,
                },
                {
                    "id": uuid4(),
                    "session_id": session_id,
                    "seat_id": seat_ids["player1"],
                    "role_snapshot": "player",
                    "controller_kind_at_join": "human",
                    "controller_access_session_id_at_join": access_ids["player1"],
                    "active_character_id": None,
                    "joined_at": now,
                    "left_at": None,
                },
                {
                    "id": uuid4(),
                    "session_id": session_id,
                    "seat_id": seat_ids["player2"],
                    "role_snapshot": "player",
                    "controller_kind_at_join": "human",
                    "controller_access_session_id_at_join": access_ids["player2"],
                    "active_character_id": None,
                    "joined_at": now,
                    "left_at": None,
                },
            ],
        )
    return room_id, campaign_id, session_id, access_ids, seat_ids


def _context(room_id: UUID, access_session_id: UUID, authority: str) -> RoomAccessContext:
    return RoomAccessContext(
        room_id=room_id,
        access_session_id=access_session_id,
        authority=RoomAccessAuthority(authority),
    )


def _actors(service, room_id, campaign_id, session_id, access_ids):
    return {
        "dm": service.resolve_human_actor(
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            context=_context(room_id, access_ids["dm"], "dm"),
        ),
        "player1": service.resolve_human_actor(
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            context=_context(room_id, access_ids["player1"], "member"),
        ),
        "player2": service.resolve_human_actor(
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            context=_context(room_id, access_ids["player2"], "member"),
        ),
    }


def test_event_sequence_idempotency_cursor_and_bounded_scan() -> None:
    engine = _engine()
    try:
        room_id, campaign_id, session_id, access_ids, _seat_ids = _seed_session(engine)
        repository = TableEventRepository(engine)
        service = TableEventService(repository)
        actors = _actors(service, room_id, campaign_id, session_id, access_ids)
        dm = actors["dm"]

        first = service.append_event(
            dm,
            TableEventAppend(
                kind="diagnostic.first",
                payload={"schema": "p3a"},
                idempotency_key="same-request",
            ),
        )
        replay = service.append_event(
            dm,
            TableEventAppend(
                kind="diagnostic.first",
                payload={"schema": "p3a"},
                idempotency_key="same-request",
            ),
        )
        second = service.append_event(
            dm,
            TableEventAppend(kind="diagnostic.second", payload={"n": 2}),
        )

        assert first.id == replay.id
        assert first.seq == replay.seq == 1
        assert second.seq == 2
        cursor = service.current_cursor(dm)
        assert cursor.revision == 2
        assert cursor.last_event_seq == 2

        page1 = service.list_after(actors["player1"], after_seq=0, limit=1)
        assert [event.seq for event in page1.events] == [1]
        assert page1.cursor == 1
        assert page1.current_seq == 2
        assert page1.has_more is True

        page2 = service.list_after(actors["player1"], after_seq=page1.cursor, limit=1)
        assert [event.seq for event in page2.events] == [2]
        assert page2.cursor == 2
        assert page2.has_more is False

        for number in range(3, MAX_EVENT_SCAN_LIMIT + 8):
            repository.append(
                room_id=room_id,
                campaign_id=campaign_id,
                session_id=session_id,
                kind="diagnostic.bulk",
                acting_seat_id=dm.seat_id,
                subject_seat_id=None,
                subject_character_id=None,
                execution_mode="self",
                visibility="public",
                recipient_seat_ids=(),
                payload_version=1,
                payload={"n": number},
                idempotency_key=None,
            )
        raw = repository.list_after(
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            after_seq=0,
            scan_limit=10_000,
        )
        assert len(raw) == MAX_EVENT_SCAN_LIMIT
        assert raw[-1].seq == MAX_EVENT_SCAN_LIMIT
    finally:
        engine.dispose()


def test_server_side_audience_projection_and_owner_nonparticipant_rejection() -> None:
    engine = _engine()
    try:
        room_id, campaign_id, session_id, access_ids, seat_ids = _seed_session(engine)
        service = TableEventService(TableEventRepository(engine))
        actors = _actors(service, room_id, campaign_id, session_id, access_ids)
        dm = actors["dm"]

        service.append_event(
            dm,
            TableEventAppend(kind="diagnostic.public", payload={"visible": "all"}),
        )
        service.append_event(
            dm,
            TableEventAppend(
                kind="diagnostic.dm",
                visibility=TableEventVisibility.DM_ONLY,
                payload={"secret": "dm-only"},
            ),
        )
        service.append_event(
            dm,
            TableEventAppend(
                kind="diagnostic.actor",
                acting_seat_id=seat_ids["player1"],
                visibility=TableEventVisibility.ACTOR_AND_DM,
                payload={"secret": "actor"},
            ),
        )
        service.append_event(
            dm,
            TableEventAppend(
                kind="diagnostic.private",
                visibility=TableEventVisibility.SEAT_PRIVATE,
                recipient_seat_ids=(seat_ids["player2"],),
                payload={"secret": "player2"},
            ),
        )

        dm_page = service.list_after(dm, after_seq=0, limit=20)
        p1_page = service.list_after(actors["player1"], after_seq=0, limit=20)
        p2_page = service.list_after(actors["player2"], after_seq=0, limit=20)

        assert [event.kind for event in dm_page.events] == [
            "diagnostic.public",
            "diagnostic.dm",
            "diagnostic.actor",
            "diagnostic.private",
        ]
        assert [event.kind for event in p1_page.events] == [
            "diagnostic.public",
            "diagnostic.actor",
        ]
        assert [event.kind for event in p2_page.events] == [
            "diagnostic.public",
            "diagnostic.private",
        ]
        assert all(event.kind != "diagnostic.dm" for event in p1_page.events + p2_page.events)

        with pytest.raises(TableEventNotFoundError):
            service.resolve_human_actor(
                room_id=room_id,
                campaign_id=campaign_id,
                session_id=session_id,
                context=_context(room_id, access_ids["owner"], "owner"),
            )

        with pytest.raises(TableEventNotFoundError):
            service.resolve_human_actor(
                room_id=uuid4(),
                campaign_id=campaign_id,
                session_id=session_id,
                context=_context(room_id, access_ids["player1"], "member"),
            )
    finally:
        engine.dispose()


def test_ended_session_rejects_new_event_but_preserves_history() -> None:
    engine = _engine()
    try:
        room_id, campaign_id, session_id, access_ids, _seat_ids = _seed_session(engine)
        service = TableEventService(TableEventRepository(engine))
        actors = _actors(service, room_id, campaign_id, session_id, access_ids)
        dm = actors["dm"]
        player = actors["player1"]

        committed = service.append_event(
            dm,
            TableEventAppend(kind="diagnostic.before-end", payload={"ok": True}),
        )
        with engine.begin() as connection:
            connection.execute(
                update(sessions)
                .where(sessions.c.id == session_id)
                .values(status="ended", ended_at=datetime.now(timezone.utc))
            )

        with pytest.raises(TableEventSessionNotActiveError):
            service.append_event(
                dm,
                TableEventAppend(kind="diagnostic.after-end", payload={"ok": False}),
            )

        page = service.list_after(player, after_seq=0, limit=20)
        assert [event.id for event in page.events] == [committed.id]
        assert page.current_seq == committed.seq
    finally:
        engine.dispose()


def test_event_append_contract_rejects_unknown_fields_and_unstable_kind() -> None:
    with pytest.raises(ValidationError):
        TableEventAppend.model_validate(
            {
                "kind": "Diagnostic Bad",
                "payload": {},
                "include_dm_only": True,
            }
        )
