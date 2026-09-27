from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from app.domain.battle_maps.schemas import (
    BattleMapCreate,
    BattleMapObjectsReplace,
    BattleMapPatch,
)
from app.domain.battle_maps.service import BattleMapService
from app.domain.combat.adjudication_service import (
    AdjudicationDecisionInput,
    CombatAdjudicationService,
    CombatAdjudicationView,
    OpportunityAttackRequestInput,
    SpecialAdjudicationRequestInput,
)
from app.domain.combat.attacks import (
    AttackAdjudicationInput,
    AttackRequestInput,
    CombatAttackService,
)
from app.domain.combat.board import (
    CombatBoardService,
    PlaceCombatantInput,
    UpdateDoorStateInput,
)
from app.domain.combat.concentration import (
    CombatConcentrationService,
    ConcentrationCheckResultView,
    DropConcentrationView,
)
from app.domain.combat.core_rolls import (
    CombatCoreRollService,
    DeathSaveRequestInput,
    SavingThrowInput,
)
from app.domain.combat.initiative import (
    CombatInitiativeService,
    FinalizeInitiativeInput,
    RequestInitiativeInput,
)
from app.domain.combat.lifecycle import (
    AddCharacterInput,
    AddMonsterInput,
    CombatActionInput,
    CombatDetailView,
    CombatService,
    MonsterOutcomeInput,
    StartCombatInput,
    StartTacticalCombatInput,
)
from app.domain.combat.movement import (
    CancelPendingMovementInput,
    ConfirmMovementInput,
    MovementService,
    PreviewMovementInput,
    RepositionInput,
    ResumeMovementInput,
)
from app.domain.combat.reaction_service import (
    CombatReactionService,
    OpenReactionInput,
    ReactionResolutionView,
    ReactionWindowView,
    ResolveReactionInput,
)
from app.domain.combat.spell_service import (
    AoeSpellProposalView,
    AoeSpellResolutionView,
    CastSpellInput,
    CombatSpellService,
    PreviewAoeSpellInput,
    ProposeAoeSpellInput,
    ResolveAoeSpellInput,
    SpellCastView,
)
from app.domain.combat.target_check import TargetCheckInput, TargetCheckService
from app.domain.combat.monster_instances import (
    CreateMonsterFromContentInput,
    CreateQuickEnemyInput,
    MonsterInstanceService,
    MonsterInstanceUpdateToolInput,
)
from app.domain.combat.semantic_hp import (
    CombatResolutionService,
    SemanticDamageInput,
    SemanticHealingInput,
    SemanticResolutionView,
)
from app.domain.combat.special_attacks import (
    CombatSpecialAttackService,
    SpecialAttackAdjudicationInput,
    SpecialAttackRequestInput,
)
from app.domain.rooms.ai_controllers import AIControllerAuthView, AIControllerUnauthorizedError
from app.domain.rooms.ai_guidance import BRIEFING_MAX_CHARS
from app.domain.rooms.ai_tools import AIToolApplicationService, AIToolScopeError
from app.domain.rooms.rolls import FormalRollInput, FormalRollSource
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext, StrictModel
from app.domain.rooms.table_events import TableActorContext
from app.domain.spatial.pathing import grid_distance
from app.domain.spatial.primitives import Footprint, occupied_cells


class CombatEntryToolInput(StrictModel):
    entry_id: UUID


class CombatRollToolInput(StrictModel):
    roll_request_id: UUID
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class CombatMutationToolInput(StrictModel):
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class CombatEntryMutationToolInput(StrictModel):
    entry_id: UUID
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class CombatPlaceTokenToolInput(StrictModel):
    """P5-F: entry_id plus the PlaceCombatantInput coordinates."""

    entry_id: UUID
    anchor_x: int = Field(ge=0, le=200)
    anchor_y: int = Field(ge=0, le=200)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class CombatSetDoorStateToolInput(StrictModel):
    """P5-F: door_id plus the UpdateDoorStateInput fields."""

    door_id: UUID
    state: Literal["open", "closed", "locked", "broken"]
    revealed: bool | None = None
    expected_runtime_revision: int = Field(ge=1)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class CombatRepositionToolInput(StrictModel):
    """P5-F: entry_id plus the RepositionInput fields (DM correction)."""

    entry_id: UUID
    anchor_x: int = Field(ge=0, le=200)
    anchor_y: int = Field(ge=0, le=200)
    reason: str = Field(min_length=1, max_length=500)
    expected_position_revision: int = Field(ge=0)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class BattleMapIdToolInput(StrictModel):
    """P5-F: battle-map editor tools address a map by id; room comes from the actor."""

    map_id: UUID


class BattleMapCreateToolInput(StrictModel):
    payload: BattleMapCreate


class BattleMapPatchToolInput(StrictModel):
    map_id: UUID
    payload: BattleMapPatch


class BattleMapReplaceObjectsToolInput(StrictModel):
    map_id: UUID
    payload: BattleMapObjectsReplace


class CombatAdjudicationDecisionToolInput(AdjudicationDecisionInput):
    action_id: UUID


_ADJUDICATION_KIND_TO_HINT: dict[str, str] = {
    "range": "adjudicate_attack",
    "reach": "adjudicate_special_attack",
    "affected_targets": "resolve_aoe_spell",
    "opportunity_attack": "resolve_adjudication",
    "special": "resolve_adjudication",
}


def next_combat_action(
    *,
    is_dm: bool,
    current_turn_entry_id: UUID | None,
    current_turn_is_monster: bool,
    my_entry_ids: frozenset[UUID],
    pending_adjudication_kinds: tuple[str, ...],
    has_open_reaction: bool,
    has_pending_roll: bool,
    current_turn_done: bool = False,
) -> str:
    """Compact next-step hint shared by get_combat_context and (E8) get_session_context."""
    if is_dm:
        if pending_adjudication_kinds:
            first_kind = pending_adjudication_kinds[0]
            if first_kind not in _ADJUDICATION_KIND_TO_HINT:
                raise ValueError(f"Unknown adjudication kind: {first_kind}")
            return _ADJUDICATION_KIND_TO_HINT[first_kind]
        if current_turn_is_monster:
            return "take_turn"
        # Turn advance is DM-authoritative: once the Player's action is spent and
        # nothing is pending, waiting would leave the table stuck (F8 finding).
        if current_turn_done and not has_open_reaction:
            return "advance_turn"
        return "wait_for_event"
    if has_pending_roll:
        return "roll_pending"
    if has_open_reaction:
        return "respond_to_reaction"
    if current_turn_entry_id is not None and current_turn_entry_id in my_entry_ids:
        return "take_turn"
    return "wait_for_event"


class CombatAIToolApplicationService(AIToolApplicationService):
    """P4-C MCP facade that delegates every rule decision to shared Combat services.

    This class intentionally contains no hit, damage, save, death-save, geometry,
    or opposed-check calculation. Human REST and MCP therefore share the same
    authoritative P4-C application services and transaction boundaries.
    """

    def __init__(
        self,
        *,
        combat_service: CombatService,
        combat_attack_service: CombatAttackService,
        combat_resolution_service: CombatResolutionService,
        combat_core_roll_service: CombatCoreRollService,
        combat_special_attack_service: CombatSpecialAttackService,
        combat_initiative_service: CombatInitiativeService,
        monster_instance_service: MonsterInstanceService,
        combat_spell_service: CombatSpellService,
        combat_concentration_service: CombatConcentrationService,
        combat_reaction_service: CombatReactionService,
        combat_adjudication_service: CombatAdjudicationService,
        movement_service: MovementService | None = None,
        combat_board_service: CombatBoardService | None = None,
        battle_map_service: BattleMapService | None = None,
        target_check_service: TargetCheckService | None = None,
        **kwargs: Any,
    ) -> None:
        # P5-F: the four tactical services are optional at construction so
        # pre-F1 call sites (P4-E fixtures) keep working; each tactical tool
        # requires its service at call time instead.
        super().__init__(**kwargs)
        self.combat_service = combat_service
        self.combat_attack_service = combat_attack_service
        self.combat_resolution_service = combat_resolution_service
        self.combat_core_roll_service = combat_core_roll_service
        self.combat_special_attack_service = combat_special_attack_service
        self.combat_initiative_service = combat_initiative_service
        self.monster_instance_service = monster_instance_service
        self.combat_spell_service = combat_spell_service
        self.combat_concentration_service = combat_concentration_service
        self.combat_reaction_service = combat_reaction_service
        self.combat_adjudication_service = combat_adjudication_service
        self.movement_service = movement_service
        self.combat_board_service = combat_board_service
        self.battle_map_service = battle_map_service
        self.target_check_service = target_check_service

    def _require_movement_service(self) -> MovementService:
        if self.movement_service is None:
            raise RuntimeError("MovementService is not wired on this facade")
        return self.movement_service

    def _require_board_service(self) -> CombatBoardService:
        if self.combat_board_service is None:
            raise RuntimeError("CombatBoardService is not wired on this facade")
        return self.combat_board_service

    def _require_battle_map_service(self) -> BattleMapService:
        if self.battle_map_service is None:
            raise RuntimeError("BattleMapService is not wired on this facade")
        return self.battle_map_service

    def _require_target_check_service(self) -> TargetCheckService:
        if self.target_check_service is None:
            raise RuntimeError("TargetCheckService is not wired on this facade")
        return self.target_check_service

    @staticmethod
    def _semantic_resolution(result: SemanticResolutionView) -> dict[str, Any]:
        # The view is already projected for the acting actor; redacted HP fields
        # are dropped rather than sent as null so a Player never sees the key.
        return result.model_dump(mode="json", exclude_none=True)

    @staticmethod
    def _server_roll(input: CombatRollToolInput) -> FormalRollInput:
        return FormalRollInput(
            roll_request_id=input.roll_request_id,
            source=FormalRollSource.SERVER,
            idempotency_key=input.idempotency_key,
        )

    def combat_get_active(
        self,
        token: str,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        combat = self.combat_service.get_active_combat(actor)
        return {"combat": combat.model_dump(mode="json") if combat is not None else None}

    def combat_list_attacks(
        self,
        token: str,
        input: CombatEntryToolInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        attacks = self.combat_attack_service.available_attacks(actor, input.entry_id)
        return {"attacks": [item.model_dump(mode="json") for item in attacks]}

    def combat_request_attack(
        self,
        token: str,
        input: AttackRequestInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self.combat_attack_service.request_attack(actor, input).model_dump(mode="json")

    def combat_adjudicate_attack(
        self,
        token: str,
        input: AttackAdjudicationInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self.combat_attack_service.adjudicate_attack(actor, input).model_dump(mode="json")

    def combat_roll_attack(
        self,
        token: str,
        input: CombatRollToolInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self.combat_attack_service.complete_attack(
            actor, self._server_roll(input)
        ).model_dump(mode="json")

    def combat_apply_damage(
        self,
        token: str,
        input: SemanticDamageInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self._semantic_resolution(
            self.combat_resolution_service.apply_damage(actor, input)
        )

    def combat_apply_healing(
        self,
        token: str,
        input: SemanticHealingInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self._semantic_resolution(
            self.combat_resolution_service.apply_healing(actor, input)
        )

    def combat_request_saving_throws(
        self,
        token: str,
        input: SavingThrowInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self.combat_core_roll_service.request_saving_throws(
            actor, input
        ).model_dump(mode="json")

    def combat_roll_saving_throw(
        self,
        token: str,
        input: CombatRollToolInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self.combat_core_roll_service.complete_saving_throw(
            actor, self._server_roll(input)
        ).model_dump(mode="json")

    def combat_request_death_save(
        self,
        token: str,
        input: DeathSaveRequestInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self.combat_core_roll_service.request_death_save(
            actor, input
        ).model_dump(mode="json")

    def combat_roll_death_save(
        self,
        token: str,
        input: CombatRollToolInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self.combat_core_roll_service.complete_death_save(
            actor, self._server_roll(input)
        ).model_dump(mode="json")

    def combat_request_special_attack(
        self,
        token: str,
        input: SpecialAttackRequestInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self.combat_special_attack_service.request_special_attack(
            actor, input
        ).model_dump(mode="json")

    def combat_adjudicate_special_attack(
        self,
        token: str,
        input: SpecialAttackAdjudicationInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self.combat_special_attack_service.adjudicate_special_attack(
            actor, input
        ).model_dump(mode="json")

    def combat_roll_special_attack(
        self,
        token: str,
        input: CombatRollToolInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self.combat_special_attack_service.complete_special_attack_roll(
            actor, self._server_roll(input)
        ).model_dump(mode="json")

    def combat_start(
        self,
        token: str,
        input: StartCombatInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self.combat_service.start_quick_combat(actor, input).model_dump(mode="json")

    def combat_add_character(
        self,
        token: str,
        input: AddCharacterInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self.combat_service.add_character(actor, input).model_dump(mode="json")

    def combat_add_monster(
        self,
        token: str,
        input: AddMonsterInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self.combat_service.add_monster(actor, input).model_dump(mode="json")

    def combat_create_monster(
        self,
        token: str,
        input: CreateMonsterFromContentInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self.monster_instance_service.create_from_content(actor, input).model_dump(mode="json")

    def combat_create_quick_enemy(
        self,
        token: str,
        input: CreateQuickEnemyInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self.monster_instance_service.create_quick_enemy(actor, input).model_dump(mode="json")

    def combat_list_monster_instances(
        self,
        token: str,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        instances = self.monster_instance_service.list_instances(actor)
        return {"instances": [inst.model_dump(mode="json") for inst in instances]}

    def combat_update_monster_instance(
        self,
        token: str,
        input: MonsterInstanceUpdateToolInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self.monster_instance_service.update_instance(
            actor, input.instance_id, input
        ).model_dump(mode="json")

    def combat_request_initiative(
        self,
        token: str,
        input: RequestInitiativeInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self.combat_initiative_service.request_initiative(actor, input).model_dump(mode="json")

    def combat_roll_initiative(
        self,
        token: str,
        input: CombatRollToolInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self.combat_initiative_service.complete_initiative(
            actor, self._server_roll(input)
        ).model_dump(mode="json")

    def combat_finalize_initiative(
        self,
        token: str,
        input: FinalizeInitiativeInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self.combat_initiative_service.finalize_initiative(actor, input).model_dump(mode="json")

    def combat_advance_turn(
        self,
        token: str,
        input: CombatMutationToolInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self.combat_service.advance_turn(actor, idempotency_key=input.idempotency_key).model_dump(mode="json")

    def combat_use_action(
        self,
        token: str,
        input: CombatActionInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self.combat_service.use_action(actor, input).model_dump(mode="json")

    def combat_withdraw_entry(
        self,
        token: str,
        input: CombatEntryMutationToolInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self.combat_service.withdraw_entry(actor, input.entry_id, idempotency_key=input.idempotency_key).model_dump(mode="json")

    def combat_remove_entry(
        self,
        token: str,
        input: CombatEntryMutationToolInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self.combat_service.remove_entry(actor, input.entry_id, idempotency_key=input.idempotency_key).model_dump(mode="json")

    def combat_set_monster_outcome(
        self,
        token: str,
        input: MonsterOutcomeInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self.combat_service.set_monster_outcome(actor, input).model_dump(mode="json")

    def combat_end(
        self,
        token: str,
        input: CombatMutationToolInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self.combat_service.end_combat(actor, idempotency_key=input.idempotency_key).model_dump(mode="json")

    def _combat_context(
        self, actor: TableActorContext
    ) -> dict[str, Any]:
        # Single-value contract (pre-F1): P6-C and other call sites stub or
        # consume this as a plain payload dict. The combat detail needed for
        # the tactical summary is fetched separately by get_session_context.
        detail = self.combat_service.get_active_combat_detail(actor)
        current_turn_entry_id = detail.current_turn_entry_id if detail is not None else None

        my_entry_ids: set[UUID] = set()
        current_turn_is_monster = False
        current_turn_action_spent = False
        if detail is not None:
            for entry in detail.entries:
                if entry.id == current_turn_entry_id:
                    current_turn_is_monster = entry.subject_kind == "monster"
                    current_turn_action_spent = not entry.action_available
                if entry.status != "active":
                    continue
                if actor.is_current_dm:
                    my_entry_ids.add(entry.id)
                elif entry.character_id is not None:
                    controlling_seat = self.combat_service.repository.controlling_seat_for_character(
                        campaign_id=actor.campaign_id,
                        session_id=actor.session_id,
                        character_id=entry.character_id,
                    )
                    if controlling_seat in actor.controlled_seat_ids:
                        my_entry_ids.add(entry.id)

        pending_requests = self.combat_core_roll_service.list_pending_rolls(actor)
        has_pending_roll = any(
            request.target_seat_id in actor.controlled_seat_ids for request in pending_requests
        )

        reaction_windows = []
        adjudications = ()
        if detail is not None:
            for entry_id in my_entry_ids:
                window = self.combat_reaction_service.get_reaction_window(actor, entry_id)
                if window is not None and window.status == "open":
                    reaction_windows.append(window)
            adjudications = self.combat_adjudication_service.list_pending(actor)

        pending_adjudication_kinds = tuple(
            adj.kind for adj in sorted(adjudications, key=lambda a: a.created_at)
        )
        next_action = next_combat_action(
            is_dm=actor.is_current_dm,
            current_turn_entry_id=current_turn_entry_id,
            current_turn_is_monster=current_turn_is_monster,
            my_entry_ids=frozenset(my_entry_ids),
            pending_adjudication_kinds=pending_adjudication_kinds,
            has_open_reaction=bool(reaction_windows),
            has_pending_roll=has_pending_roll,
            current_turn_done=current_turn_action_spent and not pending_requests,
        )
        payload = {
            "combat": detail.model_dump(mode="json") if detail is not None else None,
            "current_turn_entry_id": str(current_turn_entry_id) if current_turn_entry_id else None,
            "round": detail.round_number if detail is not None else None,
            "my_entry_ids": [str(entry_id) for entry_id in sorted(my_entry_ids, key=str)],
            "pending_roll_requests": [request.model_dump(mode="json") for request in pending_requests],
            "reaction_windows": [window.model_dump(mode="json") for window in reaction_windows],
            "pending_adjudications": [item.model_dump(mode="json") for item in adjudications],
            "next_required_action": next_action,
        }
        return payload

    _TACTICAL_SUMMARY_MAX_SUBJECTS = 5
    _TACTICAL_SUMMARY_MAX_VISIBLE = 6
    _TACTICAL_SUMMARY_NAME_LIMIT = 24

    def _tactical_summary(
        self,
        actor: TableActorContext,
        detail: CombatDetailView,
        combat_ctx: dict[str, Any],
        *,
        name_limit: int = _TACTICAL_SUMMARY_NAME_LIMIT,
        max_subjects: int = _TACTICAL_SUMMARY_MAX_SUBJECTS,
        max_visible: int = _TACTICAL_SUMMARY_MAX_VISIBLE,
    ) -> str:
        """P5-F compact bilingual tactical snapshot appended to the briefing.

        Bounded (no ASCII map): at most ``max_subjects`` subjects and
        ``max_visible`` visible combatants, names truncated to ``name_limit``
        chars. Every position comes from the actor-projected board, so
        Players never see hidden truth here.

        Names come from the combatant projection, falling back to the
        entry's display_name; when both are missing the name field is
        omitted entirely (never a "?" placeholder).
        """
        board = self._require_board_service().get_board(actor)
        pos_by_entry = {position.entry_id: position for position in board.positions}
        projection_names = {}
        for combatant in detail.combatants:
            raw_name = combatant.projection.get("name")
            if isinstance(raw_name, str) and raw_name.strip():
                projection_names[combatant.entry_id] = raw_name.strip()
        display_names = {
            entry.id: entry.display_name.strip()
            for entry in detail.entries
            if entry.display_name and entry.display_name.strip()
        }

        def display_name(entry_id) -> str | None:
            name = projection_names.get(entry_id) or display_names.get(entry_id)
            return name[:name_limit] if name else None

        running = detail.status == "running"

        def cells_of(position) -> tuple:
            return occupied_cells(
                position.anchor_x,
                position.anchor_y,
                Footprint(
                    width=position.footprint_width,
                    height=position.footprint_height,
                ),
            )

        my_ids = [UUID(raw) for raw in combat_ctx["my_entry_ids"]]
        positioned = [entry_id for entry_id in my_ids if entry_id in pos_by_entry]
        subject_parts: list[str] = []
        pending_movement: list[str] = []
        reference_cells = None
        for entry_id in positioned[:max_subjects]:
            position = pos_by_entry[entry_id]
            name = display_name(entry_id)
            part = (
                f"{name}({position.anchor_x},{position.anchor_y})"
                if name
                else f"({position.anchor_x},{position.anchor_y})"
            )
            if running:
                status = self._require_movement_service().movement_status(actor, entry_id)
                part += f" {status.used_feet}/{status.budget_feet}ft"
                if status.has_pending_movement:
                    pending_movement.append(name or f"entry {str(entry_id)[:8]}")
            subject_parts.append(part)
            if reference_cells is None:
                reference_cells = cells_of(position)
        more_subjects = len(positioned) - len(subject_parts)

        if reference_cells is None and detail.current_turn_entry_id is not None:
            turn_position = pos_by_entry.get(detail.current_turn_entry_id)
            if turn_position is not None:
                reference_cells = cells_of(turn_position)

        def distance_of(position) -> int:
            if reference_cells is None:
                return 0
            return grid_distance(reference_cells, cells_of(position)).feet

        visible = sorted(
            board.positions,
            key=lambda p: (distance_of(p), p.anchor_x, p.anchor_y),
        )
        visible_parts = []
        for position in visible[:max_visible]:
            name = display_name(position.entry_id)
            label = (
                f"{name}({position.anchor_x},{position.anchor_y})"
                if name
                else f"({position.anchor_x},{position.anchor_y})"
            )
            visible_parts.append(f"{label} {distance_of(position)}ft")
        more_visible = len(visible) - len(visible_parts)

        turn_clause = f"Round {detail.round_number}"
        if detail.current_turn_entry_id is not None:
            turn_name = display_name(detail.current_turn_entry_id)
            if turn_name:
                turn_clause += f", turn: {turn_name}"
        turn_clause += "."
        reaction_count = len(combat_ctx.get("reaction_windows", ()))
        subjects_text = "; ".join(subject_parts) or "none"
        if more_subjects:
            subjects_text += f" (+{more_subjects} more)"
        visible_text = "; ".join(visible_parts) or "none"
        if more_visible:
            visible_text += f" (+{more_visible} more)"
        pending_text = ", ".join(pending_movement) if pending_movement else "none"
        if reaction_count:
            kinds = sorted(
                {str(window.get("kind")) for window in combat_ctx["reaction_windows"]}
            )
            reaction_text = f"{reaction_count} open ({', '.join(kinds)})"
        else:
            reaction_text = "none"
        return " ".join(
            [
                f"Tactical 戰術 [mode=tactical]: {turn_clause}",
                f"Your units 你的單位: {subjects_text}.",
                f"Visible by distance 可見（依距離）: {visible_text}.",
                f"Pending movement 待處理移動: {pending_text}.",
                f"Pending reaction 待處理反應: {reaction_text}.",
                f"Next 下一步: {combat_ctx['next_required_action']}.",
            ]
        )

    def _bounded_tactical_summary(
        self,
        actor: TableActorContext,
        detail: CombatDetailView,
        combat_ctx: dict[str, Any],
        *,
        budget: int,
    ) -> str:
        """Render the tactical summary so ``static + summary`` stays in budget.

        Progressively tightens (visible rows, subject rows, name length) and,
        as a last resort, cuts at a sentence boundary. Never raises: this
        runs on the per-round AI path, so an over-long summary must shrink,
        not 500.
        """
        if budget <= 0:
            return ""
        tightening = (
            (self._TACTICAL_SUMMARY_NAME_LIMIT, self._TACTICAL_SUMMARY_MAX_SUBJECTS, self._TACTICAL_SUMMARY_MAX_VISIBLE),
            (self._TACTICAL_SUMMARY_NAME_LIMIT, self._TACTICAL_SUMMARY_MAX_SUBJECTS, 4),
            (self._TACTICAL_SUMMARY_NAME_LIMIT, self._TACTICAL_SUMMARY_MAX_SUBJECTS, 2),
            (self._TACTICAL_SUMMARY_NAME_LIMIT, 3, 2),
            (self._TACTICAL_SUMMARY_NAME_LIMIT, 2, 2),
            (16, 2, 2),
            (8, 1, 1),
        )
        summary = ""
        for name_limit, max_subjects, max_visible in tightening:
            summary = self._tactical_summary(
                actor,
                detail,
                combat_ctx,
                name_limit=name_limit,
                max_subjects=max_subjects,
                max_visible=max_visible,
            )
            if len(summary) <= budget:
                return summary
        # Last resort: cut at the last sentence boundary inside the budget so
        # no unlucky combination can ever break the 3000-char contract.
        cut = summary.rfind(". ", 0, budget)
        if cut < 0:
            return summary[:budget]
        return summary[: cut + 1]

    def combat_get_context(
        self,
        token: str,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        payload = self._combat_context(actor)
        return payload

    def get_session_context(
        self,
        token: str,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        payload = super().get_session_context(token, authenticated=authenticated)
        if payload.get("mode") != "active_session":
            return payload

        actor = self._actor(token, authenticated=authenticated)
        combat_ctx = self._combat_context(actor)
        if combat_ctx["combat"] is None:
            payload["combat"] = None
            return payload

        payload["combat"] = combat_ctx
        payload["next_required_action"] = combat_ctx["next_required_action"]
        detail = self.combat_service.get_active_combat_detail(actor)
        if detail is not None and detail.mode == "tactical":
            static = self._briefing(role=actor.role, mode="active_tactical_combat")
            # P5-F F1b: the summary is always bounded to the remaining budget.
            # It never raises — this runs on the per-round AI path, so an
            # over-long summary must shrink, not 500.
            budget = BRIEFING_MAX_CHARS - len(static) - 1
            summary = self._bounded_tactical_summary(actor, detail, combat_ctx, budget=budget)
            payload["briefing"] = f"{static}\n{summary}"
        else:
            payload["briefing"] = self._briefing(role=actor.role, mode="active_combat")
        return payload

    def combat_cast_spell(
        self,
        token: str,
        input: CastSpellInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self.combat_spell_service.cast_spell(actor, input).model_dump(mode="json")

    def combat_propose_aoe_spell(
        self,
        token: str,
        input: ProposeAoeSpellInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self.combat_spell_service.propose_aoe(actor, input).model_dump(mode="json")

    def combat_resolve_aoe_spell(
        self,
        token: str,
        input: ResolveAoeSpellInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self.combat_spell_service.resolve_aoe(actor, input).model_dump(mode="json")

    def combat_roll_concentration(
        self,
        token: str,
        input: CombatRollToolInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self.combat_concentration_service.complete_check(
            actor, self._server_roll(input)
        ).model_dump(mode="json")

    def combat_drop_concentration(
        self,
        token: str,
        input: CombatEntryMutationToolInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self.combat_concentration_service.drop_concentration(
            actor, input.entry_id, idempotency_key=input.idempotency_key
        ).model_dump(mode="json")

    def combat_open_reaction_window(
        self,
        token: str,
        input: OpenReactionInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self.combat_reaction_service.open_reaction_window(
            actor, input
        ).model_dump(mode="json")

    def combat_respond_to_reaction(
        self,
        token: str,
        input: ResolveReactionInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self.combat_reaction_service.resolve_reaction(
            actor, input
        ).model_dump(mode="json")

    def combat_request_opportunity_attack(
        self,
        token: str,
        input: OpportunityAttackRequestInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self.combat_adjudication_service.request_opportunity_attack(
            actor, input
        ).model_dump(mode="json")

    def combat_request_adjudication(
        self,
        token: str,
        input: SpecialAdjudicationRequestInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self.combat_adjudication_service.request_special(
            actor, input
        ).model_dump(mode="json")

    def combat_resolve_adjudication(
        self,
        token: str,
        input: CombatAdjudicationDecisionToolInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self.combat_adjudication_service.resolve_adjudication(
            actor, input.action_id, input
        ).model_dump(mode="json")

    # ------------------------------------------------------------------
    # P5-F tactical MCP tools. Every method resolves the actor (which
    # re-validates the grant on each call) and delegates to the same domain
    # services Human REST uses. No rule logic lives here.
    # ------------------------------------------------------------------

    def combat_start_tactical(
        self,
        token: str,
        input: StartTacticalCombatInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self.combat_service.start_tactical_combat(
            actor, input
        ).model_dump(mode="json")

    def combat_get_board(
        self,
        token: str,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self._require_board_service().get_board(actor).model_dump(mode="json")

    def combat_place_token(
        self,
        token: str,
        input: CombatPlaceTokenToolInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self._require_board_service().place_position(
            actor,
            input.entry_id,
            PlaceCombatantInput(
                anchor_x=input.anchor_x,
                anchor_y=input.anchor_y,
                idempotency_key=input.idempotency_key,
            ),
        ).model_dump(mode="json")

    def combat_reposition(
        self,
        token: str,
        input: CombatRepositionToolInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self._require_movement_service().reposition(
            actor,
            input.entry_id,
            RepositionInput(
                entry_id=input.entry_id,
                anchor_x=input.anchor_x,
                anchor_y=input.anchor_y,
                reason=input.reason,
                expected_position_revision=input.expected_position_revision,
                idempotency_key=input.idempotency_key,
            ),
        ).model_dump(mode="json")

    def combat_set_door_state(
        self,
        token: str,
        input: CombatSetDoorStateToolInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self._require_board_service().update_door_state(
            actor,
            input.door_id,
            UpdateDoorStateInput(
                state=input.state,
                revealed=input.revealed,
                expected_runtime_revision=input.expected_runtime_revision,
                idempotency_key=input.idempotency_key,
            ),
        ).model_dump(mode="json")

    def combat_preview_movement(
        self,
        token: str,
        input: PreviewMovementInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self._require_movement_service().preview(
            actor, input.entry_id, input
        ).model_dump(mode="json")

    def combat_confirm_movement(
        self,
        token: str,
        input: ConfirmMovementInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self._require_movement_service().confirm(
            actor, input.entry_id, input
        ).model_dump(mode="json")

    def combat_resume_movement(
        self,
        token: str,
        input: ResumeMovementInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self._require_movement_service().resume(
            actor, input.entry_id, input
        ).model_dump(mode="json")

    def combat_cancel_pending_movement(
        self,
        token: str,
        input: CancelPendingMovementInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self._require_movement_service().cancel_pending_movement(
            actor, input.entry_id, input
        ).model_dump(mode="json")

    def combat_check_target(
        self,
        token: str,
        input: TargetCheckInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self._require_target_check_service().check_target(
            actor, input
        ).model_dump(mode="json")

    def combat_preview_aoe(
        self,
        token: str,
        input: PreviewAoeSpellInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        preview = self.combat_spell_service.preview_aoe(actor, input)
        # AoeSpellPreview is a frozen dataclass (no model_dump); map it to the
        # same shape the REST preview route returns via AoeSpellPreviewResponse.
        template = preview.template
        return {
            "combat_id": str(preview.combat_id),
            "caster_entry_id": str(preview.caster_entry_id),
            "spell_ref": preview.spell_ref,
            "board_revision": preview.board_revision,
            "template": {
                "shape": template.kind,
                "size_feet": template.size_feet,
                "origin_x": template.origin_x,
                "origin_y": template.origin_y,
                "aim_x": template.aim_x,
                "aim_y": template.aim_y,
                "direction": template.direction,
            },
            "affected_cells": [
                {"x": cell.x, "y": cell.y} for cell in preview.affected_cells
            ],
            "candidates": [
                {
                    "entry_id": str(candidate.entry_id),
                    "display_name": candidate.display_name,
                    "subject_kind": candidate.subject_kind,
                }
                for candidate in preview.candidates
            ],
        }

    def _room_access_context(self, actor: TableActorContext) -> RoomAccessContext:
        """Translate an authenticated AI DM actor into a room access context.

        The MCP catalog gates battle-map tools to role="dm" and _actor()
        re-validates the grant on every call, so authority=DM is faithful, not
        fabricated. The grant id identifies the AI access session for the
        battle-map service, which only needs it as an identifier.
        """
        if actor.ai_controller_grant_id is None:
            raise AIControllerUnauthorizedError(
                "AI battle-map tools require an AI controller grant"
            )
        if actor.session_id is None or not actor.is_current_dm:
            # P5-F F1b: battle maps are Room-level shared assets; only the
            # current DM of an active Session may set them up or edit them.
            # A pre-session DM grant (P3-D) gets minimal context + Start only,
            # and non-DM roles are gated here even when the MCP catalog gate
            # is bypassed by calling the facade directly.
            raise AIToolScopeError(
                "Battle-map tools require the current DM of an active Session"
            )
        return RoomAccessContext(
            room_id=actor.room_id,
            access_session_id=actor.ai_controller_grant_id,
            authority=RoomAccessAuthority.DM,
        )

    def battle_map_create(
        self,
        token: str,
        input: BattleMapCreateToolInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        view = self._require_battle_map_service().create(
            self._room_access_context(actor),
            room_id=actor.room_id,
            payload=input.payload,
        )
        return view.model_dump(mode="json")

    def battle_map_get(
        self,
        token: str,
        input: BattleMapIdToolInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        view = self._require_battle_map_service().get(
            self._room_access_context(actor), actor.room_id, input.map_id
        )
        return view.model_dump(mode="json")

    def battle_map_list(
        self,
        token: str,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        views = self._require_battle_map_service().list(
            self._room_access_context(actor), actor.room_id
        )
        return {"battle_maps": [view.model_dump(mode="json") for view in views]}

    def battle_map_patch(
        self,
        token: str,
        input: BattleMapPatchToolInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        view = self._require_battle_map_service().patch(
            self._room_access_context(actor),
            room_id=actor.room_id,
            map_id=input.map_id,
            payload=input.payload,
        )
        return view.model_dump(mode="json")

    def battle_map_replace_objects(
        self,
        token: str,
        input: BattleMapReplaceObjectsToolInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        view = self._require_battle_map_service().replace_objects(
            self._room_access_context(actor),
            room_id=actor.room_id,
            map_id=input.map_id,
            payload=input.payload,
        )
        return view.model_dump(mode="json")


__all__ = [
    "BattleMapCreateToolInput",
    "BattleMapIdToolInput",
    "BattleMapPatchToolInput",
    "BattleMapReplaceObjectsToolInput",
    "CombatAIToolApplicationService",
    "CombatAdjudicationDecisionToolInput",
    "CombatEntryMutationToolInput",
    "CombatEntryToolInput",
    "CombatMutationToolInput",
    "CombatPlaceTokenToolInput",
    "CombatRepositionToolInput",
    "CombatRollToolInput",
    "CombatSetDoorStateToolInput",
    "next_combat_action",
]
