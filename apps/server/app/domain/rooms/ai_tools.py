from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from pydantic import Field

from app.domain.rooms.ai_controllers import AIControllerAuthView, AIControllerService
from app.domain.rooms.ai_guidance import render_briefing
from app.domain.rooms.ai_tool_contract import WAIT_EVENT_MAX_TIMEOUT_SECONDS
from app.domain.rooms.exploration import (
    ExplorationActionService,
    ExplorationInputKind,
    ExplorationInputRequest,
    ExplorationStageService,
    StageState,
    StageUpdateRequest,
)
from app.domain.rooms.pending_actions import PendingActionService
from app.domain.rooms.rolls import (
    FormalRollInput,
    FormalRollSource,
    QuickRollInput,
    RequestCheckInput,
    RollModifierMode,
    RollRequestType,
    RollService,
    RollVisibility,
)
from app.domain.rooms.schemas import StrictModel
from app.domain.rooms.sessions import SessionService
from app.domain.rooms.table_character_state import (
    TableCharacterStatePatch,
    TableCharacterStateService,
)
from app.domain.rooms.table_events import TableActorContext, TableEventService
from app.domain.rooms.workspace import RoomCharacterWorkspaceService


class AIToolScopeError(PermissionError):
    pass


class AIToolInputError(ValueError):
    pass


class TextActionInput(StrictModel):
    text: str = Field(min_length=1, max_length=8_000)
    subject_seat_id: UUID | None = None
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class StageTextInput(StrictModel):
    expected_revision: int = Field(ge=0)
    text: str | None = Field(default=None, max_length=12_000)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class RollPendingInput(StrictModel):
    roll_request_id: UUID
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class PhysicalRollInput(StrictModel):
    roll_request_id: UUID
    raw_dice: tuple[int, ...] = Field(min_length=1, max_length=2)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class QuickRollToolInput(StrictModel):
    subject_seat_id: UUID | None = None
    dice_count: int = Field(default=1, ge=1, le=20)
    die_sides: int = Field(default=20, ge=2, le=1000)
    flat_adjustment: int = Field(default=0, ge=-1000, le=1000)
    visibility: RollVisibility = RollVisibility.PUBLIC
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class CharacterStateToolInput(StrictModel):
    subject_seat_id: UUID | None = None
    patch: TableCharacterStatePatch


class EventsInput(StrictModel):
    after_seq: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=200)


class WaitEventsInput(EventsInput):
    timeout: float = Field(default=30.0, ge=0.0, le=WAIT_EVENT_MAX_TIMEOUT_SECONDS)


class RequestCheckToolInput(StrictModel):
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


class AIToolApplicationService:
    """Transport-neutral external-AI facade over the existing P3 application services."""

    def __init__(
        self,
        *,
        ai_controller_service: AIControllerService,
        session_service: SessionService,
        stage_service: ExplorationStageService,
        action_service: ExplorationActionService,
        roll_service: RollService,
        state_service: TableCharacterStateService,
        pending_action_service: PendingActionService,
        event_service: TableEventService,
        workspace_service: RoomCharacterWorkspaceService,
    ) -> None:
        self.ai_controller_service = ai_controller_service
        self.session_service = session_service
        self.stage_service = stage_service
        self.action_service = action_service
        self.roll_service = roll_service
        self.state_service = state_service
        self.pending_action_service = pending_action_service
        self.event_service = event_service
        self.workspace_service = workspace_service

    def _auth(
        self,
        token: str,
        *,
        authenticated: AIControllerAuthView | None = None,
        touch: bool = True,
    ) -> AIControllerAuthView:
        if authenticated is not None:
            return authenticated
        return self.ai_controller_service.authenticate(token, touch=touch)

    def _actor(
        self,
        token: str,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> TableActorContext:
        # P3-D owns credential/current-binding semantics. MCP can pass the auth
        # result already resolved for this request to avoid redundant DB round trips.
        if authenticated is not None:
            return self.ai_controller_service.actor_from_auth(authenticated)
        return self.ai_controller_service.resolve_actor(token, touch=True)

    @staticmethod
    def _subject_seat(actor: TableActorContext, requested: UUID | None) -> UUID:
        if actor.role == "player":
            if requested is not None and requested != actor.seat_id:
                raise AIToolScopeError("AI Player cannot act as another Seat")
            return actor.seat_id
        if requested is None:
            raise AIToolInputError("DM action requires subject_seat_id")
        return requested

    @staticmethod
    def _briefing(*, role: str, mode: str) -> str:
        return render_briefing(role=role, mode=mode)

    @staticmethod
    def _stage_hint(stage: StageState, *, role: str) -> tuple[bool, str]:
        # Machine-readable companion to the DM briefing loop: a DM whose Stage is
        # empty should set it before narrating. Guidance only; never enforced.
        stage_unset = stage.text is None or not stage.text.strip()
        if role == "dm" and stage_unset:
            return True, "set_stage_text"
        return stage_unset, "wait_for_event"

    def get_session_context(
        self,
        token: str,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        auth = self._auth(token, authenticated=authenticated, touch=True)
        if auth.session_id is None:
            if auth.role != "dm":
                raise AIToolScopeError("Only a pre-session AI DM grant may be unbound")
            return {
                "mode": "pre_session",
                "room_id": str(auth.room_id),
                "campaign_id": str(auth.campaign_id),
                "seat_id": str(auth.seat_id),
                "role": auth.role,
                "start_available": True,
                "briefing": self._briefing(role=auth.role, mode="pre_session"),
                "temporary_instruction": auth.temporary_instruction,
            }

        actor = self._actor(token, authenticated=auth)
        session = self.session_service.get_session(
            actor.room_id,
            actor.campaign_id,
            actor.session_id,
        )
        runtime = self.event_service.current_cursor(actor)
        after_seq = max(0, runtime.last_event_seq - 50)
        recent_events = self.event_service.list_after(
            actor,
            after_seq=after_seq,
            limit=50,
        )
        stage = self.stage_service.get_stage(actor)
        stage_unset, next_required_action = self._stage_hint(stage, role=actor.role)
        return {
            "mode": "active_session",
            "caller": {
                "seat_id": str(actor.seat_id),
                "role": actor.role,
                "is_current_dm": actor.is_current_dm,
            },
            "session": {
                "id": str(session.id),
                "campaign_id": str(session.campaign_id),
                "status": session.status.value,
                "dm_seat_id": str(session.dm_seat_id),
                "participants": [
                    {
                        "seat_id": str(item.seat_id),
                        "role": item.role,
                        "active_character_id": (
                            str(item.active_character_id)
                            if item.active_character_id is not None
                            else None
                        ),
                    }
                    for item in session.participants
                ],
            },
            "stage": stage.model_dump(mode="json"),
            "stage_unset": stage_unset,
            "next_required_action": next_required_action,
            "runtime": runtime.model_dump(mode="json"),
            "recent_events": recent_events.model_dump(mode="json"),
            "roll_requests": [
                item.model_dump(mode="json")
                for item in self.roll_service.list_requests(actor)
            ],
            "pending_actions": [
                item.model_dump(mode="json")
                for item in self.pending_action_service.list(actor)
            ],
            "briefing": self._briefing(role=actor.role, mode="active_session"),
            "temporary_instruction": auth.temporary_instruction,
        }

    def start_session(
        self,
        token: str,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        auth = self._auth(token, authenticated=authenticated, touch=True)
        if auth.session_id is not None or auth.role != "dm":
            raise AIToolScopeError("Start is only available to an unbound pre-session AI DM")
        session = self.session_service.start_session_as_ai_dm(
            auth.room_id,
            auth.campaign_id,
            grant_id=auth.grant_id,
            generation=auth.generation,
        )
        # A newly started Session always has an empty Stage, so the response tells
        # the AI DM to set it before narrating without an extra Stage read.
        return {
            **session.model_dump(mode="json"),
            "stage_unset": True,
            "next_required_action": "set_stage_text",
        }

    def get_character_context(
        self,
        token: str,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        if actor.role != "player":
            raise AIToolScopeError("Only an AI Player has an own Character context")
        session = self.session_service.get_session(
            actor.room_id,
            actor.campaign_id,
            actor.session_id,
        )
        participant = next(
            (item for item in session.participants if item.seat_id == actor.seat_id),
            None,
        )
        if participant is None or participant.active_character_id is None:
            raise AIToolScopeError("AI Player has no active Character in this Session")
        character = self.workspace_service.get_character(
            actor.room_id,
            participant.active_character_id,
        )
        return character.model_dump(mode="json")

    def post_text(
        self,
        token: str,
        *,
        kind: ExplorationInputKind,
        input: TextActionInput,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        is_subject_action = kind in {
            ExplorationInputKind.DIALOGUE,
            ExplorationInputKind.ACTION,
        }
        if not is_subject_action and input.subject_seat_id is not None:
            raise AIToolInputError("subject_seat_id is only valid for dialogue/action")
        subject_seat_id = (
            self._subject_seat(actor, input.subject_seat_id)
            if is_subject_action
            else None
        )
        event = self.action_service.send(
            actor,
            ExplorationInputRequest(
                kind=kind,
                text=input.text,
                subject_seat_id=subject_seat_id,
                idempotency_key=input.idempotency_key,
            ),
        )
        return event.model_dump(mode="json")

    def set_stage_text(
        self,
        token: str,
        input: StageTextInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        current = self.stage_service.get_stage(actor)
        stage = self.stage_service.replace_stage(
            actor,
            StageUpdateRequest(
                expected_revision=input.expected_revision,
                text=input.text,
                image_id=current.image_id,
                idempotency_key=input.idempotency_key,
            ),
        )
        return stage.model_dump(mode="json")

    def request_check(
        self,
        token: str,
        input: RequestCheckToolInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        group_id, requests = self.roll_service.request_check(
            actor,
            RequestCheckInput.model_validate(input.model_dump(mode="python")),
        )
        return {
            "roll_group_id": str(group_id),
            "requests": [item.model_dump(mode="json") for item in requests],
        }

    def roll_pending(
        self,
        token: str,
        input: RollPendingInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        result = self.roll_service.complete_formal(
            actor,
            FormalRollInput(
                roll_request_id=input.roll_request_id,
                source=FormalRollSource.SERVER,
                idempotency_key=input.idempotency_key,
            ),
        )
        return result.model_dump(mode="json")

    def submit_physical_roll(
        self,
        token: str,
        input: PhysicalRollInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        result = self.roll_service.complete_formal(
            actor,
            FormalRollInput(
                roll_request_id=input.roll_request_id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=input.raw_dice,
                idempotency_key=input.idempotency_key,
            ),
        )
        return result.model_dump(mode="json")

    def quick_roll(
        self,
        token: str,
        input: QuickRollToolInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        subject_seat_id = self._subject_seat(actor, input.subject_seat_id)
        result = self.roll_service.quick_roll(
            actor,
            QuickRollInput(
                subject_seat_id=subject_seat_id,
                dice_count=input.dice_count,
                die_sides=input.die_sides,
                flat_adjustment=input.flat_adjustment,
                visibility=input.visibility,
                idempotency_key=input.idempotency_key,
            ),
        )
        return result.model_dump(mode="json")

    def update_character_state(
        self,
        token: str,
        input: CharacterStateToolInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        subject_seat_id = self._subject_seat(actor, input.subject_seat_id)
        character = self.state_service.apply_patch(
            actor,
            subject_seat_id=subject_seat_id,
            patch=input.patch,
        )
        return character.model_dump(mode="json")

    def get_pending_events(
        self,
        token: str,
        input: EventsInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        return self.event_service.list_after(
            actor,
            after_seq=input.after_seq,
            limit=input.limit,
        ).model_dump(mode="json")

    async def wait_for_event(
        self,
        token: str,
        input: WaitEventsInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        if authenticated is None:
            actor = await asyncio.to_thread(self._actor, token)
        else:
            actor = self._actor(token, authenticated=authenticated)
        return (
            await self.event_service.wait_after(
                actor,
                after_seq=input.after_seq,
                limit=input.limit,
                timeout=input.timeout,
            )
        ).model_dump(mode="json")


__all__ = [
    "AIToolApplicationService",
    "AIToolInputError",
    "AIToolScopeError",
    "CharacterStateToolInput",
    "EventsInput",
    "PhysicalRollInput",
    "QuickRollToolInput",
    "RequestCheckToolInput",
    "RollPendingInput",
    "StageTextInput",
    "TextActionInput",
    "WaitEventsInput",
]
