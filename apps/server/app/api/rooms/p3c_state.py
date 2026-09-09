from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.errors import APIError
from app.api.rooms.access import get_room_access_context
from app.api.rooms.dependencies import (
    get_table_character_state_service,
    get_table_event_service,
)
from app.domain.character.schemas import CharacterState, PersistedCharacter
from app.domain.character.validation import CharacterValidationError
from app.domain.rooms.exploration import ExplorationSubjectNotFoundError
from app.domain.rooms.schemas import RoomAccessContext, StrictModel
from app.domain.rooms.table_character_state import (
    TableCharacterStatePatch,
    TableCharacterStateService,
)
from app.domain.rooms.table_events import (
    TableActorContext,
    TableEventActorUnauthorizedError,
    TableEventNotFoundError,
    TableEventService,
    TableEventSessionNotActiveError,
)
from app.persistence.characters import (
    CharacterArchivedError,
    CharacterNotFoundError,
    StateWriteConflictError,
    StaleBuildVersionError,
)
from app.persistence.rooms.p3c_character_state import (
    TableCharacterStateActorUnsupportedPersistenceError,
    TableCharacterStateSubjectStalePersistenceError,
)
from app.persistence.rooms.table_runtime import (
    TableEventActorBindingStalePersistenceError,
    TableEventSessionNotActivePersistenceError,
    TableEventSessionNotFoundPersistenceError,
)


router = APIRouter(
    prefix=(
        "/api/rooms/{room_id}/campaigns/{campaign_id}"
        "/sessions/{session_id}"
    ),
    tags=["room-character-state"],
)


class TableCharacterStateResponse(StrictModel):
    character_id: UUID
    current_version_id: UUID
    version_no: int
    state: CharacterState


def _response(character: PersistedCharacter) -> TableCharacterStateResponse:
    return TableCharacterStateResponse(
        character_id=character.id,
        current_version_id=character.current_version_id,
        version_no=character.version_no,
        state=character.state,
    )


def _map_table_state_error(exc: Exception) -> APIError:
    if isinstance(exc, (TableEventNotFoundError, TableEventSessionNotFoundPersistenceError)):
        return APIError(404, "session_not_found", "Session was not found for this table actor")
    if isinstance(
        exc,
        (
            TableEventActorUnauthorizedError,
            TableEventActorBindingStalePersistenceError,
            TableCharacterStateActorUnsupportedPersistenceError,
        ),
    ):
        return APIError(403, "table_actor_unauthorized", str(exc))
    if isinstance(exc, (TableEventSessionNotActiveError, TableEventSessionNotActivePersistenceError)):
        return APIError(409, "session_not_active", "Session is not active")
    if isinstance(exc, ExplorationSubjectNotFoundError):
        return APIError(404, "exploration_subject_not_found", "Player Seat is not active in this Session")
    if isinstance(exc, TableCharacterStateSubjectStalePersistenceError):
        return APIError(409, "table_state_subject_stale", "Player Seat or Active Character changed before commit")
    if isinstance(exc, CharacterNotFoundError):
        return APIError(404, "character_not_found", "Active Character was not found")
    if isinstance(exc, CharacterArchivedError):
        return APIError(409, "character_archived", "Active Character is archived")
    if isinstance(exc, StaleBuildVersionError):
        return APIError(409, "stale_build_version", str(exc))
    if isinstance(exc, StateWriteConflictError):
        return APIError(409, "state_write_conflict", str(exc))
    if isinstance(exc, CharacterValidationError):
        return APIError(422, "invalid_character_state", str(exc))
    raise exc


def _resolve_actor(
    *,
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    context: RoomAccessContext,
    event_service: TableEventService,
) -> TableActorContext:
    return event_service.resolve_human_actor(
        room_id=room_id,
        campaign_id=campaign_id,
        session_id=session_id,
        context=context,
    )


@router.patch(
    "/character-state/{subject_seat_id}",
    response_model=TableCharacterStateResponse,
)
def patch_table_character_state(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    subject_seat_id: UUID,
    request: TableCharacterStatePatch,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    state_service: TableCharacterStateService = Depends(get_table_character_state_service),
) -> TableCharacterStateResponse:
    try:
        actor = _resolve_actor(
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            context=context,
            event_service=event_service,
        )
        return _response(
            state_service.apply_patch(
                actor,
                subject_seat_id=subject_seat_id,
                patch=request,
            )
        )
    except Exception as exc:
        raise _map_table_state_error(exc) from exc


__all__ = [
    "TableCharacterStateResponse",
    "router",
]
