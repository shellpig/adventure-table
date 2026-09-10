from app.api.rooms.p3c_pending import _map_pending_error, router
from app.domain.rooms.pending_actions import (
    PendingActionInvalidTransitionError,
    PendingActionRollBindingError,
    PendingActionVersionConflictError,
)


def test_pending_action_router_exposes_p3c_lifecycle_endpoints() -> None:
    paths = {route.path for route in router.routes}
    assert paths == {
        "/api/rooms/{room_id}/campaigns/{campaign_id}/sessions/{session_id}/pending-actions",
        "/api/rooms/{room_id}/campaigns/{campaign_id}/sessions/{session_id}/pending-actions/{action_id}/transition",
    }


def test_pending_action_domain_errors_have_stable_http_codes() -> None:
    invalid = _map_pending_error(PendingActionInvalidTransitionError("pending->resolved"))
    conflict = _map_pending_error(PendingActionVersionConflictError("action"))
    binding = _map_pending_error(PendingActionRollBindingError("roll_request_subject_mismatch"))

    assert (invalid.status_code, invalid.code) == (409, "pending_action_invalid_transition")
    assert (conflict.status_code, conflict.code) == (409, "pending_action_version_conflict")
    assert (binding.status_code, binding.code) == (409, "pending_action_invalid_roll_binding")
