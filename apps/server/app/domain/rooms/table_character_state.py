from __future__ import annotations

from typing import Protocol
from uuid import UUID

from pydantic import Field, model_validator

from app.domain.character.schemas import (
    ActiveInfusion,
    ConditionState,
    HitDie,
    InventoryEntry,
    PersistedCharacter,
    PreparedSpellSelection,
    ResourceCounter,
    SpellStoringItemState,
)
from app.domain.rooms.exploration import ExplorationSubjectNotFoundError
from app.domain.rooms.schemas import StrictModel
from app.domain.rooms.table_events import (
    TableActorContext,
    TableEventActorUnauthorizedError,
    TableEventService,
)
from app.persistence.rooms.exploration_subjects import ExplorationSubjectRepository


class TableCharacterStateCombatMutationError(RuntimeError):
    """Raw HP patch tried to bypass P4-C semantic combat resolution."""


class ActiveCombatLookup(Protocol):
    def get_active(self, campaign_id: UUID): ...


class TableCharacterStatePatch(StrictModel):
    """Canonical Current State fields available to in-table gameplay actions.

    During an active Combat, current_hp/temporary_hp are correction-only fields:
    normal gameplay must use the P4-C semantic damage/healing pipeline. The
    current DM may still perform an audited correction with correction_reason.
    """

    expected_current_version_id: UUID | None = None
    current_hp: int | None = Field(default=None, ge=0)
    temporary_hp: int | None = Field(default=None, ge=0)
    conditions: list[ConditionState] | None = None
    prepared_spells: list[PreparedSpellSelection] | None = None
    spell_slots: dict[int, ResourceCounter] | None = None
    resources: dict[str, ResourceCounter] | None = None
    hit_dice_state: dict[HitDie, int] | None = None
    inventory_state: list[InventoryEntry] | None = None
    active_infusions: list[ActiveInfusion] | None = None
    feature_modes: dict[str, str] | None = None
    spell_storing_item: SpellStoringItemState | None = None
    correction_reason: str | None = Field(default=None, min_length=1, max_length=500)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)

    @model_validator(mode="after")
    def validate_patch(self) -> TableCharacterStatePatch:
        changes = self.state_changes()
        if not changes:
            raise ValueError("table Character State patch requires at least one state field")
        nullable = {"spell_storing_item"}
        if any(value is None for key, value in changes.items() if key not in nullable):
            raise ValueError("table Character State patch fields cannot be null")
        return self

    def state_changes(self) -> dict[str, object]:
        changes = self.model_dump(exclude_unset=True, mode="python")
        changes.pop("expected_current_version_id", None)
        changes.pop("correction_reason", None)
        changes.pop("idempotency_key", None)
        return changes


class TableCharacterStateRepository(Protocol):
    def apply_patch(
        self,
        *,
        actor: TableActorContext,
        acting_seat_id: UUID,
        subject_seat_id: UUID,
        subject_character_id: UUID,
        execution_mode: str,
        patch: TableCharacterStatePatch,
    ) -> PersistedCharacter: ...


class TableCharacterStateService:
    """Actor-neutral authorization for legal in-table Current State mutation."""

    def __init__(
        self,
        repository: TableCharacterStateRepository,
        subject_repository: ExplorationSubjectRepository,
        table_event_service: TableEventService,
        active_combat_lookup: ActiveCombatLookup | None = None,
    ) -> None:
        self.repository = repository
        self.subject_repository = subject_repository
        self.table_event_service = table_event_service
        self.active_combat_lookup = active_combat_lookup

    def apply_patch(
        self,
        actor: TableActorContext,
        *,
        subject_seat_id: UUID,
        patch: TableCharacterStatePatch,
    ) -> PersistedCharacter:
        self.table_event_service.require_actor_current(actor)
        subject = self.subject_repository.resolve_subject(
            room_id=actor.room_id,
            campaign_id=actor.campaign_id,
            session_id=actor.session_id,
            seat_id=subject_seat_id,
        )
        if subject is None or subject.role != "player" or subject.active_character_id is None:
            raise ExplorationSubjectNotFoundError(str(subject_seat_id))

        if subject.seat_id in actor.controlled_seat_ids:
            acting_seat_id = subject.seat_id
            execution_mode = "self"
        elif actor.is_current_dm:
            acting_seat_id = actor.seat_id
            execution_mode = "dm_proxy"
        else:
            raise TableEventActorUnauthorizedError(
                "Actor cannot mutate Current State for the selected Seat"
            )

        changes = patch.state_changes()
        hp_fields = {"current_hp", "temporary_hp"} & set(changes)
        active_combat = (
            self.active_combat_lookup.get_active(actor.campaign_id)
            if self.active_combat_lookup is not None
            else None
        )
        if hp_fields and active_combat is not None:
            if not actor.is_current_dm:
                raise TableCharacterStateCombatMutationError(
                    "Active Combat HP changes must use semantic damage/healing resolution"
                )
            if not patch.correction_reason:
                raise TableCharacterStateCombatMutationError(
                    "Active Combat raw HP correction requires correction_reason"
                )

        updated = self.repository.apply_patch(
            actor=actor,
            acting_seat_id=acting_seat_id,
            subject_seat_id=subject.seat_id,
            subject_character_id=subject.active_character_id,
            execution_mode=execution_mode,
            patch=patch,
        )
        if self.table_event_service.notifier is not None:
            self.table_event_service.notifier.notify(actor.session_id)
        return updated


__all__ = [
    "ActiveCombatLookup",
    "TableCharacterStateCombatMutationError",
    "TableCharacterStatePatch",
    "TableCharacterStateRepository",
    "TableCharacterStateService",
]
