from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import create_engine, insert, select, update

from app.db import metadata
from app.domain.rooms.ai_controller_tokens import mint_ai_controller_token
from app.persistence.rooms.session_live import SessionLiveRepository
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
    metadata.create_all(engine)
    return engine


def _seed_room_campaign(connection):
    now = datetime.now(timezone.utc)
    room_id, campaign_id = uuid4(), uuid4()
    connection.execute(
        insert(rooms).values(
            id=room_id,
            code="P3DLJB",
            name="Late Join Binding",
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
    connection.execute(update(rooms).where(rooms.c.id == room_id).values(active_campaign_id=campaign_id))
    return room_id, campaign_id, now


def _session_row(connection, session_id):
    return connection.execute(
        select(
            sessions.c.id,
            sessions.c.dm_seat_id,
            sessions.c.dm_controller_kind,
            sessions.c.dm_controller_access_session_id,
            sessions.c.dm_controller_ai_grant_id,
            sessions.c.dm_controller_generation,
        ).where(sessions.c.id == session_id)
    ).one()


def test_late_join_revalidation_rejects_revoked_human_dm_access() -> None:
    engine = _engine()
    try:
        with engine.begin() as connection:
            room_id, campaign_id, now = _seed_room_campaign(connection)
            access_id, dm_seat_id, session_id = uuid4(), uuid4(), uuid4()
            connection.execute(
                insert(room_access_sessions).values(
                    id=access_id,
                    room_id=room_id,
                    authority="dm",
                    token_hash=b"h" * 32,
                    display_name="DM",
                    created_at=now,
                    last_seen_at=now,
                    revoked_at=now,
                )
            )
            connection.execute(
                insert(campaign_seats).values(
                    id=dm_seat_id,
                    campaign_id=campaign_id,
                    role="dm",
                    label="DM",
                    controller_kind="human",
                    controller_access_session_id=access_id,
                    ai_controller_grant_id=None,
                    controller_epoch=1,
                    selected_character_id=None,
                    archived_at=None,
                )
            )
            connection.execute(
                insert(sessions).values(
                    id=session_id,
                    campaign_id=campaign_id,
                    status="active",
                    dm_seat_id=dm_seat_id,
                    dm_controller_kind="human",
                    dm_controller_access_session_id=access_id,
                    dm_controller_ai_grant_id=None,
                    dm_controller_generation=None,
                    started_at=now,
                    ended_at=None,
                )
            )
            session = _session_row(connection, session_id)
            assert SessionLiveRepository._caller_is_current_dm(
                session,
                caller_actor_kind="human",
                caller_access_session_id=access_id,
                caller_ai_grant_id=None,
                caller_generation=None,
            )
            assert not SessionLiveRepository._revalidate_current_dm_binding(
                connection,
                session=session,
                campaign_id=campaign_id,
                caller_actor_kind="human",
                caller_access_session_id=access_id,
                caller_ai_grant_id=None,
                caller_generation=None,
            )
    finally:
        engine.dispose()


def test_late_join_revalidation_rejects_stale_ai_dm_epoch() -> None:
    engine = _engine()
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA defer_foreign_keys=ON")
            room_id, campaign_id, now = _seed_room_campaign(connection)
            dm_seat_id, session_id = uuid4(), uuid4()
            token = mint_ai_controller_token()
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
            connection.execute(
                insert(sessions).values(
                    id=session_id,
                    campaign_id=campaign_id,
                    status="active",
                    dm_seat_id=dm_seat_id,
                    dm_controller_kind="ai",
                    dm_controller_access_session_id=None,
                    dm_controller_ai_grant_id=token.grant_id,
                    dm_controller_generation=1,
                    started_at=now,
                    ended_at=None,
                )
            )
            connection.execute(
                insert(ai_controller_grants).values(
                    id=token.grant_id,
                    room_id=room_id,
                    campaign_id=campaign_id,
                    seat_id=dm_seat_id,
                    role="dm",
                    session_id=session_id,
                    secret_hash=token.secret_hash,
                    secret_prefix=token.display_hint,
                    generation=1,
                    status="active",
                    pre_session_expires_at=None,
                    handoff_return_access_session_id=None,
                    temporary_instruction=None,
                    created_at=now,
                    bound_at=now,
                    revoked_at=None,
                    last_seen_at=None,
                )
            )
            connection.execute(
                update(campaign_seats)
                .where(campaign_seats.c.id == dm_seat_id)
                .values(
                    controller_kind="ai",
                    ai_controller_grant_id=token.grant_id,
                    controller_epoch=2,
                )
            )
            session = _session_row(connection, session_id)
            assert SessionLiveRepository._caller_is_current_dm(
                session,
                caller_actor_kind="ai",
                caller_access_session_id=None,
                caller_ai_grant_id=token.grant_id,
                caller_generation=1,
            )
            assert not SessionLiveRepository._revalidate_current_dm_binding(
                connection,
                session=session,
                campaign_id=campaign_id,
                caller_actor_kind="ai",
                caller_access_session_id=None,
                caller_ai_grant_id=token.grant_id,
                caller_generation=1,
            )
    finally:
        engine.dispose()
