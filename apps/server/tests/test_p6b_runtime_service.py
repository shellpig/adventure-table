from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event, func, insert, select
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from app.db import metadata
from app.domain.campaign_runtime import (
    CampaignRuntimeActiveSessionError,
    CampaignRuntimeArchivedError,
    CampaignRuntimeAuthorityError,
    CampaignRuntimeIdempotencyConflictError,
    CampaignRuntimeNotFoundError,
    CampaignRuntimeRevisionConflictError,
    CampaignRuntimeService,
    CampaignRuntimeValidationError,
    RuntimeEntryValidationError,
    RuntimeEntryVisibilityError,
    RuntimeWorldEntryCreate,
    RuntimeWorldEntryDmView,
    RuntimeWorldEntryPatch,
    RuntimeWorldEntryPlayerView,
    project_runtime_aggregate,
    project_runtime_aggregates,
)
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.table_events import TableEventService
from app.persistence.rooms.table_runtime import TableEventRepository
from app.persistence.adventures.tables import (
    adventure_definitions,
    adventure_entries,
    campaign_adventure_links,
)
from app.persistence.campaign_runtime.tables import (
    campaign_world_entries,
    campaign_world_entry_characters,
    campaign_world_mutations,
)
from app.persistence.characters import characters, character_states, character_versions
from app.persistence.rooms.tables import (
    campaign_seats,
    campaigns,
    room_access_sessions,
    room_characters,
    rooms,
    sessions,
)


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


@dataclass(frozen=True)
class ServiceFixture:
    engine: Engine
    service: CampaignRuntimeService
    room_a_id: UUID
    room_b_id: UUID
    owner_context: RoomAccessContext
    dm_context: RoomAccessContext
    member_context: RoomAccessContext
    campaign_empty_id: UUID
    campaign_attached_id: UUID
    campaign_active_session_id: UUID
    campaign_b_id: UUID
    char_a1_id: UUID
    char_a2_id: UUID
    char_b1_id: UUID
    adv_entry_attached_id: UUID
    adv_entry_unattached_id: UUID


@pytest.fixture
def fix() -> ServiceFixture:
    engine = _engine()
    event_service = TableEventService(TableEventRepository(engine))
    service = CampaignRuntimeService(engine, event_service)
    now = datetime.now(timezone.utc)

    room_a_id = uuid4()
    room_b_id = uuid4()

    owner_session_id = uuid4()
    dm_session_id = uuid4()
    member_session_id = uuid4()

    owner_context = RoomAccessContext(
        room_id=room_a_id,
        access_session_id=owner_session_id,
        authority=RoomAccessAuthority.OWNER,
        display_name="Owner A",
    )
    dm_context = RoomAccessContext(
        room_id=room_a_id,
        access_session_id=dm_session_id,
        authority=RoomAccessAuthority.DM,
        display_name="DM A",
    )
    member_context = RoomAccessContext(
        room_id=room_a_id,
        access_session_id=member_session_id,
        authority=RoomAccessAuthority.MEMBER,
        display_name="Member A",
    )

    campaign_empty_id = uuid4()
    campaign_attached_id = uuid4()
    campaign_active_session_id = uuid4()
    campaign_b_id = uuid4()

    char_a1_id = uuid4()
    char_a2_id = uuid4()
    char_b1_id = uuid4()

    adv_def_1_id = uuid4()
    adv_entry_attached_id = uuid4()
    adv_def_unattached_id = uuid4()
    adv_entry_unattached_id = uuid4()

    dm_seat_id = uuid4()
    active_session_id = uuid4()

    with engine.begin() as conn:
        # Rooms
        conn.execute(
            insert(rooms).values(
                [
                    {
                        "id": room_a_id,
                        "code": "ROOM-A",
                        "name": "Room A",
                        "password_salt": b"salt",
                        "password_hash": b"pw",
                        "owner_key_hash": b"owner",
                        "dm_key_hash": b"dm",
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": room_b_id,
                        "code": "ROOM-B",
                        "name": "Room B",
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
        # Room Access Sessions
        conn.execute(
            insert(room_access_sessions).values(
                [
                    {
                        "id": owner_session_id,
                        "room_id": room_a_id,
                        "authority": "owner",
                        "token_hash": b"owner_tok_hash_bytes_1234567890",
                        "display_name": "Owner A",
                        "created_at": now,
                        "last_seen_at": now,
                    },
                    {
                        "id": dm_session_id,
                        "room_id": room_a_id,
                        "authority": "dm",
                        "token_hash": b"dm_tok_hash_bytes_1234567890123",
                        "display_name": "DM A",
                        "created_at": now,
                        "last_seen_at": now,
                    },
                    {
                        "id": member_session_id,
                        "room_id": room_a_id,
                        "authority": "member",
                        "token_hash": b"mem_tok_hash_bytes_123456789012",
                        "display_name": "Member A",
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
                        "id": campaign_empty_id,
                        "room_id": room_a_id,
                        "name": "Empty Campaign",
                        "ruleset": "dnd-5e-2014",
                        "status": "active",
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": campaign_attached_id,
                        "room_id": room_a_id,
                        "name": "Attached Campaign",
                        "ruleset": "dnd-5e-2014",
                        "status": "active",
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": campaign_active_session_id,
                        "room_id": room_a_id,
                        "name": "Active Session Campaign",
                        "ruleset": "dnd-5e-2014",
                        "status": "active",
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": campaign_b_id,
                        "room_id": room_b_id,
                        "name": "Room B Campaign",
                        "ruleset": "dnd-5e-2014",
                        "status": "active",
                        "created_at": now,
                        "updated_at": now,
                    },
                ]
            )
        )
        # Seats & Active Session
        conn.execute(
            insert(campaign_seats).values(
                id=dm_seat_id,
                campaign_id=campaign_active_session_id,
                role="dm",
                controller_kind="human",
                controller_access_session_id=dm_session_id,
                controller_epoch=1,
                created_at=now,
                updated_at=now,
            )
        )
        conn.execute(
            insert(sessions).values(
                id=active_session_id,
                campaign_id=campaign_active_session_id,
                status="active",
                dm_seat_id=dm_seat_id,
                dm_controller_kind="human",
                dm_controller_access_session_id=dm_session_id,
                started_at=now,
                created_at=now,
            )
        )
        # Characters
        for cid, rid, name in [
            (char_a1_id, room_a_id, "Char A1"),
            (char_a2_id, room_a_id, "Char A2"),
            (char_b1_id, room_b_id, "Char B1"),
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
                    room_id=rid,
                    character_id=cid,
                    created_at=now,
                )
            )
        # Adventures & entries
        conn.execute(
            insert(adventure_definitions).values(
                [
                    {
                        "id": adv_def_1_id,
                        "room_id": room_a_id,
                        "name": "Adventure 1",
                        "ruleset": "dnd-5e-2014",
                        "status": "finalized",
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": adv_def_unattached_id,
                        "room_id": room_a_id,
                        "name": "Unattached Adventure",
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
                        "id": adv_entry_attached_id,
                        "adventure_id": adv_def_1_id,
                        "kind": "scene",
                        "title": "Attached Scene",
                        "data_json": {},
                        "visibility": "public",
                        "sort_order": 0,
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": adv_entry_unattached_id,
                        "adventure_id": adv_def_unattached_id,
                        "kind": "scene",
                        "title": "Unattached Scene",
                        "data_json": {},
                        "visibility": "public",
                        "sort_order": 0,
                        "created_at": now,
                        "updated_at": now,
                    },
                ]
            )
        )
        # Attach adv_def_1 to campaign_attached
        conn.execute(
            insert(campaign_adventure_links).values(
                campaign_id=campaign_attached_id,
                adventure_id=adv_def_1_id,
                sort_order=0,
                attached_at=now,
            )
        )

    return ServiceFixture(
        engine=engine,
        service=service,
        room_a_id=room_a_id,
        room_b_id=room_b_id,
        owner_context=owner_context,
        dm_context=dm_context,
        member_context=member_context,
        campaign_empty_id=campaign_empty_id,
        campaign_attached_id=campaign_attached_id,
        campaign_active_session_id=campaign_active_session_id,
        campaign_b_id=campaign_b_id,
        char_a1_id=char_a1_id,
        char_a2_id=char_a2_id,
        char_b1_id=char_b1_id,
        adv_entry_attached_id=adv_entry_attached_id,
        adv_entry_unattached_id=adv_entry_unattached_id,
    )


# 1. Owner and DM management CRUD
def test_owner_and_dm_management_crud(fix: ServiceFixture) -> None:
    # Owner creates entry
    create_payload = RuntimeWorldEntryCreate(
        kind="npc",
        title="Bob the Blacksmith",
        body="A sturdy dwarf.",
        dm_notes="Has a secret map.",
    )
    created_view = fix.service.create_management(
        fix.owner_context,
        fix.room_a_id,
        fix.campaign_empty_id,
        create_payload,
        idempotency_key="create-bob-1",
    )
    assert isinstance(created_view, RuntimeWorldEntryDmView)
    assert created_view.title == "Bob the Blacksmith"
    assert created_view.dm_notes == "Has a secret map."
    assert created_view.revision == 1
    assert created_view.created_by_actor_kind == "human"
    assert created_view.created_by_actor_id == fix.owner_context.access_session_id

    # DM gets entry
    get_view = fix.service.get_management(
        fix.dm_context,
        fix.room_a_id,
        fix.campaign_empty_id,
        created_view.id,
    )
    assert get_view == created_view

    # DM lists entries
    list_views = fix.service.list_management(
        fix.dm_context,
        fix.room_a_id,
        fix.campaign_empty_id,
    )
    assert len(list_views) == 1
    assert list_views[0] == created_view

    # DM updates entry
    patch_payload = RuntimeWorldEntryPatch(
        expected_revision=1,
        title="Bob the Master Smith",
        dm_notes="Lost the secret map.",
    )
    updated_view = fix.service.update_management(
        fix.dm_context,
        fix.room_a_id,
        fix.campaign_empty_id,
        created_view.id,
        patch_payload,
        idempotency_key="update-bob-1",
    )
    assert updated_view.title == "Bob the Master Smith"
    assert updated_view.dm_notes == "Lost the secret map."
    assert updated_view.revision == 2

    # Owner archives entry
    archived_view = fix.service.archive_management(
        fix.owner_context,
        fix.room_a_id,
        fix.campaign_empty_id,
        created_view.id,
        expected_revision=2,
        idempotency_key="archive-bob-1",
    )
    assert archived_view.revision == 3
    assert archived_view.archived_at is not None

    # List default excludes archived
    active_views = fix.service.list_management(
        fix.dm_context,
        fix.room_a_id,
        fix.campaign_empty_id,
    )
    assert len(active_views) == 0

    # List with include_archived=True includes it
    all_views = fix.service.list_management(
        fix.dm_context,
        fix.room_a_id,
        fix.campaign_empty_id,
        include_archived=True,
    )
    assert len(all_views) == 1
    assert all_views[0] == archived_view


# 2. Member read and write denied
def test_member_read_and_write_denied(fix: ServiceFixture) -> None:
    entry = fix.service.create_management(
        fix.owner_context,
        fix.room_a_id,
        fix.campaign_empty_id,
        RuntimeWorldEntryCreate(kind="fact", body="The sun sets in the west."),
        idempotency_key="fact-1",
    )

    with pytest.raises(CampaignRuntimeAuthorityError):
        fix.service.create_management(
            fix.member_context,
            fix.room_a_id,
            fix.campaign_empty_id,
            RuntimeWorldEntryCreate(kind="fact", body="Another fact."),
            idempotency_key="fact-mem-1",
        )

    with pytest.raises(CampaignRuntimeAuthorityError):
        fix.service.get_management(
            fix.member_context,
            fix.room_a_id,
            fix.campaign_empty_id,
            entry.id,
        )

    with pytest.raises(CampaignRuntimeAuthorityError):
        fix.service.list_management(
            fix.member_context,
            fix.room_a_id,
            fix.campaign_empty_id,
        )

    with pytest.raises(CampaignRuntimeAuthorityError):
        fix.service.update_management(
            fix.member_context,
            fix.room_a_id,
            fix.campaign_empty_id,
            entry.id,
            RuntimeWorldEntryPatch(expected_revision=1, body="Updated fact."),
            idempotency_key="fact-mem-2",
        )

    with pytest.raises(CampaignRuntimeAuthorityError):
        fix.service.archive_management(
            fix.member_context,
            fix.room_a_id,
            fix.campaign_empty_id,
            entry.id,
            expected_revision=1,
            idempotency_key="fact-mem-3",
        )


# 3. Wrong room and campaign denied
def test_wrong_room_and_campaign_denied(fix: ServiceFixture) -> None:
    # Context room does not equal route room
    with pytest.raises(CampaignRuntimeNotFoundError):
        fix.service.create_management(
            fix.owner_context,
            fix.room_b_id,
            fix.campaign_empty_id,
            RuntimeWorldEntryCreate(kind="fact", body="Fact"),
            idempotency_key="wrong-room-1",
        )

    # Campaign not in room
    with pytest.raises(CampaignRuntimeNotFoundError):
        fix.service.create_management(
            fix.owner_context,
            fix.room_a_id,
            fix.campaign_b_id,
            RuntimeWorldEntryCreate(kind="fact", body="Fact"),
            idempotency_key="wrong-camp-1",
        )

    # Non-existent campaign
    with pytest.raises(CampaignRuntimeNotFoundError):
        fix.service.create_management(
            fix.owner_context,
            fix.room_a_id,
            uuid4(),
            RuntimeWorldEntryCreate(kind="fact", body="Fact"),
            idempotency_key="nonexist-camp-1",
        )

    # Non-existent entry
    with pytest.raises(CampaignRuntimeNotFoundError):
        fix.service.get_management(
            fix.dm_context,
            fix.room_a_id,
            fix.campaign_empty_id,
            uuid4(),
        )


# 4. Active Session blocks management write with zero side effects
def test_active_session_blocks_management_writes_zero_side_effects(fix: ServiceFixture) -> None:
    # Attempt create on active session campaign
    with pytest.raises(CampaignRuntimeActiveSessionError):
        fix.service.create_management(
            fix.owner_context,
            fix.room_a_id,
            fix.campaign_active_session_id,
            RuntimeWorldEntryCreate(kind="npc", title="Active NPC"),
            idempotency_key="active-npc-1",
        )

    # Verify zero entries and zero mutations were inserted
    with fix.engine.connect() as conn:
        entry_count = conn.scalar(
            select(func.count()).select_from(campaign_world_entries).where(
                campaign_world_entries.c.campaign_id == fix.campaign_active_session_id
            )
        )
        assert entry_count == 0
        mutation_count = conn.scalar(
            select(func.count()).select_from(campaign_world_mutations).where(
                campaign_world_mutations.c.campaign_id == fix.campaign_active_session_id
            )
        )
        assert mutation_count == 0

    # Reads are not blocked by active session
    views = fix.service.list_management(
        fix.dm_context,
        fix.room_a_id,
        fix.campaign_active_session_id,
    )
    assert views == ()


# 5. Empty Campaign create works
def test_empty_campaign_create_works(fix: ServiceFixture) -> None:
    # Scene
    scene = fix.service.create_management(
        fix.dm_context,
        fix.room_a_id,
        fix.campaign_empty_id,
        RuntimeWorldEntryCreate(kind="scene", title="Tavern", body="A lively place."),
        idempotency_key="scene-1",
    )
    assert scene.kind == "scene"

    # NPC
    npc = fix.service.create_management(
        fix.dm_context,
        fix.room_a_id,
        fix.campaign_empty_id,
        RuntimeWorldEntryCreate(kind="npc", title="Barkeeper"),
        idempotency_key="npc-1",
    )
    assert npc.kind == "npc"

    # Fact
    fact = fix.service.create_management(
        fix.dm_context,
        fix.room_a_id,
        fix.campaign_empty_id,
        RuntimeWorldEntryCreate(kind="fact", body="Beer is cheap here."),
        idempotency_key="fact-1",
    )
    assert fact.kind == "fact"

    # Quest
    quest = fix.service.create_management(
        fix.dm_context,
        fix.room_a_id,
        fix.campaign_empty_id,
        RuntimeWorldEntryCreate(kind="quest", title="Rats in cellar"),
        idempotency_key="quest-1",
    )
    assert quest.kind == "quest"

    all_entries = fix.service.list_management(
        fix.dm_context,
        fix.room_a_id,
        fix.campaign_empty_id,
    )
    assert len(all_entries) == 4


# 6. Quick-add minima and immutable-kind patch
def test_quick_add_minima_and_immutable_kind_patch(fix: ServiceFixture) -> None:
    # NPC requires nonblank title
    with pytest.raises((ValidationError, RuntimeEntryValidationError), match="NPC requires a nonblank title"):
        RuntimeWorldEntryCreate(kind="npc", title="")

    # Fact requires nonblank body
    with pytest.raises((ValidationError, RuntimeEntryValidationError), match="Fact requires a nonblank body"):
        RuntimeWorldEntryCreate(kind="fact", body="")

    # Scene requires at least title or body
    with pytest.raises((ValidationError, RuntimeEntryValidationError), match="Scene requires at least"):
        RuntimeWorldEntryCreate(kind="scene", title="", body="")

    # Create valid NPC
    npc = fix.service.create_management(
        fix.dm_context,
        fix.room_a_id,
        fix.campaign_empty_id,
        RuntimeWorldEntryCreate(kind="npc", title="Goblin Scout"),
        idempotency_key="npc-scout-1",
    )

    # Patch updating title to empty string fails quick-add minima check
    with pytest.raises(RuntimeEntryValidationError, match="NPC requires a nonblank title"):
        fix.service.update_management(
            fix.dm_context,
            fix.room_a_id,
            fix.campaign_empty_id,
            npc.id,
            RuntimeWorldEntryPatch(expected_revision=1, title=""),
            idempotency_key="npc-scout-patch-1",
        )

    # Patch with valid title succeeds
    updated = fix.service.update_management(
        fix.dm_context,
        fix.room_a_id,
        fix.campaign_empty_id,
        npc.id,
        RuntimeWorldEntryPatch(expected_revision=1, title="Goblin Chief"),
        idempotency_key="npc-scout-patch-2",
    )
    assert updated.title == "Goblin Chief"
    assert updated.revision == 2


# 7. Source attachment validation
def test_source_attachment_validation(fix: ServiceFixture) -> None:
    # Attached adventure entry succeeds on campaign_attached
    entry = fix.service.create_management(
        fix.dm_context,
        fix.room_a_id,
        fix.campaign_attached_id,
        RuntimeWorldEntryCreate(
            kind="scene",
            title="Attached Scene Ref",
            source_adventure_entry_id=fix.adv_entry_attached_id,
        ),
        idempotency_key="attached-src-1",
    )
    assert entry.source_adventure_entry_id == fix.adv_entry_attached_id

    # Unattached adventure entry fails
    with pytest.raises(CampaignRuntimeValidationError, match="not from an adventure attached"):
        fix.service.create_management(
            fix.dm_context,
            fix.room_a_id,
            fix.campaign_attached_id,
            RuntimeWorldEntryCreate(
                kind="scene",
                title="Unattached Scene Ref",
                source_adventure_entry_id=fix.adv_entry_unattached_id,
            ),
            idempotency_key="unattached-src-1",
        )

    # Non-existent adventure entry fails
    with pytest.raises(CampaignRuntimeValidationError, match="not from an adventure attached"):
        fix.service.create_management(
            fix.dm_context,
            fix.room_a_id,
            fix.campaign_attached_id,
            RuntimeWorldEntryCreate(
                kind="scene",
                title="Ghost Scene Ref",
                source_adventure_entry_id=uuid4(),
            ),
            idempotency_key="ghost-src-1",
        )


# 8. Recipient same-room validation
def test_recipient_same_room_validation(fix: ServiceFixture) -> None:
    # Recipient in same room succeeds
    entry = fix.service.create_management(
        fix.dm_context,
        fix.room_a_id,
        fix.campaign_empty_id,
        RuntimeWorldEntryCreate(
            kind="fact",
            body="Secret fact for Char A1",
            visibility="character",
            character_recipient_ids=(fix.char_a1_id,),
        ),
        idempotency_key="recip-same-room-1",
    )
    assert entry.character_recipient_ids == (fix.char_a1_id,)

    # Recipient in different room fails
    with pytest.raises(CampaignRuntimeValidationError, match="does not belong to room"):
        fix.service.create_management(
            fix.dm_context,
            fix.room_a_id,
            fix.campaign_empty_id,
            RuntimeWorldEntryCreate(
                kind="fact",
                body="Secret fact for Char B1",
                visibility="character",
                character_recipient_ids=(fix.char_b1_id,),
            ),
            idempotency_key="recip-diff-room-1",
        )

    # Non-existent character recipient fails
    with pytest.raises(CampaignRuntimeValidationError, match="does not belong to room"):
        fix.service.create_management(
            fix.dm_context,
            fix.room_a_id,
            fix.campaign_empty_id,
            RuntimeWorldEntryCreate(
                kind="fact",
                body="Secret fact for Nobody",
                visibility="character",
                character_recipient_ids=(uuid4(),),
            ),
            idempotency_key="recip-ghost-1",
        )


# 9. Item holder validation
def test_item_holder_validation(fix: ServiceFixture) -> None:
    # Setup scene and npc entries in campaign_empty
    scene = fix.service.create_management(
        fix.dm_context,
        fix.room_a_id,
        fix.campaign_empty_id,
        RuntimeWorldEntryCreate(kind="scene", title="Armory"),
        idempotency_key="holder-scene-1",
    )
    npc = fix.service.create_management(
        fix.dm_context,
        fix.room_a_id,
        fix.campaign_empty_id,
        RuntimeWorldEntryCreate(kind="npc", title="Guard"),
        idempotency_key="holder-npc-1",
    )

    # Item with holder scene succeeds
    item_scene = fix.service.create_management(
        fix.dm_context,
        fix.room_a_id,
        fix.campaign_empty_id,
        RuntimeWorldEntryCreate(
            kind="item",
            title="Iron Sword",
            state={"kind": "item", "holder_ref": {"kind": "scene", "target_id": str(scene.id)}},
        ),
        idempotency_key="item-scene-1",
    )
    assert item_scene.kind == "item"

    # Item with holder npc succeeds
    item_npc = fix.service.create_management(
        fix.dm_context,
        fix.room_a_id,
        fix.campaign_empty_id,
        RuntimeWorldEntryCreate(
            kind="item",
            title="Shield",
            state={"kind": "item", "holder_ref": {"kind": "npc", "target_id": str(npc.id)}},
        ),
        idempotency_key="item-npc-1",
    )
    assert item_npc.kind == "item"

    # Item with holder character in same room succeeds
    item_char = fix.service.create_management(
        fix.dm_context,
        fix.room_a_id,
        fix.campaign_empty_id,
        RuntimeWorldEntryCreate(
            kind="item",
            title="Magic Ring",
            state={"kind": "item", "holder_ref": {"kind": "character", "target_id": str(fix.char_a1_id)}},
        ),
        idempotency_key="item-char-1",
    )
    assert item_char.kind == "item"

    # Item with holder scene pointing to an NPC fails
    with pytest.raises(CampaignRuntimeValidationError, match="expected 'scene'"):
        fix.service.create_management(
            fix.dm_context,
            fix.room_a_id,
            fix.campaign_empty_id,
            RuntimeWorldEntryCreate(
                kind="item",
                title="Broken Bow",
                state={"kind": "item", "holder_ref": {"kind": "scene", "target_id": str(npc.id)}},
            ),
            idempotency_key="item-wrong-kind-1",
        )

    # Item with holder character in different room fails
    with pytest.raises(CampaignRuntimeValidationError, match="does not belong to room"):
        fix.service.create_management(
            fix.dm_context,
            fix.room_a_id,
            fix.campaign_empty_id,
            RuntimeWorldEntryCreate(
                kind="item",
                title="Stolen Dagger",
                state={"kind": "item", "holder_ref": {"kind": "character", "target_id": str(fix.char_b1_id)}},
            ),
            idempotency_key="item-diff-char-1",
        )

    # Item with holder party succeeds without target_id
    item_party = fix.service.create_management(
        fix.dm_context,
        fix.room_a_id,
        fix.campaign_empty_id,
        RuntimeWorldEntryCreate(
            kind="item",
            title="Party Wagon",
            state={"kind": "item", "holder_ref": {"kind": "party"}},
        ),
        idempotency_key="item-party-1",
    )
    assert item_party.kind == "item"


# 10. Idempotency replay for create, update, archive
def test_idempotency_replay_create_update_archive(fix: ServiceFixture) -> None:
    # 1. Create replay
    create_payload = RuntimeWorldEntryCreate(
        kind="npc",
        title="Replay NPC",
        dm_notes="Original DM notes",
    )
    view_1 = fix.service.create_management(
        fix.dm_context,
        fix.room_a_id,
        fix.campaign_empty_id,
        create_payload,
        idempotency_key="replay-key-create",
    )
    assert view_1.revision == 1

    # Replay create
    replay_view_1 = fix.service.create_management(
        fix.dm_context,
        fix.room_a_id,
        fix.campaign_empty_id,
        create_payload,
        idempotency_key="replay-key-create",
    )
    assert replay_view_1 == view_1
    assert replay_view_1.revision == 1

    # Verify only 1 mutation row was inserted
    with fix.engine.connect() as conn:
        mut_count = conn.scalar(
            select(func.count()).select_from(campaign_world_mutations).where(
                campaign_world_mutations.c.campaign_id == fix.campaign_empty_id,
                campaign_world_mutations.c.idempotency_key == "replay-key-create",
            )
        )
        assert mut_count == 1

    # 2. Update replay
    patch_payload = RuntimeWorldEntryPatch(
        expected_revision=1,
        title="Replay NPC Updated",
    )
    view_2 = fix.service.update_management(
        fix.dm_context,
        fix.room_a_id,
        fix.campaign_empty_id,
        view_1.id,
        patch_payload,
        idempotency_key="replay-key-update",
    )
    assert view_2.revision == 2

    # Replay update
    replay_view_2 = fix.service.update_management(
        fix.dm_context,
        fix.room_a_id,
        fix.campaign_empty_id,
        view_1.id,
        patch_payload,
        idempotency_key="replay-key-update",
    )
    assert replay_view_2 == view_2
    assert replay_view_2.revision == 2

    with fix.engine.connect() as conn:
        mut_count_2 = conn.scalar(
            select(func.count()).select_from(campaign_world_mutations).where(
                campaign_world_mutations.c.campaign_id == fix.campaign_empty_id,
                campaign_world_mutations.c.idempotency_key == "replay-key-update",
            )
        )
        assert mut_count_2 == 1

    # 3. Archive replay
    view_3 = fix.service.archive_management(
        fix.dm_context,
        fix.room_a_id,
        fix.campaign_empty_id,
        view_1.id,
        expected_revision=2,
        idempotency_key="replay-key-archive",
    )
    assert view_3.revision == 3

    # Replay archive
    replay_view_3 = fix.service.archive_management(
        fix.dm_context,
        fix.room_a_id,
        fix.campaign_empty_id,
        view_1.id,
        expected_revision=2,
        idempotency_key="replay-key-archive",
    )
    assert replay_view_3 == view_3
    assert replay_view_3.revision == 3

    with fix.engine.connect() as conn:
        mut_count_3 = conn.scalar(
            select(func.count()).select_from(campaign_world_mutations).where(
                campaign_world_mutations.c.campaign_id == fix.campaign_empty_id,
                campaign_world_mutations.c.idempotency_key == "replay-key-archive",
            )
        )
        assert mut_count_3 == 1


# 11. Idempotency conflict on different command, actor, target, action
def test_idempotency_conflict_different_command_actor_target_action(fix: ServiceFixture) -> None:
    # Create with key
    fix.service.create_management(
        fix.dm_context,
        fix.room_a_id,
        fix.campaign_empty_id,
        RuntimeWorldEntryCreate(kind="npc", title="Unique NPC"),
        idempotency_key="conflict-key-1",
    )

    # Same key, different command payload
    with pytest.raises(CampaignRuntimeIdempotencyConflictError):
        fix.service.create_management(
            fix.dm_context,
            fix.room_a_id,
            fix.campaign_empty_id,
            RuntimeWorldEntryCreate(kind="npc", title="Different NPC Name"),
            idempotency_key="conflict-key-1",
        )

    # Same key, different actor
    with pytest.raises(CampaignRuntimeIdempotencyConflictError):
        fix.service.create_management(
            fix.owner_context,
            fix.room_a_id,
            fix.campaign_empty_id,
            RuntimeWorldEntryCreate(kind="npc", title="Unique NPC"),
            idempotency_key="conflict-key-1",
        )

    # Same key, different action (e.g. update using create key)
    with pytest.raises(CampaignRuntimeIdempotencyConflictError):
        fix.service.update_management(
            fix.dm_context,
            fix.room_a_id,
            fix.campaign_empty_id,
            uuid4(),
            RuntimeWorldEntryPatch(expected_revision=1, title="Foo"),
            idempotency_key="conflict-key-1",
        )


# 12. Stale revision and validation error create no mutation and preserve target/recipients
def test_stale_revision_and_validation_error_create_no_mutation(fix: ServiceFixture) -> None:
    entry = fix.service.create_management(
        fix.dm_context,
        fix.room_a_id,
        fix.campaign_empty_id,
        RuntimeWorldEntryCreate(
            kind="fact",
            body="Secret Fact",
            visibility="character",
            character_recipient_ids=(fix.char_a1_id,),
        ),
        idempotency_key="base-entry-key",
    )
    assert entry.revision == 1

    # Stale revision on update
    with pytest.raises(CampaignRuntimeRevisionConflictError):
        fix.service.update_management(
            fix.dm_context,
            fix.room_a_id,
            fix.campaign_empty_id,
            entry.id,
            RuntimeWorldEntryPatch(expected_revision=99, body="New Fact"),
            idempotency_key="stale-update-key",
        )

    # Verify no mutation row was created for stale-update-key
    with fix.engine.connect() as conn:
        mut = conn.scalar(
            select(campaign_world_mutations.c.id).where(
                campaign_world_mutations.c.idempotency_key == "stale-update-key"
            )
        )
        assert mut is None

    # Validation error on update (recipient from wrong room)
    with pytest.raises(CampaignRuntimeValidationError):
        fix.service.update_management(
            fix.dm_context,
            fix.room_a_id,
            fix.campaign_empty_id,
            entry.id,
            RuntimeWorldEntryPatch(
                expected_revision=1,
                character_recipient_ids=(fix.char_b1_id,),
            ),
            idempotency_key="bad-recip-update-key",
        )

    # Verify target and recipients are completely preserved
    reloaded = fix.service.get_management(
        fix.dm_context,
        fix.room_a_id,
        fix.campaign_empty_id,
        entry.id,
    )
    assert reloaded.revision == 1
    assert reloaded.body == "Secret Fact"
    assert reloaded.character_recipient_ids == (fix.char_a1_id,)

    # Stale revision on archive
    with pytest.raises(CampaignRuntimeRevisionConflictError):
        fix.service.archive_management(
            fix.dm_context,
            fix.room_a_id,
            fix.campaign_empty_id,
            entry.id,
            expected_revision=99,
            idempotency_key="stale-archive-key",
        )

    # Still revision 1, unarchived
    reloaded2 = fix.service.get_management(
        fix.dm_context,
        fix.room_a_id,
        fix.campaign_empty_id,
        entry.id,
    )
    assert reloaded2.revision == 1
    assert reloaded2.archived_at is None


# 13. Pure projection matrix
def test_pure_projection_matrix(fix: ServiceFixture) -> None:
    # Create 4 entries: public, dm_only, character (for char_a1), character (for char_a2)
    pub = fix.service.create_management(
        fix.dm_context,
        fix.room_a_id,
        fix.campaign_empty_id,
        RuntimeWorldEntryCreate(kind="fact", body="Public Fact", visibility="public"),
        idempotency_key="proj-pub",
    )
    dmo = fix.service.create_management(
        fix.dm_context,
        fix.room_a_id,
        fix.campaign_empty_id,
        RuntimeWorldEntryCreate(
            kind="secret",
            title="DM Secret",
            visibility="dm_only",
            dm_notes="Secret DM notes",
        ),
        idempotency_key="proj-dmo",
    )
    c1 = fix.service.create_management(
        fix.dm_context,
        fix.room_a_id,
        fix.campaign_empty_id,
        RuntimeWorldEntryCreate(
            kind="fact",
            body="Char A1 Secret",
            visibility="character",
            character_recipient_ids=(fix.char_a1_id,),
        ),
        idempotency_key="proj-c1",
    )
    c2 = fix.service.create_management(
        fix.dm_context,
        fix.room_a_id,
        fix.campaign_empty_id,
        RuntimeWorldEntryCreate(
            kind="fact",
            body="Char A2 Secret",
            visibility="character",
            character_recipient_ids=(fix.char_a2_id,),
        ),
        idempotency_key="proj-c2",
    )

    # Fetch stored aggregates
    aggregates = fix.service.runtime_repo.list_entries(fix.campaign_empty_id)
    assert len(aggregates) == 4

    # DM audience projection: sees all 4 as DmView with dm_notes
    dm_projected = project_runtime_aggregates(aggregates, controlled_character_ids=(), is_dm=True)
    assert len(dm_projected) == 4
    for p in dm_projected:
        assert isinstance(p, RuntimeWorldEntryDmView)

    # Calling projection helpers without explicit controlled_character_ids raises TypeError
    with pytest.raises(TypeError):
        project_runtime_aggregates(aggregates, is_dm=True)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        project_runtime_aggregate(aggregates[0], is_dm=True)  # type: ignore[call-arg]

    # Player audience controlling char_a1: sees pub and c1 as PlayerView, no dm_notes, no dmo, no c2
    p1_projected = project_runtime_aggregates(
        aggregates,
        controlled_character_ids=[fix.char_a1_id],
        is_dm=False,
    )
    assert len(p1_projected) == 2
    p1_ids = {p.id for p in p1_projected}
    assert p1_ids == {pub.id, c1.id}
    for p in p1_projected:
        assert isinstance(p, RuntimeWorldEntryPlayerView)

    # Player audience controlling char_a2: sees pub and c2
    p2_projected = project_runtime_aggregates(
        aggregates,
        controlled_character_ids=[fix.char_a2_id],
        is_dm=False,
    )
    assert len(p2_projected) == 2
    p2_ids = {p.id for p in p2_projected}
    assert p2_ids == {pub.id, c2.id}

    # Player audience controlling no characters: sees only public
    p0_projected = project_runtime_aggregates(
        aggregates,
        controlled_character_ids=[],
        is_dm=False,
    )
    assert len(p0_projected) == 1
    assert p0_projected[0].id == pub.id


# 14. Management patch explicit null versus omission preservation
def test_management_patch_explicit_null_vs_omission_preservation(fix: ServiceFixture) -> None:
    # Create an entry with all optional nullable fields populated
    entry = fix.service.create_management(
        fix.dm_context,
        fix.room_a_id,
        fix.campaign_attached_id,
        RuntimeWorldEntryCreate(
            kind="scene",
            title="Initial Title",
            body="Initial Body",
            dm_notes="Initial DM notes",
            source_adventure_entry_id=fix.adv_entry_attached_id,
            provenance_json={"source": "manual", "chapter": 1},
            needs_review=True,
            visibility="character",
            character_recipient_ids=(fix.char_a1_id,),
        ),
        idempotency_key="null-omission-create",
    )
    assert entry.revision == 1
    assert entry.title == "Initial Title"
    assert entry.body == "Initial Body"
    assert entry.dm_notes == "Initial DM notes"
    assert entry.source_adventure_entry_id == fix.adv_entry_attached_id
    assert entry.provenance_json == {"source": "manual", "chapter": 1}
    assert entry.needs_review is True
    assert entry.visibility == "character"
    assert entry.character_recipient_ids == (fix.char_a1_id,)

    # 1. Omission patch: only update title; omit all other optional fields
    omission_patch = RuntimeWorldEntryPatch(
        expected_revision=1,
        title="Updated Title Omission",
    )
    after_omission = fix.service.update_management(
        fix.dm_context,
        fix.room_a_id,
        fix.campaign_attached_id,
        entry.id,
        omission_patch,
        idempotency_key="null-omission-patch-1",
    )
    assert after_omission.revision == 2
    assert after_omission.title == "Updated Title Omission"
    # Preserved fields
    assert after_omission.body == "Initial Body"
    assert after_omission.dm_notes == "Initial DM notes"
    assert after_omission.source_adventure_entry_id == fix.adv_entry_attached_id
    assert after_omission.provenance_json == {"source": "manual", "chapter": 1}
    assert after_omission.needs_review is True
    assert after_omission.visibility == "character"
    assert after_omission.character_recipient_ids == (fix.char_a1_id,)

    # 2. Explicit null patch: explicitly set dm_notes=None, source_adventure_entry_id=None, provenance_json=None
    explicit_null_patch = RuntimeWorldEntryPatch(
        expected_revision=2,
        dm_notes=None,
        source_adventure_entry_id=None,
        provenance_json=None,
    )
    after_null = fix.service.update_management(
        fix.dm_context,
        fix.room_a_id,
        fix.campaign_attached_id,
        entry.id,
        explicit_null_patch,
        idempotency_key="null-omission-patch-2",
    )
    assert after_null.revision == 3
    # Preserved fields
    assert after_null.title == "Updated Title Omission"
    assert after_null.body == "Initial Body"
    assert after_null.needs_review is True
    assert after_null.visibility == "character"
    assert after_null.character_recipient_ids == (fix.char_a1_id,)
    # Explicitly cleared fields
    assert after_null.dm_notes is None
    assert after_null.source_adventure_entry_id is None
    assert after_null.provenance_json is None

    # Reload through get_management to verify persistence
    reloaded = fix.service.get_management(
        fix.dm_context,
        fix.room_a_id,
        fix.campaign_attached_id,
        entry.id,
    )
    assert reloaded.revision == 3
    assert reloaded.title == "Updated Title Omission"
    assert reloaded.dm_notes is None
    assert reloaded.source_adventure_entry_id is None
    assert reloaded.provenance_json is None
    assert reloaded.needs_review is True
    assert reloaded.character_recipient_ids == (fix.char_a1_id,)
