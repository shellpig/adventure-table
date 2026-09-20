from __future__ import annotations

from typing import BinaryIO
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from starlette.responses import StreamingResponse

from app.api.errors import APIError
from app.api.rooms.access import get_room_access_context
from app.api.rooms.dependencies import get_room_asset_service
from app.domain.room_assets.schemas import (
    RoomAsset,
    RoomAssetEmptyError,
    RoomAssetForbiddenError,
    RoomAssetInUseError,
    RoomAssetKind,
    RoomAssetNotFoundError,
    RoomAssetTooLargeError,
    RoomAssetUnsupportedMediaTypeError,
    RoomAssetVisibility,
    RoomAssetVisibilityNotAllowedError,
)
from app.domain.room_assets.service import RoomAssetService
from app.domain.rooms.schemas import RoomAccessContext

router = APIRouter(prefix="/api/rooms/{room_id}/assets", tags=["room-assets"])


def _map_room_asset_error(exc: Exception) -> APIError:
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
    raise exc


@router.post("", response_model=RoomAsset, status_code=status.HTTP_201_CREATED)
async def upload_asset(
    room_id: UUID,
    request: Request,
    kind: RoomAssetKind = Query(...),
    filename: str = Query(..., min_length=1, max_length=255),
    visibility: RoomAssetVisibility = Query(default="room"),
    context: RoomAccessContext = Depends(get_room_access_context),
    service: RoomAssetService = Depends(get_room_asset_service),
) -> RoomAsset:
    data = await request.body()
    content_type = request.headers.get("content-type", "").split(";")[0].strip()
    try:
        return service.create(
            context,
            room_id=room_id,
            kind=kind,
            filename=filename,
            mime_type=content_type,
            data=data,
            visibility=visibility,
        )
    except Exception as exc:
        raise _map_room_asset_error(exc) from exc


@router.get("", response_model=list[RoomAsset])
def list_assets(
    room_id: UUID,
    kind: RoomAssetKind | None = Query(default=None),
    context: RoomAccessContext = Depends(get_room_access_context),
    service: RoomAssetService = Depends(get_room_asset_service),
) -> list[RoomAsset]:
    try:
        return service.list(context, room_id=room_id, kind=kind)
    except Exception as exc:
        raise _map_room_asset_error(exc) from exc


@router.get("/{asset_id}", response_model=RoomAsset)
def get_asset(
    room_id: UUID,
    asset_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: RoomAssetService = Depends(get_room_asset_service),
) -> RoomAsset:
    try:
        return service.get(context, room_id=room_id, asset_id=asset_id)
    except Exception as exc:
        raise _map_room_asset_error(exc) from exc


def _content_disposition(filename: str) -> str:
    # RFC 6266 / 5987: ASCII fallback in `filename`, full UTF-8 name in `filename*`.
    ascii_name = filename.encode("ascii", "ignore").decode().replace('"', "").replace("\\", "") or "asset"
    encoded = quote(filename)
    return f"inline; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded}"


def _stream_file(handle: BinaryIO, chunk_size: int = 65536):
    try:
        while chunk := handle.read(chunk_size):
            yield chunk
    finally:
        handle.close()


@router.get("/{asset_id}/content")
def get_asset_content(
    room_id: UUID,
    asset_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: RoomAssetService = Depends(get_room_asset_service),
) -> StreamingResponse:
    try:
        asset, handle = service.open_content(context, room_id=room_id, asset_id=asset_id)
    except Exception as exc:
        raise _map_room_asset_error(exc) from exc

    return StreamingResponse(
        _stream_file(handle),
        media_type=asset.mime_type,
        headers={"Content-Disposition": _content_disposition(asset.original_filename)},
    )


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_asset(
    room_id: UUID,
    asset_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: RoomAssetService = Depends(get_room_asset_service),
) -> Response:
    try:
        service.delete(context, room_id=room_id, asset_id=asset_id)
    except Exception as exc:
        raise _map_room_asset_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
