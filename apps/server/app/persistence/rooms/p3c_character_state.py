from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.engine import Engine

from app.content.registry import ContentRegistry
from app.domain.character.schemas import CharacterState, PersistedCharacter
from app.domain.rooms.table_character_state import TableCharacterStatePatch
from app.domain.rooms.table_events import TableActorContext
from app.persistence.characters import CharacterRepository
from app.persistence.rooms.tables import session_participants
from app.persistence.rooms.table_runtime import (
    StoredTableActorBinding,
    TableEventRepository,
)
from app.persistence.state_mutations import mutate_state_against_version
from app.persistence.transaction_bound import TransactionBoundEngine


class TableCharacterStateSubjectStalePersistenceError(RuntimeError):
    pass


class TableCharacterStateActorUnsupportedPersistenceError(PermissionError):
    pass


def _actor_binding(actor: TableActorContext) -> StoredTableActorBinding:
    return StoredTableActorBinding(
        actor_kind=actor.actor_kind.value,
        room_id=actor.room_id,
        campaign_id=actor.campaign_id,
        session_id=actor.session_id,
        seat_id=actor.seat_id,
        controlled_seat_ids=actor.controlled_seat_ids,
        role=actor.role,
        is_current_dm=actor.is_current_dm,
        access_session_id=actor.access_session_id,
        ai_controller_grant_id=actor.ai_controller_grant_id,
        grant_generation=actor.grant_generation,
    )


class TableCharacterStatePersistence:
    """Commit one legal Current State patch and its table event atomically."""

    def __init__(
        self,
        engine: Engine,
        registry: ContentRegistry,
        event_repository: TableEventRepository,
    ) -> None:
        self.engine = engine
        self.registry = registry
        self.event_repository = event_repository

    def apply_patch(
        self,
        *,
        actor: TableActorContext,
        acting_seat_id: UUID,
        subject_seat_id: UUID,
        subject_character_id: UUID,
        execution_mode: str,
        patch: TableCharacterStatePatch,
    ) -> PersistedCharacter:
        binding = _actor_binding(actor)
        changes = patch.state_changes()

        def projection(connection, _event_id: UUID, _seq: int) -> None:
            subject = connection.execute(
                select(
                    session_participants.c.role_snapshot,
                    session_participants.c.active_character_id,
                )
                .where(
                    session_participants.c.session_id == actor.session_id,
                    session_participants.c.seat_id == subject_seat_id,
                    session_participants.c.left_at.is_(None),
                )
                .with_for_update()
            ).mappings().one_or_none()
            if (
                subject is None
                or subject["role_snapshot"] != "player"
                or subject["active_character_id"] != subject_character_id
            ):
                raise TableCharacterStateSubjectStalePersistenceError(
                    "Table state subject binding is no longer current"
                )

            bound_repository = CharacterRepository(
                TransactionBoundEngine(connection),  # type: ignore[arg-type]
                self.registry,
            )

            def mutate(_build, current_state: CharacterState) -> CharacterState:
                return CharacterState.model_validate(
                    {**current_state.model_dump(mode="python"), **changes}
                )

            mutate_state_against_version(
                bound_repository,
                subject_character_id,
                mutate,
                expected_current_version_id=patch.expected_current_version_id,
            )

        self.event_repository.append(
            room_id=actor.room_id,
            campaign_id=actor.campaign_id,
            session_id=actor.session_id,
            kind="character.state.updated",
            acting_seat_id=acting_seat_id,
            subject_seat_id=subject_seat_id,
            subject_character_id=subject_character_id,
            execution_mode=execution_mode,
            visibility="public",
            recipient_seat_ids=(),
            payload_version=1,
            payload={
                "changed_fields": sorted(changes),
            },
            idempotency_key=(
                f"p3c-state:{patch.idempotency_key}"
                if patch.idempotency_key
                else None
            ),
            expected_actor_binding=binding,
            transaction_projection=projection,
        )
        return CharacterRepository(self.engine, self.registry).load_character(
            subject_character_id
        )


__all__ = [
    "TableCharacterStateActorUnsupportedPersistenceError",
    "TableCharacterStatePersistence",
    "TableCharacterStateSubjectStalePersistenceError",
]
