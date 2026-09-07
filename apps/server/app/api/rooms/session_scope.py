from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.engine import Connection, Engine

from app.api.errors import APIError
from app.domain.rooms.schemas import RoomAccessContext
from app.domain.rooms.workspace import RoomCharacterWorkspaceService, RoomWorkspaceScopeError
from app.persistence.characters import characters
from app.persistence.rooms.session_live import SessionLiveRepository
from app.persistence.rooms.tables import campaign_seats
from app.persistence.rooms.workspace import RoomWorkspaceRepository
from app.persistence.transaction_bound import TransactionBoundEngine


def _bound_workspace_service(
    service: RoomCharacterWorkspaceService,
    connection: Connection,
) -> tuple[Engine, RoomCharacterWorkspaceService]:
    bound_engine = cast(Engine, TransactionBoundEngine(connection))
    return (
        bound_engine,
        RoomCharacterWorkspaceService(
            bound_engine,
            service.registry,
            workspace_repository=RoomWorkspaceRepository(bound_engine),
        ),
    )


def _lock_room_character(
    service: RoomCharacterWorkspaceService,
    connection: Connection,
    *,
    room_id: UUID,
    character_id: UUID,
) -> None:
    existing_room = service.workspace_repository.character_room_id_in_transaction(
        connection,
        character_id,
    )
    if existing_room != room_id:
        raise RoomWorkspaceScopeError(
            f"character {character_id} is not in Room {room_id}"
        )
    locked_id = connection.scalar(
        select(characters.c.id)
        .where(characters.c.id == character_id)
        .with_for_update()
    )
    if locked_id is None:
        raise RoomWorkspaceScopeError(
            f"character {character_id} is not in Room {room_id}"
        )


def _lock_current_participant_seat(
    repository: SessionLiveRepository,
    connection: Connection,
    *,
    character_id: UUID,
) -> None:
    control = repository.control_for_character(character_id)
    if control is None:
        return
    connection.execute(
        select(campaign_seats.c.id)
        .where(campaign_seats.c.id == control.seat_id)
        .with_for_update()
    ).one_or_none()


def _lock_selected_character_seats(
    connection: Connection,
    *,
    character_id: UUID,
) -> None:
    connection.execute(
        select(campaign_seats.c.id)
        .where(campaign_seats.c.selected_character_id == character_id)
        .with_for_update()
    ).all()


def require_live_character_write(
    repository: SessionLiveRepository,
    *,
    context: RoomAccessContext,
    character_id: UUID,
) -> None:
    control = repository.control_for_character(character_id)
    if control is None:
        return
    if control.dm_controller_access_session_id == context.access_session_id:
        return
    if (
        control.player_controller_kind == "human"
        and control.player_controller_access_session_id == context.access_session_id
    ):
        return
    raise APIError(
        409,
        "character_in_active_session",
        "Character is controlled by another participant in an active Session",
    )


def require_character_unleased(
    repository: SessionLiveRepository,
    *,
    character_id: UUID,
) -> None:
    if repository.control_for_character(character_id) is None:
        return
    raise APIError(
        409,
        "character_in_active_session",
        "Character cannot be archived while it is in an active Session",
    )


@contextmanager
def live_character_write_scope(
    service: RoomCharacterWorkspaceService,
    *,
    context: RoomAccessContext,
    character_id: UUID,
) -> Iterator[RoomCharacterWorkspaceService]:
    """Serialize Session/controller changes with one authorized Character write.

    Start/Late Join lock Seat then Character while acquiring a lease. If a lease
    already exists we lock that participant Seat first, then the Character, and
    re-read the current controller after both locks. If no lease exists, the
    Character lock prevents a concurrent Start/Late Join from acquiring one
    until this bound Character/Builder write has committed.
    """

    with service.engine.begin() as connection:
        bound_engine, bound_service = _bound_workspace_service(service, connection)
        live_repository = SessionLiveRepository(bound_engine)
        _lock_current_participant_seat(
            live_repository,
            connection,
            character_id=character_id,
        )
        _lock_room_character(
            service,
            connection,
            room_id=context.room_id,
            character_id=character_id,
        )
        require_live_character_write(
            live_repository,
            context=context,
            character_id=character_id,
        )
        yield bound_service


@contextmanager
def live_draft_write_scope(
    service: RoomCharacterWorkspaceService,
    *,
    context: RoomAccessContext,
    draft_id: UUID,
) -> Iterator[RoomCharacterWorkspaceService]:
    """Apply the same live authorization to an existing versioned Builder draft."""

    with service.engine.begin() as connection:
        bound_engine, bound_service = _bound_workspace_service(service, connection)
        view = bound_service.get_draft(context.room_id, draft_id)
        character_id = view.draft.character_id
        if character_id is not None:
            live_repository = SessionLiveRepository(bound_engine)
            _lock_current_participant_seat(
                live_repository,
                connection,
                character_id=character_id,
            )
            _lock_room_character(
                service,
                connection,
                room_id=context.room_id,
                character_id=character_id,
            )
            require_live_character_write(
                live_repository,
                context=context,
                character_id=character_id,
            )
        yield bound_service


@contextmanager
def unleased_character_write_scope(
    service: RoomCharacterWorkspaceService,
    *,
    context: RoomAccessContext,
    character_id: UUID,
) -> Iterator[RoomCharacterWorkspaceService]:
    """Serialize archive with Seat selection/Start and reject an existing lease."""

    with service.engine.begin() as connection:
        _lock_selected_character_seats(connection, character_id=character_id)
        _lock_room_character(
            service,
            connection,
            room_id=context.room_id,
            character_id=character_id,
        )
        bound_engine, bound_service = _bound_workspace_service(service, connection)
        require_character_unleased(
            SessionLiveRepository(bound_engine),
            character_id=character_id,
        )
        yield bound_service


__all__ = [
    "live_character_write_scope",
    "live_draft_write_scope",
    "require_character_unleased",
    "require_live_character_write",
    "unleased_character_write_scope",
]
