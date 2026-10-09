from __future__ import annotations

from urllib.parse import unquote
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.errors import APIError
from app.api.rooms.access import get_room_access_context
from app.api.rooms.dependencies import get_monster_library_service
from app.domain.monster_library.errors import (
    InvalidMonsterLibraryFilterError,
    InvalidMonsterRulesError,
    InvalidMonsterTemplateRefError,
    MonsterLibraryForbiddenError,
    MonsterTemplateArchivedError,
    MonsterTemplateNotFoundError,
    MonsterTemplateReadOnlyError,
    MonsterTemplateReferencedError,
    MonsterTemplateRevisionConflictError,
)
from app.domain.monster_library.schemas import (
    ArchiveCustomMonsterInput,
    CopyCustomMonsterInput,
    CreateCustomMonsterFromContentInput,
    CreateCustomMonsterFromInstanceInput,
    CreateCustomMonsterInput,
    MonsterLibraryDetailView,
    MonsterLibrarySummaryView,
    PatchCustomMonsterInput,
)
from app.domain.monster_library.service import MonsterLibraryService
from app.domain.rooms.schemas import RoomAccessContext

router = APIRouter(
    prefix="/api/rooms/{room_id}/monster-library",
    tags=["room-monster-library"],
)


def _map_library_error(exc: Exception) -> APIError:
    if isinstance(exc, MonsterTemplateNotFoundError):
        return APIError(404, "monster_template_not_found", str(exc))
    if isinstance(exc, MonsterLibraryForbiddenError):
        return APIError(403, "monster_library_forbidden", str(exc))
    if isinstance(exc, MonsterTemplateReadOnlyError):
        return APIError(403, "monster_template_read_only", str(exc))
    if isinstance(exc, MonsterTemplateRevisionConflictError):
        return APIError(409, "monster_template_revision_conflict", str(exc))
    if isinstance(exc, MonsterTemplateReferencedError):
        return APIError(409, "monster_template_referenced", str(exc))
    if isinstance(exc, MonsterTemplateArchivedError):
        return APIError(409, "monster_template_archived", str(exc))
    if isinstance(exc, InvalidMonsterLibraryFilterError):
        return APIError(422, "invalid_monster_library_filter", str(exc))
    if isinstance(exc, (InvalidMonsterTemplateRefError, InvalidMonsterRulesError, ValueError)):
        return APIError(422, "invalid_monster_template_ref", str(exc))
    raise exc


@router.get("", response_model=list[MonsterLibrarySummaryView])
def list_monster_library(
    room_id: UUID,
    query: str | None = Query(default=None),
    include_archived: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    source: str = Query(default="all"),
    sort: str = Query(default="name"),
    order: str = Query(default="asc"),
    size: str | None = Query(default=None),
    monster_type: str | None = Query(default=None, alias="type"),
    cr_eq: float | None = Query(default=None),
    cr_min: float | None = Query(default=None),
    cr_max: float | None = Query(default=None),
    context: RoomAccessContext = Depends(get_room_access_context),
    service: MonsterLibraryService = Depends(get_monster_library_service),
) -> list[MonsterLibrarySummaryView]:
    try:
        return service.list(
            context,
            room_id=room_id,
            query=query,
            include_archived=include_archived,
            limit=limit,
            offset=offset,
            source=source,
            sort=sort,
            order=order,
            size=size,
            monster_type=monster_type,
            cr_eq=cr_eq,
            cr_min=cr_min,
            cr_max=cr_max,
        )
    except Exception as exc:
        raise _map_library_error(exc) from exc


@router.post("/custom", response_model=MonsterLibraryDetailView, status_code=status.HTTP_201_CREATED)
def create_custom_monster(
    room_id: UUID,
    payload: CreateCustomMonsterInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: MonsterLibraryService = Depends(get_monster_library_service),
) -> MonsterLibraryDetailView:
    try:
        return service.create_custom(context, room_id=room_id, payload=payload)
    except Exception as exc:
        raise _map_library_error(exc) from exc


@router.post("/custom/from-content", response_model=MonsterLibraryDetailView, status_code=status.HTTP_201_CREATED)
def create_custom_monster_from_content(
    room_id: UUID,
    payload: CreateCustomMonsterFromContentInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: MonsterLibraryService = Depends(get_monster_library_service),
) -> MonsterLibraryDetailView:
    try:
        return service.create_from_content(context, room_id=room_id, payload=payload)
    except Exception as exc:
        raise _map_library_error(exc) from exc


@router.post("/custom/from-instance", response_model=MonsterLibraryDetailView, status_code=status.HTTP_201_CREATED)
def create_custom_monster_from_instance(
    room_id: UUID,
    payload: CreateCustomMonsterFromInstanceInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: MonsterLibraryService = Depends(get_monster_library_service),
) -> MonsterLibraryDetailView:
    try:
        return service.create_from_instance(context, room_id=room_id, payload=payload)
    except Exception as exc:
        raise _map_library_error(exc) from exc


@router.post("/custom/{template_id}/copy", response_model=MonsterLibraryDetailView, status_code=status.HTTP_201_CREATED)
def copy_custom_monster(
    room_id: UUID,
    template_id: str,
    payload: CopyCustomMonsterInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: MonsterLibraryService = Depends(get_monster_library_service),
) -> MonsterLibraryDetailView:
    try:
        return service.copy_custom(context, room_id=room_id, template_id=template_id, payload=payload)
    except Exception as exc:
        raise _map_library_error(exc) from exc


@router.patch("/custom/{template_id}", response_model=MonsterLibraryDetailView)
def patch_custom_monster(
    room_id: UUID,
    template_id: str,
    payload: PatchCustomMonsterInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: MonsterLibraryService = Depends(get_monster_library_service),
) -> MonsterLibraryDetailView:
    try:
        return service.patch_custom(context, room_id=room_id, template_id=template_id, payload=payload)
    except Exception as exc:
        raise _map_library_error(exc) from exc


@router.post("/custom/{template_id}/archive", response_model=MonsterLibraryDetailView)
def archive_custom_monster(
    room_id: UUID,
    template_id: str,
    payload: ArchiveCustomMonsterInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: MonsterLibraryService = Depends(get_monster_library_service),
) -> MonsterLibraryDetailView:
    try:
        return service.archive_custom(context, room_id=room_id, template_id=template_id, payload=payload)
    except Exception as exc:
        raise _map_library_error(exc) from exc


@router.delete("/custom/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_custom_monster(
    room_id: UUID,
    template_id: str,
    expected_revision: int = Query(..., gt=0),
    context: RoomAccessContext = Depends(get_room_access_context),
    service: MonsterLibraryService = Depends(get_monster_library_service),
) -> Response:
    try:
        service.delete_custom(
            context,
            room_id=room_id,
            template_id=template_id,
            expected_revision=expected_revision,
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as exc:
        raise _map_library_error(exc) from exc


@router.get("/{ref:path}", response_model=MonsterLibraryDetailView)
def get_monster_library_entry(
    room_id: UUID,
    ref: str,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: MonsterLibraryService = Depends(get_monster_library_service),
) -> MonsterLibraryDetailView:
    try:
        decoded_ref = unquote(ref)
        return service.get(context, room_id=room_id, ref=decoded_ref)
    except Exception as exc:
        raise _map_library_error(exc) from exc
