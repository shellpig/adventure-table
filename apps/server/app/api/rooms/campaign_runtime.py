from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import Field, ValidationError

from app.api.errors import APIError
from app.api.rooms.access import get_room_access_context
from app.api.rooms.dependencies import get_campaign_runtime_service
from app.domain.campaign_runtime.payloads import (
    RuntimeEntryKind,
    RuntimeEntryPayloadError,
    RuntimeVisibility,
)
from app.domain.campaign_runtime.schemas import (
    CampaignAdventureEntryOverlayView,
    CampaignAdventureOverride,
    CampaignAdventureOverrideAlreadyExistsError,
    CampaignAdventureOverrideCreate,
    CampaignAdventureOverridePatch,
    CampaignRuntimeContext,
    CampaignRuntimeContextPatch,
    RuntimeEntryValidationError,
    RuntimeEntryVisibilityError,
    RuntimeWorldEntryCreate,
    RuntimeWorldEntryDmView,
    RuntimeWorldEntryPatch,
)
from app.domain.campaign_runtime.service import (
    CampaignRuntimeActiveSessionError,
    CampaignRuntimeArchivedError,
    CampaignRuntimeAuthorityError,
    CampaignRuntimeIdempotencyConflictError,
    CampaignRuntimeNotFoundError,
    CampaignRuntimeRevisionConflictError,
    CampaignRuntimeService,
    CampaignRuntimeSessionNotActiveError,
    CampaignRuntimeValidationError,
)
from app.domain.rooms.schemas import RoomAccessContext, StrictModel

router = APIRouter(
    prefix="/api/rooms/{room_id}/campaigns/{campaign_id}/runtime",
    tags=["campaign-runtime"],
)


def map_campaign_runtime_error(exc: Exception) -> APIError:
    if isinstance(exc, APIError):
        return exc
    if isinstance(exc, CampaignRuntimeAuthorityError):
        return APIError(403, "campaign_runtime_forbidden", str(exc))
    if isinstance(exc, CampaignRuntimeNotFoundError):
        return APIError(404, "campaign_runtime_not_found", str(exc))
    if isinstance(exc, CampaignRuntimeArchivedError):
        return APIError(409, "campaign_runtime_archived", str(exc))
    if isinstance(exc, CampaignRuntimeActiveSessionError):
        return APIError(409, "campaign_runtime_active_session", str(exc))
    if isinstance(exc, CampaignRuntimeSessionNotActiveError):
        return APIError(409, "campaign_runtime_session_not_active", str(exc))
    if isinstance(exc, CampaignRuntimeIdempotencyConflictError):
        return APIError(409, "campaign_runtime_idempotency_conflict", str(exc))
    if isinstance(exc, CampaignRuntimeRevisionConflictError):
        return APIError(409, "campaign_runtime_revision_conflict", str(exc))
    if isinstance(exc, CampaignAdventureOverrideAlreadyExistsError):
        return APIError(409, "campaign_runtime_override_exists", str(exc))
    if isinstance(
        exc,
        (
            CampaignRuntimeValidationError,
            RuntimeEntryValidationError,
            RuntimeEntryVisibilityError,
            RuntimeEntryPayloadError,
            ValidationError,
        ),
    ):
        return APIError(422, "campaign_runtime_invalid", str(exc))
    raise exc


class CreateRuntimeWorldEntryRequest(StrictModel):
    idempotency_key: str = Field(min_length=1)
    kind: RuntimeEntryKind
    title: str | None = Field(default=None, max_length=200)
    body: str | None = None
    state: dict[str, object] = Field(default_factory=dict)
    visibility: RuntimeVisibility = "public"
    character_recipient_ids: tuple[UUID, ...] = ()
    dm_notes: str | None = None
    source_adventure_entry_id: UUID | None = None
    provenance_json: dict[str, object] | None = None
    needs_review: bool = False

    def to_domain(self) -> RuntimeWorldEntryCreate:
        return RuntimeWorldEntryCreate(
            kind=self.kind,
            title=self.title,
            body=self.body,
            state=self.state,
            visibility=self.visibility,
            character_recipient_ids=self.character_recipient_ids,
            dm_notes=self.dm_notes,
            source_adventure_entry_id=self.source_adventure_entry_id,
            provenance_json=self.provenance_json,
            needs_review=self.needs_review,
        )


class UpdateRuntimeWorldEntryRequest(StrictModel):
    idempotency_key: str = Field(min_length=1)
    expected_revision: int = Field(ge=1)
    title: str | None = Field(default=None, max_length=200)
    body: str | None = None
    state: dict[str, object] | None = None
    visibility: RuntimeVisibility | None = None
    character_recipient_ids: tuple[UUID, ...] | None = None
    dm_notes: str | None = None
    source_adventure_entry_id: UUID | None = None
    provenance_json: dict[str, object] | None = None
    needs_review: bool | None = None

    def to_domain(self) -> RuntimeWorldEntryPatch:
        patch_fields = {
            k: v
            for k, v in self.model_dump(mode="python").items()
            if k in self.model_fields_set and k != "idempotency_key"
        }
        return RuntimeWorldEntryPatch.model_validate(patch_fields)


class ArchiveRuntimeWorldEntryRequest(StrictModel):
    expected_revision: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1)


class CreateCampaignAdventureOverrideRequest(StrictModel):
    idempotency_key: str = Field(min_length=1)
    adventure_entry_id: UUID
    state: dict[str, object] = Field(default_factory=dict)
    note: str | None = None
    needs_review: bool = False

    def to_domain(self) -> CampaignAdventureOverrideCreate:
        return CampaignAdventureOverrideCreate(
            adventure_entry_id=self.adventure_entry_id,
            state=self.state,
            note=self.note,
            needs_review=self.needs_review,
        )


class UpdateCampaignAdventureOverrideRequest(StrictModel):
    idempotency_key: str = Field(min_length=1)
    expected_override_id: UUID
    expected_revision: int = Field(ge=1)
    state: dict[str, object] | None = None
    note: str | None = None
    needs_review: bool | None = None

    def to_domain(self) -> CampaignAdventureOverridePatch:
        patch_fields = {
            k: v
            for k, v in self.model_dump(mode="python").items()
            if k in self.model_fields_set and k != "idempotency_key"
        }
        return CampaignAdventureOverridePatch.model_validate(patch_fields)


class ClearCampaignAdventureOverrideRequest(StrictModel):
    idempotency_key: str = Field(min_length=1)
    expected_override_id: UUID
    expected_revision: int = Field(ge=1)


class UpdateCampaignRuntimeContextRequest(StrictModel):
    idempotency_key: str = Field(min_length=1)
    expected_revision: int = Field(ge=0)
    current_adventure_scene_entry_id: UUID | None = None
    current_runtime_scene_entry_id: UUID | None = None
    current_situation: str | None = None

    def to_domain(self) -> CampaignRuntimeContextPatch:
        patch_fields = {
            k: v
            for k, v in self.model_dump(mode="python").items()
            if k in self.model_fields_set and k != "idempotency_key"
        }
        return CampaignRuntimeContextPatch.model_validate(patch_fields)


class ClearCampaignRuntimeContextRequest(StrictModel):
    idempotency_key: str = Field(min_length=1)
    expected_revision: int = Field(ge=0)


@router.get("/entries", response_model=list[RuntimeWorldEntryDmView])
def list_runtime_entries(
    room_id: UUID,
    campaign_id: UUID,
    include_archived: bool = False,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: CampaignRuntimeService = Depends(get_campaign_runtime_service),
) -> list[RuntimeWorldEntryDmView]:
    try:
        return list(
            service.list_management(
                context,
                room_id=room_id,
                campaign_id=campaign_id,
                include_archived=include_archived,
            )
        )
    except Exception as exc:
        raise map_campaign_runtime_error(exc) from exc


@router.get("/entries/{entry_id}", response_model=RuntimeWorldEntryDmView)
def get_runtime_entry(
    room_id: UUID,
    campaign_id: UUID,
    entry_id: UUID,
    include_archived: bool = False,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: CampaignRuntimeService = Depends(get_campaign_runtime_service),
) -> RuntimeWorldEntryDmView:
    try:
        return service.get_management(
            context,
            room_id=room_id,
            campaign_id=campaign_id,
            entry_id=entry_id,
            include_archived=include_archived,
        )
    except Exception as exc:
        raise map_campaign_runtime_error(exc) from exc


@router.post(
    "/entries",
    response_model=RuntimeWorldEntryDmView,
    status_code=status.HTTP_201_CREATED,
)
def create_runtime_entry(
    room_id: UUID,
    campaign_id: UUID,
    payload: CreateRuntimeWorldEntryRequest,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: CampaignRuntimeService = Depends(get_campaign_runtime_service),
) -> RuntimeWorldEntryDmView:
    try:
        domain_payload = payload.to_domain()
        return service.create_management(
            context,
            room_id=room_id,
            campaign_id=campaign_id,
            payload=domain_payload,
            idempotency_key=payload.idempotency_key,
        )
    except Exception as exc:
        raise map_campaign_runtime_error(exc) from exc


@router.patch("/entries/{entry_id}", response_model=RuntimeWorldEntryDmView)
def update_runtime_entry(
    room_id: UUID,
    campaign_id: UUID,
    entry_id: UUID,
    payload: UpdateRuntimeWorldEntryRequest,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: CampaignRuntimeService = Depends(get_campaign_runtime_service),
) -> RuntimeWorldEntryDmView:
    try:
        domain_patch = payload.to_domain()
        return service.update_management(
            context,
            room_id=room_id,
            campaign_id=campaign_id,
            entry_id=entry_id,
            patch=domain_patch,
            idempotency_key=payload.idempotency_key,
        )
    except Exception as exc:
        raise map_campaign_runtime_error(exc) from exc


@router.post("/entries/{entry_id}/archive", response_model=RuntimeWorldEntryDmView)
def archive_runtime_entry(
    room_id: UUID,
    campaign_id: UUID,
    entry_id: UUID,
    payload: ArchiveRuntimeWorldEntryRequest,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: CampaignRuntimeService = Depends(get_campaign_runtime_service),
) -> RuntimeWorldEntryDmView:
    try:
        return service.archive_management(
            context,
            room_id=room_id,
            campaign_id=campaign_id,
            entry_id=entry_id,
            expected_revision=payload.expected_revision,
            idempotency_key=payload.idempotency_key,
        )
    except Exception as exc:
        raise map_campaign_runtime_error(exc) from exc


@router.get("/overrides", response_model=list[CampaignAdventureOverride])
def list_overrides(
    room_id: UUID,
    campaign_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: CampaignRuntimeService = Depends(get_campaign_runtime_service),
) -> list[CampaignAdventureOverride]:
    try:
        return list(
            service.list_overrides_management(
                context,
                room_id=room_id,
                campaign_id=campaign_id,
            )
        )
    except Exception as exc:
        raise map_campaign_runtime_error(exc) from exc


@router.get("/overrides/{adventure_entry_id}", response_model=CampaignAdventureOverride)
def get_override(
    room_id: UUID,
    campaign_id: UUID,
    adventure_entry_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: CampaignRuntimeService = Depends(get_campaign_runtime_service),
) -> CampaignAdventureOverride:
    try:
        return service.get_override_management(
            context,
            room_id=room_id,
            campaign_id=campaign_id,
            adventure_entry_id=adventure_entry_id,
        )
    except Exception as exc:
        raise map_campaign_runtime_error(exc) from exc


@router.post(
    "/overrides",
    response_model=CampaignAdventureOverride,
    status_code=status.HTTP_201_CREATED,
)
def create_override(
    room_id: UUID,
    campaign_id: UUID,
    payload: CreateCampaignAdventureOverrideRequest,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: CampaignRuntimeService = Depends(get_campaign_runtime_service),
) -> CampaignAdventureOverride:
    try:
        domain_payload = payload.to_domain()
        return service.create_override_management(
            context,
            room_id=room_id,
            campaign_id=campaign_id,
            payload=domain_payload,
            idempotency_key=payload.idempotency_key,
        )
    except Exception as exc:
        raise map_campaign_runtime_error(exc) from exc


@router.patch("/overrides/{adventure_entry_id}", response_model=CampaignAdventureOverride)
def update_override(
    room_id: UUID,
    campaign_id: UUID,
    adventure_entry_id: UUID,
    payload: UpdateCampaignAdventureOverrideRequest,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: CampaignRuntimeService = Depends(get_campaign_runtime_service),
) -> CampaignAdventureOverride:
    try:
        domain_patch = payload.to_domain()
        return service.update_override_management(
            context,
            room_id=room_id,
            campaign_id=campaign_id,
            adventure_entry_id=adventure_entry_id,
            patch=domain_patch,
            idempotency_key=payload.idempotency_key,
        )
    except Exception as exc:
        raise map_campaign_runtime_error(exc) from exc


@router.post("/overrides/{adventure_entry_id}/clear", response_model=CampaignAdventureOverride)
def clear_override(
    room_id: UUID,
    campaign_id: UUID,
    adventure_entry_id: UUID,
    payload: ClearCampaignAdventureOverrideRequest,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: CampaignRuntimeService = Depends(get_campaign_runtime_service),
) -> CampaignAdventureOverride:
    try:
        return service.clear_override_management(
            context,
            room_id=room_id,
            campaign_id=campaign_id,
            adventure_entry_id=adventure_entry_id,
            expected_override_id=payload.expected_override_id,
            expected_revision=payload.expected_revision,
            idempotency_key=payload.idempotency_key,
        )
    except Exception as exc:
        raise map_campaign_runtime_error(exc) from exc


@router.get("/context", response_model=CampaignRuntimeContext)
def get_context(
    room_id: UUID,
    campaign_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: CampaignRuntimeService = Depends(get_campaign_runtime_service),
) -> CampaignRuntimeContext:
    try:
        return service.get_context_management(
            context,
            room_id=room_id,
            campaign_id=campaign_id,
        )
    except Exception as exc:
        raise map_campaign_runtime_error(exc) from exc


@router.patch("/context", response_model=CampaignRuntimeContext)
def update_context(
    room_id: UUID,
    campaign_id: UUID,
    payload: UpdateCampaignRuntimeContextRequest,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: CampaignRuntimeService = Depends(get_campaign_runtime_service),
) -> CampaignRuntimeContext:
    try:
        domain_patch = payload.to_domain()
        return service.update_context_management(
            context,
            room_id=room_id,
            campaign_id=campaign_id,
            patch=domain_patch,
            idempotency_key=payload.idempotency_key,
        )
    except Exception as exc:
        raise map_campaign_runtime_error(exc) from exc


@router.post("/context/clear", response_model=CampaignRuntimeContext)
def clear_context(
    room_id: UUID,
    campaign_id: UUID,
    payload: ClearCampaignRuntimeContextRequest,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: CampaignRuntimeService = Depends(get_campaign_runtime_service),
) -> CampaignRuntimeContext:
    try:
        return service.clear_context_management(
            context,
            room_id=room_id,
            campaign_id=campaign_id,
            expected_revision=payload.expected_revision,
            idempotency_key=payload.idempotency_key,
        )
    except Exception as exc:
        raise map_campaign_runtime_error(exc) from exc


@router.get(
    "/adventure-overlays/{adventure_entry_id}",
    response_model=CampaignAdventureEntryOverlayView,
)
def get_adventure_entry_overlay(
    room_id: UUID,
    campaign_id: UUID,
    adventure_entry_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: CampaignRuntimeService = Depends(get_campaign_runtime_service),
) -> CampaignAdventureEntryOverlayView:
    try:
        return service.get_adventure_entry_overlay_management(
            context,
            room_id=room_id,
            campaign_id=campaign_id,
            adventure_entry_id=adventure_entry_id,
        )
    except Exception as exc:
        raise map_campaign_runtime_error(exc) from exc


@router.get(
    "/adventures/{adventure_id}/overlays",
    response_model=list[CampaignAdventureEntryOverlayView],
)
def list_adventure_entry_overlays(
    room_id: UUID,
    campaign_id: UUID,
    adventure_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: CampaignRuntimeService = Depends(get_campaign_runtime_service),
) -> list[CampaignAdventureEntryOverlayView]:
    try:
        return list(
            service.list_adventure_entry_overlays_management(
                context,
                room_id=room_id,
                campaign_id=campaign_id,
                adventure_id=adventure_id,
            )
        )
    except Exception as exc:
        raise map_campaign_runtime_error(exc) from exc


__all__ = [
    "ArchiveRuntimeWorldEntryRequest",
    "ClearCampaignAdventureOverrideRequest",
    "ClearCampaignRuntimeContextRequest",
    "CreateCampaignAdventureOverrideRequest",
    "CreateRuntimeWorldEntryRequest",
    "UpdateCampaignAdventureOverrideRequest",
    "UpdateCampaignRuntimeContextRequest",
    "UpdateRuntimeWorldEntryRequest",
    "map_campaign_runtime_error",
    "router",
]
