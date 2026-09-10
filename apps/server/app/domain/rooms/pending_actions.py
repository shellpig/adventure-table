from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import Field, model_validator

from app.domain.rooms.exploration import ExplorationSubjectNotFoundError
from app.domain.rooms.schemas import StrictModel
from app.domain.rooms.table_events import (
    TableActorContext,
    TableActorKind,
    TableEventActorUnauthorizedError,
    TableEventService,
)
from app.persistence.rooms.exploration_subjects import ExplorationSubjectRepository
from app.persistence.rooms.p3c_pending import (
    PendingActionConflictPersistenceError,
    PendingActionNotFoundPersistenceError,
    PendingActionRepository,
    StoredPendingAction,
)
from app.persistence.rooms.p3c_rolls import RollRepository, StoredRollRequest
from app.persistence.rooms.table_runtime import StoredTableActorBinding


class PendingActionStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    WAITING_FOR_ROLL = "waiting_for_roll"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


_ALLOWED_TRANSITIONS: dict[PendingActionStatus, frozenset[PendingActionStatus]] = {
    PendingActionStatus.PENDING: frozenset(
        {
            PendingActionStatus.PROCESSING,
            PendingActionStatus.WAITING_FOR_ROLL,
            PendingActionStatus.CANCELLED,
        }
    ),
    PendingActionStatus.PROCESSING: frozenset(
        {
            PendingActionStatus.WAITING_FOR_ROLL,
            PendingActionStatus.RESOLVED,
            PendingActionStatus.CANCELLED,
        }
    ),
    PendingActionStatus.WAITING_FOR_ROLL: frozenset(
        {
            PendingActionStatus.PROCESSING,
            PendingActionStatus.RESOLVED,
            PendingActionStatus.CANCELLED,
        }
    ),
    PendingActionStatus.RESOLVED: frozenset(),
    PendingActionStatus.CANCELLED: frozenset(),
}


class PendingActionNotFoundError(LookupError):
    pass


class PendingActionInvalidTransitionError(RuntimeError):
    pass


class PendingActionVersionConflictError(RuntimeError):
    pass


class PendingActionRollBindingError(RuntimeError):
    pass


class PendingActionCreateInput(StrictModel):
    subject_seat_id: UUID
    text: str | None = Field(default=None, max_length=8_000)
    intent_payload: dict[str, Any] | None = None
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)

    @model_validator(mode="after")
    def validate_intent(self) -> PendingActionCreateInput:
        if self.text is not None:
            self.text = self.text.strip() or None
        if self.text is None and self.intent_payload is None:
            raise ValueError("pending action requires text or intent_payload")
        return self


class PendingActionTransitionInput(StrictModel):
    expected_version: int = Field(ge=1)
    to_status: PendingActionStatus
    roll_request_id: UUID | None = None
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)

    @model_validator(mode="after")
    def validate_roll_binding(self) -> PendingActionTransitionInput:
        if self.to_status is PendingActionStatus.WAITING_FOR_ROLL and self.roll_request_id is None:
            raise ValueError("waiting_for_roll requires roll_request_id")
        return self


class PendingActionView(StrictModel):
    id: UUID
    session_id: UUID
    acting_seat_id: UUID
    subject_seat_id: UUID
    subject_character_id: UUID | None
    execution_mode: str
    text: str | None
    intent_payload: dict[str, Any] | None
    status: PendingActionStatus
    roll_request_id: UUID | None
    version: int


def validate_pending_transition(
    current: PendingActionStatus,
    target: PendingActionStatus,
) -> None:
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise PendingActionInvalidTransitionError(f"{current.value}->{target.value}")


def validate_pending_roll_binding(
    action: StoredPendingAction,
    request: StoredRollRequest | None,
) -> None:
    """Require a live formal request for the exact PendingAction subject.

    A guessed cross-Session request id resolves to ``None`` before this helper.
    Same-Session requests must still target the same Seat and the same captured
    Active Character, and must remain pending when the action enters
    ``waiting_for_roll``.
    """

    if request is None:
        raise PendingActionRollBindingError("roll_request_not_found")
    if request.session_id != action.session_id:
        raise PendingActionRollBindingError("roll_request_session_mismatch")
    if request.target_seat_id != action.subject_seat_id:
        raise PendingActionRollBindingError("roll_request_subject_mismatch")
    if request.target_character_id != action.subject_character_id:
        raise PendingActionRollBindingError("roll_request_character_mismatch")
    if request.status != "pending":
        raise PendingActionRollBindingError("roll_request_not_pending")


def _human_binding(actor: TableActorContext) -> StoredTableActorBinding:
    if actor.actor_kind is not TableActorKind.HUMAN or actor.access_session_id is None:
        raise TableEventActorUnauthorizedError(
            "AI PendingAction persistence is not available until P3-D"
        )
    return StoredTableActorBinding(
        room_id=actor.room_id,
        campaign_id=actor.campaign_id,
        session_id=actor.session_id,
        seat_id=actor.seat_id,
        controlled_seat_ids=actor.controlled_seat_ids,
        role=actor.role,
        is_current_dm=actor.is_current_dm,
        access_session_id=actor.access_session_id,
    )


class PendingActionService:
    def __init__(
        self,
        repository: PendingActionRepository,
        subject_repository: ExplorationSubjectRepository,
        table_event_service: TableEventService,
        roll_repository: RollRepository,
    ) -> None:
        self.repository = repository
        self.subject_repository = subject_repository
        self.table_event_service = table_event_service
        self.roll_repository = roll_repository

    @staticmethod
    def _view(stored: StoredPendingAction) -> PendingActionView:
        return PendingActionView(
            id=stored.id,
            session_id=stored.session_id,
            acting_seat_id=stored.acting_seat_id,
            subject_seat_id=stored.subject_seat_id,
            subject_character_id=stored.subject_character_id,
            execution_mode=stored.execution_mode,
            text=stored.text,
            intent_payload=stored.intent_payload,
            status=PendingActionStatus(stored.status),
            roll_request_id=stored.roll_request_id,
            version=stored.version,
        )

    def _subject(self, actor: TableActorContext, seat_id: UUID):
        subject = self.subject_repository.resolve_subject(
            room_id=actor.room_id,
            campaign_id=actor.campaign_id,
            session_id=actor.session_id,
            seat_id=seat_id,
        )
        if subject is None or subject.role != "player" or subject.active_character_id is None:
            raise ExplorationSubjectNotFoundError(str(seat_id))
        return subject

    def create(
        self, actor: TableActorContext, input: PendingActionCreateInput
    ) -> PendingActionView:
        self.table_event_service.require_actor_current(actor)
        subject = self._subject(actor, input.subject_seat_id)
        if subject.seat_id in actor.controlled_seat_ids:
            acting_seat_id = subject.seat_id
            execution_mode = "self"
        elif actor.is_current_dm:
            acting_seat_id = actor.seat_id
            execution_mode = "dm_proxy"
        else:
            raise TableEventActorUnauthorizedError(
                "Actor cannot create PendingAction for the selected Seat"
            )
        stored, _event = self.repository.create(
            binding=_human_binding(actor),
            acting_seat_id=acting_seat_id,
            subject_seat_id=subject.seat_id,
            subject_character_id=subject.active_character_id,
            execution_mode=execution_mode,
            text=input.text,
            intent_payload=input.intent_payload,
            idempotency_key=(
                f"p3c-pending-create:{input.idempotency_key}"
                if input.idempotency_key
                else None
            ),
        )
        if self.table_event_service.notifier is not None:
            self.table_event_service.notifier.notify(actor.session_id)
        return self._view(stored)

    def list(self, actor: TableActorContext) -> tuple[PendingActionView, ...]:
        self.table_event_service.require_actor_current(actor)
        controlled = set(actor.controlled_seat_ids)
        rows = self.repository.list_for_session(session_id=actor.session_id)
        return tuple(
            self._view(row)
            for row in rows
            if actor.is_current_dm or row.subject_seat_id in controlled
        )

    def transition(
        self,
        actor: TableActorContext,
        action_id: UUID,
        input: PendingActionTransitionInput,
    ) -> PendingActionView:
        self.table_event_service.require_actor_current(actor)
        current = self.repository.get(session_id=actor.session_id, action_id=action_id)
        if current is None:
            raise PendingActionNotFoundError(str(action_id))
        if not actor.is_current_dm and current.subject_seat_id not in actor.controlled_seat_ids:
            raise TableEventActorUnauthorizedError("Actor cannot transition this PendingAction")
        current_status = PendingActionStatus(current.status)
        validate_pending_transition(current_status, input.to_status)
        if input.to_status is PendingActionStatus.WAITING_FOR_ROLL:
            request = self.roll_repository.get_request(
                session_id=actor.session_id,
                request_id=input.roll_request_id,
            )
            validate_pending_roll_binding(current, request)
            roll_request_id = input.roll_request_id
        else:
            roll_request_id = current.roll_request_id
        try:
            stored, _event = self.repository.transition(
                binding=_human_binding(actor),
                action_id=action_id,
                expected_version=input.expected_version,
                from_status=current_status.value,
                to_status=input.to_status.value,
                roll_request_id=roll_request_id,
                idempotency_key=(
                    f"p3c-pending-transition:{input.idempotency_key}"
                    if input.idempotency_key
                    else None
                ),
            )
        except PendingActionNotFoundPersistenceError as exc:
            raise PendingActionNotFoundError(str(action_id)) from exc
        except PendingActionConflictPersistenceError as exc:
            raise PendingActionVersionConflictError(str(action_id)) from exc
        if self.table_event_service.notifier is not None:
            self.table_event_service.notifier.notify(actor.session_id)
        return self._view(stored)


__all__ = [
    "PendingActionCreateInput",
    "PendingActionInvalidTransitionError",
    "PendingActionNotFoundError",
    "PendingActionRollBindingError",
    "PendingActionService",
    "PendingActionStatus",
    "PendingActionTransitionInput",
    "PendingActionVersionConflictError",
    "PendingActionView",
    "validate_pending_roll_binding",
    "validate_pending_transition",
]
