from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
from datetime import datetime
from typing import cast
from uuid import (
    UUID,
    uuid4,
)

from sqlalchemy.engine import Connection

from app.domain.campaign_runtime.conversion import (
    project_runtime_aggregate,
)
from app.domain.campaign_runtime.errors import (
    CampaignRuntimeArchivedError,
    CampaignRuntimeAuthorityError,
    CampaignRuntimeIdempotencyConflictError,
    CampaignRuntimeNotFoundError,
    CampaignRuntimeRevisionConflictError,
    CampaignRuntimeValidationError,
)
from app.domain.campaign_runtime.payloads import (
    RuntimeEntryKind,
    RuntimeItemPayload,
    RuntimeStatePayload,
    RuntimeVisibility,
    dump_runtime_payload,
    parse_runtime_payload,
)
from app.domain.campaign_runtime.schemas import (
    RuntimeWorldEntryCreate,
    RuntimeWorldEntryDmView,
    RuntimeWorldEntryPatch,
    validate_entry_quick_add_minima,
    validate_runtime_visibility_recipients,
)
from app.domain.rooms.schemas import (
    RoomAccessAuthority,
    RoomAccessContext,
)
from app.persistence.adventures.repository import (
    CampaignAdventureLinkRepository,
)
from app.persistence.campaign_runtime.mutations import (
    CampaignWorldMutationRepository,
    StoredCampaignWorldMutation,
)
from app.persistence.campaign_runtime.repository import (
    CampaignRuntimeRepository,
    RuntimeWorldEntryArchivedError,
    RuntimeWorldEntryConflictError,
    RuntimeWorldEntryNotFoundError,
    StoredRuntimeWorldEntry,
    StoredRuntimeWorldEntryAggregate,
    StoredRuntimeWorldEntryUpdate,
)
from app.persistence.rooms.campaigns import (
    CampaignRepository,
)


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


def require_management_authority(context: RoomAccessContext, room_id: UUID) -> None:
    if context.room_id != room_id:
        raise CampaignRuntimeNotFoundError(f"Room {room_id} not found")
    if context.authority is RoomAccessAuthority.MEMBER:
        raise CampaignRuntimeAuthorityError("Owner or DM authority is required")
    if context.authority not in (RoomAccessAuthority.OWNER, RoomAccessAuthority.DM):
        raise CampaignRuntimeAuthorityError("Owner or DM authority is required")


def validate_idempotency_key(idempotency_key: str) -> None:
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


def execute_create_entry_in_transaction(
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


def execute_update_entry_in_transaction(
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


def execute_archive_entry_in_transaction(
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

