from __future__ import annotations

from enum import StrEnum
from random import SystemRandom
from typing import Protocol
from uuid import UUID, uuid4

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
from app.persistence.rooms.p3c_rolls import (
    NewRollRequest,
    RollRepository,
    RollRequestNotFoundPersistenceError,
    RollRequestNotPendingPersistenceError,
    StoredRollRequest,
    StoredRollResult,
)
from app.persistence.rooms.table_runtime import StoredTableActorBinding


class RollVisibility(StrEnum):
    PUBLIC = "public"
    ROLLER_AND_DM = "roller_and_dm"
    DM_ONLY = "dm_only"


class RollModifierMode(StrEnum):
    NORMAL = "normal"
    ADVANTAGE = "advantage"
    DISADVANTAGE = "disadvantage"


class RollRequestType(StrEnum):
    ABILITY = "ability"
    SKILL = "skill"
    SAVING_THROW = "saving_throw"
    OTHER = "other"


class FormalRollSource(StrEnum):
    SERVER = "server"
    PHYSICAL = "physical"


class RollInputInvalidError(ValueError):
    pass


class RollRequestNotFoundError(LookupError):
    pass


class RollRequestAlreadyResolvedError(RuntimeError):
    pass


class RollModifierResolver(Protocol):
    def modifier_for(
        self,
        *,
        character_id: UUID,
        request_type: RollRequestType,
        ability_ref: str | None,
        skill_ref: str | None,
    ) -> int: ...


class RequestCheckInput(StrictModel):
    target_seat_ids: tuple[UUID, ...] = Field(min_length=1, max_length=32)
    request_type: RollRequestType
    ability_ref: str | None = Field(default=None, max_length=80)
    skill_ref: str | None = Field(default=None, max_length=120)
    dc: int | None = Field(default=None, ge=0, le=999)
    modifier_mode: RollModifierMode = RollModifierMode.NORMAL
    flat_adjustment: int = Field(default=0, ge=-100, le=100)
    visibility: RollVisibility = RollVisibility.PUBLIC
    label: str | None = Field(default=None, max_length=160)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)

    @model_validator(mode="after")
    def validate_refs(self) -> RequestCheckInput:
        if len(set(self.target_seat_ids)) != len(self.target_seat_ids):
            raise ValueError("target_seat_ids must be unique")
        if self.request_type is RollRequestType.SKILL and not self.skill_ref:
            raise ValueError("skill roll requires skill_ref")
        if self.request_type in {RollRequestType.ABILITY, RollRequestType.SAVING_THROW} and not self.ability_ref:
            raise ValueError("ability/saving throw requires ability_ref")
        return self


class FormalRollInput(StrictModel):
    roll_request_id: UUID
    source: FormalRollSource = FormalRollSource.SERVER
    raw_dice: tuple[int, ...] | None = None
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)

    @model_validator(mode="after")
    def validate_source(self) -> FormalRollInput:
        if self.source is FormalRollSource.SERVER and self.raw_dice is not None:
            raise ValueError("server roll does not accept client raw_dice")
        if self.source is FormalRollSource.PHYSICAL and self.raw_dice is None:
            raise ValueError("physical roll requires raw_dice")
        return self


class QuickRollInput(StrictModel):
    subject_seat_id: UUID
    dice_count: int = Field(default=1, ge=1, le=20)
    die_sides: int = Field(default=20, ge=2, le=1000)
    flat_adjustment: int = Field(default=0, ge=-1000, le=1000)
    visibility: RollVisibility = RollVisibility.PUBLIC
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class RollRequestView(StrictModel):
    id: UUID
    session_id: UUID
    roll_group_id: UUID | None
    target_seat_id: UUID
    target_character_id: UUID | None
    request_type: RollRequestType
    ability_ref: str | None
    skill_ref: str | None
    dc: int | None
    modifier_mode: RollModifierMode
    flat_adjustment: int
    visibility: RollVisibility
    status: str
    requested_by_seat_id: UUID
    version: int


class RollResultView(StrictModel):
    id: UUID
    roll_request_id: UUID | None
    session_id: UUID
    acting_seat_id: UUID
    subject_seat_id: UUID
    subject_character_id: UUID | None
    execution_mode: str
    source: str
    formula: str
    raw_dice: tuple[int, ...]
    kept_dice: tuple[int, ...]
    base_modifier: int
    flat_adjustment: int
    total: int
    visibility: RollVisibility


class RollAudit(StrictModel):
    formula: str
    raw_dice: tuple[int, ...]
    kept_dice: tuple[int, ...]
    base_modifier: int
    flat_adjustment: int
    total: int


class RollEngine:
    def __init__(self, rng: SystemRandom | None = None) -> None:
        self.rng = rng or SystemRandom()

    @staticmethod
    def _physical_d20(mode: RollModifierMode, raw_dice: tuple[int, ...]) -> tuple[int, ...]:
        required = 1 if mode is RollModifierMode.NORMAL else 2
        if len(raw_dice) != required:
            raise RollInputInvalidError(f"{mode.value} requires {required} raw d20 value(s)")
        if any(value < 1 or value > 20 for value in raw_dice):
            raise RollInputInvalidError("raw d20 values must be between 1 and 20")
        return raw_dice

    def d20(
        self,
        *,
        mode: RollModifierMode,
        base_modifier: int,
        flat_adjustment: int,
        physical_raw_dice: tuple[int, ...] | None = None,
    ) -> RollAudit:
        count = 1 if mode is RollModifierMode.NORMAL else 2
        raw = (
            self._physical_d20(mode, physical_raw_dice)
            if physical_raw_dice is not None
            else tuple(self.rng.randint(1, 20) for _ in range(count))
        )
        if mode is RollModifierMode.ADVANTAGE:
            kept = (max(raw),)
            dice_formula = "2d20kh1"
        elif mode is RollModifierMode.DISADVANTAGE:
            kept = (min(raw),)
            dice_formula = "2d20kl1"
        else:
            kept = (raw[0],)
            dice_formula = "1d20"
        modifier = int(base_modifier) + int(flat_adjustment)
        sign = "+" if modifier >= 0 else ""
        return RollAudit(
            formula=f"{dice_formula}{sign}{modifier}",
            raw_dice=raw,
            kept_dice=kept,
            base_modifier=int(base_modifier),
            flat_adjustment=int(flat_adjustment),
            total=kept[0] + modifier,
        )

    def quick(
        self,
        *,
        dice_count: int,
        die_sides: int,
        flat_adjustment: int,
    ) -> RollAudit:
        if dice_count < 1 or die_sides < 2:
            raise RollInputInvalidError("quick roll requires positive dice and at least d2")
        raw = tuple(self.rng.randint(1, die_sides) for _ in range(dice_count))
        sign = "+" if flat_adjustment >= 0 else ""
        return RollAudit(
            formula=f"{dice_count}d{die_sides}{sign}{flat_adjustment}",
            raw_dice=raw,
            kept_dice=raw,
            base_modifier=0,
            flat_adjustment=flat_adjustment,
            total=sum(raw) + flat_adjustment,
        )


def _event_visibility(visibility: RollVisibility) -> str:
    if visibility is RollVisibility.PUBLIC:
        return "public"
    if visibility is RollVisibility.ROLLER_AND_DM:
        return "actor_and_dm"
    return "dm_only"


def _human_binding(actor: TableActorContext) -> StoredTableActorBinding:
    if actor.actor_kind is not TableActorKind.HUMAN or actor.access_session_id is None:
        raise TableEventActorUnauthorizedError("AI roll persistence is not available until P3-D")
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


class RollService:
    def __init__(
        self,
        repository: RollRepository,
        subject_repository: ExplorationSubjectRepository,
        table_event_service: TableEventService,
        modifier_resolver: RollModifierResolver,
        engine: RollEngine | None = None,
    ) -> None:
        self.repository = repository
        self.subject_repository = subject_repository
        self.table_event_service = table_event_service
        self.modifier_resolver = modifier_resolver
        self.engine = engine or RollEngine()

    @staticmethod
    def _request_view(actor: TableActorContext, request: StoredRollRequest) -> RollRequestView:
        return RollRequestView(
            id=request.id,
            session_id=request.session_id,
            roll_group_id=request.roll_group_id,
            target_seat_id=request.target_seat_id,
            target_character_id=request.target_character_id,
            request_type=RollRequestType(request.request_type),
            ability_ref=request.ability_ref,
            skill_ref=request.skill_ref,
            dc=request.dc if actor.is_current_dm else None,
            modifier_mode=RollModifierMode(request.modifier_mode),
            flat_adjustment=request.flat_adjustment,
            visibility=RollVisibility(request.visibility),
            status=request.status,
            requested_by_seat_id=request.requested_by_seat_id,
            version=request.version,
        )

    @staticmethod
    def _result_view(result: StoredRollResult) -> RollResultView:
        return RollResultView(
            id=result.id,
            roll_request_id=result.roll_request_id,
            session_id=result.session_id,
            acting_seat_id=result.acting_seat_id,
            subject_seat_id=result.subject_seat_id,
            subject_character_id=result.subject_character_id,
            execution_mode=result.execution_mode,
            source=result.source,
            formula=result.formula,
            raw_dice=result.raw_dice,
            kept_dice=result.kept_dice,
            base_modifier=result.base_modifier,
            flat_adjustment=result.flat_adjustment,
            total=result.total,
            visibility=RollVisibility(result.visibility),
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

    def request_check(
        self, actor: TableActorContext, request: RequestCheckInput
    ) -> tuple[UUID, tuple[RollRequestView, ...]]:
        self.table_event_service.require_actor_current(actor)
        if not actor.is_current_dm:
            raise TableEventActorUnauthorizedError("Only the current Session DM can create a formal Check")
        subjects = tuple(self._subject(actor, seat_id) for seat_id in request.target_seat_ids)
        new_requests = tuple(
            NewRollRequest(
                id=uuid4(),
                target_seat_id=subject.seat_id,
                target_character_id=subject.active_character_id,
            )
            for subject in subjects
        )
        group_id, stored, _event = self.repository.create_request_group(
            binding=_human_binding(actor),
            requests=new_requests,
            request_type=request.request_type.value,
            ability_ref=request.ability_ref,
            skill_ref=request.skill_ref,
            dc=request.dc,
            modifier_mode=request.modifier_mode.value,
            flat_adjustment=request.flat_adjustment,
            visibility=request.visibility.value,
            label=request.label,
            event_visibility=_event_visibility(request.visibility),
            idempotency_key=(
                f"p3c-request:{request.idempotency_key}" if request.idempotency_key else None
            ),
        )
        if self.table_event_service.notifier is not None:
            self.table_event_service.notifier.notify(actor.session_id)
        return group_id, tuple(self._request_view(actor, item) for item in stored)

    def list_requests(self, actor: TableActorContext) -> tuple[RollRequestView, ...]:
        self.table_event_service.require_actor_current(actor)
        stored = self.repository.list_requests(session_id=actor.session_id)
        visible: list[RollRequestView] = []
        controlled = set(actor.controlled_seat_ids)
        for request in stored:
            visibility = RollVisibility(request.visibility)
            if actor.is_current_dm or visibility is RollVisibility.PUBLIC or request.target_seat_id in controlled:
                visible.append(self._request_view(actor, request))
        return tuple(visible)

    def complete_formal(self, actor: TableActorContext, input: FormalRollInput) -> RollResultView:
        self.table_event_service.require_actor_current(actor)
        request = self.repository.get_request(
            session_id=actor.session_id,
            request_id=input.roll_request_id,
        )
        if request is None:
            raise RollRequestNotFoundError(str(input.roll_request_id))
        subject = self._subject(actor, request.target_seat_id)
        if request.target_seat_id in actor.controlled_seat_ids:
            execution_mode = "self"
            acting_seat_id = request.target_seat_id
        elif actor.is_current_dm:
            execution_mode = "dm_proxy"
            acting_seat_id = actor.seat_id
        else:
            raise TableEventActorUnauthorizedError("Actor cannot complete this RollRequest")
        if subject.active_character_id != request.target_character_id or request.target_character_id is None:
            raise TableEventActorUnauthorizedError("RollRequest target Character is no longer valid")

        existing = self.repository.get_result_for_request(
            session_id=actor.session_id,
            request_id=request.id,
        )
        if existing is not None:
            return self._result_view(existing)

        base_modifier = self.modifier_resolver.modifier_for(
            character_id=request.target_character_id,
            request_type=RollRequestType(request.request_type),
            ability_ref=request.ability_ref,
            skill_ref=request.skill_ref,
        )
        audit = self.engine.d20(
            mode=RollModifierMode(request.modifier_mode),
            base_modifier=base_modifier,
            flat_adjustment=request.flat_adjustment,
            physical_raw_dice=input.raw_dice if input.source is FormalRollSource.PHYSICAL else None,
        )
        try:
            stored, _event = self.repository.complete_request(
                binding=_human_binding(actor),
                request_id=request.id,
                acting_seat_id=acting_seat_id,
                execution_mode=execution_mode,
                source=input.source.value,
                formula=audit.formula,
                raw_dice=audit.raw_dice,
                kept_dice=audit.kept_dice,
                base_modifier=audit.base_modifier,
                flat_adjustment=audit.flat_adjustment,
                total=audit.total,
                visibility=request.visibility,
                event_visibility=_event_visibility(RollVisibility(request.visibility)),
                idempotency_key=(
                    f"p3c-result:{input.idempotency_key}" if input.idempotency_key else None
                ),
            )
        except RollRequestNotFoundPersistenceError as exc:
            raise RollRequestNotFoundError(str(request.id)) from exc
        except RollRequestNotPendingPersistenceError as exc:
            existing = self.repository.get_result_for_request(
                session_id=actor.session_id,
                request_id=request.id,
            )
            if existing is None:
                raise RollRequestAlreadyResolvedError(str(request.id)) from exc
            stored = existing
        if self.table_event_service.notifier is not None:
            self.table_event_service.notifier.notify(actor.session_id)
        return self._result_view(stored)

    def quick_roll(self, actor: TableActorContext, input: QuickRollInput) -> RollResultView:
        self.table_event_service.require_actor_current(actor)
        subject = self._subject(actor, input.subject_seat_id)
        if subject.seat_id not in actor.controlled_seat_ids:
            raise TableEventActorUnauthorizedError("Quick Dice can only be rolled for a controlled Seat")
        audit = self.engine.quick(
            dice_count=input.dice_count,
            die_sides=input.die_sides,
            flat_adjustment=input.flat_adjustment,
        )
        stored, _event = self.repository.record_quick_roll(
            binding=_human_binding(actor),
            acting_seat_id=subject.seat_id,
            subject_seat_id=subject.seat_id,
            subject_character_id=subject.active_character_id,
            formula=audit.formula,
            raw_dice=audit.raw_dice,
            kept_dice=audit.kept_dice,
            base_modifier=0,
            flat_adjustment=audit.flat_adjustment,
            total=audit.total,
            visibility=input.visibility.value,
            event_visibility=_event_visibility(input.visibility),
            idempotency_key=(
                f"p3c-quick:{input.idempotency_key}" if input.idempotency_key else None
            ),
        )
        if self.table_event_service.notifier is not None:
            self.table_event_service.notifier.notify(actor.session_id)
        return self._result_view(stored)


__all__ = [
    "FormalRollInput",
    "FormalRollSource",
    "QuickRollInput",
    "RequestCheckInput",
    "RollAudit",
    "RollEngine",
    "RollInputInvalidError",
    "RollModifierMode",
    "RollModifierResolver",
    "RollRequestAlreadyResolvedError",
    "RollRequestNotFoundError",
    "RollRequestType",
    "RollRequestView",
    "RollResultView",
    "RollService",
    "RollVisibility",
]
