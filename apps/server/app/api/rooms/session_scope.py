from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.engine import Connection, Engine

from app.api.errors import APIError
from app.domain.rooms.schemas import RoomAccessContext
from app.domain.rooms.table_events import TableActorContext, TableActorKind
from app.domain.rooms.workspace import RoomCharacterWorkspaceService, RoomWorkspaceScopeError
from app.persistence.characters import characters
from app.persistence.rooms.session_live import ActiveCharacterControl, SessionLiveRepository
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


def _human_can_write_live_character(
    control: ActiveCharacterControl,
    *,
    access_session_id: UUID,
) -> bool:
    if (
        control.dm_controller_kind == "human"
        and control.dm_controller_access_session_id == access_session_id
    ):
        return True
    return (
        control.player_controller_kind == "human"
        and control.player_controller_access_session_id == access_session_id
    )


def _actor_can_write_live_character(
    control: ActiveCharacterControl,
    *,
    actor: TableActorContext,
) -> bool:
    if control.session_id != actor.session_id:
        return False
    if actor.actor_kind is TableActorKind.HUMAN:
        return (
            actor.access_session_id is not None
            and _human_can_write_live_character(
                control,
                access_session_id=actor.access_session_id,
            )
        )
    if actor.actor_kind is not TableActorKind.AI:
        return False
    if actor.ai_controller_grant_id is None or actor.grant_generation is None:
        return False
    if actor.is_current_dm and actor.role == "dm":
        return (
            control.dm_controller_kind == "ai"
            and control.dm_controller_ai_grant_id == actor.ai_controller_grant_id
            and control.dm_controller_generation == actor.grant_generation
        )
    return (
        actor.role == "player"
        and control.seat_id == actor.seat_id
        and control.player_controller_kind == "ai"
        and control.player_ai_controller_grant_id == actor.ai_controller_grant_id
        and control.player_controller_epoch == actor.grant_generation
    )


def _deny_live_character_write() -> None:
    raise APIError(
        409,
        "character_in_active_session",
        "Character is controlled by another participant in an active Session",
    )


def require_live_character_write(
    repository: SessionLiveRepository,
    *,
    context: RoomAccessContext,
    character_id: UUID,
) -> None:
    """Backward-compatible Human Web authorization using current bindings."""

    control = repository.control_for_character(character_id)
    if control is None:
        return
    if _human_can_write_live_character(
        control,
        access_session_id=context.access_session_id,
    ):
        return
    _deny_live_character_write()


def require_live_character_actor_write(
    repository: SessionLiveRepository,
    *,
    actor: TableActorContext,
    character_id: UUID,
) -> None:
    """P3 actor policy for Human or AI Session-scoped Character writes."""

    control = repository.control_for_character(character_id)
    if control is None or not _actor_can_write_live_character(control, actor=actor):
        _deny_live_character_write()


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
    """Serialize Session/controller changes with one authorized Human write."""

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
def live_character_actor_write_scope(
    service: RoomCharacterWorkspaceService,
    *,
    actor: TableActorContext,
    character_id: UUID,
) -> Iterator[RoomCharacterWorkspaceService]:
    """Serialize the same Character write path for a typed Human/AI actor."""

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
            room_id=actor.room_id,
            character_id=character_id,
        )
        require_live_character_actor_write(
            live_repository,
            actor=actor,
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
    "live_character_actor_write_scope",
    "live_character_write_scope",
    "live_draft_write_scope",
    "require_character_unleased",
    "require_live_character_actor_write",
    "require_live_character_write",
    "unleased_character_write_scope",
]
