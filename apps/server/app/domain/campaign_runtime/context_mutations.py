from __future__ import annotations

from datetime import datetime
from uuid import (
    UUID,
    uuid4,
)

from sqlalchemy import select
from sqlalchemy.engine import Connection

from app.domain.campaign_runtime.conversion import (
    stored_context_to_domain,
)
from app.domain.campaign_runtime.errors import (
    CampaignRuntimeNotFoundError,
    CampaignRuntimeRevisionConflictError,
    CampaignRuntimeValidationError,
)
from app.domain.campaign_runtime.schemas import (
    CampaignRuntimeContext,
    CampaignRuntimeContextPatch,
)
from app.persistence.adventures.repository import (
    CampaignAdventureLinkRepository,
)
from app.persistence.adventures.tables import (
    adventure_definitions,
    adventure_entries,
)
from app.persistence.campaign_runtime.mutations import (
    CampaignWorldMutationRepository,
    StoredCampaignWorldMutation,
)
from app.persistence.campaign_runtime.repository import (
    CampaignRuntimeContextConflictError,
    CampaignRuntimeRepository,
    StoredCampaignRuntimeContextUpdate,
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


def execute_update_context_in_transaction(
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

    domain_context = stored_context_to_domain(updated_stored, campaign_id)
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


def execute_clear_context_in_transaction(
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

    domain_context = stored_context_to_domain(updated_stored, campaign_id)
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

