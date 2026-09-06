from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from app.api.dependencies import get_database_engine
from app.api.errors import APIError
from app.domain.rooms.access import FixedWindowThrottle
from app.domain.rooms.schemas import (
    CreateRoomRequest,
    EnterRoomRequest,
    HeartbeatResponse,
    Room,
    RoomAccessContext,
    RoomAccessGrant,
)
from app.domain.rooms.service import (
    RoomAccessDeniedError,
    RoomAccessRevokedError,
    RoomAccessThrottledError,
    RoomNotFoundError,
    RoomScopeMismatchError,
    RoomService,
)
from app.persistence.rooms.repository import RoomRepository


router = APIRouter(prefix="/api/rooms", tags=["rooms"])


def get_room_service(request: Request) -> RoomService:
    override = getattr(request.app.state, "room_service", None)
    if override is not None:
        return override
    throttle = getattr(request.app.state, "room_access_throttle", None)
    if throttle is None:
        throttle = FixedWindowThrottle()
        request.app.state.room_access_throttle = throttle
    return RoomService(
        RoomRepository(get_database_engine(request)),
        throttle=throttle,
    )


def _remote_addr(request: Request) -> str:
    if request.client is None or not request.client.host:
        return "unknown"
    return request.client.host


def _map_room_error(exc: Exception) -> APIError:
    if isinstance(exc, RoomNotFoundError):
        return APIError(404, "room_not_found", "room not found")
    if isinstance(exc, RoomAccessThrottledError):
        return APIError(
            429,
            "room_access_throttled",
            "too many failed Room access attempts; try again later",
        )
    if isinstance(exc, RoomAccessRevokedError):
        return APIError(401, "room_access_revoked", "Room access has been revoked")
    if isinstance(exc, RoomScopeMismatchError):
        return APIError(403, "room_scope_mismatch", "Room access token belongs to another Room")
    if isinstance(exc, RoomAccessDeniedError):
        return APIError(403, "room_access_denied", "Room credentials were rejected")
    raise exc


def _bearer_token(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise APIError(401, "room_access_required", "Room access token is required")
    return token.strip()


def get_room_access_context(
    room_id: UUID,
    request: Request,
    service: RoomService = Depends(get_room_service),
) -> RoomAccessContext:
    token = _bearer_token(request)
    try:
        return service.authenticate(room_id, token)
    except Exception as exc:
        raise _map_room_error(exc) from exc


@router.post("", response_model=RoomAccessGrant, status_code=status.HTTP_201_CREATED)
def create_room(
    payload: CreateRoomRequest,
    service: RoomService = Depends(get_room_service),
) -> RoomAccessGrant:
    return service.create_room(payload)


@router.post("/enter", response_model=RoomAccessGrant, status_code=status.HTTP_201_CREATED)
def enter_room(
    payload: EnterRoomRequest,
    request: Request,
    service: RoomService = Depends(get_room_service),
) -> RoomAccessGrant:
    try:
        return service.enter_room(payload, remote_addr=_remote_addr(request))
    except Exception as exc:
        raise _map_room_error(exc) from exc


@router.get("/{room_id}", response_model=Room)
def get_room(
    context: RoomAccessContext = Depends(get_room_access_context),
    service: RoomService = Depends(get_room_service),
) -> Room:
    try:
        return service.room_for_context(context)
    except Exception as exc:
        raise _map_room_error(exc) from exc


@router.post("/{room_id}/access/heartbeat", response_model=HeartbeatResponse)
def heartbeat(
    context: RoomAccessContext = Depends(get_room_access_context),
    service: RoomService = Depends(get_room_service),
) -> HeartbeatResponse:
    try:
        return HeartbeatResponse(server_time=service.heartbeat(context))
    except Exception as exc:
        raise _map_room_error(exc) from exc


__all__ = ["get_room_access_context", "get_room_service", "router"]
