from __future__ import annotations

from collections.abc import Collection, Sequence
from copy import deepcopy
from typing import cast
from uuid import UUID

from app.domain.campaign_runtime.payloads import (
    RuntimeEntryKind,
    RuntimeVisibility,
    parse_runtime_payload,
)
from app.domain.campaign_runtime.projection import (
    project_runtime_entry,
)
from app.domain.campaign_runtime.schemas import (
    CampaignAdventureOverride,
    CampaignRuntimeContext,
    RuntimeWorldEntry,
    RuntimeWorldEntryDmView,
    RuntimeWorldEntryPlayerView,
)
from app.persistence.campaign_runtime.repository import (
    StoredCampaignAdventureOverride,
    StoredCampaignRuntimeContext,
    StoredRuntimeWorldEntryAggregate,
)


def stored_aggregate_to_runtime_entry(
    aggregate: StoredRuntimeWorldEntryAggregate,
) -> RuntimeWorldEntry:
    stored = aggregate.entry
    return RuntimeWorldEntry(
        id=stored.id,
        campaign_id=stored.campaign_id,
        kind=cast(RuntimeEntryKind, stored.kind),
        title=stored.title,
        body=stored.body,
        state=parse_runtime_payload(stored.kind, stored.state_json),
        dm_notes=stored.dm_notes,
        visibility=cast(RuntimeVisibility, stored.visibility),
        needs_review=stored.needs_review,
        source_adventure_entry_id=stored.source_adventure_entry_id,
        provenance_json=deepcopy(stored.provenance_json)
        if stored.provenance_json is not None
        else None,
        revision=stored.revision,
        created_by_actor_kind=stored.created_by_actor_kind,
        created_by_actor_id=stored.created_by_actor_id,
        created_at=stored.created_at,
        updated_at=stored.updated_at,
        archived_at=stored.archived_at,
        character_recipient_ids=aggregate.character_recipient_ids,
    )


def project_runtime_aggregate(
    aggregate: StoredRuntimeWorldEntryAggregate,
    *,
    controlled_character_ids: Collection[UUID],
    is_dm: bool,
) -> RuntimeWorldEntryDmView | RuntimeWorldEntryPlayerView | None:
    entry = stored_aggregate_to_runtime_entry(aggregate)
    return project_runtime_entry(
        entry,
        controlled_character_ids=controlled_character_ids,
        is_dm=is_dm,
    )


def project_runtime_aggregates(
    aggregates: Sequence[StoredRuntimeWorldEntryAggregate],
    *,
    controlled_character_ids: Collection[UUID],
    is_dm: bool,
) -> tuple[RuntimeWorldEntryDmView | RuntimeWorldEntryPlayerView, ...]:
    results: list[RuntimeWorldEntryDmView | RuntimeWorldEntryPlayerView] = []
    for agg in aggregates:
        projected = project_runtime_aggregate(
            agg,
            controlled_character_ids=controlled_character_ids,
            is_dm=is_dm,
        )
        if projected is not None:
            results.append(projected)
    return tuple(results)


def stored_override_to_domain(
    stored: StoredCampaignAdventureOverride,
) -> CampaignAdventureOverride:
    return CampaignAdventureOverride(
        id=stored.id,
        campaign_id=stored.campaign_id,
        adventure_entry_id=stored.adventure_entry_id,
        state_json=deepcopy(stored.state_json),
        note=stored.note,
        needs_review=stored.needs_review,
        revision=stored.revision,
        created_at=stored.created_at,
        updated_at=stored.updated_at,
    )


def stored_context_to_domain(
    stored: StoredCampaignRuntimeContext | None,
    campaign_id: UUID,
) -> CampaignRuntimeContext:
    if stored is None:
        return CampaignRuntimeContext(
            campaign_id=campaign_id,
            revision=0,
        )
    return CampaignRuntimeContext(
        campaign_id=stored.campaign_id,
        current_adventure_scene_entry_id=stored.current_adventure_scene_entry_id,
        current_runtime_scene_entry_id=stored.current_runtime_scene_entry_id,
        current_situation=stored.current_situation,
        revision=stored.revision,
        created_at=stored.created_at,
        updated_at=stored.updated_at,
    )
