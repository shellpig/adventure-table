from __future__ import annotations

from fastapi import Request

from app.api.rooms.ai_controllers import get_ai_controller_service
from app.api.rooms.dependencies import (
    get_campaign_runtime_service,
    get_campaign_stage_service,
    get_combat_adjudication_service,
    get_combat_attack_service,
    get_combat_concentration_service,
    get_combat_core_roll_service,
    get_combat_initiative_service,
    get_combat_reaction_service,
    get_combat_resolution_service,
    get_combat_service,
    get_combat_special_attack_service,
    get_combat_spell_service,
    get_exploration_action_service,
    get_exploration_stage_service,
    get_monster_instance_service,
    get_pending_action_service,
    get_roll_service,
    get_room_workspace_service,
    get_session_service,
    get_table_character_state_service,
    get_table_event_service,
)
from app.domain.campaign_runtime.ai_tools import CampaignContextAIToolApplicationService
from app.domain.campaign_runtime.context import CampaignContextService
from app.domain.campaign_runtime.world import CampaignWorldService
from app.domain.rooms.ai_tools import AIToolApplicationService


def get_ai_tool_application_service(request: Request) -> AIToolApplicationService:
    service = getattr(request.app.state, "ai_tool_application_service", None)
    if service is None:
        service = CampaignContextAIToolApplicationService(
            campaign_context_service=CampaignContextService(get_campaign_runtime_service(request)),
            campaign_world_service=CampaignWorldService(get_campaign_runtime_service(request)),
            campaign_stage_service=get_campaign_stage_service(request),
            ai_controller_service=get_ai_controller_service(request),
            session_service=get_session_service(request),
            stage_service=get_exploration_stage_service(request),
            action_service=get_exploration_action_service(request),
            roll_service=get_roll_service(request),
            state_service=get_table_character_state_service(request),
            pending_action_service=get_pending_action_service(request),
            event_service=get_table_event_service(request),
            workspace_service=get_room_workspace_service(request),
            combat_service=get_combat_service(request),
            combat_attack_service=get_combat_attack_service(request),
            combat_resolution_service=get_combat_resolution_service(request),
            combat_core_roll_service=get_combat_core_roll_service(request),
            combat_special_attack_service=get_combat_special_attack_service(request),
            combat_initiative_service=get_combat_initiative_service(request),
            monster_instance_service=get_monster_instance_service(request),
            combat_spell_service=get_combat_spell_service(request),
            combat_concentration_service=get_combat_concentration_service(request),
            combat_reaction_service=get_combat_reaction_service(request),
            combat_adjudication_service=get_combat_adjudication_service(request),
        )
        request.app.state.ai_tool_application_service = service
    return service


__all__ = ["get_ai_tool_application_service"]
