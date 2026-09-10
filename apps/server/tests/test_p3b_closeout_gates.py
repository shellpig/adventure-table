from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import create_engine, insert, select, update

from app.db import metadata
from app.domain.rooms.exploration import (
    ExplorationActionService,
    ExplorationInputKind,
    ExplorationInputRequest,
    ExplorationStageService,
    StageUpdateRequest,
)
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.sessions import SessionService
from app.domain.rooms.table_events import TableEventService
from app.persistence.characters import character_states, characters
from app.persistence.rooms.exploration import ExplorationRepository
from app.persistence.rooms.exploration_messages import (
    ExplorationMessageRepository,
    session_messages,
)
from app.persistence.rooms.exploration_subjects import ExplorationSubjectRepository
from app.persistence.rooms.session_live import SessionLiveRepository
from app.persistence.rooms.sessions import SessionRepository
from app.persistence.rooms.table_runtime import TableEventRepository
from app.persistence.rooms.tables import (
    ai_controller_grants,
    campaign_seats,
    campaigns,
    room_access_sessions,
    rooms,
    session_participants,
    sessions,
)


def _engine(url: str = "sqlite+pysqlite:///:memory:"):
    engine = create_engine(url)
    metadata.create_all(engine)
    return engine


def _seed_table(engine):
    now = datetime.now(timezone.utc)
    room_id, campaign_id, session_id = uuid4(), uuid4(), uuid4()
    access = {name: uuid4() for name in ("dm", "p1", "p2")}
    seats = {name: uuid4() for name in ("dm", "p1", "p2")}
    chars = {name: uuid4() for name in ("p1", "p2")}

    with engine.begin() as connection:
        connection.execute(insert(rooms).values(
            id=room_id,
            code=f"P3B{uuid4().hex[:8].upper()}",
            name="P3-B Closeout Gates",
            password_salt=b"s" * 32,
            password_hash=b"p" * 64,
            owner_key_hash=b"o" * 32,
            dm_key_hash=b"d" * 32,
            active_campaign_id=None,
            created_at=now,
            updated_at=now,
        ))
        for index, name in enumerate(("dm", "p1", "p2"), start=1):
            connection.execute(insert(room_access_sessions).values(
                id=access[name],
                room_id=room_id,
                authority="dm" if name == "dm" else "member",
                token_hash=bytes([index]) * 32,
                display_name=name,
                created_at=now,
                last_seen_at=now,
                revoked_at=None,
            ))
        connection.execute(insert(campaigns).values(
            id=campaign_id,
            room_id=room_id,
            name="Campaign",
            ruleset="dnd5e-2014",
            status="active",
            created_at=now,
            updated_at=now,
        ))
        connection.execute(
            update(rooms).where(rooms.c.id == room_id).values(active_campaign_id=campaign_id)
        )
        connection.execute(insert(characters), [
            {
                "id": chars["p1"],
                "name": "Mira",
                "ruleset": "dnd5e-2014",
                "current_version_id": None,
                "archived_at": None,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": chars["p2"],
                "name": "Serena",
                "ruleset": "dnd5e-2014",
                "current_version_id": None,
                "archived_at": None,
                "created_at": now,
                "updated_at": now,
            },
        ])
        connection.execute(insert(character_states), [
            {
                "character_id": chars["p1"],
                "state_payload": {"hp_current": 9, "marker": "preserve-me"},
                "state_revision": 7,
                "updated_at": now,
            },
            {
                "character_id": chars["p2"],
                "state_payload": {"hp_current": 12},
                "state_revision": 3,
                "updated_at": now,
            },
        ])
        connection.execute(insert(campaign_seats), [
            {
                "id": seats["dm"],
                "campaign_id": campaign_id,
                "role": "dm",
                "label": "DM",
                "controller_kind": "human",
                "controller_access_session_id": access["dm"],
                "selected_character_id": None,
                "archived_at": None,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": seats["p1"],
                "campaign_id": campaign_id,
                "role": "player",
                "label": "Mira",
                "controller_kind": "human",
                "controller_access_session_id": access["p1"],
                "selected_character_id": chars["p1"],
                "archived_at": None,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": seats["p2"],
                "campaign_id": campaign_id,
                "role": "player",
                "label": "Serena",
                "controller_kind": "human",
                "controller_access_session_id": access["p2"],
                "selected_character_id": chars["p2"],
                "archived_at": None,
                "created_at": now,
                "updated_at": now,
            },
        ])
        connection.execute(insert(sessions).values(
            id=session_id,
            campaign_id=campaign_id,
            status="active",
            dm_seat_id=seats["dm"],
            dm_controller_kind="human",
            dm_controller_access_session_id=access["dm"],
            started_at=now,
            ended_at=None,
            created_at=now,
        ))
        connection.execute(insert(session_participants), [
            {
                "id": uuid4(),
                "session_id": session_id,
                "seat_id": seats["dm"],
                "role_snapshot": "dm",
                "controller_kind_at_join": "human",
                "controller_access_session_id_at_join": access["dm"],
                "active_character_id": None,
                "joined_at": now,
                "left_at": None,
            },
            {
                "id": uuid4(),
                "session_id": session_id,
                "seat_id": seats["p1"],
                "role_snapshot": "player",
                "controller_kind_at_join": "human",
                "controller_access_session_id_at_join": access["p1"],
                "active_character_id": chars["p1"],
                "joined_at": now,
                "left_at": None,
            },
            {
                "id": uuid4(),
                "session_id": session_id,
                "seat_id": seats["p2"],
                "role_snapshot": "player",
                "controller_kind_at_join": "human",
                "controller_access_session_id_at_join": access["p2"],
                "active_character_id": chars["p2"],
                "joined_at": now,
                "left_at": None,
            },
        ])
    return room_id, campaign_id, session_id, access, seats, chars


def _actor(events, room_id: UUID, campaign_id: UUID, session_id: UUID, access_id: UUID, authority: str):
    return events.resolve_human_actor(
        room_id=room_id,
        campaign_id=campaign_id,
        session_id=session_id,
        context=RoomAccessContext(
            room_id=room_id,
            access_session_id=access_id,
            authority=RoomAccessAuthority(authority),
        ),
    )


def _actions(engine, events):
    return ExplorationActionService(
        ExplorationSubjectRepository(engine),
        ExplorationMessageRepository(engine),
        events,
    )


def test_dm_proxy_never_changes_human_or_ai_seat_controller() -> None:
    engine = _engine()
    try:
        room_id, campaign_id, session_id, access, seats, _chars = _seed_table(engine)
        events = TableEventService(TableEventRepository(engine))
        actions = _actions(engine, events)
        dm = _actor(events, room_id, campaign_id, session_id, access["dm"], "dm")

        human_proxy = actions.send(dm, ExplorationInputRequest(
            kind=ExplorationInputKind.ACTION,
            subject_seat_id=seats["p1"],
            text="Mira checks the door.",
        ))
        assert human_proxy.execution_mode.value == "dm_proxy"

        grant_id = uuid4()
        now = datetime.now(timezone.utc)
        with engine.begin() as connection:
            human_after = connection.execute(
                select(
                    campaign_seats.c.controller_kind,
                    campaign_seats.c.controller_access_session_id,
                ).where(campaign_seats.c.id == seats["p1"])
            ).mappings().one()
            assert human_after["controller_kind"] == "human"
            assert human_after["controller_access_session_id"] == access["p1"]

            connection.execute(insert(ai_controller_grants).values(
                id=grant_id,
                room_id=room_id,
                campaign_id=campaign_id,
                seat_id=seats["p2"],
                role="player",
                session_id=session_id,
                secret_hash=b"a" * 32,
                secret_prefix="proxy-ai",
                generation=1,
                status="active",
                pre_session_expires_at=None,
                handoff_return_access_session_id=access["p2"],
                temporary_instruction=None,
                created_at=now,
                bound_at=now,
                revoked_at=None,
                last_seen_at=None,
            ))
            connection.execute(
                update(campaign_seats)
                .where(campaign_seats.c.id == seats["p2"])
                .values(
                    controller_kind="ai",
                    controller_access_session_id=None,
                    ai_controller_grant_id=grant_id,
                    controller_epoch=1,
                )
            )

        ai_proxy = actions.send(dm, ExplorationInputRequest(
            kind=ExplorationInputKind.ACTION,
            subject_seat_id=seats["p2"],
            text="Serena studies the rune.",
        ))
        assert ai_proxy.execution_mode.value == "dm_proxy"

        with engine.connect() as connection:
            ai_after = connection.execute(
                select(
                    campaign_seats.c.controller_kind,
                    campaign_seats.c.controller_access_session_id,
                    campaign_seats.c.ai_controller_grant_id,
                    campaign_seats.c.controller_epoch,
                ).where(campaign_seats.c.id == seats["p2"])
            ).mappings().one()
        assert ai_after["controller_kind"] == "ai"
        assert ai_after["controller_access_session_id"] is None
        assert ai_after["ai_controller_grant_id"] == grant_id
        assert ai_after["controller_epoch"] == 1
    finally:
        engine.dispose()


def test_normal_session_end_preserves_messages_and_character_state() -> None:
    engine = _engine()
    try:
        room_id, campaign_id, session_id, access, _seats, chars = _seed_table(engine)
        events = TableEventService(TableEventRepository(engine))
        actions = _actions(engine, events)
        p1 = _actor(events, room_id, campaign_id, session_id, access["p1"], "member")
        actions.send(p1, ExplorationInputRequest(
            kind=ExplorationInputKind.OOC,
            text="Persist through End.",
        ))

        with engine.connect() as connection:
            state_before = connection.execute(
                select(character_states).where(character_states.c.character_id == chars["p1"])
            ).mappings().one()

        session_service = SessionService(
            SessionRepository(engine),
            SessionLiveRepository(engine),
        )
        ended = session_service.end_session(
            room_id,
            campaign_id,
            session_id,
            RoomAccessContext(
                room_id=room_id,
                access_session_id=access["dm"],
                authority=RoomAccessAuthority.DM,
            ),
        )
        assert ended.status.value == "ended"

        with engine.connect() as connection:
            messages = connection.execute(
                select(session_messages).where(session_messages.c.session_id == session_id)
            ).mappings().all()
            state_after = connection.execute(
                select(character_states).where(character_states.c.character_id == chars["p1"])
            ).mappings().one()

        assert len(messages) == 1
        assert messages[0]["text"] == "Persist through End."
        assert state_after["state_payload"] == state_before["state_payload"]
        assert state_after["state_revision"] == state_before["state_revision"]
    finally:
        engine.dispose()


def test_stage_and_message_survive_database_restart(tmp_path: Path) -> None:
    database = tmp_path / "p3b-restart.sqlite3"
    url = f"sqlite+pysqlite:///{database}"
    engine = _engine(url)
    room_id, campaign_id, session_id, access, _seats, _chars = _seed_table(engine)
    events = TableEventService(TableEventRepository(engine))
    dm = _actor(events, room_id, campaign_id, session_id, access["dm"], "dm")
    p1 = _actor(events, room_id, campaign_id, session_id, access["p1"], "member")
    ExplorationStageService(ExplorationRepository(engine), events).replace_stage(
        dm,
        StageUpdateRequest(expected_revision=0, text="Restart Stage"),
    )
    _actions(engine, events).send(p1, ExplorationInputRequest(
        kind=ExplorationInputKind.OOC,
        text="Restart Message",
    ))
    engine.dispose()

    restarted = create_engine(url)
    try:
        restarted_events = TableEventService(TableEventRepository(restarted))
        restarted_dm = _actor(
            restarted_events,
            room_id,
            campaign_id,
            session_id,
            access["dm"],
            "dm",
        )
        restarted_p1 = _actor(
            restarted_events,
            room_id,
            campaign_id,
            session_id,
            access["p1"],
            "member",
        )
        stage = ExplorationStageService(
            ExplorationRepository(restarted),
            restarted_events,
        ).get_stage(restarted_dm)
        visible = restarted_events.list_after(restarted_p1, after_seq=0, limit=20)

        assert stage.text == "Restart Stage"
        assert [event.kind for event in visible.events] == [
            "stage.updated",
            "exploration.ooc",
        ]
        assert visible.events[1].payload["text"] == "Restart Message"
    finally:
        restarted.dispose()
