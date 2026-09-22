from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from typing_extensions import Self

from app.domain.campaign_runtime.context_mutations import (
    execute_update_context_in_transaction,
)
from app.domain.campaign_runtime.entry_mutations import (
    RESERVED_INTERNAL_IDEMPOTENCY_PREFIX,
    execute_archive_entry_in_transaction,
    execute_create_entry_in_transaction,
    execute_update_entry_in_transaction,
    validate_idempotency_key,
    validate_mutation_identity,
)
from app.domain.campaign_runtime.errors import (
    CampaignRuntimeAuthorityError,
    CampaignRuntimeIdempotencyConflictError,
    CampaignRuntimeNotFoundError,
    CampaignRuntimeValidationError,
)
from app.domain.campaign_runtime.events import (
    actor_identity,
    context_event_envelope,
    override_event_envelope,
    runtime_entry_event_envelope,
)
from app.domain.campaign_runtime.override_mutations import (
    execute_clear_override_in_transaction,
    execute_create_override_in_transaction,
    execute_update_override_in_transaction,
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
from app.domain.rooms.exploration import MAX_EXPLORATION_TEXT_LENGTH
from app.domain.rooms.schemas import RoomAccessContext, StrictModel
from app.domain.rooms.table_events import TableActorContext
from app.persistence.campaign_runtime.mutations import (
    StoredCampaignWorldMutation,
)
from app.persistence.rooms.exploration_messages import (
    ExplorationMessageRepository,
)


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


class CreateWorldEntryChange(StrictModel):
    action: Literal["create_entry"] = "create_entry"
    payload: RuntimeWorldEntryCreate


class UpdateWorldEntryChange(StrictModel):
    action: Literal["update_entry"] = "update_entry"
    entry_id: UUID
    patch: RuntimeWorldEntryPatch


class ArchiveWorldEntryChange(StrictModel):
    action: Literal["archive_entry"] = "archive_entry"
    entry_id: UUID
    expected_revision: int = Field(ge=1)


class SetAdventureOverrideChange(StrictModel):
    action: Literal["set_override"] = "set_override"
    intent: SetAdventureOverrideIntent


class ClearAdventureOverrideChange(StrictModel):
    action: Literal["clear_override"] = "clear_override"
    intent: ClearAdventureOverrideIntent


class SetCurrentContextChange(StrictModel):
    action: Literal["set_context"] = "set_context"
    patch: CampaignRuntimeContextPatch


WorldActionChange = Annotated[
    CreateWorldEntryChange
    | UpdateWorldEntryChange
    | ArchiveWorldEntryChange
    | SetAdventureOverrideChange
    | ClearAdventureOverrideChange
    | SetCurrentContextChange,
    Field(discriminator="action"),
]


class ResolveWorldActionRequest(StrictModel):
    change: WorldActionChange = Field(discriminator="action")
    narration: str | None = Field(default=None, max_length=MAX_EXPLORATION_TEXT_LENGTH)

    @model_validator(mode="after")
    def _validate_narration(self) -> Self:
        if self.narration is not None:
            stripped = self.narration.strip()
            if not stripped:
                raise ValueError("narration cannot be blank")
            self.narration = stripped
        return self


class ResolveWorldActionResult(StrictModel):
    action: str
    entry: RuntimeWorldEntryDmView | None = None
    override: CampaignAdventureOverride | None = None
    context: CampaignRuntimeContext | None = None
    narration: str | None = None
    action_event_id: UUID
    action_event_seq: int
    narration_event_id: UUID | None = None
    narration_event_seq: int | None = None

    @property
    def result(
        self,
    ) -> RuntimeWorldEntryDmView | CampaignAdventureOverride | CampaignRuntimeContext:
        if self.entry is not None:
            return self.entry
        if self.override is not None:
            return self.override
        if self.context is not None:
            return self.context
        raise ValueError("No result present")


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


def _convert_override_intent(
    intent: SetAdventureOverrideIntent,
) -> CampaignAdventureOverrideCreate | CampaignAdventureOverridePatch:
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

        return CampaignAdventureOverridePatch(**patch_kwargs)

    if intent.expected_revision is not None:
        raise CampaignRuntimeValidationError(
            "expected_revision must be absent when creating an override"
        )

    return CampaignAdventureOverrideCreate(
        adventure_entry_id=intent.adventure_entry_id,
        state=intent.state if intent.state is not None else {},
        note=intent.note,
        needs_review=intent.needs_review if intent.needs_review is not None else False,
    )


class CampaignWorldService:
    """Unified application service for Campaign World write intents (P6-D D1).

    Dispatches all eight public intents across both management (RoomAccessContext outside
    active session) and active (TableActorContext inside active session) paths, delegating
    to CampaignRuntimeService for canonical validation, concurrency, events, and idempotency.
    """

    def __init__(
        self,
        runtime_service: CampaignRuntimeService,
        message_repository: ExplorationMessageRepository | None = None,
    ) -> None:
        self.runtime_service = runtime_service
        self.message_repo = (
            message_repository
            if message_repository is not None
            else ExplorationMessageRepository(runtime_service.engine)
        )

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
        converted = _convert_override_intent(intent)
        if isinstance(converted, CampaignAdventureOverridePatch):
            if target.is_active:
                assert target.actor is not None
                return self.runtime_service.update_override_active(
                    target.actor, intent.adventure_entry_id, converted, idempotency_key=idempotency_key
                )
            assert target.context is not None
            return self.runtime_service.update_override_management(
                target.context,
                target.room_id,
                target.campaign_id,
                intent.adventure_entry_id,
                converted,
                idempotency_key=idempotency_key,
            )

        if target.is_active:
            assert target.actor is not None
            return self.runtime_service.create_override_active(
                target.actor, converted, idempotency_key=idempotency_key
            )
        assert target.context is not None
        return self.runtime_service.create_override_management(
            target.context,
            target.room_id,
            target.campaign_id,
            converted,
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

    def resolve_world_action(
        self,
        actor: TableActorContext,
        request: ResolveWorldActionRequest,
        *,
        idempotency_key: str,
    ) -> ResolveWorldActionResult:
        if not isinstance(actor, TableActorContext):
            raise CampaignRuntimeValidationError(
                f"Expected TableActorContext, got {type(actor).__name__}"
            )
        if not actor.is_current_dm or actor.role != "dm":
            raise CampaignRuntimeAuthorityError("Only the current DM may resolve world actions")

        validate_idempotency_key(idempotency_key)
        actor_kind, actor_id = actor_identity(actor)
        now = datetime.now(timezone.utc)
        inner_key = f"{RESERVED_INTERNAL_IDEMPOTENCY_PREFIX}{hashlib.sha256(idempotency_key.encode('utf-8')).hexdigest()}"
        action_event_key = f"p6d-world-action:{hashlib.sha256(idempotency_key.encode('utf-8')).hexdigest()}"
        narration_event_key = f"p6d-narration:{hashlib.sha256(idempotency_key.encode('utf-8')).hexdigest()}"

        with self.runtime_service.engine.begin() as connection:
            binding = self.runtime_service._require_active_dm_authority(
                connection, actor, action_verb="resolve world action"
            )

            campaign = self.runtime_service.campaign_repo.get_for_update_in_transaction(
                connection, actor.campaign_id
            )
            if campaign is None:
                raise CampaignRuntimeNotFoundError(f"Campaign {actor.campaign_id} not found")

            stored_mutation = self.runtime_service.mutation_repo.get_in_transaction(
                connection, actor.campaign_id, idempotency_key
            )
            if stored_mutation is not None:
                validate_mutation_identity(
                    stored_mutation,
                    action_kind="world_action.resolve",
                    target_id=stored_mutation.target_id,
                    command_payload=request.model_dump(mode="json"),
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                )
                return ResolveWorldActionResult.model_validate(stored_mutation.result_payload)

            change = request.change
            target_id: UUID | None = None
            entry_result: RuntimeWorldEntryDmView | None = None
            override_result: CampaignAdventureOverride | None = None
            context_result: CampaignRuntimeContext | None = None

            if isinstance(change, CreateWorldEntryChange):
                entry_result, aggregate = execute_create_entry_in_transaction(
                    connection,
                    room_id=actor.room_id,
                    campaign_id=actor.campaign_id,
                    payload=change.payload,
                    idempotency_key=inner_key,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    now=now,
                    runtime_repo=self.runtime_service.runtime_repo,
                    mutation_repo=self.runtime_service.mutation_repo,
                    link_repo=self.runtime_service.link_repo,
                )
                target_id = entry_result.id
                _, visibility, recipient_seats, safe_payload = runtime_entry_event_envelope(
                    connection,
                    actor.session_id,
                    entry_result,
                    aggregate,
                    "created",
                    self.runtime_service.event_service,
                )

            elif isinstance(change, UpdateWorldEntryChange):
                entry_result, aggregate = execute_update_entry_in_transaction(
                    connection,
                    room_id=actor.room_id,
                    campaign_id=actor.campaign_id,
                    entry_id=change.entry_id,
                    patch=change.patch,
                    idempotency_key=inner_key,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    now=now,
                    runtime_repo=self.runtime_service.runtime_repo,
                    mutation_repo=self.runtime_service.mutation_repo,
                    link_repo=self.runtime_service.link_repo,
                )
                target_id = change.entry_id
                _, visibility, recipient_seats, safe_payload = runtime_entry_event_envelope(
                    connection,
                    actor.session_id,
                    entry_result,
                    aggregate,
                    "updated",
                    self.runtime_service.event_service,
                )

            elif isinstance(change, ArchiveWorldEntryChange):
                entry_result, aggregate = execute_archive_entry_in_transaction(
                    connection,
                    campaign_id=actor.campaign_id,
                    entry_id=change.entry_id,
                    expected_revision=change.expected_revision,
                    idempotency_key=inner_key,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    now=now,
                    runtime_repo=self.runtime_service.runtime_repo,
                    mutation_repo=self.runtime_service.mutation_repo,
                )
                target_id = change.entry_id
                _, visibility, recipient_seats, safe_payload = runtime_entry_event_envelope(
                    connection,
                    actor.session_id,
                    entry_result,
                    aggregate,
                    "archived",
                    self.runtime_service.event_service,
                )

            elif isinstance(change, SetAdventureOverrideChange):
                converted = _convert_override_intent(change.intent)
                if isinstance(converted, CampaignAdventureOverridePatch):
                    override_result = execute_update_override_in_transaction(
                        connection,
                        room_id=actor.room_id,
                        campaign_id=actor.campaign_id,
                        adventure_entry_id=change.intent.adventure_entry_id,
                        patch=converted,
                        idempotency_key=inner_key,
                        actor_kind=actor_kind,
                        actor_id=actor_id,
                        now=now,
                        runtime_repo=self.runtime_service.runtime_repo,
                        mutation_repo=self.runtime_service.mutation_repo,
                        link_repo=self.runtime_service.link_repo,
                    )
                    target_id = change.intent.adventure_entry_id
                    _, visibility, recipient_seats, safe_payload = override_event_envelope(
                        override_result, "updated"
                    )
                else:
                    override_result = execute_create_override_in_transaction(
                        connection,
                        room_id=actor.room_id,
                        campaign_id=actor.campaign_id,
                        payload=converted,
                        idempotency_key=inner_key,
                        actor_kind=actor_kind,
                        actor_id=actor_id,
                        now=now,
                        runtime_repo=self.runtime_service.runtime_repo,
                        mutation_repo=self.runtime_service.mutation_repo,
                        link_repo=self.runtime_service.link_repo,
                    )
                    target_id = change.intent.adventure_entry_id
                    _, visibility, recipient_seats, safe_payload = override_event_envelope(
                        override_result, "created"
                    )

            elif isinstance(change, ClearAdventureOverrideChange):
                override_result = execute_clear_override_in_transaction(
                    connection,
                    campaign_id=actor.campaign_id,
                    adventure_entry_id=change.intent.adventure_entry_id,
                    expected_override_id=change.intent.expected_override_id,
                    expected_revision=change.intent.expected_revision,
                    idempotency_key=inner_key,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    now=now,
                    runtime_repo=self.runtime_service.runtime_repo,
                    mutation_repo=self.runtime_service.mutation_repo,
                )
                target_id = change.intent.adventure_entry_id
                _, visibility, recipient_seats, safe_payload = override_event_envelope(
                    override_result, "cleared"
                )

            elif isinstance(change, SetCurrentContextChange):
                context_result = execute_update_context_in_transaction(
                    connection,
                    room_id=actor.room_id,
                    campaign_id=actor.campaign_id,
                    patch=change.patch,
                    idempotency_key=inner_key,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    now=now,
                    runtime_repo=self.runtime_service.runtime_repo,
                    mutation_repo=self.runtime_service.mutation_repo,
                    link_repo=self.runtime_service.link_repo,
                )
                target_id = actor.campaign_id
                _, visibility, recipient_seats, safe_payload = context_event_envelope(
                    context_result, "updated"
                )
            else:
                raise CampaignRuntimeValidationError(
                    f"Unsupported change type: {type(change).__name__}"
                )

            action_event = self.runtime_service.event_service.repository.append_in_transaction(
                connection,
                room_id=actor.room_id,
                campaign_id=actor.campaign_id,
                session_id=actor.session_id,
                kind="world.action.resolved",
                acting_seat_id=actor.seat_id,
                subject_seat_id=None,
                subject_character_id=None,
                execution_mode="self",
                visibility=visibility,
                recipient_seat_ids=tuple(recipient_seats),
                payload_version=1,
                payload={
                    **safe_payload,
                    "action": change.action,
                },
                idempotency_key=action_event_key,
                expected_actor_binding=binding,
            )

            narration_event_id: UUID | None = None
            narration_event_seq: int | None = None

            if request.narration is not None:
                narration_event = self.message_repo.append_message_in_transaction(
                    connection,
                    binding=binding,
                    message_kind="narration",
                    text=request.narration,
                    acting_seat_id=actor.seat_id,
                    subject_seat_id=None,
                    subject_character_id=None,
                    execution_mode="self",
                    visibility="public",
                    recipient_seat_ids=(),
                    source_command=None,
                    idempotency_key=narration_event_key,
                )
                narration_event_id = narration_event.id
                narration_event_seq = narration_event.seq

            result = ResolveWorldActionResult(
                action=change.action,
                entry=entry_result,
                override=override_result,
                context=context_result,
                narration=request.narration,
                action_event_id=action_event.id,
                action_event_seq=action_event.seq,
                narration_event_id=narration_event_id,
                narration_event_seq=narration_event_seq,
            )
            mutation = StoredCampaignWorldMutation(
                id=uuid4(),
                campaign_id=actor.campaign_id,
                idempotency_key=idempotency_key,
                action_kind="world_action.resolve",
                target_id=target_id,
                command_payload=request.model_dump(mode="json"),
                result_payload=result.model_dump(mode="json"),
                created_by_actor_kind=actor_kind,
                created_by_actor_id=actor_id,
                created_at=now,
            )
            self.runtime_service.mutation_repo.insert_in_transaction(connection, mutation)

        if self.runtime_service.event_service.notifier is not None:
            self.runtime_service.event_service.notifier.notify(actor.session_id)

        return result
