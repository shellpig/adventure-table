from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, insert, select, update

from app.db import metadata
from app.domain.rooms.ai_controllers import (
    AIControllerHandoffError,
    AIControllerService,
    AIHandoffRequest,
)
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.table_events import TableEventService
from app.persistence.characters import characters
from app.persistence.rooms.ai_controllers import AIControllerGrantRepository
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
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    return engine


def _seed(connection):
    now = datetime.now(timezone.utc)
    room_id, campaign_id, session_id = uuid4(), uuid4(), uuid4()
    dm_seat_id, player_seat_id, character_id = uuid4(), uuid4(), uuid4()
    h1, h2, admin = uuid4(), uuid4(), uuid4()
    connection.execute(
        insert(rooms).values(
            id=room_id,
            code="P3DREC",
            name="Recovery",
            password_salt=b"s" * 32,
            password_hash=b"h" * 64,
            owner_key_hash=b"o" * 32,
            dm_key_hash=b"d" * 32,
            active_campaign_id=None,
            created_at=now,
            updated_at=now,
        )
    )
    for access_id, authority, display_name in (
        (h1, "member", "Same Player"),
        (h2, "member", "Same Player"),
        (admin, "owner", "Owner"),
    ):
        connection.execute(
            insert(room_access_sessions).values(
                id=access_id,
                room_id=room_id,
                authority=authority,
                token_hash=access_id.bytes + access_id.bytes,
                display_name=display_name,
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
        )
    )
    connection.execute(update(rooms).where(rooms.c.id == room_id).values(active_campaign_id=campaign_id))
    connection.execute(
        insert(characters).values(
            id=character_id,
            name="Mira",
            ruleset="dnd5e-2014",
            current_version_id=None,
            archived_at=None,
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
                "controller_access_session_id": admin,
                "ai_controller_grant_id": None,
                "controller_epoch": 1,
                "selected_character_id": None,
                "archived_at": None,
            },
            {
                "id": player_seat_id,
                "campaign_id": campaign_id,
                "role": "player",
                "label": "Mira",
                "controller_kind": "human",
                "controller_access_session_id": h1,
                "ai_controller_grant_id": None,
                "controller_epoch": 1,
                "selected_character_id": character_id,
                "archived_at": None,
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
            dm_controller_access_session_id=admin,
            dm_controller_ai_grant_id=None,
            dm_controller_generation=None,
            started_at=now,
            ended_at=None,
        )
    )
    connection.execute(
        insert(session_participants).values(
            id=uuid4(),
            session_id=session_id,
            seat_id=player_seat_id,
            role_snapshot="player",
            controller_kind_at_join="human",
            controller_access_session_id_at_join=h1,
            controller_ai_grant_id_at_join=None,
            controller_generation_at_join=None,
            active_character_id=character_id,
            joined_at=now,
            left_at=None,
        )
    )
    return room_id, campaign_id, session_id, player_seat_id, h1, h2, admin


def _context(room_id, access_id, authority=RoomAccessAuthority.MEMBER):
    return RoomAccessContext(
        room_id=room_id,
        access_session_id=access_id,
        authority=authority,
    )


def test_lost_origin_requires_admin_recovery_and_instruction_does_not_leak() -> None:
    engine = _engine()
    event_service = TableEventService(TableEventRepository(engine))
    repository = AIControllerGrantRepository(engine)
    service = AIControllerService(repository, event_service)
    try:
        with engine.begin() as connection:
            room_id, campaign_id, session_id, seat_id, h1, h2, admin = _seed(connection)

        first = service.let_ai_control_player(
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            seat_id=seat_id,
            context=_context(room_id, h1),
            request=AIHandoffRequest(
                temporary_instruction="Protect the wizard; save the last 2nd-level slot"
            ),
        )
        assert service.authenticate(first.token).temporary_instruction is not None

        # Simulate browser storage/access-session loss. A new access session with
        # the same display name is deliberately not the self-service origin.
        with engine.begin() as connection:
            connection.execute(
                update(room_access_sessions)
                .where(room_access_sessions.c.id == h1)
                .values(revoked_at=datetime.now(timezone.utc))
            )

        with pytest.raises(AIControllerHandoffError):
            service.take_back_player(
                room_id=room_id,
                campaign_id=campaign_id,
                session_id=session_id,
                seat_id=seat_id,
                context=_context(room_id, h2),
            )

        service.administratively_reassign_player(
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            seat_id=seat_id,
            target_access_session_id=h2,
            admin_context=_context(room_id, admin, RoomAccessAuthority.OWNER),
        )
        old = repository.get(first.grant_id)
        assert old is not None
        assert old.status == "revoked"
        assert old.temporary_instruction is None

        seat = engine.connect().execute(
            select(campaign_seats).where(campaign_seats.c.id == seat_id)
        ).mappings().one()
        assert seat["controller_kind"] == "human"
        assert seat["controller_access_session_id"] == h2
        assert seat["ai_controller_grant_id"] is None
        assert int(seat["controller_epoch"]) == first.generation + 1

        # A later handoff is a new credential and must not inherit the old
        # instruction. Recreate the service to prove the value comes from DB,
        # not process memory.
        second = service.let_ai_control_player(
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            seat_id=seat_id,
            context=_context(room_id, h2),
            request=AIHandoffRequest(),
        )
        restarted_service = AIControllerService(
            AIControllerGrantRepository(engine),
            TableEventService(TableEventRepository(engine)),
        )
        assert restarted_service.authenticate(second.token).temporary_instruction is None
        assert second.generation == first.generation + 2

        with engine.connect() as connection:
            admin_events = connection.execute(
                select(session_events.c.subject_seat_id, session_events.c.payload)
                .where(session_events.c.kind == "controller.changed")
                .order_by(session_events.c.seq)
            ).mappings().all()
        recovery_event = next(
            row for row in admin_events if row["payload"].get("reason") == "administrative_reassignment"
        )
        assert recovery_event["subject_seat_id"] == seat_id
        assert recovery_event["payload"]["admin_access_session_id"] == str(admin)
        assert recovery_event["payload"]["target_access_session_id"] == str(h2)
    finally:
        engine.dispose()
