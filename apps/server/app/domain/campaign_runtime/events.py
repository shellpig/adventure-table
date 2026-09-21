from __future__ import annotations

import hashlib
from uuid import UUID

from sqlalchemy.engine import Connection

from app.domain.campaign_runtime.schemas import (
    CampaignAdventureOverride,
    CampaignRuntimeContext,
    RuntimeWorldEntryDmView,
)
from app.domain.rooms.table_events import (
    TableActorContext,
    TableActorKind,
    TableEventService,
)
from app.persistence.campaign_runtime.repository import (
    StoredRuntimeWorldEntryAggregate,
)


def override_event_envelope(
    override: CampaignAdventureOverride,
    action: str,
) -> tuple[CampaignAdventureOverride, str, tuple[UUID, ...], dict[str, object]]:
    return (
        override,
        "dm_only",
        (),
        {
            "override_id": str(override.id),
            "adventure_entry_id": str(override.adventure_entry_id),
            "revision": int(override.revision),
            "action": action,
        },
    )


def runtime_entry_event_envelope(
    connection: Connection,
    session_id: UUID,
    view: RuntimeWorldEntryDmView,
    aggregate: StoredRuntimeWorldEntryAggregate,
    action: str,
    event_service: TableEventService,
) -> tuple[RuntimeWorldEntryDmView, str, tuple[UUID, ...], dict[str, object]]:
    if aggregate.entry.visibility == "character":
        recipient_seats = (
            event_service.repository.active_session_seats_for_characters_in_transaction(
                connection,
                session_id,
                aggregate.character_recipient_ids,
            )
        )
        event_visibility = "seat_private"
    elif aggregate.entry.visibility == "dm_only":
        recipient_seats = ()
        event_visibility = "dm_only"
    else:
        recipient_seats = ()
        event_visibility = "public"

    event_payload: dict[str, object] = {
        "entry_id": str(aggregate.entry.id),
        "entry_kind": str(aggregate.entry.kind),
        "revision": int(aggregate.entry.revision),
        "action": action,
    }
    return view, event_visibility, recipient_seats, event_payload


def context_event_envelope(
    context: CampaignRuntimeContext,
    action: str,
) -> tuple[CampaignRuntimeContext, str, tuple[UUID, ...], dict[str, object]]:
    return (
        context,
        "dm_only",
        (),
        {
            "revision": int(context.revision),
            "action": action,
        },
    )


def session_event_idempotency_key(idempotency_key: str) -> str:
    digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
    return f"p6b-world:{digest}"


def actor_identity(actor: TableActorContext) -> tuple[str, UUID | None]:
    actor_id = (
        actor.access_session_id
        if actor.actor_kind is TableActorKind.HUMAN
        else actor.ai_controller_grant_id
    )
    return actor.actor_kind.value, actor_id
