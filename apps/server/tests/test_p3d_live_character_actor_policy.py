from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, insert

from app.api.errors import APIError
from app.api.rooms.session_scope import (
    require_live_character_actor_write,
    require_live_character_write,
)
from app.db import metadata
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.table_events import TableActorContext, TableActorKind
from app.persistence.characters import characters
from app.persistence.rooms.session_live import SessionLiveRepository
from app.persistence.rooms.tables import (
    active_character_session_leases,
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
            active_character_session_leases,
            ai_controller_grants,
        ],
    )
    return engine


def _seed_live_character(connection, *, player_kind: str):
    now = datetime.now(timezone.utc)
    room_id, campaign_id, session_id = uuid4(), uuid4(), uuid4()
    character_id, dm_seat_id, player_seat_id = uuid4(), uuid4(), uuid4()
    dm_access_id, player_access_id = uuid4(), uuid4()
    dm_grant_id, player_grant_id = uuid4(), uuid4()
    connection.execute(
        insert(rooms).values(
            id=room_id,
            code="P3DLCP",
            name="Live policy",
            password_salt=b"s" * 32,
            password_hash=b"h" * 64,
            owner_key_hash=b"o" * 32,
            dm_key_hash=b"d" * 32,
            active_campaign_id=None,
            created_at=now,
            updated_at=now,
        )
    )
    for access_id, authority in ((dm_access_id, "dm"), (player_access_id, "member")):
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
        insert(characters).values(
            id=character_id,
            name="Mira",
            ruleset="dnd5e-2014",
            current_version_id=None,
            archived_at=None,
        )
    )
    connection.execute(
        insert(ai_controller_grants),
        [
            {
                "id": dm_grant_id,
                "room_id": room_id,
                "campaign_id": campaign_id,
                "seat_id": dm_seat_id,
                "role": "dm",
                "session_id": session_id,
                "secret_hash": b"d" * 32,
                "secret_prefix": "dm",
                "generation": 3,
                "status": "active",
                "pre_session_expires_at": None,
                "handoff_return_access_session_id": None,
                "temporary_instruction": None,
                "created_at": now,
                "bound_at": now,
                "revoked_at": None,
                "last_seen_at": now,
            },
            {
                "id": player_grant_id,
                "room_id": room_id,
                "campaign_id": campaign_id,
                "seat_id": player_seat_id,
                "role": "player",
                "session_id": session_id,
                "secret_hash": b"p" * 32,
                "secret_prefix": "player",
                "generation": 7,
                "status": "active",
                "pre_session_expires_at": None,
                "handoff_return_access_session_id": player_access_id,
                "temporary_instruction": None,
                "created_at": now,
                "bound_at": now,
                "revoked_at": None,
                "last_seen_at": now,
            },
        ],
    )
    connection.execute(
        insert(campaign_seats),
        [
            {
                "id": dm_seat_id,
                "campaign_id": campaign_id,
                "role": "dm",
                "label": "DM",
                "controller_kind": "ai",
                "controller_access_session_id": None,
                "ai_controller_grant_id": dm_grant_id,
                "controller_epoch": 3,
                "selected_character_id": None,
                "archived_at": None,
            },
            {
                "id": player_seat_id,
                "campaign_id": campaign_id,
                "role": "player",
                "label": "Mira",
                "controller_kind": player_kind,
                "controller_access_session_id": (
                    player_access_id if player_kind == "human" else None
                ),
                "ai_controller_grant_id": (
                    player_grant_id if player_kind == "ai" else None
                ),
                "controller_epoch": 7,
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
            dm_controller_kind="ai",
            dm_controller_access_session_id=None,
            dm_controller_ai_grant_id=dm_grant_id,
            dm_controller_generation=3,
            started_at=now,
            ended_at=None,
        )
    )
    participant_id = uuid4()
    connection.execute(
        insert(session_participants).values(
            id=participant_id,
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
    connection.execute(
        insert(active_character_session_leases).values(
            character_id=character_id,
            session_id=session_id,
            participant_id=participant_id,
        )
    )
    return {
        "room": room_id,
        "campaign": campaign_id,
        "session": session_id,
        "character": character_id,
        "player_seat": player_seat_id,
        "player_access": player_access_id,
        "player_grant": player_grant_id,
        "dm_seat": dm_seat_id,
        "dm_grant": dm_grant_id,
    }


def test_human_policy_uses_current_player_binding_not_join_snapshot() -> None:
    engine = _engine()
    try:
        with engine.begin() as connection:
            ids = _seed_live_character(connection, player_kind="ai")
        repo = SessionLiveRepository(engine)
        stale_human = RoomAccessContext(
            room_id=ids["room"],
            access_session_id=ids["player_access"],
            authority=RoomAccessAuthority.MEMBER,
        )
        with pytest.raises(APIError):
            require_live_character_write(
                repo,
                context=stale_human,
                character_id=ids["character"],
            )
    finally:
        engine.dispose()


def test_ai_player_and_fixed_ai_dm_share_actor_policy_without_human_context() -> None:
    engine = _engine()
    try:
        with engine.begin() as connection:
            ids = _seed_live_character(connection, player_kind="ai")
        repo = SessionLiveRepository(engine)
        player = TableActorContext(
            actor_kind=TableActorKind.AI,
            room_id=ids["room"],
            campaign_id=ids["campaign"],
            session_id=ids["session"],
            seat_id=ids["player_seat"],
            controlled_seat_ids=(ids["player_seat"],),
            role="player",
            is_current_dm=False,
            ai_controller_grant_id=ids["player_grant"],
            grant_generation=7,
        )
        require_live_character_actor_write(
            repo,
            actor=player,
            character_id=ids["character"],
        )

        dm = TableActorContext(
            actor_kind=TableActorKind.AI,
            room_id=ids["room"],
            campaign_id=ids["campaign"],
            session_id=ids["session"],
            seat_id=ids["dm_seat"],
            controlled_seat_ids=(ids["dm_seat"],),
            role="dm",
            is_current_dm=True,
            ai_controller_grant_id=ids["dm_grant"],
            grant_generation=3,
        )
        require_live_character_actor_write(
            repo,
            actor=dm,
            character_id=ids["character"],
        )

        stale = player.model_copy(update={"grant_generation": 6})
        with pytest.raises(APIError):
            require_live_character_actor_write(
                repo,
                actor=stale,
                character_id=ids["character"],
            )
    finally:
        engine.dispose()
