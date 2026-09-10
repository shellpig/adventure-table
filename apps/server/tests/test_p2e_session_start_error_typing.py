from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.sessions import (
    DMControllerMismatchError,
    SessionLobbyUnavailableError,
    SessionService,
)
from app.persistence.rooms.sessions import (
    SessionStartControllerMismatchPersistenceError,
    SessionStartPersistenceError,
)


class _StartErrorRepository:
    def __init__(self, room_id: UUID, error: Exception) -> None:
        self.room_id = room_id
        self.error = error

    def campaign_room_id(self, _campaign_id: UUID) -> UUID:
        return self.room_id

    def start_from_lobby(self, **_kwargs):
        raise self.error


def _context(room_id: UUID) -> RoomAccessContext:
    return RoomAccessContext(
        room_id=room_id,
        access_session_id=uuid4(),
        authority=RoomAccessAuthority.DM,
    )


def test_start_controller_mapping_depends_on_exception_type_not_message_text() -> None:
    room_id = uuid4()
    campaign_id = uuid4()
    service = SessionService(
        _StartErrorRepository(
            room_id,
            SessionStartControllerMismatchPersistenceError(
                'completely rewritten persistence wording with no legacy markers'
            ),
        ),
        live_repository=object(),
        event_service=object(),
    )

    with pytest.raises(DMControllerMismatchError):
        service.start_session(room_id, campaign_id, _context(room_id))


def test_start_lobby_error_does_not_become_dm_mismatch_even_if_wording_mentions_caller() -> None:
    room_id = uuid4()
    campaign_id = uuid4()
    service = SessionService(
        _StartErrorRepository(
            room_id,
            SessionStartPersistenceError('Caller wording is irrelevant to the API contract'),
        ),
        live_repository=object(),
        event_service=object(),
    )

    with pytest.raises(SessionLobbyUnavailableError):
        service.start_session(room_id, campaign_id, _context(room_id))
