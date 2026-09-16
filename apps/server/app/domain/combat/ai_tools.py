from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import Field

from app.domain.combat.attacks import (
    AttackAdjudicationInput,
    AttackRequestInput,
    CombatAttackService,
)
from app.domain.combat.core_rolls import (
    CombatCoreRollService,
    DeathSaveRequestInput,
    SavingThrowInput,
)
from app.domain.combat.lifecycle import CombatService
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


class CombatEntryToolInput(StrictModel):
    entry_id: UUID


class CombatRollToolInput(StrictModel):
    roll_request_id: UUID
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


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
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.combat_service = combat_service
        self.combat_attack_service = combat_attack_service
        self.combat_resolution_service = combat_resolution_service
        self.combat_core_roll_service = combat_core_roll_service
        self.combat_special_attack_service = combat_special_attack_service

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


__all__ = [
    "CombatAIToolApplicationService",
    "CombatEntryToolInput",
    "CombatRollToolInput",
]
