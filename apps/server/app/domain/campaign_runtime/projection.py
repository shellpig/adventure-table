from __future__ import annotations

from collections.abc import Collection
from copy import deepcopy
from uuid import UUID

from app.domain.campaign_runtime.schemas import (
    RuntimeWorldEntry,
    RuntimeWorldEntryDmView,
    RuntimeWorldEntryPlayerView,
)


def project_runtime_entry(
    entry: RuntimeWorldEntry,
    *,
    controlled_character_ids: Collection[UUID],
    is_dm: bool,
) -> RuntimeWorldEntryDmView | RuntimeWorldEntryPlayerView | None:
    if is_dm:
        return RuntimeWorldEntryDmView(
            id=entry.id,
            campaign_id=entry.campaign_id,
            kind=entry.kind,
            title=entry.title,
            body=entry.body,
            state=entry.state.model_copy(deep=True),
            visibility=entry.visibility,
            dm_notes=entry.dm_notes,
            needs_review=entry.needs_review,
            source_adventure_entry_id=entry.source_adventure_entry_id,
            provenance_json=deepcopy(entry.provenance_json)
            if entry.provenance_json is not None
            else None,
            character_recipient_ids=entry.character_recipient_ids,
            revision=entry.revision,
            created_by_actor_kind=entry.created_by_actor_kind,
            created_by_actor_id=entry.created_by_actor_id,
            created_at=entry.created_at,
            updated_at=entry.updated_at,
            archived_at=entry.archived_at,
        )

    # Player audience projection
    if entry.visibility == "dm_only":
        return None

    if entry.visibility == "character":
        if not controlled_character_ids:
            return None
        char_ids = set(controlled_character_ids)
        if not (char_ids & set(entry.character_recipient_ids)):
            return None

    elif entry.visibility != "public":
        return None

    return RuntimeWorldEntryPlayerView(
        id=entry.id,
        campaign_id=entry.campaign_id,
        kind=entry.kind,
        title=entry.title,
        body=entry.body,
        state=entry.state.model_copy(deep=True),
        visibility=entry.visibility,
        revision=entry.revision,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )


__all__ = [
    "project_runtime_entry",
]
