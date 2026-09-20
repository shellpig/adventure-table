from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, event, func, insert, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool


def _ev_key(k: str) -> str:
    return f"p6b-world:{hashlib.sha256(k.encode('utf-8')).hexdigest()}"

from app.db import metadata
from app.domain.campaign_runtime import (
    CampaignRuntimeActiveSessionError,
    CampaignRuntimeArchivedError,
    CampaignRuntimeAuthorityError,
    CampaignRuntimeConflictError,
    CampaignRuntimeIdempotencyConflictError,
    CampaignRuntimeNotFoundError,
    CampaignRuntimeRevisionConflictError,
    CampaignRuntimeService,
    CampaignRuntimeSessionNotActiveError,
    CampaignRuntimeValidationError,
    RuntimeWorldEntryCreate,
    RuntimeWorldEntryDmView,
    RuntimeWorldEntryPatch,
    RuntimeWorldEntryPlayerView,
)
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.table_events import (
    TableActorContext,
    TableActorKind,
    TableEventService,
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
from app.persistence.campaign_runtime.tables import (
    campaign_world_entries,
    campaign_world_entry_characters,
    campaign_world_mutations,
)
from app.persistence.characters import characters
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
class ActiveFixture:
    engine: Engine
    service: CampaignRuntimeService
    notifier: RecordingNotifier
    room_id: UUID
    campaign_id: UUID
    ai_campaign_id: UUID
    session_id: UUID
    ai_session_id: UUID
    inactive_session_id: UUID
    # Actors
    human_dm_actor: TableActorContext
    ai_dm_actor: TableActorContext
    human_player_1_actor: TableActorContext
    ai_player_2_actor: TableActorContext
    # IDs
    dm_seat_id: UUID
    ai_dm_seat_id: UUID
    player_1_seat_id: UUID
    player_2_seat_id: UUID
    char_1_id: UUID
    char_2_id: UUID
    char_3_id: UUID
    adv_entry_id: UUID
    owner_context: RoomAccessContext
    human_dm_access_id: UUID
    ai_dm_grant_id: UUID


@pytest.fixture
def fix() -> ActiveFixture:
    engine = _engine()
    notifier = RecordingNotifier()
    event_service = TableEventService(TableEventRepository(engine), notifier=notifier)
    service = CampaignRuntimeService(engine, event_service)
    now = datetime.now(timezone.utc)

    room_id = uuid4()
    campaign_id = uuid4()
    ai_campaign_id = uuid4()
    session_id = uuid4()
    ai_session_id = uuid4()
    inactive_session_id = uuid4()

    owner_access_id = uuid4()
    human_dm_access_id = uuid4()
    human_player_1_access_id = uuid4()

    ai_dm_grant_id = uuid4()
    ai_player_grant_id = uuid4()

    dm_seat_id = uuid4()
    ai_dm_seat_id = uuid4()
    player_1_seat_id = uuid4()
    player_2_seat_id = uuid4()

    char_1_id = uuid4()
    char_2_id = uuid4()
    char_3_id = uuid4()

    adv_def_id = uuid4()
    adv_entry_id = uuid4()

    owner_context = RoomAccessContext(
        room_id=room_id,
        access_session_id=owner_access_id,
        authority=RoomAccessAuthority.OWNER,
        display_name="Owner",
    )

    with engine.begin() as conn:
        # Room
        conn.execute(
            insert(rooms).values(
                id=room_id,
                code="ROOM-ACTIVE",
                name="Active Room",
                password_salt=b"salt",
                password_hash=b"pw",
                owner_key_hash=b"owner",
                dm_key_hash=b"dm",
                created_at=now,
                updated_at=now,
            )
        )
        # Access sessions
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
                        "id": human_dm_access_id,
                        "room_id": room_id,
                        "authority": "dm",
                        "token_hash": b"tok_dm_hash_1234567890123",
                        "display_name": "Human DM",
                        "created_at": now,
                        "last_seen_at": now,
                    },
                    {
                        "id": human_player_1_access_id,
                        "room_id": room_id,
                        "authority": "member",
                        "token_hash": b"tok_p1_hash_1234567890123",
                        "display_name": "Human Player 1",
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
                        "name": "Active Campaign",
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
            (char_3_id, "Rogue 3"),
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
        # Adventure definition and link
        conn.execute(
            insert(adventure_definitions).values(
                id=adv_def_id,
                room_id=room_id,
                name="Test Adventure",
                ruleset="dnd-5e-2014",
                status="finalized",
                created_at=now,
                updated_at=now,
            )
        )
        conn.execute(
            insert(adventure_entries).values(
                id=adv_entry_id,
                adventure_id=adv_def_id,
                kind="scene",
                title="Adventure Scene",
                data_json={},
                visibility="public",
                sort_order=0,
                created_at=now,
                updated_at=now,
            )
        )
        conn.execute(
            insert(campaign_adventure_links).values(
                campaign_id=campaign_id,
                adventure_id=adv_def_id,
                sort_order=0,
                attached_at=now,
            )
        )

        # Seats (initial seed)
        conn.execute(
            insert(campaign_seats).values(
                [
                    {
                        "id": dm_seat_id,
                        "campaign_id": campaign_id,
                        "role": "dm",
                        "controller_kind": "human",
                        "controller_access_session_id": human_dm_access_id,
                        "ai_controller_grant_id": None,
                        "controller_epoch": 1,
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
                    {
                        "id": player_1_seat_id,
                        "campaign_id": campaign_id,
                        "role": "player",
                        "controller_kind": "human",
                        "controller_access_session_id": human_player_1_access_id,
                        "ai_controller_grant_id": None,
                        "controller_epoch": 1,
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": player_2_seat_id,
                        "campaign_id": campaign_id,
                        "role": "player",
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

        # 1. Main session (Human DM) & Inactive session
        conn.execute(
            insert(sessions).values(
                id=session_id,
                campaign_id=campaign_id,
                status="active",
                dm_seat_id=dm_seat_id,
                dm_controller_kind="human",
                dm_controller_access_session_id=human_dm_access_id,
                started_at=now,
                created_at=now,
            )
        )
        conn.execute(
            insert(sessions).values(
                id=inactive_session_id,
                campaign_id=campaign_id,
                status="ended",
                dm_seat_id=dm_seat_id,
                dm_controller_kind="human",
                dm_controller_access_session_id=human_dm_access_id,
                started_at=now,
                ended_at=now,
                created_at=now,
            )
        )

        # AI controller grants
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
                        "campaign_id": campaign_id,
                        "seat_id": player_2_seat_id,
                        "role": "player",
                        "session_id": session_id,
                        "secret_hash": b"p" * 32,
                        "secret_prefix": "aipl",
                        "generation": 1,
                        "status": "active",
                        "pre_session_expires_at": None,
                        "handoff_return_access_session_id": human_player_1_access_id,
                        "temporary_instruction": None,
                        "created_at": now,
                        "bound_at": now,
                        "revoked_at": None,
                        "last_seen_at": None,
                    },
                ]
            )
        )

        # 2. AI DM session
        conn.execute(
            insert(sessions).values(
                id=ai_session_id,
                campaign_id=ai_campaign_id,
                status="active",
                dm_seat_id=ai_dm_seat_id,
                dm_controller_kind="ai",
                dm_controller_ai_grant_id=ai_dm_grant_id,
                dm_controller_generation=1,
                started_at=now,
                created_at=now,
            )
        )

        # Transition AI DM grant to active session
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
                        "controller_access_session_id_at_join": human_dm_access_id,
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
                        "controller_access_session_id_at_join": human_player_1_access_id,
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

    human_dm_actor = event_service.resolve_human_actor(
        room_id=room_id,
        campaign_id=campaign_id,
        session_id=session_id,
        context=RoomAccessContext(
            room_id=room_id,
            access_session_id=human_dm_access_id,
            authority=RoomAccessAuthority.DM,
            display_name="Human DM",
        ),
    )
    ai_dm_actor = event_service.resolve_ai_actor(
        room_id=room_id,
        campaign_id=ai_campaign_id,
        session_id=ai_session_id,
        grant_id=ai_dm_grant_id,
        generation=1,
    )
    human_player_1_actor = event_service.resolve_human_actor(
        room_id=room_id,
        campaign_id=campaign_id,
        session_id=session_id,
        context=RoomAccessContext(
            room_id=room_id,
            access_session_id=human_player_1_access_id,
            authority=RoomAccessAuthority.MEMBER,
            display_name="Human Player 1",
        ),
    )
    ai_player_2_actor = event_service.resolve_ai_actor(
        room_id=room_id,
        campaign_id=campaign_id,
        session_id=session_id,
        grant_id=ai_player_grant_id,
        generation=1,
    )

    return ActiveFixture(
        engine=engine,
        service=service,
        notifier=notifier,
        room_id=room_id,
        campaign_id=campaign_id,
        ai_campaign_id=ai_campaign_id,
        session_id=session_id,
        ai_session_id=ai_session_id,
        inactive_session_id=inactive_session_id,
        human_dm_actor=human_dm_actor,
        ai_dm_actor=ai_dm_actor,
        human_player_1_actor=human_player_1_actor,
        ai_player_2_actor=ai_player_2_actor,
        dm_seat_id=dm_seat_id,
        ai_dm_seat_id=ai_dm_seat_id,
        player_1_seat_id=player_1_seat_id,
        player_2_seat_id=player_2_seat_id,
        char_1_id=char_1_id,
        char_2_id=char_2_id,
        char_3_id=char_3_id,
        adv_entry_id=adv_entry_id,
        owner_context=owner_context,
        human_dm_access_id=human_dm_access_id,
        ai_dm_grant_id=ai_dm_grant_id,
    )


# 1. Human DM and AI DM create/update/archive parity
def test_human_and_ai_dm_parity(fix: ActiveFixture) -> None:
    # Human DM creates NPC
    human_create = RuntimeWorldEntryCreate(
        kind="npc",
        title="Gorim Ironbreaker",
        body="A grizzled dwarf blacksmith.",
        dm_notes="Knows secret entrance.",
    )
    human_view = fix.service.create_active(
        fix.human_dm_actor,
        human_create,
        idempotency_key="h-create-gorim",
    )
    assert isinstance(human_view, RuntimeWorldEntryDmView)
    assert human_view.title == "Gorim Ironbreaker"
    assert human_view.created_by_actor_kind == "human"
    assert human_view.created_by_actor_id == fix.human_dm_access_id
    assert human_view.revision == 1
    assert len(fix.notifier.notifications) == 1
    assert fix.notifier.notifications[-1] == fix.session_id

    # Human DM updates NPC
    human_patch = RuntimeWorldEntryPatch(
        expected_revision=1,
        title="Gorim Ironbreaker, Master Smith",
    )
    human_updated = fix.service.update_active(
        fix.human_dm_actor,
        human_view.id,
        human_patch,
        idempotency_key="h-update-gorim",
    )
    assert human_updated.title == "Gorim Ironbreaker, Master Smith"
    assert human_updated.revision == 2
    assert len(fix.notifier.notifications) == 2

    # Human DM archives NPC
    human_archived = fix.service.archive_active(
        fix.human_dm_actor,
        human_view.id,
        expected_revision=2,
        idempotency_key="h-archive-gorim",
    )
    assert human_archived.archived_at is not None
    assert human_archived.revision == 3
    assert len(fix.notifier.notifications) == 3

    # AI DM creates Fact
    ai_create = RuntimeWorldEntryCreate(
        kind="fact",
        body="The red dragon lives in Mount Ash.",
        dm_notes="Actually sleeping.",
    )
    ai_view = fix.service.create_active(
        fix.ai_dm_actor,
        ai_create,
        idempotency_key="ai-create-dragon",
    )
    assert isinstance(ai_view, RuntimeWorldEntryDmView)
    assert ai_view.body == "The red dragon lives in Mount Ash."
    assert ai_view.created_by_actor_kind == "ai"
    assert ai_view.created_by_actor_id == fix.ai_dm_grant_id
    assert ai_view.revision == 1
    assert len(fix.notifier.notifications) == 4
    assert fix.notifier.notifications[-1] == fix.ai_session_id

    # AI DM updates Fact
    ai_patch = RuntimeWorldEntryPatch(
        expected_revision=1,
        body="The ancient red dragon lives in Mount Ash.",
    )
    ai_updated = fix.service.update_active(
        fix.ai_dm_actor,
        ai_view.id,
        ai_patch,
        idempotency_key="ai-update-dragon",
    )
    assert ai_updated.body == "The ancient red dragon lives in Mount Ash."
    assert ai_updated.revision == 2
    assert len(fix.notifier.notifications) == 5

    # AI DM archives Fact
    ai_archived = fix.service.archive_active(
        fix.ai_dm_actor,
        ai_view.id,
        expected_revision=2,
        idempotency_key="ai-archive-dragon",
    )
    assert ai_archived.archived_at is not None
    assert ai_archived.revision == 3
    assert len(fix.notifier.notifications) == 6


# 2. Rejection matrix with zero side effects
def test_rejection_matrix_zero_side_effects(fix: ActiveFixture) -> None:
    create_payload = RuntimeWorldEntryCreate(
        kind="npc",
        title="Unauthorized NPC",
    )

    # Human Player rejected
    with pytest.raises(CampaignRuntimeAuthorityError, match="Only the current DM"):
        fix.service.create_active(
            fix.human_player_1_actor,
            create_payload,
            idempotency_key="unauth-1",
        )

    # AI Player rejected
    with pytest.raises(CampaignRuntimeAuthorityError, match="Only the current DM"):
        fix.service.create_active(
            fix.ai_player_2_actor,
            create_payload,
            idempotency_key="unauth-2",
        )

    # Non-participant actor rejected
    non_participant_actor = TableActorContext(
        actor_kind=TableActorKind.HUMAN,
        room_id=fix.room_id,
        campaign_id=fix.campaign_id,
        session_id=fix.session_id,
        seat_id=uuid4(),
        controlled_seat_ids=(uuid4(),),
        role="dm",
        is_current_dm=True,
        access_session_id=fix.human_dm_access_id,
    )
    with pytest.raises(CampaignRuntimeAuthorityError, match="no longer current"):
        fix.service.create_active(
            non_participant_actor,
            create_payload,
            idempotency_key="unauth-3",
        )

    # Wrong scope actor (wrong room)
    wrong_room_actor = TableActorContext(
        actor_kind=TableActorKind.HUMAN,
        room_id=uuid4(),
        campaign_id=fix.campaign_id,
        session_id=fix.session_id,
        seat_id=fix.dm_seat_id,
        controlled_seat_ids=(fix.dm_seat_id,),
        role="dm",
        is_current_dm=True,
        access_session_id=fix.human_dm_access_id,
    )
    with pytest.raises(CampaignRuntimeNotFoundError):
        fix.service.create_active(
            wrong_room_actor,
            create_payload,
            idempotency_key="unauth-4",
        )

    # Stale Human access (revoked access session)
    stale_access_id = uuid4()
    with fix.engine.begin() as conn:
        conn.execute(
            insert(room_access_sessions).values(
                id=stale_access_id,
                room_id=fix.room_id,
                authority="dm",
                token_hash=b"tok_stale_hash_1234567890",
                display_name="Stale DM",
                revoked_at=datetime.now(timezone.utc),
                created_at=datetime.now(timezone.utc),
                last_seen_at=datetime.now(timezone.utc),
            )
        )
    stale_human_actor = TableActorContext(
        actor_kind=TableActorKind.HUMAN,
        room_id=fix.room_id,
        campaign_id=fix.campaign_id,
        session_id=fix.session_id,
        seat_id=fix.dm_seat_id,
        controlled_seat_ids=(fix.dm_seat_id,),
        role="dm",
        is_current_dm=True,
        access_session_id=stale_access_id,
    )
    with pytest.raises(CampaignRuntimeAuthorityError, match="no longer current"):
        fix.service.create_active(
            stale_human_actor,
            create_payload,
            idempotency_key="unauth-5",
        )

    # Stale AI generation
    stale_ai_actor = TableActorContext(
        actor_kind=TableActorKind.AI,
        room_id=fix.room_id,
        campaign_id=fix.ai_campaign_id,
        session_id=fix.ai_session_id,
        seat_id=fix.ai_dm_seat_id,
        controlled_seat_ids=(fix.ai_dm_seat_id,),
        role="dm",
        is_current_dm=True,
        ai_controller_grant_id=fix.ai_dm_grant_id,
        grant_generation=999,  # Generation mismatch
    )
    with pytest.raises(CampaignRuntimeAuthorityError, match="no longer current"):
        fix.service.create_active(
            stale_ai_actor,
            create_payload,
            idempotency_key="unauth-6",
        )

    # Inactive session
    inactive_actor = TableActorContext(
        actor_kind=TableActorKind.HUMAN,
        room_id=fix.room_id,
        campaign_id=fix.campaign_id,
        session_id=fix.inactive_session_id,
        seat_id=fix.dm_seat_id,
        controlled_seat_ids=(fix.dm_seat_id,),
        role="dm",
        is_current_dm=True,
        access_session_id=fix.human_dm_access_id,
    )
    with pytest.raises(CampaignRuntimeSessionNotActiveError, match="is not active"):
        fix.service.create_active(
            inactive_actor,
            create_payload,
            idempotency_key="unauth-7",
        )

    # Inactive session reads (get_active and list_active for DM)
    with pytest.raises(CampaignRuntimeSessionNotActiveError, match="is not active"):
        fix.service.get_active(inactive_actor, uuid4())
    with pytest.raises(CampaignRuntimeSessionNotActiveError, match="is not active"):
        fix.service.list_active(inactive_actor)

    # Inactive session reads (get_active and list_active for Player)
    inactive_player_actor = TableActorContext(
        actor_kind=TableActorKind.HUMAN,
        room_id=fix.room_id,
        campaign_id=fix.campaign_id,
        session_id=fix.inactive_session_id,
        seat_id=fix.player_1_seat_id,
        controlled_seat_ids=(fix.player_1_seat_id,),
        role="player",
        is_current_dm=False,
        access_session_id=fix.human_player_1_actor.access_session_id,
    )
    with pytest.raises(CampaignRuntimeSessionNotActiveError, match="is not active"):
        fix.service.get_active(inactive_player_actor, uuid4())
    with pytest.raises(CampaignRuntimeSessionNotActiveError, match="is not active"):
        fix.service.list_active(inactive_player_actor)

    # Management write blocked while session is active
    with pytest.raises(CampaignRuntimeActiveSessionError, match="active session"):
        fix.service.create_management(
            fix.owner_context,
            fix.room_id,
            fix.campaign_id,
            create_payload,
            idempotency_key="unauth-8",
        )

    # Verify zero side effects: no entries created, no mutations, no events, no notifications
    with fix.engine.connect() as conn:
        entry_count = conn.execute(select(func.count(campaign_world_entries.c.id))).scalar()
        assert entry_count == 0
        mutation_count = conn.execute(select(func.count(campaign_world_mutations.c.id))).scalar()
        assert mutation_count == 0
        event_count = conn.execute(select(func.count(session_events.c.id))).scalar()
        assert event_count == 0
    assert len(fix.notifier.notifications) == 0


# 3. Active read matrix
def test_active_read_matrix(fix: ActiveFixture) -> None:
    # DM creates 4 entries:
    # 1. Public entry
    pub_view = fix.service.create_active(
        fix.human_dm_actor,
        RuntimeWorldEntryCreate(
            kind="scene",
            title="Public Town Square",
            body="A noisy plaza.",
            visibility="public",
            dm_notes="Undercover guard watching.",
        ),
        idempotency_key="mat-pub",
    )
    # 2. Own-character entry for char_1
    c1_view = fix.service.create_active(
        fix.human_dm_actor,
        RuntimeWorldEntryCreate(
            kind="secret",
            title="Fighter's Secret",
            body="Char 1 knows where the treasure is.",
            visibility="character",
            character_recipient_ids=(fix.char_1_id,),
            dm_notes="Treasure is guarded.",
        ),
        idempotency_key="mat-c1",
    )
    # 3. Other-character entry for char_2
    c2_view = fix.service.create_active(
        fix.human_dm_actor,
        RuntimeWorldEntryCreate(
            kind="secret",
            title="Wizard's Spellbook Clue",
            body="Char 2 knows ancient runes.",
            visibility="character",
            character_recipient_ids=(fix.char_2_id,),
            dm_notes="Runes are cursed.",
        ),
        idempotency_key="mat-c2",
    )
    # 4. DM-only entry
    dm_only_view = fix.service.create_active(
        fix.human_dm_actor,
        RuntimeWorldEntryCreate(
            kind="secret",
            title="Campaign Master Plan",
            body="The villain's identity.",
            visibility="dm_only",
            dm_notes="DM only knowledge.",
        ),
        idempotency_key="mat-dmonly",
    )

    # --- DM Reads ---
    dm_list = fix.service.list_active(fix.human_dm_actor)
    assert len(dm_list) == 4
    for item in dm_list:
        assert isinstance(item, RuntimeWorldEntryDmView)
        assert item.dm_notes is not None

    dm_get = fix.service.get_active(fix.human_dm_actor, dm_only_view.id)
    assert isinstance(dm_get, RuntimeWorldEntryDmView)
    assert dm_get.dm_notes == "DM only knowledge."

    # --- Player 1 (char_1) Reads ---
    # Can read public
    p1_pub = fix.service.get_active(fix.human_player_1_actor, pub_view.id)
    assert isinstance(p1_pub, RuntimeWorldEntryPlayerView)
    assert p1_pub.title == "Public Town Square"
    assert "dm_notes" not in p1_pub.model_dump()

    # Can read own character knowledge
    p1_c1 = fix.service.get_active(fix.human_player_1_actor, c1_view.id)
    assert isinstance(p1_c1, RuntimeWorldEntryPlayerView)
    assert p1_c1.title == "Fighter's Secret"
    assert "dm_notes" not in p1_c1.model_dump()

    # Cannot read other character knowledge (must raise NotFoundError, no existence leak)
    with pytest.raises(CampaignRuntimeNotFoundError):
        fix.service.get_active(fix.human_player_1_actor, c2_view.id)

    # Cannot read DM-only knowledge (must raise NotFoundError)
    with pytest.raises(CampaignRuntimeNotFoundError):
        fix.service.get_active(fix.human_player_1_actor, dm_only_view.id)

    # list_active for Player 1 contains ONLY public and char_1 entries
    p1_list = fix.service.list_active(fix.human_player_1_actor)
    assert len(p1_list) == 2
    p1_list_ids = {e.id for e in p1_list}
    assert p1_list_ids == {pub_view.id, c1_view.id}
    for e in p1_list:
        assert isinstance(e, RuntimeWorldEntryPlayerView)
        assert "dm_notes" not in e.model_dump()

    # --- Player 2 (AI, char_2) Reads ---
    # Can read public
    p2_pub = fix.service.get_active(fix.ai_player_2_actor, pub_view.id)
    assert isinstance(p2_pub, RuntimeWorldEntryPlayerView)

    # Can read own char_2 knowledge
    p2_c2 = fix.service.get_active(fix.ai_player_2_actor, c2_view.id)
    assert isinstance(p2_c2, RuntimeWorldEntryPlayerView)
    assert p2_c2.title == "Wizard's Spellbook Clue"

    # Cannot read char_1 knowledge
    with pytest.raises(CampaignRuntimeNotFoundError):
        fix.service.get_active(fix.ai_player_2_actor, c1_view.id)

    # Cannot read DM-only knowledge
    with pytest.raises(CampaignRuntimeNotFoundError):
        fix.service.get_active(fix.ai_player_2_actor, dm_only_view.id)

    # list_active for Player 2 contains ONLY public and char_2 entries
    p2_list = fix.service.list_active(fix.ai_player_2_actor)
    assert len(p2_list) == 2
    p2_list_ids = {e.id for e in p2_list}
    assert p2_list_ids == {pub_view.id, c2_view.id}


# 4. Event payload exact allowlist and visibility/recipient mapping
def test_event_payload_allowlist_and_visibility_mapping(fix: ActiveFixture) -> None:
    # 1. Public entry
    pub_view = fix.service.create_active(
        fix.human_dm_actor,
        RuntimeWorldEntryCreate(
            kind="npc",
            title="Public Bartender",
            visibility="public",
        ),
        idempotency_key="ev-pub",
    )
    # 2. DM-only entry
    dm_view = fix.service.create_active(
        fix.human_dm_actor,
        RuntimeWorldEntryCreate(
            kind="secret",
            title="Hidden Dragon",
            body="Secret body text",
            dm_notes="Secret DM notes",
            visibility="dm_only",
        ),
        idempotency_key="ev-dm",
    )
    # 3. Character entry with active session characters (char_1 and char_2)
    char_view = fix.service.create_active(
        fix.human_dm_actor,
        RuntimeWorldEntryCreate(
            kind="fact",
            body="Shared character fact",
            visibility="character",
            character_recipient_ids=(fix.char_1_id, fix.char_2_id),
        ),
        idempotency_key="ev-char",
    )
    # 4. Character entry with inactive character (char_3 is in campaign/room but not in session)
    char3_view = fix.service.create_active(
        fix.human_dm_actor,
        RuntimeWorldEntryCreate(
            kind="fact",
            body="Rogue's fact",
            visibility="character",
            character_recipient_ids=(fix.char_3_id,),
        ),
        idempotency_key="ev-char3",
    )

    with fix.engine.connect() as conn:
        events = conn.execute(
            select(session_events).order_by(session_events.c.seq)
        ).mappings().all()
        assert len(events) == 4

        # Check public event
        ev_pub = events[0]
        assert ev_pub["kind"] == "world.entry.created"
        assert ev_pub["visibility"] == "public"
        assert ev_pub["recipient_seat_ids"] == []
        assert ev_pub["acting_seat_id"] == fix.dm_seat_id
        assert ev_pub["execution_mode"] == "self"
        assert ev_pub["subject_seat_id"] is None
        assert ev_pub["subject_character_id"] is None
        assert set(ev_pub["payload"].keys()) == {"entry_id", "entry_kind", "revision", "action"}
        assert ev_pub["payload"]["entry_id"] == str(pub_view.id)
        assert ev_pub["payload"]["entry_kind"] == "npc"
        assert ev_pub["payload"]["revision"] == 1
        assert ev_pub["payload"]["action"] == "created"

        # Check DM-only event
        ev_dm = events[1]
        assert ev_dm["kind"] == "world.entry.created"
        assert ev_dm["visibility"] == "dm_only"
        assert ev_dm["recipient_seat_ids"] == []
        assert set(ev_dm["payload"].keys()) == {"entry_id", "entry_kind", "revision", "action"}
        assert ev_dm["payload"]["action"] == "created"
        # Verify no secret text in payload
        assert "Hidden Dragon" not in str(ev_dm["payload"])
        assert "Secret body text" not in str(ev_dm["payload"])
        assert "Secret DM notes" not in str(ev_dm["payload"])

        # Check character event (char_1 and char_2) -> maps to player_1_seat_id and player_2_seat_id
        ev_char = events[2]
        assert ev_char["kind"] == "world.entry.created"
        assert ev_char["visibility"] == "seat_private"
        recipient_seats = {UUID(s) for s in ev_char["recipient_seat_ids"]}
        assert recipient_seats == {fix.player_1_seat_id, fix.player_2_seat_id}
        assert set(ev_char["payload"].keys()) == {"entry_id", "entry_kind", "revision", "action"}
        # Never put character recipient IDs in payload
        assert str(fix.char_1_id) not in str(ev_char["payload"])
        assert str(fix.char_2_id) not in str(ev_char["payload"])

        # Check character event for inactive character (char_3) -> seat_private with empty recipient_seat_ids
        ev_char3 = events[3]
        assert ev_char3["kind"] == "world.entry.created"
        assert ev_char3["visibility"] == "seat_private"
        assert ev_char3["recipient_seat_ids"] == []

    dm_page = fix.service.event_service.list_after(
        fix.human_dm_actor, after_seq=0, limit=10
    )
    assert len(dm_page.events) == 4

    player_page = fix.service.event_service.list_after(
        fix.human_player_1_actor, after_seq=0, limit=10
    )
    assert {event.payload["entry_id"] for event in player_page.events} == {
        str(pub_view.id),
        str(char_view.id),
    }
    assert all(
        set(event.payload) == {"entry_id", "entry_kind", "revision", "action"}
        for event in player_page.events
    )


# 5. Idempotent retry returns identical result and exactly one event/notifier
def test_idempotent_retry_behavior(fix: ActiveFixture) -> None:
    # 1. Create retry
    c_payload = RuntimeWorldEntryCreate(
        kind="npc",
        title="Mayor of Oakvale",
    )
    first_res = fix.service.create_active(
        fix.human_dm_actor,
        c_payload,
        idempotency_key="retry-mayor-1",
    )
    assert len(fix.notifier.notifications) == 1

    # Retry same command with same key
    second_res = fix.service.create_active(
        fix.human_dm_actor,
        c_payload,
        idempotency_key="retry-mayor-1",
    )
    assert second_res == first_res
    assert len(fix.notifier.notifications) == 1  # Notifier NOT called again

    # 2. Update retry
    u_patch = RuntimeWorldEntryPatch(
        expected_revision=1,
        title="Mayor of Oakvale, Senior",
    )
    first_up = fix.service.update_active(
        fix.human_dm_actor,
        first_res.id,
        u_patch,
        idempotency_key="retry-mayor-update",
    )
    assert first_up.revision == 2
    assert len(fix.notifier.notifications) == 2

    second_up = fix.service.update_active(
        fix.human_dm_actor,
        first_res.id,
        u_patch,
        idempotency_key="retry-mayor-update",
    )
    assert second_up == first_up
    assert second_up.revision == 2
    assert len(fix.notifier.notifications) == 2  # Notifier NOT called again

    # 3. Archive retry
    first_arch = fix.service.archive_active(
        fix.human_dm_actor,
        first_res.id,
        expected_revision=2,
        idempotency_key="retry-mayor-archive",
    )
    assert first_arch.revision == 3
    assert len(fix.notifier.notifications) == 3

    second_arch = fix.service.archive_active(
        fix.human_dm_actor,
        first_res.id,
        expected_revision=2,
        idempotency_key="retry-mayor-archive",
    )
    assert second_arch == first_arch
    assert second_arch.revision == 3
    assert len(fix.notifier.notifications) == 3  # Notifier NOT called again

    # Verify DB counts: exactly 1 target row in entries, 3 in mutations, 3 in events
    with fix.engine.connect() as conn:
        entry_count = conn.execute(select(func.count(campaign_world_entries.c.id))).scalar()
        assert entry_count == 1
        mutation_count = conn.execute(select(func.count(campaign_world_mutations.c.id))).scalar()
        assert mutation_count == 3
        event_count = conn.execute(select(func.count(session_events.c.id))).scalar()
        assert event_count == 3


# 6. Same key different command/actor/target/action rejects
def test_idempotency_conflict_rejections(fix: ActiveFixture) -> None:
    c_payload = RuntimeWorldEntryCreate(kind="npc", title="Guard 1")
    fix.service.create_active(
        fix.human_dm_actor,
        c_payload,
        idempotency_key="conflict-key-1",
    )

    # Same key, different title -> conflict
    with pytest.raises(CampaignRuntimeIdempotencyConflictError, match="different command"):
        fix.service.create_active(
            fix.human_dm_actor,
            RuntimeWorldEntryCreate(kind="npc", title="Guard 2"),
            idempotency_key="conflict-key-1",
        )

    # Same key, different action (update with create's key) -> conflict
    with pytest.raises(CampaignRuntimeIdempotencyConflictError, match="different command or actor"):
        fix.service.update_active(
            fix.human_dm_actor,
            uuid4(),
            RuntimeWorldEntryPatch(expected_revision=1, title="Guard Updated"),
            idempotency_key="conflict-key-1",
        )

    # Same key, different actor (new DM after handoff) -> conflict
    other_dm_access_id = uuid4()
    with fix.engine.begin() as conn:
        conn.execute(
            insert(room_access_sessions).values(
                id=other_dm_access_id,
                room_id=fix.room_id,
                authority="dm",
                token_hash=b"tok_other_dm_hash_12345678",
                display_name="Other DM",
                created_at=datetime.now(timezone.utc),
                last_seen_at=datetime.now(timezone.utc),
            )
        )
        conn.execute(
            update(campaign_seats)
            .where(campaign_seats.c.id == fix.dm_seat_id)
            .values(controller_access_session_id=other_dm_access_id)
        )
        conn.execute(
            update(sessions)
            .where(sessions.c.id == fix.session_id)
            .values(dm_controller_access_session_id=other_dm_access_id)
        )
    other_dm_actor = TableActorContext(
        actor_kind=TableActorKind.HUMAN,
        room_id=fix.room_id,
        campaign_id=fix.campaign_id,
        session_id=fix.session_id,
        seat_id=fix.dm_seat_id,
        controlled_seat_ids=(fix.dm_seat_id,),
        role="dm",
        is_current_dm=True,
        access_session_id=other_dm_access_id,
    )
    with pytest.raises(CampaignRuntimeIdempotencyConflictError, match="different command or actor"):
        fix.service.create_active(
            other_dm_actor,
            c_payload,
            idempotency_key="conflict-key-1",
        )


# 7. Stale revision and failure inside event callback roll back everything
def test_rollback_on_callback_failure(fix: ActiveFixture) -> None:
    # Create an entry
    created = fix.service.create_active(
        fix.human_dm_actor,
        RuntimeWorldEntryCreate(kind="npc", title="Tavern Keeper"),
        idempotency_key="tb-entry",
    )
    assert created.revision == 1
    notifications_before = len(fix.notifier.notifications)

    # 1. Stale revision conflict on update
    with pytest.raises(CampaignRuntimeRevisionConflictError):
        fix.service.update_active(
            fix.human_dm_actor,
            created.id,
            RuntimeWorldEntryPatch(expected_revision=99, title="Wrong Revision"),
            idempotency_key="tb-stale-rev",
        )

    # Assert title was NOT updated, no new mutation, no new event, no new notification
    with fix.engine.connect() as conn:
        entry = conn.execute(
            select(campaign_world_entries).where(campaign_world_entries.c.id == created.id)
        ).mappings().one()
        assert entry["revision"] == 1
        assert entry["title"] == "Tavern Keeper"

        mut = conn.execute(
            select(campaign_world_mutations).where(
                campaign_world_mutations.c.idempotency_key == "tb-stale-rev"
            )
        ).one_or_none()
        assert mut is None

        ev = conn.execute(
            select(session_events).where(session_events.c.idempotency_key == _ev_key("tb-stale-rev"))
        ).one_or_none()
        assert ev is None

    assert len(fix.notifier.notifications) == notifications_before

    # 2. Instrument failure raised after real target mutation inside the event callback
    original_insert = fix.service.mutation_repo.insert_in_transaction

    def exploding_insert(connection, mutation) -> None:
        if mutation.idempotency_key == "exploding-key":
            raise RuntimeError("Database catastrophe after target mutation!")
        original_insert(connection, mutation)

    fix.service.mutation_repo.insert_in_transaction = exploding_insert

    with pytest.raises(RuntimeError, match="Database catastrophe"):
        fix.service.create_active(
            fix.human_dm_actor,
            RuntimeWorldEntryCreate(kind="npc", title="Doomed NPC"),
            idempotency_key="exploding-key",
        )

    # Restore original method
    fix.service.mutation_repo.insert_in_transaction = original_insert

    # Verify atomic rollback: Doomed NPC must NOT exist in DB, no mutation, no event, no notifier
    with fix.engine.connect() as conn:
        doomed = conn.execute(
            select(campaign_world_entries).where(campaign_world_entries.c.title == "Doomed NPC")
        ).one_or_none()
        assert doomed is None

        mut = conn.execute(
            select(campaign_world_mutations).where(
                campaign_world_mutations.c.idempotency_key == "exploding-key"
            )
        ).one_or_none()
        assert mut is None

        ev = conn.execute(
            select(session_events).where(session_events.c.idempotency_key == _ev_key("exploding-key"))
        ).one_or_none()
        assert ev is None

    assert len(fix.notifier.notifications) == notifications_before


# 8. Session-outside management regression and active session block
def test_management_outside_session_regression(fix: ActiveFixture) -> None:
    # Create a separate campaign with NO active session
    empty_campaign_id = uuid4()
    now = datetime.now(timezone.utc)
    with fix.engine.begin() as conn:
        conn.execute(
            insert(campaigns).values(
                id=empty_campaign_id,
                room_id=fix.room_id,
                name="Session-free Campaign",
                ruleset="dnd-5e-2014",
                status="active",
                created_at=now,
                updated_at=now,
            )
        )

    notifications_before = len(fix.notifier.notifications)

    # Management create outside session succeeds
    created = fix.service.create_management(
        fix.owner_context,
        fix.room_id,
        empty_campaign_id,
        RuntimeWorldEntryCreate(kind="fact", body="The sun sets in the west."),
        idempotency_key="mgmt-fact-1",
    )
    assert isinstance(created, RuntimeWorldEntryDmView)
    assert created.revision == 1

    # No session event and no notifier
    assert len(fix.notifier.notifications) == notifications_before
    with fix.engine.connect() as conn:
        events = conn.execute(
            select(session_events).where(session_events.c.idempotency_key == _ev_key("mgmt-fact-1"))
        ).all()
        assert len(events) == 0

    # Management update outside session succeeds
    updated = fix.service.update_management(
        fix.owner_context,
        fix.room_id,
        empty_campaign_id,
        created.id,
        RuntimeWorldEntryPatch(expected_revision=1, body="The sun always sets in the west."),
        idempotency_key="mgmt-fact-update",
    )
    assert updated.revision == 2
    assert len(fix.notifier.notifications) == notifications_before

    # Management archive outside session succeeds
    archived = fix.service.archive_management(
        fix.owner_context,
        fix.room_id,
        empty_campaign_id,
        created.id,
        expected_revision=2,
        idempotency_key="mgmt-fact-archive",
    )
    assert archived.revision == 3
    assert archived.archived_at is not None
    assert len(fix.notifier.notifications) == notifications_before


# 9. 160-character idempotency key and replay
def test_160_character_idempotency_key_and_replay(fix: ActiveFixture) -> None:
    key_160 = "k" * 160
    c_payload = RuntimeWorldEntryCreate(kind="npc", title="160 Char NPC")
    view = fix.service.create_active(
        fix.human_dm_actor,
        c_payload,
        idempotency_key=key_160,
    )
    assert view.title == "160 Char NPC"
    notifications_before = len(fix.notifier.notifications)

    # Verify campaign mutation stores the exact original 160-char key
    with fix.engine.connect() as conn:
        mut = conn.execute(
            select(campaign_world_mutations).where(
                campaign_world_mutations.c.campaign_id == fix.campaign_id,
                campaign_world_mutations.c.idempotency_key == key_160,
            )
        ).mappings().one()
        assert mut["idempotency_key"] == key_160

        # Verify session event stores the namespaced fixed-length sha256 digest <= 160 chars
        ev_key = _ev_key(key_160)
        assert len(ev_key) <= 160
        ev = conn.execute(
            select(session_events).where(
                session_events.c.session_id == fix.session_id,
                session_events.c.idempotency_key == ev_key,
            )
        ).mappings().one()
        assert ev["idempotency_key"] == ev_key

    # Replay with the same 160-char key returns stored result without appending duplicate event
    replay_view = fix.service.create_active(
        fix.human_dm_actor,
        c_payload,
        idempotency_key=key_160,
    )
    assert replay_view.id == view.id
    assert replay_view.revision == view.revision

    # Event count in session_events remains exactly 1 and no notification sent on replay
    with fix.engine.connect() as conn:
        ev_count = conn.execute(
            select(func.count(session_events.c.id)).where(
                session_events.c.session_id == fix.session_id,
                session_events.c.idempotency_key == ev_key,
            )
        ).scalar()
        assert ev_count == 1
    assert len(fix.notifier.notifications) == notifications_before


# 10. Cross-session committed replay with same Human actor
def test_cross_session_committed_replay(fix: ActiveFixture) -> None:
    # 1. Create entry in Session 1
    c_payload = RuntimeWorldEntryCreate(kind="fact", body="The tower stands on the cliff.")
    view1 = fix.service.create_active(
        fix.human_dm_actor,
        c_payload,
        idempotency_key="cross-session-key-1",
    )
    assert view1.body == "The tower stands on the cliff."
    session_1_notifications = len(fix.notifier.notifications)

    # 2. End Session 1 and start Session 2 in the same campaign with the same Human DM
    session_2_id = uuid4()
    now = datetime.now(timezone.utc)
    with fix.engine.begin() as conn:
        conn.execute(
            update(sessions)
            .where(sessions.c.id == fix.session_id)
            .values(status="ended", ended_at=now)
        )
        conn.execute(
            insert(sessions).values(
                id=session_2_id,
                campaign_id=fix.campaign_id,
                status="active",
                dm_seat_id=fix.dm_seat_id,
                dm_controller_kind="human",
                dm_controller_access_session_id=fix.human_dm_access_id,
                started_at=now,
                created_at=now,
            )
        )
        conn.execute(
            insert(session_participants).values(
                id=uuid4(),
                session_id=session_2_id,
                seat_id=fix.dm_seat_id,
                role_snapshot="dm",
                controller_kind_at_join="human",
                controller_access_session_id_at_join=fix.human_dm_access_id,
                controller_ai_grant_id_at_join=None,
                controller_generation_at_join=None,
                active_character_id=None,
                joined_at=now,
            )
        )

    human_dm_session_2_actor = fix.service.event_service.resolve_human_actor(
        room_id=fix.room_id,
        campaign_id=fix.campaign_id,
        session_id=session_2_id,
        context=RoomAccessContext(
            room_id=fix.room_id,
            access_session_id=fix.human_dm_access_id,
            authority=RoomAccessAuthority.DM,
            display_name="Human DM",
        ),
    )

    # 3. Same Human actor + campaign mutation key in Session 2 returns stored result
    replay_view = fix.service.create_active(
        human_dm_session_2_actor,
        c_payload,
        idempotency_key="cross-session-key-1",
    )
    assert replay_view.id == view1.id
    assert replay_view.revision == view1.revision

    # No new event in Session 2 and no notification for Session 2
    with fix.engine.connect() as conn:
        s2_events = conn.execute(
            select(session_events).where(session_events.c.session_id == session_2_id)
        ).all()
        assert len(s2_events) == 0
    assert len(fix.notifier.notifications) == session_1_notifications

    # 4. Pre-check revalidates active actor even on replay: ended session is rejected
    with fix.engine.begin() as conn:
        conn.execute(
            update(sessions).where(sessions.c.id == session_2_id).values(status="ended", ended_at=now)
        )

    with pytest.raises(CampaignRuntimeSessionNotActiveError, match="is not active"):
        fix.service.create_active(
            human_dm_session_2_actor,
            c_payload,
            idempotency_key="cross-session-key-1",
        )
