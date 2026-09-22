from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator
from typing_extensions import Self

from app.domain.campaign_runtime.errors import (
    CampaignRuntimeValidationError,
)
from app.domain.campaign_runtime.schemas import (
    CampaignAdventureOverride,
    CampaignAdventureOverrideCreate,
    CampaignAdventureOverridePatch,
    CampaignRuntimeContext,
    CampaignRuntimeContextPatch,
    RuntimeWorldEntryCreate,
    RuntimeWorldEntryDmView,
    RuntimeWorldEntryPatch,
    validate_runtime_visibility_recipients,
)
from app.domain.campaign_runtime.service import CampaignRuntimeService
from app.domain.rooms.schemas import RoomAccessContext, StrictModel
from app.domain.rooms.table_events import TableActorContext


class SetAdventureOverrideIntent(StrictModel):
    adventure_entry_id: UUID
    state: dict[str, object] | None = None
    note: str | None = None
    needs_review: bool | None = None
    expected_override_id: UUID | None = None
    expected_revision: int | None = None

    @model_validator(mode="after")
    def _validate_intent(self) -> Self:
        if self.expected_override_id is None:
            if self.expected_revision is not None:
                raise ValueError("expected_revision must be absent when creating an override")
            if "state" in self.model_fields_set and self.state is None:
                raise ValueError("state cannot be None")
            if self.state is None:
                self.state = {}
            if self.needs_review is None:
                self.needs_review = False
        else:
            if self.expected_revision is None:
                raise ValueError("expected_revision is required when updating an override")
            if self.expected_revision < 1:
                raise ValueError("expected_revision must be at least 1")
            update_fields = self.model_fields_set & {"state", "note", "needs_review"}
            if not update_fields:
                raise ValueError(
                    "at least one of state, note, or needs_review must be provided for update"
                )
            if "state" in self.model_fields_set and self.state is None:
                raise ValueError("state cannot be None on update")
            if "needs_review" in self.model_fields_set and self.needs_review is None:
                raise ValueError("needs_review cannot be None on update")
        return self


class ClearAdventureOverrideIntent(StrictModel):
    adventure_entry_id: UUID
    expected_override_id: UUID
    expected_revision: int = Field(ge=1)


SetCurrentContextIntent = CampaignRuntimeContextPatch


class GrantCharacterKnowledgeIntent(StrictModel):
    entry_id: UUID
    expected_revision: int = Field(ge=1)
    character_recipient_ids: tuple[UUID, ...]


class SetEntryNeedsReviewIntent(StrictModel):
    target_kind: Literal["entry"] = "entry"
    entry_id: UUID
    expected_revision: int = Field(ge=1)
    needs_review: bool


class SetOverrideNeedsReviewIntent(StrictModel):
    target_kind: Literal["override"] = "override"
    adventure_entry_id: UUID
    expected_override_id: UUID
    expected_revision: int = Field(ge=1)
    needs_review: bool


SetNeedsReviewTarget = SetEntryNeedsReviewIntent | SetOverrideNeedsReviewIntent


class _DispatchTarget:
    def __init__(
        self,
        *,
        is_active: bool,
        actor: TableActorContext | None = None,
        context: RoomAccessContext | None = None,
        room_id: UUID,
        campaign_id: UUID,
    ) -> None:
        self.is_active = is_active
        self.actor = actor
        self.context = context
        self.room_id = room_id
        self.campaign_id = campaign_id


def _resolve_dispatch(
    actor_or_context: TableActorContext | RoomAccessContext,
    campaign_id: UUID | None = None,
    room_id: UUID | None = None,
) -> _DispatchTarget:
    if isinstance(actor_or_context, TableActorContext):
        if campaign_id is not None and campaign_id != actor_or_context.campaign_id:
            raise CampaignRuntimeValidationError(
                f"campaign_id {campaign_id} does not match actor campaign_id {actor_or_context.campaign_id}"
            )
        if room_id is not None and room_id != actor_or_context.room_id:
            raise CampaignRuntimeValidationError(
                f"room_id {room_id} does not match actor room_id {actor_or_context.room_id}"
            )
        return _DispatchTarget(
            is_active=True,
            actor=actor_or_context,
            room_id=actor_or_context.room_id,
            campaign_id=actor_or_context.campaign_id,
        )
    if isinstance(actor_or_context, RoomAccessContext):
        effective_room_id = room_id if room_id is not None else actor_or_context.room_id
        if campaign_id is None:
            raise CampaignRuntimeValidationError("campaign_id is required for management context")
        return _DispatchTarget(
            is_active=False,
            context=actor_or_context,
            room_id=effective_room_id,
            campaign_id=campaign_id,
        )
    raise CampaignRuntimeValidationError(
        f"Expected TableActorContext or RoomAccessContext, got {type(actor_or_context).__name__}"
    )


class CampaignWorldService:
    """Unified application service for Campaign World write intents (P6-D D1).

    Dispatches all eight public intents across both management (RoomAccessContext outside
    active session) and active (TableActorContext inside active session) paths, delegating
    to CampaignRuntimeService for canonical validation, concurrency, events, and idempotency.
    """

    def __init__(self, runtime_service: CampaignRuntimeService) -> None:
        self.runtime_service = runtime_service

    def create_world_entry(
        self,
        actor_or_context: TableActorContext | RoomAccessContext,
        payload: RuntimeWorldEntryCreate,
        *,
        idempotency_key: str,
        campaign_id: UUID | None = None,
        room_id: UUID | None = None,
    ) -> RuntimeWorldEntryDmView:
        target = _resolve_dispatch(actor_or_context, campaign_id=campaign_id, room_id=room_id)
        if target.is_active:
            assert target.actor is not None
            return self.runtime_service.create_active(
                target.actor, payload, idempotency_key=idempotency_key
            )
        assert target.context is not None
        return self.runtime_service.create_management(
            target.context,
            target.room_id,
            target.campaign_id,
            payload,
            idempotency_key=idempotency_key,
        )

    def update_world_entry(
        self,
        actor_or_context: TableActorContext | RoomAccessContext,
        entry_id: UUID,
        patch: RuntimeWorldEntryPatch,
        *,
        idempotency_key: str,
        campaign_id: UUID | None = None,
        room_id: UUID | None = None,
    ) -> RuntimeWorldEntryDmView:
        target = _resolve_dispatch(actor_or_context, campaign_id=campaign_id, room_id=room_id)
        if target.is_active:
            assert target.actor is not None
            return self.runtime_service.update_active(
                target.actor, entry_id, patch, idempotency_key=idempotency_key
            )
        assert target.context is not None
        return self.runtime_service.update_management(
            target.context,
            target.room_id,
            target.campaign_id,
            entry_id,
            patch,
            idempotency_key=idempotency_key,
        )

    def archive_world_entry(
        self,
        actor_or_context: TableActorContext | RoomAccessContext,
        entry_id: UUID,
        *,
        expected_revision: int,
        idempotency_key: str,
        campaign_id: UUID | None = None,
        room_id: UUID | None = None,
    ) -> RuntimeWorldEntryDmView:
        target = _resolve_dispatch(actor_or_context, campaign_id=campaign_id, room_id=room_id)
        if target.is_active:
            assert target.actor is not None
            return self.runtime_service.archive_active(
                target.actor, entry_id, expected_revision=expected_revision, idempotency_key=idempotency_key
            )
        assert target.context is not None
        return self.runtime_service.archive_management(
            target.context,
            target.room_id,
            target.campaign_id,
            entry_id,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
        )

    def set_adventure_override(
        self,
        actor_or_context: TableActorContext | RoomAccessContext,
        intent: SetAdventureOverrideIntent,
        *,
        idempotency_key: str,
        campaign_id: UUID | None = None,
        room_id: UUID | None = None,
    ) -> CampaignAdventureOverride:
        target = _resolve_dispatch(actor_or_context, campaign_id=campaign_id, room_id=room_id)
        if intent.expected_override_id is not None:
            if intent.expected_revision is None:
                raise CampaignRuntimeValidationError(
                    "expected_revision is required when updating an override"
                )
            patch_kwargs: dict[str, object] = {
                "expected_override_id": intent.expected_override_id,
                "expected_revision": intent.expected_revision,
            }
            if "state" in intent.model_fields_set:
                patch_kwargs["state"] = intent.state
            if "note" in intent.model_fields_set:
                patch_kwargs["note"] = intent.note
            if "needs_review" in intent.model_fields_set:
                patch_kwargs["needs_review"] = intent.needs_review

            patch = CampaignAdventureOverridePatch(**patch_kwargs)
            if target.is_active:
                assert target.actor is not None
                return self.runtime_service.update_override_active(
                    target.actor, intent.adventure_entry_id, patch, idempotency_key=idempotency_key
                )
            assert target.context is not None
            return self.runtime_service.update_override_management(
                target.context,
                target.room_id,
                target.campaign_id,
                intent.adventure_entry_id,
                patch,
                idempotency_key=idempotency_key,
            )

        if intent.expected_revision is not None:
            raise CampaignRuntimeValidationError(
                "expected_revision must be absent when creating an override"
            )

        create_payload = CampaignAdventureOverrideCreate(
            adventure_entry_id=intent.adventure_entry_id,
            state=intent.state if intent.state is not None else {},
            note=intent.note,
            needs_review=intent.needs_review if intent.needs_review is not None else False,
        )
        if target.is_active:
            assert target.actor is not None
            return self.runtime_service.create_override_active(
                target.actor, create_payload, idempotency_key=idempotency_key
            )
        assert target.context is not None
        return self.runtime_service.create_override_management(
            target.context,
            target.room_id,
            target.campaign_id,
            create_payload,
            idempotency_key=idempotency_key,
        )

    def clear_adventure_override(
        self,
        actor_or_context: TableActorContext | RoomAccessContext,
        intent: ClearAdventureOverrideIntent,
        *,
        idempotency_key: str,
        campaign_id: UUID | None = None,
        room_id: UUID | None = None,
    ) -> CampaignAdventureOverride:
        target = _resolve_dispatch(actor_or_context, campaign_id=campaign_id, room_id=room_id)
        if target.is_active:
            assert target.actor is not None
            return self.runtime_service.clear_override_active(
                target.actor,
                intent.adventure_entry_id,
                expected_override_id=intent.expected_override_id,
                expected_revision=intent.expected_revision,
                idempotency_key=idempotency_key,
            )
        assert target.context is not None
        return self.runtime_service.clear_override_management(
            target.context,
            target.room_id,
            target.campaign_id,
            intent.adventure_entry_id,
            expected_override_id=intent.expected_override_id,
            expected_revision=intent.expected_revision,
            idempotency_key=idempotency_key,
        )

    def set_current_context(
        self,
        actor_or_context: TableActorContext | RoomAccessContext,
        patch: CampaignRuntimeContextPatch,
        *,
        idempotency_key: str,
        campaign_id: UUID | None = None,
        room_id: UUID | None = None,
    ) -> CampaignRuntimeContext:
        target = _resolve_dispatch(actor_or_context, campaign_id=campaign_id, room_id=room_id)
        if target.is_active:
            assert target.actor is not None
            return self.runtime_service.update_context_active(
                target.actor, patch, idempotency_key=idempotency_key
            )
        assert target.context is not None
        return self.runtime_service.update_context_management(
            target.context,
            target.room_id,
            target.campaign_id,
            patch,
            idempotency_key=idempotency_key,
        )

    def grant_character_knowledge(
        self,
        actor_or_context: TableActorContext | RoomAccessContext,
        intent: GrantCharacterKnowledgeIntent,
        *,
        idempotency_key: str,
        campaign_id: UUID | None = None,
        room_id: UUID | None = None,
    ) -> RuntimeWorldEntryDmView:
        validate_runtime_visibility_recipients("character", intent.character_recipient_ids)
        patch = RuntimeWorldEntryPatch(
            expected_revision=intent.expected_revision,
            visibility="character",
            character_recipient_ids=intent.character_recipient_ids,
        )
        return self.update_world_entry(
            actor_or_context,
            intent.entry_id,
            patch,
            idempotency_key=idempotency_key,
            campaign_id=campaign_id,
            room_id=room_id,
        )

    def set_needs_review(
        self,
        actor_or_context: TableActorContext | RoomAccessContext,
        target: SetNeedsReviewTarget,
        *,
        idempotency_key: str,
        campaign_id: UUID | None = None,
        room_id: UUID | None = None,
    ) -> RuntimeWorldEntryDmView | CampaignAdventureOverride:
        if isinstance(target, SetEntryNeedsReviewIntent):
            patch = RuntimeWorldEntryPatch(
                expected_revision=target.expected_revision,
                needs_review=target.needs_review,
            )
            return self.update_world_entry(
                actor_or_context,
                target.entry_id,
                patch,
                idempotency_key=idempotency_key,
                campaign_id=campaign_id,
                room_id=room_id,
            )

        if isinstance(target, SetOverrideNeedsReviewIntent):
            override_patch = CampaignAdventureOverridePatch(
                expected_override_id=target.expected_override_id,
                expected_revision=target.expected_revision,
                needs_review=target.needs_review,
            )
            dispatch = _resolve_dispatch(actor_or_context, campaign_id=campaign_id, room_id=room_id)
            if dispatch.is_active:
                assert dispatch.actor is not None
                return self.runtime_service.update_override_active(
                    dispatch.actor,
                    target.adventure_entry_id,
                    override_patch,
                    idempotency_key=idempotency_key,
                )
            assert dispatch.context is not None
            return self.runtime_service.update_override_management(
                dispatch.context,
                dispatch.room_id,
                dispatch.campaign_id,
                target.adventure_entry_id,
                override_patch,
                idempotency_key=idempotency_key,
            )

        raise CampaignRuntimeValidationError(
            f"Unsupported needs_review target type: {type(target).__name__}"
        )
