from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool

from app.db import metadata
from app.domain.rooms.campaigns import (
    CampaignCreate,
    CampaignLifecycleError,
    CampaignService,
    CampaignStatus,
)
from app.domain.rooms.schemas import CreateRoomRequest
from app.domain.rooms.seats import ControllerKind, SeatControllerPatch, SeatCreate, SeatRole, SeatService
from app.domain.rooms.service import RoomService
from app.domain.rooms.sessions import SessionService, SessionStatus
from app.persistence.rooms.campaigns import CampaignRepository
from app.persistence.rooms.repository import RoomRepository
from app.persistence.rooms.seats import SeatRepository
from app.persistence.rooms.sessions import SessionRepository


def _engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    metadata.create_all(engine)
    return engine


def test_campaign_with_session_history_cannot_be_hard_deleted_even_if_returned_to_draft() -> None:
    engine = _engine()
    try:
        room_service = RoomService(RoomRepository(engine))
        owner = room_service.create_room(
            CreateRoomRequest(name="Campaign history", password="secret")
        )
        campaigns = CampaignService(CampaignRepository(engine))
        campaign = campaigns.create_campaign(
            owner.room.id,
            CampaignCreate(name="Campaign", ruleset="dnd5e-2014"),
        )
        campaigns.set_status(owner.room.id, campaign.id, CampaignStatus.ACTIVE)
        campaigns.select_campaign(owner.room.id, campaign.id)

        seats = SeatService(SeatRepository(engine))
        dm_seat = seats.create_seat(
            owner.room.id,
            campaign.id,
            SeatCreate(role=SeatRole.DM),
        )
        seats.set_controller(
            owner.room.id,
            campaign.id,
            dm_seat.id,
            SeatControllerPatch(
                controller_kind=ControllerKind.HUMAN,
                controller_access_session_id=owner.access_session_id,
            ),
        )

        context = room_service.authenticate(owner.room.id, owner.access_token)
        session_repository = SessionRepository(engine)
        session_service = SessionService(session_repository)
        started = session_service.start_session(
            owner.room.id,
            campaign.id,
            context,
        )
        ended = session_service.end_session(
            owner.room.id,
            campaign.id,
            started.id,
            context,
        )
        assert ended.status is SessionStatus.ENDED

        # Status mutation is intentionally exercised here: even if a caller
        # returns the Campaign to Draft later, retained Session history is an
        # independent, permanent hard-delete barrier.
        campaigns.set_status(owner.room.id, campaign.id, CampaignStatus.DRAFT)
        with pytest.raises(CampaignLifecycleError, match="Session history"):
            campaigns.delete_draft(owner.room.id, campaign.id)

        persisted_campaign = campaigns.get_campaign(owner.room.id, campaign.id)
        assert persisted_campaign.status is CampaignStatus.DRAFT
        persisted_session = session_repository.get(started.id)
        assert persisted_session is not None
        assert persisted_session.status == SessionStatus.ENDED.value
    finally:
        engine.dispose()
