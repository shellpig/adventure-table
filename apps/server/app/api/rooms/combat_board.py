"""P5-A Combat board runtime routes: tactical start, placement, doors, board read/image."""

from __future__ import annotations

from typing import BinaryIO
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends
from starlette.responses import StreamingResponse

from app.api.rooms.access import RoomAccessContext, get_room_access_context
from app.api.rooms.combat import _actor_from_request, _map_combat_error
from app.api.rooms.dependencies import (
    get_combat_board_service,
    get_combat_service,
    get_table_event_service,
)
from app.domain.combat.board import (
    BoardDoorView,
    BoardPositionView,
    CombatBoardService,
    CombatBoardView,
    PlaceCombatantInput,
    UpdateDoorStateInput,
)
from app.domain.combat.lifecycle import CombatService, CombatView, StartTacticalCombatInput
from app.domain.rooms.table_events import TableEventService

router = APIRouter(
    prefix=(
        "/api/rooms/{room_id}/campaigns/{campaign_id}"
        "/sessions/{session_id}/combat"
    ),
    tags=["room-combat"],
)


@router.post("/tactical-start", response_model=CombatView)
def start_tactical_combat(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    payload: StartTacticalCombatInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: CombatService = Depends(get_combat_service),
) -> CombatView:
    try:
        return service.start_tactical_combat(
            _actor_from_request(room_id, campaign_id, session_id, context, event_service),
            payload,
        )
    except Exception as exc:
        raise _map_combat_error(exc) from exc


@router.get("/board", response_model=CombatBoardView)
def get_combat_board(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: CombatBoardService = Depends(get_combat_board_service),
) -> CombatBoardView:
    try:
        return service.get_board(
            _actor_from_request(room_id, campaign_id, session_id, context, event_service)
        )
    except Exception as exc:
        raise _map_combat_error(exc) from exc


@router.put("/board/positions/{entry_id}", response_model=BoardPositionView)
def place_combatant(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    entry_id: UUID,
    payload: PlaceCombatantInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: CombatBoardService = Depends(get_combat_board_service),
) -> BoardPositionView:
    try:
        return service.place_combatant(
            _actor_from_request(room_id, campaign_id, session_id, context, event_service),
            entry_id,
            payload,
        )
    except Exception as exc:
        raise _map_combat_error(exc) from exc


@router.patch("/board/doors/{door_id}", response_model=BoardDoorView)
def update_door_state(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    door_id: UUID,
    payload: UpdateDoorStateInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: CombatBoardService = Depends(get_combat_board_service),
) -> BoardDoorView:
    try:
        return service.update_door_state(
            _actor_from_request(room_id, campaign_id, session_id, context, event_service),
            door_id,
            payload,
        )
    except Exception as exc:
        raise _map_combat_error(exc) from exc


def _content_disposition(filename: str) -> str:
    # RFC 6266 / 5987: ASCII fallback in `filename`, full UTF-8 name in `filename*`.
    ascii_name = filename.encode("ascii", "ignore").decode().replace('"', "").replace("\\", "") or "board"
    encoded = quote(filename)
    return f'inline; filename="{ascii_name}"; filename*=UTF-8\'\'{encoded}'


def _stream_file(handle: BinaryIO, chunk_size: int = 65536):
    try:
        while chunk := handle.read(chunk_size):
            yield chunk
    finally:
        handle.close()


@router.get("/board/image")
def get_combat_board_image(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: CombatBoardService = Depends(get_combat_board_service),
) -> StreamingResponse:
    try:
        mime_type, filename, handle = service.open_board_image(
            _actor_from_request(room_id, campaign_id, session_id, context, event_service)
        )
    except Exception as exc:
        raise _map_combat_error(exc) from exc
    return StreamingResponse(
        _stream_file(handle),
        media_type=mime_type,
        headers={"Content-Disposition": _content_disposition(filename)},
    )
