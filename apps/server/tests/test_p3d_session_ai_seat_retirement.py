from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, insert, select, update

from app.db import metadata
from app.domain.rooms.ai_controller_tokens import mint_ai_controller_token
from app.persistence.characters import characters
from app.persistence.rooms.sessions import SessionRepository, SessionStartPersistenceError
from app.persistence.rooms.tables import (
    active_character_session_leases,
    ai_controller_grants,
    campaign_roster_entries,
    campaign_seats,
    campaigns,
    room_access_sessions,
    room_characters,
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
    dm_access_id, dm_seat_id, player_seat_id, character_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    player_grant = mint_ai_controller_token()
    participant_id = uuid4()
    connection.execute(
        insert(rooms).values(
            id=room_id,
            code="P3DRET",
            name="Retirement",
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
        insert(room_access_sessions).values(
            id=dm_access_id,
            room_id=room_id,
            authority="dm",
            token_hash=b"d" * 32,
            display_name="DM",
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
        insert(room_characters).values(room_id=room_id, character_id=character_id)
    )
    connection.execute(
        insert(campaign_roster_entries).values(
            campaign_id=campaign_id,
            character_id=character_id,
            status="active",
            added_at=now,
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
                "controller_epoch": 1,
                "selected_character_id": None,
                "archived_at": None,
            },
            {
                "id": player_seat_id,
                "campaign_id": campaign_id,
                "role": "player",
                "label": "Mira",
                "controller_kind": "none",
                "controller_access_session_id": None,
                "ai_controller_grant_id": None,
                "controller_epoch": 0,
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
            dm_controller_access_session_id=dm_access_id,
            dm_controller_ai_grant_id=None,
            dm_controller_generation=None,
            started_at=now,
            ended_at=None,
        )
    )
    connection.execute(
        insert(session_participants).values(
            id=participant_id,
            session_id=session_id,
            seat_id=player_seat_id,
            role_snapshot="player",
            controller_kind_at_join="none",
            controller_access_session_id_at_join=None,
            controller_ai_grant_id_at_join=None,
            controller_generation_at_join=None,
            active_character_id=character_id,
            joined_at=now,
            left_at=None,
        )
    )
    connection.execute(
        insert(active_character_session_leases).values(
            character_id=character_id,
            session_id=session_id,
            participant_id=participant_id,
        )
    )
    connection.execute(
        insert(ai_controller_grants).values(
            id=player_grant.grant_id,
            room_id=room_id,
            campaign_id=campaign_id,
            seat_id=player_seat_id,
            role="player",
            session_id=session_id,
            secret_hash=player_grant.secret_hash,
            secret_prefix=player_grant.display_hint,
            generation=1,
            status="active",
            pre_session_expires_at=None,
            handoff_return_access_session_id=dm_access_id,
            temporary_instruction="Only for this Session",
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
            ai_controller_grant_id=player_grant.grant_id,
            controller_epoch=1,
        )
    )
    return (
        room_id,
        campaign_id,
        session_id,
        dm_access_id,
        player_seat_id,
        character_id,
        player_grant.grant_id,
    )


def test_finalize_retires_session_ai_binding_before_next_session() -> None:
    engine = _engine()
    repository = SessionRepository(engine)
    try:
        with engine.begin() as connection:
            (
                room_id,
                campaign_id,
                session_id,
                dm_access_id,
                player_seat_id,
                character_id,
                grant_id,
            ) = _seed(connection)

        finalized = repository.finalize(session_id, status="ended")
        assert finalized is not None and finalized.status == "ended"
        assert repository.lease_for_character(character_id) is None

        with engine.connect() as connection:
            seat = connection.execute(
                select(campaign_seats).where(campaign_seats.c.id == player_seat_id)
            ).mappings().one()
            grant = connection.execute(
                select(ai_controller_grants).where(ai_controller_grants.c.id == grant_id)
            ).mappings().one()
        assert seat["controller_kind"] == "none"
        assert seat["controller_access_session_id"] is None
        assert seat["ai_controller_grant_id"] is None
        assert int(seat["controller_epoch"]) == 2
        assert grant["status"] == "revoked"
        assert grant["temporary_instruction"] is None

        next_session = repository.start_from_lobby(
            room_id=room_id,
            campaign_id=campaign_id,
            caller_access_session_id=dm_access_id,
            caller_authority="dm",
        )
        next_player = next(
            row for row in repository.list_participants(next_session.id)
            if row.seat_id == player_seat_id
        )
        assert next_player.controller_kind_at_join == "none"
        assert next_player.controller_ai_grant_id_at_join is None
        assert next_player.controller_generation_at_join is None
    finally:
        engine.dispose()


def test_start_fails_closed_on_tampered_stale_ai_player_binding() -> None:
    engine = _engine()
    repository = SessionRepository(engine)
    try:
        with engine.begin() as connection:
            (
                room_id,
                campaign_id,
                session_id,
                dm_access_id,
                _player_seat_id,
                _character_id,
                _grant_id,
            ) = _seed(connection)
        repository.finalize(session_id, status="ended")

        # Corrupt the lobby back into a stale AI Player binding to prove Start
        # does not trust controller_kind/epoch shape alone.
        with engine.begin() as connection:
            player_seat = connection.execute(
                select(campaign_seats)
                .where(campaign_seats.c.campaign_id == campaign_id, campaign_seats.c.role == "player")
            ).mappings().one()
            stale = mint_ai_controller_token()
            connection.execute(
                insert(ai_controller_grants).values(
                    id=stale.grant_id,
                    room_id=room_id,
                    campaign_id=campaign_id,
                    seat_id=player_seat["id"],
                    role="player",
                    session_id=session_id,
                    secret_hash=stale.secret_hash,
                    secret_prefix=stale.display_hint,
                    generation=int(player_seat["controller_epoch"]) + 1,
                    status="revoked",
                    pre_session_expires_at=None,
                    handoff_return_access_session_id=dm_access_id,
                    temporary_instruction=None,
                    created_at=datetime.now(timezone.utc),
                    bound_at=datetime.now(timezone.utc),
                    revoked_at=datetime.now(timezone.utc),
                    last_seen_at=None,
                )
            )
            connection.execute(
                update(campaign_seats)
                .where(campaign_seats.c.id == player_seat["id"])
                .values(
                    controller_kind="ai",
                    controller_access_session_id=None,
                    ai_controller_grant_id=stale.grant_id,
                    controller_epoch=int(player_seat["controller_epoch"]) + 1,
                )
            )

        with pytest.raises(SessionStartPersistenceError):
            repository.start_from_lobby(
                room_id=room_id,
                campaign_id=campaign_id,
                caller_access_session_id=dm_access_id,
                caller_authority="dm",
            )
        assert repository.active_for_campaign(campaign_id) is None
    finally:
        engine.dispose()
