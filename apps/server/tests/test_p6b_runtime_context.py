from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
from threading import Barrier
import time
from typing import cast
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event, insert, select, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from app.db import metadata
from app.domain.adventures.attachments import CampaignAdventureService
from app.domain.adventures.schemas import (
    CampaignAdventureAttach,
    CampaignAdventureDetachBlockedError,
)
from app.domain.campaign_runtime import (
    CampaignRuntimeActiveSessionError,
    CampaignRuntimeAuthorityError,
    CampaignRuntimeContext,
    CampaignRuntimeContextPatch,
    CampaignRuntimeIdempotencyConflictError,
    CampaignRuntimeNotFoundError,
    CampaignRuntimeRevisionConflictError,
    CampaignRuntimeService,
    CampaignRuntimeSessionNotActiveError,
    CampaignRuntimeValidationError,
    RuntimeWorldEntryCreate,
)
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.table_events import (
    TableActorContext,
    TableActorKind,
    TableEventService,
)
from app.persistence.adventures.repository import (
    AdventureRepository,
    CampaignAdventureLinkRepository,
)
from app.persistence.adventures.tables import (
    adventure_definitions,
    adventure_entries,
    campaign_adventure_links,
)
from app.persistence.campaign_runtime.mutations import (
    CampaignWorldMutationRepository,
    StoredCampaignWorldMutation,
)
from app.persistence.campaign_runtime.repository import (
    CampaignRuntimeRepository,
    StoredCampaignRuntimeContextUpdate,
)
from app.persistence.campaign_runtime.tables import (
    campaign_adventure_overrides,
    campaign_runtime_context,
    campaign_world_entries,
    campaign_world_mutations,
)
from app.persistence.characters import characters
from app.persistence.rooms.campaigns import CampaignRepository
from app.persistence.rooms.table_runtime import (
    TableEventRepository,
    session_events,
    session_table_runtime,
)
from app.persistence.rooms.tables import (
    ai_controller_grants,
    campaign_seats,
    campaigns,
    room_access_sessions,
    room_characters,
    rooms,
    session_participants,
    sessions,
)


def _ev_key(k: str) -> str:
    return f"p6b-world:{hashlib.sha256(k.encode('utf-8')).hexdigest()}"


def _engine() -> Engine:
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


class RecordingNotifier:
    def __init__(self) -> None:
        self.notifications: list[UUID] = []

    def notify(self, session_id: UUID) -> None:
        self.notifications.append(session_id)

    def register(self, session_id: UUID) -> object:
        return object()

    async def wait(self, handle: object, timeout: float) -> bool:
        return False

    def unregister(self, handle: object) -> None:
        pass


@dataclass(frozen=True)
class ContextFixture:
    engine: Engine
    service: CampaignRuntimeService
    adv_service: CampaignAdventureService
    notifier: RecordingNotifier
    room_id: UUID
    other_room_id: UUID
    campaign_id: UUID
    campaign_active_id: UUID
    ai_campaign_id: UUID
    campaign_unattached_id: UUID
    other_campaign_id: UUID
    session_id: UUID
    ai_session_id: UUID
    inactive_session_id: UUID
    adv_1_id: UUID
    adv_unattached_id: UUID
    adv_other_room_id: UUID
    adv_scene_entry_id: UUID
    adv_npc_entry_id: UUID
    adv_unattached_scene_id: UUID
    adv_other_room_scene_id: UUID
    rt_scene_entry_id: UUID
    rt_archived_scene_entry_id: UUID
    rt_fact_entry_id: UUID
    rt_other_camp_scene_id: UUID
    owner_context: RoomAccessContext
    dm_context: RoomAccessContext
    member_context: RoomAccessContext
    human_dm_actor: TableActorContext
    human_player_actor: TableActorContext
    ai_dm_actor: TableActorContext
    ai_player_actor: TableActorContext
    human_dm_access_id: UUID
    ai_dm_grant_id: UUID


@pytest.fixture
def fix() -> ContextFixture:
    engine = _engine()
    notifier = RecordingNotifier()
    event_service = TableEventService(TableEventRepository(engine), notifier=notifier)
    service = CampaignRuntimeService(engine, event_service)

    link_repo = CampaignAdventureLinkRepository(engine)
    adv_repo = AdventureRepository(engine)
    camp_repo = CampaignRepository(engine)
    adv_service = CampaignAdventureService(link_repo, adv_repo, camp_repo)

    now = datetime.now(timezone.utc)
    room_id = uuid4()
    other_room_id = uuid4()

    campaign_id = uuid4()
    campaign_active_id = uuid4()
    ai_campaign_id = uuid4()
    campaign_unattached_id = uuid4()
    other_campaign_id = uuid4()

    session_id = uuid4()
    ai_session_id = uuid4()
    inactive_session_id = uuid4()

    owner_access_id = uuid4()
    dm_access_id = uuid4()
    member_access_id = uuid4()
    player_access_id = uuid4()

    dm_seat_id = uuid4()
    player_seat_id = uuid4()
    ai_dm_seat_id = uuid4()
    ai_player_seat_id = uuid4()

    char_1_id = uuid4()
    char_2_id = uuid4()

    ai_dm_grant_id = uuid4()
    ai_player_grant_id = uuid4()

    adv_1_id = uuid4()
    adv_unattached_id = uuid4()
    adv_other_room_id = uuid4()

    adv_scene_entry_id = uuid4()
    adv_npc_entry_id = uuid4()
    adv_unattached_scene_id = uuid4()
    adv_other_room_scene_id = uuid4()

    rt_scene_entry_id = uuid4()
    rt_archived_scene_entry_id = uuid4()
    rt_fact_entry_id = uuid4()
    rt_other_camp_scene_id = uuid4()

    with engine.begin() as conn:
        conn.execute(
            insert(rooms).values(
                [
                    {
                        "id": room_id,
                        "code": "ROOM-CTX-A",
                        "name": "Room Context A",
                        "password_salt": b"s" * 32,
                        "password_hash": b"p" * 64,
                        "owner_key_hash": b"o" * 32,
                        "dm_key_hash": b"d" * 32,
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": other_room_id,
                        "code": "ROOM-CTX-B",
                        "name": "Room Context B",
                        "password_salt": b"s" * 32,
                        "password_hash": b"p" * 64,
                        "owner_key_hash": b"o" * 32,
                        "dm_key_hash": b"d" * 32,
                        "created_at": now,
                        "updated_at": now,
                    },
                ]
            )
        )
        conn.execute(
            insert(room_access_sessions).values(
                [
                    {
                        "id": owner_access_id,
                        "room_id": room_id,
                        "authority": "owner",
                        "token_hash": b"tok_owner_1234567890123456",
                        "display_name": "Owner A",
                        "created_at": now,
                        "last_seen_at": now,
                    },
                    {
                        "id": dm_access_id,
                        "room_id": room_id,
                        "authority": "dm",
                        "token_hash": b"tok_dm_12345678901234567890",
                        "display_name": "DM A",
                        "created_at": now,
                        "last_seen_at": now,
                    },
                    {
                        "id": member_access_id,
                        "room_id": room_id,
                        "authority": "member",
                        "token_hash": b"tok_member_1234567890123456",
                        "display_name": "Member A",
                        "created_at": now,
                        "last_seen_at": now,
                    },
                    {
                        "id": player_access_id,
                        "room_id": room_id,
                        "authority": "member",
                        "token_hash": b"tok_player_1234567890123456",
                        "display_name": "Player 1",
                        "created_at": now,
                        "last_seen_at": now,
                    },
                ]
            )
        )
        conn.execute(
            insert(campaigns).values(
                [
                    {
                        "id": campaign_id,
                        "room_id": room_id,
                        "name": "Campaign Idle",
                        "ruleset": "dnd-5e-2014",
                        "status": "active",
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": campaign_active_id,
                        "room_id": room_id,
                        "name": "Campaign Active",
                        "ruleset": "dnd-5e-2014",
                        "status": "active",
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": ai_campaign_id,
                        "room_id": room_id,
                        "name": "Campaign AI Active",
                        "ruleset": "dnd-5e-2014",
                        "status": "active",
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": campaign_unattached_id,
                        "room_id": room_id,
                        "name": "Campaign Unattached",
                        "ruleset": "dnd-5e-2014",
                        "status": "active",
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": other_campaign_id,
                        "room_id": other_room_id,
                        "name": "Campaign Other Room",
                        "ruleset": "dnd-5e-2014",
                        "status": "active",
                        "created_at": now,
                        "updated_at": now,
                    },
                ]
            )
        )
        conn.execute(
            insert(characters).values(
                [
                    {
                        "id": char_1_id,
                        "name": "Fighter",
                        "ruleset": "dnd-5e-2014",
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": char_2_id,
                        "name": "Wizard",
                        "ruleset": "dnd-5e-2014",
                        "created_at": now,
                        "updated_at": now,
                    },
                ]
            )
        )
        conn.execute(
            insert(room_characters).values(
                [
                    {"room_id": room_id, "character_id": char_1_id, "created_at": now},
                    {"room_id": room_id, "character_id": char_2_id, "created_at": now},
                ]
            )
        )
        # Seats (initial seed)
        conn.execute(
            insert(campaign_seats).values(
                [
                    {
                        "id": dm_seat_id,
                        "campaign_id": campaign_active_id,
                        "role": "dm",
                        "controller_kind": "human",
                        "controller_access_session_id": dm_access_id,
                        "ai_controller_grant_id": None,
                        "controller_epoch": 1,
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": player_seat_id,
                        "campaign_id": campaign_active_id,
                        "role": "player",
                        "controller_kind": "human",
                        "controller_access_session_id": player_access_id,
                        "ai_controller_grant_id": None,
                        "controller_epoch": 1,
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": ai_player_seat_id,
                        "campaign_id": campaign_active_id,
                        "role": "player",
                        "controller_kind": "none",
                        "controller_access_session_id": None,
                        "ai_controller_grant_id": None,
                        "controller_epoch": 0,
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": ai_dm_seat_id,
                        "campaign_id": ai_campaign_id,
                        "role": "dm",
                        "controller_kind": "none",
                        "controller_access_session_id": None,
                        "ai_controller_grant_id": None,
                        "controller_epoch": 0,
                        "created_at": now,
                        "updated_at": now,
                    },
                ]
            )
        )

        # 1. Main sessions (Human DM)
        conn.execute(
            insert(sessions).values(
                [
                    {
                        "id": session_id,
                        "campaign_id": campaign_active_id,
                        "status": "active",
                        "dm_seat_id": dm_seat_id,
                        "dm_controller_kind": "human",
                        "dm_controller_access_session_id": dm_access_id,
                        "started_at": now,
                        "created_at": now,
                    },
                    {
                        "id": inactive_session_id,
                        "campaign_id": campaign_active_id,
                        "status": "ended",
                        "dm_seat_id": dm_seat_id,
                        "dm_controller_kind": "human",
                        "dm_controller_access_session_id": dm_access_id,
                        "started_at": now,
                        "ended_at": now,
                        "created_at": now,
                    },
                ]
            )
        )

        # 2. AI Grants
        conn.execute(
            insert(ai_controller_grants).values(
                [
                    {
                        "id": ai_dm_grant_id,
                        "room_id": room_id,
                        "campaign_id": ai_campaign_id,
                        "seat_id": ai_dm_seat_id,
                        "role": "dm",
                        "session_id": None,
                        "secret_hash": b"s" * 32,
                        "secret_prefix": "aidm",
                        "generation": 1,
                        "status": "active",
                        "pre_session_expires_at": now + timedelta(hours=1),
                        "handoff_return_access_session_id": None,
                        "temporary_instruction": None,
                        "created_at": now,
                        "bound_at": now,
                        "revoked_at": None,
                        "last_seen_at": None,
                    },
                    {
                        "id": ai_player_grant_id,
                        "room_id": room_id,
                        "campaign_id": campaign_active_id,
                        "seat_id": ai_player_seat_id,
                        "role": "player",
                        "session_id": session_id,
                        "secret_hash": b"p" * 32,
                        "secret_prefix": "aipl",
                        "generation": 1,
                        "status": "active",
                        "pre_session_expires_at": None,
                        "handoff_return_access_session_id": player_access_id,
                        "temporary_instruction": None,
                        "created_at": now,
                        "bound_at": now,
                        "revoked_at": None,
                        "last_seen_at": None,
                    },
                ]
            )
        )

        # 3. AI DM session
        conn.execute(
            insert(sessions).values(
                [
                    {
                        "id": ai_session_id,
                        "campaign_id": ai_campaign_id,
                        "status": "active",
                        "dm_seat_id": ai_dm_seat_id,
                        "dm_controller_kind": "ai",
                        "dm_controller_ai_grant_id": ai_dm_grant_id,
                        "dm_controller_generation": 1,
                        "started_at": now,
                        "created_at": now,
                    },
                ]
            )
        )

        # 4. Transition AI DM grant to active session
        conn.execute(
            update(ai_controller_grants)
            .where(ai_controller_grants.c.id == ai_dm_grant_id)
            .values(session_id=ai_session_id, pre_session_expires_at=None)
        )

        # Bind seats to AI controller grants
        conn.execute(
            update(campaign_seats)
            .where(campaign_seats.c.id == ai_dm_seat_id)
            .values(
                controller_kind="ai",
                ai_controller_grant_id=ai_dm_grant_id,
                controller_epoch=1,
            )
        )
        conn.execute(
            update(campaign_seats)
            .where(campaign_seats.c.id == ai_player_seat_id)
            .values(
                controller_kind="ai",
                ai_controller_grant_id=ai_player_grant_id,
                controller_epoch=1,
            )
        )

        # Session participants for main session
        conn.execute(
            insert(session_participants).values(
                [
                    {
                        "id": uuid4(),
                        "session_id": session_id,
                        "seat_id": dm_seat_id,
                        "role_snapshot": "dm",
                        "controller_kind_at_join": "human",
                        "controller_access_session_id_at_join": dm_access_id,
                        "controller_ai_grant_id_at_join": None,
                        "controller_generation_at_join": None,
                        "active_character_id": None,
                        "joined_at": now,
                    },
                    {
                        "id": uuid4(),
                        "session_id": session_id,
                        "seat_id": player_seat_id,
                        "role_snapshot": "player",
                        "controller_kind_at_join": "human",
                        "controller_access_session_id_at_join": player_access_id,
                        "controller_ai_grant_id_at_join": None,
                        "controller_generation_at_join": None,
                        "active_character_id": char_1_id,
                        "joined_at": now,
                    },
                    {
                        "id": uuid4(),
                        "session_id": session_id,
                        "seat_id": ai_player_seat_id,
                        "role_snapshot": "player",
                        "controller_kind_at_join": "ai",
                        "controller_access_session_id_at_join": None,
                        "controller_ai_grant_id_at_join": ai_player_grant_id,
                        "controller_generation_at_join": 1,
                        "active_character_id": char_2_id,
                        "joined_at": now,
                    },
                ]
            )
        )

        # Session participants for AI DM session
        conn.execute(
            insert(session_participants).values(
                [
                    {
                        "id": uuid4(),
                        "session_id": ai_session_id,
                        "seat_id": ai_dm_seat_id,
                        "role_snapshot": "dm",
                        "controller_kind_at_join": "ai",
                        "controller_access_session_id_at_join": None,
                        "controller_ai_grant_id_at_join": ai_dm_grant_id,
                        "controller_generation_at_join": 1,
                        "active_character_id": None,
                        "joined_at": now,
                    },
                ]
            )
        )
        conn.execute(
            insert(adventure_definitions).values(
                [
                    {
                        "id": adv_1_id,
                        "room_id": room_id,
                        "name": "Adventure 1",
                        "ruleset": "dnd-5e-2014",
                        "status": "finalized",
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": adv_unattached_id,
                        "room_id": room_id,
                        "name": "Adventure Unattached",
                        "ruleset": "dnd-5e-2014",
                        "status": "finalized",
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": adv_other_room_id,
                        "room_id": other_room_id,
                        "name": "Adventure Other Room",
                        "ruleset": "dnd-5e-2014",
                        "status": "finalized",
                        "created_at": now,
                        "updated_at": now,
                    },
                ]
            )
        )
        conn.execute(
            insert(adventure_entries).values(
                [
                    {
                        "id": adv_scene_entry_id,
                        "adventure_id": adv_1_id,
                        "parent_entry_id": None,
                        "kind": "scene",
                        "title": "Adv Scene 1",
                        "body": "A damp cave.",
                        "data_json": {"kind": "scene"},
                        "visibility": "public",
                        "sort_order": 1,
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": adv_npc_entry_id,
                        "adventure_id": adv_1_id,
                        "parent_entry_id": None,
                        "kind": "npc",
                        "title": "Adv NPC 1",
                        "body": "A goblin guard.",
                        "data_json": {"kind": "npc"},
                        "visibility": "public",
                        "sort_order": 2,
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": adv_unattached_scene_id,
                        "adventure_id": adv_unattached_id,
                        "parent_entry_id": None,
                        "kind": "scene",
                        "title": "Unattached Scene",
                        "body": "Unattached cave.",
                        "data_json": {"kind": "scene"},
                        "visibility": "public",
                        "sort_order": 1,
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": adv_other_room_scene_id,
                        "adventure_id": adv_other_room_id,
                        "parent_entry_id": None,
                        "kind": "scene",
                        "title": "Other Room Scene",
                        "body": "Other room cave.",
                        "data_json": {"kind": "scene"},
                        "visibility": "public",
                        "sort_order": 1,
                        "created_at": now,
                        "updated_at": now,
                    },
                ]
            )
        )
        conn.execute(
            insert(campaign_adventure_links).values(
                [
                    {
                        "campaign_id": campaign_id,
                        "adventure_id": adv_1_id,
                        "sort_order": 1,
                        "attached_at": now,
                    },
                    {
                        "campaign_id": campaign_active_id,
                        "adventure_id": adv_1_id,
                        "sort_order": 1,
                        "attached_at": now,
                    },
                ]
            )
        )
        conn.execute(
            insert(campaign_world_entries).values(
                [
                    {
                        "id": rt_scene_entry_id,
                        "campaign_id": campaign_id,
                        "kind": "scene",
                        "title": "RT Scene 1",
                        "body": "A stone crypt.",
                        "state_json": {"kind": "scene"},
                        "visibility": "public",
                        "needs_review": False,
                        "revision": 1,
                        "created_by_actor_kind": "human",
                        "created_by_actor_id": owner_access_id,
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": rt_archived_scene_entry_id,
                        "campaign_id": campaign_id,
                        "kind": "scene",
                        "title": "RT Archived Scene",
                        "body": "Old crypt.",
                        "state_json": {"kind": "scene"},
                        "visibility": "public",
                        "needs_review": False,
                        "revision": 1,
                        "created_by_actor_kind": "human",
                        "created_by_actor_id": owner_access_id,
                        "created_at": now,
                        "updated_at": now,
                        "archived_at": now,
                    },
                    {
                        "id": rt_fact_entry_id,
                        "campaign_id": campaign_id,
                        "kind": "fact",
                        "title": None,
                        "body": "The crypt is haunted.",
                        "state_json": {"kind": "fact"},
                        "visibility": "public",
                        "needs_review": False,
                        "revision": 1,
                        "created_by_actor_kind": "human",
                        "created_by_actor_id": owner_access_id,
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": rt_other_camp_scene_id,
                        "campaign_id": other_campaign_id,
                        "kind": "scene",
                        "title": "Other Camp Scene",
                        "body": "Other camp crypt.",
                        "state_json": {"kind": "scene"},
                        "visibility": "public",
                        "needs_review": False,
                        "revision": 1,
                        "created_by_actor_kind": "human",
                        "created_by_actor_id": owner_access_id,
                        "created_at": now,
                        "updated_at": now,
                    },
                ]
            )
        )
        conn.execute(
            update(campaign_world_entries)
            .where(campaign_world_entries.c.id == rt_archived_scene_entry_id)
            .values(archived_at=now)
        )

    owner_context = RoomAccessContext(
        room_id=room_id,
        access_session_id=owner_access_id,
        authority=RoomAccessAuthority.OWNER,
        display_name="Owner A",
    )
    dm_context = RoomAccessContext(
        room_id=room_id,
        access_session_id=dm_access_id,
        authority=RoomAccessAuthority.DM,
        display_name="DM A",
    )
    member_context = RoomAccessContext(
        room_id=room_id,
        access_session_id=member_access_id,
        authority=RoomAccessAuthority.MEMBER,
        display_name="Member A",
    )
    player_context = RoomAccessContext(
        room_id=room_id,
        access_session_id=player_access_id,
        authority=RoomAccessAuthority.MEMBER,
        display_name="Player 1",
    )

    human_dm_actor = event_service.resolve_human_actor(
        room_id=room_id,
        campaign_id=campaign_active_id,
        session_id=session_id,
        context=dm_context,
    )
    human_player_actor = event_service.resolve_human_actor(
        room_id=room_id,
        campaign_id=campaign_active_id,
        session_id=session_id,
        context=player_context,
    )
    ai_dm_actor = event_service.resolve_ai_actor(
        room_id=room_id,
        campaign_id=ai_campaign_id,
        session_id=ai_session_id,
        grant_id=ai_dm_grant_id,
        generation=1,
    )
    ai_player_actor = event_service.resolve_ai_actor(
        room_id=room_id,
        campaign_id=campaign_active_id,
        session_id=session_id,
        grant_id=ai_player_grant_id,
        generation=1,
    )

    return ContextFixture(
        engine=engine,
        service=service,
        adv_service=adv_service,
        notifier=notifier,
        room_id=room_id,
        other_room_id=other_room_id,
        campaign_id=campaign_id,
        campaign_active_id=campaign_active_id,
        ai_campaign_id=ai_campaign_id,
        campaign_unattached_id=campaign_unattached_id,
        other_campaign_id=other_campaign_id,
        session_id=session_id,
        ai_session_id=ai_session_id,
        inactive_session_id=inactive_session_id,
        adv_1_id=adv_1_id,
        adv_unattached_id=adv_unattached_id,
        adv_other_room_id=adv_other_room_id,
        adv_scene_entry_id=adv_scene_entry_id,
        adv_npc_entry_id=adv_npc_entry_id,
        adv_unattached_scene_id=adv_unattached_scene_id,
        adv_other_room_scene_id=adv_other_room_scene_id,
        rt_scene_entry_id=rt_scene_entry_id,
        rt_archived_scene_entry_id=rt_archived_scene_entry_id,
        rt_fact_entry_id=rt_fact_entry_id,
        rt_other_camp_scene_id=rt_other_camp_scene_id,
        owner_context=owner_context,
        dm_context=dm_context,
        member_context=member_context,
        human_dm_actor=human_dm_actor,
        human_player_actor=human_player_actor,
        ai_dm_actor=ai_dm_actor,
        ai_player_actor=ai_player_actor,
        human_dm_access_id=dm_access_id,
        ai_dm_grant_id=ai_dm_grant_id,
    )


# 1. get absent => all null/revision 0; update expected 0 => revision 1; persisted reload;
# situation-only; adventure scene; runtime scene; switch requires explicit clearing;
# both non-null rejected; clear => all null and revision increments without row deletion;
# subsequent update continues monotonic revision.
def test_context_lifecycle_and_invariants(fix: ContextFixture) -> None:
    # get absent
    ctx0 = fix.service.get_context_management(fix.owner_context, fix.room_id, fix.campaign_id)
    assert ctx0.campaign_id == fix.campaign_id
    assert ctx0.revision == 0
    assert ctx0.current_adventure_scene_entry_id is None
    assert ctx0.current_runtime_scene_entry_id is None
    assert ctx0.current_situation is None
    assert ctx0.created_at is None
    assert ctx0.updated_at is None

    # update expected 0 => revision 1 (situation-only)
    patch1 = CampaignRuntimeContextPatch(
        expected_revision=0,
        current_situation="A dark cave entrance.",
    )
    ctx1 = fix.service.update_context_management(
        fix.owner_context, fix.room_id, fix.campaign_id, patch1, idempotency_key="k1"
    )
    assert ctx1.campaign_id == fix.campaign_id
    assert ctx1.revision == 1
    assert ctx1.current_situation == "A dark cave entrance."
    assert ctx1.current_adventure_scene_entry_id is None
    assert ctx1.current_runtime_scene_entry_id is None
    assert ctx1.created_at is not None
    assert ctx1.updated_at is not None

    # persisted reload
    reloaded = fix.service.get_context_management(fix.owner_context, fix.room_id, fix.campaign_id)
    assert reloaded.revision == 1
    assert reloaded.current_situation == "A dark cave entrance."
    assert reloaded.created_at == ctx1.created_at

    # adventure scene
    patch2 = CampaignRuntimeContextPatch(
        expected_revision=1,
        current_adventure_scene_entry_id=fix.adv_scene_entry_id,
    )
    ctx2 = fix.service.update_context_management(
        fix.owner_context, fix.room_id, fix.campaign_id, patch2, idempotency_key="k2"
    )
    assert ctx2.revision == 2
    assert ctx2.current_adventure_scene_entry_id == fix.adv_scene_entry_id
    assert ctx2.current_runtime_scene_entry_id is None
    assert ctx2.current_situation == "A dark cave entrance."

    # switch requires explicit clearing: setting runtime scene without clearing adventure scene rejects
    patch_switch_fail = CampaignRuntimeContextPatch(
        expected_revision=2,
        current_runtime_scene_entry_id=fix.rt_scene_entry_id,
    )
    with pytest.raises(CampaignRuntimeValidationError, match="Cannot set both adventure and runtime"):
        fix.service.update_context_management(
            fix.owner_context, fix.room_id, fix.campaign_id, patch_switch_fail, idempotency_key="k3-fail"
        )

    # switch with explicit clearing of adventure scene succeeds
    patch_switch_ok = CampaignRuntimeContextPatch(
        expected_revision=2,
        current_adventure_scene_entry_id=None,
        current_runtime_scene_entry_id=fix.rt_scene_entry_id,
    )
    ctx3 = fix.service.update_context_management(
        fix.owner_context, fix.room_id, fix.campaign_id, patch_switch_ok, idempotency_key="k3"
    )
    assert ctx3.revision == 3
    assert ctx3.current_adventure_scene_entry_id is None
    assert ctx3.current_runtime_scene_entry_id == fix.rt_scene_entry_id
    assert ctx3.current_situation == "A dark cave entrance."

    # both non-null in patch rejected at schema level
    with pytest.raises(ValidationError, match="Cannot set both adventure and runtime scene references"):
        CampaignRuntimeContextPatch(
            expected_revision=3,
            current_adventure_scene_entry_id=fix.adv_scene_entry_id,
            current_runtime_scene_entry_id=fix.rt_scene_entry_id,
        )

    # clear => all null and revision increments without row deletion
    ctx4 = fix.service.clear_context_management(
        fix.owner_context, fix.room_id, fix.campaign_id, expected_revision=3, idempotency_key="k4"
    )
    assert ctx4.revision == 4
    assert ctx4.current_adventure_scene_entry_id is None
    assert ctx4.current_runtime_scene_entry_id is None
    assert ctx4.current_situation is None

    # check row in DB was not deleted
    with fix.engine.connect() as conn:
        row = conn.execute(
            select(campaign_runtime_context).where(
                campaign_runtime_context.c.campaign_id == fix.campaign_id
            )
        ).mappings().one()
        assert row["revision"] == 4
        assert row["current_adventure_scene_entry_id"] is None
        assert row["current_runtime_scene_entry_id"] is None
        assert row["current_situation"] is None

    # subsequent update continues monotonic revision
    patch5 = CampaignRuntimeContextPatch(
        expected_revision=4,
        current_situation="Sun rising over the mountains.",
    )
    ctx5 = fix.service.update_context_management(
        fix.owner_context, fix.room_id, fix.campaign_id, patch5, idempotency_key="k5"
    )
    assert ctx5.revision == 5
    assert ctx5.current_situation == "Sun rising over the mountains."


# 2. Adventure reference: attached same-Room scene succeeds; unattached/wrong Room/non-scene reject.
# Runtime reference: same-Campaign active scene succeeds; wrong Campaign/non-scene/archived reject.
def test_context_reference_validation(fix: ContextFixture) -> None:
    # Adventure reference: attached same-Room scene succeeds
    patch_ok = CampaignRuntimeContextPatch(
        expected_revision=0,
        current_adventure_scene_entry_id=fix.adv_scene_entry_id,
    )
    ctx = fix.service.update_context_management(
        fix.owner_context, fix.room_id, fix.campaign_id, patch_ok, idempotency_key="ref-ok"
    )
    assert ctx.current_adventure_scene_entry_id == fix.adv_scene_entry_id

    # Unattached adventure scene rejects
    patch_unattached = CampaignRuntimeContextPatch(
        expected_revision=1,
        current_adventure_scene_entry_id=fix.adv_unattached_scene_id,
    )
    with pytest.raises(CampaignRuntimeValidationError, match="not from an adventure attached"):
        fix.service.update_context_management(
            fix.owner_context, fix.room_id, fix.campaign_id, patch_unattached, idempotency_key="ref-unattached"
        )

    # Wrong Room adventure scene rejects with NotFound
    patch_wrong_room = CampaignRuntimeContextPatch(
        expected_revision=1,
        current_adventure_scene_entry_id=fix.adv_other_room_scene_id,
    )
    with pytest.raises(CampaignRuntimeNotFoundError, match="not found in room"):
        fix.service.update_context_management(
            fix.owner_context, fix.room_id, fix.campaign_id, patch_wrong_room, idempotency_key="ref-wrong-room"
        )

    # Non-scene adventure entry (NPC) rejects
    patch_non_scene_adv = CampaignRuntimeContextPatch(
        expected_revision=1,
        current_adventure_scene_entry_id=fix.adv_npc_entry_id,
    )
    with pytest.raises(CampaignRuntimeValidationError, match="is not a scene"):
        fix.service.update_context_management(
            fix.owner_context, fix.room_id, fix.campaign_id, patch_non_scene_adv, idempotency_key="ref-non-scene-adv"
        )

    # Runtime reference: same-Campaign active scene succeeds
    patch_rt_ok = CampaignRuntimeContextPatch(
        expected_revision=1,
        current_adventure_scene_entry_id=None,
        current_runtime_scene_entry_id=fix.rt_scene_entry_id,
    )
    ctx_rt = fix.service.update_context_management(
        fix.owner_context, fix.room_id, fix.campaign_id, patch_rt_ok, idempotency_key="ref-rt-ok"
    )
    assert ctx_rt.current_runtime_scene_entry_id == fix.rt_scene_entry_id

    # Wrong Campaign runtime scene rejects with NotFound
    patch_wrong_camp = CampaignRuntimeContextPatch(
        expected_revision=2,
        current_runtime_scene_entry_id=fix.rt_other_camp_scene_id,
    )
    with pytest.raises(CampaignRuntimeNotFoundError, match="not found in campaign"):
        fix.service.update_context_management(
            fix.owner_context, fix.room_id, fix.campaign_id, patch_wrong_camp, idempotency_key="ref-wrong-camp"
        )

    # Non-scene runtime entry (Fact) rejects
    patch_non_scene_rt = CampaignRuntimeContextPatch(
        expected_revision=2,
        current_runtime_scene_entry_id=fix.rt_fact_entry_id,
    )
    with pytest.raises(CampaignRuntimeValidationError, match="is not a scene"):
        fix.service.update_context_management(
            fix.owner_context, fix.room_id, fix.campaign_id, patch_non_scene_rt, idempotency_key="ref-non-scene-rt"
        )

    # Archived runtime scene rejects
    patch_archived_rt = CampaignRuntimeContextPatch(
        expected_revision=2,
        current_runtime_scene_entry_id=fix.rt_archived_scene_entry_id,
    )
    with pytest.raises(CampaignRuntimeValidationError, match="is archived"):
        fix.service.update_context_management(
            fix.owner_context, fix.room_id, fix.campaign_id, patch_archived_rt, idempotency_key="ref-archived-rt"
        )


# 3. Management owner/dm success with no event; member/wrong Room rejected;
# management write during active Session rejected. Active Human DM and AI DM parity;
# Player/AI Player/nonparticipant/stale/revoked/inactive/wrong scope read/write rejected via public CampaignRuntime* exceptions.
def test_context_authority_and_actor_parity(fix: ContextFixture) -> None:
    # Management: Owner write succeeds with no event/notifier
    fix.service.update_context_management(
        fix.owner_context,
        fix.room_id,
        fix.campaign_id,
        CampaignRuntimeContextPatch(expected_revision=0, current_situation="Owner write"),
        idempotency_key="m-owner",
    )
    assert len(fix.notifier.notifications) == 0

    # Management: DM write succeeds with no event/notifier
    fix.service.update_context_management(
        fix.dm_context,
        fix.room_id,
        fix.campaign_id,
        CampaignRuntimeContextPatch(expected_revision=1, current_situation="DM write"),
        idempotency_key="m-dm",
    )
    assert len(fix.notifier.notifications) == 0

    # Member rejected for read, update, clear
    with pytest.raises(CampaignRuntimeAuthorityError, match="Owner or DM authority is required"):
        fix.service.get_context_management(fix.member_context, fix.room_id, fix.campaign_id)

    with pytest.raises(CampaignRuntimeAuthorityError, match="Owner or DM authority is required"):
        fix.service.update_context_management(
            fix.member_context,
            fix.room_id,
            fix.campaign_id,
            CampaignRuntimeContextPatch(expected_revision=2, current_situation="Member write"),
            idempotency_key="m-member-write",
        )

    with pytest.raises(CampaignRuntimeAuthorityError, match="Owner or DM authority is required"):
        fix.service.clear_context_management(
            fix.member_context,
            fix.room_id,
            fix.campaign_id,
            expected_revision=2,
            idempotency_key="m-member-clear",
        )

    # Wrong Room rejected
    with pytest.raises(CampaignRuntimeNotFoundError):
        fix.service.get_context_management(fix.owner_context, fix.other_room_id, fix.campaign_id)

    with pytest.raises(CampaignRuntimeNotFoundError):
        fix.service.update_context_management(
            fix.owner_context,
            fix.other_room_id,
            fix.campaign_id,
            CampaignRuntimeContextPatch(expected_revision=2, current_situation="Wrong room"),
            idempotency_key="m-wrong-room",
        )

    # Management write during active Session rejected
    with pytest.raises(CampaignRuntimeActiveSessionError, match="has an active session"):
        fix.service.update_context_management(
            fix.owner_context,
            fix.room_id,
            fix.campaign_active_id,
            CampaignRuntimeContextPatch(expected_revision=0, current_situation="Active session write"),
            idempotency_key="m-active-write",
        )

    with pytest.raises(CampaignRuntimeActiveSessionError, match="has an active session"):
        fix.service.clear_context_management(
            fix.owner_context,
            fix.room_id,
            fix.campaign_active_id,
            expected_revision=0,
            idempotency_key="m-active-clear",
        )

    # Active: Human DM write and read
    ctx_h = fix.service.update_context_active(
        fix.human_dm_actor,
        CampaignRuntimeContextPatch(expected_revision=0, current_situation="Active Human DM write"),
        idempotency_key="a-hdm-1",
    )
    assert ctx_h.revision == 1
    assert ctx_h.current_situation == "Active Human DM write"
    read_h = fix.service.get_context_active(fix.human_dm_actor)
    assert read_h.revision == 1
    assert read_h.current_situation == "Active Human DM write"

    # Active: AI DM write and read (parity)
    ctx_ai = fix.service.update_context_active(
        fix.ai_dm_actor,
        CampaignRuntimeContextPatch(expected_revision=0, current_situation="Active AI DM write"),
        idempotency_key="a-aidm-1",
    )
    assert ctx_ai.revision == 1
    assert ctx_ai.current_situation == "Active AI DM write"
    read_ai = fix.service.get_context_active(fix.ai_dm_actor)
    assert read_ai.revision == 1
    assert read_ai.current_situation == "Active AI DM write"

    # Player / AI Player read and write rejected
    with pytest.raises(CampaignRuntimeAuthorityError, match="Only the current DM may"):
        fix.service.get_context_active(fix.human_player_actor)

    with pytest.raises(CampaignRuntimeAuthorityError, match="Only the current DM may"):
        fix.service.update_context_active(
            fix.human_player_actor,
            CampaignRuntimeContextPatch(expected_revision=2, current_situation="Player write"),
            idempotency_key="a-hp-1",
        )

    with pytest.raises(CampaignRuntimeAuthorityError, match="Only the current DM may"):
        fix.service.clear_context_active(
            fix.human_player_actor,
            expected_revision=2,
            idempotency_key="a-hp-clear",
        )

    with pytest.raises(CampaignRuntimeAuthorityError, match="Only the current DM may"):
        fix.service.get_context_active(fix.ai_player_actor)

    with pytest.raises(CampaignRuntimeAuthorityError, match="Only the current DM may"):
        fix.service.update_context_active(
            fix.ai_player_actor,
            CampaignRuntimeContextPatch(expected_revision=2, current_situation="AI Player write"),
            idempotency_key="a-aip-1",
        )

    with pytest.raises(CampaignRuntimeAuthorityError, match="Only the current DM may"):
        fix.service.clear_context_active(
            fix.ai_player_actor,
            expected_revision=2,
            idempotency_key="a-aip-clear",
        )

    # Nonparticipant rejected
    non_actor = fix.human_dm_actor.model_copy(update={"seat_id": uuid4()})
    with pytest.raises(CampaignRuntimeAuthorityError):
        fix.service.get_context_active(non_actor)

    with pytest.raises(CampaignRuntimeAuthorityError):
        fix.service.update_context_active(
            non_actor,
            CampaignRuntimeContextPatch(expected_revision=2, current_situation="Nonpart write"),
            idempotency_key="a-nonpart-1",
        )

    # Stale binding / grant generation rejected
    stale_actor = fix.ai_dm_actor.model_copy(update={"grant_generation": 999})
    with pytest.raises(CampaignRuntimeAuthorityError):
        fix.service.get_context_active(stale_actor)

    with pytest.raises(CampaignRuntimeAuthorityError):
        fix.service.update_context_active(
            stale_actor,
            CampaignRuntimeContextPatch(expected_revision=2, current_situation="Stale write"),
            idempotency_key="a-stale-1",
        )

    # Inactive session rejected
    inactive_actor = fix.human_dm_actor.model_copy(update={"session_id": fix.inactive_session_id})
    with pytest.raises(CampaignRuntimeSessionNotActiveError):
        fix.service.get_context_active(inactive_actor)

    with pytest.raises(CampaignRuntimeSessionNotActiveError):
        fix.service.update_context_active(
            inactive_actor,
            CampaignRuntimeContextPatch(expected_revision=2, current_situation="Inactive write"),
            idempotency_key="a-inact-1",
        )

    # Wrong scope rejected
    wrong_scope_actor = fix.human_dm_actor.model_copy(update={"room_id": fix.other_room_id})
    with pytest.raises(CampaignRuntimeNotFoundError):
        fix.service.get_context_active(wrong_scope_actor)

    with pytest.raises(CampaignRuntimeNotFoundError):
        fix.service.update_context_active(
            wrong_scope_actor,
            CampaignRuntimeContextPatch(expected_revision=2, current_situation="Wrong scope write"),
            idempotency_key="a-wrong-1",
        )

    # Real revocation evidence (at end of test to preserve prior checks)
    now = datetime.now(timezone.utc)

    # 1. Human DM revocation
    human_rev_key = "a-hdm-rev-1"
    ctx_pre_rev = fix.service.update_context_active(
        fix.human_dm_actor,
        CampaignRuntimeContextPatch(expected_revision=1, current_situation="Pre-revocation human"),
        idempotency_key=human_rev_key,
    )
    assert ctx_pre_rev.revision == 2
    notifications_before_h_rev = list(fix.notifier.notifications)

    # Revoke human DM room_access_session
    with fix.engine.begin() as conn:
        conn.execute(
            update(room_access_sessions)
            .where(room_access_sessions.c.id == fix.dm_context.access_session_id)
            .values(revoked_at=now)
        )

    # Read rejected
    with pytest.raises(CampaignRuntimeAuthorityError):
        fix.service.get_context_active(fix.human_dm_actor)

    # Write rejected
    with pytest.raises(CampaignRuntimeAuthorityError):
        fix.service.update_context_active(
            fix.human_dm_actor,
            CampaignRuntimeContextPatch(expected_revision=2, current_situation="Post-revocation human"),
            idempotency_key="a-hdm-rev-2",
        )

    # Exact retry rejected (stale/revoked binding cannot even replay cached mutation)
    with pytest.raises(CampaignRuntimeAuthorityError):
        fix.service.update_context_active(
            fix.human_dm_actor,
            CampaignRuntimeContextPatch(expected_revision=1, current_situation="Pre-revocation human"),
            idempotency_key=human_rev_key,
        )

    # No new notifications or context state changes
    assert fix.notifier.notifications == notifications_before_h_rev
    with fix.engine.connect() as conn:
        ctx_stored = fix.service.runtime_repo.get_context_in_transaction(conn, fix.campaign_active_id)
        assert ctx_stored is not None
        assert ctx_stored.revision == 2

    # 2. AI DM revocation
    ai_rev_key = "a-aidm-rev-1"
    ctx_ai_pre_rev = fix.service.update_context_active(
        fix.ai_dm_actor,
        CampaignRuntimeContextPatch(expected_revision=1, current_situation="Pre-revocation AI"),
        idempotency_key=ai_rev_key,
    )
    assert ctx_ai_pre_rev.revision == 2
    notifications_before_ai_rev = list(fix.notifier.notifications)

    # Revoke AI DM grant
    with fix.engine.begin() as conn:
        conn.execute(
            update(ai_controller_grants)
            .where(ai_controller_grants.c.id == fix.ai_dm_actor.ai_controller_grant_id)
            .values(revoked_at=now, status="revoked")
        )

    # Read rejected
    with pytest.raises(CampaignRuntimeAuthorityError):
        fix.service.get_context_active(fix.ai_dm_actor)

    # Write rejected
    with pytest.raises(CampaignRuntimeAuthorityError):
        fix.service.update_context_active(
            fix.ai_dm_actor,
            CampaignRuntimeContextPatch(expected_revision=2, current_situation="Post-revocation AI"),
            idempotency_key="a-aidm-rev-2",
        )

    # Exact retry rejected
    with pytest.raises(CampaignRuntimeAuthorityError):
        fix.service.update_context_active(
            fix.ai_dm_actor,
            CampaignRuntimeContextPatch(expected_revision=1, current_situation="Pre-revocation AI"),
            idempotency_key=ai_rev_key,
        )

    # No new notifications or context state changes
    assert fix.notifier.notifications == notifications_before_ai_rev
    with fix.engine.connect() as conn:
        ctx_ai_stored = fix.service.runtime_repo.get_context_in_transaction(conn, fix.ai_campaign_id)
        assert ctx_ai_stored is not None
        assert ctx_ai_stored.revision == 2


# 4. Exact retry management and active/cross-Session, plus mismatched action/command/actor collisions.
# Event is dm_only, identifier-only, one event/notifier on new success and none on retry/failure.
def test_context_idempotency_and_events(fix: ContextFixture) -> None:
    # Exact retry management
    patch_m = CampaignRuntimeContextPatch(expected_revision=0, current_situation="Management retry")
    res1 = fix.service.update_context_management(
        fix.owner_context, fix.room_id, fix.campaign_id, patch_m, idempotency_key="idem-m-1"
    )
    res1_retry = fix.service.update_context_management(
        fix.owner_context, fix.room_id, fix.campaign_id, patch_m, idempotency_key="idem-m-1"
    )
    assert res1.revision == res1_retry.revision == 1
    assert res1.current_situation == res1_retry.current_situation == "Management retry"

    # Verify no duplicate mutation row
    with fix.engine.connect() as conn:
        muts = conn.execute(
            select(campaign_world_mutations).where(
                campaign_world_mutations.c.campaign_id == fix.campaign_id,
                campaign_world_mutations.c.idempotency_key == "idem-m-1",
            )
        ).mappings().all()
        assert len(muts) == 1

    # Exact retry active
    patch_a = CampaignRuntimeContextPatch(expected_revision=0, current_situation="Active retry")
    res2 = fix.service.update_context_active(
        fix.human_dm_actor, patch_a, idempotency_key="idem-a-1"
    )
    assert res2.revision == 1

    # Check exactly 1 notification and 1 session event
    assert fix.notifier.notifications == [fix.session_id]
    with fix.engine.connect() as conn:
        evs = conn.execute(
            select(session_events).where(
                session_events.c.session_id == fix.session_id,
                session_events.c.kind == "world.context_changed",
            )
        ).mappings().all()
        assert len(evs) == 1
        ev = evs[0]
        assert ev["visibility"] == "dm_only"
        assert ev["recipient_seat_ids"] == []
        # Event is identifier-safe: revision and action only, never situation text
        assert ev["payload"] == {"revision": 1, "action": "updated"}
        cursor = conn.execute(
            select(session_table_runtime.c.last_event_seq).where(
                session_table_runtime.c.session_id == fix.session_id
            )
        ).scalar_one()
        assert cursor == 1

    # Active retry
    res2_retry = fix.service.update_context_active(
        fix.human_dm_actor, patch_a, idempotency_key="idem-a-1"
    )
    assert res2_retry.revision == 1
    assert res2_retry.current_situation == "Active retry"

    # Check NO second notification and NO second event
    assert fix.notifier.notifications == [fix.session_id]
    with fix.engine.connect() as conn:
        evs = conn.execute(
            select(session_events).where(
                session_events.c.session_id == fix.session_id,
                session_events.c.kind == "world.context_changed",
            )
        ).mappings().all()
        assert len(evs) == 1
        cursor = conn.execute(
            select(session_table_runtime.c.last_event_seq).where(
                session_table_runtime.c.session_id == fix.session_id
            )
        ).scalar_one()
        assert cursor == 1

    # End original session to respect single-active-Session invariant
    now = datetime.now(timezone.utc)
    with fix.engine.begin() as conn:
        conn.execute(
            update(sessions)
            .where(sessions.c.id == fix.session_id)
            .values(status="ended", ended_at=now)
        )
        conn.execute(
            update(session_participants)
            .where(session_participants.c.session_id == fix.session_id)
            .values(left_at=now)
        )

    # Old actor must now fail SessionNotActive
    with pytest.raises(CampaignRuntimeSessionNotActiveError):
        fix.service.get_context_active(fix.human_dm_actor)
    with pytest.raises(CampaignRuntimeSessionNotActiveError):
        fix.service.update_context_active(
            fix.human_dm_actor, patch_a, idempotency_key="idem-a-1"
        )

    # Create next active Session and participant
    sess_2_id = uuid4()
    with fix.engine.begin() as conn:
        conn.execute(
            insert(sessions).values(
                id=sess_2_id,
                campaign_id=fix.campaign_active_id,
                status="active",
                dm_seat_id=fix.human_dm_actor.seat_id,
                dm_controller_kind="human",
                dm_controller_access_session_id=fix.dm_context.access_session_id,
                started_at=now,
                created_at=now,
            )
        )
        conn.execute(
            insert(session_participants).values(
                id=uuid4(),
                session_id=sess_2_id,
                seat_id=fix.human_dm_actor.seat_id,
                role_snapshot="dm",
                controller_kind_at_join="human",
                controller_access_session_id_at_join=fix.dm_context.access_session_id,
                joined_at=now,
            )
        )

    alt_dm_actor = fix.human_dm_actor.model_copy(update={"session_id": sess_2_id})

    # Exact replay by new active DM returns stored result without second event or notifier
    res_cross = fix.service.update_context_active(
        alt_dm_actor, patch_a, idempotency_key="idem-a-1"
    )
    assert res_cross.revision == 1
    assert fix.notifier.notifications == [fix.session_id]
    with fix.engine.connect() as conn:
        evs_sess_2 = conn.execute(
            select(session_events).where(
                session_events.c.session_id == sess_2_id,
            )
        ).mappings().all()
        assert len(evs_sess_2) == 0

    # Mismatched collisions using alt_dm_actor:
    # 1. Same idempotency_key with different command
    patch_diff = CampaignRuntimeContextPatch(expected_revision=0, current_situation="Different situation")
    with pytest.raises(CampaignRuntimeIdempotencyConflictError, match="different command or actor identity"):
        fix.service.update_context_active(
            alt_dm_actor, patch_diff, idempotency_key="idem-a-1"
        )

    # 2. Same idempotency_key with different action_kind
    with pytest.raises(CampaignRuntimeIdempotencyConflictError, match="different command or actor identity"):
        fix.service.clear_context_active(
            alt_dm_actor, expected_revision=0, idempotency_key="idem-a-1"
        )

    # 3. Same idempotency_key with different actor
    mgmt_actor_key = "idem-mgmt-actor-coll"
    fix.service.update_context_management(
        fix.dm_context,
        fix.room_id,
        fix.campaign_id,
        CampaignRuntimeContextPatch(expected_revision=1, current_situation="Actor coll"),
        idempotency_key=mgmt_actor_key,
    )
    with pytest.raises(CampaignRuntimeIdempotencyConflictError, match="different command or actor identity"):
        fix.service.update_context_management(
            fix.owner_context,
            fix.room_id,
            fix.campaign_id,
            CampaignRuntimeContextPatch(expected_revision=1, current_situation="Actor coll"),
            idempotency_key=mgmt_actor_key,
        )

    # 4. Successful active clear coverage in the new current Session (sess_2)
    clear_key = "idem-clear-sess2"
    res_clear = fix.service.clear_context_active(
        alt_dm_actor,
        expected_revision=1,
        idempotency_key=clear_key,
    )
    assert res_clear.revision == 2
    assert res_clear.current_adventure_scene_entry_id is None
    assert res_clear.current_runtime_scene_entry_id is None
    assert res_clear.current_situation is None

    # Event world.context_changed is dm_only with payload exactly {"revision": 2, "action": "cleared"}
    # and notifier exactly once for sess_2
    assert fix.notifier.notifications == [fix.session_id, sess_2_id]
    with fix.engine.connect() as conn:
        evs_sess_2 = conn.execute(
            select(session_events).where(
                session_events.c.session_id == sess_2_id,
                session_events.c.kind == "world.context_changed",
            )
        ).mappings().all()
        assert len(evs_sess_2) == 1
        ev_clear = evs_sess_2[0]
        assert ev_clear["visibility"] == "dm_only"
        assert ev_clear["recipient_seat_ids"] == []
        assert ev_clear["payload"] == {"revision": 2, "action": "cleared"}
        cursor = conn.execute(
            select(session_table_runtime.c.last_event_seq).where(
                session_table_runtime.c.session_id == sess_2_id
            )
        ).scalar_one()
        assert cursor == 1

    # Exact retry of clear_context_active adds no event/cursor/notifier
    res_clear_retry = fix.service.clear_context_active(
        alt_dm_actor,
        expected_revision=1,
        idempotency_key=clear_key,
    )
    assert res_clear_retry.revision == 2
    assert res_clear_retry.current_adventure_scene_entry_id is None
    assert res_clear_retry.current_runtime_scene_entry_id is None
    assert res_clear_retry.current_situation is None
    assert fix.notifier.notifications == [fix.session_id, sess_2_id]
    with fix.engine.connect() as conn:
        evs_sess_2_after = conn.execute(
            select(session_events).where(
                session_events.c.session_id == sess_2_id,
                session_events.c.kind == "world.context_changed",
            )
        ).mappings().all()
        assert len(evs_sess_2_after) == 1
        cursor_after = conn.execute(
            select(session_table_runtime.c.last_event_seq).where(
                session_table_runtime.c.session_id == sess_2_id
            )
        ).scalar_one()
        assert cursor_after == 1


# 5. Post-write failure after real context CAS/insert (wrap real mutation insert and raise)
# rolls back context/mutation/event/cursor and no notifier.
# Stale revision has zero side effects. Cover first-insert concurrent conflict and existing-row two-writer conflict.
def test_context_rollback_and_conflicts(fix: ContextFixture) -> None:
    # Post-write failure: wrap mutation_repo.insert_in_transaction and raise
    real_insert = fix.service.mutation_repo.insert_in_transaction

    def failing_insert(conn, mut):
        real_insert(conn, mut)
        raise RuntimeError("simulated post-write failure")

    fix.service.mutation_repo.insert_in_transaction = failing_insert  # type: ignore[assignment]
    try:
        patch = CampaignRuntimeContextPatch(expected_revision=0, current_situation="Will fail")
        with pytest.raises(RuntimeError, match="simulated post-write failure"):
            fix.service.update_context_active(
                fix.human_dm_actor, patch, idempotency_key="boom-1"
            )
    finally:
        fix.service.mutation_repo.insert_in_transaction = real_insert  # type: ignore[assignment]

    # Verify context was rolled back (row does not exist)
    with fix.engine.connect() as conn:
        ctx_row = conn.execute(
            select(campaign_runtime_context).where(
                campaign_runtime_context.c.campaign_id == fix.campaign_active_id
            )
        ).mappings().one_or_none()
        assert ctx_row is None

        # Verify mutation was rolled back
        mut_row = conn.execute(
            select(campaign_world_mutations).where(
                campaign_world_mutations.c.idempotency_key == "boom-1"
            )
        ).mappings().one_or_none()
        assert mut_row is None

        # Verify session_events was rolled back
        ev_rows = conn.execute(
            select(session_events).where(session_events.c.session_id == fix.session_id)
        ).mappings().all()
        assert len(ev_rows) == 0

        # Verify cursor was rolled back
        cursor = conn.execute(
            select(session_table_runtime.c.last_event_seq).where(
                session_table_runtime.c.session_id == fix.session_id
            )
        ).scalar_one_or_none()
        assert cursor in (None, 0)

    # Verify notifier was not called
    assert fix.session_id not in fix.notifier.notifications

    # Stale revision has zero side effects
    with pytest.raises(CampaignRuntimeRevisionConflictError):
        fix.service.update_context_active(
            fix.human_dm_actor,
            CampaignRuntimeContextPatch(expected_revision=999, current_situation="Stale revision"),
            idempotency_key="stale-rev",
        )
    assert fix.session_id not in fix.notifier.notifications

    # First-insert concurrent conflict:
    # Directly test CampaignRuntimeRepository.update_context_in_transaction with expected_revision=0
    # when row already exists
    # First insert succeeds:
    fix.service.runtime_repo.update_context(
        fix.campaign_id,
        StoredCampaignRuntimeContextUpdate(
            expected_revision=0,
            current_adventure_scene_entry_id=None,
            current_runtime_scene_entry_id=None,
            current_situation="First writer",
            updated_at=datetime.now(timezone.utc),
        ),
    )
    # Second insert with expected_revision=0 fails with conflict:
    with pytest.raises(CampaignRuntimeRevisionConflictError) as exc_info:
        fix.service.update_context_management(
            fix.owner_context,
            fix.room_id,
            fix.campaign_id,
            CampaignRuntimeContextPatch(expected_revision=0, current_situation="Second writer"),
            idempotency_key="race-0",
        )
    assert exc_info.value.expected_revision == 0
    assert exc_info.value.current_revision == 1

    # Existing-row two-writer conflict:
    # Both writers expect revision 1, writer 1 succeeds (revision becomes 2)
    fix.service.update_context_management(
        fix.owner_context,
        fix.room_id,
        fix.campaign_id,
        CampaignRuntimeContextPatch(expected_revision=1, current_situation="Writer 1"),
        idempotency_key="writer-1",
    )
    # Writer 2 still expects revision 1, fails with conflict
    with pytest.raises(CampaignRuntimeRevisionConflictError) as exc_info2:
        fix.service.update_context_management(
            fix.owner_context,
            fix.room_id,
            fix.campaign_id,
            CampaignRuntimeContextPatch(expected_revision=1, current_situation="Writer 2"),
            idempotency_key="writer-2",
        )
    assert exc_info2.value.expected_revision == 1
    assert exc_info2.value.current_revision == 2


# 6. PostgreSQL concurrency evidence gated by P4_POSTGRES_URL + xdist_group postgres
# using dedicated reset schema pattern:
# - same revision two updates => one commit/one stable conflict
# - detach vs set-current-Adventure-scene in both lock-order outcomes => never a detached Adventure referenced by context.
POSTGRES_URL = os.environ.get("P4_POSTGRES_URL")
SERVER_ROOT = Path(__file__).resolve().parents[1]


def _alembic_config() -> Config:
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SERVER_ROOT / "alembic"))
    assert POSTGRES_URL is not None
    config.set_main_option("sqlalchemy.url", POSTGRES_URL)
    config.attributes["target_database_url"] = POSTGRES_URL
    return config


@pytest.mark.xdist_group("postgres")
@pytest.mark.skipif(
    not POSTGRES_URL,
    reason="P4_POSTGRES_URL is only supplied by the P4 PostgreSQL job",
)
def test_postgres_context_concurrency_and_detach_race() -> None:
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    try:
        with engine.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
        command.upgrade(_alembic_config(), "heads")

        now = datetime.now(timezone.utc)
        room_id = uuid4()
        campaign_id = uuid4()
        adv_id = uuid4()
        scene_entry_id = uuid4()
        owner_access_id = uuid4()
        dm_access_id = uuid4()

        with engine.begin() as conn:
            conn.execute(
                insert(rooms).values(
                    id=room_id,
                    code="PG-CTX",
                    name="PG Context Room",
                    password_salt=b"s" * 32,
                    password_hash=b"p" * 64,
                    owner_key_hash=b"o" * 32,
                    dm_key_hash=b"d" * 32,
                    created_at=now,
                    updated_at=now,
                )
            )
            conn.execute(
                insert(room_access_sessions).values(
                    [
                        {
                            "id": owner_access_id,
                            "room_id": room_id,
                            "authority": "owner",
                            "token_hash": b"tok_owner_pg_ctx_12345678",
                            "display_name": "Owner",
                            "created_at": now,
                            "last_seen_at": now,
                        },
                        {
                            "id": dm_access_id,
                            "room_id": room_id,
                            "authority": "dm",
                            "token_hash": b"tok_dm_pg_ctx_12345678901",
                            "display_name": "DM",
                            "created_at": now,
                            "last_seen_at": now,
                        },
                    ]
                )
            )
            conn.execute(
                insert(campaigns).values(
                    id=campaign_id,
                    room_id=room_id,
                    name="PG Context Campaign",
                    ruleset="dnd-5e-2014",
                    status="active",
                    created_at=now,
                    updated_at=now,
                )
            )
            conn.execute(
                insert(adventure_definitions).values(
                    id=adv_id,
                    room_id=room_id,
                    name="PG Context Adventure",
                    summary="Test Adventure",
                    status="finalized",
                    created_at=now,
                    updated_at=now,
                )
            )
            conn.execute(
                insert(adventure_entries).values(
                    id=scene_entry_id,
                    adventure_id=adv_id,
                    parent_entry_id=None,
                    kind="scene",
                    title="PG Scene",
                    body="A scene in the adventure.",
                    data_json={"kind": "scene"},
                    visibility="public",
                    sort_order=1,
                    created_at=now,
                    updated_at=now,
                )
            )
            conn.execute(
                insert(campaign_adventure_links).values(
                    campaign_id=campaign_id,
                    adventure_id=adv_id,
                    sort_order=1,
                    attached_at=now,
                )
            )

        owner_ctx = RoomAccessContext(
            room_id=room_id,
            access_session_id=owner_access_id,
            authority=RoomAccessAuthority.OWNER,
            display_name="Owner",
        )
        dm_ctx = RoomAccessContext(
            room_id=room_id,
            access_session_id=dm_access_id,
            authority=RoomAccessAuthority.DM,
            display_name="DM",
        )

        link_repo = CampaignAdventureLinkRepository(engine)
        adv_repo = AdventureRepository(engine)
        camp_repo = CampaignRepository(engine)
        adv_svc = CampaignAdventureService(link_repo, adv_repo, camp_repo)

        event_repo = TableEventRepository(engine)
        event_svc = TableEventService(event_repo)
        runtime_svc = CampaignRuntimeService(engine, event_svc)

        # Part 1: Same revision two updates => one commit, one stable conflict
        barrier_1 = Barrier(2)
        err_1: Exception | None = None
        err_2: Exception | None = None

        def update_worker_1() -> None:
            nonlocal err_1
            try:
                barrier_1.wait(timeout=10)
                runtime_svc.update_context_management(
                    dm_ctx,
                    room_id,
                    campaign_id,
                    CampaignRuntimeContextPatch(expected_revision=0, current_situation="Writer 1 PG"),
                    idempotency_key="pg-race-1",
                )
            except Exception as e:
                err_1 = e

        def update_worker_2() -> None:
            nonlocal err_2
            try:
                barrier_1.wait(timeout=10)
                runtime_svc.update_context_management(
                    dm_ctx,
                    room_id,
                    campaign_id,
                    CampaignRuntimeContextPatch(expected_revision=0, current_situation="Writer 2 PG"),
                    idempotency_key="pg-race-2",
                )
            except Exception as e:
                err_2 = e

        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(update_worker_1)
            f2 = pool.submit(update_worker_2)
            f1.result(timeout=15)
            f2.result(timeout=15)

        # Exactly one committed, one got revision conflict
        errors = [e for e in (err_1, err_2) if e is not None]
        assert len(errors) == 1
        assert isinstance(errors[0], CampaignRuntimeRevisionConflictError)

        with engine.connect() as conn:
            ctx_row = conn.execute(
                select(campaign_runtime_context).where(
                    campaign_runtime_context.c.campaign_id == campaign_id
                )
            ).mappings().one()
            assert ctx_row["revision"] == 1

        # Part 2: Detach vs set-current-Adventure-scene in both lock-order outcomes
        # Outcome A: Detach acquires campaign lock first
        barrier_a = Barrier(2)
        detach_a_err: Exception | None = None
        update_a_err: Exception | None = None

        def detach_first() -> None:
            nonlocal detach_a_err
            try:
                with engine.begin() as conn:
                    conn.execute(
                        select(campaigns.c.id)
                        .where(campaigns.c.id == campaign_id)
                        .with_for_update()
                    ).one()
                    barrier_a.wait(timeout=10)
                    time.sleep(0.3)
                    conn.execute(
                        campaign_adventure_links.delete().where(
                            campaign_adventure_links.c.campaign_id == campaign_id,
                            campaign_adventure_links.c.adventure_id == adv_id,
                        )
                    )
            except Exception as e:
                detach_a_err = e

        def update_second() -> None:
            nonlocal update_a_err
            try:
                barrier_a.wait(timeout=10)
                runtime_svc.update_context_management(
                    dm_ctx,
                    room_id,
                    campaign_id,
                    CampaignRuntimeContextPatch(
                        expected_revision=1,
                        current_adventure_scene_entry_id=scene_entry_id,
                    ),
                    idempotency_key="pg-race-set-scene-1",
                )
            except Exception as e:
                update_a_err = e

        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(detach_first)
            f2 = pool.submit(update_second)
            f1.result(timeout=15)
            f2.result(timeout=15)

        assert detach_a_err is None
        assert isinstance(update_a_err, CampaignRuntimeValidationError)

        with engine.connect() as conn:
            # Adventure is detached
            link = conn.execute(
                select(campaign_adventure_links).where(
                    campaign_adventure_links.c.campaign_id == campaign_id,
                    campaign_adventure_links.c.adventure_id == adv_id,
                )
            ).one_or_none()
            assert link is None
            # Context does NOT point to the detached adventure
            ctx = conn.execute(
                select(campaign_runtime_context).where(
                    campaign_runtime_context.c.campaign_id == campaign_id
                )
            ).mappings().one()
            assert ctx["current_adventure_scene_entry_id"] is None

        # Outcome B: Set-current-Adventure-scene acquires campaign lock first
        # Re-attach adventure
        adv_svc.attach(
            owner_ctx,
            room_id,
            campaign_id,
            CampaignAdventureAttach(adventure_id=adv_id),
        )

        barrier_b = Barrier(2)
        update_b_err: Exception | None = None
        detach_b_err: Exception | None = None

        def update_first() -> None:
            nonlocal update_b_err
            try:
                with engine.begin() as conn:
                    conn.execute(
                        select(campaigns.c.id)
                        .where(campaigns.c.id == campaign_id)
                        .with_for_update()
                    ).one()
                    barrier_b.wait(timeout=10)
                    time.sleep(0.3)
                    conn.execute(
                        campaign_runtime_context.update()
                        .where(campaign_runtime_context.c.campaign_id == campaign_id)
                        .values(
                            current_adventure_scene_entry_id=scene_entry_id,
                            revision=campaign_runtime_context.c.revision + 1,
                            updated_at=datetime.now(timezone.utc),
                        )
                    )
            except Exception as e:
                update_b_err = e

        def detach_second() -> None:
            nonlocal detach_b_err
            try:
                barrier_b.wait(timeout=10)
                adv_svc.detach(owner_ctx, room_id, campaign_id, adv_id)
            except Exception as e:
                detach_b_err = e

        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(update_first)
            f2 = pool.submit(detach_second)
            f1.result(timeout=15)
            f2.result(timeout=15)

        assert update_b_err is None
        assert isinstance(detach_b_err, CampaignAdventureDetachBlockedError)

        with engine.connect() as conn:
            # Adventure is still attached
            link = conn.execute(
                select(campaign_adventure_links).where(
                    campaign_adventure_links.c.campaign_id == campaign_id,
                    campaign_adventure_links.c.adventure_id == adv_id,
                )
            ).one_or_none()
            assert link is not None
            # Context points to the attached adventure
            ctx = conn.execute(
                select(campaign_runtime_context).where(
                    campaign_runtime_context.c.campaign_id == campaign_id
                )
            ).mappings().one()
            assert ctx["current_adventure_scene_entry_id"] == scene_entry_id
    finally:
        engine.dispose()
