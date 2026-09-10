from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import create_engine, insert, update

from app.db import metadata
from app.domain.rooms.ai_controller_tokens import mint_ai_controller_token
from app.persistence.characters import characters
from app.persistence.rooms.ai_controllers import AIControllerGrantRepository
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


def _seed_access(connection, *, room_id, access_id, authority):
    now = datetime.now(timezone.utc)
    connection.execute(
        insert(room_access_sessions).values(
            id=access_id,
            room_id=room_id,
            authority=authority,
            token_hash=uuid4().bytes + uuid4().bytes,
            display_name=authority,
            created_at=now,
            last_seen_at=now,
            revoked_at=None,
        )
    )


def _seed_live_player(connection):
    now = datetime.now(timezone.utc)
    room_id, campaign_id, session_id = uuid4(), uuid4(), uuid4()
    owner_id, player_id = uuid4(), uuid4()
    character_id, dm_seat_id, player_seat_id = uuid4(), uuid4(), uuid4()
    connection.execute(
        insert(rooms).values(
            id=room_id,
            code="P3DBND",
            name="Actor Binding",
            password_salt=b"s" * 32,
            password_hash=b"h" * 64,
            owner_key_hash=b"o" * 32,
            dm_key_hash=b"d" * 32,
            active_campaign_id=None,
            created_at=now,
            updated_at=now,
        )
    )
    _seed_access(connection, room_id=room_id, access_id=owner_id, authority="owner")
    _seed_access(connection, room_id=room_id, access_id=player_id, authority="member")
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
                "controller_access_session_id": owner_id,
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
                "controller_access_session_id": player_id,
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
            dm_controller_access_session_id=owner_id,
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
            controller_access_session_id_at_join=player_id,
            controller_ai_grant_id_at_join=None,
            controller_generation_at_join=None,
            active_character_id=character_id,
            joined_at=now,
            left_at=None,
        )
    )
    return room_id, campaign_id, session_id, player_seat_id, player_id


def test_player_authorization_tracks_current_seat_not_join_snapshot() -> None:
    engine = _engine()
    grant_repo = AIControllerGrantRepository(engine)
    table_repo = TableEventRepository(engine)
    try:
        with engine.begin() as connection:
            room_id, campaign_id, session_id, seat_id, player_id = _seed_live_player(connection)

        human = table_repo.resolve_human_actor(
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            access_session_id=player_id,
        )
        assert human is not None
        assert human.actor_kind == "human"
        assert table_repo.actor_binding_is_current(human)

        minted = mint_ai_controller_token()
        with engine.begin() as connection:
            grant = grant_repo.player_handoff_in_transaction(
                connection,
                grant_id=minted.grant_id,
                room_id=room_id,
                campaign_id=campaign_id,
                session_id=session_id,
                seat_id=seat_id,
                caller_access_session_id=player_id,
                secret_hash=minted.secret_hash,
                secret_prefix=minted.display_hint,
                temporary_instruction=None,
            )

        assert table_repo.resolve_human_actor(
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            access_session_id=player_id,
        ) is None
        assert not table_repo.actor_binding_is_current(human)

        ai = table_repo.resolve_ai_actor(
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            grant_id=grant.id,
            generation=grant.generation,
        )
        assert ai is not None
        assert ai.actor_kind == "ai"
        assert ai.seat_id == seat_id
        assert ai.controlled_seat_ids == (seat_id,)
        assert table_repo.actor_binding_is_current(ai)

        with engine.begin() as connection:
            connection.execute(
                update(campaign_seats)
                .where(campaign_seats.c.id == seat_id)
                .values(controller_epoch=grant.generation + 1)
            )
        assert not table_repo.actor_binding_is_current(ai)
    finally:
        engine.dispose()


def test_ai_dm_requires_fixed_session_grant_and_generation() -> None:
    engine = _engine()
    grant_repo = AIControllerGrantRepository(engine)
    table_repo = TableEventRepository(engine)
    now = datetime.now(timezone.utc)
    try:
        with engine.begin() as connection:
            room_id = uuid4()
            campaign_id = uuid4()
            session_id = uuid4()
            dm_seat_id = uuid4()
            connection.execute(
                insert(rooms).values(
                    id=room_id,
                    code="P3DAID",
                    name="AI DM",
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

        minted = mint_ai_controller_token()
        grant = grant_repo.mint_pre_session_dm(
            grant_id=minted.grant_id,
            room_id=room_id,
            campaign_id=campaign_id,
            seat_id=dm_seat_id,
            secret_hash=minted.secret_hash,
            secret_prefix=minted.display_hint,
            expires_at=now.replace(year=now.year + 1),
            now=now,
        )
        with engine.begin() as connection:
            connection.execute(
                insert(sessions).values(
                    id=session_id,
                    campaign_id=campaign_id,
                    status="active",
                    dm_seat_id=dm_seat_id,
                    dm_controller_kind="ai",
                    dm_controller_access_session_id=None,
                    dm_controller_ai_grant_id=grant.id,
                    dm_controller_generation=grant.generation,
                    started_at=now,
                    ended_at=None,
                )
            )
            connection.execute(
                update(ai_controller_grants)
                .where(ai_controller_grants.c.id == grant.id)
                .values(session_id=session_id, pre_session_expires_at=None, bound_at=now)
            )

        ai = table_repo.resolve_ai_actor(
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            grant_id=grant.id,
            generation=grant.generation,
        )
        assert ai is not None
        assert ai.is_current_dm

        with engine.begin() as connection:
            connection.execute(
                update(sessions)
                .where(sessions.c.id == session_id)
                .values(dm_controller_generation=grant.generation + 1)
            )
        assert table_repo.resolve_ai_actor(
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            grant_id=grant.id,
            generation=grant.generation,
        ) is None
    finally:
        engine.dispose()
