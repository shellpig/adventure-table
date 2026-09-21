from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import Field

from app.domain.campaign_runtime.context import CampaignContextService
from app.domain.campaign_runtime.context_schemas import (
    AdventureSceneRef,
    CampaignContextDmView,
    RuntimeSceneRef,
    SEARCH_MAX_LIMIT,
    SceneRef,
)
from app.domain.combat.ai_tools import CombatAIToolApplicationService
from app.domain.rooms.ai_controllers import AIControllerAuthView
from app.domain.rooms.ai_tools import AIToolInputError
from app.domain.rooms.schemas import StrictModel
from app.domain.rooms.table_events import TableActorContext

SESSION_CONTEXT_MAX_WORLD_REFS = 20


class SceneContextToolInput(StrictModel):
    adventure_entry_id: UUID | None = None
    runtime_entry_id: UUID | None = None


class SearchCampaignContextToolInput(StrictModel):
    query: str
    kinds: tuple[str, ...] | None = None
    limit: int | None = Field(default=None, ge=1, le=SEARCH_MAX_LIMIT)
    offset: int = Field(default=0, ge=0)


class WorldEntryToolInput(StrictModel):
    world_entry_id: UUID


class AdventureEntryToolInput(StrictModel):
    adventure_entry_id: UUID


class CampaignContextAIToolApplicationService(CombatAIToolApplicationService):
    """Facade exposing CampaignContextService intents as transport-neutral MCP tools."""

    def __init__(
        self,
        *,
        campaign_context_service: CampaignContextService,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self.campaign_context_service = campaign_context_service

    def get_campaign_context(
        self,
        token: str,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        view = self.campaign_context_service.get_campaign_context(actor)
        return view.model_dump(mode="json")

    def get_scene_context(
        self,
        token: str,
        input: SceneContextToolInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        if input.adventure_entry_id is not None and input.runtime_entry_id is not None:
            raise AIToolInputError("Cannot specify both adventure_entry_id and runtime_entry_id")
        actor = self._actor(token, authenticated=authenticated)
        scene_ref: SceneRef | None = None
        if input.adventure_entry_id is not None:
            scene_ref = AdventureSceneRef(adventure_entry_id=input.adventure_entry_id)
        elif input.runtime_entry_id is not None:
            scene_ref = RuntimeSceneRef(runtime_entry_id=input.runtime_entry_id)
        view = self.campaign_context_service.get_scene_context(actor, scene_ref)
        return view.model_dump(mode="json")

    def search_campaign_context(
        self,
        token: str,
        input: SearchCampaignContextToolInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        view = self.campaign_context_service.search_campaign_context(
            actor,
            query=input.query,
            kinds=input.kinds,
            limit=input.limit,
            offset=input.offset,
        )
        return view.model_dump(mode="json")

    def get_world_entry(
        self,
        token: str,
        input: WorldEntryToolInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        view = self.campaign_context_service.get_world_entry(actor, input.world_entry_id)
        return view.model_dump(mode="json")

    def get_adventure_entry(
        self,
        token: str,
        input: AdventureEntryToolInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        view = self.campaign_context_service.get_adventure_entry(actor, input.adventure_entry_id)
        return view.model_dump(mode="json")

    def _active_context_extension(self, actor: TableActorContext) -> dict[str, Any]:
        view = self.campaign_context_service.get_campaign_context(actor)
        world_entry_refs = [
            item.model_dump(mode="json")
            for item in view.world_entries[:SESSION_CONTEXT_MAX_WORLD_REFS]
        ]
        next_context_tools = [
            "get_scene_context",
            "search_campaign_context",
            "get_world_entry",
        ]
        if actor.is_current_dm:
            next_context_tools.append("get_adventure_entry")

        context_data: dict[str, Any] = {
            "current_scene": view.current_scene.model_dump(mode="json"),
            "current_situation": view.current_situation,
            "world_entry_refs": world_entry_refs,
            "world_entry_refs_truncated": len(view.world_entries) > SESSION_CONTEXT_MAX_WORLD_REFS,
            "next_context_tools": next_context_tools,
        }
        if isinstance(view, CampaignContextDmView):
            context_data["attached_adventure_count"] = len(view.attached_adventures)

        return {"campaign_context": context_data}


__all__ = [
    "AdventureEntryToolInput",
    "CampaignContextAIToolApplicationService",
    "SESSION_CONTEXT_MAX_WORLD_REFS",
    "SceneContextToolInput",
    "SearchCampaignContextToolInput",
    "WorldEntryToolInput",
]
