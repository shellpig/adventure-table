from __future__ import annotations

import logging
from typing import Annotated, Literal, Union
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.exceptions import RequestValidationError
from pydantic import Field, TypeAdapter, ValidationError

from app.api.errors import APIError
from app.api.rooms.access import get_room_access_context
from app.api.rooms.adventures import _map_adventure_error
from app.api.rooms.dependencies import (
    get_adventure_import_service,
    get_room_asset_service,
)
from app.domain.adventure_imports.errors import (
    AdventureImportBlockingWarningsError,
    AdventureImportForbiddenError,
    AdventureImportNotFoundError,
    AdventureImportRevisionConflictError,
    AdventureImportValidationError,
)
from app.domain.adventure_imports.schemas import (
    AdventureImport,
    AdventureImportDraft,
    AdventureImportSource,
    DraftWarning,
    ImportDraft,
    ReviewStatus,
    SourceChunk,
)
from app.domain.adventures.schemas import AdventureDefinition
from app.domain.adventure_imports.service import (
    AdventureImportService,
    require_import_author,
)
from app.domain.room_assets.schemas import (
    RoomAssetEmptyError,
    RoomAssetForbiddenError,
    RoomAssetInUseError,
    RoomAssetNotFoundError,
    RoomAssetTooLargeError,
    RoomAssetUnsupportedMediaTypeError,
    RoomAssetVisibilityNotAllowedError,
)
from app.domain.room_assets.service import RoomAssetService
from app.domain.rooms.schemas import RoomAccessContext, StrictModel

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/rooms/{room_id}/adventure-imports",
    tags=["adventure-imports"],
)

RAW_SOURCE_MIME_TYPES: dict[str, str] = {
    "txt": "text/plain",
    "markdown": "text/markdown",
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


class CreateAdventureImportRequest(StrictModel):
    name: str = Field(min_length=1, max_length=200)


class CancelAdventureImportRequest(StrictModel):
    expected_revision: int


class PasteSourcePayload(StrictModel):
    source_kind: Literal["paste"] = "paste"
    text: str
    filename: str | None = None
    media_type: str | None = None


class UrlSourcePayload(StrictModel):
    source_kind: Literal["url"] = "url"
    url: str
    text: str | None = None
    excerpt: str | None = None
    title: str | None = None


JsonSourcePayload = Annotated[
    Union[PasteSourcePayload, UrlSourcePayload],
    Field(discriminator="source_kind"),
]

_JSON_SOURCE_ADAPTER = TypeAdapter(JsonSourcePayload)


class AddSourceFromAssetRequest(StrictModel):
    asset_id: UUID


class UpdateImportDraftRequest(StrictModel):
    draft: ImportDraft
    warnings: list[DraftWarning] = Field(default_factory=list)
    expected_revision: int


class SetEntryReviewRequest(StrictModel):
    review_status: ReviewStatus
    expected_revision: int


class ResolveWarningRequest(StrictModel):
    resolution: str | None = None
    expected_revision: int


class AnswerQuestionRequest(StrictModel):
    answer: str
    expected_revision: int


class FinalizeAdventureImportRequest(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    summary: str | None = None
    expected_revision: int


def _map_adventure_import_error(exc: Exception) -> APIError:
    if isinstance(exc, APIError):
        return exc
    if isinstance(exc, AdventureImportNotFoundError):
        return APIError(404, "adventure_import_not_found", str(exc))
    if isinstance(exc, AdventureImportForbiddenError):
        return APIError(403, "adventure_import_authority_required", str(exc))
    if isinstance(exc, AdventureImportRevisionConflictError):
        return APIError(409, "adventure_import_revision_conflict", str(exc))
    if isinstance(exc, AdventureImportBlockingWarningsError):
        return APIError(
            409,
            "adventure_import_blocking_warnings",
            str(exc),
            params={"warning_ids": list(exc.unresolved_warning_ids)},
        )
    if isinstance(exc, AdventureImportValidationError):
        return APIError(400, "adventure_import_invalid", str(exc))
    if isinstance(exc, RoomAssetNotFoundError):
        return APIError(404, "room_asset_not_found", str(exc))
    if isinstance(exc, RoomAssetForbiddenError):
        return APIError(403, "room_asset_authority_required", str(exc))
    if isinstance(exc, RoomAssetUnsupportedMediaTypeError):
        return APIError(400, "asset_media_type_not_supported", str(exc))
    if isinstance(exc, RoomAssetTooLargeError):
        return APIError(413, "asset_too_large", str(exc))
    if isinstance(exc, RoomAssetEmptyError):
        return APIError(400, "asset_empty", str(exc))
    if isinstance(exc, RoomAssetVisibilityNotAllowedError):
        return APIError(400, "asset_visibility_not_allowed", str(exc))
    if isinstance(exc, RoomAssetInUseError):
        return APIError(409, "asset_in_use", str(exc))
    return _map_adventure_error(exc)


@router.post("", response_model=AdventureImport, status_code=status.HTTP_201_CREATED)
def create_import(
    room_id: UUID,
    payload: CreateAdventureImportRequest,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: AdventureImportService = Depends(get_adventure_import_service),
) -> AdventureImport:
    try:
        return service.create_import(context, room_id=room_id, name=payload.name)
    except Exception as exc:
        raise _map_adventure_import_error(exc) from exc


@router.get("", response_model=list[AdventureImport])
def list_imports(
    room_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: AdventureImportService = Depends(get_adventure_import_service),
) -> list[AdventureImport]:
    try:
        return list(service.list_imports(context, room_id=room_id))
    except Exception as exc:
        raise _map_adventure_import_error(exc) from exc


@router.get("/{import_id}", response_model=AdventureImport)
def get_import(
    room_id: UUID,
    import_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: AdventureImportService = Depends(get_adventure_import_service),
) -> AdventureImport:
    try:
        return service.get_import(context, room_id=room_id, import_id=import_id)
    except Exception as exc:
        raise _map_adventure_import_error(exc) from exc


@router.post("/{import_id}/cancel", response_model=AdventureImport)
def cancel_import(
    room_id: UUID,
    import_id: UUID,
    payload: CancelAdventureImportRequest,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: AdventureImportService = Depends(get_adventure_import_service),
) -> AdventureImport:
    try:
        return service.cancel_import(
            context,
            room_id=room_id,
            import_id=import_id,
            expected_revision=payload.expected_revision,
        )
    except Exception as exc:
        raise _map_adventure_import_error(exc) from exc


@router.post("/{import_id}/sources", response_model=AdventureImportSource)
async def add_source(
    room_id: UUID,
    import_id: UUID,
    request: Request,
    source_kind: str | None = Query(default=None),
    filename: str | None = Query(default=None, min_length=1, max_length=255),
    context: RoomAccessContext = Depends(get_room_access_context),
    service: AdventureImportService = Depends(get_adventure_import_service),
    room_asset_service: RoomAssetService = Depends(get_room_asset_service),
) -> AdventureImportSource:
    # 1. Authority check before any side effects or body reading
    try:
        require_import_author(context, room_id)
    except Exception as exc:
        raise _map_adventure_import_error(exc) from exc

    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()

    if content_type == "application/json":
        body_bytes = await request.body()
        try:
            payload = _JSON_SOURCE_ADAPTER.validate_json(body_bytes)
        except ValidationError as exc:
            raise RequestValidationError(exc.errors()) from exc
        if isinstance(payload, PasteSourcePayload):
            try:
                return service.add_text_source(
                    context,
                    room_id=room_id,
                    import_id=import_id,
                    source_kind="paste",
                    text=payload.text,
                    filename=payload.filename,
                    media_type=payload.media_type,
                )
            except Exception as exc:
                raise _map_adventure_import_error(exc) from exc
        elif isinstance(payload, UrlSourcePayload):
            try:
                return service.add_url_source(
                    context,
                    room_id=room_id,
                    import_id=import_id,
                    url=payload.url,
                    text=payload.text,
                    excerpt=payload.excerpt,
                    title=payload.title,
                )
            except Exception as exc:
                raise _map_adventure_import_error(exc) from exc

    # Raw-body document upload
    if source_kind not in RAW_SOURCE_MIME_TYPES:
        raise APIError(
            400,
            "asset_media_type_not_supported",
            f"Unsupported raw source_kind: '{source_kind}'",
        )
    if not filename or not filename.strip():
        raise APIError(
            400,
            "adventure_import_invalid",
            "Query parameter 'filename' is required for raw upload",
        )
    expected_mime = RAW_SOURCE_MIME_TYPES[source_kind]
    if content_type != expected_mime:
        raise APIError(
            400,
            "asset_media_type_not_supported",
            f"Content-Type '{content_type}' does not match expected '{expected_mime}' for source_kind '{source_kind}'",
        )

    data = await request.body()
    try:
        asset = room_asset_service.create(
            context,
            room_id=room_id,
            kind="source_document",
            filename=filename.strip(),
            mime_type=content_type,
            data=data,
            visibility="dm_only",
        )
    except Exception as exc:
        raise _map_adventure_import_error(exc) from exc

    try:
        return service.add_asset_source(
            context,
            room_id=room_id,
            import_id=import_id,
            asset_id=asset.id,
        )
    except Exception as exc:
        try:
            room_asset_service.delete(context, room_id=room_id, asset_id=asset.id)
        except (
            RoomAssetNotFoundError,
            RoomAssetForbiddenError,
            RoomAssetInUseError,
            OSError,
        ) as cleanup_exc:
            # The original error is still raised below; this line is the only
            # trace of the orphaned source_document asset left in the Room.
            logger.warning(
                "adventure import source cleanup failed for room=%s import_id=%s asset_id=%s: %s",
                room_id,
                import_id,
                asset.id,
                cleanup_exc,
            )
        raise _map_adventure_import_error(exc) from exc


@router.get("/{import_id}/sources", response_model=list[AdventureImportSource])
def list_sources(
    room_id: UUID,
    import_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: AdventureImportService = Depends(get_adventure_import_service),
) -> list[AdventureImportSource]:
    try:
        return list(service.list_sources(context, room_id=room_id, import_id=import_id))
    except Exception as exc:
        raise _map_adventure_import_error(exc) from exc


@router.post("/{import_id}/sources/from-asset", response_model=AdventureImportSource)
def add_source_from_asset(
    room_id: UUID,
    import_id: UUID,
    payload: AddSourceFromAssetRequest,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: AdventureImportService = Depends(get_adventure_import_service),
) -> AdventureImportSource:
    try:
        return service.add_asset_source(
            context,
            room_id=room_id,
            import_id=import_id,
            asset_id=payload.asset_id,
        )
    except Exception as exc:
        raise _map_adventure_import_error(exc) from exc


@router.get("/{import_id}/sources/{source_id}/chunk", response_model=SourceChunk)
def read_source_chunk(
    room_id: UUID,
    import_id: UUID,
    source_id: UUID,
    offset: int = Query(default=0),
    limit: int | None = Query(default=None),
    context: RoomAccessContext = Depends(get_room_access_context),
    service: AdventureImportService = Depends(get_adventure_import_service),
) -> SourceChunk:
    try:
        return service.read_source_chunk(
            context,
            room_id=room_id,
            import_id=import_id,
            source_id=source_id,
            offset=offset,
            limit=limit,
        )
    except Exception as exc:
        raise _map_adventure_import_error(exc) from exc


@router.get("/{import_id}/draft", response_model=AdventureImportDraft)
def get_draft(
    room_id: UUID,
    import_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: AdventureImportService = Depends(get_adventure_import_service),
) -> AdventureImportDraft:
    try:
        return service.get_draft(context, room_id=room_id, import_id=import_id)
    except Exception as exc:
        raise _map_adventure_import_error(exc) from exc


@router.put("/{import_id}/draft", response_model=AdventureImportDraft)
def update_draft(
    room_id: UUID,
    import_id: UUID,
    payload: UpdateImportDraftRequest,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: AdventureImportService = Depends(get_adventure_import_service),
) -> AdventureImportDraft:
    try:
        return service.update_draft(
            context,
            room_id=room_id,
            import_id=import_id,
            draft=payload.draft,
            warnings=payload.warnings,
            expected_revision=payload.expected_revision,
        )
    except Exception as exc:
        raise _map_adventure_import_error(exc) from exc


@router.post(
    "/{import_id}/draft/entries/{entry_id}/review",
    response_model=AdventureImportDraft,
)
def set_entry_review(
    room_id: UUID,
    import_id: UUID,
    entry_id: str,
    payload: SetEntryReviewRequest,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: AdventureImportService = Depends(get_adventure_import_service),
) -> AdventureImportDraft:
    try:
        return service.set_entry_review(
            context,
            room_id=room_id,
            import_id=import_id,
            entry_id=entry_id,
            review_status=payload.review_status,
            expected_revision=payload.expected_revision,
        )
    except Exception as exc:
        raise _map_adventure_import_error(exc) from exc


@router.post(
    "/{import_id}/warnings/{warning_id}/resolve",
    response_model=AdventureImportDraft,
)
def resolve_warning(
    room_id: UUID,
    import_id: UUID,
    warning_id: str,
    payload: ResolveWarningRequest,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: AdventureImportService = Depends(get_adventure_import_service),
) -> AdventureImportDraft:
    try:
        return service.resolve_import_warning(
            context,
            room_id=room_id,
            import_id=import_id,
            warning_id=warning_id,
            resolution=payload.resolution,
            expected_revision=payload.expected_revision,
        )
    except Exception as exc:
        raise _map_adventure_import_error(exc) from exc


@router.post(
    "/{import_id}/questions/{question_id}/answer",
    response_model=AdventureImportDraft,
)
def answer_question(
    room_id: UUID,
    import_id: UUID,
    question_id: str,
    payload: AnswerQuestionRequest,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: AdventureImportService = Depends(get_adventure_import_service),
) -> AdventureImportDraft:
    try:
        return service.answer_import_question(
            context,
            room_id=room_id,
            import_id=import_id,
            question_id=question_id,
            answer=payload.answer,
            expected_revision=payload.expected_revision,
        )
    except Exception as exc:
        raise _map_adventure_import_error(exc) from exc


@router.post("/{import_id}/finalize", response_model=AdventureDefinition)
def finalize_adventure(
    room_id: UUID,
    import_id: UUID,
    payload: FinalizeAdventureImportRequest,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: AdventureImportService = Depends(get_adventure_import_service),
) -> AdventureDefinition:
    try:
        return service.finalize_adventure(
            context,
            room_id=room_id,
            import_id=import_id,
            name=payload.name,
            summary=payload.summary,
            expected_revision=payload.expected_revision,
        )
    except Exception as exc:
        raise _map_adventure_import_error(exc) from exc


__all__ = ["router"]
