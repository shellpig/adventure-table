from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import create_engine, insert, update

from app.db import metadata
from app.domain.rooms.campaigns import Campaign, CampaignStatus
from app.domain.rooms.schemas import RoomAccessAuthority
from app.domain.rooms.seats import CampaignSeat, ControllerKind, PresenceStatus, SeatRole
from app.domain.rooms.session_resume import SessionResumeService
from app.domain.rooms.sessions import (
    SessionParticipantSnapshot,
    SessionResume,
    SessionSnapshot,
    SessionStatus,
)
from app.persistence.characters import characters
from app.persistence.rooms.session_resume import SessionResumeRepository
from app.persistence.rooms.tables import (
    ai_controller_grants,
    campaign_seats,
    campaigns,
    room_access_sessions,
    rooms,
    sessions,
)


def _engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(
        engine,
        tables=[
            characters,
            rooms,
            room_access_sessions,
            campaigns,
            campaign_seats,
            sessions,
            ai_controller_grants,
        ],
    )
    return engine


def test_resume_repository_returns_only_exact_active_handoff_origin() -> None:
    engine = _engine()
    now = datetime.now(timezone.utc)
    room_id, campaign_id, session_id, seat_id = uuid4(), uuid4(), uuid4(), uuid4()
    h1, h2, grant_id = uuid4(), uuid4(), uuid4()
    try:
        with engine.begin() as connection:
            connection.execute(insert(rooms).values(
                id=room_id,
                code="P3DRTB",
                name="Resume",
                password_salt=b"s" * 32,
                password_hash=b"h" * 64,
                owner_key_hash=b"o" * 32,
                dm_key_hash=b"d" * 32,
                active_campaign_id=None,
                created_at=now,
                updated_at=now,
            ))
            connection.execute(insert(campaigns).values(
                id=campaign_id,
                room_id=room_id,
                name="Campaign",
                ruleset="dnd5e-2014",
                status="active",
            ))
            connection.execute(update(rooms).where(rooms.c.id == room_id).values(
                active_campaign_id=campaign_id,
            ))
            for access_id in (h1, h2):
                connection.execute(insert(room_access_sessions).values(
                    id=access_id,
                    room_id=room_id,
                    authority="member",
                    token_hash=uuid4().bytes + uuid4().bytes,
                    display_name="Same Name",
                    created_at=now,
                    last_seen_at=now,
                    revoked_at=None,
                ))
            connection.execute(insert(campaign_seats).values(
                id=seat_id,
                campaign_id=campaign_id,
                role="player",
                label="Mira",
                controller_kind="ai",
                controller_access_session_id=None,
                ai_controller_grant_id=grant_id,
                controller_epoch=2,
                selected_character_id=None,
                archived_at=None,
            ))
            connection.execute(insert(sessions).values(
                id=session_id,
                campaign_id=campaign_id,
                status="active",
                dm_seat_id=seat_id,
                dm_controller_kind="human",
                dm_controller_access_session_id=h2,
                dm_controller_ai_grant_id=None,
                dm_controller_generation=None,
                started_at=now,
                ended_at=None,
            ))
            connection.execute(insert(ai_controller_grants).values(
                id=grant_id,
                room_id=room_id,
                campaign_id=campaign_id,
                seat_id=seat_id,
                role="player",
                session_id=session_id,
                secret_hash=b"x" * 32,
                secret_prefix="AT1-demo",
                generation=2,
                status="active",
                pre_session_expires_at=None,
                handoff_return_access_session_id=h1,
                temporary_instruction="Protect the wizard",
                created_at=now,
                bound_at=now,
                revoked_at=None,
                last_seen_at=None,
            ))

        repo = SessionResumeRepository(engine)
        assert repo.self_take_back_seat_ids(
            room_id=room_id,
            session_id=session_id,
            access_session_id=h1,
        ) == (seat_id,)
        assert repo.self_take_back_seat_ids(
            room_id=room_id,
            session_id=session_id,
            access_session_id=h2,
        ) == ()

        with engine.begin() as connection:
            connection.execute(update(room_access_sessions).where(
                room_access_sessions.c.id == h1
            ).values(revoked_at=now))
        assert repo.self_take_back_seat_ids(
            room_id=room_id,
            session_id=session_id,
            access_session_id=h1,
        ) == ()
    finally:
        engine.dispose()


def test_session_resume_projects_only_boolean_equivalent_seat_ids() -> None:
    now = datetime.now(timezone.utc)
    room_id, campaign_id, session_id, dm_seat_id, player_seat_id, h1 = (
        uuid4(), uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    )
    active_session = SessionSnapshot(
        id=session_id,
        campaign_id=campaign_id,
        status=SessionStatus.ACTIVE,
        dm_seat_id=dm_seat_id,
        dm_controller_kind="human",
        dm_controller_access_session_id=uuid4(),
        started_at=now,
        participants=[SessionParticipantSnapshot(
            id=uuid4(),
            seat_id=player_seat_id,
            role="player",
            controller_kind_at_join="human",
            controller_access_session_id_at_join=h1,
            active_character_id=None,
        )],
    )
    seat = CampaignSeat(
        id=player_seat_id,
        campaign_id=campaign_id,
        role=SeatRole.PLAYER,
        label="Mira",
        controller_kind=ControllerKind.AI,
        presence=PresenceStatus.NOT_APPLICABLE,
        created_at=now,
        updated_at=now,
    )

    class SummaryRepo:
        def self_take_back_seat_ids(self, **kwargs):
            assert kwargs == {
                "room_id": room_id,
                "session_id": session_id,
                "access_session_id": h1,
            }
            return (player_seat_id,)

    service = SessionResumeService(
        session_service=SimpleNamespace(
            resume=lambda *_args, **_kwargs: SessionResume(
                room_id=room_id,
                campaign_id=campaign_id,
                active_session=active_session,
            )
        ),
        room_repository=SimpleNamespace(get_room=lambda _room_id: SimpleNamespace(
            id=room_id,
            code="ROOM01",
            name="Room",
            active_campaign_id=campaign_id,
            created_at=now,
            updated_at=now,
        )),
        campaign_service=SimpleNamespace(get_campaign=lambda *_args: Campaign(
            id=campaign_id,
            room_id=room_id,
            name="Campaign",
            ruleset="dnd5e-2014",
            status=CampaignStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )),
        seat_service=SimpleNamespace(list_seats=lambda *_args, **_kwargs: [seat]),
        character_repository=object(),
        summary_repository=SummaryRepo(),
    )

    resume = service.resume(
        room_id,
        campaign_id,
        caller_access_session_id=h1,
    )
    assert resume.self_take_back_seat_ids == [player_seat_id]
    payload = resume.model_dump(mode="json")
    assert payload["self_take_back_seat_ids"] == [str(player_seat_id)]
    assert "handoff_return_access_session_id" not in str(payload)
    assert RoomAccessAuthority.MEMBER.value not in payload["self_take_back_seat_ids"]
