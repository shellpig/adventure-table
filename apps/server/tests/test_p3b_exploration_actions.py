from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, insert, select, update
from sqlalchemy.pool import StaticPool

from app.db import metadata
from app.domain.rooms.exploration import (
    ExplorationActionService,
    ExplorationInputKind,
    ExplorationInputRequest,
)
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.table_events import TableEventActorUnauthorizedError, TableEventService
from app.persistence.rooms.exploration_messages import (
    ExplorationMessageRepository,
    session_messages,
)
from app.persistence.rooms.exploration_subjects import ExplorationSubjectRepository
from app.persistence.rooms.table_runtime import TableEventRepository, session_events
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


def _seed(engine):
    now = datetime.now(timezone.utc)
    room_id, campaign_id, session_id = uuid4(), uuid4(), uuid4()
    access = {name: uuid4() for name in ("dm", "p1", "p2")}
    seats = {name: uuid4() for name in ("dm", "p1", "p2")}
    characters = {name: uuid4() for name in ("p1", "p2")}
    with engine.begin() as connection:
        connection.execute(insert(rooms).values(
            id=room_id, code="P3BACTION1", name="P3-B Action",
            password_salt=b"s" * 32, password_hash=b"p" * 64,
            owner_key_hash=b"o" * 32, dm_key_hash=b"d" * 32,
            active_campaign_id=None, created_at=now, updated_at=now,
        ))
        for index, name in enumerate(("dm", "p1", "p2"), start=1):
            connection.execute(insert(room_access_sessions).values(
                id=access[name], room_id=room_id,
                authority="dm" if name == "dm" else "member",
                token_hash=bytes([index]) * 32, display_name=name,
                created_at=now, last_seen_at=now, revoked_at=None,
            ))
        connection.execute(insert(campaigns).values(
            id=campaign_id, room_id=room_id, name="Campaign",
            ruleset="dnd5e-2014", status="active", created_at=now, updated_at=now,
        ))
        connection.execute(update(rooms).where(rooms.c.id == room_id).values(active_campaign_id=campaign_id))
        connection.execute(insert(campaign_seats), [
            {
                "id": seats["dm"], "campaign_id": campaign_id, "role": "dm", "label": "DM",
                "controller_kind": "human", "controller_access_session_id": access["dm"],
                "selected_character_id": None, "archived_at": None, "created_at": now, "updated_at": now,
            },
            {
                "id": seats["p1"], "campaign_id": campaign_id, "role": "player", "label": "Mira",
                "controller_kind": "human", "controller_access_session_id": access["p1"],
                "selected_character_id": None, "archived_at": None, "created_at": now, "updated_at": now,
            },
            {
                "id": seats["p2"], "campaign_id": campaign_id, "role": "player", "label": "Serena",
                "controller_kind": "human", "controller_access_session_id": access["p2"],
                "selected_character_id": None, "archived_at": None, "created_at": now, "updated_at": now,
            },
        ])
        connection.execute(insert(sessions).values(
            id=session_id, campaign_id=campaign_id, status="active", dm_seat_id=seats["dm"],
            dm_controller_kind="human", dm_controller_access_session_id=access["dm"],
            started_at=now, ended_at=None, created_at=now,
        ))
        connection.execute(insert(session_participants), [
            {
                "id": uuid4(), "session_id": session_id, "seat_id": seats["dm"], "role_snapshot": "dm",
                "controller_kind_at_join": "human", "controller_access_session_id_at_join": access["dm"],
                "active_character_id": None, "joined_at": now, "left_at": None,
            },
            {
                "id": uuid4(), "session_id": session_id, "seat_id": seats["p1"], "role_snapshot": "player",
                "controller_kind_at_join": "human", "controller_access_session_id_at_join": access["p1"],
                "active_character_id": characters["p1"], "joined_at": now, "left_at": None,
            },
            {
                "id": uuid4(), "session_id": session_id, "seat_id": seats["p2"], "role_snapshot": "player",
                "controller_kind_at_join": "human", "controller_access_session_id_at_join": access["p2"],
                "active_character_id": characters["p2"], "joined_at": now, "left_at": None,
            },
        ])
    return room_id, campaign_id, session_id, access, seats, characters


def _actor(events: TableEventService, room_id: UUID, campaign_id: UUID, session_id: UUID, access_id: UUID, authority: str):
    return events.resolve_human_actor(
        room_id=room_id, campaign_id=campaign_id, session_id=session_id,
        context=RoomAccessContext(
            room_id=room_id, access_session_id=access_id,
            authority=RoomAccessAuthority(authority),
        ),
    )


def _actions(engine, events: TableEventService) -> ExplorationActionService:
    return ExplorationActionService(
        ExplorationSubjectRepository(engine),
        ExplorationMessageRepository(engine),
        events,
    )


def test_dialogue_action_search_and_dm_proxy_keep_subject_and_acting_identity_distinct() -> None:
    engine = _engine()
    try:
        room_id, campaign_id, session_id, access, seats, characters = _seed(engine)
        events = TableEventService(TableEventRepository(engine))
        actions = _actions(engine, events)
        dm = _actor(events, room_id, campaign_id, session_id, access["dm"], "dm")
        p1 = _actor(events, room_id, campaign_id, session_id, access["p1"], "member")

        dialogue = actions.send(p1, ExplorationInputRequest(
            kind=ExplorationInputKind.DIALOGUE, subject_seat_id=seats["p1"], text="Hello.",
        ))
        assert dialogue.acting_seat_id == seats["p1"]
        assert dialogue.subject_seat_id == seats["p1"]
        assert dialogue.subject_character_id == characters["p1"]
        assert dialogue.execution_mode.value == "self"

        with pytest.raises(TableEventActorUnauthorizedError):
            actions.send(p1, ExplorationInputRequest(
                kind=ExplorationInputKind.ACTION, subject_seat_id=seats["p2"], text="I move Serena.",
            ))

        proxied = actions.send(dm, ExplorationInputRequest(
            kind=ExplorationInputKind.ACTION,
            subject_seat_id=seats["p2"],
            text="Search the desk.",
            source_command="search",
        ))
        assert proxied.acting_seat_id == seats["dm"]
        assert proxied.subject_seat_id == seats["p2"]
        assert proxied.subject_character_id == characters["p2"]
        assert proxied.execution_mode.value == "dm_proxy"
        assert proxied.payload["source_command"] == "search"
        assert proxied.kind == "exploration.action"

        with engine.connect() as connection:
            rows = connection.execute(
                select(session_messages)
                .where(session_messages.c.session_id == session_id)
                .order_by(session_messages.c.created_at, session_messages.c.id)
            ).mappings().all()
        assert len(rows) == 2
        assert rows[0]["kind"] == "dialogue"
        assert rows[0]["subject_character_id"] == characters["p1"]
        assert rows[1]["kind"] == "action"
        assert rows[1]["acting_seat_id"] == seats["dm"]
        assert rows[1]["subject_seat_id"] == seats["p2"]
        assert rows[1]["execution_mode"] == "dm_proxy"
        assert rows[1]["source_command"] == "search"
        assert {rows[0]["event_id"], rows[1]["event_id"]} == {dialogue.id, proxied.id}
    finally:
        engine.dispose()


def test_whisper_is_server_filtered_to_sender_and_current_dm_and_narration_is_dm_only() -> None:
    engine = _engine()
    try:
        room_id, campaign_id, session_id, access, _seats, _characters = _seed(engine)
        events = TableEventService(TableEventRepository(engine))
        actions = _actions(engine, events)
        dm = _actor(events, room_id, campaign_id, session_id, access["dm"], "dm")
        p1 = _actor(events, room_id, campaign_id, session_id, access["p1"], "member")
        p2 = _actor(events, room_id, campaign_id, session_id, access["p2"], "member")

        whisper = actions.send(p1, ExplorationInputRequest(
            kind=ExplorationInputKind.WHISPER_DM, text="I pocket the key.",
        ))
        assert whisper.visibility.value == "seat_private"
        assert [event.kind for event in events.list_after(p1, after_seq=0, limit=20).events] == [
            "exploration.whisper_dm"
        ]
        assert [event.kind for event in events.list_after(dm, after_seq=0, limit=20).events] == [
            "exploration.whisper_dm"
        ]
        assert events.list_after(p2, after_seq=0, limit=20).events == []

        with pytest.raises(TableEventActorUnauthorizedError):
            actions.send(p2, ExplorationInputRequest(
                kind=ExplorationInputKind.NARRATION, text="The moon turns red.",
            ))
        narration = actions.send(dm, ExplorationInputRequest(
            kind=ExplorationInputKind.NARRATION, text="The moon turns red.",
        ))
        assert narration.visibility.value == "public"
    finally:
        engine.dispose()


def test_one_human_controlling_multiple_player_seats_must_choose_subject_explicitly() -> None:
    engine = _engine()
    try:
        room_id, campaign_id, session_id, access, seats, _characters = _seed(engine)
        with engine.begin() as connection:
            connection.execute(
                update(session_participants)
                .where(
                    session_participants.c.session_id == session_id,
                    session_participants.c.seat_id == seats["p2"],
                )
                .values(controller_access_session_id_at_join=access["p1"])
            )
        events = TableEventService(TableEventRepository(engine))
        actions = _actions(engine, events)
        p1 = _actor(events, room_id, campaign_id, session_id, access["p1"], "member")
        assert set(p1.controlled_seat_ids) == {seats["p1"], seats["p2"]}

        second = actions.send(p1, ExplorationInputRequest(
            kind=ExplorationInputKind.ACTION, subject_seat_id=seats["p2"], text="Serena opens the door.",
        ))
        assert second.acting_seat_id == seats["p2"]
        assert second.execution_mode.value == "self"
    finally:
        engine.dispose()


def test_message_idempotency_never_duplicates_canonical_message_or_event() -> None:
    engine = _engine()
    try:
        room_id, campaign_id, session_id, access, _seats, _characters = _seed(engine)
        events = TableEventService(TableEventRepository(engine))
        actions = _actions(engine, events)
        p1 = _actor(events, room_id, campaign_id, session_id, access["p1"], "member")
        request = ExplorationInputRequest(
            kind=ExplorationInputKind.OOC,
            text="Same request",
            idempotency_key="same-ooc",
        )

        first = actions.send(p1, request)
        replay = actions.send(p1, request)
        assert replay.id == first.id
        assert replay.seq == first.seq

        with engine.connect() as connection:
            message_rows = connection.execute(
                select(session_messages).where(session_messages.c.session_id == session_id)
            ).mappings().all()
            event_rows = connection.execute(
                select(session_events).where(session_events.c.session_id == session_id)
            ).mappings().all()
        assert len(message_rows) == 1
        assert len(event_rows) == 1
        assert message_rows[0]["event_id"] == event_rows[0]["id"] == first.id
    finally:
        engine.dispose()
