from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, ConfigDict

from app.api.dependencies import get_character_builder_service
from app.api.errors import APIError
from app.domain.character_builder.creation import BuilderConfirmResult, BuilderReviewDTO
from app.domain.character_builder.rules import load_ability_generation_rules
from app.domain.character_builder.schemas import (
    BuilderDraftCreateInput,
    BuilderDraftPatchInput,
    BuilderMode,
    BuilderValidationResult,
    BuilderView,
)
from app.domain.character_builder.service import (
    BuilderCannotConfirmError,
    BuilderModeNotEnabledError,
    CharacterBuilderService,
)
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


router = APIRouter(prefix="/api/character-builder", tags=["character-builder"])


class AbilityGenerationRulesDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    standard_array: tuple[int, ...]
    point_buy_budget: int
    point_buy_costs: dict[int, int]
    manual_standard_min: int
    manual_standard_max: int
    hard_min: int
    hard_max: int


class VersionDraftCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: BuilderMode = BuilderMode.LEVEL_UP


def _not_found(exc: BuilderDraftNotFoundError) -> APIError:
    return APIError(404, "builder_draft_not_found", f"builder draft not found: {exc}")


def _already_confirmed(exc: BuilderDraftAlreadyConfirmedError) -> APIError:
    return APIError(409, "builder_draft_already_confirmed", str(exc))


@router.get("/rules/ability-generation", response_model=AbilityGenerationRulesDTO)
def get_ability_generation_rules() -> AbilityGenerationRulesDTO:
    rules = load_ability_generation_rules()
    return AbilityGenerationRulesDTO(
        standard_array=rules.standard_array,
        point_buy_budget=rules.point_buy_budget,
        point_buy_costs=rules.point_buy_costs,
        manual_standard_min=rules.manual_standard_min,
        manual_standard_max=rules.manual_standard_max,
        hard_min=rules.hard_min,
        hard_max=rules.hard_max,
    )


@router.post("/drafts", response_model=BuilderView, status_code=status.HTTP_201_CREATED)
def create_builder_draft(
    request: BuilderDraftCreateInput,
    service: CharacterBuilderService = Depends(get_character_builder_service),
) -> BuilderView:
    try:
        return service.create_draft(request)
    except BuilderModeNotEnabledError as exc:
        # Keep the P1-A public error contract for callers that try to create a
        # versioned draft through the generic create endpoint. P1-G adds the
        # character-scoped endpoint below rather than changing this response.
        raise APIError(422, "builder_mode_not_enabled", str(exc)) from exc


@router.post(
    "/characters/{character_id}/drafts",
    response_model=BuilderView,
    status_code=status.HTTP_201_CREATED,
)
def create_character_version_draft(
    character_id: UUID,
    request: VersionDraftCreateInput,
    service: CharacterBuilderService = Depends(get_character_builder_service),
) -> BuilderView:
    try:
        return service.create_version_draft(character_id, request.mode)
    except CharacterNotFoundError as exc:
        raise APIError(404, "character_not_found", f"character not found: {exc}") from exc
    except (CharacterVersionNotFoundError, ValueError) as exc:
        raise APIError(422, "version_draft_invalid", str(exc)) from exc


@router.get("/drafts", response_model=list[BuilderView])
def list_create_builder_drafts(
    service: CharacterBuilderService = Depends(get_character_builder_service),
) -> list[BuilderView]:
    return list(service.list_create_drafts())


@router.get("/characters/{character_id}/drafts", response_model=list[BuilderView])
def list_character_builder_drafts(
    character_id: UUID,
    service: CharacterBuilderService = Depends(get_character_builder_service),
) -> list[BuilderView]:
    return list(service.list_character_drafts(character_id))


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
    except BuilderDraftAlreadyConfirmedError as exc:
        raise _already_confirmed(exc) from exc
    except BuilderDraftRevisionConflictError as exc:
        raise APIError(409, "stale_draft_revision", str(exc)) from exc
    except ValueError as exc:
        raise APIError(422, "builder_patch_invalid", str(exc)) from exc


@router.post("/drafts/{draft_id}/validate", response_model=BuilderValidationResult)
def validate_builder_draft(
    draft_id: UUID,
    service: CharacterBuilderService = Depends(get_character_builder_service),
) -> BuilderValidationResult:
    try:
        return service.validate_draft(draft_id)
    except BuilderDraftNotFoundError as exc:
        raise _not_found(exc) from exc


@router.get("/drafts/{draft_id}/review", response_model=BuilderReviewDTO)
def review_builder_draft(
    draft_id: UUID,
    service: CharacterBuilderService = Depends(get_character_builder_service),
) -> BuilderReviewDTO:
    try:
        return service.review_draft(draft_id)
    except BuilderDraftNotFoundError as exc:
        raise _not_found(exc) from exc


@router.post("/drafts/{draft_id}/confirm", response_model=BuilderConfirmResult)
def confirm_builder_draft(
    draft_id: UUID,
    service: CharacterBuilderService = Depends(get_character_builder_service),
) -> BuilderConfirmResult:
    try:
        return service.confirm_draft(draft_id)
    except BuilderDraftNotFoundError as exc:
        raise _not_found(exc) from exc
    except BuilderDraftRevisionConflictError as exc:
        raise APIError(409, "stale_draft_revision", str(exc)) from exc
    except StaleBuildVersionError as exc:
        raise APIError(409, "stale_build_version", str(exc)) from exc
    except StateReconciliationBlockedError as exc:
        raise APIError(422, "state_reconciliation_blocked", str(exc)) from exc
    except BuilderCannotConfirmError as exc:
        blocking = [
            issue.message
            for issue in exc.validation.issues
            if issue.severity == "blocking_error"
        ]
        message = blocking[0] if blocking else str(exc)
        raise APIError(422, "builder_confirm_blocked", message) from exc


@router.delete("/drafts/{draft_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_builder_draft(
    draft_id: UUID,
    service: CharacterBuilderService = Depends(get_character_builder_service),
) -> Response:
    try:
        service.cancel_draft(draft_id)
    except BuilderDraftNotFoundError as exc:
        raise _not_found(exc) from exc
    except BuilderDraftAlreadyConfirmedError as exc:
        raise _already_confirmed(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
