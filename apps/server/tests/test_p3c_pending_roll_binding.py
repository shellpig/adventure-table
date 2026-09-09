from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.domain.rooms.pending_actions import (
    PendingActionRollBindingError,
    validate_pending_roll_binding,
)


def _action(*, session_id=None, seat_id=None, character_id=None):
    return SimpleNamespace(
        session_id=session_id or uuid4(),
        subject_seat_id=seat_id or uuid4(),
        subject_character_id=character_id or uuid4(),
    )


def _request(action, **overrides):
    values = {
        "session_id": action.session_id,
        "target_seat_id": action.subject_seat_id,
        "target_character_id": action.subject_character_id,
        "status": "pending",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_waiting_for_roll_accepts_same_pending_subject_request() -> None:
    action = _action()
    validate_pending_roll_binding(action, _request(action))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("override", "code"),
    [
        ({"session_id": uuid4()}, "roll_request_session_mismatch"),
        ({"target_seat_id": uuid4()}, "roll_request_subject_mismatch"),
        ({"target_character_id": uuid4()}, "roll_request_character_mismatch"),
        ({"status": "resolved"}, "roll_request_not_pending"),
    ],
)
def test_waiting_for_roll_rejects_wrong_or_resolved_request(override, code: str) -> None:
    action = _action()
    with pytest.raises(PendingActionRollBindingError, match=code):
        validate_pending_roll_binding(  # type: ignore[arg-type]
            action,
            _request(action, **override),
        )


def test_waiting_for_roll_rejects_missing_or_cross_session_request() -> None:
    action = _action()
    with pytest.raises(PendingActionRollBindingError, match="roll_request_not_found"):
        validate_pending_roll_binding(action, None)  # type: ignore[arg-type]
