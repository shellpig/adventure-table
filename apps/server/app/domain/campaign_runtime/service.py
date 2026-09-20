from __future__ import annotations

import hashlib
from collections.abc import Callable, Collection, Sequence
from copy import deepcopy
from datetime import datetime, timezone
from typing import TypeVar, cast
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.engine import Connection, Engine, RowMapping

from app.domain.adventures.payloads import (
    AdventureEntryPayload,
    AdventureEntryPayloadError,
    parse_entry_payload,
)
from app.domain.adventures.schemas import (
    AdventureEntryKind,
    AdventureEntryVisibility,
)
from app.domain.campaign_runtime.payloads import (
    CampaignRuntimeError,
    RuntimeEntryKind,
    RuntimeItemPayload,
    RuntimeStatePayload,
    RuntimeVisibility,
    dump_runtime_payload,
    parse_runtime_payload,
)
from app.domain.campaign_runtime.projection import project_runtime_entry
from app.domain.campaign_runtime.schemas import (
    CampaignAdventureEntryOverlayView,
    CampaignAdventureOverride,
    CampaignAdventureOverrideAlreadyExistsError,
    CampaignAdventureOverrideCreate,
    CampaignAdventureOverridePatch,
    CampaignRuntimeContext,
    CampaignRuntimeContextPatch,
    RuntimeWorldEntry,
    RuntimeWorldEntryCreate,
    RuntimeWorldEntryDmView,
    RuntimeWorldEntryPatch,
    RuntimeWorldEntryPlayerView,
    validate_entry_quick_add_minima,
    validate_runtime_visibility_recipients,
)
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.table_events import (
    TableActorContext,
    TableActorKind,
    TableEventActorUnauthorizedError,
    TableEventService,
)
from app.persistence.adventures.repository import CampaignAdventureLinkRepository
from app.persistence.adventures.tables import (
    adventure_definitions,
    adventure_entries,
)
from app.persistence.campaign_runtime.mutations import (
    CampaignWorldMutationRepository,
    StoredCampaignWorldMutation,
)
from app.persistence.campaign_runtime.repository import (
    CampaignAdventureOverrideConflictError,
    CampaignAdventureOverrideNotFoundError,
    CampaignRuntimeContextConflictError,
    CampaignRuntimeRepository,
    RuntimeWorldEntryArchivedError,
    RuntimeWorldEntryConflictError,
    RuntimeWorldEntryNotFoundError,
    StoredCampaignAdventureOverride,
    StoredCampaignAdventureOverrideUpdate,
    StoredCampaignRuntimeContext,
    StoredCampaignRuntimeContextUpdate,
    StoredRuntimeWorldEntry,
    StoredRuntimeWorldEntryAggregate,
    StoredRuntimeWorldEntryUpdate,
)
from app.persistence.rooms.campaigns import CampaignRepository
from app.persistence.rooms.sessions import SessionRepository
from app.persistence.rooms.table_runtime import (
    StoredTableActorBinding,
    TableEventActorBindingStalePersistenceError,
    TableEventSessionNotActivePersistenceError,
    TableEventSessionNotFoundPersistenceError,
)

T = TypeVar("T")


class CampaignRuntimeAuthorityError(CampaignRuntimeError, PermissionError):
    """Raised when actor lacks required room/campaign management authority."""


class CampaignRuntimeNotFoundError(CampaignRuntimeError, LookupError):
    """Raised when room, campaign, or runtime entry is not found."""


class CampaignRuntimeConflictError(CampaignRuntimeError, RuntimeError):
    """Base exception for runtime conflicts."""


class CampaignRuntimeActiveSessionError(CampaignRuntimeConflictError):
    """Raised when management writes are attempted on a campaign with an active session."""


class CampaignRuntimeSessionNotActiveError(CampaignRuntimeConflictError):
    """Raised when active writes are attempted on a session that is not active."""


class CampaignRuntimeIdempotencyConflictError(CampaignRuntimeConflictError):
    """Raised when an idempotency key is reused with differing command or actor identity."""


class CampaignRuntimeRevisionConflictError(CampaignRuntimeConflictError):
    """Raised when expected revision does not match current entry revision."""

    def __init__(
        self,
        campaign_id: UUID,
        entry_id: UUID,
        expected_revision: int,
        current_revision: int,
        message: str | None = None,
    ) -> None:
        self.campaign_id = campaign_id
        self.entry_id = entry_id
        self.expected_revision = expected_revision
        self.current_revision = current_revision
        detail = message or f"expected revision {expected_revision} but found {current_revision}"
        super().__init__(
            f"Runtime world entry {entry_id} revision conflict in campaign {campaign_id}: {detail}"
        )


class CampaignRuntimeArchivedError(CampaignRuntimeRevisionConflictError):
    """Raised when modifying or re-archiving an already-archived runtime entry."""

    def __init__(
        self,
        campaign_id: UUID,
        entry_id: UUID,
        expected_revision: int,
        current_revision: int,
    ) -> None:
        super().__init__(
            campaign_id=campaign_id,
            entry_id=entry_id,
            expected_revision=expected_revision,
            current_revision=current_revision,
            message="entry is already archived",
        )


class CampaignRuntimeValidationError(CampaignRuntimeError, ValueError):
    """Raised when business reference or payload invariants are violated."""


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


def _stored_to_context_domain(
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


def _get_attached_adventure_entry_source(
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


def _validate_and_parse_entry_state(
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
    data = _validate_and_parse_entry_state(kind, entry_row["data_json"], override_state)
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


def _get_adventure_entry_overlay_in_transaction(
    connection: Connection,
    *,
    room_id: UUID,
    campaign_id: UUID,
    adventure_entry_id: UUID,
    link_repo: CampaignAdventureLinkRepository,
    runtime_repo: CampaignRuntimeRepository,
) -> CampaignAdventureEntryOverlayView:
    row = _get_attached_adventure_entry_source(
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


def _list_adventure_entry_overlays_in_transaction(
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


def _override_event_envelope(
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


def _runtime_entry_event_envelope(
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


def validate_mutation_identity(
    stored: StoredCampaignWorldMutation,
    *,
    action_kind: str,
    target_id: UUID | None,
    command_payload: dict[str, object],
    actor_kind: str,
    actor_id: UUID | None,
) -> None:
    if action_kind in ("runtime_entry.create", "override.create"):
        target_matches = (
            stored.target_id is not None if target_id is None else stored.target_id == target_id
        )
    else:
        target_matches = stored.target_id == target_id

    if not (
        stored.action_kind == action_kind
        and target_matches
        and stored.created_by_actor_kind == actor_kind
        and stored.created_by_actor_id == actor_id
        and stored.command_payload == command_payload
    ):
        raise CampaignRuntimeIdempotencyConflictError(
            f"Idempotency key '{stored.idempotency_key}' has already been used with different command or actor identity"
        )


def _require_management_authority(context: RoomAccessContext, room_id: UUID) -> None:
    if context.room_id != room_id:
        raise CampaignRuntimeNotFoundError(f"Room {room_id} not found")
    if context.authority is RoomAccessAuthority.MEMBER:
        raise CampaignRuntimeAuthorityError("Owner or DM authority is required")
    if context.authority not in (RoomAccessAuthority.OWNER, RoomAccessAuthority.DM):
        raise CampaignRuntimeAuthorityError("Owner or DM authority is required")


def _validate_idempotency_key(idempotency_key: str) -> None:
    if (
        not isinstance(idempotency_key, str)
        or not idempotency_key.strip()
        or len(idempotency_key) > 160
    ):
        raise CampaignRuntimeValidationError(
            "Idempotency key must be a nonblank string of at most 160 characters"
        )


def _validate_entry_references(
    connection: Connection,
    *,
    room_id: UUID,
    campaign_id: UUID,
    character_recipient_ids: Sequence[UUID],
    source_adventure_entry_id: UUID | None,
    kind: str,
    state: RuntimeStatePayload,
    runtime_repo: CampaignRuntimeRepository,
    link_repo: CampaignAdventureLinkRepository,
) -> None:
    for cid in character_recipient_ids:
        char_room_id = CampaignRepository.character_room_id_in_transaction(connection, cid)
        if char_room_id != room_id:
            raise CampaignRuntimeValidationError(
                f"Character recipient {cid} does not belong to room {room_id}"
            )

    if source_adventure_entry_id is not None:
        if not link_repo.is_adventure_entry_attached_in_transaction(
            connection, campaign_id, source_adventure_entry_id
        ):
            raise CampaignRuntimeValidationError(
                f"Source adventure entry {source_adventure_entry_id} is not from an adventure attached to campaign {campaign_id}"
            )

    if kind == "item" and isinstance(state, RuntimeItemPayload) and state.holder_ref is not None:
        holder_ref = state.holder_ref
        if holder_ref.kind in ("scene", "npc"):
            assert holder_ref.target_id is not None
            target_aggregate = runtime_repo.get_entry_in_transaction(
                connection, campaign_id, holder_ref.target_id, include_archived=False
            )
            if target_aggregate is None:
                raise CampaignRuntimeValidationError(
                    f"Item holder target {holder_ref.kind} {holder_ref.target_id} not found or archived in campaign {campaign_id}"
                )
            if target_aggregate.entry.kind != holder_ref.kind:
                raise CampaignRuntimeValidationError(
                    f"Item holder target {holder_ref.target_id} has kind '{target_aggregate.entry.kind}', expected '{holder_ref.kind}'"
                )
        elif holder_ref.kind == "character":
            assert holder_ref.target_id is not None
            char_room_id = CampaignRepository.character_room_id_in_transaction(
                connection, holder_ref.target_id
            )
            if char_room_id != room_id:
                raise CampaignRuntimeValidationError(
                    f"Item holder character {holder_ref.target_id} does not belong to room {room_id}"
                )


def _prepare_create_entry(
    connection: Connection,
    *,
    room_id: UUID,
    campaign_id: UUID,
    payload: RuntimeWorldEntryCreate,
    actor_kind: str,
    actor_id: UUID | None,
    now: datetime,
    runtime_repo: CampaignRuntimeRepository,
    link_repo: CampaignAdventureLinkRepository,
) -> tuple[StoredRuntimeWorldEntry, tuple[UUID, ...]]:
    parsed_state = parse_runtime_payload(payload.kind, payload.state)
    _validate_entry_references(
        connection,
        room_id=room_id,
        campaign_id=campaign_id,
        character_recipient_ids=payload.character_recipient_ids,
        source_adventure_entry_id=payload.source_adventure_entry_id,
        kind=payload.kind,
        state=parsed_state,
        runtime_repo=runtime_repo,
        link_repo=link_repo,
    )
    entry_id = uuid4()
    stored_entry = StoredRuntimeWorldEntry(
        id=entry_id,
        campaign_id=campaign_id,
        kind=payload.kind,
        title=payload.title,
        body=payload.body,
        state_json=payload.state,
        dm_notes=payload.dm_notes,
        visibility=payload.visibility,
        needs_review=payload.needs_review,
        source_adventure_entry_id=payload.source_adventure_entry_id,
        provenance_json=deepcopy(payload.provenance_json)
        if payload.provenance_json is not None
        else None,
        revision=1,
        created_by_actor_kind=actor_kind,
        created_by_actor_id=actor_id,
        created_at=now,
        updated_at=now,
        archived_at=None,
    )
    return stored_entry, payload.character_recipient_ids


def _execute_create_in_transaction(
    connection: Connection,
    *,
    room_id: UUID,
    campaign_id: UUID,
    payload: RuntimeWorldEntryCreate,
    idempotency_key: str,
    actor_kind: str,
    actor_id: UUID | None,
    now: datetime,
    runtime_repo: CampaignRuntimeRepository,
    mutation_repo: CampaignWorldMutationRepository,
    link_repo: CampaignAdventureLinkRepository,
) -> tuple[RuntimeWorldEntryDmView, StoredRuntimeWorldEntryAggregate]:
    stored_entry, recipients = _prepare_create_entry(
        connection,
        room_id=room_id,
        campaign_id=campaign_id,
        payload=payload,
        actor_kind=actor_kind,
        actor_id=actor_id,
        now=now,
        runtime_repo=runtime_repo,
        link_repo=link_repo,
    )
    created_aggregate = runtime_repo.create_entry_in_transaction(
        connection,
        stored_entry,
        character_recipient_ids=recipients,
    )
    view = project_runtime_aggregate(created_aggregate, controlled_character_ids=(), is_dm=True)
    assert isinstance(view, RuntimeWorldEntryDmView)

    command_payload = payload.model_dump(mode="json")
    mutation = StoredCampaignWorldMutation(
        id=uuid4(),
        campaign_id=campaign_id,
        idempotency_key=idempotency_key,
        action_kind="runtime_entry.create",
        target_id=stored_entry.id,
        command_payload=command_payload,
        result_payload=view.model_dump(mode="json"),
        created_by_actor_kind=actor_kind,
        created_by_actor_id=actor_id,
        created_at=now,
    )
    mutation_repo.insert_in_transaction(connection, mutation)
    return view, created_aggregate


def _execute_update_in_transaction(
    connection: Connection,
    *,
    room_id: UUID,
    campaign_id: UUID,
    entry_id: UUID,
    patch: RuntimeWorldEntryPatch,
    idempotency_key: str,
    actor_kind: str,
    actor_id: UUID | None,
    now: datetime,
    runtime_repo: CampaignRuntimeRepository,
    mutation_repo: CampaignWorldMutationRepository,
    link_repo: CampaignAdventureLinkRepository,
) -> tuple[RuntimeWorldEntryDmView, StoredRuntimeWorldEntryAggregate]:
    existing_aggregate = runtime_repo.get_entry_in_transaction(
        connection, campaign_id, entry_id, include_archived=True
    )
    if existing_aggregate is None:
        raise CampaignRuntimeNotFoundError(
            f"Runtime entry {entry_id} not found in campaign {campaign_id}"
        )
    if existing_aggregate.entry.archived_at is not None:
        raise CampaignRuntimeArchivedError(
            campaign_id=campaign_id,
            entry_id=entry_id,
            expected_revision=patch.expected_revision,
            current_revision=existing_aggregate.entry.revision,
        )
    if existing_aggregate.entry.revision != patch.expected_revision:
        raise CampaignRuntimeRevisionConflictError(
            campaign_id=campaign_id,
            entry_id=entry_id,
            expected_revision=patch.expected_revision,
            current_revision=existing_aggregate.entry.revision,
        )

    existing_entry = existing_aggregate.entry
    candidate_title = (
        patch.title if "title" in patch.model_fields_set else existing_entry.title
    )
    candidate_body = (
        patch.body if "body" in patch.model_fields_set else existing_entry.body
    )
    candidate_dm_notes = (
        patch.dm_notes
        if "dm_notes" in patch.model_fields_set
        else existing_entry.dm_notes
    )
    candidate_visibility = (
        patch.visibility
        if "visibility" in patch.model_fields_set
        else cast(RuntimeVisibility, existing_entry.visibility)
    )
    candidate_needs_review = (
        patch.needs_review
        if "needs_review" in patch.model_fields_set
        else existing_entry.needs_review
    )
    candidate_source_adventure_entry_id = (
        patch.source_adventure_entry_id
        if "source_adventure_entry_id" in patch.model_fields_set
        else existing_entry.source_adventure_entry_id
    )
    candidate_provenance_json = (
        deepcopy(patch.provenance_json)
        if "provenance_json" in patch.model_fields_set
        else deepcopy(existing_entry.provenance_json)
    )
    candidate_character_recipient_ids = (
        patch.character_recipient_ids
        if "character_recipient_ids" in patch.model_fields_set
        else existing_aggregate.character_recipient_ids
    )
    assert candidate_character_recipient_ids is not None
    assert candidate_visibility is not None
    assert candidate_needs_review is not None

    if "state" in patch.model_fields_set:
        assert patch.state is not None
        candidate_state_dict = patch.state
    else:
        candidate_state_dict = existing_entry.state_json

    kind = cast(RuntimeEntryKind, existing_entry.kind)
    validate_entry_quick_add_minima(kind, candidate_title, candidate_body)
    validate_runtime_visibility_recipients(
        candidate_visibility, candidate_character_recipient_ids
    )

    parsed_state = parse_runtime_payload(kind, candidate_state_dict)
    candidate_state_json = dump_runtime_payload(parsed_state)

    _validate_entry_references(
        connection,
        room_id=room_id,
        campaign_id=campaign_id,
        character_recipient_ids=candidate_character_recipient_ids,
        source_adventure_entry_id=candidate_source_adventure_entry_id,
        kind=kind,
        state=parsed_state,
        runtime_repo=runtime_repo,
        link_repo=link_repo,
    )

    update_candidate = StoredRuntimeWorldEntryUpdate(
        expected_revision=patch.expected_revision,
        title=candidate_title,
        body=candidate_body,
        state_json=candidate_state_json,
        dm_notes=candidate_dm_notes,
        visibility=candidate_visibility,
        needs_review=candidate_needs_review,
        source_adventure_entry_id=candidate_source_adventure_entry_id,
        provenance_json=candidate_provenance_json,
        updated_at=now,
        character_recipient_ids=tuple(candidate_character_recipient_ids),
    )

    try:
        updated_aggregate = runtime_repo.update_entry_in_transaction(
            connection,
            campaign_id,
            entry_id,
            update_candidate,
        )
    except RuntimeWorldEntryNotFoundError:
        raise CampaignRuntimeNotFoundError(
            f"Runtime entry {entry_id} not found in campaign {campaign_id}"
        )
    except RuntimeWorldEntryArchivedError as exc:
        raise CampaignRuntimeArchivedError(
            campaign_id=exc.campaign_id,
            entry_id=exc.entry_id,
            expected_revision=exc.expected_revision,
            current_revision=exc.current_revision,
        ) from exc
    except RuntimeWorldEntryConflictError as exc:
        raise CampaignRuntimeRevisionConflictError(
            campaign_id=exc.campaign_id,
            entry_id=exc.entry_id,
            expected_revision=exc.expected_revision,
            current_revision=exc.current_revision,
            message=str(exc),
        ) from exc

    view = project_runtime_aggregate(updated_aggregate, controlled_character_ids=(), is_dm=True)
    assert isinstance(view, RuntimeWorldEntryDmView)

    command_payload = {
        k: v for k, v in patch.model_dump(mode="json").items() if k in patch.model_fields_set
    }
    mutation = StoredCampaignWorldMutation(
        id=uuid4(),
        campaign_id=campaign_id,
        idempotency_key=idempotency_key,
        action_kind="runtime_entry.update",
        target_id=entry_id,
        command_payload=command_payload,
        result_payload=view.model_dump(mode="json"),
        created_by_actor_kind=actor_kind,
        created_by_actor_id=actor_id,
        created_at=now,
    )
    mutation_repo.insert_in_transaction(connection, mutation)
    return view, updated_aggregate


def _execute_archive_in_transaction(
    connection: Connection,
    *,
    campaign_id: UUID,
    entry_id: UUID,
    expected_revision: int,
    idempotency_key: str,
    actor_kind: str,
    actor_id: UUID | None,
    now: datetime,
    runtime_repo: CampaignRuntimeRepository,
    mutation_repo: CampaignWorldMutationRepository,
) -> tuple[RuntimeWorldEntryDmView, StoredRuntimeWorldEntryAggregate]:
    try:
        archived_aggregate = runtime_repo.archive_entry_in_transaction(
            connection,
            campaign_id,
            entry_id,
            expected_revision=expected_revision,
            archived_at=now,
        )
    except RuntimeWorldEntryNotFoundError:
        raise CampaignRuntimeNotFoundError(
            f"Runtime entry {entry_id} not found in campaign {campaign_id}"
        )
    except RuntimeWorldEntryArchivedError as exc:
        raise CampaignRuntimeArchivedError(
            campaign_id=exc.campaign_id,
            entry_id=exc.entry_id,
            expected_revision=exc.expected_revision,
            current_revision=exc.current_revision,
        ) from exc
    except RuntimeWorldEntryConflictError as exc:
        raise CampaignRuntimeRevisionConflictError(
            campaign_id=exc.campaign_id,
            entry_id=exc.entry_id,
            expected_revision=exc.expected_revision,
            current_revision=exc.current_revision,
            message=str(exc),
        ) from exc

    view = project_runtime_aggregate(archived_aggregate, controlled_character_ids=(), is_dm=True)
    assert isinstance(view, RuntimeWorldEntryDmView)

    command_payload = {"expected_revision": expected_revision}
    mutation = StoredCampaignWorldMutation(
        id=uuid4(),
        campaign_id=campaign_id,
        idempotency_key=idempotency_key,
        action_kind="runtime_entry.archive",
        target_id=entry_id,
        command_payload=command_payload,
        result_payload=view.model_dump(mode="json"),
        created_by_actor_kind=actor_kind,
        created_by_actor_id=actor_id,
        created_at=now,
    )
    mutation_repo.insert_in_transaction(connection, mutation)
    return view, archived_aggregate


def _execute_create_override_in_transaction(
    connection: Connection,
    *,
    room_id: UUID,
    campaign_id: UUID,
    payload: CampaignAdventureOverrideCreate,
    idempotency_key: str,
    actor_kind: str,
    actor_id: UUID | None,
    now: datetime,
    runtime_repo: CampaignRuntimeRepository,
    mutation_repo: CampaignWorldMutationRepository,
    link_repo: CampaignAdventureLinkRepository,
) -> CampaignAdventureOverride:
    row = _get_attached_adventure_entry_source(
        connection,
        room_id=room_id,
        campaign_id=campaign_id,
        adventure_entry_id=payload.adventure_entry_id,
        link_repo=link_repo,
    )

    existing = runtime_repo.get_override_in_transaction(
        connection, campaign_id, payload.adventure_entry_id
    )
    if existing is not None:
        raise CampaignAdventureOverrideAlreadyExistsError(
            f"Override for adventure entry {payload.adventure_entry_id} already exists in campaign {campaign_id}"
        )

    _validate_and_parse_entry_state(row["kind"], row["data_json"], payload.state)

    override_id = uuid4()
    stored_override = StoredCampaignAdventureOverride(
        id=override_id,
        campaign_id=campaign_id,
        adventure_entry_id=payload.adventure_entry_id,
        state_json=deepcopy(payload.state),
        note=payload.note,
        needs_review=payload.needs_review,
        revision=1,
        created_at=now,
        updated_at=now,
    )
    created_override = runtime_repo.create_override_in_transaction(
        connection, stored_override
    )
    domain_override = stored_override_to_domain(created_override)

    mutation = StoredCampaignWorldMutation(
        id=uuid4(),
        campaign_id=campaign_id,
        idempotency_key=idempotency_key,
        action_kind="override.create",
        target_id=payload.adventure_entry_id,
        command_payload=payload.model_dump(mode="json"),
        result_payload=domain_override.model_dump(mode="json"),
        created_by_actor_kind=actor_kind,
        created_by_actor_id=actor_id,
        created_at=now,
    )
    mutation_repo.insert_in_transaction(connection, mutation)
    return domain_override


def _execute_update_override_in_transaction(
    connection: Connection,
    *,
    room_id: UUID,
    campaign_id: UUID,
    adventure_entry_id: UUID,
    patch: CampaignAdventureOverridePatch,
    idempotency_key: str,
    actor_kind: str,
    actor_id: UUID | None,
    now: datetime,
    runtime_repo: CampaignRuntimeRepository,
    mutation_repo: CampaignWorldMutationRepository,
    link_repo: CampaignAdventureLinkRepository,
) -> CampaignAdventureOverride:
    existing_override = runtime_repo.get_override_in_transaction(
        connection, campaign_id, adventure_entry_id
    )
    if existing_override is None:
        raise CampaignRuntimeNotFoundError(
            f"Campaign adventure override for entry {adventure_entry_id} not found in campaign {campaign_id}"
        )
    if (
        existing_override.id != patch.expected_override_id
        or existing_override.revision != patch.expected_revision
    ):
        raise CampaignRuntimeRevisionConflictError(
            campaign_id=campaign_id,
            entry_id=adventure_entry_id,
            expected_revision=patch.expected_revision,
            current_revision=existing_override.revision,
        )

    row = _get_attached_adventure_entry_source(
        connection,
        room_id=room_id,
        campaign_id=campaign_id,
        adventure_entry_id=adventure_entry_id,
        link_repo=link_repo,
    )

    candidate_state = (
        patch.state if "state" in patch.model_fields_set else existing_override.state_json
    )
    candidate_note = (
        patch.note if "note" in patch.model_fields_set else existing_override.note
    )
    candidate_needs_review = (
        patch.needs_review if "needs_review" in patch.model_fields_set else existing_override.needs_review
    )
    assert candidate_state is not None
    assert candidate_needs_review is not None

    _validate_and_parse_entry_state(row["kind"], row["data_json"], candidate_state)

    update_candidate = StoredCampaignAdventureOverrideUpdate(
        expected_override_id=patch.expected_override_id,
        expected_revision=patch.expected_revision,
        state_json=deepcopy(candidate_state),
        note=candidate_note,
        needs_review=candidate_needs_review,
        updated_at=now,
    )
    try:
        updated_stored = runtime_repo.update_override_in_transaction(
            connection, campaign_id, adventure_entry_id, update_candidate
        )
    except CampaignAdventureOverrideConflictError as exc:
        raise CampaignRuntimeRevisionConflictError(
            campaign_id=exc.campaign_id,
            entry_id=exc.adventure_entry_id,
            expected_revision=exc.expected_revision,
            current_revision=exc.current_revision,
        ) from exc
    except CampaignAdventureOverrideNotFoundError as exc:
        raise CampaignRuntimeNotFoundError(str(exc)) from exc

    domain_override = stored_override_to_domain(updated_stored)

    command_payload = {
        k: v for k, v in patch.model_dump(mode="json").items() if k in patch.model_fields_set
    }
    mutation = StoredCampaignWorldMutation(
        id=uuid4(),
        campaign_id=campaign_id,
        idempotency_key=idempotency_key,
        action_kind="override.update",
        target_id=adventure_entry_id,
        command_payload=command_payload,
        result_payload=domain_override.model_dump(mode="json"),
        created_by_actor_kind=actor_kind,
        created_by_actor_id=actor_id,
        created_at=now,
    )
    mutation_repo.insert_in_transaction(connection, mutation)
    return domain_override


def _execute_clear_override_in_transaction(
    connection: Connection,
    *,
    campaign_id: UUID,
    adventure_entry_id: UUID,
    expected_override_id: UUID,
    expected_revision: int,
    idempotency_key: str,
    actor_kind: str,
    actor_id: UUID | None,
    now: datetime,
    runtime_repo: CampaignRuntimeRepository,
    mutation_repo: CampaignWorldMutationRepository,
) -> CampaignAdventureOverride:
    try:
        deleted_stored = runtime_repo.delete_override_in_transaction(
            connection,
            campaign_id,
            adventure_entry_id,
            expected_override_id,
            expected_revision,
        )
    except CampaignAdventureOverrideNotFoundError as exc:
        raise CampaignRuntimeNotFoundError(str(exc)) from exc
    except CampaignAdventureOverrideConflictError as exc:
        raise CampaignRuntimeRevisionConflictError(
            campaign_id=exc.campaign_id,
            entry_id=exc.adventure_entry_id,
            expected_revision=exc.expected_revision,
            current_revision=exc.current_revision,
        ) from exc

    domain_override = stored_override_to_domain(deleted_stored)

    command_payload = {
        "expected_override_id": str(expected_override_id),
        "expected_revision": expected_revision,
    }
    mutation = StoredCampaignWorldMutation(
        id=uuid4(),
        campaign_id=campaign_id,
        idempotency_key=idempotency_key,
        action_kind="override.clear",
        target_id=adventure_entry_id,
        command_payload=command_payload,
        result_payload=domain_override.model_dump(mode="json"),
        created_by_actor_kind=actor_kind,
        created_by_actor_id=actor_id,
        created_at=now,
    )
    mutation_repo.insert_in_transaction(connection, mutation)
    return domain_override


def _context_event_envelope(
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


def _validate_context_references(
    connection: Connection,
    *,
    room_id: UUID,
    campaign_id: UUID,
    adventure_scene_entry_id: UUID | None,
    runtime_scene_entry_id: UUID | None,
    runtime_repo: CampaignRuntimeRepository,
    link_repo: CampaignAdventureLinkRepository,
) -> None:
    if adventure_scene_entry_id is not None:
        row = connection.execute(
            select(
                adventure_entries.c.id,
                adventure_entries.c.kind,
                adventure_definitions.c.room_id,
            )
            .join(
                adventure_definitions,
                adventure_definitions.c.id == adventure_entries.c.adventure_id,
            )
            .where(adventure_entries.c.id == adventure_scene_entry_id)
        ).mappings().one_or_none()

        if row is None or row["room_id"] != room_id:
            raise CampaignRuntimeNotFoundError(
                f"Adventure entry {adventure_scene_entry_id} not found in room {room_id}"
            )
        if row["kind"] != "scene":
            raise CampaignRuntimeValidationError(
                f"Adventure entry {adventure_scene_entry_id} is not a scene (kind='{row['kind']}')"
            )
        if not link_repo.is_adventure_entry_attached_in_transaction(
            connection, campaign_id, adventure_scene_entry_id
        ):
            raise CampaignRuntimeValidationError(
                f"Adventure entry {adventure_scene_entry_id} is not from an adventure attached to campaign {campaign_id}"
            )

    if runtime_scene_entry_id is not None:
        aggregate = runtime_repo.get_entry_in_transaction(
            connection, campaign_id, runtime_scene_entry_id, include_archived=True
        )
        if aggregate is None:
            raise CampaignRuntimeNotFoundError(
                f"Runtime entry {runtime_scene_entry_id} not found in campaign {campaign_id}"
            )
        if aggregate.entry.archived_at is not None:
            raise CampaignRuntimeValidationError(
                f"Runtime scene entry {runtime_scene_entry_id} is archived"
            )
        if aggregate.entry.kind != "scene":
            raise CampaignRuntimeValidationError(
                f"Runtime entry {runtime_scene_entry_id} is not a scene (kind='{aggregate.entry.kind}')"
            )


def _execute_update_context_in_transaction(
    connection: Connection,
    *,
    room_id: UUID,
    campaign_id: UUID,
    patch: CampaignRuntimeContextPatch,
    idempotency_key: str,
    actor_kind: str,
    actor_id: UUID | None,
    now: datetime,
    runtime_repo: CampaignRuntimeRepository,
    mutation_repo: CampaignWorldMutationRepository,
    link_repo: CampaignAdventureLinkRepository,
) -> CampaignRuntimeContext:
    existing_stored = runtime_repo.get_context_in_transaction(connection, campaign_id)
    cand_adv = (
        patch.current_adventure_scene_entry_id
        if "current_adventure_scene_entry_id" in patch.model_fields_set
        else (existing_stored.current_adventure_scene_entry_id if existing_stored is not None else None)
    )
    cand_rt = (
        patch.current_runtime_scene_entry_id
        if "current_runtime_scene_entry_id" in patch.model_fields_set
        else (existing_stored.current_runtime_scene_entry_id if existing_stored is not None else None)
    )
    cand_sit = (
        patch.current_situation
        if "current_situation" in patch.model_fields_set
        else (existing_stored.current_situation if existing_stored is not None else None)
    )

    if cand_adv is not None and cand_rt is not None:
        raise CampaignRuntimeValidationError(
            "Cannot set both adventure and runtime scene references; clear the other in the same patch"
        )

    _validate_context_references(
        connection,
        room_id=room_id,
        campaign_id=campaign_id,
        adventure_scene_entry_id=cand_adv,
        runtime_scene_entry_id=cand_rt,
        runtime_repo=runtime_repo,
        link_repo=link_repo,
    )

    try:
        updated_stored = runtime_repo.update_context_in_transaction(
            connection,
            campaign_id,
            StoredCampaignRuntimeContextUpdate(
                expected_revision=patch.expected_revision,
                current_adventure_scene_entry_id=cand_adv,
                current_runtime_scene_entry_id=cand_rt,
                current_situation=cand_sit,
                updated_at=now,
            ),
        )
    except CampaignRuntimeContextConflictError as exc:
        raise CampaignRuntimeRevisionConflictError(
            campaign_id=exc.campaign_id,
            entry_id=exc.campaign_id,
            expected_revision=exc.expected_revision,
            current_revision=exc.current_revision,
            message=str(exc),
        ) from exc

    domain_context = _stored_to_context_domain(updated_stored, campaign_id)
    command_payload = {
        k: v for k, v in patch.model_dump(mode="json").items() if k in patch.model_fields_set
    }
    mutation = StoredCampaignWorldMutation(
        id=uuid4(),
        campaign_id=campaign_id,
        idempotency_key=idempotency_key,
        action_kind="context.update",
        target_id=campaign_id,
        command_payload=command_payload,
        result_payload=domain_context.model_dump(mode="json"),
        created_by_actor_kind=actor_kind,
        created_by_actor_id=actor_id,
        created_at=now,
    )
    mutation_repo.insert_in_transaction(connection, mutation)
    return domain_context


def _execute_clear_context_in_transaction(
    connection: Connection,
    *,
    campaign_id: UUID,
    expected_revision: int,
    idempotency_key: str,
    actor_kind: str,
    actor_id: UUID | None,
    now: datetime,
    runtime_repo: CampaignRuntimeRepository,
    mutation_repo: CampaignWorldMutationRepository,
) -> CampaignRuntimeContext:
    try:
        updated_stored = runtime_repo.clear_context_in_transaction(
            connection,
            campaign_id,
            expected_revision=expected_revision,
            updated_at=now,
        )
    except CampaignRuntimeContextConflictError as exc:
        raise CampaignRuntimeRevisionConflictError(
            campaign_id=exc.campaign_id,
            entry_id=exc.campaign_id,
            expected_revision=exc.expected_revision,
            current_revision=exc.current_revision,
            message=str(exc),
        ) from exc

    domain_context = _stored_to_context_domain(updated_stored, campaign_id)
    command_payload = {
        "expected_revision": expected_revision,
    }
    mutation = StoredCampaignWorldMutation(
        id=uuid4(),
        campaign_id=campaign_id,
        idempotency_key=idempotency_key,
        action_kind="context.clear",
        target_id=campaign_id,
        command_payload=command_payload,
        result_payload=domain_context.model_dump(mode="json"),
        created_by_actor_kind=actor_kind,
        created_by_actor_id=actor_id,
        created_at=now,
    )
    mutation_repo.insert_in_transaction(connection, mutation)
    return domain_context


def _session_event_idempotency_key(idempotency_key: str) -> str:
    digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
    return f"p6b-world:{digest}"


def _actor_identity(actor: TableActorContext) -> tuple[str, UUID | None]:
    actor_id = (
        actor.access_session_id
        if actor.actor_kind is TableActorKind.HUMAN
        else actor.ai_controller_grant_id
    )
    return actor.actor_kind.value, actor_id


class CampaignRuntimeService:
    def __init__(
        self,
        engine: Engine,
        event_service: TableEventService,
    ) -> None:
        self.engine = engine
        self.event_service = event_service
        self.runtime_repo = CampaignRuntimeRepository(engine)
        self.mutation_repo = CampaignWorldMutationRepository(engine)
        self.campaign_repo = CampaignRepository(engine)
        self.link_repo = CampaignAdventureLinkRepository(engine)
        self.session_repo = SessionRepository(engine)

    def _require_active_dm_authority(
        self,
        connection: Connection,
        actor: TableActorContext,
        action_verb: str = "write runtime world state",
    ) -> StoredTableActorBinding:
        if not actor.is_current_dm or actor.role != "dm":
            raise CampaignRuntimeAuthorityError(f"Only the current DM may {action_verb}")
        return self._require_active_actor(connection, actor)

    def _require_active_actor(
        self,
        connection: Connection,
        actor: TableActorContext,
    ) -> StoredTableActorBinding:
        try:
            binding = TableEventService._stored_binding(actor)
        except TableEventActorUnauthorizedError as exc:
            raise CampaignRuntimeAuthorityError(str(exc)) from exc
        try:
            return self.event_service.repository.require_active_actor_in_transaction(
                connection, binding
            )
        except TableEventSessionNotFoundPersistenceError as exc:
            raise CampaignRuntimeNotFoundError(f"Session {actor.session_id} not found") from exc
        except TableEventSessionNotActivePersistenceError as exc:
            raise CampaignRuntimeSessionNotActiveError(
                f"Session {actor.session_id} is not active"
            ) from exc
        except TableEventActorBindingStalePersistenceError as exc:
            raise CampaignRuntimeAuthorityError(str(exc)) from exc

    def _orchestrate_management_mutation(
        self,
        *,
        context: RoomAccessContext,
        room_id: UUID,
        campaign_id: UUID,
        action_kind: str,
        target_id: UUID | None,
        command_payload: dict[str, object],
        idempotency_key: str,
        parse_result: Callable[[dict[str, object]], T],
        execute_action: Callable[[Connection, datetime], T],
    ) -> T:
        _require_management_authority(context, room_id)
        _validate_idempotency_key(idempotency_key)

        with self.engine.begin() as connection:
            campaign = self.campaign_repo.get_for_update_in_transaction(
                connection, campaign_id
            )
            if campaign is None or campaign.room_id != room_id:
                raise CampaignRuntimeNotFoundError(
                    f"Campaign {campaign_id} not found in room {room_id}"
                )

            active_session = self.session_repo.active_for_campaign_in_transaction(
                connection, campaign_id
            )
            if active_session is not None:
                raise CampaignRuntimeActiveSessionError(
                    f"Campaign {campaign_id} has an active session; management writes are forbidden during active sessions"
                )

            stored_mutation = self.mutation_repo.get_in_transaction(
                connection, campaign_id, idempotency_key
            )
            if stored_mutation is not None:
                validate_mutation_identity(
                    stored_mutation,
                    action_kind=action_kind,
                    target_id=target_id,
                    command_payload=command_payload,
                    actor_kind="human",
                    actor_id=context.access_session_id,
                )
                return parse_result(stored_mutation.result_payload)

            now = datetime.now(timezone.utc)
            return execute_action(connection, now)

    def create_management(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        campaign_id: UUID,
        payload: RuntimeWorldEntryCreate,
        *,
        idempotency_key: str,
    ) -> RuntimeWorldEntryDmView:
        command_payload = payload.model_dump(mode="json")
        return self._orchestrate_management_mutation(
            context=context,
            room_id=room_id,
            campaign_id=campaign_id,
            action_kind="runtime_entry.create",
            target_id=None,
            command_payload=command_payload,
            idempotency_key=idempotency_key,
            parse_result=RuntimeWorldEntryDmView.model_validate,
            execute_action=lambda conn, now: _execute_create_in_transaction(
                conn,
                room_id=room_id,
                campaign_id=campaign_id,
                payload=payload,
                idempotency_key=idempotency_key,
                actor_kind="human",
                actor_id=context.access_session_id,
                now=now,
                runtime_repo=self.runtime_repo,
                mutation_repo=self.mutation_repo,
                link_repo=self.link_repo,
            )[0],
        )

    def update_management(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        campaign_id: UUID,
        entry_id: UUID,
        patch: RuntimeWorldEntryPatch,
        *,
        idempotency_key: str,
    ) -> RuntimeWorldEntryDmView:
        command_payload = {
            k: v for k, v in patch.model_dump(mode="json").items() if k in patch.model_fields_set
        }
        return self._orchestrate_management_mutation(
            context=context,
            room_id=room_id,
            campaign_id=campaign_id,
            action_kind="runtime_entry.update",
            target_id=entry_id,
            command_payload=command_payload,
            idempotency_key=idempotency_key,
            parse_result=RuntimeWorldEntryDmView.model_validate,
            execute_action=lambda conn, now: _execute_update_in_transaction(
                conn,
                room_id=room_id,
                campaign_id=campaign_id,
                entry_id=entry_id,
                patch=patch,
                idempotency_key=idempotency_key,
                actor_kind="human",
                actor_id=context.access_session_id,
                now=now,
                runtime_repo=self.runtime_repo,
                mutation_repo=self.mutation_repo,
                link_repo=self.link_repo,
            )[0],
        )

    def archive_management(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        campaign_id: UUID,
        entry_id: UUID,
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> RuntimeWorldEntryDmView:
        if expected_revision < 1:
            raise CampaignRuntimeValidationError("expected_revision must be at least 1")
        command_payload = {"expected_revision": expected_revision}
        return self._orchestrate_management_mutation(
            context=context,
            room_id=room_id,
            campaign_id=campaign_id,
            action_kind="runtime_entry.archive",
            target_id=entry_id,
            command_payload=command_payload,
            idempotency_key=idempotency_key,
            parse_result=RuntimeWorldEntryDmView.model_validate,
            execute_action=lambda conn, now: _execute_archive_in_transaction(
                conn,
                campaign_id=campaign_id,
                entry_id=entry_id,
                expected_revision=expected_revision,
                idempotency_key=idempotency_key,
                actor_kind="human",
                actor_id=context.access_session_id,
                now=now,
                runtime_repo=self.runtime_repo,
                mutation_repo=self.mutation_repo,
            )[0],
        )

    def create_override_management(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        campaign_id: UUID,
        payload: CampaignAdventureOverrideCreate,
        *,
        idempotency_key: str,
    ) -> CampaignAdventureOverride:
        command_payload = payload.model_dump(mode="json")
        return self._orchestrate_management_mutation(
            context=context,
            room_id=room_id,
            campaign_id=campaign_id,
            action_kind="override.create",
            target_id=payload.adventure_entry_id,
            command_payload=command_payload,
            idempotency_key=idempotency_key,
            parse_result=CampaignAdventureOverride.model_validate,
            execute_action=lambda conn, now: _execute_create_override_in_transaction(
                conn,
                room_id=room_id,
                campaign_id=campaign_id,
                payload=payload,
                idempotency_key=idempotency_key,
                actor_kind="human",
                actor_id=context.access_session_id,
                now=now,
                runtime_repo=self.runtime_repo,
                mutation_repo=self.mutation_repo,
                link_repo=self.link_repo,
            ),
        )

    def update_override_management(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        campaign_id: UUID,
        adventure_entry_id: UUID,
        patch: CampaignAdventureOverridePatch,
        *,
        idempotency_key: str,
    ) -> CampaignAdventureOverride:
        command_payload = {
            k: v for k, v in patch.model_dump(mode="json").items() if k in patch.model_fields_set
        }
        return self._orchestrate_management_mutation(
            context=context,
            room_id=room_id,
            campaign_id=campaign_id,
            action_kind="override.update",
            target_id=adventure_entry_id,
            command_payload=command_payload,
            idempotency_key=idempotency_key,
            parse_result=CampaignAdventureOverride.model_validate,
            execute_action=lambda conn, now: _execute_update_override_in_transaction(
                conn,
                room_id=room_id,
                campaign_id=campaign_id,
                adventure_entry_id=adventure_entry_id,
                patch=patch,
                idempotency_key=idempotency_key,
                actor_kind="human",
                actor_id=context.access_session_id,
                now=now,
                runtime_repo=self.runtime_repo,
                mutation_repo=self.mutation_repo,
                link_repo=self.link_repo,
            ),
        )

    def clear_override_management(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        campaign_id: UUID,
        adventure_entry_id: UUID,
        *,
        expected_override_id: UUID,
        expected_revision: int,
        idempotency_key: str,
    ) -> CampaignAdventureOverride:
        if expected_revision < 1:
            raise CampaignRuntimeValidationError("expected_revision must be at least 1")
        command_payload = {
            "expected_override_id": str(expected_override_id),
            "expected_revision": expected_revision,
        }
        return self._orchestrate_management_mutation(
            context=context,
            room_id=room_id,
            campaign_id=campaign_id,
            action_kind="override.clear",
            target_id=adventure_entry_id,
            command_payload=command_payload,
            idempotency_key=idempotency_key,
            parse_result=CampaignAdventureOverride.model_validate,
            execute_action=lambda conn, now: _execute_clear_override_in_transaction(
                conn,
                campaign_id=campaign_id,
                adventure_entry_id=adventure_entry_id,
                expected_override_id=expected_override_id,
                expected_revision=expected_revision,
                idempotency_key=idempotency_key,
                actor_kind="human",
                actor_id=context.access_session_id,
                now=now,
                runtime_repo=self.runtime_repo,
                mutation_repo=self.mutation_repo,
            ),
        )

    def update_context_management(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        campaign_id: UUID,
        patch: CampaignRuntimeContextPatch,
        *,
        idempotency_key: str,
    ) -> CampaignRuntimeContext:
        command_payload = {
            k: v for k, v in patch.model_dump(mode="json").items() if k in patch.model_fields_set
        }
        return self._orchestrate_management_mutation(
            context=context,
            room_id=room_id,
            campaign_id=campaign_id,
            action_kind="context.update",
            target_id=campaign_id,
            command_payload=command_payload,
            idempotency_key=idempotency_key,
            parse_result=CampaignRuntimeContext.model_validate,
            execute_action=lambda conn, now: _execute_update_context_in_transaction(
                conn,
                room_id=room_id,
                campaign_id=campaign_id,
                patch=patch,
                idempotency_key=idempotency_key,
                actor_kind="human",
                actor_id=context.access_session_id,
                now=now,
                runtime_repo=self.runtime_repo,
                mutation_repo=self.mutation_repo,
                link_repo=self.link_repo,
            ),
        )

    def clear_context_management(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        campaign_id: UUID,
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> CampaignRuntimeContext:
        if expected_revision < 0:
            raise CampaignRuntimeValidationError("expected_revision must be at least 0")
        command_payload = {
            "expected_revision": expected_revision,
        }
        return self._orchestrate_management_mutation(
            context=context,
            room_id=room_id,
            campaign_id=campaign_id,
            action_kind="context.clear",
            target_id=campaign_id,
            command_payload=command_payload,
            idempotency_key=idempotency_key,
            parse_result=CampaignRuntimeContext.model_validate,
            execute_action=lambda conn, now: _execute_clear_context_in_transaction(
                conn,
                campaign_id=campaign_id,
                expected_revision=expected_revision,
                idempotency_key=idempotency_key,
                actor_kind="human",
                actor_id=context.access_session_id,
                now=now,
                runtime_repo=self.runtime_repo,
                mutation_repo=self.mutation_repo,
            ),
        )

    def _orchestrate_active_mutation(
        self,
        *,
        actor: TableActorContext,
        action_kind: str,
        target_id: UUID | None,
        command_payload: dict[str, object],
        idempotency_key: str,
        event_kind: str,
        parse_result: Callable[[dict[str, object]], T],
        execute_action: Callable[
            [Connection],
            tuple[T, str, Sequence[UUID], dict[str, object]],
        ],
    ) -> T:
        _validate_idempotency_key(idempotency_key)
        actor_kind, actor_id = _actor_identity(actor)

        with self.engine.connect() as connection:
            binding = self._require_active_dm_authority(connection, actor)
            stored_mutation = self.mutation_repo.get_in_transaction(
                connection, actor.campaign_id, idempotency_key
            )
            if stored_mutation is not None:
                validate_mutation_identity(
                    stored_mutation,
                    action_kind=action_kind,
                    target_id=target_id,
                    command_payload=command_payload,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                )
                return parse_result(stored_mutation.result_payload)

        event_key = _session_event_idempotency_key(idempotency_key)
        projection_ran = False
        result_item: T | None = None

        def projection(connection: Connection, event_id: UUID, _seq: int) -> None:
            nonlocal projection_ran, result_item
            self.campaign_repo.get_for_update_in_transaction(
                connection, actor.campaign_id
            )
            item, event_visibility, recipient_seats, event_payload = execute_action(connection)
            self.event_service.repository.update_event_projection_in_transaction(
                connection,
                event_id=event_id,
                visibility=event_visibility,
                recipient_seat_ids=tuple(recipient_seats),
                payload=event_payload,
            )
            projection_ran = True
            result_item = item

        try:
            self.event_service.repository.append(
                room_id=actor.room_id,
                campaign_id=actor.campaign_id,
                session_id=actor.session_id,
                kind=event_kind,
                acting_seat_id=actor.seat_id,
                subject_seat_id=None,
                subject_character_id=None,
                execution_mode="self",
                visibility="public",
                recipient_seat_ids=(),
                payload_version=1,
                payload={},
                idempotency_key=event_key,
                expected_actor_binding=binding,
                transaction_projection=projection,
            )
        except TableEventActorBindingStalePersistenceError as exc:
            raise CampaignRuntimeAuthorityError(str(exc)) from exc
        except TableEventSessionNotFoundPersistenceError as exc:
            raise CampaignRuntimeNotFoundError(str(actor.session_id)) from exc
        except TableEventSessionNotActivePersistenceError as exc:
            raise CampaignRuntimeSessionNotActiveError(str(actor.session_id)) from exc

        if not projection_ran:
            stored_mutation = self.mutation_repo.get(actor.campaign_id, idempotency_key)
            if stored_mutation is None:
                raise CampaignRuntimeIdempotencyConflictError(
                    f"Idempotency key '{idempotency_key}' collision with unrelated session event"
                )
            validate_mutation_identity(
                stored_mutation,
                action_kind=action_kind,
                target_id=target_id,
                command_payload=command_payload,
                actor_kind=actor_kind,
                actor_id=actor_id,
            )
            return parse_result(stored_mutation.result_payload)

        if self.event_service.notifier is not None:
            self.event_service.notifier.notify(actor.session_id)

        assert result_item is not None
        return result_item

    def create_active(
        self,
        actor: TableActorContext,
        payload: RuntimeWorldEntryCreate,
        *,
        idempotency_key: str,
    ) -> RuntimeWorldEntryDmView:
        command_payload = payload.model_dump(mode="json")
        now = datetime.now(timezone.utc)
        actor_kind, actor_id = _actor_identity(actor)

        def execute(
            connection: Connection,
        ) -> tuple[RuntimeWorldEntryDmView, str, tuple[UUID, ...], dict[str, object]]:
            view, aggregate = _execute_create_in_transaction(
                connection,
                room_id=actor.room_id,
                campaign_id=actor.campaign_id,
                payload=payload,
                idempotency_key=idempotency_key,
                actor_kind=actor_kind,
                actor_id=actor_id,
                now=now,
                runtime_repo=self.runtime_repo,
                mutation_repo=self.mutation_repo,
                link_repo=self.link_repo,
            )
            return _runtime_entry_event_envelope(
                connection, actor.session_id, view, aggregate, "created", self.event_service
            )

        return self._orchestrate_active_mutation(
            actor=actor,
            action_kind="runtime_entry.create",
            target_id=None,
            command_payload=command_payload,
            idempotency_key=idempotency_key,
            event_kind="world.entry.created",
            parse_result=RuntimeWorldEntryDmView.model_validate,
            execute_action=execute,
        )

    def update_active(
        self,
        actor: TableActorContext,
        entry_id: UUID,
        patch: RuntimeWorldEntryPatch,
        *,
        idempotency_key: str,
    ) -> RuntimeWorldEntryDmView:
        command_payload = {
            k: v for k, v in patch.model_dump(mode="json").items() if k in patch.model_fields_set
        }
        now = datetime.now(timezone.utc)
        actor_kind, actor_id = _actor_identity(actor)

        def execute(
            connection: Connection,
        ) -> tuple[RuntimeWorldEntryDmView, str, tuple[UUID, ...], dict[str, object]]:
            view, aggregate = _execute_update_in_transaction(
                connection,
                room_id=actor.room_id,
                campaign_id=actor.campaign_id,
                entry_id=entry_id,
                patch=patch,
                idempotency_key=idempotency_key,
                actor_kind=actor_kind,
                actor_id=actor_id,
                now=now,
                runtime_repo=self.runtime_repo,
                mutation_repo=self.mutation_repo,
                link_repo=self.link_repo,
            )
            return _runtime_entry_event_envelope(
                connection, actor.session_id, view, aggregate, "updated", self.event_service
            )

        return self._orchestrate_active_mutation(
            actor=actor,
            action_kind="runtime_entry.update",
            target_id=entry_id,
            command_payload=command_payload,
            idempotency_key=idempotency_key,
            event_kind="world.entry.updated",
            parse_result=RuntimeWorldEntryDmView.model_validate,
            execute_action=execute,
        )

    def archive_active(
        self,
        actor: TableActorContext,
        entry_id: UUID,
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> RuntimeWorldEntryDmView:
        if expected_revision < 1:
            raise CampaignRuntimeValidationError("expected_revision must be at least 1")
        command_payload = {"expected_revision": expected_revision}
        now = datetime.now(timezone.utc)
        actor_kind, actor_id = _actor_identity(actor)

        def execute(
            connection: Connection,
        ) -> tuple[RuntimeWorldEntryDmView, str, tuple[UUID, ...], dict[str, object]]:
            view, aggregate = _execute_archive_in_transaction(
                connection,
                campaign_id=actor.campaign_id,
                entry_id=entry_id,
                expected_revision=expected_revision,
                idempotency_key=idempotency_key,
                actor_kind=actor_kind,
                actor_id=actor_id,
                now=now,
                runtime_repo=self.runtime_repo,
                mutation_repo=self.mutation_repo,
            )
            return _runtime_entry_event_envelope(
                connection, actor.session_id, view, aggregate, "archived", self.event_service
            )

        return self._orchestrate_active_mutation(
            actor=actor,
            action_kind="runtime_entry.archive",
            target_id=entry_id,
            command_payload=command_payload,
            idempotency_key=idempotency_key,
            event_kind="world.entry.archived",
            parse_result=RuntimeWorldEntryDmView.model_validate,
            execute_action=execute,
        )

    def create_override_active(
        self,
        actor: TableActorContext,
        payload: CampaignAdventureOverrideCreate,
        *,
        idempotency_key: str,
    ) -> CampaignAdventureOverride:
        command_payload = payload.model_dump(mode="json")
        now = datetime.now(timezone.utc)
        actor_kind, actor_id = _actor_identity(actor)

        def execute(
            connection: Connection,
        ) -> tuple[CampaignAdventureOverride, str, tuple[UUID, ...], dict[str, object]]:
            override = _execute_create_override_in_transaction(
                connection,
                room_id=actor.room_id,
                campaign_id=actor.campaign_id,
                payload=payload,
                idempotency_key=idempotency_key,
                actor_kind=actor_kind,
                actor_id=actor_id,
                now=now,
                runtime_repo=self.runtime_repo,
                mutation_repo=self.mutation_repo,
                link_repo=self.link_repo,
            )
            return _override_event_envelope(override, "created")

        return self._orchestrate_active_mutation(
            actor=actor,
            action_kind="override.create",
            target_id=payload.adventure_entry_id,
            command_payload=command_payload,
            idempotency_key=idempotency_key,
            event_kind="world.override.created",
            parse_result=CampaignAdventureOverride.model_validate,
            execute_action=execute,
        )

    def update_override_active(
        self,
        actor: TableActorContext,
        adventure_entry_id: UUID,
        patch: CampaignAdventureOverridePatch,
        *,
        idempotency_key: str,
    ) -> CampaignAdventureOverride:
        command_payload = {
            k: v for k, v in patch.model_dump(mode="json").items() if k in patch.model_fields_set
        }
        now = datetime.now(timezone.utc)
        actor_kind, actor_id = _actor_identity(actor)

        def execute(
            connection: Connection,
        ) -> tuple[CampaignAdventureOverride, str, tuple[UUID, ...], dict[str, object]]:
            override = _execute_update_override_in_transaction(
                connection,
                room_id=actor.room_id,
                campaign_id=actor.campaign_id,
                adventure_entry_id=adventure_entry_id,
                patch=patch,
                idempotency_key=idempotency_key,
                actor_kind=actor_kind,
                actor_id=actor_id,
                now=now,
                runtime_repo=self.runtime_repo,
                mutation_repo=self.mutation_repo,
                link_repo=self.link_repo,
            )
            return _override_event_envelope(override, "updated")

        return self._orchestrate_active_mutation(
            actor=actor,
            action_kind="override.update",
            target_id=adventure_entry_id,
            command_payload=command_payload,
            idempotency_key=idempotency_key,
            event_kind="world.override.updated",
            parse_result=CampaignAdventureOverride.model_validate,
            execute_action=execute,
        )

    def clear_override_active(
        self,
        actor: TableActorContext,
        adventure_entry_id: UUID,
        *,
        expected_override_id: UUID,
        expected_revision: int,
        idempotency_key: str,
    ) -> CampaignAdventureOverride:
        if expected_revision < 1:
            raise CampaignRuntimeValidationError("expected_revision must be at least 1")
        command_payload = {
            "expected_override_id": str(expected_override_id),
            "expected_revision": expected_revision,
        }
        now = datetime.now(timezone.utc)
        actor_kind, actor_id = _actor_identity(actor)

        def execute(
            connection: Connection,
        ) -> tuple[CampaignAdventureOverride, str, tuple[UUID, ...], dict[str, object]]:
            override = _execute_clear_override_in_transaction(
                connection,
                campaign_id=actor.campaign_id,
                adventure_entry_id=adventure_entry_id,
                expected_override_id=expected_override_id,
                expected_revision=expected_revision,
                idempotency_key=idempotency_key,
                actor_kind=actor_kind,
                actor_id=actor_id,
                now=now,
                runtime_repo=self.runtime_repo,
                mutation_repo=self.mutation_repo,
            )
            return _override_event_envelope(override, "cleared")

        return self._orchestrate_active_mutation(
            actor=actor,
            action_kind="override.clear",
            target_id=adventure_entry_id,
            command_payload=command_payload,
            idempotency_key=idempotency_key,
            event_kind="world.override.cleared",
            parse_result=CampaignAdventureOverride.model_validate,
            execute_action=execute,
        )

    def update_context_active(
        self,
        actor: TableActorContext,
        patch: CampaignRuntimeContextPatch,
        *,
        idempotency_key: str,
    ) -> CampaignRuntimeContext:
        command_payload = {
            k: v for k, v in patch.model_dump(mode="json").items() if k in patch.model_fields_set
        }
        now = datetime.now(timezone.utc)
        actor_kind, actor_id = _actor_identity(actor)

        def execute(
            connection: Connection,
        ) -> tuple[CampaignRuntimeContext, str, tuple[UUID, ...], dict[str, object]]:
            context = _execute_update_context_in_transaction(
                connection,
                room_id=actor.room_id,
                campaign_id=actor.campaign_id,
                patch=patch,
                idempotency_key=idempotency_key,
                actor_kind=actor_kind,
                actor_id=actor_id,
                now=now,
                runtime_repo=self.runtime_repo,
                mutation_repo=self.mutation_repo,
                link_repo=self.link_repo,
            )
            return _context_event_envelope(context, "updated")

        return self._orchestrate_active_mutation(
            actor=actor,
            action_kind="context.update",
            target_id=actor.campaign_id,
            command_payload=command_payload,
            idempotency_key=idempotency_key,
            event_kind="world.context_changed",
            parse_result=CampaignRuntimeContext.model_validate,
            execute_action=execute,
        )

    def clear_context_active(
        self,
        actor: TableActorContext,
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> CampaignRuntimeContext:
        if expected_revision < 0:
            raise CampaignRuntimeValidationError("expected_revision must be at least 0")
        command_payload = {
            "expected_revision": expected_revision,
        }
        now = datetime.now(timezone.utc)
        actor_kind, actor_id = _actor_identity(actor)

        def execute(
            connection: Connection,
        ) -> tuple[CampaignRuntimeContext, str, tuple[UUID, ...], dict[str, object]]:
            context = _execute_clear_context_in_transaction(
                connection,
                campaign_id=actor.campaign_id,
                expected_revision=expected_revision,
                idempotency_key=idempotency_key,
                actor_kind=actor_kind,
                actor_id=actor_id,
                now=now,
                runtime_repo=self.runtime_repo,
                mutation_repo=self.mutation_repo,
            )
            return _context_event_envelope(context, "cleared")

        return self._orchestrate_active_mutation(
            actor=actor,
            action_kind="context.clear",
            target_id=actor.campaign_id,
            command_payload=command_payload,
            idempotency_key=idempotency_key,
            event_kind="world.context_changed",
            parse_result=CampaignRuntimeContext.model_validate,
            execute_action=execute,
        )

    def get_management(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        campaign_id: UUID,
        entry_id: UUID,
        include_archived: bool = False,
    ) -> RuntimeWorldEntryDmView:
        _require_management_authority(context, room_id)
        with self.engine.connect() as connection:
            campaign = self.campaign_repo.get_in_transaction(connection, campaign_id)
            if campaign is None or campaign.room_id != room_id:
                raise CampaignRuntimeNotFoundError(
                    f"Campaign {campaign_id} not found in room {room_id}"
                )
            aggregate = self.runtime_repo.get_entry_in_transaction(
                connection, campaign_id, entry_id, include_archived=include_archived
            )
            if aggregate is None:
                raise CampaignRuntimeNotFoundError(
                    f"Runtime entry {entry_id} not found in campaign {campaign_id}"
                )
            view = project_runtime_aggregate(aggregate, controlled_character_ids=(), is_dm=True)
            assert isinstance(view, RuntimeWorldEntryDmView)
            return view

    def list_management(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        campaign_id: UUID,
        include_archived: bool = False,
    ) -> tuple[RuntimeWorldEntryDmView, ...]:
        _require_management_authority(context, room_id)
        with self.engine.connect() as connection:
            campaign = self.campaign_repo.get_in_transaction(connection, campaign_id)
            if campaign is None or campaign.room_id != room_id:
                raise CampaignRuntimeNotFoundError(
                    f"Campaign {campaign_id} not found in room {room_id}"
                )
            aggregates = self.runtime_repo.list_entries_in_transaction(
                connection, campaign_id, include_archived=include_archived
            )
            views = project_runtime_aggregates(aggregates, controlled_character_ids=(), is_dm=True)
            return tuple(cast(RuntimeWorldEntryDmView, v) for v in views)

    def get_override_management(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        campaign_id: UUID,
        adventure_entry_id: UUID,
    ) -> CampaignAdventureOverride:
        _require_management_authority(context, room_id)
        with self.engine.connect() as connection:
            campaign = self.campaign_repo.get_in_transaction(connection, campaign_id)
            if campaign is None or campaign.room_id != room_id:
                raise CampaignRuntimeNotFoundError(
                    f"Campaign {campaign_id} not found in room {room_id}"
                )
            stored = self.runtime_repo.get_override_in_transaction(
                connection, campaign_id, adventure_entry_id
            )
            if stored is None:
                raise CampaignRuntimeNotFoundError(
                    f"Campaign adventure override for entry {adventure_entry_id} not found in campaign {campaign_id}"
                )
            return stored_override_to_domain(stored)

    def list_overrides_management(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        campaign_id: UUID,
    ) -> tuple[CampaignAdventureOverride, ...]:
        _require_management_authority(context, room_id)
        with self.engine.connect() as connection:
            campaign = self.campaign_repo.get_in_transaction(connection, campaign_id)
            if campaign is None or campaign.room_id != room_id:
                raise CampaignRuntimeNotFoundError(
                    f"Campaign {campaign_id} not found in room {room_id}"
                )
            stored_list = self.runtime_repo.list_overrides_in_transaction(
                connection, campaign_id
            )
            return tuple(stored_override_to_domain(s) for s in stored_list)

    def get_context_management(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        campaign_id: UUID,
    ) -> CampaignRuntimeContext:
        _require_management_authority(context, room_id)
        with self.engine.connect() as connection:
            campaign = self.campaign_repo.get_in_transaction(connection, campaign_id)
            if campaign is None or campaign.room_id != room_id:
                raise CampaignRuntimeNotFoundError(
                    f"Campaign {campaign_id} not found in room {room_id}"
                )
            stored = self.runtime_repo.get_context_in_transaction(connection, campaign_id)
            return _stored_to_context_domain(stored, campaign_id)

    def get_adventure_entry_overlay_management(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        campaign_id: UUID,
        adventure_entry_id: UUID,
    ) -> CampaignAdventureEntryOverlayView:
        _require_management_authority(context, room_id)
        with self.engine.connect() as connection:
            campaign = self.campaign_repo.get_in_transaction(connection, campaign_id)
            if campaign is None or campaign.room_id != room_id:
                raise CampaignRuntimeNotFoundError(
                    f"Campaign {campaign_id} not found in room {room_id}"
                )
            return _get_adventure_entry_overlay_in_transaction(
                connection,
                room_id=room_id,
                campaign_id=campaign_id,
                adventure_entry_id=adventure_entry_id,
                link_repo=self.link_repo,
                runtime_repo=self.runtime_repo,
            )

    def list_adventure_entry_overlays_management(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        campaign_id: UUID,
        adventure_id: UUID,
    ) -> tuple[CampaignAdventureEntryOverlayView, ...]:
        _require_management_authority(context, room_id)
        with self.engine.connect() as connection:
            campaign = self.campaign_repo.get_in_transaction(connection, campaign_id)
            if campaign is None or campaign.room_id != room_id:
                raise CampaignRuntimeNotFoundError(
                    f"Campaign {campaign_id} not found in room {room_id}"
                )
            return _list_adventure_entry_overlays_in_transaction(
                connection,
                campaign_id=campaign_id,
                adventure_id=adventure_id,
                link_repo=self.link_repo,
                runtime_repo=self.runtime_repo,
            )

    def get_active(
        self,
        actor: TableActorContext,
        entry_id: UUID,
        include_archived: bool = False,
    ) -> RuntimeWorldEntryDmView | RuntimeWorldEntryPlayerView:
        with self.engine.connect() as connection:
            self._require_active_actor(connection, actor)
            campaign = self.campaign_repo.get_in_transaction(connection, actor.campaign_id)
            if campaign is None or campaign.room_id != actor.room_id:
                raise CampaignRuntimeNotFoundError(
                    f"Campaign {actor.campaign_id} not found in room {actor.room_id}"
                )
            aggregate = self.runtime_repo.get_entry_in_transaction(
                connection, actor.campaign_id, entry_id, include_archived=include_archived
            )
            if aggregate is None:
                raise CampaignRuntimeNotFoundError(
                    f"Runtime entry {entry_id} not found in campaign {actor.campaign_id}"
                )
            if actor.is_current_dm:
                view = project_runtime_aggregate(aggregate, controlled_character_ids=(), is_dm=True)
                assert isinstance(view, RuntimeWorldEntryDmView)
                return view

            controlled_char_ids = (
                self.event_service.repository.active_character_ids_for_seats_in_transaction(
                    connection, actor.session_id, actor.controlled_seat_ids
                )
            )
            player_view = project_runtime_aggregate(
                aggregate, controlled_character_ids=controlled_char_ids, is_dm=False
            )
            if player_view is None:
                raise CampaignRuntimeNotFoundError(
                    f"Runtime entry {entry_id} not found in campaign {actor.campaign_id}"
                )
            return player_view

    def list_active(
        self,
        actor: TableActorContext,
        include_archived: bool = False,
    ) -> tuple[RuntimeWorldEntryDmView | RuntimeWorldEntryPlayerView, ...]:
        with self.engine.connect() as connection:
            self._require_active_actor(connection, actor)
            campaign = self.campaign_repo.get_in_transaction(connection, actor.campaign_id)
            if campaign is None or campaign.room_id != actor.room_id:
                raise CampaignRuntimeNotFoundError(
                    f"Campaign {actor.campaign_id} not found in room {actor.room_id}"
                )
            aggregates = self.runtime_repo.list_entries_in_transaction(
                connection, actor.campaign_id, include_archived=include_archived
            )
            if actor.is_current_dm:
                dm_views = project_runtime_aggregates(aggregates, controlled_character_ids=(), is_dm=True)
                return tuple(cast(RuntimeWorldEntryDmView, v) for v in dm_views)

            controlled_char_ids = (
                self.event_service.repository.active_character_ids_for_seats_in_transaction(
                    connection, actor.session_id, actor.controlled_seat_ids
                )
            )
            player_views = project_runtime_aggregates(
                aggregates, controlled_character_ids=controlled_char_ids, is_dm=False
            )
            return player_views

    def get_override_active(
        self,
        actor: TableActorContext,
        adventure_entry_id: UUID,
    ) -> CampaignAdventureOverride:
        with self.engine.connect() as connection:
            self._require_active_dm_authority(
                connection, actor, action_verb="read adventure override"
            )
            campaign = self.campaign_repo.get_in_transaction(connection, actor.campaign_id)
            if campaign is None or campaign.room_id != actor.room_id:
                raise CampaignRuntimeNotFoundError(
                    f"Campaign {actor.campaign_id} not found in room {actor.room_id}"
                )
            stored = self.runtime_repo.get_override_in_transaction(
                connection, actor.campaign_id, adventure_entry_id
            )
            if stored is None:
                raise CampaignRuntimeNotFoundError(
                    f"Campaign adventure override for entry {adventure_entry_id} not found in campaign {actor.campaign_id}"
                )
            return stored_override_to_domain(stored)

    def list_overrides_active(
        self,
        actor: TableActorContext,
    ) -> tuple[CampaignAdventureOverride, ...]:
        with self.engine.connect() as connection:
            self._require_active_dm_authority(
                connection, actor, action_verb="read adventure overrides"
            )
            campaign = self.campaign_repo.get_in_transaction(connection, actor.campaign_id)
            if campaign is None or campaign.room_id != actor.room_id:
                raise CampaignRuntimeNotFoundError(
                    f"Campaign {actor.campaign_id} not found in room {actor.room_id}"
                )
            stored_list = self.runtime_repo.list_overrides_in_transaction(
                connection, actor.campaign_id
            )
            return tuple(stored_override_to_domain(s) for s in stored_list)

    def get_context_active(
        self,
        actor: TableActorContext,
    ) -> CampaignRuntimeContext:
        with self.engine.connect() as connection:
            self._require_active_dm_authority(
                connection, actor, action_verb="read campaign runtime context"
            )
            campaign = self.campaign_repo.get_in_transaction(connection, actor.campaign_id)
            if campaign is None or campaign.room_id != actor.room_id:
                raise CampaignRuntimeNotFoundError(
                    f"Campaign {actor.campaign_id} not found in room {actor.room_id}"
                )
            stored = self.runtime_repo.get_context_in_transaction(connection, actor.campaign_id)
            return _stored_to_context_domain(stored, actor.campaign_id)

    def get_adventure_entry_overlay_active(
        self,
        actor: TableActorContext,
        adventure_entry_id: UUID,
    ) -> CampaignAdventureEntryOverlayView:
        with self.engine.connect() as connection:
            self._require_active_dm_authority(
                connection, actor, action_verb="read adventure entry overlay"
            )
            campaign = self.campaign_repo.get_in_transaction(connection, actor.campaign_id)
            if campaign is None or campaign.room_id != actor.room_id:
                raise CampaignRuntimeNotFoundError(
                    f"Campaign {actor.campaign_id} not found in room {actor.room_id}"
                )
            return _get_adventure_entry_overlay_in_transaction(
                connection,
                room_id=actor.room_id,
                campaign_id=actor.campaign_id,
                adventure_entry_id=adventure_entry_id,
                link_repo=self.link_repo,
                runtime_repo=self.runtime_repo,
            )

    def list_adventure_entry_overlays_active(
        self,
        actor: TableActorContext,
        adventure_id: UUID,
    ) -> tuple[CampaignAdventureEntryOverlayView, ...]:
        with self.engine.connect() as connection:
            self._require_active_dm_authority(
                connection, actor, action_verb="read adventure entry overlays"
            )
            campaign = self.campaign_repo.get_in_transaction(connection, actor.campaign_id)
            if campaign is None or campaign.room_id != actor.room_id:
                raise CampaignRuntimeNotFoundError(
                    f"Campaign {actor.campaign_id} not found in room {actor.room_id}"
                )
            return _list_adventure_entry_overlays_in_transaction(
                connection,
                campaign_id=actor.campaign_id,
                adventure_id=adventure_id,
                link_repo=self.link_repo,
                runtime_repo=self.runtime_repo,
            )


__all__ = [
    "CampaignAdventureEntryOverlayView",
    "CampaignAdventureOverride",
    "CampaignAdventureOverrideAlreadyExistsError",
    "CampaignAdventureOverrideCreate",
    "CampaignAdventureOverridePatch",
    "CampaignRuntimeActiveSessionError",
    "CampaignRuntimeArchivedError",
    "CampaignRuntimeAuthorityError",
    "CampaignRuntimeConflictError",
    "CampaignRuntimeContext",
    "CampaignRuntimeContextPatch",
    "CampaignRuntimeIdempotencyConflictError",
    "CampaignRuntimeNotFoundError",
    "CampaignRuntimeRevisionConflictError",
    "CampaignRuntimeService",
    "CampaignRuntimeSessionNotActiveError",
    "CampaignRuntimeValidationError",
    "project_runtime_aggregate",
    "project_runtime_aggregates",
    "stored_aggregate_to_runtime_entry",
    "stored_override_to_domain",
    "validate_mutation_identity",
]
