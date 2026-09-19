from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Engine

from app.content import load_default_content_registry
from app.domain.character.fixture import build_p0_fighter_wizard_fixture, build_p0_fighter_wizard_state
from app.domain.combat.adjudication_service import CombatAdjudicationService
from app.domain.combat.ai_tools import CombatAIToolApplicationService
from app.domain.combat.attack_definitions import AttackDefinitionResolver
from app.domain.combat.attacks import AttackAdjudicationInput, AttackRequestInput, CombatAttackService
from app.domain.combat.concentration import CombatConcentrationService
from app.domain.combat.core_rolls import CombatCoreRollService, SavingThrowInput
from app.domain.combat.initiative import (
    CombatInitiativeService,
    FinalizeInitiativeInput,
    RequestInitiativeInput,
)
from app.domain.combat.lifecycle import AddMonsterInput, CombatService, StartCombatInput
from app.domain.combat.monster_instances import MonsterInstanceService
from app.domain.combat.order import CombatOrderService
from app.domain.combat.reaction_service import (
    CombatReactionService,
    OpenReactionInput,
    ReactionKind,
    ResolveReactionInput,
)
from app.domain.combat.roll_compat import CombatAwareRollRepository
from app.domain.combat.semantic_hp import CombatResolutionService
from app.domain.combat.special_attacks import CombatSpecialAttackService
from app.domain.combat.spell_service import CombatSpellService
from app.domain.rooms.ai_controllers import (
    AIControllerService,
    AIHandoffRequest,
)
from app.domain.rooms.campaigns import CampaignCreate, CampaignService, CampaignStatus, RosterAdd
from app.domain.rooms.character_rolls import CharacterRollModifierResolver
from app.domain.rooms.exploration import ExplorationActionService, ExplorationStageService
from app.domain.rooms.pending_actions import PendingActionService
from app.domain.rooms.rolls import FormalRollInput, FormalRollSource, RollService
from app.domain.rooms.schemas import CreateRoomRequest, EnterRoomRequest, RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.seats import (
    ControllerKind,
    SeatControllerPatch,
    SeatCreate,
    SeatRole,
    SeatService,
)
from app.domain.rooms.service import RoomService
from app.domain.rooms.sessions import SessionLateJoinRequest, SessionService
from app.api.rooms.table_event_wait import ProcessLocalTableEventNotifier
from app.domain.rooms.table_events import (
    TableActorContext,
    TableEventService,
)
from app.persistence.characters import CharacterRepository
from app.persistence.combat.adjudication import CombatAdjudicationRepository
from app.persistence.combat.attacks import CombatAttackRepository
from app.persistence.combat.concentration import CombatConcentrationRepository
from app.persistence.combat.core_rolls import CombatCoreRollRepository
from app.persistence.combat.initiative import CombatInitiativeRepository
from app.persistence.combat.lifecycle import CombatRepository
from app.persistence.combat.order import CombatOrderRepository
from app.persistence.combat.reactions import CombatReactionRepository
from app.persistence.combat.repository import MonsterRepository
from app.persistence.combat.resolution import CombatResolutionRepository
from app.persistence.combat.special_attacks import SpecialAttackRepository
from app.persistence.combat.spells import CombatSpellRepository
from app.persistence.rooms.ai_controllers import AIControllerGrantRepository
from app.persistence.rooms.campaigns import CampaignRepository
from app.persistence.rooms.exploration import ExplorationRepository
from app.persistence.rooms.exploration_messages import ExplorationMessageRepository
from app.persistence.rooms.exploration_subjects import ExplorationSubjectRepository
from app.persistence.rooms.p3c_pending import PendingActionRepository
from app.persistence.rooms.p3c_runtime import roll_results
from app.persistence.rooms.repository import RoomRepository
from app.persistence.rooms.seats import SeatRepository
from app.persistence.rooms.sessions import SessionRepository
from app.persistence.rooms.table_runtime import TableEventRepository, session_events
from app.persistence.combat.tables import combats
from app.persistence.rooms.workspace import RoomWorkspaceRepository
import tests.test_p4b_combat_lifecycle as support


POSTGRES_URL = os.environ.get("P4_POSTGRES_URL")
# All Postgres tests reset the one shared database: keep them on a single xdist worker.
pytestmark = [
    pytest.mark.xdist_group("postgres"),
    pytest.mark.skipif(
        not POSTGRES_URL,
        reason="P4_POSTGRES_URL is only supplied by the P4 Non-E2E PostgreSQL job",
    ),
]
SERVER_ROOT = Path(__file__).resolve().parents[1]


def _config() -> Config:
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SERVER_ROOT / "alembic"))
    assert POSTGRES_URL is not None
    config.set_main_option("sqlalchemy.url", POSTGRES_URL)
    config.attributes["target_database_url"] = POSTGRES_URL
    return config


def _reset() -> None:
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
    finally:
        engine.dispose()
    command.upgrade(_config(), "heads")


class _Services:
    """One process-local service graph; rebuilt from scratch to model a restart."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.registry = load_default_content_registry()
        self.notifier = ProcessLocalTableEventNotifier()
        self.events = TableEventService(TableEventRepository(engine), notifier=self.notifier)
        self.rooms = RoomService(RoomRepository(engine))
        self.characters = CharacterRepository(engine, self.registry)
        self.workspace = RoomWorkspaceRepository(engine)
        self.campaigns = CampaignService(CampaignRepository(engine))
        self.seats = SeatService(SeatRepository(engine))
        self.sessions = SessionService(SessionRepository(engine), event_service=self.events)
        self.monsters = MonsterRepository(engine)
        self.combat = CombatService(
            CombatRepository(engine, self.events.repository),
            self.events,
            self.characters,
            self.monsters,
            self.registry,
        )
        self.rolls = RollService(
            CombatAwareRollRepository(engine, self.events.repository),
            ExplorationSubjectRepository(engine),
            self.events,
            CharacterRollModifierResolver(self.characters, self.registry),
            registry=self.registry,
        )
        self.stage = ExplorationStageService(ExplorationRepository(engine), self.events)
        self.actions = ExplorationActionService(
            ExplorationSubjectRepository(engine),
            ExplorationMessageRepository(engine),
            self.events,
        )
        self.pending = PendingActionService(
            PendingActionRepository(engine, self.events.repository),
            ExplorationSubjectRepository(engine),
            self.events,
            self.rolls.repository,
        )
        self.concentration = CombatConcentrationService(
            CombatConcentrationRepository(engine, self.events.repository),
            self.combat.repository,
            self.monsters,
            self.rolls,
            self.events,
        )
        self.core_rolls = CombatCoreRollService(
            CombatCoreRollRepository(engine, self.events.repository),
            self.combat.repository,
            self.combat,
            self.monsters,
            self.rolls,
            self.events,
            concentration_service=self.concentration,
        )
        self.initiative = CombatInitiativeService(
            CombatInitiativeRepository(engine, self.events.repository),
            self.combat.repository,
            self.combat,
            self.monsters,
            self.rolls,
            self.events,
        )
        self.order = CombatOrderService(
            CombatOrderRepository(engine, self.events.repository),
            self.combat,
            self.events,
        )
        self.resolution = CombatResolutionService(
            CombatResolutionRepository(engine, self.events.repository),
            self.combat.repository,
            self.combat,
            self.events,
        )
        self.adjudication = CombatAdjudicationService(
            CombatAdjudicationRepository(engine, self.events.repository),
            self.combat.repository,
            self.combat,
            self.events,
        )
        self.attacks = CombatAttackService(
            CombatAttackRepository(engine, self.events.repository),
            self.adjudication.repository,
            self.combat.repository,
            self.combat,
            AttackDefinitionResolver(self.characters, self.monsters, self.registry),
            self.rolls,
            self.events,
        )
        self.special_attacks = CombatSpecialAttackService(
            SpecialAttackRepository(engine, self.events.repository),
            self.core_rolls.repository,
            self.combat.repository,
            self.combat,
            self.characters,
            self.monsters,
            self.registry,
            self.rolls,
            self.events,
        )
        self.reaction = CombatReactionService(
            CombatReactionRepository(engine, self.events.repository),
            self.combat.repository,
            self.combat,
            self.events,
        )
        self.spells = CombatSpellService(
            CombatSpellRepository(engine, self.events.repository),
            self.combat.repository,
            self.combat,
            self.events,
            self.monsters,
            self.characters,
            self.rolls,
            self.registry,
        )
        self.monster_service = MonsterInstanceService(self.monsters, self.registry, self.events)
        self.grants = AIControllerGrantRepository(engine)
        self.controllers = AIControllerService(self.grants, self.events)

    def human(self, ids: dict, context) -> TableActorContext:
        return self.events.resolve_human_actor(
            room_id=UUID(ids["room_id"]),
            campaign_id=UUID(ids["campaign_id"]),
            session_id=UUID(ids["session_id"]),
            context=context,
        )

    def ai_participant(self, ids: dict) -> TableActorContext:
        return self.controllers.resolve_actor(ids["ai_token"])

    def build_ai_tool_service(self) -> CombatAIToolApplicationService:
        return CombatAIToolApplicationService(
            ai_controller_service=self.controllers,
            session_service=self.sessions,
            stage_service=self.stage,
            action_service=self.actions,
            roll_service=self.rolls,
            state_service=object(),
            pending_action_service=self.pending,
            event_service=self.events,
            workspace_service=object(),
            combat_service=self.combat,
            combat_attack_service=self.attacks,
            combat_resolution_service=self.resolution,
            combat_core_roll_service=self.core_rolls,
            combat_special_attack_service=self.special_attacks,
            combat_initiative_service=self.initiative,
            monster_instance_service=self.monster_service,
            combat_spell_service=self.spells,
            combat_concentration_service=self.concentration,
            combat_reaction_service=self.reaction,
            combat_adjudication_service=self.adjudication,
        )


def _build_dataset(monkeypatch: pytest.MonkeyPatch) -> dict:
    _reset()
    assert POSTGRES_URL is not None
    first_engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    monkeypatch.setattr(support, "create_engine", lambda *_args, **_kwargs: first_engine)
    table = support._setup()
    first_services = _Services(first_engine)

    # 1 Character (Mira) + 2 monsters (Goblin Alpha, Goblin Beta)
    combat = table.combat.start_quick_combat(
        table.dm_actor,
        StartCombatInput(include_active_party=True, idempotency_key="p4f-start-combat"),
    )
    alpha = support._quick_enemy(table, "Goblin Alpha")
    beta = support._quick_enemy(table, "Goblin Beta")
    table.combat.add_monster(
        table.dm_actor,
        AddMonsterInput(monster_instance_id=alpha.id, idempotency_key="p4f-add-alpha"),
    )
    table.combat.add_monster(
        table.dm_actor,
        AddMonsterInput(monster_instance_id=beta.id, idempotency_key="p4f-add-beta"),
    )

    # Participant seat for AI participant on table
    room = first_services.rooms.repository.get_room(table.room_id)
    assert room is not None
    luna_player = first_services.rooms.enter_room(
        EnterRoomRequest(code=room.code, password="secret", display_name="Luna Player"),
        remote_addr="127.0.0.3",
    )
    build = build_p0_fighter_wizard_fixture()
    luna_char = first_services.characters.create_character(
        name="Luna",
        build=build,
        state=build_p0_fighter_wizard_state(build),
    )
    first_services.workspace.attach_character(room_id=table.room_id, character_id=luna_char.id)
    first_services.campaigns.add_character(
        table.room_id,
        table.campaign_id,
        RosterAdd(character_id=luna_char.id),
    )
    luna_seat = first_services.seats.create_seat(
        table.room_id,
        table.campaign_id,
        SeatCreate(role=SeatRole.PLAYER, label="Luna"),
    )
    first_services.seats.set_controller(
        table.room_id,
        table.campaign_id,
        luna_seat.id,
        SeatControllerPatch(
            controller_kind=ControllerKind.HUMAN,
            controller_access_session_id=luna_player.access_session_id,
        ),
    )
    first_services.seats.select_character(
        table.room_id,
        table.campaign_id,
        luna_seat.id,
        luna_char.id,
    )
    table.session_service.late_join(
        table.room_id,
        table.campaign_id,
        table.session_id,
        SessionLateJoinRequest(seat_id=luna_seat.id),
        table.dm_context,
    )
    ai_grant = first_services.controllers.let_ai_control_player(
        room_id=table.room_id,
        campaign_id=table.campaign_id,
        session_id=table.session_id,
        seat_id=luna_seat.id,
        context=RoomAccessContext(
            room_id=table.room_id,
            access_session_id=luna_player.access_session_id,
            authority=RoomAccessAuthority.MEMBER,
        ),
        request=AIHandoffRequest(temporary_instruction="Support the party in combat."),
    )
    ai_token = ai_grant.token

    # Initiative: Alpha (18), Mira (14), Beta (8)
    entries = table.combat.repository.list_entries(combat.id)
    alpha_entry = next(e for e in entries if e.monster_instance_id == alpha.id)
    beta_entry = next(e for e in entries if e.monster_instance_id == beta.id)
    mira_entry = next(e for e in entries if e.character_id == table.character_id)

    dice_map = {alpha_entry.id: 18, mira_entry.id: 14, beta_entry.id: 8}
    req = table.initiative.request_initiative(
        table.dm_actor,
        RequestInitiativeInput(idempotency_key="p4f-init-req"),
    )
    for r in req.requests:
        actor = table.player_actor if r.target_seat_id is not None else table.dm_actor
        table.initiative.complete_initiative(
            actor,
            FormalRollInput(
                roll_request_id=r.id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(dice_map[r.target_combat_entry_id],),
                idempotency_key=f"p4f-init-roll-{r.id}",
            ),
        )

    order = table.initiative.suggested_order(table.dm_actor)
    table.initiative.finalize_initiative(
        table.dm_actor,
        FinalizeInitiativeInput(ordered_entry_ids=order, idempotency_key="p4f-init-fin"),
    )

    # Advance 10 turns so round_number == 4 and current turn is Mira
    for _ in range(10):
        table.combat.advance_turn(table.dm_actor)

    c_at_mira = table.combat.get_active_combat_detail(table.dm_actor)
    assert c_at_mira is not None
    assert c_at_mira.round_number == 4
    assert c_at_mira.current_turn_entry_id == mira_entry.id

    # (a) Request saving throw targeting Player character (Mira)
    st = first_services.core_rolls.request_saving_throws(
        table.dm_actor,
        SavingThrowInput(
            target_entry_ids=(mira_entry.id,),
            dc=14,
            ability_ref="dexterity",
            idempotency_key="p4f-st-req",
        ),
    )
    pending_roll_request_id = st.requests[0].id

    # (b) Player requests attack with range unresolved, creating pending DM adjudication
    atk = first_services.attacks.request_attack(
        table.player_actor,
        AttackRequestInput(
            attacker_entry_id=mira_entry.id,
            target_entry_id=beta_entry.id,
            source_ref="inventory:inventory:longsword",
            range_confirmed=True,
            idempotency_key="p4f-atk-req",
        ),
    )
    assert atk.status == "dm_adjudication_required"
    assert atk.action_id is not None
    adjudication_action_id = atk.action_id

    # (c) Open reaction window for Player character (Mira)
    w = first_services.reaction.open_reaction_window(
        table.dm_actor,
        OpenReactionInput(
            entry_id=mira_entry.id,
            kind=ReactionKind.SHIELD,
            reason="incoming_attack",
            source_entry_id=alpha_entry.id,
            idempotency_key="p4f-rx-open",
        ),
    )
    reaction_window_id = w.window_id

    # Plain dumps before restart
    dm_detail = first_services.combat.get_active_combat_detail(table.dm_actor)
    player_detail = first_services.combat.get_active_combat_detail(table.player_actor)
    assert dm_detail is not None
    assert player_detail is not None

    dm_pending_rolls = first_services.core_rolls.list_pending_rolls(table.dm_actor)
    player_pending_rolls = first_services.core_rolls.list_pending_rolls(table.player_actor)
    rx_window = first_services.reaction.get_reaction_window(table.dm_actor, mira_entry.id)
    assert rx_window is not None
    adj_list = first_services.adjudication.list_pending(table.dm_actor)

    with first_engine.connect() as conn:
        rev = conn.scalar(select(combats.c.revision).where(combats.c.id == combat.id))
        max_seq = conn.scalar(
            select(func.coalesce(func.max(session_events.c.seq), 0)).where(
                session_events.c.session_id == table.session_id
            )
        )

    assert rev is not None
    assert max_seq is not None

    ids = {
        "room_id": str(table.room_id),
        "campaign_id": str(table.campaign_id),
        "session_id": str(table.session_id),
        "dm_token": str(table.dm_token),
        "player_token": str(table.player_token),
        "ai_token": str(ai_token),
        "combat_id": str(combat.id),
        "mira_entry_id": str(mira_entry.id),
        "alpha_entry_id": str(alpha_entry.id),
        "beta_entry_id": str(beta_entry.id),
        "round": int(c_at_mira.round_number),
        "current_turn_entry_id": str(c_at_mira.current_turn_entry_id),
        "pending_roll_request_id": str(pending_roll_request_id),
        "reaction_window_id": str(reaction_window_id),
        "adjudication_action_id": str(adjudication_action_id),
        "dm_detail_dump": dm_detail.model_dump(mode="json"),
        "player_detail_dump": player_detail.model_dump(mode="json"),
        "dm_pending_rolls_dump": [r.model_dump(mode="json") for r in dm_pending_rolls],
        "player_pending_rolls_dump": [r.model_dump(mode="json") for r in player_pending_rolls],
        "reaction_window_dump": rx_window.model_dump(mode="json"),
        "adjudication_list_dump": [a.model_dump(mode="json") for a in adj_list],
        "revision": int(rev),
        "max_seq": int(max_seq),
    }

    first_engine.dispose()
    del first_services
    del table
    return ids


def test_p4f_active_combat_survives_process_restart_and_resolves_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = _build_dataset(monkeypatch)

    assert POSTGRES_URL is not None
    second_engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    s = _Services(second_engine)
    try:
        # Re-authenticate DM, Player, and AI participant
        dm_context = s.rooms.authenticate(UUID(ids["room_id"]), ids["dm_token"])
        player_context = s.rooms.authenticate(UUID(ids["room_id"]), ids["player_token"])
        dm = s.human(ids, dm_context)
        player = s.human(ids, player_context)
        ai_actor = s.ai_participant(ids)
        assert dm.is_current_dm is True
        assert player.role == "player"
        assert ai_actor.actor_kind.value == "ai"

        # Exact restore assertions
        dm_detail = s.combat.get_active_combat_detail(dm)
        assert dm_detail is not None
        assert dm_detail.model_dump(mode="json") == ids["dm_detail_dump"]
        assert dm_detail.round_number == ids["round"] == 4
        assert str(dm_detail.current_turn_entry_id) == ids["current_turn_entry_id"] == ids["mira_entry_id"]

        player_detail = s.combat.get_active_combat_detail(player)
        assert player_detail is not None
        assert player_detail.model_dump(mode="json") == ids["player_detail_dump"]

        # Secrecy rules: Player gets no monster current_hp or armor_class
        for c in player_detail.combatants:
            if c.is_hostile:
                assert "current_hp" not in c.projection
                assert "armor_class" not in c.projection
        for c in dm_detail.combatants:
            if c.is_hostile:
                assert "current_hp" in c.projection
                assert "armor_class" in c.projection

        # Pending rolls match stored
        assert [r.model_dump(mode="json") for r in s.core_rolls.list_pending_rolls(dm)] == ids["dm_pending_rolls_dump"]
        assert [r.model_dump(mode="json") for r in s.core_rolls.list_pending_rolls(player)] == ids["player_pending_rolls_dump"]

        # Reaction window matches stored and is open
        rx_window = s.reaction.get_reaction_window(dm, UUID(ids["mira_entry_id"]))
        assert rx_window is not None
        assert rx_window.model_dump(mode="json") == ids["reaction_window_dump"]
        assert rx_window.status == "open"
        assert rx_window.window_id == ids["reaction_window_id"]

        # Adjudication list matches stored and is pending
        adjudications = s.adjudication.list_pending(dm)
        assert [a.model_dump(mode="json") for a in adjudications] == ids["adjudication_list_dump"]
        assert len(adjudications) == 1
        assert adjudications[0].status == "pending"
        assert str(adjudications[0].action_id) == ids["adjudication_action_id"]

        # Revision and session_events max seq unchanged by reconnect / read
        with s.engine.connect() as conn:
            rev_reconnected = conn.scalar(select(combats.c.revision).where(combats.c.id == UUID(ids["combat_id"])))
            seq_reconnected = conn.scalar(
                select(func.coalesce(func.max(session_events.c.seq), 0)).where(
                    session_events.c.session_id == UUID(ids["session_id"])
                )
            )
        assert rev_reconnected == ids["revision"]
        assert seq_reconnected == ids["max_seq"]

        # AI tool service reads active combat and context
        ai_tool = s.build_ai_tool_service()
        ai_active = ai_tool.combat_get_active(ids["ai_token"])
        assert ai_active["combat"] is not None
        assert ai_active["combat"]["round_number"] == ids["round"] == 4
        assert ai_active["combat"]["current_turn_entry_id"] == ids["current_turn_entry_id"]

        ai_context = ai_tool.combat_get_context(ids["ai_token"])
        assert ai_context["round"] == ids["round"] == 4
        assert ai_context["current_turn_entry_id"] == ids["current_turn_entry_id"]
        assert ai_context["next_required_action"] == "wait_for_event"
        assert len(ai_active["combat"]["entries"]) == 3

        # --- Resolve once each ---

        # 1. Player completes saving throw (physical dice)
        save_res1 = s.core_rolls.complete_saving_throw(
            player,
            FormalRollInput(
                roll_request_id=UUID(ids["pending_roll_request_id"]),
                source=FormalRollSource.PHYSICAL,
                raw_dice=(15,),
                idempotency_key="p4f-resolve-save",
            ),
        )
        with s.engine.connect() as conn:
            rows1 = conn.execute(
                select(roll_results).where(roll_results.c.roll_request_id == UUID(ids["pending_roll_request_id"]))
            ).all()
        assert len(rows1) == 1

        with s.engine.connect() as conn:
            rev_before_save_retry = conn.scalar(select(combats.c.revision).where(combats.c.id == UUID(ids["combat_id"])))
        save_res2 = s.core_rolls.complete_saving_throw(
            player,
            FormalRollInput(
                roll_request_id=UUID(ids["pending_roll_request_id"]),
                source=FormalRollSource.PHYSICAL,
                raw_dice=(15,),
                idempotency_key="p4f-resolve-save",
            ),
        )
        assert save_res2.result_id == save_res1.result_id
        with s.engine.connect() as conn:
            rev_after_save_retry = conn.scalar(select(combats.c.revision).where(combats.c.id == UUID(ids["combat_id"])))
            rows2 = conn.execute(
                select(roll_results).where(roll_results.c.roll_request_id == UUID(ids["pending_roll_request_id"]))
            ).all()
        assert rev_after_save_retry == rev_before_save_retry
        assert len(rows2) == 1

        # 2. Player resolves reaction window (decline)
        rx_res1 = s.reaction.resolve_reaction(
            player,
            ResolveReactionInput(
                owner_entry_id=UUID(ids["mira_entry_id"]),
                accept=False,
                idempotency_key="p4f-resolve-rx",
            ),
        )
        assert rx_res1.status == "declined"
        with s.engine.connect() as conn:
            events_seq1 = conn.scalar(
                select(func.coalesce(func.max(session_events.c.seq), 0)).where(
                    session_events.c.session_id == UUID(ids["session_id"])
                )
            )

        rx_res2 = s.reaction.resolve_reaction(
            player,
            ResolveReactionInput(
                owner_entry_id=UUID(ids["mira_entry_id"]),
                accept=False,
                idempotency_key="p4f-resolve-rx",
            ),
        )
        assert rx_res2.status == "declined"
        with s.engine.connect() as conn:
            events_seq2 = conn.scalar(
                select(func.coalesce(func.max(session_events.c.seq), 0)).where(
                    session_events.c.session_id == UUID(ids["session_id"])
                )
            )
        assert events_seq2 == events_seq1

        # 3. DM resolves adjudication (in range)
        adj_res1 = s.attacks.adjudicate_attack(
            dm,
            AttackAdjudicationInput(
                action_id=UUID(ids["adjudication_action_id"]),
                in_range=True,
                idempotency_key="p4f-resolve-adj",
            ),
        )
        assert adj_res1.status == "waiting_for_roll"
        assert adj_res1.roll_request_id is not None

        adj_res2 = s.attacks.adjudicate_attack(
            dm,
            AttackAdjudicationInput(
                action_id=UUID(ids["adjudication_action_id"]),
                in_range=True,
                idempotency_key="p4f-resolve-adj",
            ),
        )
        assert adj_res2.status == adj_res1.status
        assert adj_res2.roll_request_id == adj_res1.roll_request_id

        # After all three: Player pending rolls has only what adjudication opened; round/turn unchanged
        player_pending_after = s.core_rolls.list_pending_rolls(player)
        assert len(player_pending_after) == 1
        assert player_pending_after[0].id == adj_res1.roll_request_id

        detail_after = s.combat.get_active_combat_detail(dm)
        assert detail_after is not None
        assert detail_after.round_number == 4
        assert str(detail_after.current_turn_entry_id) == ids["mira_entry_id"]

        opened_attack_roll_id = adj_res1.roll_request_id
    finally:
        second_engine.dispose()
        del s

    # Second restart: rebuild from scratch and assert resolved state persisted in PostgreSQL
    third_engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    s3 = _Services(third_engine)
    try:
        dm_ctx3 = s3.rooms.authenticate(UUID(ids["room_id"]), ids["dm_token"])
        player_ctx3 = s3.rooms.authenticate(UUID(ids["room_id"]), ids["player_token"])
        dm3 = s3.human(ids, dm_ctx3)
        player3 = s3.human(ids, player_ctx3)

        # Saving throw remains resolved
        with s3.engine.connect() as conn:
            persisted_results = conn.execute(
                select(roll_results).where(roll_results.c.roll_request_id == UUID(ids["pending_roll_request_id"]))
            ).all()
        assert len(persisted_results) == 1

        # Reaction window is no longer open
        window_after = s3.reaction.get_reaction_window(dm3, UUID(ids["mira_entry_id"]))
        assert window_after is None or window_after.status != "open"

        # Adjudication list is empty
        assert len(s3.adjudication.list_pending(dm3)) == 0

        # Player pending rolls contains only the opened attack roll
        p_rolls = s3.core_rolls.list_pending_rolls(player3)
        assert len(p_rolls) == 1
        assert p_rolls[0].id == opened_attack_roll_id

        # Round and current turn remained untouched
        c_detail3 = s3.combat.get_active_combat_detail(dm3)
        assert c_detail3 is not None
        assert c_detail3.round_number == 4
        assert str(c_detail3.current_turn_entry_id) == ids["mira_entry_id"]
    finally:
        third_engine.dispose()
        del s3
