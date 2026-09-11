from __future__ import annotations

from app.domain.rooms.ai_controllers import AIControllerService, AIHandoffRequest
from app.domain.rooms.ai_tools import (
    AIToolApplicationService,
    EventsInput,
    RollPendingInput,
)
from app.domain.rooms.rolls import (
    RequestCheckInput,
    RollRequestType,
    RollService,
    RollVisibility,
)
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.table_events import TableEventService
from app.persistence.rooms.ai_controllers import AIControllerGrantRepository
from app.persistence.rooms.exploration_subjects import ExplorationSubjectRepository
from app.persistence.rooms.p3c_rolls import RollRepository
from app.persistence.rooms.table_runtime import TableEventRepository
from tests.test_p3e_shared_action_integration import _engine, _seed


class _FixedModifierResolver:
    def modifier_for(self, *, character_id, request_type, ability_ref, skill_ref) -> int:
        del character_id, request_type, ability_ref, skill_ref
        return 3


def _facade(controller, events, rolls):
    return AIToolApplicationService(
        ai_controller_service=controller,
        session_service=None,  # type: ignore[arg-type]
        stage_service=None,  # type: ignore[arg-type]
        action_service=None,  # type: ignore[arg-type]
        roll_service=rolls,
        state_service=None,  # type: ignore[arg-type]
        pending_action_service=None,  # type: ignore[arg-type]
        event_service=events,
        workspace_service=None,  # type: ignore[arg-type]
    )


def test_human_dm_check_is_visible_and_ai_mcp_roll_resolves_canonical_request() -> None:
    engine = _engine()
    try:
        ids = _seed(engine)
        events = TableEventService(TableEventRepository(engine))
        controller = AIControllerService(AIControllerGrantRepository(engine), events)
        rolls = RollService(
            RollRepository(engine, events.repository),
            ExplorationSubjectRepository(engine),
            events,
            _FixedModifierResolver(),
        )

        dm = events.resolve_human_actor(
            room_id=ids["room_id"],
            campaign_id=ids["campaign_id"],
            session_id=ids["session_id"],
            context=RoomAccessContext(
                room_id=ids["room_id"],
                access_session_id=ids["dm_access_id"],
                authority=RoomAccessAuthority.DM,
            ),
        )
        grant = controller.let_ai_control_player(
            room_id=ids["room_id"],
            campaign_id=ids["campaign_id"],
            session_id=ids["session_id"],
            seat_id=ids["player_seat_id"],
            context=RoomAccessContext(
                room_id=ids["room_id"],
                access_session_id=ids["player_access_id"],
                authority=RoomAccessAuthority.MEMBER,
            ),
            request=AIHandoffRequest(),
        )
        facade = _facade(controller, events, rolls)

        _group_id, requests = rolls.request_check(
            dm,
            RequestCheckInput(
                target_seat_ids=(ids["player_seat_id"],),
                request_type=RollRequestType.OTHER,
                dc=17,
                visibility=RollVisibility.PUBLIC,
                label="Check the trapped door",
                idempotency_key="p3e-human-dm-check-1",
            ),
        )
        request = requests[0]
        assert request.status == "pending"
        assert request.dc == 17

        pending = facade.get_pending_events(
            grant.token,
            EventsInput(after_seq=0, limit=50),
        )
        requested_event = next(
            event for event in pending["events"] if event["kind"] == "roll.requested"
        )
        assert str(request.id) in requested_event["payload"]["roll_request_ids"]
        assert "dc" not in requested_event["payload"]

        result = facade.roll_pending(
            grant.token,
            RollPendingInput(
                roll_request_id=request.id,
                idempotency_key="p3e-ai-roll-1",
            ),
        )
        assert result["roll_request_id"] == str(request.id)
        assert result["acting_seat_id"] == str(ids["player_seat_id"])
        assert result["subject_seat_id"] == str(ids["player_seat_id"])
        assert result["subject_character_id"] == str(ids["character_id"])
        assert result["execution_mode"] == "self"
        assert result["source"] == "server"
        assert result["base_modifier"] == 3
        assert result["total"] == result["kept_dice"][0] + 3

        human_requests = {item.id: item for item in rolls.list_requests(dm)}
        assert human_requests[request.id].status == "resolved"
        assert human_requests[request.id].dc == 17

        human_events = events.list_after(dm, after_seq=0, limit=50)
        resolved_event = next(
            event
            for event in human_events.events
            if event.kind == "roll.resolved"
            and event.payload.get("roll_request_id") == str(request.id)
        )
        assert resolved_event.acting_seat_id == ids["player_seat_id"]
        assert resolved_event.payload["total"] == result["total"]
        assert resolved_event.payload["base_modifier"] == 3
    finally:
        engine.dispose()
