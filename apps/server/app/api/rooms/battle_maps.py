from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.api.errors import APIError
from app.api.rooms.access import get_room_access_context
from app.api.rooms.dependencies import get_battle_map_service
from app.domain.battle_maps.schemas import (
    BattleMap,
    BattleMapAssetInvalidError,
    BattleMapCreate,
    BattleMapForbiddenError,
    BattleMapInvalidError,
    BattleMapNotFoundError,
    BattleMapObjectsReplace,
    BattleMapPatch,
    BattleMapRevisionConflictError,
    BattleMapShrinkConflictError,
    BattleMapSummary,
)
from app.domain.battle_maps.service import BattleMapService
from app.domain.rooms.schemas import RoomAccessContext

router = APIRouter(prefix="/api/rooms/{room_id}/battle-maps", tags=["room-battle-maps"])


def _map_battle_map_error(exc: Exception) -> APIError:
    if isinstance(exc, (BattleMapNotFoundError, BattleMapForbiddenError)):
        return APIError(404, "battle_map_not_found", str(exc))
    if isinstance(
        exc, (BattleMapRevisionConflictError, BattleMapShrinkConflictError)
    ):
        return APIError(409, "battle_map_revision_conflict", str(exc))
    if isinstance(exc, BattleMapInvalidError):
        return APIError(400, "battle_map_invalid", str(exc))
    if isinstance(exc, BattleMapAssetInvalidError):
        return APIError(400, "battle_map_asset_invalid", str(exc))
    raise exc


@router.post("", response_model=BattleMap, status_code=status.HTTP_201_CREATED)
def create_battle_map(
    room_id: UUID,
    payload: BattleMapCreate,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: BattleMapService = Depends(get_battle_map_service),
) -> BattleMap:
    try:
        return service.create(context, room_id=room_id, payload=payload)
    except Exception as exc:
        raise _map_battle_map_error(exc) from exc


@router.get("", response_model=list[BattleMapSummary])
def list_battle_maps(
    room_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: BattleMapService = Depends(get_battle_map_service),
) -> list[BattleMapSummary]:
    try:
        return service.list(context, room_id)
    except Exception as exc:
        raise _map_battle_map_error(exc) from exc


@router.get("/{map_id}", response_model=BattleMap)
def get_battle_map(
    room_id: UUID,
    map_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: BattleMapService = Depends(get_battle_map_service),
) -> BattleMap:
    try:
        return service.get(context, room_id, map_id)
    except Exception as exc:
        raise _map_battle_map_error(exc) from exc


@router.patch("/{map_id}", response_model=BattleMap)
def patch_battle_map(
    room_id: UUID,
    map_id: UUID,
    payload: BattleMapPatch,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: BattleMapService = Depends(get_battle_map_service),
) -> BattleMap:
    try:
        return service.patch(context, room_id=room_id, map_id=map_id, payload=payload)
    except Exception as exc:
        raise _map_battle_map_error(exc) from exc


@router.put("/{map_id}/objects", response_model=BattleMap)
def replace_battle_map_objects(
    room_id: UUID,
    map_id: UUID,
    payload: BattleMapObjectsReplace,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: BattleMapService = Depends(get_battle_map_service),
) -> BattleMap:
    try:
        return service.replace_objects(
            context, room_id=room_id, map_id=map_id, payload=payload
        )
    except Exception as exc:
        raise _map_battle_map_error(exc) from exc


@router.delete("/{map_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_battle_map(
    room_id: UUID,
    map_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: BattleMapService = Depends(get_battle_map_service),
) -> Response:
    try:
        service.delete(context, room_id, map_id)
    except Exception as exc:
        raise _map_battle_map_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
