from app.domain.rooms.rolls import (
    RollVisibility,
    _request_event_visibility,
    _result_event_visibility,
)


def test_private_formal_requests_wake_target_seats_without_exposing_result_audience() -> None:
    assert _request_event_visibility(RollVisibility.PUBLIC) == "public"
    assert _request_event_visibility(RollVisibility.ROLLER_AND_DM) == "seat_private"
    assert _request_event_visibility(RollVisibility.DM_ONLY) == "seat_private"


def test_formal_and_quick_results_keep_requested_visibility() -> None:
    assert _result_event_visibility(RollVisibility.PUBLIC) == "public"
    assert _result_event_visibility(RollVisibility.ROLLER_AND_DM) == "actor_and_dm"
    assert _result_event_visibility(RollVisibility.DM_ONLY) == "dm_only"
