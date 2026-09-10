from uuid import uuid4

from app.api.rooms.p3c_rolls import _map_roll_error, _submission_response, router
from app.domain.rooms.rolls import RollInputInvalidError, RollResultView, RollVisibility
from app.domain.rooms.table_events import TableActorContext, TableActorKind


def _actor(*, is_dm: bool) -> TableActorContext:
    seat_id = uuid4()
    return TableActorContext(
        actor_kind=TableActorKind.HUMAN,
        room_id=uuid4(),
        campaign_id=uuid4(),
        session_id=uuid4(),
        seat_id=seat_id,
        controlled_seat_ids=() if is_dm else (seat_id,),
        role="dm" if is_dm else "player",
        is_current_dm=is_dm,
        access_session_id=uuid4(),
    )


def _result(visibility: RollVisibility) -> RollResultView:
    return RollResultView(
        id=uuid4(),
        roll_request_id=uuid4(),
        session_id=uuid4(),
        acting_seat_id=uuid4(),
        subject_seat_id=uuid4(),
        subject_character_id=uuid4(),
        execution_mode="self",
        source="server",
        formula="1d20+3",
        raw_dice=(12,),
        kept_dice=(12,),
        base_modifier=3,
        flat_adjustment=0,
        total=15,
        visibility=visibility,
    )


def test_roll_router_exposes_only_p3c_roll_endpoints() -> None:
    paths = {route.path for route in router.routes}
    assert paths == {
        "/api/rooms/{room_id}/campaigns/{campaign_id}/sessions/{session_id}/checks",
        "/api/rooms/{room_id}/campaigns/{campaign_id}/sessions/{session_id}/roll-requests",
        "/api/rooms/{room_id}/campaigns/{campaign_id}/sessions/{session_id}/rolls/formal",
        "/api/rooms/{room_id}/campaigns/{campaign_id}/sessions/{session_id}/rolls/quick",
    }


def test_dm_only_result_is_not_projected_to_player_response() -> None:
    result = _result(RollVisibility.DM_ONLY)
    response = _submission_response(_actor(is_dm=False), result)

    assert response.result_id == result.id
    assert response.roll_request_id == result.roll_request_id
    assert response.hidden is True
    assert response.result is None


def test_dm_can_receive_dm_only_result_details() -> None:
    result = _result(RollVisibility.DM_ONLY)
    response = _submission_response(_actor(is_dm=True), result)

    assert response.hidden is False
    assert response.result == result


def test_roll_input_errors_have_stable_http_code() -> None:
    error = _map_roll_error(RollInputInvalidError("bad ability ref"))
    assert error.status_code == 422
    assert error.code == "invalid_roll_input"
