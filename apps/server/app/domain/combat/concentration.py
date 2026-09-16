from __future__ import annotations

from typing import Any
from uuid import UUID

from app.domain.combat.concentration_triggers import monster_save_modifier
from app.domain.rooms.rolls import (
    FormalRollInput,
    FormalRollSource,
    RollModifierMode,
    RollRequestType,
    RollService,
)
from app.domain.rooms.schemas import StrictModel
from app.domain.rooms.table_events import (
    TableActorContext,
    TableEventActorUnauthorizedError,
    TableEventService,
)
from app.persistence.combat.concentration import (
    CombatConcentrationNotFoundError,
    CombatConcentrationRepository,
    CombatConcentrationStateConflictError,
    StoredConcentrationRequest,
    StoredConcentrationResolution,
)
from app.persistence.combat.lifecycle import CombatRepository, actor_binding
from app.persistence.combat.repository import MonsterRepository


class ConcentrationCheckResultView(StrictModel):
    result_id: UUID
    roll_request_id: UUID
    target_entry_id: UUID
    d20: int
    modifier: int
    total: int
    dc: int
    succeeded: bool
    linked_effect_ids: tuple[str, ...] = ()
    linked_effects_removed_from: tuple[dict[str, Any], ...] = ()


class CombatConcentrationService:
    """Actor-neutral Concentration saving throw application service."""

    def __init__(
        self,
        repository: CombatConcentrationRepository,
        combat_repository: CombatRepository,
        monster_repository: MonsterRepository,
        roll_service: RollService,
        table_event_service: TableEventService,
    ) -> None:
        self.repository = repository
        self.combat_repository = combat_repository
        self.monster_repository = monster_repository
        self.roll_service = roll_service
        self.table_event_service = table_event_service

    def _authorize_roll(
        self,
        actor: TableActorContext,
        target_seat_id: UUID | None,
    ) -> tuple[UUID, str]:
        if target_seat_id is None:
            if not actor.is_current_dm:
                raise TableEventActorUnauthorizedError(
                    "Only the current Session DM can roll for Monster combatants"
                )
            return actor.seat_id, "self"
        if target_seat_id in actor.controlled_seat_ids:
            return target_seat_id, "self"
        if actor.is_current_dm:
            return actor.seat_id, "dm_proxy"
        raise TableEventActorUnauthorizedError("Actor cannot complete this Combat RollRequest")

    def complete_check(
        self,
        actor: TableActorContext,
        input: FormalRollInput,
    ) -> ConcentrationCheckResultView:
        self.table_event_service.require_actor_current(actor)
        request = self.repository.get_request(
            session_id=actor.session_id,
            request_id=input.roll_request_id,
        )
        if (
            request is None
            or request.roll_group_label != "Concentration"
            or request.request_type != "saving_throw"
            or request.ability_ref not in {"srd5.1:ability:constitution", "constitution"}
        ):
            raise CombatConcentrationNotFoundError(str(input.roll_request_id))

        if request.status == "resolved":
            event = self.repository.get_resolution_event(
                session_id=actor.session_id,
                request_id=request.id,
            )
            if event is not None:
                payload = dict(event.payload or {})
                return ConcentrationCheckResultView(
                    result_id=UUID(str(payload["roll_result_id"])),
                    roll_request_id=request.id,
                    target_entry_id=UUID(str(payload["target_entry_id"])),
                    d20=int(payload["d20"]),
                    modifier=int(payload["modifier"]),
                    total=int(payload["total"]),
                    dc=int(payload["dc"]),
                    succeeded=bool(payload["succeeded"]),
                    linked_effect_ids=tuple(str(x) for x in payload.get("linked_effect_ids", ())),
                    linked_effects_removed_from=tuple(
                        dict(x) for x in payload.get("linked_effects_removed_from", ())
                    ),
                )

        acting_seat_id, execution_mode = self._authorize_roll(actor, request.target_seat_id)

        entry = self.combat_repository.get_entry(request.target_combat_entry_id)
        if entry is None or entry.status != "active":
            raise CombatConcentrationNotFoundError("CombatEntry is missing or inactive")

        if entry.subject_kind == "character":
            if entry.character_id is None:
                raise CombatConcentrationStateConflictError(
                    "Character CombatEntry has no Character identity"
                )
            modifier = self.roll_service.modifier_resolver.modifier_for(
                character_id=entry.character_id,
                request_type=RollRequestType.SAVING_THROW,
                ability_ref="constitution",
                skill_ref=None,
            )
        elif entry.subject_kind == "monster":
            if entry.monster_instance_id is None:
                raise CombatConcentrationStateConflictError(
                    "Monster CombatEntry has no Monster identity"
                )
            monster = self.monster_repository.get_instance(entry.monster_instance_id)
            if monster is None:
                raise CombatConcentrationNotFoundError("Monster Instance was not found")
            modifier = monster_save_modifier(monster.rules_snapshot, "constitution")
        else:
            raise CombatConcentrationStateConflictError(
                f"unsupported CombatEntry kind: {entry.subject_kind}"
            )

        audit = self.roll_service.engine.d20(
            mode=RollModifierMode(request.modifier_mode),
            base_modifier=0,
            flat_adjustment=0,
            physical_raw_dice=(
                input.raw_dice if input.source is FormalRollSource.PHYSICAL else None
            ),
        )
        d20 = int(audit.kept_dice[0])

        stored, event = self.repository.complete_check(
            binding=actor_binding(actor),
            request_id=request.id,
            acting_seat_id=acting_seat_id,
            execution_mode=execution_mode,
            d20=d20,
            constitution_save_modifier=modifier,
            roll_source=input.source.value,
            idempotency_key=input.idempotency_key,
        )
        if self.table_event_service.notifier is not None:
            self.table_event_service.notifier.notify(actor.session_id)

        payload = dict(event.payload or {})
        return ConcentrationCheckResultView(
            result_id=stored.roll_result_id,
            roll_request_id=stored.roll_request_id,
            target_entry_id=stored.target_entry_id,
            d20=int(payload.get("d20", d20)),
            modifier=int(payload.get("modifier", modifier)),
            total=stored.total,
            dc=stored.dc,
            succeeded=stored.succeeded,
            linked_effect_ids=tuple(str(x) for x in payload.get("linked_effect_ids", ())),
            linked_effects_removed_from=tuple(
                dict(x) for x in payload.get("linked_effects_removed_from", ())
            ),
        )


__all__ = [
    "CombatConcentrationNotFoundError",
    "CombatConcentrationService",
    "CombatConcentrationStateConflictError",
    "ConcentrationCheckResultView",
    "StoredConcentrationRequest",
    "StoredConcentrationResolution",
]
