from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.api.character_builder import (
    AbilityGenerationRulesDTO,
    VersionDraftCreateInput,
    _with_live_artificer_review,
    get_ability_generation_rules,
)
from app.api.errors import APIError
from app.api.rooms.access import get_room_access_context
from app.api.rooms.dependencies import get_room_workspace_service
from app.api.rooms.session_scope import (
    live_character_write_scope,
    live_draft_write_scope,
)
from app.domain.character_builder.creation import BuilderConfirmResult, BuilderReviewDTO
from app.domain.character_builder.schemas import (
    BuilderDraftCreateInput,
    BuilderDraftPatchInput,
    BuilderValidationResult,
    BuilderView,
)
from app.domain.character_builder.service import BuilderCannotConfirmError, BuilderModeNotEnabledError
from app.domain.rooms.schemas import RoomAccessContext
from app.domain.rooms.workspace import RoomCharacterWorkspaceService, RoomWorkspaceScopeError
from app.persistence.builder_drafts import (
    BuilderDraftAlreadyConfirmedError,
    BuilderDraftNotFoundError,
    BuilderDraftRevisionConflictError,
)
from app.persistence.characters import (
    CharacterNotFoundError,
    CharacterVersionNotFoundError,
    StaleBuildVersionError,
    StateReconciliationBlockedError,
)


router = APIRouter(
    prefix="/api/rooms/{room_id}/character-builder",
    tags=["room-character-builder"],
)


def _scope_error(exc: RoomWorkspaceScopeError) -> APIError:
    return APIError(404, "room_resource_not_found", "Room builder resource was not found")


def _not_found(exc: BuilderDraftNotFoundError) -> APIError:
    return APIError(404, "builder_draft_not_found", f"builder draft not found: {exc}")


def _already_confirmed(exc: BuilderDraftAlreadyConfirmedError) -> APIError:
    return APIError(409, "builder_draft_already_confirmed", str(exc))


@router.get("/rules/ability-generation", response_model=AbilityGenerationRulesDTO)
def ability_generation_rules(
    _context: RoomAccessContext = Depends(get_room_access_context),
) -> AbilityGenerationRulesDTO:
    return get_ability_generation_rules()


@router.post("/drafts", response_model=BuilderView, status_code=status.HTTP_201_CREATED)
def create_builder_draft(
    room_id: UUID,
    request: BuilderDraftCreateInput,
    _context: RoomAccessContext = Depends(get_room_access_context),
    service: RoomCharacterWorkspaceService = Depends(get_room_workspace_service),
) -> BuilderView:
    try:
        # This generic route is intentionally create-only. Preserve the existing
        # Builder mode contract before any P2 live Character scope lookup: legal
        # versioned workflows use /characters/{character_id}/drafts instead.
        return service.create_draft(room_id, request)
    except RoomWorkspaceScopeError as exc:
        raise _scope_error(exc) from exc
    except BuilderModeNotEnabledError as exc:
        raise APIError(422, "builder_mode_not_enabled", str(exc)) from exc


@router.post(
    "/characters/{character_id}/drafts",
    response_model=BuilderView,
    status_code=status.HTTP_201_CREATED,
)
def create_character_version_draft(
    room_id: UUID,
    character_id: UUID,
    request: VersionDraftCreateInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: RoomCharacterWorkspaceService = Depends(get_room_workspace_service),
) -> BuilderView:
    try:
        with live_character_write_scope(
            service,
            context=context,
            character_id=character_id,
        ) as scoped_service:
            return scoped_service.create_version_draft(
                room_id,
                character_id,
                request.mode,
            )
    except RoomWorkspaceScopeError as exc:
        raise _scope_error(exc) from exc
    except CharacterNotFoundError as exc:
        raise APIError(404, "character_not_found", f"character not found: {exc}") from exc
    except (CharacterVersionNotFoundError, ValueError) as exc:
        raise APIError(422, "version_draft_invalid", str(exc)) from exc


@router.get("/drafts", response_model=list[BuilderView])
def list_create_builder_drafts(
    room_id: UUID,
    _context: RoomAccessContext = Depends(get_room_access_context),
    service: RoomCharacterWorkspaceService = Depends(get_room_workspace_service),
) -> list[BuilderView]:
    return list(service.list_create_drafts(room_id))


@router.get("/characters/{character_id}/drafts", response_model=list[BuilderView])
def list_character_builder_drafts(
    room_id: UUID,
    character_id: UUID,
    _context: RoomAccessContext = Depends(get_room_access_context),
    service: RoomCharacterWorkspaceService = Depends(get_room_workspace_service),
) -> list[BuilderView]:
    try:
        return list(service.list_character_drafts(room_id, character_id))
    except RoomWorkspaceScopeError as exc:
        raise _scope_error(exc) from exc


@router.get("/drafts/{draft_id}", response_model=BuilderView)
def get_builder_draft(
    room_id: UUID,
    draft_id: UUID,
    _context: RoomAccessContext = Depends(get_room_access_context),
    service: RoomCharacterWorkspaceService = Depends(get_room_workspace_service),
) -> BuilderView:
    try:
        return service.get_draft(room_id, draft_id)
    except RoomWorkspaceScopeError as exc:
        raise _scope_error(exc) from exc
    except BuilderDraftNotFoundError as exc:
        raise _not_found(exc) from exc


@router.patch("/drafts/{draft_id}", response_model=BuilderView)
def patch_builder_draft(
    room_id: UUID,
    draft_id: UUID,
    request: BuilderDraftPatchInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: RoomCharacterWorkspaceService = Depends(get_room_workspace_service),
) -> BuilderView:
    try:
        with live_draft_write_scope(
            service,
            context=context,
            draft_id=draft_id,
        ) as scoped_service:
            return scoped_service.patch_draft(room_id, draft_id, request)
    except RoomWorkspaceScopeError as exc:
        raise _scope_error(exc) from exc
    except BuilderDraftNotFoundError as exc:
        raise _not_found(exc) from exc
    except BuilderDraftAlreadyConfirmedError as exc:
        raise _already_confirmed(exc) from exc
    except BuilderDraftRevisionConflictError as exc:
        raise APIError(409, "stale_draft_revision", str(exc)) from exc
    except ValueError as exc:
        raise APIError(422, "builder_patch_invalid", str(exc)) from exc


@router.post("/drafts/{draft_id}/validate", response_model=BuilderValidationResult)
def validate_builder_draft(
    room_id: UUID,
    draft_id: UUID,
    _context: RoomAccessContext = Depends(get_room_access_context),
    service: RoomCharacterWorkspaceService = Depends(get_room_workspace_service),
) -> BuilderValidationResult:
    try:
        return service.validate_draft(room_id, draft_id)
    except RoomWorkspaceScopeError as exc:
        raise _scope_error(exc) from exc
    except BuilderDraftNotFoundError as exc:
        raise _not_found(exc) from exc


@router.get("/drafts/{draft_id}/review", response_model=BuilderReviewDTO)
def review_builder_draft(
    room_id: UUID,
    draft_id: UUID,
    _context: RoomAccessContext = Depends(get_room_access_context),
    service: RoomCharacterWorkspaceService = Depends(get_room_workspace_service),
) -> BuilderReviewDTO:
    try:
        review = service.review_draft(room_id, draft_id)
        return _with_live_artificer_review(review, service.builder_service)
    except RoomWorkspaceScopeError as exc:
        raise _scope_error(exc) from exc
    except BuilderDraftNotFoundError as exc:
        raise _not_found(exc) from exc


@router.post("/drafts/{draft_id}/confirm", response_model=BuilderConfirmResult)
def confirm_builder_draft(
    room_id: UUID,
    draft_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: RoomCharacterWorkspaceService = Depends(get_room_workspace_service),
) -> BuilderConfirmResult:
    try:
        with live_draft_write_scope(
            service,
            context=context,
            draft_id=draft_id,
        ) as scoped_service:
            return scoped_service.confirm_draft(room_id, draft_id)
    except RoomWorkspaceScopeError as exc:
        raise _scope_error(exc) from exc
    except BuilderDraftNotFoundError as exc:
        raise _not_found(exc) from exc
    except BuilderDraftRevisionConflictError as exc:
        raise APIError(409, "stale_draft_revision", str(exc)) from exc
    except StaleBuildVersionError as exc:
        raise APIError(409, "stale_build_version", str(exc)) from exc
    except StateReconciliationBlockedError as exc:
        raise APIError(422, "state_reconciliation_blocked", str(exc)) from exc
    except BuilderCannotConfirmError as exc:
        blocking = [issue.message for issue in exc.validation.issues if issue.severity == "blocking_error"]
        raise APIError(422, "builder_confirm_blocked", blocking[0] if blocking else str(exc)) from exc


@router.delete("/drafts/{draft_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_builder_draft(
    room_id: UUID,
    draft_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: RoomCharacterWorkspaceService = Depends(get_room_workspace_service),
) -> Response:
    try:
        with live_draft_write_scope(
            service,
            context=context,
            draft_id=draft_id,
        ) as scoped_service:
            scoped_service.cancel_draft(room_id, draft_id)
    except RoomWorkspaceScopeError as exc:
        raise _scope_error(exc) from exc
    except BuilderDraftNotFoundError as exc:
        raise _not_found(exc) from exc
    except BuilderDraftAlreadyConfirmedError as exc:
        raise _already_confirmed(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
