from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, insert, update
from sqlalchemy.pool import StaticPool

from app.db import metadata
from app.domain.rooms.ai_controllers import (
    AIControllerService,
    AIControllerUnauthorizedError,
    AIHandoffRequest,
)
from app.domain.rooms.ai_tools import AIToolApplicationService
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
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


def _seed_active_player(engine):
    now = datetime.now(timezone.utc)
    room_id, campaign_id, session_id = uuid4(), uuid4(), uuid4()
    dm_seat_id, player_seat_id = uuid4(), uuid4()
    player_access_id, character_id = uuid4(), uuid4()

    with engine.begin() as connection:
        connection.execute(
            insert(rooms).values(
                id=room_id,
                code="P3EINS1",
                name="P3E instruction lifecycle",
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
            insert(room_access_sessions).values(
                id=player_access_id,
                room_id=room_id,
                authority="member",
                token_hash=b"p" * 32,
                display_name="Player",
                created_at=now,
                last_seen_at=now,
                revoked_at=None,
            )
        )
        connection.execute(
            insert(characters).values(
                id=character_id,
                name="Instruction Hero",
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
                    "controller_kind": "none",
                    "controller_access_session_id": None,
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
            ],
        )
        connection.execute(
            insert(sessions).values(
                id=session_id,
                campaign_id=campaign_id,
                status="active",
                dm_seat_id=dm_seat_id,
                dm_controller_kind="none",
                dm_controller_access_session_id=None,
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

    return {
        "room_id": room_id,
        "campaign_id": campaign_id,
        "session_id": session_id,
        "dm_seat_id": dm_seat_id,
        "player_seat_id": player_seat_id,
        "player_access_id": player_access_id,
        "character_id": character_id,
        "now": now,
    }


class _SessionService:
    def __init__(self, ids: dict) -> None:
        self.ids = ids

    def get_session(self, room_id, campaign_id, session_id):
        assert room_id == self.ids["room_id"]
        assert campaign_id == self.ids["campaign_id"]
        assert session_id == self.ids["session_id"]
        return SimpleNamespace(
            id=session_id,
            campaign_id=campaign_id,
            status=SimpleNamespace(value="active"),
            dm_seat_id=self.ids["dm_seat_id"],
            participants=[
                SimpleNamespace(
                    seat_id=self.ids["player_seat_id"],
                    role="player",
                    active_character_id=self.ids["character_id"],
                )
            ],
        )


class _StageService:
    @staticmethod
    def get_stage(actor):
        return SimpleNamespace(model_dump=lambda **_: {"revision": 0, "text": None})


class _EmptyListService:
    @staticmethod
    def list_requests(actor):
        return []

    @staticmethod
    def list(actor):
        return []


def _facade(controller, events, ids) -> AIToolApplicationService:
    empty = _EmptyListService()
    return AIToolApplicationService(
        ai_controller_service=controller,
        session_service=_SessionService(ids),  # type: ignore[arg-type]
        stage_service=_StageService(),  # type: ignore[arg-type]
        action_service=None,  # type: ignore[arg-type]
        roll_service=empty,  # type: ignore[arg-type]
        state_service=None,  # type: ignore[arg-type]
        pending_action_service=empty,  # type: ignore[arg-type]
        event_service=events,
        workspace_service=None,  # type: ignore[arg-type]
    )


def test_temporary_instruction_is_current_handoff_only_in_p3e_context() -> None:
    engine = _engine()
    try:
        ids = _seed_active_player(engine)
        events = TableEventService(TableEventRepository(engine))
        controller = AIControllerService(AIControllerGrantRepository(engine), events)
        facade = _facade(controller, events, ids)
        human = RoomAccessContext(
            room_id=ids["room_id"],
            access_session_id=ids["player_access_id"],
            authority=RoomAccessAuthority.MEMBER,
            display_name="Player",
        )

        first = controller.let_ai_control_player(
            room_id=ids["room_id"],
            campaign_id=ids["campaign_id"],
            session_id=ids["session_id"],
            seat_id=ids["player_seat_id"],
            context=human,
            request=AIHandoffRequest(temporary_instruction="  Keep the scout safe  "),
        )
        first_context = facade.get_session_context(first.token)
        assert first_context["temporary_instruction"] == "Keep the scout safe"

        controller.take_back_player(
            room_id=ids["room_id"],
            campaign_id=ids["campaign_id"],
            session_id=ids["session_id"],
            seat_id=ids["player_seat_id"],
            context=human,
        )
        with pytest.raises(AIControllerUnauthorizedError):
            facade.get_session_context(first.token)

        second = controller.let_ai_control_player(
            room_id=ids["room_id"],
            campaign_id=ids["campaign_id"],
            session_id=ids["session_id"],
            seat_id=ids["player_seat_id"],
            context=human,
            request=AIHandoffRequest(),
        )
        second_context = facade.get_session_context(second.token)
        assert second_context["temporary_instruction"] is None
    finally:
        engine.dispose()
