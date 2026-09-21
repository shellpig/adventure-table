from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, event, func, insert, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from app.db import metadata
from app.domain.campaign_runtime import (
    CampaignAdventureOverrideCreate,
    CampaignRuntimeAuthorityError,
    CampaignRuntimeContextPatch,
    CampaignRuntimeNotFoundError,
    CampaignRuntimeService,
    CampaignRuntimeSessionNotActiveError,
    RuntimeWorldEntryCreate,
)
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.table_events import (
    TableActorContext,
    TableEventService,
)
from app.persistence.adventures.tables import (
    adventure_definitions,
    adventure_entries,
    campaign_adventure_links,
)
from app.persistence.campaign_runtime.tables import (
    campaign_adventure_overrides,
    campaign_runtime_context,
    campaign_world_entries,
    campaign_world_mutations,
)
from app.persistence.characters import characters
from app.persistence.rooms.table_runtime import TableEventRepository
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


def _scan_str(obj: object, target: str) -> bool:
    if isinstance(obj, str):
        return target in obj
    if isinstance(obj, dict):
        return any(_scan_str(k, target) or _scan_str(v, target) for k, v in obj.items())
    if isinstance(obj, (list, tuple, set)):
        return any(_scan_str(item, target) for item in obj)
    return False


def _snapshot(engine: Engine, campaign_id: UUID) -> dict[str, int]:
    with engine.connect() as conn:
        return {
            "entries": conn.scalar(
                select(func.count()).select_from(campaign_world_entries).where(
                    campaign_world_entries.c.campaign_id == campaign_id
                )
            ) or 0,
            "mutations": conn.scalar(
                select(func.count()).select_from(campaign_world_mutations).where(
                    campaign_world_mutations.c.campaign_id == campaign_id
                )
            ) or 0,
            "overrides": conn.scalar(
                select(func.count()).select_from(campaign_adventure_overrides).where(
                    campaign_adventure_overrides.c.campaign_id == campaign_id
                )
            ) or 0,
            "contexts": conn.scalar(
                select(func.count()).select_from(campaign_runtime_context).where(
                    campaign_runtime_context.c.campaign_id == campaign_id
                )
            ) or 0,
        }


def _build_active_fixture() -> ActiveFixture:
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


@pytest.fixture
def active_fix() -> ActiveFixture:
    return _build_active_fixture()


def _seed_context_fixture(base_fix: ActiveFixture) -> ActiveFixture:
    now = datetime.now(timezone.utc)
    # Attach adventure and link to ai_campaign_id for DM parity
    with base_fix.engine.begin() as conn:
        adv_def_id = conn.scalar(
            select(adventure_entries.c.adventure_id).where(
                adventure_entries.c.id == base_fix.adv_entry_id
            )
        )
        assert adv_def_id is not None
        conn.execute(
            insert(campaign_adventure_links).values(
                campaign_id=base_fix.ai_campaign_id,
                adventure_id=adv_def_id,
                sort_order=0,
                attached_at=now,
            )
        )

    # Seed override, runtime scene, dm-only secret, char-only fact, related item, context
    base_fix.service.create_override_active(
        base_fix.human_dm_actor,
        CampaignAdventureOverrideCreate(
            adventure_entry_id=base_fix.adv_entry_id,
            state={"dm_summary": "The scene has been cleared."},
            note="Override note",
        ),
        idempotency_key="seed-override",
    )
    base_fix.service.create_active(
        base_fix.human_dm_actor,
        RuntimeWorldEntryCreate(
            kind="scene",
            title="Runtime Inn",
            body="A noisy tavern.",
            visibility="public",
        ),
        idempotency_key="seed-rt-scene",
    )
    base_fix.service.create_active(
        base_fix.human_dm_actor,
        RuntimeWorldEntryCreate(
            kind="secret",
            title="Secret Room",
            body="Behind the chimney.",
            visibility="dm_only",
            dm_notes="DC 15 trap",
        ),
        idempotency_key="seed-secret",
    )
    base_fix.service.create_active(
        base_fix.human_dm_actor,
        RuntimeWorldEntryCreate(
            kind="fact",
            body="Player 1 secret heritage.",
            visibility="character",
            character_recipient_ids=(base_fix.char_1_id,),
        ),
        idempotency_key="seed-fact",
    )
    base_fix.service.create_active(
        base_fix.human_dm_actor,
        RuntimeWorldEntryCreate(
            kind="item",
            title="Relic Blade",
            visibility="public",
            state={
                "kind": "item",
                "holder_ref": {"kind": "party"},
            },
            source_adventure_entry_id=base_fix.adv_entry_id,
        ),
        idempotency_key="seed-item",
    )
    base_fix.service.update_context_active(
        base_fix.human_dm_actor,
        CampaignRuntimeContextPatch(
            expected_revision=0,
            current_adventure_scene_entry_id=base_fix.adv_entry_id,
            current_situation="Party rests at the entrance.",
        ),
        idempotency_key="seed-context",
    )
    # Mirror context to AI DM campaign
    base_fix.service.create_override_active(
        base_fix.ai_dm_actor,
        CampaignAdventureOverrideCreate(
            adventure_entry_id=base_fix.adv_entry_id,
            state={"dm_summary": "The scene has been cleared."},
            note="Override note",
        ),
        idempotency_key="ai-seed-override",
    )
    base_fix.service.update_context_active(
        base_fix.ai_dm_actor,
        CampaignRuntimeContextPatch(
            expected_revision=0,
            current_adventure_scene_entry_id=base_fix.adv_entry_id,
            current_situation="Party rests at the entrance.",
        ),
        idempotency_key="ai-seed-context",
    )
    return base_fix


@pytest.fixture
def context_seeded_fix() -> ActiveFixture:
    return _seed_context_fixture(_build_active_fixture())


def setup_authority_failure_actor(
    fix: ActiveFixture, failure_kind: str
) -> tuple[TableActorContext, tuple[type[Exception], ...]]:
    now = datetime.now(timezone.utc)
    if failure_kind == "inactive_session":
        actor = TableActorContext(
            actor_kind=fix.human_dm_actor.actor_kind,
            room_id=fix.room_id,
            campaign_id=fix.campaign_id,
            session_id=fix.inactive_session_id,
            seat_id=fix.dm_seat_id,
            controlled_seat_ids=(fix.dm_seat_id,),
            role="dm",
            is_current_dm=True,
            access_session_id=fix.human_dm_access_id,
        )
        return actor, (CampaignRuntimeSessionNotActiveError, CampaignRuntimeNotFoundError)
    if failure_kind == "revoked_human":
        with fix.engine.begin() as conn:
            conn.execute(
                update(room_access_sessions)
                .where(room_access_sessions.c.id == fix.human_dm_access_id)
                .values(revoked_at=now)
            )
        return fix.human_dm_actor, (CampaignRuntimeAuthorityError,)
    if failure_kind == "revoked_ai":
        with fix.engine.begin() as conn:
            conn.execute(
                update(ai_controller_grants)
                .where(ai_controller_grants.c.id == fix.ai_dm_grant_id)
                .values(status="revoked", revoked_at=now)
            )
        return fix.ai_dm_actor, (CampaignRuntimeAuthorityError,)
    raise ValueError(f"Unknown failure kind: {failure_kind}")
