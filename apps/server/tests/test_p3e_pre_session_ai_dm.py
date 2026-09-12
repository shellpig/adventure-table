from __future__ import annotations

from datetime import timedelta

import pytest

from app.domain.rooms.ai_controllers import AIControllerService
from app.domain.rooms.ai_tools import AIToolApplicationService, AIToolScopeError
from app.domain.rooms.sessions import SessionService
from app.domain.rooms.table_events import TableEventService
from app.mcp.guide import render_briefing
from app.mcp.tools import tool_catalog
from app.persistence.rooms.ai_controllers import AIControllerGrantRepository
from app.persistence.rooms.sessions import SessionRepository
from app.persistence.rooms.table_runtime import TableEventRepository
from tests.test_p3d_ai_dm_session_lifecycle import _engine, _seed_campaign


def _facade(controller, sessions):
    return AIToolApplicationService(
        ai_controller_service=controller,
        session_service=sessions,
        stage_service=None,  # type: ignore[arg-type]
        action_service=None,  # type: ignore[arg-type]
        roll_service=None,  # type: ignore[arg-type]
        state_service=None,  # type: ignore[arg-type]
        pending_action_service=None,  # type: ignore[arg-type]
        event_service=None,  # type: ignore[arg-type]
        workspace_service=None,  # type: ignore[arg-type]
    )


def test_pre_session_ai_dm_context_and_start_use_real_p3d_session_binding() -> None:
    engine = _engine()
    try:
        with engine.begin() as connection:
            room_id, campaign_id, dm_seat_id = _seed_campaign(connection)

        events = TableEventService(TableEventRepository(engine))
        controller = AIControllerService(AIControllerGrantRepository(engine), events)
        sessions = SessionService(SessionRepository(engine), event_service=events)
        facade = _facade(controller, sessions)
        grant = controller.configure_pre_session_ai_dm(
            room_id=room_id,
            campaign_id=campaign_id,
            seat_id=dm_seat_id,
            ttl=timedelta(minutes=5),
        )

        before = controller.authenticate(grant.token)
        assert before.session_id is None
        assert [item["name"] for item in tool_catalog(before)] == [
            "get_session_context",
            "start_session",
        ]

        context = facade.get_session_context(grant.token)
        assert context == {
            "mode": "pre_session",
            "room_id": str(room_id),
            "campaign_id": str(campaign_id),
            "seat_id": str(dm_seat_id),
            "role": "dm",
            "start_available": True,
            "briefing": render_briefing(role="dm", mode="pre_session"),
            "temporary_instruction": None,
        }

        started = facade.start_session(grant.token)
        assert started["status"] == "active"
        assert started["dm_controller_kind"] == "ai"
        assert started["dm_controller_ai_grant_id"] == str(grant.grant_id)
        assert started["dm_controller_generation"] == grant.generation

        after = controller.authenticate(grant.token)
        assert after.session_id is not None
        assert str(after.session_id) == started["id"]
        names = [item["name"] for item in tool_catalog(after)]
        assert "start_session" not in names
        assert "post_narration" in names
        assert "request_check" in names
        assert "get_session_context" in names

        with pytest.raises(AIToolScopeError):
            facade.start_session(grant.token)
    finally:
        engine.dispose()
