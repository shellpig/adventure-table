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
from sqlalchemy import create_engine, event, insert, select, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from app.db import metadata
from app.domain.adventures.attachments import CampaignAdventureService
from app.domain.adventures.schemas import (
    AdventureAlreadyAttachedError,
    CampaignAdventureAttach,
    CampaignAdventureDetachBlockedError,
)
from app.domain.campaign_runtime import (
    CampaignAdventureEntryOverlayView,
    CampaignAdventureOverride,
    CampaignAdventureOverrideAlreadyExistsError,
    CampaignAdventureOverrideCreate,
    CampaignAdventureOverridePatch,
    CampaignRuntimeActiveSessionError,
    CampaignRuntimeAuthorityError,
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
from app.persistence.campaign_runtime.mutations import CampaignWorldMutationRepository
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
class OverrideFixture:
    engine: Engine
    service: CampaignRuntimeService
    adv_service: CampaignAdventureService
    notifier: RecordingNotifier
    room_id: UUID
    other_room_id: UUID
    campaign_id: UUID
    campaign_active_id: UUID
    ai_campaign_id: UUID
    session_id: UUID
    ai_session_id: UUID
    inactive_session_id: UUID
    adv_1_id: UUID
    adv_2_unattached_id: UUID
    adv_other_room_id: UUID
    npc_entry_id: UUID
    scene_entry_id: UUID
    unattached_entry_id: UUID
    other_room_entry_id: UUID
    owner_context: RoomAccessContext
    dm_context: RoomAccessContext
    member_context: RoomAccessContext
    human_dm_actor: TableActorContext
    human_player_actor: TableActorContext
    ai_dm_actor: TableActorContext
    ai_player_actor: TableActorContext


@pytest.fixture
def fix() -> OverrideFixture:
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

    owner_access_id = uuid4()
    dm_access_id = uuid4()
    member_access_id = uuid4()

    owner_context = RoomAccessContext(
        room_id=room_id,
        access_session_id=owner_access_id,
        authority=RoomAccessAuthority.OWNER,
        display_name="Owner",
    )
    dm_context = RoomAccessContext(
        room_id=room_id,
        access_session_id=dm_access_id,
        authority=RoomAccessAuthority.DM,
        display_name="DM",
    )
    member_context = RoomAccessContext(
        room_id=room_id,
        access_session_id=member_access_id,
        authority=RoomAccessAuthority.MEMBER,
        display_name="Member",
    )

    campaign_id = uuid4()
    campaign_active_id = uuid4()
    ai_campaign_id = uuid4()
    session_id = uuid4()
    ai_session_id = uuid4()
    inactive_session_id = uuid4()

    dm_seat_id = uuid4()
    player_1_seat_id = uuid4()
    player_2_seat_id = uuid4()
    ai_dm_seat_id = uuid4()

    ai_dm_grant_id = uuid4()
    ai_player_grant_id = uuid4()

    char_1_id = uuid4()
    char_2_id = uuid4()

    adv_1_id = uuid4()
    adv_2_unattached_id = uuid4()
    adv_other_room_id = uuid4()

    npc_entry_id = uuid4()
    scene_entry_id = uuid4()
    unattached_entry_id = uuid4()
    other_room_entry_id = uuid4()

    with engine.begin() as conn:
        # Rooms
        conn.execute(
            insert(rooms).values(
                [
                    {
                        "id": room_id,
                        "code": "ROOM-OVR",
                        "name": "Override Room",
                        "password_salt": b"salt",
                        "password_hash": b"pw",
                        "owner_key_hash": b"owner",
                        "dm_key_hash": b"dm",
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": other_room_id,
                        "code": "ROOM-OTHER",
                        "name": "Other Room",
                        "password_salt": b"salt",
                        "password_hash": b"pw",
                        "owner_key_hash": b"owner",
                        "dm_key_hash": b"dm",
                        "created_at": now,
                        "updated_at": now,
                    },
                ]
            )
        )

        # Room access sessions
        conn.execute(
            insert(room_access_sessions).values(
                [
                    {
                        "id": owner_access_id,
                        "room_id": room_id,
                        "authority": "owner",
                        "token_hash": b"tok_owner_hash_1234567890",
                        "display_name": "Owner",
                        "created_at": now,
                        "last_seen_at": now,
                    },
                    {
                        "id": dm_access_id,
                        "room_id": room_id,
                        "authority": "dm",
                        "token_hash": b"tok_dm_hash_1234567890123",
                        "display_name": "DM",
                        "created_at": now,
                        "last_seen_at": now,
                    },
                    {
                        "id": member_access_id,
                        "room_id": room_id,
                        "authority": "member",
                        "token_hash": b"tok_mem_hash_1234567890123",
                        "display_name": "Member",
                        "created_at": now,
                        "last_seen_at": now,
                    },
                ]
            )
        )

        # Campaigns
        conn.execute(
            insert(campaigns).values(
                [
                    {
                        "id": campaign_id,
                        "room_id": room_id,
                        "name": "Idle Campaign",
                        "ruleset": "dnd-5e-2014",
                        "status": "active",
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": campaign_active_id,
                        "room_id": room_id,
                        "name": "Active Session Campaign",
                        "ruleset": "dnd-5e-2014",
                        "status": "active",
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": ai_campaign_id,
                        "room_id": room_id,
                        "name": "AI Active Campaign",
                        "ruleset": "dnd-5e-2014",
                        "status": "active",
                        "created_at": now,
                        "updated_at": now,
                    },
                ]
            )
        )

        # Characters
        for cid, name in [
            (char_1_id, "Fighter 1"),
            (char_2_id, "Wizard 2"),
        ]:
            conn.execute(
                insert(characters).values(
                    id=cid,
                    name=name,
                    ruleset="dnd-5e-2014",
                    created_at=now,
                    updated_at=now,
                )
            )
            conn.execute(
                insert(room_characters).values(
                    room_id=room_id,
                    character_id=cid,
                    created_at=now,
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
                        "id": player_1_seat_id,
                        "campaign_id": campaign_active_id,
                        "role": "player",
                        "controller_kind": "human",
                        "controller_access_session_id": member_access_id,
                        "ai_controller_grant_id": None,
                        "controller_epoch": 1,
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": player_2_seat_id,
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
                        "seat_id": player_2_seat_id,
                        "role": "player",
                        "session_id": session_id,
                        "secret_hash": b"p" * 32,
                        "secret_prefix": "aipl",
                        "generation": 1,
                        "status": "active",
                        "pre_session_expires_at": None,
                        "handoff_return_access_session_id": member_access_id,
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
            .where(campaign_seats.c.id == player_2_seat_id)
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
                        "seat_id": player_1_seat_id,
                        "role_snapshot": "player",
                        "controller_kind_at_join": "human",
                        "controller_access_session_id_at_join": member_access_id,
                        "controller_ai_grant_id_at_join": None,
                        "controller_generation_at_join": None,
                        "active_character_id": char_1_id,
                        "joined_at": now,
                    },
                    {
                        "id": uuid4(),
                        "session_id": session_id,
                        "seat_id": player_2_seat_id,
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

        # Adventures
        conn.execute(
            insert(adventure_definitions).values(
                [
                    {
                        "id": adv_1_id,
                        "room_id": room_id,
                        "name": "Lost Mine",
                        "summary": "Adventure 1",
                        "status": "finalized",
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": adv_2_unattached_id,
                        "room_id": room_id,
                        "name": "Sunless Citadel",
                        "summary": "Adventure 2",
                        "status": "finalized",
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": adv_other_room_id,
                        "room_id": other_room_id,
                        "name": "Other Room Adventure",
                        "summary": "Adventure Other",
                        "status": "finalized",
                        "created_at": now,
                        "updated_at": now,
                    },
                ]
            )
        )

        # Adventure Entries
        conn.execute(
            insert(adventure_entries).values(
                [
                    {
                        "id": npc_entry_id,
                        "adventure_id": adv_1_id,
                        "parent_entry_id": None,
                        "kind": "npc",
                        "title": "Gundren Rockseeker",
                        "body": "A dwarf patron.",
                        "data_json": {"kind": "npc", "disposition": "neutral", "role": "patron"},
                        "visibility": "public",
                        "sort_order": 1,
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": scene_entry_id,
                        "adventure_id": adv_1_id,
                        "parent_entry_id": None,
                        "kind": "scene",
                        "title": "Cragmaw Hideout",
                        "body": "A cave entrance.",
                        "data_json": {"kind": "scene", "read_aloud": "You see a dark cave."},
                        "visibility": "dm_only",
                        "sort_order": 2,
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": unattached_entry_id,
                        "adventure_id": adv_2_unattached_id,
                        "parent_entry_id": None,
                        "kind": "npc",
                        "title": "Meepo",
                        "body": "A kobold keeper.",
                        "data_json": {"kind": "npc", "disposition": "friendly"},
                        "visibility": "public",
                        "sort_order": 1,
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": other_room_entry_id,
                        "adventure_id": adv_other_room_id,
                        "parent_entry_id": None,
                        "kind": "npc",
                        "title": "Other NPC",
                        "body": "In other room.",
                        "data_json": {"kind": "npc", "disposition": "neutral"},
                        "visibility": "public",
                        "sort_order": 1,
                        "created_at": now,
                        "updated_at": now,
                    },
                ]
            )
        )

        # Links (adv_1 is attached to campaign_id, campaign_active_id, and ai_campaign_id)
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
                    {
                        "campaign_id": ai_campaign_id,
                        "adventure_id": adv_1_id,
                        "sort_order": 1,
                        "attached_at": now,
                    },
                ]
            )
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
        context=member_context,
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

    return OverrideFixture(
        engine=engine,
        service=service,
        adv_service=adv_service,
        notifier=notifier,
        room_id=room_id,
        other_room_id=other_room_id,
        campaign_id=campaign_id,
        campaign_active_id=campaign_active_id,
        ai_campaign_id=ai_campaign_id,
        session_id=session_id,
        ai_session_id=ai_session_id,
        inactive_session_id=inactive_session_id,
        adv_1_id=adv_1_id,
        adv_2_unattached_id=adv_2_unattached_id,
        adv_other_room_id=adv_other_room_id,
        npc_entry_id=npc_entry_id,
        scene_entry_id=scene_entry_id,
        unattached_entry_id=unattached_entry_id,
        other_room_entry_id=other_room_entry_id,
        owner_context=owner_context,
        dm_context=dm_context,
        member_context=member_context,
        human_dm_actor=human_dm_actor,
        human_player_actor=human_player_actor,
        ai_dm_actor=ai_dm_actor,
        ai_player_actor=ai_player_actor,
    )


def test_neutral_source_npc_plus_hostile_override_preserves_source(fix: OverrideFixture) -> None:
    # 1. Check initial overlay: no override, neutral
    initial_overlay = fix.service.get_adventure_entry_overlay_management(
        fix.owner_context, fix.room_id, fix.campaign_id, fix.npc_entry_id
    )
    assert initial_overlay.override is None
    assert getattr(initial_overlay.data, "disposition", None) == "neutral"

    # 2. Create hostile override
    override = fix.service.create_override_management(
        fix.owner_context,
        fix.room_id,
        fix.campaign_id,
        CampaignAdventureOverrideCreate(
            adventure_entry_id=fix.npc_entry_id,
            state={"disposition": "hostile"},
            note="Turned hostile after goblin raid.",
            needs_review=True,
        ),
        idempotency_key="create-hostile-ovr-1",
    )
    assert override.revision == 1
    assert override.needs_review is True

    # 3. Verify source entry in adventure_entries table is UNCHANGED (still neutral)
    with fix.engine.connect() as conn:
        row = conn.execute(
            select(adventure_entries.c.data_json).where(adventure_entries.c.id == fix.npc_entry_id)
        ).scalar_one()
        assert row["disposition"] == "neutral"

    # 4. Verify overlay view in campaign: overlay data is hostile!
    overlay = fix.service.get_adventure_entry_overlay_management(
        fix.owner_context, fix.room_id, fix.campaign_id, fix.npc_entry_id
    )
    assert overlay.override is not None
    assert overlay.override.id == override.id
    assert overlay.override.state_json == {"disposition": "hostile"}
    assert overlay.override.needs_review is True
    assert getattr(overlay.data, "disposition", None) == "hostile"
    assert getattr(overlay.data, "role", None) == "patron"


def test_override_management_crud_lifecycle(fix: OverrideFixture) -> None:
    # Create
    created = fix.service.create_override_management(
        fix.dm_context,
        fix.room_id,
        fix.campaign_id,
        CampaignAdventureOverrideCreate(
            adventure_entry_id=fix.npc_entry_id,
            state={"disposition": "friendly"},
            note="Saved by party",
            needs_review=False,
        ),
        idempotency_key="mgmt-crud-1",
    )
    assert created.revision == 1
    assert created.state_json == {"disposition": "friendly"}

    # Get
    fetched = fix.service.get_override_management(
        fix.dm_context, fix.room_id, fix.campaign_id, fix.npc_entry_id
    )
    assert fetched == created

    # List
    listed = fix.service.list_overrides_management(fix.dm_context, fix.room_id, fix.campaign_id)
    assert len(listed) == 1
    assert listed[0] == created

    # List overlays
    overlays = fix.service.list_adventure_entry_overlays_management(
        fix.dm_context, fix.room_id, fix.campaign_id, fix.adv_1_id
    )
    assert len(overlays) == 2
    npc_ov = next(o for o in overlays if o.id == fix.npc_entry_id)
    assert npc_ov.override is not None
    assert npc_ov.override.revision == 1
    scene_ov = next(o for o in overlays if o.id == fix.scene_entry_id)
    assert scene_ov.override is None

    # Update
    updated = fix.service.update_override_management(
        fix.dm_context,
        fix.room_id,
        fix.campaign_id,
        fix.npc_entry_id,
        CampaignAdventureOverridePatch(
            expected_override_id=created.id,
            expected_revision=1,
            state={"disposition": "hostile"},
            note="Betrayed by party",
            needs_review=True,
        ),
        idempotency_key="mgmt-crud-2",
    )
    assert updated.revision == 2
    assert updated.state_json == {"disposition": "hostile"}
    assert updated.needs_review is True

    # Clear
    cleared = fix.service.clear_override_management(
        fix.dm_context,
        fix.room_id,
        fix.campaign_id,
        fix.npc_entry_id,
        expected_override_id=created.id,
        expected_revision=2,
        idempotency_key="mgmt-crud-3",
    )
    assert cleared.id == created.id

    # Verify gone
    with pytest.raises(CampaignRuntimeNotFoundError):
        fix.service.get_override_management(
            fix.dm_context, fix.room_id, fix.campaign_id, fix.npc_entry_id
        )

    listed_after = fix.service.list_overrides_management(
        fix.dm_context, fix.room_id, fix.campaign_id
    )
    assert len(listed_after) == 0


def test_override_active_crud_lifecycle_and_events(fix: OverrideFixture) -> None:
    # 1. Create active
    created = fix.service.create_override_active(
        fix.human_dm_actor,
        CampaignAdventureOverrideCreate(
            adventure_entry_id=fix.npc_entry_id,
            state={"disposition": "hostile"},
            note="Ambushed!",
        ),
        idempotency_key="act-crud-1",
    )
    assert created.revision == 1
    assert fix.session_id in fix.notifier.notifications

    # Verify event secrecy and payload
    with fix.engine.connect() as conn:
        ev = conn.execute(
            select(session_events).where(session_events.c.kind == "world.override.created")
        ).mappings().one()
        assert ev["visibility"] == "dm_only"
        assert ev["recipient_seat_ids"] == []
        assert ev["payload"] == {
            "override_id": str(created.id),
            "adventure_entry_id": str(fix.npc_entry_id),
            "revision": 1,
            "action": "created",
        }

    # 2. Get active & list active
    got = fix.service.get_override_active(fix.human_dm_actor, fix.npc_entry_id)
    assert got == created
    listed = fix.service.list_overrides_active(fix.human_dm_actor)
    assert len(listed) == 1

    # Overlay active
    overlay = fix.service.get_adventure_entry_overlay_active(fix.human_dm_actor, fix.npc_entry_id)
    assert overlay.override is not None
    assert getattr(overlay.data, "disposition", None) == "hostile"

    # 3. Update active
    updated = fix.service.update_override_active(
        fix.human_dm_actor,
        fix.npc_entry_id,
        CampaignAdventureOverridePatch(
            expected_override_id=created.id,
            expected_revision=1,
            state={"disposition": "friendly"},
            note="Pacified",
        ),
        idempotency_key="act-crud-2",
    )
    assert updated.revision == 2

    with fix.engine.connect() as conn:
        ev_up = conn.execute(
            select(session_events).where(session_events.c.kind == "world.override.updated")
        ).mappings().one()
        assert ev_up["visibility"] == "dm_only"
        assert ev_up["payload"] == {
            "override_id": str(created.id),
            "adventure_entry_id": str(fix.npc_entry_id),
            "revision": 2,
            "action": "updated",
        }

    # 4. Clear active
    cleared = fix.service.clear_override_active(
        fix.human_dm_actor,
        fix.npc_entry_id,
        expected_override_id=created.id,
        expected_revision=2,
        idempotency_key="act-crud-3",
    )
    assert cleared.id == created.id

    with fix.engine.connect() as conn:
        ev_cl = conn.execute(
            select(session_events).where(session_events.c.kind == "world.override.cleared")
        ).mappings().one()
        assert ev_cl["visibility"] == "dm_only"
        assert ev_cl["payload"] == {
            "override_id": str(created.id),
            "adventure_entry_id": str(fix.npc_entry_id),
            "revision": 2,
            "action": "cleared",
        }


def test_ai_dm_active_crud_success(fix: OverrideFixture) -> None:
    created = fix.service.create_override_active(
        fix.ai_dm_actor,
        CampaignAdventureOverrideCreate(
            adventure_entry_id=fix.npc_entry_id,
            state={"disposition": "friendly"},
            note="AI DM noted friendship",
        ),
        idempotency_key="ai-dm-crud-1",
    )
    assert created.revision == 1

    got = fix.service.get_override_active(fix.ai_dm_actor, fix.npc_entry_id)
    assert got == created

    overlay = fix.service.get_adventure_entry_overlay_active(fix.ai_dm_actor, fix.npc_entry_id)
    assert overlay.override is not None
    assert getattr(overlay.data, "disposition", None) == "friendly"


def test_player_and_ai_player_rejection(fix: OverrideFixture) -> None:
    # 1. Human Player write rejection
    with pytest.raises(CampaignRuntimeAuthorityError):
        fix.service.create_override_active(
            fix.human_player_actor,
            CampaignAdventureOverrideCreate(
                adventure_entry_id=fix.npc_entry_id,
                state={"disposition": "hostile"},
            ),
            idempotency_key="p-write-1",
        )

    # 2. AI Player write rejection
    with pytest.raises(CampaignRuntimeAuthorityError):
        fix.service.create_override_active(
            fix.ai_player_actor,
            CampaignAdventureOverrideCreate(
                adventure_entry_id=fix.npc_entry_id,
                state={"disposition": "hostile"},
            ),
            idempotency_key="aip-write-1",
        )

    # 3. Human Player read rejection (even on public source entry!)
    with pytest.raises(CampaignRuntimeAuthorityError):
        fix.service.get_override_active(fix.human_player_actor, fix.npc_entry_id)

    with pytest.raises(CampaignRuntimeAuthorityError):
        fix.service.list_overrides_active(fix.human_player_actor)

    with pytest.raises(CampaignRuntimeAuthorityError):
        fix.service.get_adventure_entry_overlay_active(fix.human_player_actor, fix.npc_entry_id)

    with pytest.raises(CampaignRuntimeAuthorityError):
        fix.service.list_adventure_entry_overlays_active(fix.human_player_actor, fix.adv_1_id)

    # 4. AI Player read rejection
    with pytest.raises(CampaignRuntimeAuthorityError):
        fix.service.get_override_active(fix.ai_player_actor, fix.npc_entry_id)

    with pytest.raises(CampaignRuntimeAuthorityError):
        fix.service.list_overrides_active(fix.ai_player_actor)

    with pytest.raises(CampaignRuntimeAuthorityError):
        fix.service.get_adventure_entry_overlay_active(fix.ai_player_actor, fix.npc_entry_id)

    with pytest.raises(CampaignRuntimeAuthorityError):
        fix.service.list_adventure_entry_overlays_active(fix.ai_player_actor, fix.adv_1_id)

    # 5. Management member rejection
    with pytest.raises(CampaignRuntimeAuthorityError):
        fix.service.create_override_management(
            fix.member_context,
            fix.room_id,
            fix.campaign_id,
            CampaignAdventureOverrideCreate(adventure_entry_id=fix.npc_entry_id),
            idempotency_key="mem-write-1",
        )

    with pytest.raises(CampaignRuntimeAuthorityError):
        fix.service.get_override_management(
            fix.member_context, fix.room_id, fix.campaign_id, fix.npc_entry_id
        )

    with pytest.raises(CampaignRuntimeAuthorityError):
        fix.service.get_adventure_entry_overlay_management(
            fix.member_context, fix.room_id, fix.campaign_id, fix.npc_entry_id
        )


def test_active_vs_management_authority(fix: OverrideFixture) -> None:
    # 1. Management write rejected when campaign has active session
    with pytest.raises(CampaignRuntimeActiveSessionError):
        fix.service.create_override_management(
            fix.dm_context,
            fix.room_id,
            fix.campaign_active_id,
            CampaignAdventureOverrideCreate(
                adventure_entry_id=fix.npc_entry_id,
                state={"disposition": "hostile"},
            ),
            idempotency_key="mgmt-active-rej-1",
        )

    # 2. Active write rejected when session is not active (ended)
    inactive_actor = fix.human_dm_actor.model_copy(
        update={"session_id": fix.inactive_session_id}
    )
    with pytest.raises(CampaignRuntimeSessionNotActiveError):
        fix.service.create_override_active(
            inactive_actor,
            CampaignAdventureOverrideCreate(
                adventure_entry_id=fix.npc_entry_id,
                state={"disposition": "hostile"},
            ),
            idempotency_key="act-inactive-rej-1",
        )


def test_stale_revision_conflict(fix: OverrideFixture) -> None:
    created = fix.service.create_override_management(
        fix.dm_context,
        fix.room_id,
        fix.campaign_id,
        CampaignAdventureOverrideCreate(
            adventure_entry_id=fix.npc_entry_id,
            state={"disposition": "friendly"},
        ),
        idempotency_key="stale-rev-1",
    )
    assert created.revision == 1

    # Update with wrong expected revision (e.g. 2 instead of 1)
    with pytest.raises(CampaignRuntimeRevisionConflictError):
        fix.service.update_override_management(
            fix.dm_context,
            fix.room_id,
            fix.campaign_id,
            fix.npc_entry_id,
            CampaignAdventureOverridePatch(
                expected_override_id=created.id,
                expected_revision=2,
                state={"disposition": "hostile"},
            ),
            idempotency_key="stale-rev-2",
        )

    # Clear with wrong expected revision
    with pytest.raises(CampaignRuntimeRevisionConflictError):
        fix.service.clear_override_management(
            fix.dm_context,
            fix.room_id,
            fix.campaign_id,
            fix.npc_entry_id,
            expected_override_id=created.id,
            expected_revision=2,
            idempotency_key="stale-rev-3",
        )


def test_already_exists_rejection(fix: OverrideFixture) -> None:
    fix.service.create_override_management(
        fix.dm_context,
        fix.room_id,
        fix.campaign_id,
        CampaignAdventureOverrideCreate(
            adventure_entry_id=fix.npc_entry_id,
            state={"disposition": "friendly"},
        ),
        idempotency_key="already-exists-1",
    )

    with pytest.raises(CampaignAdventureOverrideAlreadyExistsError):
        fix.service.create_override_management(
            fix.dm_context,
            fix.room_id,
            fix.campaign_id,
            CampaignAdventureOverrideCreate(
                adventure_entry_id=fix.npc_entry_id,
                state={"disposition": "hostile"},
            ),
            idempotency_key="already-exists-2",
        )


def test_wrong_room_campaign_and_unattached_targets(fix: OverrideFixture) -> None:
    # 1. Target entry in different room
    with pytest.raises(CampaignRuntimeNotFoundError):
        fix.service.create_override_management(
            fix.dm_context,
            fix.room_id,
            fix.campaign_id,
            CampaignAdventureOverrideCreate(
                adventure_entry_id=fix.other_room_entry_id,
                state={"disposition": "hostile"},
            ),
            idempotency_key="wrong-room-1",
        )

    # 2. Target entry unattached to campaign
    with pytest.raises(CampaignRuntimeValidationError):
        fix.service.create_override_management(
            fix.dm_context,
            fix.room_id,
            fix.campaign_id,
            CampaignAdventureOverrideCreate(
                adventure_entry_id=fix.unattached_entry_id,
                state={"disposition": "hostile"},
            ),
            idempotency_key="unattached-1",
        )

    # 3. Overlay view on unattached entry
    with pytest.raises(CampaignRuntimeValidationError):
        fix.service.get_adventure_entry_overlay_management(
            fix.dm_context, fix.room_id, fix.campaign_id, fix.unattached_entry_id
        )

    # 4. List overlays on unattached adventure
    with pytest.raises(CampaignRuntimeValidationError):
        fix.service.list_adventure_entry_overlays_management(
            fix.dm_context, fix.room_id, fix.campaign_id, fix.adv_2_unattached_id
        )


def test_idempotency_retries(fix: OverrideFixture) -> None:
    payload = CampaignAdventureOverrideCreate(
        adventure_entry_id=fix.npc_entry_id,
        state={"disposition": "hostile"},
        note="Initial note",
    )
    first = fix.service.create_override_management(
        fix.dm_context,
        fix.room_id,
        fix.campaign_id,
        payload,
        idempotency_key="idem-key-1",
    )

    # Exact retry returns same result
    retry = fix.service.create_override_management(
        fix.dm_context,
        fix.room_id,
        fix.campaign_id,
        payload,
        idempotency_key="idem-key-1",
    )
    assert retry == first

    # Mismatched command payload raises CampaignRuntimeIdempotencyConflictError
    diff_payload = CampaignAdventureOverrideCreate(
        adventure_entry_id=fix.npc_entry_id,
        state={"disposition": "friendly"},
        note="Different note",
    )
    with pytest.raises(CampaignRuntimeIdempotencyConflictError):
        fix.service.create_override_management(
            fix.dm_context,
            fix.room_id,
            fix.campaign_id,
            diff_payload,
            idempotency_key="idem-key-1",
        )

    # Active exact retry returns stored result without duplicate event
    created_act = fix.service.create_override_active(
        fix.human_dm_actor,
        CampaignAdventureOverrideCreate(
            adventure_entry_id=fix.npc_entry_id,
            state={"disposition": "hostile"},
            note="Initial active note",
        ),
        idempotency_key="idem-act-create-1",
    )

    act_payload = CampaignAdventureOverridePatch(
        expected_override_id=created_act.id,
        expected_revision=1,
        state={"disposition": "friendly"},
    )
    first_act = fix.service.update_override_active(
        fix.human_dm_actor,
        fix.npc_entry_id,
        act_payload,
        idempotency_key="idem-act-key-1",
    )
    assert first_act.revision == 2

    retry_act = fix.service.update_override_active(
        fix.human_dm_actor,
        fix.npc_entry_id,
        act_payload,
        idempotency_key="idem-act-key-1",
    )
    assert retry_act == first_act

    with fix.engine.connect() as conn:
        events = conn.execute(
            select(session_events).where(session_events.c.kind == "world.override.updated")
        ).all()
        assert len(events) == 1  # No duplicate event!


def test_rollback_on_failure_leaves_clean_state(fix: OverrideFixture) -> None:
    # Attempt override with invalid state payload for npc kind
    with pytest.raises(CampaignRuntimeValidationError):
        fix.service.create_override_management(
            fix.dm_context,
            fix.room_id,
            fix.campaign_id,
            CampaignAdventureOverrideCreate(
                adventure_entry_id=fix.npc_entry_id,
                state={"disposition": "invalid-disposition-value"},
            ),
            idempotency_key="fail-key-1",
        )

    # Verify no override row was created
    with fix.engine.connect() as conn:
        overrides = conn.execute(select(campaign_adventure_overrides)).all()
        assert len(overrides) == 0

        # Verify no mutation row was created
        mutations = conn.execute(select(campaign_world_mutations)).all()
        assert len(mutations) == 0


def test_detach_blocker_matrix(fix: OverrideFixture) -> None:
    # 1. Detach unblocked adventure (adv_1 from campaign_id has no overrides or scene context)
    fix.adv_service.detach(fix.owner_context, fix.room_id, fix.campaign_id, fix.adv_1_id)
    with fix.engine.connect() as conn:
        link = conn.execute(
            select(campaign_adventure_links).where(
                campaign_adventure_links.c.campaign_id == fix.campaign_id,
                campaign_adventure_links.c.adventure_id == fix.adv_1_id,
            )
        ).one_or_none()
        assert link is None

    # Re-attach for subsequent tests
    fix.adv_service.attach(
        fix.owner_context,
        fix.room_id,
        fix.campaign_id,
        CampaignAdventureAttach(adventure_id=fix.adv_1_id),
    )

    # 2. Active override blocks detach
    created_ovr = fix.service.create_override_management(
        fix.dm_context,
        fix.room_id,
        fix.campaign_id,
        CampaignAdventureOverrideCreate(
            adventure_entry_id=fix.npc_entry_id,
            state={"disposition": "hostile"},
        ),
        idempotency_key="detach-ovr-1",
    )

    with pytest.raises(CampaignAdventureDetachBlockedError) as exc_info:
        fix.adv_service.detach(fix.owner_context, fix.room_id, fix.campaign_id, fix.adv_1_id)
    assert exc_info.value.reason == "active overrides exist for this adventure"

    # Clear override -> detach permitted!
    fix.service.clear_override_management(
        fix.dm_context,
        fix.room_id,
        fix.campaign_id,
        fix.npc_entry_id,
        expected_override_id=created_ovr.id,
        expected_revision=1,
        idempotency_key="detach-ovr-clear-1",
    )

    # 3. current_adventure_scene_entry_id in campaign_runtime_context blocks detach
    with fix.engine.begin() as conn:
        conn.execute(
            insert(campaign_runtime_context).values(
                campaign_id=fix.campaign_id,
                current_adventure_scene_entry_id=fix.scene_entry_id,
                current_runtime_scene_entry_id=None,
                current_situation="In the hideout",
                revision=1,
                updated_at=datetime.now(timezone.utc),
            )
        )

    with pytest.raises(CampaignAdventureDetachBlockedError) as exc_info2:
        fix.adv_service.detach(fix.owner_context, fix.room_id, fix.campaign_id, fix.adv_1_id)
    assert exc_info2.value.reason == "current adventure scene points to this adventure"

    # Clear current adventure scene
    with fix.engine.begin() as conn:
        conn.execute(
            campaign_runtime_context.update()
            .where(campaign_runtime_context.c.campaign_id == fix.campaign_id)
            .values(current_adventure_scene_entry_id=None)
        )

    # 4. Provenance reference in campaign_world_entries does NOT block detach
    with fix.engine.begin() as conn:
        conn.execute(
            insert(campaign_world_entries).values(
                id=uuid4(),
                campaign_id=fix.campaign_id,
                kind="npc",
                title="Derived Gundren",
                body="He was cloned",
                state_json={},
                dm_notes=None,
                visibility="public",
                needs_review=False,
                source_adventure_entry_id=fix.npc_entry_id,  # Provenance reference!
                provenance_json={"origin": "Lost Mine"},
                revision=1,
                created_by_actor_kind="human",
                created_by_actor_id=fix.dm_context.access_session_id,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                archived_at=None,
            )
        )

    # Detach must succeed despite provenance reference!
    fix.adv_service.detach(fix.owner_context, fix.room_id, fix.campaign_id, fix.adv_1_id)

    # And provenance reference remains in table intact
    with fix.engine.connect() as conn:
        prov_entry = conn.execute(
            select(campaign_world_entries).where(
                campaign_world_entries.c.source_adventure_entry_id == fix.npc_entry_id
            )
        ).mappings().one()
        assert prov_entry["source_adventure_entry_id"] == fix.npc_entry_id


def test_sequential_detach_vs_override_race_prevention(fix: OverrideFixture) -> None:
    # Verify that detach and override creation serialize on campaign lock
    # When detach completes first, override creation fails
    fix.adv_service.detach(fix.owner_context, fix.room_id, fix.campaign_id, fix.adv_1_id)

    with pytest.raises(CampaignRuntimeValidationError):
        fix.service.create_override_management(
            fix.dm_context,
            fix.room_id,
            fix.campaign_id,
            CampaignAdventureOverrideCreate(
                adventure_entry_id=fix.npc_entry_id,
                state={"disposition": "hostile"},
            ),
            idempotency_key="race-test-1",
        )


def test_aba_recreation_prevention(fix: OverrideFixture) -> None:
    # 1. Create override O1 (revision 1)
    o1 = fix.service.create_override_management(
        fix.dm_context,
        fix.room_id,
        fix.campaign_id,
        CampaignAdventureOverrideCreate(
            adventure_entry_id=fix.npc_entry_id,
            state={"disposition": "hostile"},
            note="Original override",
        ),
        idempotency_key="aba-create-1",
    )
    assert o1.revision == 1

    # 2. Clear override O1 with correct expected_override_id and revision
    cleared = fix.service.clear_override_management(
        fix.dm_context,
        fix.room_id,
        fix.campaign_id,
        fix.npc_entry_id,
        expected_override_id=o1.id,
        expected_revision=1,
        idempotency_key="aba-clear-1",
    )
    assert cleared.id == o1.id

    # 3. Attempt update on cleared override: raises CampaignRuntimeNotFoundError (zero side effects)
    with pytest.raises(CampaignRuntimeNotFoundError):
        fix.service.update_override_management(
            fix.dm_context,
            fix.room_id,
            fix.campaign_id,
            fix.npc_entry_id,
            CampaignAdventureOverridePatch(
                expected_override_id=o1.id,
                expected_revision=1,
                state={"disposition": "friendly"},
            ),
            idempotency_key="aba-stale-update-1",
        )

    # 4. Attempt clear on already cleared override: raises CampaignRuntimeNotFoundError
    with pytest.raises(CampaignRuntimeNotFoundError):
        fix.service.clear_override_management(
            fix.dm_context,
            fix.room_id,
            fix.campaign_id,
            fix.npc_entry_id,
            expected_override_id=o1.id,
            expected_revision=1,
            idempotency_key="aba-stale-clear-1",
        )

    # 5. Recreate override O2 on the same entry (revision 1, new UUID)
    o2 = fix.service.create_override_management(
        fix.dm_context,
        fix.room_id,
        fix.campaign_id,
        CampaignAdventureOverrideCreate(
            adventure_entry_id=fix.npc_entry_id,
            state={"disposition": "friendly"},
            note="Recreated override",
        ),
        idempotency_key="aba-create-2",
    )
    assert o2.id != o1.id
    assert o2.revision == 1

    # 6. Old client with stale expected_override_id=O1.id tries to update:
    # Must fail with revision conflict (identity mismatch), NOT overwrite O2!
    with pytest.raises(CampaignRuntimeRevisionConflictError):
        fix.service.update_override_management(
            fix.dm_context,
            fix.room_id,
            fix.campaign_id,
            fix.npc_entry_id,
            CampaignAdventureOverridePatch(
                expected_override_id=o1.id,
                expected_revision=1,
                state={"disposition": "hostile"},
            ),
            idempotency_key="aba-stale-update-2",
        )

    # 7. Old client with stale expected_override_id=O1.id tries to clear:
    # Must fail with revision conflict (identity mismatch), NOT delete O2!
    with pytest.raises(CampaignRuntimeRevisionConflictError):
        fix.service.clear_override_management(
            fix.dm_context,
            fix.room_id,
            fix.campaign_id,
            fix.npc_entry_id,
            expected_override_id=o1.id,
            expected_revision=1,
            idempotency_key="aba-stale-clear-2",
        )

    # 8. Verify O2 in DB is untouched (state is still friendly, revision 1, id is o2.id)
    current_o2 = fix.service.get_override_management(
        fix.dm_context, fix.room_id, fix.campaign_id, fix.npc_entry_id
    )
    assert current_o2.id == o2.id
    assert current_o2.revision == 1
    assert current_o2.state_json == {"disposition": "friendly"}

    # 9. Valid client using correct expected_override_id=o2.id succeeds
    up2 = fix.service.update_override_management(
        fix.dm_context,
        fix.room_id,
        fix.campaign_id,
        fix.npc_entry_id,
        CampaignAdventureOverridePatch(
            expected_override_id=o2.id,
            expected_revision=1,
            state={"disposition": "neutral"},
        ),
        idempotency_key="aba-valid-update-1",
    )
    assert up2.revision == 2
    assert up2.state_json == {"disposition": "neutral"}


def test_mismatched_entry_kind_rejected(fix: OverrideFixture) -> None:
    # fix.npc_entry_id is an NPC entry.
    # Attempting to set state with kind='scene' must be rejected (not silently overwritten)
    with pytest.raises(CampaignRuntimeValidationError):
        fix.service.create_override_management(
            fix.dm_context,
            fix.room_id,
            fix.campaign_id,
            CampaignAdventureOverrideCreate(
                adventure_entry_id=fix.npc_entry_id,
                state={"kind": "scene", "read_aloud": "A cave."},
            ),
            idempotency_key="kind-mismatch-1",
        )

    # Active create rejection
    with pytest.raises(CampaignRuntimeValidationError):
        fix.service.create_override_active(
            fix.human_dm_actor,
            CampaignAdventureOverrideCreate(
                adventure_entry_id=fix.npc_entry_id,
                state={"kind": "scene", "read_aloud": "A cave."},
            ),
            idempotency_key="kind-mismatch-act-1",
        )

    # Create valid override
    created = fix.service.create_override_management(
        fix.dm_context,
        fix.room_id,
        fix.campaign_id,
        CampaignAdventureOverrideCreate(
            adventure_entry_id=fix.npc_entry_id,
            state={"disposition": "hostile"},
        ),
        idempotency_key="kind-valid-1",
    )

    # Attempting update with kind mismatch is rejected
    with pytest.raises(CampaignRuntimeValidationError):
        fix.service.update_override_management(
            fix.dm_context,
            fix.room_id,
            fix.campaign_id,
            fix.npc_entry_id,
            CampaignAdventureOverridePatch(
                expected_override_id=created.id,
                expected_revision=1,
                state={"kind": "scene"},
            ),
            idempotency_key="kind-mismatch-up-1",
        )

    # Active update kind rejection against an override created via create_override_active
    created_active = fix.service.create_override_active(
        fix.human_dm_actor,
        CampaignAdventureOverrideCreate(
            adventure_entry_id=fix.npc_entry_id,
            state={"disposition": "hostile"},
        ),
        idempotency_key="kind-valid-act-1",
    )

    with pytest.raises(CampaignRuntimeValidationError):
        fix.service.update_override_active(
            fix.human_dm_actor,
            fix.npc_entry_id,
            CampaignAdventureOverridePatch(
                expected_override_id=created_active.id,
                expected_revision=1,
                state={"kind": "scene"},
            ),
            idempotency_key="kind-mismatch-act-up-1",
        )


def test_stale_or_revoked_actor_binding(fix: OverrideFixture) -> None:
    now = datetime.now(timezone.utc)

    # 1. Human actor revocation
    with fix.engine.begin() as conn:
        conn.execute(
            update(room_access_sessions)
            .where(room_access_sessions.c.id == fix.dm_context.access_session_id)
            .values(revoked_at=now)
        )

    # Write path
    with pytest.raises(CampaignRuntimeAuthorityError):
        fix.service.create_override_active(
            fix.human_dm_actor,
            CampaignAdventureOverrideCreate(
                adventure_entry_id=fix.npc_entry_id,
                state={"disposition": "hostile"},
            ),
            idempotency_key="revoked-human-create",
        )

    # Read paths
    with pytest.raises(CampaignRuntimeAuthorityError):
        fix.service.get_override_active(fix.human_dm_actor, fix.npc_entry_id)

    with pytest.raises(CampaignRuntimeAuthorityError):
        fix.service.list_overrides_active(fix.human_dm_actor)

    with pytest.raises(CampaignRuntimeAuthorityError):
        fix.service.get_adventure_entry_overlay_active(fix.human_dm_actor, fix.npc_entry_id)

    with pytest.raises(CampaignRuntimeAuthorityError):
        fix.service.list_adventure_entry_overlays_active(fix.human_dm_actor, fix.adv_1_id)

    # Replay path
    with pytest.raises(CampaignRuntimeAuthorityError):
        fix.service.create_override_active(
            fix.human_dm_actor,
            CampaignAdventureOverrideCreate(
                adventure_entry_id=fix.npc_entry_id,
                state={"disposition": "hostile"},
            ),
            idempotency_key="revoked-human-create",
        )

    # 2. AI actor revocation
    with fix.engine.begin() as conn:
        conn.execute(
            update(ai_controller_grants)
            .where(ai_controller_grants.c.id == fix.ai_dm_actor.ai_controller_grant_id)
            .values(revoked_at=now, status="revoked")
        )

    with pytest.raises(CampaignRuntimeAuthorityError):
        fix.service.create_override_active(
            fix.ai_dm_actor,
            CampaignAdventureOverrideCreate(
                adventure_entry_id=fix.npc_entry_id,
                state={"disposition": "friendly"},
            ),
            idempotency_key="revoked-ai-create",
        )

    with pytest.raises(CampaignRuntimeAuthorityError):
        fix.service.get_override_active(fix.ai_dm_actor, fix.npc_entry_id)

    with pytest.raises(CampaignRuntimeAuthorityError):
        fix.service.list_overrides_active(fix.ai_dm_actor)

    with pytest.raises(CampaignRuntimeAuthorityError):
        fix.service.get_adventure_entry_overlay_active(fix.ai_dm_actor, fix.npc_entry_id)

    with pytest.raises(CampaignRuntimeAuthorityError):
        fix.service.list_adventure_entry_overlays_active(fix.ai_dm_actor, fix.adv_1_id)


def test_inactive_session_and_nonparticipant_and_wrong_scope(fix: OverrideFixture) -> None:
    # 1. Inactive session
    inactive_actor = fix.human_dm_actor.model_copy(
        update={"session_id": fix.inactive_session_id}
    )
    with pytest.raises(CampaignRuntimeSessionNotActiveError):
        fix.service.create_override_active(
            inactive_actor,
            CampaignAdventureOverrideCreate(
                adventure_entry_id=fix.npc_entry_id,
                state={"disposition": "hostile"},
            ),
            idempotency_key="act-inactive-1",
        )

    with pytest.raises(CampaignRuntimeSessionNotActiveError):
        fix.service.get_override_active(inactive_actor, fix.npc_entry_id)

    # 2. Nonparticipant actor (seat_id not participating)
    nonparticipant_actor = fix.human_dm_actor.model_copy(
        update={"seat_id": uuid4()}
    )
    with pytest.raises(CampaignRuntimeAuthorityError):
        fix.service.create_override_active(
            nonparticipant_actor,
            CampaignAdventureOverrideCreate(
                adventure_entry_id=fix.npc_entry_id,
                state={"disposition": "hostile"},
            ),
            idempotency_key="act-nonpart-1",
        )

    # 3. Wrong scope (wrong room or campaign)
    wrong_scope_actor = fix.human_dm_actor.model_copy(
        update={"room_id": fix.other_room_id}
    )
    with pytest.raises(CampaignRuntimeNotFoundError):
        fix.service.create_override_active(
            wrong_scope_actor,
            CampaignAdventureOverrideCreate(
                adventure_entry_id=fix.npc_entry_id,
                state={"disposition": "hostile"},
            ),
            idempotency_key="act-wrong-scope-1",
        )


def test_idempotency_collisions_and_cross_session_replay(fix: OverrideFixture) -> None:
    # Create initial active override
    key = "collision-test-key-1"
    created = fix.service.create_override_active(
        fix.human_dm_actor,
        CampaignAdventureOverrideCreate(
            adventure_entry_id=fix.npc_entry_id,
            state={"disposition": "hostile"},
            note="Collision test note",
        ),
        idempotency_key=key,
    )
    assert created.revision == 1

    # 1. Collision on different action_kind (update with same key)
    with pytest.raises(CampaignRuntimeIdempotencyConflictError):
        fix.service.update_override_active(
            fix.human_dm_actor,
            fix.npc_entry_id,
            CampaignAdventureOverridePatch(
                expected_override_id=created.id,
                expected_revision=1,
                state={"disposition": "friendly"},
            ),
            idempotency_key=key,
        )

    # 2. Collision on different target_id (different entry)
    with pytest.raises(CampaignRuntimeIdempotencyConflictError):
        fix.service.create_override_active(
            fix.human_dm_actor,
            CampaignAdventureOverrideCreate(
                adventure_entry_id=fix.scene_entry_id,
                state={"read_aloud": "New scene"},
            ),
            idempotency_key=key,
        )

    # 3. Collision on different actor (within valid authority mode on inactive campaign)
    mgmt_actor_key = "collision-diff-actor-1"
    fix.service.create_override_management(
        fix.dm_context,
        fix.room_id,
        fix.campaign_id,
        CampaignAdventureOverrideCreate(
            adventure_entry_id=fix.npc_entry_id,
            state={"disposition": "hostile"},
            note="Management actor collision test",
        ),
        idempotency_key=mgmt_actor_key,
    )
    with pytest.raises(CampaignRuntimeIdempotencyConflictError):
        fix.service.create_override_management(
            fix.owner_context,
            fix.room_id,
            fix.campaign_id,
            CampaignAdventureOverrideCreate(
                adventure_entry_id=fix.npc_entry_id,
                state={"disposition": "hostile"},
                note="Management actor collision test",
            ),
            idempotency_key=mgmt_actor_key,
        )

    # 4. Cross-session replay:
    # In a second active session for the same campaign, replay the same key and payload.
    # It must return the cached result and NOT append duplicate events to session 2.
    now = datetime.now(timezone.utc)
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

    sess_2_actor = fix.human_dm_actor.model_copy(update={"session_id": sess_2_id})
    replayed = fix.service.create_override_active(
        sess_2_actor,
        CampaignAdventureOverrideCreate(
            adventure_entry_id=fix.npc_entry_id,
            state={"disposition": "hostile"},
            note="Collision test note",
        ),
        idempotency_key=key,
    )
    assert replayed.id == created.id

    # Verify no events were created in sess_2_id
    with fix.engine.connect() as conn:
        sess_2_events = conn.execute(
            select(session_events).where(session_events.c.session_id == sess_2_id)
        ).all()
        assert len(sess_2_events) == 0


def test_real_post_write_rollback(fix: OverrideFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    real_insert = fix.service.mutation_repo.insert_in_transaction

    def failing_insert(conn, mutation):
        real_insert(conn, mutation)
        raise RuntimeError("Simulated crash after real write")

    monkeypatch.setattr(fix.service.mutation_repo, "insert_in_transaction", failing_insert)

    with pytest.raises(RuntimeError, match="Simulated crash after real write"):
        fix.service.create_override_active(
            fix.human_dm_actor,
            CampaignAdventureOverrideCreate(
                adventure_entry_id=fix.npc_entry_id,
                state={"disposition": "hostile"},
            ),
            idempotency_key="fail-postwrite-1",
        )

    # Verify override row was rolled back
    with fix.engine.connect() as conn:
        overrides = conn.execute(select(campaign_adventure_overrides)).all()
        assert len(overrides) == 0

        # Verify mutation was rolled back
        mutations = conn.execute(select(campaign_world_mutations)).all()
        assert len(mutations) == 0

        # Verify session event was rolled back
        events = conn.execute(select(session_events)).all()
        assert len(events) == 0

        # Verify cursor in session_table_runtime is unchanged
        cursor_row = conn.execute(
            select(session_table_runtime.c.last_event_seq).where(
                session_table_runtime.c.session_id == fix.session_id
            )
        ).scalar_one_or_none()
        assert cursor_row in (None, 0)

    # Verify notifier was NOT notified
    assert fix.session_id not in fix.notifier.notifications


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
def test_postgres_concurrent_detach_vs_override() -> None:
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
        entry_id = uuid4()
        owner_access_id = uuid4()
        dm_access_id = uuid4()

        with engine.begin() as conn:
            conn.execute(
                insert(rooms).values(
                    id=room_id,
                    code="PG-DETACH",
                    name="PG Detach Room",
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
                            "token_hash": b"tok_owner_pg_1234567890123",
                            "display_name": "Owner",
                            "created_at": now,
                            "last_seen_at": now,
                        },
                        {
                            "id": dm_access_id,
                            "room_id": room_id,
                            "authority": "dm",
                            "token_hash": b"tok_dm_pg_1234567890123456",
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
                    name="PG Campaign",
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
                    name="PG Adventure",
                    summary="Test Adventure",
                    status="finalized",
                    created_at=now,
                    updated_at=now,
                )
            )
            conn.execute(
                insert(adventure_entries).values(
                    id=entry_id,
                    adventure_id=adv_id,
                    parent_entry_id=None,
                    kind="npc",
                    title="PG NPC",
                    body="A test npc.",
                    data_json={"kind": "npc", "disposition": "neutral"},
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

        # Outcome A: Detach acquires campaign lock first
        barrier_a = Barrier(2)
        detach_a_err: Exception | None = None
        override_a_err: Exception | None = None

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

        def create_override_second() -> None:
            nonlocal override_a_err
            try:
                barrier_a.wait(timeout=10)
                runtime_svc.create_override_management(
                    dm_ctx,
                    room_id,
                    campaign_id,
                    CampaignAdventureOverrideCreate(
                        adventure_entry_id=entry_id,
                        state={"disposition": "hostile"},
                    ),
                    idempotency_key="pg-race-create-1",
                )
            except Exception as e:
                override_a_err = e

        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(detach_first)
            f2 = pool.submit(create_override_second)
            f1.result(timeout=15)
            f2.result(timeout=15)

        assert detach_a_err is None
        assert isinstance(override_a_err, CampaignRuntimeValidationError)

        with engine.connect() as conn:
            link = conn.execute(
                select(campaign_adventure_links).where(
                    campaign_adventure_links.c.campaign_id == campaign_id,
                    campaign_adventure_links.c.adventure_id == adv_id,
                )
            ).one_or_none()
            assert link is None
            ovrs = conn.execute(select(campaign_adventure_overrides)).all()
            assert len(ovrs) == 0

        # Outcome B: Create override acquires campaign lock first
        adv_svc.attach(
            owner_ctx,
            room_id,
            campaign_id,
            CampaignAdventureAttach(adventure_id=adv_id),
        )

        barrier_b = Barrier(2)
        override_b_err: Exception | None = None
        detach_b_err: Exception | None = None

        def create_first() -> None:
            nonlocal override_b_err
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
                        insert(campaign_adventure_overrides).values(
                            id=uuid4(),
                            campaign_id=campaign_id,
                            adventure_entry_id=entry_id,
                            state_json={"disposition": "hostile"},
                            note="Created in PG lock race",
                            needs_review=False,
                            revision=1,
                            created_at=datetime.now(timezone.utc),
                            updated_at=datetime.now(timezone.utc),
                        )
                    )
            except Exception as e:
                override_b_err = e

        def detach_second() -> None:
            nonlocal detach_b_err
            try:
                barrier_b.wait(timeout=10)
                adv_svc.detach(owner_ctx, room_id, campaign_id, adv_id)
            except Exception as e:
                detach_b_err = e

        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(create_first)
            f2 = pool.submit(detach_second)
            f1.result(timeout=15)
            f2.result(timeout=15)

        assert override_b_err is None
        assert isinstance(detach_b_err, CampaignAdventureDetachBlockedError)

        with engine.connect() as conn:
            link = conn.execute(
                select(campaign_adventure_links).where(
                    campaign_adventure_links.c.campaign_id == campaign_id,
                    campaign_adventure_links.c.adventure_id == adv_id,
                )
            ).one_or_none()
            assert link is not None
            ovrs = conn.execute(select(campaign_adventure_overrides)).all()
            assert len(ovrs) == 1
    finally:
        engine.dispose()
