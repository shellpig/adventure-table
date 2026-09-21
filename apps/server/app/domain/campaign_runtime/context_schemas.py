from __future__ import annotations

from typing import Literal
from uuid import UUID

from app.domain.campaign_runtime.payloads import (
    CampaignRuntimeError,
    RuntimeEntryKind,
    RuntimeVisibility,
)
from app.domain.campaign_runtime.schemas import (
    CampaignAdventureEntryOverlayView,
    CampaignAdventureOverride,
    RuntimeWorldEntryDmView,
    RuntimeWorldEntryPlayerView,
)
from app.domain.rooms.schemas import StrictModel


class CampaignInvalidSceneRefError(CampaignRuntimeError, ValueError):
    """Raised when a provided scene reference is invalid, foreign, or not a scene."""


class CampaignPartyMemberView(StrictModel):
    seat_id: UUID
    role: str
    active_character_id: UUID | None = None
    character_label: str | None = None


class ActiveCombatRef(StrictModel):
    combat_id: UUID
    round: int | None = None
    current_turn_entry_id: UUID | None = None


class AttachedAdventureRef(StrictModel):
    adventure_id: UUID
    name: str


class WorldEntryRef(StrictModel):
    id: UUID
    kind: RuntimeEntryKind
    title: str | None = None
    visibility: RuntimeVisibility


class CurrentSceneView(StrictModel):
    kind: Literal["adventure", "runtime", "none"]
    label: str | None = None
    entry_id: UUID | None = None


class CampaignContextPlayerView(StrictModel):
    campaign_id: UUID
    name: str
    current_scene: CurrentSceneView
    current_situation: str | None = None
    party: tuple[CampaignPartyMemberView, ...] = ()
    active_combat: ActiveCombatRef | None = None
    world_entries: tuple[WorldEntryRef, ...] = ()


class CampaignContextDmView(StrictModel):
    campaign_id: UUID
    name: str
    current_scene: CurrentSceneView
    current_situation: str | None = None
    party: tuple[CampaignPartyMemberView, ...] = ()
    active_combat: ActiveCombatRef | None = None
    attached_adventures: tuple[AttachedAdventureRef, ...] = ()
    world_entries: tuple[WorldEntryRef, ...] = ()


CampaignContextView = CampaignContextDmView | CampaignContextPlayerView


class AdventureSceneRef(StrictModel):
    adventure_entry_id: UUID


class RuntimeSceneRef(StrictModel):
    runtime_entry_id: UUID


SceneRef = AdventureSceneRef | RuntimeSceneRef


class SceneContextPlayerView(StrictModel):
    scene_id: UUID | None = None
    scene_kind: Literal["runtime"] | None = None
    title: str | None = None
    runtime_scene: RuntimeWorldEntryPlayerView | None = None
    related_entries: tuple[RuntimeWorldEntryPlayerView, ...] = ()


class SceneContextDmView(StrictModel):
    scene_id: UUID | None = None
    scene_kind: Literal["adventure", "runtime"] | None = None
    title: str | None = None
    baseline: CampaignAdventureEntryOverlayView | None = None
    override: CampaignAdventureOverride | None = None
    runtime_scene: RuntimeWorldEntryDmView | None = None
    current_truth: Literal["baseline", "override", "runtime"] | None = None
    related_entries: tuple[RuntimeWorldEntryDmView, ...] = ()


SceneContextView = SceneContextDmView | SceneContextPlayerView


__all__ = [
    "ActiveCombatRef",
    "AdventureSceneRef",
    "AttachedAdventureRef",
    "CampaignContextDmView",
    "CampaignContextPlayerView",
    "CampaignContextView",
    "CampaignInvalidSceneRefError",
    "CampaignPartyMemberView",
    "CurrentSceneView",
    "RuntimeSceneRef",
    "SceneContextDmView",
    "SceneContextPlayerView",
    "SceneContextView",
    "SceneRef",
    "WorldEntryRef",
]
