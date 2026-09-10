from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import create_engine, insert, select, update
from sqlalchemy.pool import StaticPool

from app.db import metadata
from app.domain.rooms.ai_controllers import AIControllerService, AIHandoffRequest
from app.domain.rooms.ai_tools import AIToolApplicationService, TextActionInput
from app.domain.rooms.exploration import ExplorationActionService, ExplorationInputKind
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.table_events import TableEventService
from app.persistence.characters import characters
from app.persistence.rooms.ai_controllers import AIControllerGrantRepository
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
    dm_access_id, player_access_id = uuid4(), uuid4()
    dm_seat_id, player_seat_id, character_id = uuid4(), uuid4(), uuid4()

    with engine.begin() as connection:
        connection.execute(
            insert(rooms).values(
                id=room_id,
                code="P3ESHARED1",
                name="P3-E shared action",
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
            update(rooms).where(rooms.c.id == room_id).values(active_campaign_id=campaign_id)
        )
        connection.execute(
            insert(characters).values(
                id=character_id,
                name="Mira",
                ruleset="dnd5e-2014",
                current_version_id=None,
                archived_at=None,
                created_at=now,
                updated_at=now,
            )
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
                    "controller_epoch": 0,
                    "selected_character_id": None,
                    "archived_at": None,
                    "created_at": now,
                    "updated_at": now,
                },
                {
                    "id": player_seat_id,
                    "campaign_id": campaign_id,
                    "role": "player",
                    "label": "Mira",
                    "controller_kind": "human",
                    "controller_access_session_id": player_access_id,
                    "ai_controller_grant_id": None,
                    "controller_epoch": 0,
                    "selected_character_id": character_id,
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
            insert(session_participants),
            [
                {
                    "id": uuid4(),
                    "session_id": session_id,
                    "seat_id": dm_seat_id,
                    "role_snapshot": "dm",
                    "controller_kind_at_join": "human",
                    "controller_access_session_id_at_join": dm_access_id,
                    "controller_ai_grant_id_at_join": None,
                    "controller_generation_at_join": None,
                    "active_character_id": None,
                    "joined_at": now,
                    "left_at": None,
                },
                {
                    "id": uuid4(),
                    "session_id": session_id,
                    "seat_id": player_seat_id,
                    "role_snapshot": "player",
                    "controller_kind_at_join": "human",
                    "controller_access_session_id_at_join": player_access_id,
                    "controller_ai_grant_id_at_join": None,
                    "controller_generation_at_join": None,
                    "active_character_id": character_id,
                    "joined_at": now,
                    "left_at": None,
                },
            ],
        )

    return {
        "room_id": room_id,
        "campaign_id": campaign_id,
        "session_id": session_id,
        "dm_access_id": dm_access_id,
        "player_access_id": player_access_id,
        "dm_seat_id": dm_seat_id,
        "player_seat_id": player_seat_id,
        "character_id": character_id,
    }


def _facade(controller, events, actions):
    return AIToolApplicationService(
        ai_controller_service=controller,
        session_service=None,  # type: ignore[arg-type]
        stage_service=None,  # type: ignore[arg-type]
        action_service=actions,
        roll_service=None,  # type: ignore[arg-type]
        state_service=None,  # type: ignore[arg-type]
        pending_action_service=None,  # type: ignore[arg-type]
        event_service=events,
        workspace_service=None,  # type: ignore[arg-type]
    )


def test_ai_mcp_action_uses_canonical_exploration_message_and_human_event_path() -> None:
    engine = _engine()
    try:
        ids = _seed(engine)
        events = TableEventService(TableEventRepository(engine))
        controller = AIControllerService(AIControllerGrantRepository(engine), events)
        actions = ExplorationActionService(
            ExplorationSubjectRepository(engine),
            ExplorationMessageRepository(engine),
            events,
        )

        grant = controller.let_ai_control_player(
            room_id=ids["room_id"],
            campaign_id=ids["campaign_id"],
            session_id=ids["session_id"],
            seat_id=ids["player_seat_id"],
            context=RoomAccessContext(
                room_id=ids["room_id"],
                access_session_id=ids["player_access_id"],
                authority=RoomAccessAuthority.MEMBER,
            ),
            request=AIHandoffRequest(),
        )
        facade = _facade(controller, events, actions)

        result = facade.post_text(
            grant.token,
            kind=ExplorationInputKind.ACTION,
            input=TextActionInput(
                text="Open the trapped door carefully.",
                idempotency_key="p3e-shared-action-1",
            ),
        )

        assert result["kind"] == "exploration.action"
        assert result["acting_seat_id"] == str(ids["player_seat_id"])
        assert result["subject_seat_id"] == str(ids["player_seat_id"])
        assert result["subject_character_id"] == str(ids["character_id"])
        assert result["execution_mode"] == "self"
        assert result["payload"]["text"] == "Open the trapped door carefully."

        event_id = UUID(result["id"])
        with engine.connect() as connection:
            stored = connection.execute(
                select(
                    session_messages.c.event_id,
                    session_messages.c.kind,
                    session_messages.c.text,
                    session_messages.c.subject_seat_id,
                    session_messages.c.subject_character_id,
                    session_events.c.seq,
                )
                .join(session_events, session_events.c.id == session_messages.c.event_id)
                .where(session_messages.c.event_id == event_id)
            ).mappings().one()
        assert stored["event_id"] == event_id
        assert stored["kind"] == "action"
        assert stored["text"] == "Open the trapped door carefully."
        assert stored["subject_seat_id"] == ids["player_seat_id"]
        assert stored["subject_character_id"] == ids["character_id"]
        assert stored["seq"] == result["seq"]

        dm = events.resolve_human_actor(
            room_id=ids["room_id"],
            campaign_id=ids["campaign_id"],
            session_id=ids["session_id"],
            context=RoomAccessContext(
                room_id=ids["room_id"],
                access_session_id=ids["dm_access_id"],
                authority=RoomAccessAuthority.DM,
            ),
        )
        visible = events.list_after(dm, after_seq=0, limit=50)
        matching = next(event for event in visible.events if event.id == event_id)
        assert matching.kind == "exploration.action"
        assert matching.payload["text"] == "Open the trapped door carefully."
    finally:
        engine.dispose()
