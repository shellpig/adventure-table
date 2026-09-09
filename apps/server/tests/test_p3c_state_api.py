from uuid import uuid4

from app.api.rooms import router as rooms_router
from app.api.rooms.p3c_state import _map_table_state_error
from app.domain.character.validation import CharacterValidationError
from app.domain.rooms.table_events import TableEventActorUnauthorizedError
from app.persistence.characters import StateWriteConflictError, StaleBuildVersionError
from app.persistence.rooms.p3c_character_state import (
    TableCharacterStateSubjectStalePersistenceError,
)


def test_table_state_route_is_registered_as_session_scoped_patch() -> None:
    matches = [
        route
        for route in rooms_router.routes
        if getattr(route, "path", "").endswith("/sessions/{session_id}/character-state/{subject_seat_id}")
    ]
    assert len(matches) == 1
    assert matches[0].methods == {"PATCH"}


def test_table_state_errors_map_to_stable_p3c_codes() -> None:
    unauthorized = _map_table_state_error(TableEventActorUnauthorizedError("nope"))
    assert unauthorized.status_code == 403
    assert unauthorized.code == "table_actor_unauthorized"

    stale_subject = _map_table_state_error(
        TableCharacterStateSubjectStalePersistenceError("stale")
    )
    assert stale_subject.status_code == 409
    assert stale_subject.code == "table_state_subject_stale"

    stale_build = _map_table_state_error(
        StaleBuildVersionError(uuid4(), uuid4(), uuid4())
    )
    assert stale_build.status_code == 409
    assert stale_build.code == "stale_build_version"

    conflict = _map_table_state_error(StateWriteConflictError(uuid4(), 3))
    assert conflict.status_code == 409
    assert conflict.code == "state_write_conflict"

    invalid = _map_table_state_error(CharacterValidationError("bad state"))
    assert invalid.status_code == 422
    assert invalid.code == "invalid_character_state"
