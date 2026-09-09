from __future__ import annotations

from uuid import uuid4

import pytest

from app.domain.rooms.pending_actions import (
    PendingActionCreateInput,
    PendingActionInvalidTransitionError,
    PendingActionStatus,
    PendingActionTransitionInput,
    validate_pending_transition,
)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (PendingActionStatus.PENDING, PendingActionStatus.PROCESSING),
        (PendingActionStatus.PENDING, PendingActionStatus.WAITING_FOR_ROLL),
        (PendingActionStatus.PENDING, PendingActionStatus.CANCELLED),
        (PendingActionStatus.PROCESSING, PendingActionStatus.WAITING_FOR_ROLL),
        (PendingActionStatus.PROCESSING, PendingActionStatus.RESOLVED),
        (PendingActionStatus.PROCESSING, PendingActionStatus.CANCELLED),
        (PendingActionStatus.WAITING_FOR_ROLL, PendingActionStatus.PROCESSING),
        (PendingActionStatus.WAITING_FOR_ROLL, PendingActionStatus.RESOLVED),
        (PendingActionStatus.WAITING_FOR_ROLL, PendingActionStatus.CANCELLED),
    ],
)
def test_documented_pending_action_transitions_are_allowed(
    current: PendingActionStatus,
    target: PendingActionStatus,
) -> None:
    validate_pending_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (PendingActionStatus.PENDING, PendingActionStatus.RESOLVED),
        (PendingActionStatus.WAITING_FOR_ROLL, PendingActionStatus.PENDING),
        (PendingActionStatus.RESOLVED, PendingActionStatus.PROCESSING),
        (PendingActionStatus.RESOLVED, PendingActionStatus.CANCELLED),
        (PendingActionStatus.CANCELLED, PendingActionStatus.PENDING),
    ],
)
def test_illegal_reverse_or_skip_transitions_are_rejected(
    current: PendingActionStatus,
    target: PendingActionStatus,
) -> None:
    with pytest.raises(PendingActionInvalidTransitionError):
        validate_pending_transition(current, target)


def test_waiting_for_roll_requires_a_formal_request_reference() -> None:
    with pytest.raises(ValueError):
        PendingActionTransitionInput(
            expected_version=1,
            to_status=PendingActionStatus.WAITING_FOR_ROLL,
        )
    valid = PendingActionTransitionInput(
        expected_version=1,
        to_status=PendingActionStatus.WAITING_FOR_ROLL,
        roll_request_id=uuid4(),
    )
    assert valid.roll_request_id is not None


def test_pending_action_requires_real_intent_payload_or_text() -> None:
    with pytest.raises(ValueError):
        PendingActionCreateInput(subject_seat_id=uuid4(), text="   ")
    assert PendingActionCreateInput(
        subject_seat_id=uuid4(),
        intent_payload={"kind": "search", "target": "door"},
    ).intent_payload == {"kind": "search", "target": "door"}
