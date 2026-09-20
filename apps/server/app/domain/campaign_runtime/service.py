from __future__ import annotations

import hashlib
from collections.abc import Callable, Collection, Sequence
from copy import deepcopy
from datetime import datetime, timezone
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy.engine import Connection, Engine

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
from app.persistence.rooms.campaigns import CampaignRepository
from app.persistence.rooms.sessions import SessionRepository
from app.persistence.rooms.table_runtime import (
    StoredTableActorBinding,
    TableEventActorBindingStalePersistenceError,
    TableEventSessionNotActivePersistenceError,
    TableEventSessionNotFoundPersistenceError,
)


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


def validate_mutation_identity(
    stored: StoredCampaignWorldMutation,
    *,
    action_kind: str,
    target_id: UUID | None,
    command_payload: dict[str, object],
    actor_kind: str,
    actor_id: UUID | None,
) -> None:
    if action_kind == "runtime_entry.create":
        target_matches = stored.target_id is not None
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
    ) -> StoredTableActorBinding:
        if not actor.is_current_dm or actor.role != "dm":
            raise CampaignRuntimeAuthorityError("Only the current DM may write runtime world state")
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

    def create_management(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        campaign_id: UUID,
        payload: RuntimeWorldEntryCreate,
        *,
        idempotency_key: str,
    ) -> RuntimeWorldEntryDmView:
        _require_management_authority(context, room_id)
        _validate_idempotency_key(idempotency_key)
        command_payload = payload.model_dump(mode="json")

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
                    action_kind="runtime_entry.create",
                    target_id=None,
                    command_payload=command_payload,
                    actor_kind="human",
                    actor_id=context.access_session_id,
                )
                return RuntimeWorldEntryDmView.model_validate(stored_mutation.result_payload)

            now = datetime.now(timezone.utc)
            view, _ = _execute_create_in_transaction(
                connection,
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
            )
            return view

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
        _require_management_authority(context, room_id)
        _validate_idempotency_key(idempotency_key)
        command_payload = {
            k: v for k, v in patch.model_dump(mode="json").items() if k in patch.model_fields_set
        }

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
                    action_kind="runtime_entry.update",
                    target_id=entry_id,
                    command_payload=command_payload,
                    actor_kind="human",
                    actor_id=context.access_session_id,
                )
                return RuntimeWorldEntryDmView.model_validate(stored_mutation.result_payload)

            now = datetime.now(timezone.utc)
            view, _ = _execute_update_in_transaction(
                connection,
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
            )
            return view

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
        _require_management_authority(context, room_id)
        _validate_idempotency_key(idempotency_key)
        if expected_revision < 1:
            raise CampaignRuntimeValidationError("expected_revision must be at least 1")
        command_payload = {"expected_revision": expected_revision}

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
                    action_kind="runtime_entry.archive",
                    target_id=entry_id,
                    command_payload=command_payload,
                    actor_kind="human",
                    actor_id=context.access_session_id,
                )
                return RuntimeWorldEntryDmView.model_validate(stored_mutation.result_payload)

            now = datetime.now(timezone.utc)
            view, _ = _execute_archive_in_transaction(
                connection,
                campaign_id=campaign_id,
                entry_id=entry_id,
                expected_revision=expected_revision,
                idempotency_key=idempotency_key,
                actor_kind="human",
                actor_id=context.access_session_id,
                now=now,
                runtime_repo=self.runtime_repo,
                mutation_repo=self.mutation_repo,
            )
            return view

    def _orchestrate_active_mutation(
        self,
        *,
        actor: TableActorContext,
        action_kind: str,
        target_id: UUID | None,
        command_payload: dict[str, object],
        idempotency_key: str,
        event_kind: str,
        action_name: str,
        execute_action: Callable[
            [Connection],
            tuple[RuntimeWorldEntryDmView, StoredRuntimeWorldEntryAggregate],
        ],
    ) -> RuntimeWorldEntryDmView:
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
                return RuntimeWorldEntryDmView.model_validate(stored_mutation.result_payload)

        event_key = _session_event_idempotency_key(idempotency_key)
        projection_ran = False
        result_view: RuntimeWorldEntryDmView | None = None

        def projection(connection: Connection, event_id: UUID, _seq: int) -> None:
            nonlocal projection_ran, result_view
            view, aggregate = execute_action(connection)
            if aggregate.entry.visibility == "character":
                recipient_seats = (
                    self.event_service.repository.active_session_seats_for_characters_in_transaction(
                        connection,
                        actor.session_id,
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

            self.event_service.repository.update_event_projection_in_transaction(
                connection,
                event_id=event_id,
                visibility=event_visibility,
                recipient_seat_ids=recipient_seats,
                payload={
                    "entry_id": str(aggregate.entry.id),
                    "entry_kind": str(aggregate.entry.kind),
                    "revision": int(aggregate.entry.revision),
                    "action": action_name,
                },
            )
            projection_ran = True
            result_view = view

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
            return RuntimeWorldEntryDmView.model_validate(stored_mutation.result_payload)

        if self.event_service.notifier is not None:
            self.event_service.notifier.notify(actor.session_id)

        assert result_view is not None
        return result_view

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

        def execute(connection: Connection) -> tuple[RuntimeWorldEntryDmView, StoredRuntimeWorldEntryAggregate]:
            return _execute_create_in_transaction(
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

        return self._orchestrate_active_mutation(
            actor=actor,
            action_kind="runtime_entry.create",
            target_id=None,
            command_payload=command_payload,
            idempotency_key=idempotency_key,
            event_kind="world.entry.created",
            action_name="created",
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

        def execute(connection: Connection) -> tuple[RuntimeWorldEntryDmView, StoredRuntimeWorldEntryAggregate]:
            return _execute_update_in_transaction(
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

        return self._orchestrate_active_mutation(
            actor=actor,
            action_kind="runtime_entry.update",
            target_id=entry_id,
            command_payload=command_payload,
            idempotency_key=idempotency_key,
            event_kind="world.entry.updated",
            action_name="updated",
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

        def execute(connection: Connection) -> tuple[RuntimeWorldEntryDmView, StoredRuntimeWorldEntryAggregate]:
            return _execute_archive_in_transaction(
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

        return self._orchestrate_active_mutation(
            actor=actor,
            action_kind="runtime_entry.archive",
            target_id=entry_id,
            command_payload=command_payload,
            idempotency_key=idempotency_key,
            event_kind="world.entry.archived",
            action_name="archived",
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


__all__ = [
    "CampaignRuntimeActiveSessionError",
    "CampaignRuntimeArchivedError",
    "CampaignRuntimeAuthorityError",
    "CampaignRuntimeConflictError",
    "CampaignRuntimeIdempotencyConflictError",
    "CampaignRuntimeNotFoundError",
    "CampaignRuntimeRevisionConflictError",
    "CampaignRuntimeService",
    "CampaignRuntimeSessionNotActiveError",
    "CampaignRuntimeValidationError",
    "project_runtime_aggregate",
    "project_runtime_aggregates",
    "stored_aggregate_to_runtime_entry",
    "validate_mutation_identity",
]
