from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, insert, select, update

from app.db import metadata
from app.domain.rooms.ai_controller_tokens import mint_ai_controller_token
from app.domain.rooms.ai_controllers import (
    AIControllerService,
    AIControllerUnauthorizedError,
)
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.sessions import SessionService
from app.domain.rooms.table_events import TableEventService
from app.persistence.characters import characters
from app.persistence.rooms.ai_controllers import AIControllerGrantRepository
from app.persistence.rooms.session_live import SessionLiveRepository
from app.persistence.rooms.sessions import SessionRepository
from app.persistence.rooms.table_runtime import TableEventRepository, session_events
from app.persistence.rooms.tables import (
    active_character_session_leases,
    ai_controller_grants,
    campaign_seats,
    campaigns,
    room_access_sessions,
    rooms,
    session_participants,
)


def _engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    return engine


def _seed_ai_dm_lobby(connection):
    now = datetime.now(timezone.utc)
    room_id, campaign_id, dm_seat_id = uuid4(), uuid4(), uuid4()
    connection.execute(
        insert(rooms).values(
            id=room_id,
            code="P3DD3A",
            name="Owner Abandon",
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
            name="Campaign",
            ruleset="dnd5e-2014",
            status="active",
        )
    )
    connection.execute(
        update(rooms).where(rooms.c.id == room_id).values(active_campaign_id=campaign_id)
    )
    connection.execute(
        insert(campaign_seats).values(
            id=dm_seat_id,
            campaign_id=campaign_id,
            role="dm",
            label="AI DM",
            controller_kind="none",
            controller_access_session_id=None,
            ai_controller_grant_id=None,
            controller_epoch=0,
            selected_character_id=None,
            archived_at=None,
        )
    )
    return room_id, campaign_id, dm_seat_id


def test_owner_abandon_revokes_ai_dm_and_ai_player_atomically() -> None:
    engine = _engine()
    event_service = TableEventService(TableEventRepository(engine))
    grant_repository = AIControllerGrantRepository(engine)
    controller_service = AIControllerService(grant_repository, event_service)
    session_repository = SessionRepository(engine)
    session_service = SessionService(
        session_repository,
        SessionLiveRepository(engine),
        event_service,
    )
    now = datetime.now(timezone.utc)
    try:
        with engine.begin() as connection:
            room_id, campaign_id, dm_seat_id = _seed_ai_dm_lobby(connection)

        dm_issued = controller_service.configure_pre_session_ai_dm(
            room_id=room_id,
            campaign_id=campaign_id,
            seat_id=dm_seat_id,
        )
        started = session_service.start_session_as_ai_dm(
            room_id,
            campaign_id,
            grant_id=dm_issued.grant_id,
            generation=dm_issued.generation,
        )

        owner_access_id = uuid4()
        player_seat_id = uuid4()
        player_character_id = uuid4()
        participant_id = uuid4()
        player_token = mint_ai_controller_token()
        with engine.begin() as connection:
            connection.execute(
                insert(room_access_sessions).values(
                    id=owner_access_id,
                    room_id=room_id,
                    authority="owner",
                    token_hash=b"x" * 32,
                    display_name="Owner",
                    created_at=now,
                    last_seen_at=now,
                    revoked_at=None,
                )
            )
            connection.execute(
                insert(characters).values(
                    id=player_character_id,
                    name="AI Player Character",
                    ruleset="dnd5e-2014",
                    current_version_id=None,
                    archived_at=None,
                )
            )
            connection.execute(
                insert(campaign_seats).values(
                    id=player_seat_id,
                    campaign_id=campaign_id,
                    role="player",
                    label="AI Player",
                    controller_kind="none",
                    controller_access_session_id=None,
                    ai_controller_grant_id=None,
                    controller_epoch=0,
                    selected_character_id=player_character_id,
                    archived_at=None,
                )
            )
            connection.execute(
                insert(session_participants).values(
                    id=participant_id,
                    session_id=started.id,
                    seat_id=player_seat_id,
                    role_snapshot="player",
                    controller_kind_at_join="none",
                    controller_access_session_id_at_join=None,
                    controller_ai_grant_id_at_join=None,
                    controller_generation_at_join=None,
                    active_character_id=player_character_id,
                    joined_at=now,
                    left_at=None,
                )
            )
            connection.execute(
                insert(active_character_session_leases).values(
                    character_id=player_character_id,
                    session_id=started.id,
                    participant_id=participant_id,
                )
            )
            connection.execute(
                insert(ai_controller_grants).values(
                    id=player_token.grant_id,
                    room_id=room_id,
                    campaign_id=campaign_id,
                    seat_id=player_seat_id,
                    role="player",
                    session_id=started.id,
                    secret_hash=player_token.secret_hash,
                    secret_prefix=player_token.display_hint,
                    generation=1,
                    status="active",
                    pre_session_expires_at=None,
                    handoff_return_access_session_id=owner_access_id,
                    temporary_instruction="Protect the party until handoff returns",
                    created_at=now,
                    bound_at=now,
                    revoked_at=None,
                    last_seen_at=None,
                )
            )
            connection.execute(
                update(campaign_seats)
                .where(campaign_seats.c.id == player_seat_id)
                .values(
                    controller_kind="ai",
                    controller_access_session_id=None,
                    ai_controller_grant_id=player_token.grant_id,
                    controller_epoch=1,
                    updated_at=now,
                )
            )

        assert controller_service.resolve_actor(dm_issued.token).is_current_dm
        assert controller_service.resolve_actor(player_token.plaintext).seat_id == player_seat_id

        abandoned = session_service.abandon_session(
            room_id,
            campaign_id,
            started.id,
            RoomAccessContext(
                room_id=room_id,
                access_session_id=owner_access_id,
                authority=RoomAccessAuthority.OWNER,
            ),
        )
        assert abandoned.status.value == "abandoned"
        assert session_repository.lease_for_character(player_character_id) is None

        with engine.connect() as connection:
            grant_rows = connection.execute(
                select(
                    ai_controller_grants.c.id,
                    ai_controller_grants.c.status,
                    ai_controller_grants.c.temporary_instruction,
                ).where(
                    ai_controller_grants.c.id.in_(
                        [dm_issued.grant_id, player_token.grant_id]
                    )
                )
            ).mappings().all()
            kinds = connection.scalars(
                select(session_events.c.kind)
                .where(session_events.c.session_id == started.id)
                .order_by(session_events.c.seq)
            ).all()
        assert {row["status"] for row in grant_rows} == {"revoked"}
        assert all(row["temporary_instruction"] is None for row in grant_rows)
        assert kinds[-1] == "session.abandoned"

        with pytest.raises(AIControllerUnauthorizedError):
            controller_service.resolve_actor(dm_issued.token)
        with pytest.raises(AIControllerUnauthorizedError):
            controller_service.resolve_actor(player_token.plaintext)
    finally:
        engine.dispose()
