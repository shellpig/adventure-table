from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from uuid import (
    UUID,
    uuid4,
)

from sqlalchemy.engine import Connection

from app.domain.campaign_runtime.adventure_overlay import (
    get_attached_adventure_entry_source,
    validate_and_parse_entry_state,
)
from app.domain.campaign_runtime.conversion import (
    stored_override_to_domain,
)
from app.domain.campaign_runtime.errors import (
    CampaignRuntimeNotFoundError,
    CampaignRuntimeRevisionConflictError,
)
from app.domain.campaign_runtime.schemas import (
    CampaignAdventureOverride,
    CampaignAdventureOverrideAlreadyExistsError,
    CampaignAdventureOverrideCreate,
    CampaignAdventureOverridePatch,
)
from app.persistence.adventures.repository import (
    CampaignAdventureLinkRepository,
)
from app.persistence.campaign_runtime.mutations import (
    CampaignWorldMutationRepository,
    StoredCampaignWorldMutation,
)
from app.persistence.campaign_runtime.repository import (
    CampaignAdventureOverrideConflictError,
    CampaignAdventureOverrideNotFoundError,
    CampaignRuntimeRepository,
    StoredCampaignAdventureOverride,
    StoredCampaignAdventureOverrideUpdate,
)


def execute_create_override_in_transaction(
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
    row = get_attached_adventure_entry_source(
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

    validate_and_parse_entry_state(row["kind"], row["data_json"], payload.state)

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


def execute_update_override_in_transaction(
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

    row = get_attached_adventure_entry_source(
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

    validate_and_parse_entry_state(row["kind"], row["data_json"], candidate_state)

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


def execute_clear_override_in_transaction(
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

