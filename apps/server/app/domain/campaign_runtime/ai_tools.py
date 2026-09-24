from __future__ import annotations

from typing import Annotated, Any
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
from app.domain.campaign_runtime.schemas import (
    CampaignRuntimeContextPatch,
    RuntimeWorldEntryCreate,
    RuntimeWorldEntryPatch,
)
from app.domain.campaign_runtime.stage import (
    CampaignStageBridgeService,
    StageImageSource,
)
from app.domain.campaign_runtime.world import (
    CampaignWorldService,
    ClearAdventureOverrideIntent,
    GrantCharacterKnowledgeIntent,
    ResolveWorldActionRequest,
    SetAdventureOverrideIntent,
    SetNeedsReviewTarget,
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


class WorldCreateEntryToolInput(StrictModel):
    entry: RuntimeWorldEntryCreate
    idempotency_key: str = Field(min_length=1, max_length=120)


class WorldUpdateEntryToolInput(StrictModel):
    entry_id: UUID
    patch: RuntimeWorldEntryPatch
    idempotency_key: str = Field(min_length=1, max_length=120)


class WorldArchiveEntryToolInput(StrictModel):
    entry_id: UUID
    expected_revision: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=120)


class WorldSetOverrideToolInput(StrictModel):
    intent: SetAdventureOverrideIntent
    idempotency_key: str = Field(min_length=1, max_length=120)


class WorldClearOverrideToolInput(StrictModel):
    intent: ClearAdventureOverrideIntent
    idempotency_key: str = Field(min_length=1, max_length=120)


class WorldSetCurrentContextToolInput(StrictModel):
    patch: CampaignRuntimeContextPatch
    idempotency_key: str = Field(min_length=1, max_length=120)


class WorldGrantKnowledgeToolInput(StrictModel):
    intent: GrantCharacterKnowledgeIntent
    idempotency_key: str = Field(min_length=1, max_length=120)


class WorldSetNeedsReviewToolInput(StrictModel):
    target: Annotated[SetNeedsReviewTarget, Field(discriminator="target_kind")]
    idempotency_key: str = Field(min_length=1, max_length=120)


class WorldResolveActionToolInput(StrictModel):
    request: ResolveWorldActionRequest
    idempotency_key: str = Field(min_length=1, max_length=120)


class SetStageImageToolInput(StrictModel):
    source: StageImageSource
    expected_revision: int = Field(ge=0)
    idempotency_key: str = Field(min_length=1, max_length=120)


class CampaignContextAIToolApplicationService(CombatAIToolApplicationService):
    """Facade exposing CampaignContextService / CampaignWorldService / CampaignStageBridgeService
    intents as transport-neutral MCP tools."""

    def __init__(
        self,
        *,
        campaign_context_service: CampaignContextService,
        campaign_world_service: CampaignWorldService,
        campaign_stage_service: CampaignStageBridgeService,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self.campaign_context_service = campaign_context_service
        self.campaign_world_service = campaign_world_service
        self.campaign_stage_service = campaign_stage_service

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

    def world_create_entry(
        self,
        token: str,
        input: WorldCreateEntryToolInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        view = self.campaign_world_service.create_world_entry(
            actor,
            input.entry,
            idempotency_key=input.idempotency_key,
        )
        return view.model_dump(mode="json")

    def world_update_entry(
        self,
        token: str,
        input: WorldUpdateEntryToolInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        view = self.campaign_world_service.update_world_entry(
            actor,
            input.entry_id,
            input.patch,
            idempotency_key=input.idempotency_key,
        )
        return view.model_dump(mode="json")

    def world_archive_entry(
        self,
        token: str,
        input: WorldArchiveEntryToolInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        view = self.campaign_world_service.archive_world_entry(
            actor,
            input.entry_id,
            expected_revision=input.expected_revision,
            idempotency_key=input.idempotency_key,
        )
        return view.model_dump(mode="json")

    def world_set_override(
        self,
        token: str,
        input: WorldSetOverrideToolInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        view = self.campaign_world_service.set_adventure_override(
            actor,
            input.intent,
            idempotency_key=input.idempotency_key,
        )
        return view.model_dump(mode="json")

    def world_clear_override(
        self,
        token: str,
        input: WorldClearOverrideToolInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        view = self.campaign_world_service.clear_adventure_override(
            actor,
            input.intent,
            idempotency_key=input.idempotency_key,
        )
        return view.model_dump(mode="json")

    def world_set_current_context(
        self,
        token: str,
        input: WorldSetCurrentContextToolInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        view = self.campaign_world_service.set_current_context(
            actor,
            input.patch,
            idempotency_key=input.idempotency_key,
        )
        return view.model_dump(mode="json")

    def world_grant_knowledge(
        self,
        token: str,
        input: WorldGrantKnowledgeToolInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        view = self.campaign_world_service.grant_character_knowledge(
            actor,
            input.intent,
            idempotency_key=input.idempotency_key,
        )
        return view.model_dump(mode="json")

    def world_set_needs_review(
        self,
        token: str,
        input: WorldSetNeedsReviewToolInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        view = self.campaign_world_service.set_needs_review(
            actor,
            input.target,
            idempotency_key=input.idempotency_key,
        )
        return view.model_dump(mode="json")

    def world_resolve_action(
        self,
        token: str,
        input: WorldResolveActionToolInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        view = self.campaign_world_service.resolve_world_action(
            actor,
            input.request,
            idempotency_key=input.idempotency_key,
        )
        return view.model_dump(mode="json")

    def set_stage_image(
        self,
        token: str,
        input: SetStageImageToolInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        view = self.campaign_stage_service.set_stage_image(
            actor,
            input.source,
            expected_revision=input.expected_revision,
            idempotency_key=input.idempotency_key,
        )
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
            # The Adventure outline lives in get_campaign_context; point the DM
            # there first, and to scene selection while no scene is current.
            if view.attached_adventures:
                next_context_tools.insert(0, "get_campaign_context")
            if view.current_scene.kind == "none":
                next_context_tools.append("world_set_current_context")

        context_data: dict[str, Any] = {
            "current_scene": view.current_scene.model_dump(mode="json"),
            "current_situation": view.current_situation,
            "world_entry_refs": world_entry_refs,
            "world_entry_refs_truncated": len(view.world_entries) > SESSION_CONTEXT_MAX_WORLD_REFS,
            "next_context_tools": next_context_tools,
        }
        if isinstance(view, CampaignContextDmView):
            context_data["attached_adventure_count"] = len(view.attached_adventures)
            context_data["attached_adventures"] = [
                {
                    "adventure_id": str(ref.adventure_id),
                    "name": ref.name,
                    "outline_entry_count": len(ref.outline),
                }
                for ref in view.attached_adventures
            ]

        return {"campaign_context": context_data}


__all__ = [
    "AdventureEntryToolInput",
    "CampaignContextAIToolApplicationService",
    "SESSION_CONTEXT_MAX_WORLD_REFS",
    "SceneContextToolInput",
    "SearchCampaignContextToolInput",
    "SetStageImageToolInput",
    "WorldArchiveEntryToolInput",
    "WorldClearOverrideToolInput",
    "WorldCreateEntryToolInput",
    "WorldEntryToolInput",
    "WorldGrantKnowledgeToolInput",
    "WorldResolveActionToolInput",
    "WorldSetCurrentContextToolInput",
    "WorldSetNeedsReviewToolInput",
    "WorldSetOverrideToolInput",
    "WorldUpdateEntryToolInput",
]
