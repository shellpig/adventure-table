from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from app.content import load_default_content_registry
from app.db import metadata
from app.domain.character.fixture import (
    build_p0_fighter_wizard_fixture,
    build_p0_fighter_wizard_state,
)
from app.domain.combat.initiative import (
    CombatInitiativeService,
    FinalizeInitiativeInput,
    RequestInitiativeInput,
)
from app.domain.combat.lifecycle import (
    ActiveCombatExistsError,
    AddMonsterInput,
    CombatActionInput,
    CombatActionKind,
    CombatEconomyCost,
    CombatService,
    StartCombatInput,
)
from app.domain.combat.order import CombatOrderService, ReorderInitiativeInput
from app.domain.combat.roll_compat import CombatAwareRollRepository
from app.domain.rooms.campaigns import CampaignCreate, CampaignService, CampaignStatus, RosterAdd
from app.domain.rooms.character_rolls import CharacterRollModifierResolver
from app.domain.rooms.rolls import (
    FormalRollInput,
    FormalRollSource,
    RequestCheckInput,
    RollRequestType,
    RollService,
)
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
from app.persistence.characters import CharacterRepository
from app.persistence.combat.initiative import CombatInitiativeRepository
from app.persistence.combat.lifecycle import CombatRepository
from app.persistence.combat.order import CombatOrderRepository
from app.persistence.combat.repository import MonsterRepository
from app.persistence.rooms.campaigns import CampaignRepository
from app.persistence.rooms.exploration_subjects import ExplorationSubjectRepository
from app.persistence.rooms.repository import RoomRepository
from app.persistence.rooms.seats import SeatRepository
from app.persistence.rooms.sessions import SessionRepository
from app.persistence.rooms.table_runtime import TableEventRepository
from app.persistence.rooms.workspace import RoomWorkspaceRepository


@dataclass
class CombatTable:
    engine: Engine
    room_id: UUID
    campaign_id: UUID
    character_id: UUID
    player_seat_id: UUID
    dm_context: object
    player_context: object
    session_service: SessionService
    events: TableEventService
    combat: CombatService
    initiative: CombatInitiativeService
    order: CombatOrderService
    rolls: RollService
    monsters: MonsterRepository
    session_id: UUID
    dm_actor: TableActorContext
    player_actor: TableActorContext
    dm_token: str | None = None
    player_token: str | None = None

    def actor_for_session(self, session_id: UUID, context: object) -> TableActorContext:
        return self.events.resolve_human_actor(
            room_id=self.room_id,
            campaign_id=self.campaign_id,
            session_id=session_id,
            context=context,
        )


def _setup() -> CombatTable:
    # StaticPool keeps one in-memory SQLite database across service connections.
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata.create_all(engine)
    registry = load_default_content_registry()

    rooms = RoomService(RoomRepository(engine))
    owner = rooms.create_room(
        CreateRoomRequest(name="P4-B", password="secret", display_name="Player")
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
        room_id=owner.room.id,
        character_id=character.id,
    )

    campaigns = CampaignService(CampaignRepository(engine))
    campaign = campaigns.create_campaign(
        owner.room.id,
        CampaignCreate(name="Campaign", ruleset="dnd5e-2014"),
    )
    campaigns.set_status(owner.room.id, campaign.id, CampaignStatus.ACTIVE)
    campaigns.select_campaign(owner.room.id, campaign.id)
    campaigns.add_character(
        owner.room.id,
        campaign.id,
        RosterAdd(character_id=character.id),
    )

    seats = SeatService(SeatRepository(engine))
    dm_seat = seats.create_seat(
        owner.room.id, campaign.id, SeatCreate(role=SeatRole.DM, label="DM")
    )
    seats.set_controller(
        owner.room.id,
        campaign.id,
        dm_seat.id,
        SeatControllerPatch(
            controller_kind=ControllerKind.HUMAN,
            controller_access_session_id=dm.access_session_id,
        ),
    )
    player_seat = seats.create_seat(
        owner.room.id,
        campaign.id,
        SeatCreate(role=SeatRole.PLAYER, label="Player"),
    )
    seats.set_controller(
        owner.room.id,
        campaign.id,
        player_seat.id,
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
    combat = CombatService(combat_repository, events, characters, monsters, registry)
    roll_service = RollService(
        CombatAwareRollRepository(engine, events.repository),
        ExplorationSubjectRepository(engine),
        events,
        CharacterRollModifierResolver(characters, registry),
    )
    initiative = CombatInitiativeService(
        CombatInitiativeRepository(engine, events.repository),
        combat_repository,
        combat,
        monsters,
        roll_service,
        events,
    )
    order = CombatOrderService(
        CombatOrderRepository(engine, events.repository),
        combat,
        events,
    )

    def actor(context: object) -> TableActorContext:
        return events.resolve_human_actor(
            room_id=owner.room.id,
            campaign_id=campaign.id,
            session_id=started.id,
            context=context,
        )

    return CombatTable(
        engine=engine,
        room_id=owner.room.id,
        campaign_id=campaign.id,
        character_id=character.id,
        player_seat_id=player_seat.id,
        dm_context=dm_context,
        player_context=player_context,
        session_service=sessions,
        events=events,
        combat=combat,
        initiative=initiative,
        order=order,
        rolls=roll_service,
        monsters=monsters,
        session_id=started.id,
        dm_actor=actor(dm_context),
        player_actor=actor(player_context),
        dm_token=dm.access_token,
        player_token=owner.access_token,
    )


def _quick_enemy(table: CombatTable, name: str):
    return table.monsters.create_quick_enemy(
        campaign_id=table.campaign_id,
        name=name,
        armor_class=12,
        max_hp=9,
        speed={"walk": "30 ft."},
    )


def _complete_request(table: CombatTable, request, raw: int, suffix: str) -> None:
    actor = table.dm_actor if request.target_seat_id is None else table.player_actor
    table.initiative.complete_initiative(
        actor,
        FormalRollInput(
            roll_request_id=request.id,
            source=FormalRollSource.PHYSICAL,
            raw_dice=(raw,),
            idempotency_key=f"roll-{suffix}",
        ),
    )


def test_lifecycle_midcombat_reorder_and_cross_session_resume() -> None:
    table = _setup()
    try:
        started = table.combat.start_quick_combat(
            table.dm_actor,
            StartCombatInput(idempotency_key="start"),
        )
        assert started.status == "initiative_pending"
        assert [entry.character_id for entry in started.entries] == [table.character_id]

        with pytest.raises(ActiveCombatExistsError):
            table.combat.start_quick_combat(
                table.dm_actor,
                StartCombatInput(idempotency_key="second-active"),
            )

        first_monster = _quick_enemy(table, "Goblin A")
        pending = table.combat.add_monster(
            table.dm_actor,
            AddMonsterInput(
                monster_instance_id=first_monster.id,
                idempotency_key="add-goblin-a",
            ),
        )
        assert len(pending.entries) == 2

        requests = table.initiative.request_initiative(
            table.dm_actor,
            RequestInitiativeInput(idempotency_key="initial-initiative"),
        )
        assert len(requests.requests) == 2
        for index, request in enumerate(requests.requests):
            _complete_request(table, request, 11 + index, f"initial-{index}")

        ordered = table.initiative.suggested_order(table.dm_actor)
        running = table.initiative.finalize_initiative(
            table.dm_actor,
            FinalizeInitiativeInput(
                ordered_entry_ids=ordered,
                idempotency_key="finalize",
            ),
        )
        assert running.status == "running"
        assert running.round_number == 1
        assert running.current_turn_entry_id == ordered[0]

        action = table.combat.use_action(
            table.dm_actor,
            CombatActionInput(
                entry_id=running.current_turn_entry_id,
                action_kind=CombatActionKind.DODGE,
                economy_cost=CombatEconomyCost.ACTION,
                idempotency_key="spend-current-action",
            ),
        )
        assert action.entry_id == running.current_turn_entry_id
        spent = table.combat.get_active_combat(table.dm_actor)
        assert spent is not None
        spent_current = next(
            entry for entry in spent.entries if entry.id == spent.current_turn_entry_id
        )
        assert spent_current.action_available is False

        newcomer = _quick_enemy(table, "Goblin B")
        with_newcomer = table.combat.add_monster(
            table.dm_actor,
            AddMonsterInput(
                monster_instance_id=newcomer.id,
                idempotency_key="add-goblin-b",
            ),
        )
        newcomer_entry = next(
            entry for entry in with_newcomer.entries if entry.monster_instance_id == newcomer.id
        )
        newcomer_request = table.initiative.request_initiative(
            table.dm_actor,
            RequestInitiativeInput(
                entry_ids=(newcomer_entry.id,),
                idempotency_key="newcomer-initiative",
            ),
        )
        assert len(newcomer_request.requests) == 1
        _complete_request(table, newcomer_request.requests[0], 9, "newcomer")

        before_reorder = table.combat.get_active_combat(table.dm_actor)
        assert before_reorder is not None
        before_economy = {
            entry.id: (
                entry.action_available,
                entry.bonus_action_available,
                entry.reaction_available,
                entry.attacks_used,
                entry.ready_state,
                entry.pending_reaction_state,
            )
            for entry in before_reorder.entries
        }
        reordered_ids = tuple(entry.id for entry in before_reorder.entries)
        after_reorder = table.order.reorder_running(
            table.dm_actor,
            ReorderInitiativeInput(
                ordered_entry_ids=reordered_ids,
                idempotency_key="midcombat-reorder",
            ),
        )
        assert after_reorder.round_number == before_reorder.round_number
        assert after_reorder.current_turn_entry_id == before_reorder.current_turn_entry_id
        assert {
            entry.id: (
                entry.action_available,
                entry.bonus_action_available,
                entry.reaction_available,
                entry.attacks_used,
                entry.ready_state,
                entry.pending_reaction_state,
            )
            for entry in after_reorder.entries
        } == before_economy

        # End Session A without ending Combat, then create Session B and prove
        # the exact Campaign-level Combat state is still canonical and mutable.
        table.session_service.end_session(
            table.room_id,
            table.campaign_id,
            table.session_id,
            table.dm_context,
        )
        session_b = table.session_service.start_session(
            table.room_id,
            table.campaign_id,
            table.dm_context,
        )
        dm_b = table.actor_for_session(session_b.id, table.dm_context)
        resumed = table.combat.get_active_combat(dm_b)
        assert resumed is not None
        assert resumed.id == after_reorder.id
        assert resumed.round_number == after_reorder.round_number
        assert resumed.current_turn_entry_id == after_reorder.current_turn_entry_id
        assert [entry.id for entry in resumed.entries] == [entry.id for entry in after_reorder.entries]

        advanced = table.combat.advance_turn(dm_b, idempotency_key="session-b-advance")
        assert advanced.id == resumed.id
        assert advanced.current_turn_entry_id != resumed.current_turn_entry_id

        ended = table.combat.end_combat(dm_b, idempotency_key="end-combat")
        assert ended.status == "ended"
        assert ended.round_number is None
        assert ended.current_turn_entry_id is None

        replacement = table.combat.start_quick_combat(
            dm_b,
            StartCombatInput(include_active_party=False, idempotency_key="replacement"),
        )
        assert replacement.id != ended.id
        assert replacement.status == "initiative_pending"
    finally:
        table.engine.dispose()


def test_grouped_monster_initiative_ties_and_p3_check_isolation() -> None:
    table = _setup()
    try:
        table.combat.start_quick_combat(
            table.dm_actor,
            StartCombatInput(include_active_party=False, idempotency_key="monsters-only"),
        )
        first = _quick_enemy(table, "Wolf A")
        second = _quick_enemy(table, "Wolf B")
        solo = _quick_enemy(table, "Bandit")
        for monster, group, key in (
            (first, "wolves", "first"),
            (second, "wolves", "second"),
            (solo, None, "solo"),
        ):
            table.combat.add_monster(
                table.dm_actor,
                AddMonsterInput(
                    monster_instance_id=monster.id,
                    initiative_group_key=group,
                    idempotency_key=f"add-{key}",
                ),
            )

        requested = table.initiative.request_initiative(
            table.dm_actor,
            RequestInitiativeInput(idempotency_key="monster-init"),
        )
        assert len(requested.requests) == 2
        assert sorted(len(request.grouped_entry_ids) for request in requested.requests) == [1, 2]

        # Combat formal rolls are deliberately excluded from the old P3 Check
        # list/resume projection, including seatless Monster initiative.
        assert table.rolls.list_requests(table.dm_actor) == ()

        for index, request in enumerate(requested.requests):
            _complete_request(table, request, 10, f"monster-{index}")

        ties = table.initiative.tied_totals(table.dm_actor)
        assert set(ties[10]) == {
            entry.id
            for entry in table.combat.get_active_combat(table.dm_actor).entries
        }

        group_id, checks = table.rolls.request_check(
            table.dm_actor,
            RequestCheckInput(
                target_seat_ids=(table.player_seat_id,),
                request_type=RollRequestType.ABILITY,
                ability_ref="dexterity",
                idempotency_key="legacy-check",
            ),
        )
        assert group_id is not None
        assert len(checks) == 1
        visible = table.rolls.list_requests(table.dm_actor)
        assert [request.id for request in visible] == [checks[0].id]

        explicit_order = tuple(
            entry.id for entry in table.combat.get_active_combat(table.dm_actor).entries
        )
        finalized = table.initiative.finalize_initiative(
            table.dm_actor,
            FinalizeInitiativeInput(
                ordered_entry_ids=explicit_order,
                idempotency_key="explicit-tie-order",
            ),
        )
        assert finalized.status == "running"
        assert tuple(entry.id for entry in finalized.entries) == explicit_order
    finally:
        table.engine.dispose()
