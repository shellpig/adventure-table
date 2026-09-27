"""Shared P5-A tactical test fixture: room/campaign/seats/session + combat + board."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import create_engine, insert
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from app.content import load_default_content_registry
from app.db import metadata
from app.domain.character.fixture import (
    build_p0_fighter_wizard_fixture,
    build_p0_fighter_wizard_state,
)
from app.domain.combat.board import CombatBoardService
from app.domain.combat.lifecycle import CombatService
from app.domain.room_assets.service import RoomAssetService
from app.persistence.room_assets.storage import FilesystemAssetStorage
from app.domain.rooms.campaigns import CampaignCreate, CampaignService, CampaignStatus, RosterAdd
from app.domain.rooms.schemas import CreateRoomRequest, EnterRoomRequest
from app.domain.rooms.seats import (
    ControllerKind,
    SeatControllerPatch,
    SeatCreate,
    SeatRole,
    SeatService,
)
from app.domain.rooms.service import RoomService
from app.domain.rooms.sessions import SessionService
from app.domain.rooms.table_events import TableActorContext, TableEventService
from app.persistence.battle_maps.repository import BattleMapRepository
from app.persistence.battle_maps.tables import battle_map_doors, battle_map_walls, battle_maps
from app.persistence.characters import CharacterRepository
from app.persistence.combat.lifecycle import CombatRepository
from app.persistence.combat.repository import MonsterRepository
from app.persistence.combat_boards.repository import CombatBoardRepository
from app.persistence.room_assets.repository import RoomAssetRepository
from app.persistence.rooms.campaigns import CampaignRepository
from app.persistence.rooms.repository import RoomRepository
from app.persistence.rooms.seats import SeatRepository
from app.persistence.rooms.sessions import SessionRepository
from app.persistence.rooms.table_runtime import TableEventRepository
from app.persistence.rooms.workspace import RoomWorkspaceRepository


@dataclass
class TacticalTable:
    engine: Engine
    room_id: UUID
    campaign_id: UUID
    character_id: UUID
    session_id: UUID
    dm_actor: TableActorContext
    player_actor: TableActorContext
    events: TableEventService
    combat: CombatService
    board: CombatBoardService
    battle_maps: BattleMapRepository
    characters: object | None = None
    registry: object | None = None


def setup_tactical_table() -> TacticalTable:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata.create_all(engine)
    registry = load_default_content_registry()

    rooms = RoomService(RoomRepository(engine))
    owner = rooms.create_room(
        CreateRoomRequest(name="P5-A", password="secret", display_name="Player")
    )
    dm = rooms.enter_room(
        EnterRoomRequest(
            code=owner.room.code,
            password="secret",
            elevated_key=owner.dm_key,
            display_name="DM",
        ),
        remote_addr="127.0.0.2",
    )

    characters = CharacterRepository(engine, registry)
    build = build_p0_fighter_wizard_fixture()
    character = characters.create_character(
        name="Mira",
        build=build,
        state=build_p0_fighter_wizard_state(build),
    )
    RoomWorkspaceRepository(engine).attach_character(
        room_id=owner.room.id, character_id=character.id
    )

    campaigns = CampaignService(CampaignRepository(engine))
    campaign = campaigns.create_campaign(
        owner.room.id, CampaignCreate(name="Campaign", ruleset="dnd5e-2014")
    )
    campaigns.set_status(owner.room.id, campaign.id, CampaignStatus.ACTIVE)
    campaigns.select_campaign(owner.room.id, campaign.id)
    campaigns.add_character(
        owner.room.id, campaign.id, RosterAdd(character_id=character.id)
    )

    seats = SeatService(SeatRepository(engine))
    dm_seat = seats.create_seat(
        owner.room.id, campaign.id, SeatCreate(role=SeatRole.DM, label="DM")
    )
    seats.set_controller(
        owner.room.id, campaign.id, dm_seat.id,
        SeatControllerPatch(
            controller_kind=ControllerKind.HUMAN,
            controller_access_session_id=dm.access_session_id,
        ),
    )
    player_seat = seats.create_seat(
        owner.room.id, campaign.id, SeatCreate(role=SeatRole.PLAYER, label="Player")
    )
    seats.set_controller(
        owner.room.id, campaign.id, player_seat.id,
        SeatControllerPatch(
            controller_kind=ControllerKind.HUMAN,
            controller_access_session_id=owner.access_session_id,
        ),
    )
    seats.select_character(owner.room.id, campaign.id, player_seat.id, character.id)

    dm_context = rooms.authenticate(owner.room.id, dm.access_token)
    player_context = rooms.authenticate(owner.room.id, owner.access_token)
    events = TableEventService(TableEventRepository(engine))
    sessions = SessionService(SessionRepository(engine), event_service=events)
    started = sessions.start_session(owner.room.id, campaign.id, dm_context)

    combat_repository = CombatRepository(engine, events.repository)
    monsters = MonsterRepository(engine)

    # Mirror production wiring (app/api/rooms/dependencies.py): Player-facing
    # event payloads never leak hidden Monster combatants.
    def hidden_combat_entry_ids(campaign_id: UUID) -> frozenset[str]:
        combat = combat_repository.get_active(campaign_id)
        if combat is None:
            return frozenset()
        hidden: set[str] = set()
        for entry in combat_repository.list_entries(combat.id):
            if entry.subject_kind != "monster" or entry.monster_instance_id is None:
                continue
            instance = monsters.get_instance(entry.monster_instance_id)
            if instance is not None and instance.visibility == "hidden":
                hidden.add(str(entry.id))
                hidden.add(str(entry.monster_instance_id))
        return frozenset(hidden)

    events.hidden_combat_entry_ids = hidden_combat_entry_ids
    battle_map_repository = BattleMapRepository(engine)
    board_repository = CombatBoardRepository(engine, events.repository)
    combat = CombatService(
        combat_repository, events, characters, monsters, registry,
        battle_map_repository=battle_map_repository,
        board_repository=board_repository,
    )
    asset_service = RoomAssetService(
        RoomAssetRepository(engine),
        FilesystemAssetStorage(Path(tempfile.mkdtemp(prefix="p5a-assets-"))),
        max_image_bytes=20 * 1024 * 1024,
        max_source_document_bytes=20 * 1024 * 1024,
    )
    board = CombatBoardService(
        board_repository=board_repository,
        combat_service=combat,
        room_asset_service=asset_service,
        table_event_service=events,
    )

    def actor(context: object) -> TableActorContext:
        return events.resolve_human_actor(
            room_id=owner.room.id, campaign_id=campaign.id,
            session_id=started.id, context=context,
        )

    return TacticalTable(
        engine=engine, room_id=owner.room.id, campaign_id=campaign.id,
        character_id=character.id, session_id=started.id,
        dm_actor=actor(dm_context), player_actor=actor(player_context),
        events=events, combat=combat, board=board,
        battle_maps=battle_map_repository,
        characters=characters, registry=registry,
    )


def insert_battle_map(table: TacticalTable) -> UUID:
    map_id = uuid4()
    now = datetime.now(timezone.utc)
    with table.engine.begin() as conn:
        conn.execute(insert(battle_maps).values(
            id=map_id, room_id=table.room_id, name="Dungeon",
            source_kind="blank", image_asset_id=None,
            width_cells=20, height_cells=15,
            grid_pixel_size=None, grid_offset_x=None, grid_offset_y=None,
            revision=3, created_at=now, updated_at=now,
        ))
        conn.execute(insert(battle_map_walls).values(
            id=uuid4(), battle_map_id=map_id,
            x1=0, y1=0, x2=5, y2=0, visibility="public",
        ))
        conn.execute(insert(battle_map_walls).values(
            id=uuid4(), battle_map_id=map_id,
            x1=10, y1=10, x2=12, y2=10, visibility="hidden",
        ))
        conn.execute(insert(battle_map_doors).values(
            id=uuid4(), battle_map_id=map_id,
            x1=5, y1=0, x2=6, y2=0,
            default_state="closed", visibility="hidden",
        ))
    return map_id

