from __future__ import annotations

from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.engine import Connection, RowMapping

from app.domain.adventures.payloads import (
    AdventureEntryPayload,
    AdventureEntryPayloadError,
    parse_entry_payload,
)
from app.domain.adventures.schemas import (
    AdventureEntryKind,
    AdventureEntryVisibility,
)
from app.domain.campaign_runtime.conversion import (
    stored_override_to_domain,
)
from app.domain.campaign_runtime.errors import (
    CampaignRuntimeNotFoundError,
    CampaignRuntimeValidationError,
)
from app.domain.campaign_runtime.schemas import (
    CampaignAdventureEntryOverlayView,
)
from app.persistence.adventures.repository import (
    CampaignAdventureLinkRepository,
)
from app.persistence.adventures.tables import (
    adventure_definitions,
    adventure_entries,
)
from app.persistence.campaign_runtime.repository import (
    CampaignRuntimeRepository,
    StoredCampaignAdventureOverride,
)


def get_attached_adventure_entry_source(
    connection: Connection,
    *,
    room_id: UUID,
    campaign_id: UUID,
    adventure_entry_id: UUID,
    link_repo: CampaignAdventureLinkRepository,
) -> RowMapping:
    row = connection.execute(
        select(
            adventure_entries.c.id,
            adventure_entries.c.adventure_id,
            adventure_entries.c.parent_entry_id,
            adventure_entries.c.kind,
            adventure_entries.c.title,
            adventure_entries.c.body,
            adventure_entries.c.data_json,
            adventure_entries.c.visibility,
            adventure_entries.c.sort_order,
            adventure_definitions.c.room_id,
        )
        .join(
            adventure_definitions,
            adventure_definitions.c.id == adventure_entries.c.adventure_id,
        )
        .where(adventure_entries.c.id == adventure_entry_id)
    ).mappings().one_or_none()

    if row is None or row["room_id"] != room_id:
        raise CampaignRuntimeNotFoundError(
            f"Adventure entry {adventure_entry_id} not found in room {room_id}"
        )
    if not link_repo.is_adventure_entry_attached_in_transaction(
        connection, campaign_id, adventure_entry_id
    ):
        raise CampaignRuntimeValidationError(
            f"Adventure entry {adventure_entry_id} is not from an adventure attached to campaign {campaign_id}"
        )
    return row


def validate_and_parse_entry_state(
    entry_kind: str,
    base_data_json: dict[str, object],
    override_state: dict[str, object] | None,
) -> AdventureEntryPayload:
    if override_state is None:
        try:
            return parse_entry_payload(entry_kind, base_data_json)
        except AdventureEntryPayloadError as exc:
            raise CampaignRuntimeValidationError(
                f"Invalid state for entry kind '{entry_kind}': {exc}"
            ) from exc

    merged = dict(base_data_json)
    merged.update(override_state)
    try:
        return parse_entry_payload(entry_kind, merged)
    except AdventureEntryPayloadError as exc:
        raise CampaignRuntimeValidationError(
            f"Invalid override state for entry kind '{entry_kind}': {exc}"
        ) from exc


def _build_adventure_entry_overlay(
    entry_row: RowMapping,
    override: StoredCampaignAdventureOverride | None,
) -> CampaignAdventureEntryOverlayView:
    entry_id = entry_row["id"]
    adventure_id = entry_row["adventure_id"]
    parent_entry_id = entry_row["parent_entry_id"]
    kind = cast(AdventureEntryKind, entry_row["kind"])
    title = entry_row["title"]
    body = entry_row["body"]
    visibility = cast(AdventureEntryVisibility, entry_row["visibility"])
    sort_order = entry_row["sort_order"]

    override_state = override.state_json if override is not None else None
    data = validate_and_parse_entry_state(kind, entry_row["data_json"], override_state)
    domain_override = stored_override_to_domain(override) if override is not None else None

    return CampaignAdventureEntryOverlayView(
        id=entry_id,
        adventure_id=adventure_id,
        parent_entry_id=parent_entry_id,
        kind=kind,
        title=title,
        body=body,
        data=data,
        visibility=visibility,
        sort_order=sort_order,
        override=domain_override,
    )


def get_adventure_entry_overlay_in_transaction(
    connection: Connection,
    *,
    room_id: UUID,
    campaign_id: UUID,
    adventure_entry_id: UUID,
    link_repo: CampaignAdventureLinkRepository,
    runtime_repo: CampaignRuntimeRepository,
) -> CampaignAdventureEntryOverlayView:
    row = get_attached_adventure_entry_source(
        connection,
        room_id=room_id,
        campaign_id=campaign_id,
        adventure_entry_id=adventure_entry_id,
        link_repo=link_repo,
    )
    override = runtime_repo.get_override_in_transaction(
        connection, campaign_id, adventure_entry_id
    )
    return _build_adventure_entry_overlay(row, override)


def list_adventure_entry_overlays_in_transaction(
    connection: Connection,
    *,
    campaign_id: UUID,
    adventure_id: UUID,
    link_repo: CampaignAdventureLinkRepository,
    runtime_repo: CampaignRuntimeRepository,
) -> tuple[CampaignAdventureEntryOverlayView, ...]:
    if not link_repo.is_attached_in_transaction(
        connection, campaign_id, adventure_id
    ):
        raise CampaignRuntimeValidationError(
            f"Adventure {adventure_id} is not attached to campaign {campaign_id}"
        )
    rows = connection.execute(
        select(
            adventure_entries.c.id,
            adventure_entries.c.adventure_id,
            adventure_entries.c.parent_entry_id,
            adventure_entries.c.kind,
            adventure_entries.c.title,
            adventure_entries.c.body,
            adventure_entries.c.data_json,
            adventure_entries.c.visibility,
            adventure_entries.c.sort_order,
        )
        .where(adventure_entries.c.adventure_id == adventure_id)
        .order_by(
            adventure_entries.c.sort_order.asc(),
            adventure_entries.c.created_at.asc(),
        )
    ).mappings().all()
    overrides = runtime_repo.list_overrides_in_transaction(
        connection, campaign_id
    )
    overrides_by_entry_id = {o.adventure_entry_id: o for o in overrides}
    return tuple(
        _build_adventure_entry_overlay(row, overrides_by_entry_id.get(row["id"]))
        for row in rows
    )
