from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import Field

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
    ProposeAoeSpellInput,
    ResolveAoeSpellInput,
    SpellCastView,
)
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
from app.domain.rooms.ai_controllers import AIControllerAuthView
from app.domain.rooms.ai_tools import AIToolApplicationService
from app.domain.rooms.rolls import FormalRollInput, FormalRollSource
from app.domain.rooms.schemas import StrictModel
from app.domain.rooms.table_events import TableActorContext


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
        **kwargs: Any,
    ) -> None:
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

    def _combat_context(self, actor: TableActorContext) -> dict[str, Any]:
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
        return {
            "combat": detail.model_dump(mode="json") if detail is not None else None,
            "current_turn_entry_id": str(current_turn_entry_id) if current_turn_entry_id else None,
            "round": detail.round_number if detail is not None else None,
            "my_entry_ids": [str(entry_id) for entry_id in sorted(my_entry_ids, key=str)],
            "pending_roll_requests": [request.model_dump(mode="json") for request in pending_requests],
            "reaction_windows": [window.model_dump(mode="json") for window in reaction_windows],
            "pending_adjudications": [item.model_dump(mode="json") for item in adjudications],
            "next_required_action": next_action,
        }

    def combat_get_context(
        self,
        token: str,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self._combat_context(actor)

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


__all__ = [
    "CombatAIToolApplicationService",
    "CombatAdjudicationDecisionToolInput",
    "CombatEntryMutationToolInput",
    "CombatEntryToolInput",
    "CombatMutationToolInput",
    "CombatRollToolInput",
    "next_combat_action",
]
