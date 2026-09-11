from __future__ import annotations

from fastapi import Request

from app.api.rooms.ai_controllers import get_ai_controller_service
from app.api.rooms.dependencies import (
    get_exploration_action_service,
    get_exploration_stage_service,
    get_pending_action_service,
    get_roll_service,
    get_room_workspace_service,
    get_session_service,
    get_table_character_state_service,
    get_table_event_service,
)
from app.domain.rooms.ai_tools import AIToolApplicationService


def get_ai_tool_application_service(request: Request) -> AIToolApplicationService:
    service = getattr(request.app.state, "ai_tool_application_service", None)
    if service is None:
        service = AIToolApplicationService(
            ai_controller_service=get_ai_controller_service(request),
            session_service=get_session_service(request),
            stage_service=get_exploration_stage_service(request),
            action_service=get_exploration_action_service(request),
            roll_service=get_roll_service(request),
            state_service=get_table_character_state_service(request),
            pending_action_service=get_pending_action_service(request),
            event_service=get_table_event_service(request),
            workspace_service=get_room_workspace_service(request),
        )
        request.app.state.ai_tool_application_service = service
    return service


__all__ = ["get_ai_tool_application_service"]
