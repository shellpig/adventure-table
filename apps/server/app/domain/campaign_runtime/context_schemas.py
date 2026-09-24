from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field

from app.domain.adventures.schemas import AdventureEntryKind, AdventureEntryVisibility
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


ADVENTURE_OUTLINE_MAX_ENTRIES = 100


class AdventureOutlineEntryRef(StrictModel):
    id: UUID
    parent_entry_id: UUID | None = None
    kind: AdventureEntryKind
    title: str | None = None
    visibility: AdventureEntryVisibility
    has_override: bool


class AttachedAdventureRef(StrictModel):
    """DM-only table of contents: entry refs without bodies, so an AI DM can
    discover what the Adventure contains and drill down with get_adventure_entry."""

    adventure_id: UUID
    name: str
    summary: str | None = None
    outline: tuple[AdventureOutlineEntryRef, ...] = ()
    outline_truncated: bool = False


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
    current_context_revision: int = Field(ge=0)
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


SEARCH_DEFAULT_LIMIT = 20
SEARCH_MAX_LIMIT = 50
SEARCH_SNIPPET_MAX_CHARS = 160

SearchKind = RuntimeEntryKind | AdventureEntryKind


class CampaignSearchHitPlayerView(StrictModel):
    id: UUID
    kind: RuntimeEntryKind
    title: str | None = None
    snippet: str | None = None


class CampaignSearchHitDmView(StrictModel):
    source: Literal["runtime", "adventure"]
    id: UUID
    kind: SearchKind
    title: str | None = None
    snippet: str | None = None
    visibility: RuntimeVisibility | AdventureEntryVisibility
    adventure_id: UUID | None = None
    has_override: bool
    current_truth: Literal["runtime", "override", "baseline"]


class CampaignSearchPlayerResult(StrictModel):
    query: str
    limit: int
    offset: int
    has_more: bool
    hits: tuple[CampaignSearchHitPlayerView, ...] = ()


class CampaignSearchDmResult(StrictModel):
    query: str
    limit: int
    offset: int
    has_more: bool
    hits: tuple[CampaignSearchHitDmView, ...] = ()


CampaignSearchResult = CampaignSearchDmResult | CampaignSearchPlayerResult


__all__ = [
    "ADVENTURE_OUTLINE_MAX_ENTRIES",
    "ActiveCombatRef",
    "AdventureOutlineEntryRef",
    "AdventureSceneRef",
    "AttachedAdventureRef",
    "CampaignContextDmView",
    "CampaignContextPlayerView",
    "CampaignContextView",
    "CampaignInvalidSceneRefError",
    "CampaignPartyMemberView",
    "CampaignSearchDmResult",
    "CampaignSearchHitDmView",
    "CampaignSearchHitPlayerView",
    "CampaignSearchPlayerResult",
    "CampaignSearchResult",
    "CurrentSceneView",
    "RuntimeSceneRef",
    "SEARCH_DEFAULT_LIMIT",
    "SEARCH_MAX_LIMIT",
    "SEARCH_SNIPPET_MAX_CHARS",
    "SceneContextDmView",
    "SceneContextPlayerView",
    "SceneContextView",
    "SceneRef",
    "SearchKind",
    "WorldEntryRef",
]
