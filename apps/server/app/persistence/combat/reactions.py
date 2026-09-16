from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.engine import Engine

from app.domain.combat.reaction_service import ReactionWindow, resolve_reaction
from app.persistence.combat.tables import combat_entries, combats
from app.persistence.rooms.table_runtime import (
    StoredTableActorBinding,
    StoredTableEvent,
    TableEventRepository,
    session_events,
)


class CombatReactionNotFoundError(LookupError):
    pass


class CombatReactionStateConflictError(RuntimeError):
    pass


class CombatReactionRepository:
    """Durable P4-D reaction windows backed by ``combat_entries``.

    Reaction state and the corresponding Session event are mutated through the
    same ``TableEventRepository`` transaction projection.  Reconnect/reload can
    therefore recover the open window directly from ``pending_reaction_state``;
    no in-memory reaction registry is authoritative.
    """

    def __init__(self, engine: Engine, event_repository: TableEventRepository) -> None:
        self.engine = engine
        self.event_repository = event_repository

    def get(self, *, combat_id: UUID, entry_id: UUID) -> ReactionWindow | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(combat_entries.c.pending_reaction_state).where(
                    combat_entries.c.id == entry_id,
                    combat_entries.c.combat_id == combat_id,
                )
            ).mappings().one_or_none()
        if row is None:
            raise CombatReactionNotFoundError(str(entry_id))
        payload = dict(row["pending_reaction_state"] or {})
        return ReactionWindow.from_payload(payload) if payload else None

    @staticmethod
    def _load_scope(connection, *, binding: StoredTableActorBinding, combat_id: UUID, entry_id: UUID):
        combat = connection.execute(
            select(combats)
            .where(
                combats.c.id == combat_id,
                combats.c.campaign_id == binding.campaign_id,
            )
            .with_for_update()
        ).mappings().one_or_none()
        entry = connection.execute(
            select(combat_entries)
            .where(
                combat_entries.c.id == entry_id,
                combat_entries.c.combat_id == combat_id,
            )
            .with_for_update()
        ).mappings().one_or_none()
        if combat is None or entry is None:
            raise CombatReactionNotFoundError(str(entry_id))
        if combat["status"] != "running" or entry["status"] != "active":
            raise CombatReactionStateConflictError(
                "Reaction window requires an active combat entry in a running Combat"
            )
        return combat, entry

    def set_window(
        self,
        *,
        binding: StoredTableActorBinding,
        combat_id: UUID,
        entry_id: UUID,
        window: ReactionWindow,
        idempotency_key: str | None,
        execution_mode: str = "system",
    ) -> tuple[ReactionWindow, StoredTableEvent]:
        if window.entry_id != str(entry_id):
            raise ValueError("reaction window entry_id must match the persisted combat entry")
        if window.session_ref is not None and window.session_ref != str(binding.session_id):
            raise ValueError("reaction window session_ref must match the active Session")
        if window.status != "open":
            raise ValueError("only an open reaction window can be persisted as pending")

        def projection(connection, event_id: UUID, _seq: int) -> None:
            _combat, entry = self._load_scope(
                connection,
                binding=binding,
                combat_id=combat_id,
                entry_id=entry_id,
            )
            pending = dict(entry["pending_reaction_state"] or {})
            if pending:
                current = ReactionWindow.from_payload(pending)
                if current.window_id != window.window_id:
                    raise CombatReactionStateConflictError(
                        "combat entry already has a pending reaction window"
                    )
            now = datetime.now().astimezone()
            connection.execute(
                update(combat_entries)
                .where(combat_entries.c.id == entry_id)
                .values(pending_reaction_state=window.to_payload(), updated_at=now)
            )
            connection.execute(
                update(combats)
                .where(combats.c.id == combat_id)
                .values(revision=combats.c.revision + 1, updated_at=now)
            )
            event_payload = {
                "combat_id": str(combat_id),
                "entry_id": str(entry_id),
                "window_id": window.window_id,
                "kind": window.kind.value,
                "reason": window.reason,
                "source_entry_id": window.source_entry_id,
                "eligible_entry_ids": list(window.eligible),
                "target_entry_id": window.target_entry_id,
                "target_is_hostile": bool(entry["is_hostile"]),
                "safe_payload": dict(window.safe_payload or {}),
                "status": window.status,
            }
            connection.execute(
                update(session_events)
                .where(session_events.c.id == event_id)
                .values(subject_character_id=entry["character_id"], payload=event_payload)
            )

        event = self.event_repository.append(
            room_id=binding.room_id,
            campaign_id=binding.campaign_id,
            session_id=binding.session_id,
            kind="combat.reaction_requested",
            acting_seat_id=binding.seat_id,
            subject_seat_id=None,
            subject_character_id=None,
            execution_mode=execution_mode,
            visibility="public",
            recipient_seat_ids=(),
            payload_version=1,
            payload={
                "combat_id": str(combat_id),
                "entry_id": str(entry_id),
                "window_id": window.window_id,
                "kind": window.kind.value,
                "reason": window.reason,
                "source_entry_id": window.source_entry_id,
                "eligible_entry_ids": list(window.eligible),
                "target_entry_id": window.target_entry_id,
                "safe_payload": dict(window.safe_payload or {}),
                "status": window.status,
            },
            idempotency_key=(
                f"p4d-reaction-open:{idempotency_key}" if idempotency_key else None
            ),
            expected_actor_binding=binding,
            transaction_projection=projection,
        )
        restored = self.get(combat_id=combat_id, entry_id=entry_id)
        if restored is None:
            raise CombatReactionStateConflictError("reaction window was not persisted")
        return restored, event

    def resolve_window(
        self,
        *,
        binding: StoredTableActorBinding,
        combat_id: UUID,
        owner_entry_id: UUID,
        actor_entry_id: UUID,
        accept: bool,
        idempotency_key: str | None,
        execution_mode: str = "self",
    ) -> StoredTableEvent:
        event_payload: dict[str, object] = {
            "combat_id": str(combat_id),
            "entry_id": str(owner_entry_id),
            "actor_entry_id": str(actor_entry_id),
            "accepted": accept,
        }

        def projection(connection, event_id: UUID, _seq: int) -> None:
            _combat, owner = self._load_scope(
                connection,
                binding=binding,
                combat_id=combat_id,
                entry_id=owner_entry_id,
            )
            if actor_entry_id == owner_entry_id:
                actor = owner
            else:
                actor = connection.execute(
                    select(combat_entries)
                    .where(
                        combat_entries.c.id == actor_entry_id,
                        combat_entries.c.combat_id == combat_id,
                    )
                    .with_for_update()
                ).mappings().one_or_none()
                if actor is None or actor["status"] != "active":
                    raise CombatReactionNotFoundError(str(actor_entry_id))

            pending = dict(owner["pending_reaction_state"] or {})
            if not pending:
                raise CombatReactionStateConflictError("combat entry has no pending reaction window")
            window = ReactionWindow.from_payload(pending)
            resolution = resolve_reaction(
                window=window,
                actor_entry_id=str(actor_entry_id),
                reaction_available=bool(actor["reaction_available"]),
                accept=accept,
            )
            now = datetime.now().astimezone()
            connection.execute(
                update(combat_entries)
                .where(combat_entries.c.id == owner_entry_id)
                .values(pending_reaction_state={}, updated_at=now)
            )
            if actor_entry_id != owner_entry_id or resolution.reaction_available != bool(owner["reaction_available"]):
                connection.execute(
                    update(combat_entries)
                    .where(combat_entries.c.id == actor_entry_id)
                    .values(
                        reaction_available=resolution.reaction_available,
                        updated_at=now,
                    )
                )
            event_payload.update(
                {
                    "target_entry_id": str(owner_entry_id),
                    "target_is_hostile": bool(owner["is_hostile"]),
                    "actor_is_hostile": bool(actor["is_hostile"]),
                    "window_id": window.window_id,
                    "kind": window.kind.value,
                    "status": resolution.window.status,
                }
            )
            connection.execute(
                update(combats)
                .where(combats.c.id == combat_id)
                .values(revision=combats.c.revision + 1, updated_at=now)
            )
            connection.execute(
                update(session_events)
                .where(session_events.c.id == event_id)
                .values(
                    subject_character_id=actor["character_id"],
                    payload=event_payload,
                )
            )

        return self.event_repository.append(
            room_id=binding.room_id,
            campaign_id=binding.campaign_id,
            session_id=binding.session_id,
            kind="combat.reaction_resolved",
            acting_seat_id=binding.seat_id,
            subject_seat_id=None,
            subject_character_id=None,
            execution_mode=execution_mode,
            visibility="public",
            recipient_seat_ids=(),
            payload_version=1,
            payload=event_payload,
            idempotency_key=(
                f"p4d-reaction-resolve:{idempotency_key}" if idempotency_key else None
            ),
            expected_actor_binding=binding,
            transaction_projection=projection,
        )


__all__ = [
    "CombatReactionNotFoundError",
    "CombatReactionRepository",
    "CombatReactionStateConflictError",
]
