from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, insert, update

from app.db import metadata
from app.domain.rooms.ai_controller_tokens import mint_ai_controller_token
from app.persistence.characters import characters
from app.persistence.rooms.ai_controllers import (
    AIControllerGrantRepository,
    AIControllerGrantUnauthorizedPersistenceError,
    AIControllerHandoffPersistenceError,
)
from app.persistence.rooms.tables import (
    ai_controller_grants,
    campaign_seats,
    campaigns,
    room_access_sessions,
    rooms,
    session_participants,
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
            session_participants,
            ai_controller_grants,
        ],
    )
    return engine


def _seed_access(connection, *, room_id, access_id, authority="member", name="Player"):
    now = datetime.now(timezone.utc)
    connection.execute(
        insert(room_access_sessions).values(
            id=access_id,
            room_id=room_id,
            authority=authority,
            token_hash=uuid4().bytes + uuid4().bytes,
            display_name=name,
            created_at=now,
            last_seen_at=now,
            revoked_at=None,
        )
    )


def _seed_room_campaign(connection):
    now = datetime.now(timezone.utc)
    room_id = uuid4()
    campaign_id = uuid4()
    connection.execute(
        insert(rooms).values(
            id=room_id,
            code="P3D001",
            name="P3D Room",
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
            name="P3D Campaign",
            ruleset="dnd5e-2014",
            status="active",
        )
    )
    connection.execute(
        update(rooms).where(rooms.c.id == room_id).values(active_campaign_id=campaign_id)
    )
    return room_id, campaign_id


def test_player_take_back_requires_exact_handoff_origin_access_session() -> None:
    engine = _engine()
    repo = AIControllerGrantRepository(engine)
    now = datetime.now(timezone.utc)
    room_id = campaign_id = session_id = seat_id = h1 = h2 = None
    try:
        with engine.begin() as connection:
            room_id, campaign_id = _seed_room_campaign(connection)
            h1, h2, owner = uuid4(), uuid4(), uuid4()
            _seed_access(connection, room_id=room_id, access_id=h1, name="Same Name")
            _seed_access(connection, room_id=room_id, access_id=h2, name="Same Name")
            _seed_access(connection, room_id=room_id, access_id=owner, authority="owner", name="Owner")
            character_id = uuid4()
            connection.execute(
                insert(characters).values(
                    id=character_id,
                    name="Mira",
                    ruleset="dnd5e-2014",
                    current_version_id=None,
                    archived_at=None,
                )
            )
            dm_seat_id, seat_id, session_id = uuid4(), uuid4(), uuid4()
            connection.execute(
                insert(campaign_seats),
                [
                    {
                        "id": dm_seat_id,
                        "campaign_id": campaign_id,
                        "role": "dm",
                        "label": "DM",
                        "controller_kind": "human",
                        "controller_access_session_id": owner,
                        "ai_controller_grant_id": None,
                        "controller_epoch": 1,
                        "selected_character_id": None,
                        "archived_at": None,
                    },
                    {
                        "id": seat_id,
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
                    dm_controller_access_session_id=owner,
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
                    seat_id=seat_id,
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

        minted = mint_ai_controller_token()
        with engine.begin() as connection:
            grant = repo.player_handoff_in_transaction(
                connection,
                grant_id=minted.grant_id,
                room_id=room_id,
                campaign_id=campaign_id,
                session_id=session_id,
                seat_id=seat_id,
                caller_access_session_id=h1,
                secret_hash=minted.secret_hash,
                secret_prefix=minted.display_hint,
                temporary_instruction="Protect the wizard",
                now=now,
            )
        assert grant.generation == 2
        assert grant.handoff_return_access_session_id == h1
        assert grant.temporary_instruction == "Protect the wizard"

        with engine.begin() as connection, pytest.raises(AIControllerHandoffPersistenceError):
            repo.take_back_in_transaction(
                connection,
                room_id=room_id,
                campaign_id=campaign_id,
                session_id=session_id,
                seat_id=seat_id,
                caller_access_session_id=h2,
                now=now + timedelta(seconds=1),
            )

        with engine.begin() as connection:
            repo.take_back_in_transaction(
                connection,
                room_id=room_id,
                campaign_id=campaign_id,
                session_id=session_id,
                seat_id=seat_id,
                caller_access_session_id=h1,
                now=now + timedelta(seconds=2),
            )
        with pytest.raises(AIControllerGrantUnauthorizedPersistenceError):
            repo.resolve_current_scope(grant.id)
    finally:
        engine.dispose()


def test_pre_session_dm_rotate_invalidates_old_generation_and_expiry_is_authoritative() -> None:
    engine = _engine()
    repo = AIControllerGrantRepository(engine)
    now = datetime.now(timezone.utc)
    try:
        with engine.begin() as connection:
            room_id, campaign_id = _seed_room_campaign(connection)
            dm_seat_id = uuid4()
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

        first_token = mint_ai_controller_token()
        first = repo.mint_pre_session_dm(
            grant_id=first_token.grant_id,
            room_id=room_id,
            campaign_id=campaign_id,
            seat_id=dm_seat_id,
            secret_hash=first_token.secret_hash,
            secret_prefix=first_token.display_hint,
            expires_at=now + timedelta(minutes=5),
            now=now,
        )
        assert first.generation == 1
        assert repo.resolve_current_scope(first.id, now=now + timedelta(minutes=1)).grant.id == first.id

        second_token = mint_ai_controller_token()
        second = repo.mint_pre_session_dm(
            grant_id=second_token.grant_id,
            room_id=room_id,
            campaign_id=campaign_id,
            seat_id=dm_seat_id,
            secret_hash=second_token.secret_hash,
            secret_prefix=second_token.display_hint,
            expires_at=now + timedelta(minutes=10),
            now=now + timedelta(minutes=2),
        )
        assert second.generation == 2
        with pytest.raises(AIControllerGrantUnauthorizedPersistenceError):
            repo.resolve_current_scope(first.id, now=now + timedelta(minutes=3))

        with pytest.raises(AIControllerGrantUnauthorizedPersistenceError):
            repo.resolve_current_scope(second.id, now=now + timedelta(minutes=11))
    finally:
        engine.dispose()
