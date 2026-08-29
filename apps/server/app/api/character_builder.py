from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.api.errors import APIError
from app.api.dependencies import get_character_builder_service
from app.domain.character_builder.schemas import (
    BuilderDraftCreateInput,
    BuilderDraftPatchInput,
    BuilderValidationResult,
    BuilderView,
)
from app.domain.character_builder.service import (
    BuilderModeNotEnabledError,
    CharacterBuilderService,
)
from app.persistence.builder_drafts import (
    BuilderDraftNotFoundError,
    BuilderDraftRevisionConflictError,
)


router = APIRouter(prefix="/api/character-builder", tags=["character-builder"])


def _not_found(exc: BuilderDraftNotFoundError) -> APIError:
    return APIError(404, "builder_draft_not_found", f"builder draft not found: {exc}")


@router.post(
    "/drafts",
    response_model=BuilderView,
    status_code=status.HTTP_201_CREATED,
)
def create_builder_draft(
    request: BuilderDraftCreateInput,
    service: CharacterBuilderService = Depends(get_character_builder_service),
) -> BuilderView:
    try:
        return service.create_draft(request)
    except BuilderModeNotEnabledError as exc:
        raise APIError(422, "builder_mode_not_enabled", str(exc)) from exc


@router.get("/drafts/{draft_id}", response_model=BuilderView)
def get_builder_draft(
    draft_id: UUID,
    service: CharacterBuilderService = Depends(get_character_builder_service),
) -> BuilderView:
    try:
        return service.get_draft(draft_id)
    except BuilderDraftNotFoundError as exc:
        raise _not_found(exc) from exc


@router.patch("/drafts/{draft_id}", response_model=BuilderView)
def patch_builder_draft(
    draft_id: UUID,
    request: BuilderDraftPatchInput,
    service: CharacterBuilderService = Depends(get_character_builder_service),
) -> BuilderView:
    try:
        return service.patch_draft(draft_id, request)
    except BuilderDraftNotFoundError as exc:
        raise _not_found(exc) from exc
    except BuilderDraftRevisionConflictError as exc:
        raise APIError(409, "stale_draft_revision", str(exc)) from exc


@router.post(
    "/drafts/{draft_id}/validate",
    response_model=BuilderValidationResult,
)
def validate_builder_draft(
    draft_id: UUID,
    service: CharacterBuilderService = Depends(get_character_builder_service),
) -> BuilderValidationResult:
    try:
        return service.validate_draft(draft_id)
    except BuilderDraftNotFoundError as exc:
        raise _not_found(exc) from exc


@router.delete(
    "/drafts/{draft_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def cancel_builder_draft(
    draft_id: UUID,
    service: CharacterBuilderService = Depends(get_character_builder_service),
) -> Response:
    try:
        service.cancel_draft(draft_id)
    except BuilderDraftNotFoundError as exc:
        raise _not_found(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
