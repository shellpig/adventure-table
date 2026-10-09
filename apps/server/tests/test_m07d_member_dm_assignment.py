"""M07-D D2b (F14 backend blocker): member-authority Human as current DM.

User decision (2026-10-04, recorded in the M07-D handoff): a Human current DM
who holds only member Room authority must be constructible through the real
Owner-assignment workflow, may read the session libraries read-only, and still
cannot author Room libraries. Owner-only DM assignment and no mid-session DM
switch remain.

The Seat gameplay role (DM Seat controller) was confused with the target's
Room authority: ``SeatService.set_controller`` rejected member access sessions
for DM Seats, and ``start_from_lobby`` additionally required dm/owner caller
authority, so the decided flow was unreachable. These tests prove the full
real lifecycle and pin the preserved rejections.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, update
from sqlalchemy.pool import StaticPool

from app.content import load_default_content_registry
from app.content.localization_files import load_content_localization_catalog
from app.content.registry import resolve_content_root
from app.db import metadata
from app.domain.battle_maps.schemas import BattleMapCreate, BattleMapForbiddenError
from app.domain.battle_maps.service import BattleMapService
from app.domain.character.fixture import (
    build_p0_fighter_wizard_fixture,
    build_p0_fighter_wizard_state,
)
from app.domain.monster_library.errors import MonsterLibraryForbiddenError
from app.domain.monster_library.schemas import CreateCustomMonsterFromContentInput
from app.domain.monster_library.service import MonsterLibraryService
from app.domain.rooms.campaigns import (
    CampaignCreate,
    CampaignService,
    CampaignStatus,
    RosterAdd,
)
from app.domain.rooms.schemas import CreateRoomRequest, EnterRoomRequest
from app.domain.rooms.seats import (
    ControllerKind,
    SeatControllerError,
    SeatControllerPatch,
    SeatCreate,
    SeatRole,
    SeatService,
)
from app.domain.rooms.service import RoomService
from app.domain.rooms.sessions import (
    DMControllerMismatchError,
    SessionService,
    SessionStatus,
)
from app.domain.rooms.table_events import (
    TableActorContext,
    TableEventActorUnauthorizedError,
    TableEventService,
)
from app.persistence.battle_maps.repository import BattleMapRepository
from app.persistence.characters import CharacterRepository
from app.persistence.combat.repository import MonsterRepository
from app.persistence.monster_library.repository import MonsterLibraryRepository
from app.persistence.room_assets.repository import RoomAssetRepository
from app.persistence.rooms.campaigns import CampaignRepository
from app.persistence.rooms.repository import RoomRepository
from app.persistence.rooms.seats import SeatRepository
from app.persistence.rooms.sessions import SessionRepository
from app.persistence.rooms.table_runtime import TableEventRepository
from app.persistence.rooms.tables import room_access_sessions
from app.persistence.rooms.workspace import RoomWorkspaceRepository

GOBLIN_KEY = "srd5.1:monster:goblin"


def _engine():
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


class _MemberDmTable:
    """Room with a member-authority Human assigned (by Owner workflow) to the DM Seat."""

    def __init__(self) -> None:
        self.engine = _engine()
        registry = load_default_content_registry()
        self.registry = registry
        rooms = RoomService(RoomRepository(self.engine))
        self.rooms = rooms
        self.owner = rooms.create_room(
            CreateRoomRequest(name="M07-D member DM", password="secret", display_name="Owner")
        )
        assert self.owner.authority == "owner"
        self.member_dm = rooms.enter_room(
            EnterRoomRequest(
                code=self.owner.room.code,
                password="secret",
                display_name="Member DM",
            ),
            remote_addr="127.0.0.2",
        )
        assert self.member_dm.authority == "member"
        self.watcher = rooms.enter_room(
            EnterRoomRequest(
                code=self.owner.room.code,
                password="secret",
                display_name="Watcher",
            ),
            remote_addr="127.0.0.3",
        )
        assert self.watcher.authority == "member"

        build = build_p0_fighter_wizard_fixture()
        characters = CharacterRepository(self.engine, registry)
        character = characters.create_character(
            name="Mira",
            build=build,
            state=build_p0_fighter_wizard_state(build),
        )
        self.character_id = character.id
        RoomWorkspaceRepository(self.engine).attach_character(
            room_id=self.owner.room.id, character_id=character.id
        )

        campaigns = CampaignService(CampaignRepository(self.engine))
        campaign = campaigns.create_campaign(
            self.owner.room.id,
            CampaignCreate(name="Campaign", ruleset="dnd5e-2014"),
        )
        campaigns.set_status(self.owner.room.id, campaign.id, CampaignStatus.ACTIVE)
        campaigns.select_campaign(self.owner.room.id, campaign.id)
        campaigns.add_character(
            self.owner.room.id, campaign.id, RosterAdd(character_id=character.id)
        )
        self.campaign_id = campaign.id

        self.seats = SeatService(SeatRepository(self.engine))
        self.dm_seat = self.seats.create_seat(
            self.owner.room.id, campaign.id, SeatCreate(role=SeatRole.DM)
        )
        player_seat = self.seats.create_seat(
            self.owner.room.id, campaign.id, SeatCreate(role=SeatRole.PLAYER)
        )
        self.seats.set_controller(
            self.owner.room.id,
            campaign.id,
            player_seat.id,
            SeatControllerPatch(
                controller_kind=ControllerKind.HUMAN,
                controller_access_session_id=self.watcher.access_session_id,
            ),
        )
        self.seats.select_character(
            self.owner.room.id, campaign.id, player_seat.id, character.id
        )

        self.events = TableEventService(TableEventRepository(self.engine))
        self.sessions = SessionService(
            SessionRepository(self.engine), event_service=self.events
        )
        localization = load_content_localization_catalog(registry, resolve_content_root())
        self.battle_maps = BattleMapService(
            BattleMapRepository(self.engine),
            RoomAssetRepository(self.engine),
            self.events,
            content_registry=registry,
        )
        self.library = MonsterLibraryService(
            self.engine,
            MonsterLibraryRepository(self.engine),
            MonsterRepository(self.engine),
            registry,
            localization,
            self.events,
        )

    def owner_context(self):
        return self.rooms.authenticate(self.owner.room.id, self.owner.access_token)

    def member_dm_context(self):
        return self.rooms.authenticate(self.owner.room.id, self.member_dm.access_token)

    def watcher_context(self):
        return self.rooms.authenticate(self.owner.room.id, self.watcher.access_token)

    def assign_member_to_dm_seat(self):
        return self.seats.set_controller(
            self.owner.room.id,
            self.campaign_id,
            self.dm_seat.id,
            SeatControllerPatch(
                controller_kind=ControllerKind.HUMAN,
                controller_access_session_id=self.member_dm.access_session_id,
            ),
        )

    def resolve_actor(self, context) -> TableActorContext:
        return self.events.resolve_human_actor(
            room_id=self.owner.room.id,
            campaign_id=self.campaign_id,
            session_id=self.session_id,
            context=context,
        )


def test_owner_can_assign_active_same_room_member_to_dm_seat() -> None:
    table = _MemberDmTable()
    try:
        bound = table.assign_member_to_dm_seat()
        assert bound.controller_kind is ControllerKind.HUMAN
        assert bound.controller_access_session_id == table.member_dm.access_session_id
        assert bound.controller_authority is not None
        assert bound.controller_authority.value == "member"
    finally:
        table.engine.dispose()


def test_member_dm_starts_session_and_reads_libraries_but_cannot_author() -> None:
    table = _MemberDmTable()
    try:
        table.assign_member_to_dm_seat()
        started = table.sessions.start_session(
            table.owner.room.id, table.campaign_id, table.member_dm_context()
        )
        assert started.dm_controller_access_session_id == table.member_dm.access_session_id
        table.session_id = started.id

        owner_ctx = table.owner_context()
        created_map = table.battle_maps.create(
            owner_ctx,
            room_id=table.owner.room.id,
            payload=BattleMapCreate(
                name="Member DM Map", source_kind="blank", width_cells=12, height_cells=10
            ),
        )
        custom = table.library.create_from_content(
            owner_ctx,
            table.owner.room.id,
            CreateCustomMonsterFromContentInput(content_key=GOBLIN_KEY),
        )

        actor = table.resolve_actor(table.member_dm_context())
        assert actor.role == "dm" and actor.is_current_dm

        maps = table.battle_maps.list_for_actor(actor)
        assert str(created_map.id) in {str(item.id) for item in maps}
        single_map = table.battle_maps.get_for_actor(actor, created_map.id)
        assert single_map.id == created_map.id

        entries = table.library.list_for_actor(
            actor, table.owner.room.id, query="goblin", source="custom"
        )
        assert custom.ref in {item.ref for item in entries}
        detail = table.library.get_for_actor(actor, table.owner.room.id, ref=custom.ref)
        assert detail.ref == custom.ref
        builtin = table.library.get_for_actor(actor, table.owner.room.id, ref=GOBLIN_KEY)
        assert builtin.source_kind == "builtin"

        # Room authority is NOT promoted: management reads still forbid members.
        member_ctx = table.member_dm_context()
        with pytest.raises(MonsterLibraryForbiddenError):
            table.library.list(member_ctx, table.owner.room.id)
        with pytest.raises(MonsterLibraryForbiddenError):
            table.library.get(member_ctx, table.owner.room.id, custom.ref)
        with pytest.raises(BattleMapForbiddenError):
            table.battle_maps.list(member_ctx, table.owner.room.id)
        with pytest.raises(BattleMapForbiddenError):
            table.battle_maps.get(member_ctx, table.owner.room.id, created_map.id)
    finally:
        table.engine.dispose()


def test_player_seat_member_cannot_read_session_libraries() -> None:
    table = _MemberDmTable()
    try:
        table.assign_member_to_dm_seat()
        started = table.sessions.start_session(
            table.owner.room.id, table.campaign_id, table.member_dm_context()
        )
        table.session_id = started.id
        owner_ctx = table.owner_context()
        created_map = table.battle_maps.create(
            owner_ctx,
            room_id=table.owner.room.id,
            payload=BattleMapCreate(
                name="Member DM Map", source_kind="blank", width_cells=12, height_cells=10
            ),
        )
        player_actor = table.resolve_actor(table.watcher_context())
        assert not player_actor.is_current_dm
        with pytest.raises(TableEventActorUnauthorizedError):
            table.battle_maps.list_for_actor(player_actor)
        with pytest.raises(TableEventActorUnauthorizedError):
            table.battle_maps.get_for_actor(player_actor, created_map.id)
        with pytest.raises(TableEventActorUnauthorizedError):
            table.library.list_for_actor(player_actor, table.owner.room.id)
        with pytest.raises(TableEventActorUnauthorizedError):
            table.library.get_for_actor(player_actor, table.owner.room.id, ref=GOBLIN_KEY)
    finally:
        table.engine.dispose()


def test_dm_seat_assignment_still_rejects_invalid_cross_room_revoked() -> None:
    table = _MemberDmTable()
    try:
        with pytest.raises(SeatControllerError):
            table.seats.set_controller(
                table.owner.room.id,
                table.campaign_id,
                table.dm_seat.id,
                SeatControllerPatch(
                    controller_kind=ControllerKind.HUMAN,
                    controller_access_session_id=uuid4(),
                ),
            )
        other_room = table.rooms.create_room(
            CreateRoomRequest(name="Other", password="secret", display_name="Other Owner")
        )
        other_member = table.rooms.enter_room(
            EnterRoomRequest(
                code=other_room.room.code, password="secret", display_name="Other Member"
            ),
            remote_addr="127.0.0.9",
        )
        with pytest.raises(SeatControllerError):
            table.seats.set_controller(
                table.owner.room.id,
                table.campaign_id,
                table.dm_seat.id,
                SeatControllerPatch(
                    controller_kind=ControllerKind.HUMAN,
                    controller_access_session_id=other_member.access_session_id,
                ),
            )
        with table.engine.begin() as connection:
            connection.execute(
                update(room_access_sessions)
                .where(room_access_sessions.c.id == table.member_dm.access_session_id)
                .values(revoked_at=datetime.now(timezone.utc))
            )
        with pytest.raises(SeatControllerError):
            table.assign_member_to_dm_seat()
    finally:
        table.engine.dispose()


def test_dm_controller_fixed_while_session_active_and_non_controller_cannot_start() -> None:
    table = _MemberDmTable()
    try:
        table.assign_member_to_dm_seat()
        started = table.sessions.start_session(
            table.owner.room.id, table.campaign_id, table.member_dm_context()
        )
        assert started.status is SessionStatus.ACTIVE
        with pytest.raises(SeatControllerError):
            table.seats.set_controller(
                table.owner.room.id,
                table.campaign_id,
                table.dm_seat.id,
                SeatControllerPatch(
                    controller_kind=ControllerKind.HUMAN,
                    controller_access_session_id=table.owner.access_session_id,
                ),
            )
        ended = table.sessions.end_session(
            table.owner.room.id, table.campaign_id, started.id, table.member_dm_context()
        )
        assert ended.status is SessionStatus.ENDED
        with pytest.raises(DMControllerMismatchError):
            table.sessions.start_session(
                table.owner.room.id, table.campaign_id, table.watcher_context()
            )
        with pytest.raises(DMControllerMismatchError):
            table.sessions.start_session(
                table.owner.room.id, table.campaign_id, table.owner_context()
            )
        # After End the Owner-assigned member DM can start the next Session.
        restarted = table.sessions.start_session(
            table.owner.room.id, table.campaign_id, table.member_dm_context()
        )
        assert restarted.status is SessionStatus.ACTIVE
    finally:
        table.engine.dispose()
