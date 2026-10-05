"""M07-D D.1: cross-integration journeys on real PostgreSQL.

Backend half of D.1 (the browser journey ``m07d-library-journey.spec.ts`` is
the commander's). Built on the formal application services over true PG --
``xdist_group("postgres")`` -- covering the D.1 elements that no earlier node
proves end to end:

- two Rooms: library/map/placement scope isolation;
- one Room with two Campaigns: shared library, independent runtime
  (Instances, Combat boards, HP, resources), template edits apply to new
  loads while live snapshots stay frozen;
- Session End -> new Session continues the same Combat (entries, positions,
  pending initiative state) and a service/DB reconnect (restart) keeps
  everything;
- Quick / empty map / zero Adventure / optional Scene stay legal;
- Player/AI Player rejections have zero side effects;
- Room hard delete clears the whole M07 graph.

Deliberately not recreated here (cited nodes cover them):
``test_m07c_combat_load.py`` (load happy path, batch rejection, retry),
``test_m07c_secrecy.py`` / ``test_m07d_secrecy.py`` (hidden projection),
``test_m07d_session_libraries.py`` (Session library read boundary),
``test_m07*_postgres_race.py`` (load vs edit/archive/delete races).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from uuid import UUID

from alembic import command
import pytest
from sqlalchemy import create_engine, func, select, text, update
from sqlalchemy.engine import Engine

from app.content import ContentRegistry, load_default_content_registry
from app.content.localization_files import load_content_localization_catalog
from app.content.registry import resolve_content_root
from app.domain.battle_maps.schemas import (
    BattleMapCreate,
    BattleMapForbiddenError,
    BattleMapNotFoundError,
    MonsterPlacementInput,
    MonsterPlacementsReplace,
)
from app.domain.battle_maps.service import BattleMapService
from app.domain.combat.board import CombatBoardService, PlaceCombatantInput
from app.domain.combat.lifecycle import (
    CombatService,
    StartCombatInput,
    StartTacticalCombatInput,
)
from app.domain.monster_library.errors import MonsterTemplateNotFoundError
from app.domain.monster_library.schemas import (
    CreateCustomMonsterInput,
    PatchCustomMonsterInput,
)
from app.domain.monster_library.service import MonsterLibraryService
from app.domain.rooms.ai_controllers import AIControllerService, AIHandoffRequest
from app.domain.rooms.schemas import (
    CreateRoomRequest,
    EnterRoomRequest,
    RoomAccessAuthority,
    RoomAccessContext,
    RoomAccessGrant,
)
from app.domain.rooms.table_events import (
    TableActorContext,
    TableEventActorUnauthorizedError,
    TableEventService,
)
from app.domain.character.fixture import (
    build_p0_fighter_wizard_fixture,
    build_p0_fighter_wizard_state,
)
from app.domain.rooms.campaigns import (
    CampaignCreate,
    CampaignService,
    CampaignStatus,
    RosterAdd,
)
from app.domain.rooms.seats import (
    ControllerKind,
    SeatControllerPatch,
    SeatCreate,
    SeatRole,
    SeatService,
)
from app.domain.rooms.service import RoomService
from app.domain.rooms.sessions import SessionService
from app.persistence.battle_maps.repository import BattleMapRepository
from app.persistence.battle_maps.tables import battle_map_monster_placements, battle_maps
from app.persistence.characters import CharacterRepository
from app.persistence.combat.tables import (
    combat_entries,
    combats,
    monster_instances,
    monster_templates,
)
from app.persistence.combat.repository import MonsterRepository
from app.persistence.combat_boards.tables import combat_boards, combat_positions
from app.persistence.monster_library.repository import MonsterLibraryRepository
from app.persistence.room_assets.repository import RoomAssetRepository
from app.persistence.rooms.ai_controllers import AIControllerGrantRepository
from app.persistence.rooms.campaigns import CampaignRepository
from app.persistence.rooms.repository import RoomRepository
from app.persistence.rooms.seats import SeatRepository
from app.persistence.rooms.session_live import SessionLiveRepository
from app.persistence.rooms.sessions import SessionRepository
from app.persistence.rooms.table_runtime import TableEventRepository, session_events
from app.persistence.rooms.workspace import RoomWorkspaceRepository
from tests.p5a_tactical_helpers import wire_tactical_services
from tests.test_p5a_postgres_migration import POSTGRES_URL, _config, _reset

pytestmark = [
    pytest.mark.xdist_group("postgres"),
    pytest.mark.skipif(not POSTGRES_URL, reason="P4_POSTGRES_URL is only supplied by the PostgreSQL job"),
]

GOBLIN_KEY = "srd5.1:monster:goblin"


@pytest.fixture(autouse=True)
def _restore_pg_heads() -> Iterator[None]:
    try:
        yield
    finally:
        _reset()
        command.upgrade(_config(), "heads")


@dataclass
class CampaignWorld:
    campaign_id: UUID
    session_id: UUID
    dm_actor: TableActorContext
    player_actor: TableActorContext
    dm_context: RoomAccessContext
    combat: CombatService
    board: CombatBoardService


@dataclass
class JourneyWorld:
    engine: Engine
    registry: ContentRegistry
    room_a_id: UUID
    room_b_id: UUID
    owner_a: RoomAccessGrant
    owner_b: RoomAccessGrant
    character_id: UUID
    character2_id: UUID
    events: TableEventService
    sessions: SessionService
    battle_maps: BattleMapService
    library: MonsterLibraryService
    characters: CharacterRepository
    rooms: RoomService
    campaigns: dict[str, CampaignWorld] = field(default_factory=dict)


def _build_campaign(
    world: JourneyWorld,
    *,
    room_id: UUID,
    owner: RoomAccessGrant,
    name: str,
    character_id: UUID,
) -> CampaignWorld:
    rooms = world.rooms
    dm = rooms.enter_room(
        EnterRoomRequest(
            code=owner.room.code,
            password="secret",
            elevated_key=owner.dm_key,
            display_name=f"DM-{name}",
        ),
        remote_addr="127.0.0.2",
    )
    campaigns = CampaignService(CampaignRepository(world.engine))
    campaign = campaigns.create_campaign(
        room_id, CampaignCreate(name=name, ruleset="dnd5e-2014")
    )
    campaigns.set_status(room_id, campaign.id, CampaignStatus.ACTIVE)
    campaigns.select_campaign(room_id, campaign.id)
    campaigns.add_character(
        room_id, campaign.id, RosterAdd(character_id=character_id)
    )

    seats = SeatService(SeatRepository(world.engine))
    dm_seat = seats.create_seat(
        room_id, campaign.id, SeatCreate(role=SeatRole.DM, label="DM")
    )
    seats.set_controller(
        room_id, campaign.id, dm_seat.id,
        SeatControllerPatch(
            controller_kind=ControllerKind.HUMAN,
            controller_access_session_id=dm.access_session_id,
        ),
    )
    player_seat = seats.create_seat(
        room_id, campaign.id, SeatCreate(role=SeatRole.PLAYER, label="Player")
    )
    seats.set_controller(
        room_id, campaign.id, player_seat.id,
        SeatControllerPatch(
            controller_kind=ControllerKind.HUMAN,
            controller_access_session_id=owner.access_session_id,
        ),
    )
    seats.select_character(room_id, campaign.id, player_seat.id, character_id)
    dm_context = rooms.authenticate(room_id, dm.access_token)
    started = world.sessions.start_session(room_id, campaign.id, dm_context)

    combat, board, _ = wire_tactical_services(
        world.engine, world.registry, world.characters, world.events
    )

    def actor(context: RoomAccessContext) -> TableActorContext:
        return world.events.resolve_human_actor(
            room_id=room_id, campaign_id=campaign.id,
            session_id=started.id, context=context,
        )

    owner_context = rooms.authenticate(room_id, owner.access_token)
    return CampaignWorld(
        campaign_id=campaign.id,
        session_id=started.id,
        dm_actor=actor(dm_context),
        player_actor=actor(owner_context),
        dm_context=dm_context,
        combat=combat,
        board=board,
    )


def _build_world() -> JourneyWorld:
    _reset()
    command.upgrade(_config(), "heads")
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL, pool_size=10, max_overflow=10)
    registry = load_default_content_registry()
    localization = load_content_localization_catalog(registry, resolve_content_root())

    rooms = RoomService(RoomRepository(engine))
    owner_a = rooms.create_room(
        CreateRoomRequest(name="Journey A", password="secret", display_name="Owner A")
    )
    owner_b = rooms.create_room(
        CreateRoomRequest(name="Journey B", password="secret", display_name="Owner B")
    )

    characters = CharacterRepository(engine, registry)
    build = build_p0_fighter_wizard_fixture()
    character = characters.create_character(
        name="Mira", build=build, state=build_p0_fighter_wizard_state(build)
    )
    character2 = characters.create_character(
        name="Kai", build=build, state=build_p0_fighter_wizard_state(build)
    )
    character3 = characters.create_character(
        name="Rin", build=build, state=build_p0_fighter_wizard_state(build)
    )
    RoomWorkspaceRepository(engine).attach_character(
        room_id=owner_a.room.id, character_id=character.id
    )
    RoomWorkspaceRepository(engine).attach_character(
        room_id=owner_a.room.id, character_id=character2.id
    )
    RoomWorkspaceRepository(engine).attach_character(
        room_id=owner_b.room.id, character_id=character3.id
    )

    events = TableEventService(TableEventRepository(engine))
    sessions = SessionService(
        SessionRepository(engine), SessionLiveRepository(engine), event_service=events
    )
    battle_maps = BattleMapService(
        BattleMapRepository(engine),
        RoomAssetRepository(engine),
        events,
        content_registry=registry,
    )
    library = MonsterLibraryService(
        engine,
        MonsterLibraryRepository(engine),
        MonsterRepository(engine),
        registry,
        localization,
        events,
    )

    world = JourneyWorld(
        engine=engine,
        registry=registry,
        room_a_id=owner_a.room.id,
        room_b_id=owner_b.room.id,
        owner_a=owner_a,
        owner_b=owner_b,
        character_id=character.id,
        character2_id=character2.id,
        events=events,
        sessions=sessions,
        battle_maps=battle_maps,
        library=library,
        characters=characters,
        rooms=rooms,
    )
    world.campaigns["a1"] = _build_campaign(
        world, room_id=owner_a.room.id, owner=owner_a, name="A1",
        character_id=character.id,
    )
    world.campaigns["a2"] = _build_campaign(
        world, room_id=owner_a.room.id, owner=owner_a, name="A2",
        character_id=character2.id,
    )
    world.campaigns["b1"] = _build_campaign(
        world, room_id=owner_b.room.id, owner=owner_b, name="B1",
        character_id=character3.id,
    )
    return world


def _owner_context(world: JourneyWorld, room_id: UUID, owner: RoomAccessGrant) -> RoomAccessContext:
    return RoomAccessContext(
        room_id=room_id,
        access_session_id=owner.access_session_id,
        authority=RoomAccessAuthority.OWNER,
    )


def _dm_room_context(cw: CampaignWorld, room_id: UUID) -> RoomAccessContext:
    return RoomAccessContext(
        room_id=room_id,
        access_session_id=cw.dm_actor.access_session_id,
        authority=RoomAccessAuthority.DM,
    )


def _member_context(world: JourneyWorld, room_id: UUID, owner: RoomAccessGrant) -> RoomAccessContext:
    member = world.rooms.enter_room(
        EnterRoomRequest(
            code=owner.room.code, password="secret", display_name="Member"
        ),
        remote_addr="127.0.0.9",
    )
    return world.rooms.authenticate(room_id, member.access_token)


def _make_template(
    world: JourneyWorld, room_id: UUID, owner: RoomAccessGrant, *, name: str, size: str, max_hp: int
) -> UUID:
    created = world.library.create_custom(
        _owner_context(world, room_id, owner),
        room_id,
        CreateCustomMonsterInput(name=name, size=size, armor_class=13, max_hp=max_hp),
    )
    return UUID(created.ref.removeprefix("custom:"))


def _make_map(world: JourneyWorld, room_id: UUID, owner: RoomAccessGrant, *, name: str = "Journey Map") -> UUID:
    created = world.battle_maps.create(
        _owner_context(world, room_id, owner),
        room_id=room_id,
        payload=BattleMapCreate(
            name=name, source_kind="blank", width_cells=20, height_cells=15
        ),
    )
    return created.id


def _put(
    world: JourneyWorld,
    room_id: UUID,
    owner: RoomAccessGrant,
    map_id: UUID,
    placements: list[MonsterPlacementInput],
    *,
    expected_revision: int,
):
    return world.battle_maps.replace_monster_placements(
        _owner_context(world, room_id, owner),
        room_id=room_id,
        map_id=map_id,
        payload=MonsterPlacementsReplace(
            expected_revision=expected_revision, placements=placements
        ),
    )


def _placement(
    *,
    template_key: str | None = None,
    custom_template_id: UUID | None = None,
    anchor: tuple[int, int] = (1, 1),
    visibility: str = "public",
    sort_order: int = 0,
) -> MonsterPlacementInput:
    return MonsterPlacementInput(
        template_key=template_key,
        custom_template_id=custom_template_id,
        anchor_x=anchor[0],
        anchor_y=anchor[1],
        visibility=visibility,
        sort_order=sort_order,
    )


def _counts(engine: Engine) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            "combats": connection.scalar(select(func.count()).select_from(combats)) or 0,
            "boards": connection.scalar(select(func.count()).select_from(combat_boards)) or 0,
            "entries": connection.scalar(select(func.count()).select_from(combat_entries)) or 0,
            "instances": connection.scalar(select(func.count()).select_from(monster_instances)) or 0,
            "events": connection.scalar(select(func.count()).select_from(session_events)) or 0,
        }


def _ai_player_actor(world: JourneyWorld, cw: CampaignWorld) -> TableActorContext:
    service = AIControllerService(
        AIControllerGrantRepository(world.engine), world.events
    )
    grant = service.let_ai_control_player(
        room_id=world.room_a_id,
        campaign_id=cw.campaign_id,
        session_id=cw.session_id,
        seat_id=cw.player_actor.seat_id,
        context=world.rooms.authenticate(world.room_a_id, world.owner_a.access_token),
        request=AIHandoffRequest(),
    )
    return world.events.resolve_ai_actor(
        room_id=world.room_a_id,
        campaign_id=cw.campaign_id,
        session_id=cw.session_id,
        grant_id=grant.grant_id,
        generation=grant.generation,
    )


def _monster_instance_ids(world: JourneyWorld, combat_id: UUID) -> list[UUID]:
    with world.engine.connect() as connection:
        return list(
            connection.execute(
                select(combat_entries.c.monster_instance_id)
                .where(combat_entries.c.combat_id == combat_id)
                .where(combat_entries.c.monster_instance_id.is_not(None))
            ).scalars()
        )


# --- D.1: two Rooms stay isolated ------------------------------------------------


def test_pg_two_rooms_scope_isolation() -> None:
    """Room B cannot see or use Room A's templates, maps, or placements."""
    world = _build_world()
    try:
        room_a, room_b = world.room_a_id, world.room_b_id
        template_id = _make_template(
            world, room_a, world.owner_a, name="A Brute", size="Large", max_hp=59
        )
        map_id = _make_map(world, room_a, world.owner_a)
        _put(
            world, room_a, world.owner_a, map_id,
            [
                _placement(template_key=GOBLIN_KEY, anchor=(1, 1)),
                _placement(
                    custom_template_id=template_id, anchor=(6, 6),
                    visibility="hidden", sort_order=1,
                ),
            ],
            expected_revision=1,
        )
        b1 = world.campaigns["b1"]
        ctx_b = _owner_context(world, room_b, world.owner_b)

        # Cross-room reads are 404.
        with pytest.raises(MonsterTemplateNotFoundError):
            world.library.get(ctx_b, room_b, f"custom:{template_id}")
        assert all(
            view.ref != f"custom:{template_id}"
            for view in world.library.list(ctx_b, room_b)
        )
        with pytest.raises(BattleMapNotFoundError):
            world.battle_maps.get(ctx_b, room_b, map_id)

        # Cross-room tactical start is refused with zero side effects.
        before = _counts(world.engine)
        with pytest.raises(BattleMapNotFoundError):
            b1.combat.start_tactical_combat(
                b1.dm_actor,
                StartTacticalCombatInput(
                    battle_map_id=map_id, load_map_monsters=True,
                    idempotency_key="cross-room",
                ),
            )
        assert _counts(world.engine) == before
    finally:
        world.engine.dispose()


# --- D.1: one Room, two Campaigns ------------------------------------------------


def test_pg_two_campaigns_share_library_with_independent_runtime() -> None:
    """Same library, separate Instances/boards/HP/resources per Campaign.

    Editing the template afterwards only affects new loads; the live
    Campaign's snapshots stay frozen ("改庫但已上場資料不變").
    """
    world = _build_world()
    try:
        room_a = world.room_a_id
        template_id = _make_template(
            world, room_a, world.owner_a, name="Shared Brute", size="Large", max_hp=60
        )
        map_id = _make_map(world, room_a, world.owner_a)
        _put(
            world, room_a, world.owner_a, map_id,
            [
                _placement(template_key=GOBLIN_KEY, anchor=(1, 1)),
                _placement(
                    custom_template_id=template_id, anchor=(6, 6),
                    visibility="hidden", sort_order=1,
                ),
            ],
            expected_revision=1,
        )
        a1, a2 = world.campaigns["a1"], world.campaigns["a2"]

        combat1 = a1.combat.start_tactical_combat(
            a1.dm_actor,
            StartTacticalCombatInput(
                battle_map_id=map_id, load_map_monsters=True,
                include_active_party=True, idempotency_key="a1-first",
            ),
        )
        combat2 = a2.combat.start_tactical_combat(
            a2.dm_actor,
            StartTacticalCombatInput(
                battle_map_id=map_id, load_map_monsters=True,
                include_active_party=True, idempotency_key="a2-first",
            ),
        )
        assert combat1.id != combat2.id
        instances1 = _monster_instance_ids(world, combat1.id)
        instances2 = _monster_instance_ids(world, combat2.id)
        assert len(instances1) == 2 and len(instances2) == 2
        assert set(instances1).isdisjoint(instances2)
        # Same library template behind both runtimes.
        with world.engine.connect() as connection:
            refs1 = set(
                connection.execute(
                    select(monster_instances.c.custom_template_id)
                    .where(monster_instances.c.id.in_(instances1))
                ).scalars()
            )
        assert template_id in refs1

        # HP and resources are independent per Campaign.
        with world.engine.begin() as connection:
            connection.execute(
                update(monster_instances)
                .where(monster_instances.c.id == instances1[0])
                .values(current_hp=1, resources={"spell_slots": {"1": 0}})
            )
        with world.engine.connect() as connection:
            hp2, res2 = connection.execute(
                select(monster_instances.c.current_hp, monster_instances.c.resources)
                .where(monster_instances.c.id == instances2[0])
            ).one()
        assert hp2 != 1
        assert res2 != {"spell_slots": {"1": 0}}

        # Editing the template: new loads use the latest, live snapshots frozen.
        a1.combat.end_combat(a1.dm_actor)
        world.library.patch_custom(
            _owner_context(world, room_a, world.owner_a),
            room_a, template_id,
            PatchCustomMonsterInput(expected_revision=1, max_hp=99),
        )
        combat3 = a1.combat.start_tactical_combat(
            a1.dm_actor,
            StartTacticalCombatInput(
                battle_map_id=map_id, load_map_monsters=True,
                include_active_party=True, idempotency_key="a1-second",
            ),
        )
        new_ids = _monster_instance_ids(world, combat3.id)
        with world.engine.connect() as connection:
            new_max_hp = connection.execute(
                select(monster_instances.c.rules_snapshot["max_hp"].as_integer())
                .where(monster_instances.c.id.in_(new_ids))
                .where(monster_instances.c.custom_template_id == template_id)
            ).scalar_one()
            old_max_hp = connection.execute(
                select(monster_instances.c.rules_snapshot["max_hp"].as_integer())
                .where(monster_instances.c.id.in_(instances2))
                .where(monster_instances.c.custom_template_id == template_id)
            ).scalar_one()
        assert new_max_hp == 99
        assert old_max_hp == 60
    finally:
        world.engine.dispose()


# --- D.1: Session End -> new Session continues the same Combat --------------------


def _combat_state(world: JourneyWorld, cw: CampaignWorld) -> dict:
    combat = cw.combat.repository.get_active(cw.campaign_id)
    assert combat is not None
    with world.engine.connect() as connection:
        entries = {
            str(row["id"]): (row["subject_kind"], str(row["monster_instance_id"]))
            for row in connection.execute(
                select(combat_entries).where(combat_entries.c.combat_id == combat.id)
            ).mappings()
        }
        positions = {
            str(row["combat_entry_id"]): (row["anchor_x"], row["anchor_y"])
            for row in connection.execute(
                select(combat_positions).where(combat_positions.c.combat_id == combat.id)
            ).mappings()
        }
        board = dict(
            connection.execute(
                select(combat_boards).where(combat_boards.c.combat_id == combat.id)
            ).mappings().one()
        )
        cursor = connection.scalar(
            select(func.max(session_events.c.seq)).where(
                session_events.c.session_id == cw.session_id
            )
        ) or 0
    return {
        "combat_id": combat.id,
        "status": combat.status,
        "entries": entries,
        "positions": positions,
        "board": (board["source_battle_map_id"], board["source_battle_map_revision"], board["runtime_revision"]),
        "cursor": cursor,
    }


def test_pg_session_end_new_session_continues_combat_and_restart_persists() -> None:
    """Combat/positions/pending state survive Session End, a new Session, and a reconnect."""
    world = _build_world()
    try:
        room_a = world.room_a_id
        a1 = world.campaigns["a1"]
        template_id = _make_template(
            world, room_a, world.owner_a, name="Lurker", size="Medium", max_hp=40
        )
        map_id = _make_map(world, room_a, world.owner_a)
        _put(
            world, room_a, world.owner_a, map_id,
            [
                _placement(template_key=GOBLIN_KEY, anchor=(1, 1)),
                _placement(
                    custom_template_id=template_id, anchor=(6, 6),
                    visibility="hidden", sort_order=1,
                ),
            ],
            expected_revision=1,
        )
        started = a1.combat.start_tactical_combat(
            a1.dm_actor,
            StartTacticalCombatInput(
                battle_map_id=map_id, load_map_monsters=True,
                include_active_party=True, idempotency_key="continue-1",
            ),
        )
        # Place the party character; initiative stays pending.
        character_entry_id = next(
            entry.id
            for entry in a1.combat.repository.list_entries(started.id)
            if entry.subject_kind == "character"
        )
        a1.board.place_position(
            a1.dm_actor, character_entry_id,
            PlaceCombatantInput(anchor_x=10, anchor_y=10),
        )
        before = _combat_state(world, a1)
        assert before["status"] == "initiative_pending"

        # End the Session: the Combat stays active with identical state.
        world.sessions.end_session(
            room_a, a1.campaign_id, a1.session_id, a1.dm_context
        )
        continued = _combat_state(world, a1)
        assert continued["combat_id"] == before["combat_id"]
        assert continued["entries"] == before["entries"]
        assert continued["positions"] == before["positions"]
        assert continued["status"] == "initiative_pending"
        assert continued["board"] == before["board"]
        assert continued["cursor"] >= before["cursor"]

        # A new Session continues the same Combat.
        CampaignService(CampaignRepository(world.engine)).select_campaign(
            room_a, a1.campaign_id
        )
        restarted_session = world.sessions.start_session(room_a, a1.campaign_id, a1.dm_context)
        new_dm_actor = world.events.resolve_human_actor(
            room_id=room_a, campaign_id=a1.campaign_id,
            session_id=restarted_session.id, context=a1.dm_context,
        )
        resumed = _combat_state(world, a1)
        assert resumed["combat_id"] == before["combat_id"]
        assert resumed["entries"] == before["entries"]
        assert resumed["positions"] == before["positions"]
        board_view = a1.board.get_board(new_dm_actor)
        assert (board_view.source_battle_map_id, board_view.source_battle_map_revision) == (
            map_id, 2,
        )

        # Restart: drop every service/connection and rebuild from the DB.
        world.engine.dispose()
        engine2 = create_engine(POSTGRES_URL, pool_size=10, max_overflow=10)
        try:
            characters2 = CharacterRepository(engine2, world.registry)
            events2 = TableEventService(TableEventRepository(engine2))
            combat2, board2, _ = wire_tactical_services(
                engine2, world.registry, characters2, events2
            )
            actor2 = events2.resolve_human_actor(
                room_id=room_a, campaign_id=a1.campaign_id,
                session_id=restarted_session.id, context=a1.dm_context,
            )
            stored = combat2.repository.get_active(a1.campaign_id)
            assert stored is not None and stored.id == before["combat_id"]
            entries2 = {
                str(e.id) for e in combat2.repository.list_entries(stored.id)
            }
            assert entries2 == set(before["entries"])
            with engine2.connect() as connection:
                positions2 = {
                    str(r["combat_entry_id"]): (r["anchor_x"], r["anchor_y"])
                    for r in connection.execute(
                        select(combat_positions).where(
                            combat_positions.c.combat_id == stored.id
                        )
                    ).mappings()
                }
            assert positions2 == before["positions"]
            board_view2 = board2.get_board(actor2)
            assert (board_view2.source_battle_map_id, board_view2.source_battle_map_revision) == (
                map_id, 2,
            )
            # Library and placements are intact after the reconnect too.
            maps2 = BattleMapService(
                BattleMapRepository(engine2), RoomAssetRepository(engine2),
                events2, content_registry=world.registry,
            )
            reread = maps2.get(
                _dm_room_context(a1, room_a), room_a, map_id
            )
            assert len(reread.monster_placements) == 2
        finally:
            engine2.dispose()
    finally:
        world.engine.dispose()


# --- D.1: Quick / empty map / zero Adventure / optional Scene ---------------------


def test_pg_quick_empty_map_zero_adventure_optional_scene_legal() -> None:
    """Quick combat, empty placements, and no Adventure/Scene are all legal."""
    world = _build_world()
    try:
        room_a = world.room_a_id
        a1 = world.campaigns["a1"]
        ctx = _owner_context(world, room_a, world.owner_a)

        # Empty custom library (builtins are always listed) and zero Adventures.
        assert [
            view for view in world.library.list(ctx, room_a)
            if view.ref.startswith("custom:")
        ] == []
        with world.engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM adventure_definitions")) == 0

        # Quick Combat needs no map or board.
        quick = a1.combat.start_quick_combat(
            a1.dm_actor, StartCombatInput(include_active_party=True)
        )
        assert quick.mode == "quick"
        a1.combat.end_combat(a1.dm_actor)

        # A map with no placements starts map-only Tactical Combat.
        map_id = _make_map(world, room_a, world.owner_a, name="Empty Map")
        tactical = a1.combat.start_tactical_combat(
            a1.dm_actor,
            StartTacticalCombatInput(
                battle_map_id=map_id, load_map_monsters=True,
                include_active_party=False, idempotency_key="empty-map",
            ),
        )
        assert tactical.mode == "tactical"
        board = a1.board.get_board(a1.dm_actor)
        assert board.source_battle_map_id == map_id
        a1.combat.end_combat(a1.dm_actor)

        # No Adventure or runtime world entries were needed to run the Session.
        with world.engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM adventure_entries")) == 0
            assert connection.scalar(text("SELECT count(*) FROM campaign_world_entries")) == 0
    finally:
        world.engine.dispose()


# --- D.1: Player / AI Player rejections --------------------------------------------


def test_pg_player_and_ai_player_rejections_have_zero_side_effects() -> None:
    """Players cannot author placements or start loaded combats; failures change nothing."""
    world = _build_world()
    try:
        room_a = world.room_a_id
        a1 = world.campaigns["a1"]
        template_id = _make_template(
            world, room_a, world.owner_a, name="Guard", size="Medium", max_hp=30
        )
        map_id = _make_map(world, room_a, world.owner_a)
        _put(
            world, room_a, world.owner_a, map_id,
            [_placement(template_key=GOBLIN_KEY, anchor=(1, 1))],
            expected_revision=1,
        )

        # A plain member cannot replace placements: 403, revision untouched.
        member_ctx = _member_context(world, room_a, world.owner_a)
        with pytest.raises(BattleMapForbiddenError):
            world.battle_maps.replace_monster_placements(
                member_ctx, room_id=room_a, map_id=map_id,
                payload=MonsterPlacementsReplace(
                    expected_revision=1,
                    placements=[_placement(custom_template_id=template_id, anchor=(3, 3))],
                ),
            )
        reread = world.battle_maps.get(
            _owner_context(world, room_a, world.owner_a), room_a, map_id
        )
        assert reread.revision == 2
        assert len(reread.monster_placements) == 1
        assert reread.monster_placements[0].template_key == GOBLIN_KEY

        # An AI Player cannot start Tactical Combat: refused, nothing stored.
        ai_player = _ai_player_actor(world, a1)
        before = _counts(world.engine)
        with pytest.raises(TableEventActorUnauthorizedError):
            a1.combat.start_tactical_combat(
                ai_player,
                StartTacticalCombatInput(
                    battle_map_id=map_id, load_map_monsters=True,
                    idempotency_key="ai-player-start",
                ),
            )
        assert _counts(world.engine) == before

        # Player-side invisibility of hidden placements is covered by
        # test_m07c_secrecy.py (view/detail/board/order/ties/reveal),
        # test_m07d_secrecy.py (events), test_m07d_session_libraries.py
        # (Session library read boundary) and
        # test_m07c_acceptance.py::test_ai_player_mcp_reads_never_reveal_hidden_loaded_monster.
    finally:
        world.engine.dispose()


# --- D.1: Room hard delete clears the M07 graph --------------------------------------


def test_pg_room_hard_delete_clears_m07_graph() -> None:
    """Hard delete removes templates, maps, placements, boards, and instances."""
    world = _build_world()
    try:
        room_a, room_b = world.room_a_id, world.room_b_id
        a1 = world.campaigns["a1"]
        template_id = _make_template(
            world, room_a, world.owner_a, name="Doomed", size="Medium", max_hp=20
        )
        map_id = _make_map(world, room_a, world.owner_a)
        _put(
            world, room_a, world.owner_a, map_id,
            [_placement(custom_template_id=template_id, anchor=(2, 2))],
            expected_revision=1,
        )
        started = a1.combat.start_tactical_combat(
            a1.dm_actor,
            StartTacticalCombatInput(
                battle_map_id=map_id, load_map_monsters=True,
                include_active_party=False, idempotency_key="doomed",
            ),
        )
        doomed_instances = _monster_instance_ids(world, started.id)
        assert len(doomed_instances) == 1
        a1.combat.end_combat(a1.dm_actor)

        RoomWorkspaceRepository(world.engine).hard_delete_room(room_a)

        with world.engine.connect() as connection:
            assert connection.scalar(
                select(func.count()).select_from(monster_templates)
                .where(monster_templates.c.room_id == room_a)
            ) == 0
            assert connection.scalar(
                select(func.count()).select_from(battle_maps)
                .where(battle_maps.c.room_id == room_a)
            ) == 0
            assert connection.scalar(
                select(func.count()).select_from(battle_map_monster_placements)
                .where(battle_map_monster_placements.c.battle_map_id == map_id)
            ) == 0
            assert connection.scalar(
                select(func.count()).select_from(combats)
                .where(combats.c.id == started.id)
            ) == 0
            assert connection.scalar(
                select(func.count()).select_from(combat_boards)
                .where(combat_boards.c.combat_id == started.id)
            ) == 0
            assert connection.scalar(
                select(func.count()).select_from(monster_instances)
                .where(monster_instances.c.id.in_(doomed_instances))
            ) == 0
            # Room B is untouched.
            b1 = world.campaigns["b1"]
            assert connection.scalar(
                text("SELECT count(*) FROM rooms WHERE id = :room_id"),
                {"room_id": room_b},
            ) == 1
            assert connection.scalar(
                select(func.count()).select_from(combats)
                .where(combats.c.campaign_id == b1.campaign_id)
            ) == 0
        assert world.sessions.repository.get(b1.session_id) is not None
    finally:
        world.engine.dispose()
