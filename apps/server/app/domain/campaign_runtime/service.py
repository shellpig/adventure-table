from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from typing import TypeVar, cast
from uuid import UUID

from sqlalchemy.engine import Connection, Engine

from app.domain.campaign_runtime.adventure_overlay import (
    get_adventure_entry_overlay_in_transaction,
    list_adventure_entry_overlays_in_transaction,
)
from app.domain.campaign_runtime.context_mutations import (
    execute_clear_context_in_transaction,
    execute_update_context_in_transaction,
)
from app.domain.campaign_runtime.conversion import (
    project_runtime_aggregate,
    project_runtime_aggregates,
    stored_context_to_domain,
    stored_override_to_domain,
)
from app.domain.campaign_runtime.entry_mutations import (
    execute_archive_entry_in_transaction,
    execute_create_entry_in_transaction,
    execute_update_entry_in_transaction,
    require_management_authority,
    validate_idempotency_key,
    validate_mutation_identity,
)
from app.domain.campaign_runtime.errors import (
    CampaignRuntimeActiveSessionError,
    CampaignRuntimeAuthorityError,
    CampaignRuntimeIdempotencyConflictError,
    CampaignRuntimeNotFoundError,
    CampaignRuntimeSessionNotActiveError,
    CampaignRuntimeValidationError,
)
from app.domain.campaign_runtime.events import (
    actor_identity,
    context_event_envelope,
    override_event_envelope,
    runtime_entry_event_envelope,
    session_event_idempotency_key,
)
from app.domain.campaign_runtime.override_mutations import (
    execute_clear_override_in_transaction,
    execute_create_override_in_transaction,
    execute_update_override_in_transaction,
)
from app.domain.campaign_runtime.schemas import (
    CampaignAdventureEntryOverlayView,
    CampaignAdventureOverride,
    CampaignAdventureOverrideCreate,
    CampaignAdventureOverridePatch,
    CampaignRuntimeContext,
    CampaignRuntimeContextPatch,
    RuntimeWorldEntryCreate,
    RuntimeWorldEntryDmView,
    RuntimeWorldEntryPatch,
    RuntimeWorldEntryPlayerView,
)
from app.domain.rooms.schemas import RoomAccessContext
from app.domain.rooms.table_events import (
    TableActorContext,
    TableEventActorUnauthorizedError,
    TableEventService,
)
from app.persistence.adventures.repository import CampaignAdventureLinkRepository
from app.persistence.campaign_runtime.mutations import (
    CampaignWorldMutationRepository,
)
from app.persistence.campaign_runtime.repository import (
    CampaignRuntimeRepository,
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
        require_management_authority(context, room_id)
        validate_idempotency_key(idempotency_key)

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
            execute_action=lambda conn, now: execute_create_entry_in_transaction(
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
            execute_action=lambda conn, now: execute_update_entry_in_transaction(
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
            execute_action=lambda conn, now: execute_archive_entry_in_transaction(
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
            execute_action=lambda conn, now: execute_create_override_in_transaction(
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
            execute_action=lambda conn, now: execute_update_override_in_transaction(
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
            execute_action=lambda conn, now: execute_clear_override_in_transaction(
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
            execute_action=lambda conn, now: execute_update_context_in_transaction(
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
            execute_action=lambda conn, now: execute_clear_context_in_transaction(
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
        validate_idempotency_key(idempotency_key)
        actor_kind, actor_id = actor_identity(actor)

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

        event_key = session_event_idempotency_key(idempotency_key)
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
        actor_kind, actor_id = actor_identity(actor)

        def execute(
            connection: Connection,
        ) -> tuple[RuntimeWorldEntryDmView, str, tuple[UUID, ...], dict[str, object]]:
            view, aggregate = execute_create_entry_in_transaction(
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
            return runtime_entry_event_envelope(
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
        actor_kind, actor_id = actor_identity(actor)

        def execute(
            connection: Connection,
        ) -> tuple[RuntimeWorldEntryDmView, str, tuple[UUID, ...], dict[str, object]]:
            view, aggregate = execute_update_entry_in_transaction(
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
            return runtime_entry_event_envelope(
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
        actor_kind, actor_id = actor_identity(actor)

        def execute(
            connection: Connection,
        ) -> tuple[RuntimeWorldEntryDmView, str, tuple[UUID, ...], dict[str, object]]:
            view, aggregate = execute_archive_entry_in_transaction(
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
            return runtime_entry_event_envelope(
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
        actor_kind, actor_id = actor_identity(actor)

        def execute(
            connection: Connection,
        ) -> tuple[CampaignAdventureOverride, str, tuple[UUID, ...], dict[str, object]]:
            override = execute_create_override_in_transaction(
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
            return override_event_envelope(override, "created")

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
        actor_kind, actor_id = actor_identity(actor)

        def execute(
            connection: Connection,
        ) -> tuple[CampaignAdventureOverride, str, tuple[UUID, ...], dict[str, object]]:
            override = execute_update_override_in_transaction(
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
            return override_event_envelope(override, "updated")

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
        actor_kind, actor_id = actor_identity(actor)

        def execute(
            connection: Connection,
        ) -> tuple[CampaignAdventureOverride, str, tuple[UUID, ...], dict[str, object]]:
            override = execute_clear_override_in_transaction(
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
            return override_event_envelope(override, "cleared")

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
        actor_kind, actor_id = actor_identity(actor)

        def execute(
            connection: Connection,
        ) -> tuple[CampaignRuntimeContext, str, tuple[UUID, ...], dict[str, object]]:
            context = execute_update_context_in_transaction(
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
            return context_event_envelope(context, "updated")

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
        actor_kind, actor_id = actor_identity(actor)

        def execute(
            connection: Connection,
        ) -> tuple[CampaignRuntimeContext, str, tuple[UUID, ...], dict[str, object]]:
            context = execute_clear_context_in_transaction(
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
            return context_event_envelope(context, "cleared")

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
        require_management_authority(context, room_id)
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
        require_management_authority(context, room_id)
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
        require_management_authority(context, room_id)
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
        require_management_authority(context, room_id)
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
        require_management_authority(context, room_id)
        with self.engine.connect() as connection:
            campaign = self.campaign_repo.get_in_transaction(connection, campaign_id)
            if campaign is None or campaign.room_id != room_id:
                raise CampaignRuntimeNotFoundError(
                    f"Campaign {campaign_id} not found in room {room_id}"
                )
            stored = self.runtime_repo.get_context_in_transaction(connection, campaign_id)
            return stored_context_to_domain(stored, campaign_id)

    def get_adventure_entry_overlay_management(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        campaign_id: UUID,
        adventure_entry_id: UUID,
    ) -> CampaignAdventureEntryOverlayView:
        require_management_authority(context, room_id)
        with self.engine.connect() as connection:
            campaign = self.campaign_repo.get_in_transaction(connection, campaign_id)
            if campaign is None or campaign.room_id != room_id:
                raise CampaignRuntimeNotFoundError(
                    f"Campaign {campaign_id} not found in room {room_id}"
                )
            return get_adventure_entry_overlay_in_transaction(
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
        require_management_authority(context, room_id)
        with self.engine.connect() as connection:
            campaign = self.campaign_repo.get_in_transaction(connection, campaign_id)
            if campaign is None or campaign.room_id != room_id:
                raise CampaignRuntimeNotFoundError(
                    f"Campaign {campaign_id} not found in room {room_id}"
                )
            return list_adventure_entry_overlays_in_transaction(
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
            return stored_context_to_domain(stored, actor.campaign_id)

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
            return get_adventure_entry_overlay_in_transaction(
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
            return list_adventure_entry_overlays_in_transaction(
                connection,
                campaign_id=actor.campaign_id,
                adventure_id=adventure_id,
                link_repo=self.link_repo,
                runtime_repo=self.runtime_repo,
            )
