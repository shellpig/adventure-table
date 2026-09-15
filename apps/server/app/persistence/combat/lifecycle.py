from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from app.persistence.characters import characters
from app.persistence.combat.tables import combat_actions, combat_entries, combats
from app.persistence.rooms.table_runtime import (
    StoredTableActorBinding,
    TableEventRepository,
    session_events,
)
from app.persistence.rooms.tables import session_participants, sessions


class CombatPersistenceError(RuntimeError):
    pass


class ActiveCombatExistsPersistenceError(CombatPersistenceError):
    pass


class CombatNotFoundPersistenceError(LookupError):
    pass


class CombatStateConflictPersistenceError(CombatPersistenceError):
    pass


@dataclass(frozen=True)
class NewCombatEntry:
    subject_kind: str
    display_name: str
    character_id: UUID | None = None
    monster_instance_id: UUID | None = None
    attacks_allowed: int = 1
    surprised: bool = False
    initiative_group_key: str | None = None


@dataclass(frozen=True)
class SessionCharacterBinding:
    seat_id: UUID
    character_id: UUID
    character_name: str


@dataclass(frozen=True)
class StoredCombat:
    id: UUID
    campaign_id: UUID
    started_session_id: UUID
    ended_session_id: UUID | None
    mode: str
    status: str
    round_number: int | None
    current_turn_entry_id: UUID | None
    revision: int
    started_at: datetime
    ended_at: datetime | None
    updated_at: datetime


@dataclass(frozen=True)
class StoredCombatEntry:
    id: UUID
    combat_id: UUID
    subject_kind: str
    character_id: UUID | None
    monster_instance_id: UUID | None
    display_name: str
    status: str
    initiative_group_key: str | None
    initiative_roll_request_id: UUID | None
    initiative_roll_result_id: UUID | None
    initiative_total: int | None
    turn_order: int | None
    surprised: bool
    action_available: bool
    bonus_action_available: bool
    reaction_available: bool
    attacks_allowed: int
    attacks_used: int
    ready_state: dict[str, Any]
    pending_reaction_state: dict[str, Any]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class StoredCombatAction:
    id: UUID
    combat_id: UUID
    entry_id: UUID
    session_id: UUID
    acting_seat_id: UUID
    subject_seat_id: UUID | None
    execution_mode: str
    action_kind: str
    economy_cost: str
    payload: dict[str, Any]
    idempotency_key: str | None
    created_at: datetime


def actor_binding(actor) -> StoredTableActorBinding:
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


class CombatRepository:
    """P4-B canonical Combat persistence layered on the P3 durable event transaction."""

    def __init__(self, engine: Engine, event_repository: TableEventRepository) -> None:
        self.engine = engine
        self.event_repository = event_repository

    @staticmethod
    def _combat(row) -> StoredCombat:
        return StoredCombat(
            id=row["id"], campaign_id=row["campaign_id"],
            started_session_id=row["started_session_id"], ended_session_id=row["ended_session_id"],
            mode=row["mode"], status=row["status"], round_number=row["round_number"],
            current_turn_entry_id=row["current_turn_entry_id"], revision=int(row["revision"]),
            started_at=row["started_at"], ended_at=row["ended_at"], updated_at=row["updated_at"],
        )

    @staticmethod
    def _entry(row) -> StoredCombatEntry:
        return StoredCombatEntry(
            id=row["id"], combat_id=row["combat_id"], subject_kind=row["subject_kind"],
            character_id=row["character_id"], monster_instance_id=row["monster_instance_id"],
            display_name=row["display_name"], status=row["status"],
            initiative_group_key=row["initiative_group_key"],
            initiative_roll_request_id=row["initiative_roll_request_id"],
            initiative_roll_result_id=row["initiative_roll_result_id"],
            initiative_total=row["initiative_total"], turn_order=row["turn_order"],
            surprised=bool(row["surprised"]), action_available=bool(row["action_available"]),
            bonus_action_available=bool(row["bonus_action_available"]),
            reaction_available=bool(row["reaction_available"]),
            attacks_allowed=int(row["attacks_allowed"]), attacks_used=int(row["attacks_used"]),
            ready_state=dict(row["ready_state"] or {}),
            pending_reaction_state=dict(row["pending_reaction_state"] or {}),
            created_at=row["created_at"], updated_at=row["updated_at"],
        )

    @staticmethod
    def _action(row) -> StoredCombatAction:
        return StoredCombatAction(
            id=row["id"], combat_id=row["combat_id"], entry_id=row["entry_id"],
            session_id=row["session_id"], acting_seat_id=row["acting_seat_id"],
            subject_seat_id=row["subject_seat_id"], execution_mode=row["execution_mode"],
            action_kind=row["action_kind"], economy_cost=row["economy_cost"],
            payload=dict(row["payload"] or {}), idempotency_key=row["idempotency_key"],
            created_at=row["created_at"],
        )

    def get_active(self, campaign_id: UUID) -> StoredCombat | None:
        with self.engine.connect() as connection:
            row = connection.execute(select(combats).where(
                combats.c.campaign_id == campaign_id,
                combats.c.status.in_(("initiative_pending", "running")),
            )).mappings().one_or_none()
        return self._combat(row) if row is not None else None

    def get(self, combat_id: UUID) -> StoredCombat | None:
        with self.engine.connect() as connection:
            row = connection.execute(select(combats).where(combats.c.id == combat_id)).mappings().one_or_none()
        return self._combat(row) if row is not None else None

    def get_entry(self, entry_id: UUID) -> StoredCombatEntry | None:
        with self.engine.connect() as connection:
            row = connection.execute(select(combat_entries).where(combat_entries.c.id == entry_id)).mappings().one_or_none()
        return self._entry(row) if row is not None else None

    def list_entries(self, combat_id: UUID) -> tuple[StoredCombatEntry, ...]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(combat_entries).where(combat_entries.c.combat_id == combat_id).order_by(
                    combat_entries.c.turn_order.asc().nullslast(), combat_entries.c.created_at, combat_entries.c.id
                )
            ).mappings().all()
        return tuple(self._entry(row) for row in rows)

    def has_active_hostile(self, combat_id: UUID) -> bool:
        with self.engine.connect() as connection:
            hostile_id = connection.execute(
                select(combat_entries.c.id).where(
                    combat_entries.c.combat_id == combat_id,
                    combat_entries.c.status == "active",
                    combat_entries.c.is_hostile.is_(True),
                ).limit(1)
            ).scalar_one_or_none()
        return hostile_id is not None

    def entries_for_initiative_request(self, combat_id: UUID, request_id: UUID) -> tuple[StoredCombatEntry, ...]:
        with self.engine.connect() as connection:
            rows = connection.execute(select(combat_entries).where(
                combat_entries.c.combat_id == combat_id,
                combat_entries.c.initiative_roll_request_id == request_id,
            )).mappings().all()
        return tuple(self._entry(row) for row in rows)

    def session_characters(self, *, campaign_id: UUID, session_id: UUID) -> tuple[SessionCharacterBinding, ...]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(session_participants.c.seat_id, session_participants.c.active_character_id, characters.c.name)
                .select_from(session_participants.join(sessions, sessions.c.id == session_participants.c.session_id).join(
                    characters, characters.c.id == session_participants.c.active_character_id
                ))
                .where(
                    sessions.c.id == session_id, sessions.c.campaign_id == campaign_id,
                    sessions.c.status == "active", session_participants.c.role_snapshot == "player",
                    session_participants.c.left_at.is_(None), session_participants.c.active_character_id.is_not(None),
                ).order_by(session_participants.c.joined_at, session_participants.c.id)
            ).mappings().all()
        return tuple(SessionCharacterBinding(
            seat_id=row["seat_id"], character_id=row["active_character_id"], character_name=row["name"]
        ) for row in rows)

    def controlling_seat_for_character(self, *, campaign_id: UUID, session_id: UUID, character_id: UUID) -> UUID | None:
        with self.engine.connect() as connection:
            return connection.execute(
                select(session_participants.c.seat_id).select_from(
                    session_participants.join(sessions, sessions.c.id == session_participants.c.session_id)
                ).where(
                    sessions.c.id == session_id, sessions.c.campaign_id == campaign_id,
                    sessions.c.status == "active", session_participants.c.left_at.is_(None),
                    session_participants.c.active_character_id == character_id,
                )
            ).scalar_one_or_none()

    @staticmethod
    def _insert_entry(connection, combat_id: UUID, entry: NewCombatEntry, *, entry_id: UUID) -> None:
        connection.execute(insert(combat_entries).values(
            id=entry_id, combat_id=combat_id, subject_kind=entry.subject_kind,
            character_id=entry.character_id, monster_instance_id=entry.monster_instance_id,
            display_name=entry.display_name, status="active",
            is_hostile=entry.subject_kind == "monster",
            initiative_group_key=entry.initiative_group_key,
            surprised=entry.surprised, action_available=True, bonus_action_available=True,
            reaction_available=not entry.surprised,
            attacks_allowed=max(1, int(entry.attacks_allowed)), attacks_used=0,
            ready_state={}, pending_reaction_state={},
        ))

    def create_quick_combat(self, *, binding: StoredTableActorBinding, entries: tuple[NewCombatEntry, ...], idempotency_key: str | None):
        combat_id = uuid4()
        entry_ids = tuple(uuid4() for _ in entries)

        def projection(connection, _event_id: UUID, _seq: int) -> None:
            connection.execute(insert(combats).values(
                id=combat_id, campaign_id=binding.campaign_id, started_session_id=binding.session_id,
                mode="quick", status="initiative_pending", revision=1,
            ))
            for entry_id, entry in zip(entry_ids, entries, strict=True):
                self._insert_entry(connection, combat_id, entry, entry_id=entry_id)

        try:
            event = self.event_repository.append(
                room_id=binding.room_id, campaign_id=binding.campaign_id, session_id=binding.session_id,
                kind="combat.started", acting_seat_id=binding.seat_id, subject_seat_id=None,
                subject_character_id=None, execution_mode="self", visibility="public", recipient_seat_ids=(),
                payload_version=1, payload={"combat_id": str(combat_id), "mode": "quick", "entry_ids": [str(v) for v in entry_ids]},
                idempotency_key=f"p4b-combat-start:{idempotency_key}" if idempotency_key else None,
                expected_actor_binding=binding, transaction_projection=projection,
            )
        except IntegrityError as exc:
            if self.get_active(binding.campaign_id) is not None:
                raise ActiveCombatExistsPersistenceError(str(binding.campaign_id)) from exc
            raise
        canonical_id = UUID(str(event.payload["combat_id"]))
        combat = self.get(canonical_id)
        if combat is None:
            raise CombatNotFoundPersistenceError(str(canonical_id))
        return combat, self.list_entries(canonical_id), event

    def add_entry(self, *, binding: StoredTableActorBinding, combat_id: UUID, entry: NewCombatEntry, idempotency_key: str | None):
        entry_id = uuid4()

        def projection(connection, _event_id: UUID, _seq: int) -> None:
            combat = connection.execute(select(combats).where(
                combats.c.id == combat_id, combats.c.campaign_id == binding.campaign_id
            ).with_for_update()).mappings().one_or_none()
            if combat is None:
                raise CombatNotFoundPersistenceError(str(combat_id))
            if combat["status"] == "ended":
                raise CombatStateConflictPersistenceError("ended Combat cannot accept entries")
            self._insert_entry(connection, combat_id, entry, entry_id=entry_id)
            connection.execute(update(combats).where(combats.c.id == combat_id).values(
                revision=combats.c.revision + 1, updated_at=datetime.now().astimezone()
            ))

        try:
            event = self.event_repository.append(
                room_id=binding.room_id, campaign_id=binding.campaign_id, session_id=binding.session_id,
                kind="combat.entry_added", acting_seat_id=binding.seat_id, subject_seat_id=None,
                subject_character_id=entry.character_id, execution_mode="self", visibility="public",
                recipient_seat_ids=(), payload_version=1,
                payload={"combat_id": str(combat_id), "entry_id": str(entry_id), "subject_kind": entry.subject_kind, "display_name": entry.display_name},
                idempotency_key=f"p4b-entry-add:{idempotency_key}" if idempotency_key else None,
                expected_actor_binding=binding, transaction_projection=projection,
            )
        except IntegrityError as exc:
            raise CombatStateConflictPersistenceError("Combatant is already present in this Combat") from exc
        stored = self.get_entry(UUID(str(event.payload["entry_id"])))
        if stored is None:
            raise CombatNotFoundPersistenceError(str(entry_id))
        return stored, event

    def bind_initiative_request(self, *, entry_ids: tuple[UUID, ...], request_id: UUID) -> tuple[StoredCombatEntry, ...]:
        if not entry_ids:
            return ()
        with self.engine.begin() as connection:
            rows = connection.execute(select(combat_entries).where(combat_entries.c.id.in_(entry_ids)).with_for_update()).mappings().all()
            if len(rows) != len(entry_ids):
                raise CombatNotFoundPersistenceError("initiative target entry was not found")
            if any(row["status"] != "active" for row in rows):
                raise CombatStateConflictPersistenceError("inactive entry cannot roll initiative")
            if any(row["initiative_roll_request_id"] not in (None, request_id) for row in rows):
                raise CombatStateConflictPersistenceError("initiative request is already bound")
            connection.execute(update(combat_entries).where(combat_entries.c.id.in_(entry_ids)).values(
                initiative_roll_request_id=request_id, updated_at=datetime.now().astimezone()
            ))
        return tuple(stored for entry_id in entry_ids if (stored := self.get_entry(entry_id)) is not None)

    def record_initiative_result(self, *, entry_ids: tuple[UUID, ...], request_id: UUID, result_id: UUID, total: int):
        if not entry_ids:
            raise CombatStateConflictPersistenceError("initiative result has no Combat entry")
        with self.engine.begin() as connection:
            rows = connection.execute(select(combat_entries).where(combat_entries.c.id.in_(entry_ids)).with_for_update()).mappings().all()
            if len(rows) != len(entry_ids):
                raise CombatNotFoundPersistenceError("initiative entry was not found")
            if any(row["initiative_roll_request_id"] != request_id for row in rows):
                raise CombatStateConflictPersistenceError("initiative result does not match request")
            if any(row["initiative_roll_result_id"] not in (None, result_id) for row in rows):
                raise CombatStateConflictPersistenceError("initiative is already resolved")
            connection.execute(update(combat_entries).where(combat_entries.c.id.in_(entry_ids)).values(
                initiative_roll_result_id=result_id, initiative_total=int(total), updated_at=datetime.now().astimezone()
            ))
        return tuple(stored for entry_id in entry_ids if (stored := self.get_entry(entry_id)) is not None)

    def resolve_initiative_order(self, *, binding: StoredTableActorBinding, combat_id: UUID, ordered_entry_ids: tuple[UUID, ...], idempotency_key: str | None):
        def projection(connection, _event_id: UUID, _seq: int) -> None:
            combat = connection.execute(select(combats).where(
                combats.c.id == combat_id, combats.c.campaign_id == binding.campaign_id
            ).with_for_update()).mappings().one_or_none()
            if combat is None:
                raise CombatNotFoundPersistenceError(str(combat_id))
            if combat["status"] != "initiative_pending":
                raise CombatStateConflictPersistenceError("Combat is not awaiting initiative")
            rows = connection.execute(select(combat_entries).where(
                combat_entries.c.combat_id == combat_id, combat_entries.c.status == "active"
            ).with_for_update()).mappings().all()
            expected = {row["id"] for row in rows}
            if not expected or expected != set(ordered_entry_ids) or len(expected) != len(ordered_entry_ids):
                raise CombatStateConflictPersistenceError("initiative order must contain every active Combat entry exactly once")
            if any(row["initiative_total"] is None for row in rows):
                raise CombatStateConflictPersistenceError("all active entries require initiative")
            by_id = {row["id"]: row for row in rows}
            for index, target_id in enumerate(ordered_entry_ids):
                row = by_id[target_id]
                connection.execute(update(combat_entries).where(combat_entries.c.id == target_id).values(
                    turn_order=index, action_available=True, bonus_action_available=True,
                    reaction_available=not bool(row["surprised"]), attacks_used=0,
                    ready_state={}, pending_reaction_state={}, updated_at=datetime.now().astimezone(),
                ))
            first = ordered_entry_ids[0]
            connection.execute(update(combats).where(combats.c.id == combat_id).values(
                status="running", round_number=1, current_turn_entry_id=first,
                revision=combats.c.revision + 1, updated_at=datetime.now().astimezone(),
            ))

        event = self.event_repository.append(
            room_id=binding.room_id, campaign_id=binding.campaign_id, session_id=binding.session_id,
            kind="combat.initiative_ordered", acting_seat_id=binding.seat_id, subject_seat_id=None,
            subject_character_id=None, execution_mode="self", visibility="public", recipient_seat_ids=(),
            payload_version=1, payload={"combat_id": str(combat_id), "ordered_entry_ids": [str(v) for v in ordered_entry_ids], "round": 1},
            idempotency_key=f"p4b-initiative-order:{idempotency_key}" if idempotency_key else None,
            expected_actor_binding=binding, transaction_projection=projection,
        )
        combat = self.get(UUID(str(event.payload["combat_id"])))
        if combat is None:
            raise CombatNotFoundPersistenceError(str(combat_id))
        return combat, event

    def advance_turn(self, *, binding: StoredTableActorBinding, combat_id: UUID, idempotency_key: str | None):
        def projection(connection, event_id: UUID, _seq: int) -> None:
            combat = connection.execute(select(combats).where(
                combats.c.id == combat_id, combats.c.campaign_id == binding.campaign_id
            ).with_for_update()).mappings().one_or_none()
            if combat is None:
                raise CombatNotFoundPersistenceError(str(combat_id))
            if combat["status"] != "running" or combat["current_turn_entry_id"] is None:
                raise CombatStateConflictPersistenceError("Combat is not running")
            rows = connection.execute(select(combat_entries).where(
                combat_entries.c.combat_id == combat_id, combat_entries.c.status == "active",
                combat_entries.c.turn_order.is_not(None),
            ).order_by(combat_entries.c.turn_order).with_for_update()).mappings().all()
            if not rows:
                raise CombatStateConflictPersistenceError("running Combat has no turn order")
            ids = [row["id"] for row in rows]
            try:
                current_index = ids.index(combat["current_turn_entry_id"])
            except ValueError as exc:
                raise CombatStateConflictPersistenceError("current turn entry is not active") from exc

            current_row = rows[current_index]
            current_was_surprised = bool(current_row["surprised"])
            if current_was_surprised:
                # 5e 2014 surprise ends when that creature's first turn ends. It
                # can react immediately after that turn, even before round 1 ends.
                connection.execute(update(combat_entries).where(
                    combat_entries.c.id == current_row["id"]
                ).values(
                    surprised=False,
                    reaction_available=True,
                    updated_at=datetime.now().astimezone(),
                ))

            next_index = (current_index + 1) % len(ids)
            next_entry_id = ids[next_index]
            round_number = int(combat["round_number"]) + (1 if next_index == 0 else 0)
            next_surprised = bool(rows[next_index]["surprised"])
            if next_entry_id == current_row["id"] and current_was_surprised:
                next_surprised = False
            connection.execute(update(combat_entries).where(combat_entries.c.id == next_entry_id).values(
                action_available=True, bonus_action_available=True,
                reaction_available=not next_surprised,
                attacks_used=0, ready_state={}, pending_reaction_state={}, updated_at=datetime.now().astimezone(),
            ))
            connection.execute(update(combats).where(combats.c.id == combat_id).values(
                round_number=round_number, current_turn_entry_id=next_entry_id,
                revision=combats.c.revision + 1, updated_at=datetime.now().astimezone(),
            ))
            connection.execute(update(session_events).where(session_events.c.id == event_id).values(payload={
                "combat_id": str(combat_id), "round": round_number, "current_turn_entry_id": str(next_entry_id)
            }))

        event = self.event_repository.append(
            room_id=binding.room_id, campaign_id=binding.campaign_id, session_id=binding.session_id,
            kind="combat.turn_advanced", acting_seat_id=binding.seat_id, subject_seat_id=None,
            subject_character_id=None, execution_mode="self", visibility="public", recipient_seat_ids=(),
            payload_version=1, payload={"combat_id": str(combat_id)},
            idempotency_key=f"p4b-turn-advance:{idempotency_key}" if idempotency_key else None,
            expected_actor_binding=binding, transaction_projection=projection,
        )
        combat = self.get(UUID(str(event.payload["combat_id"])))
        if combat is None:
            raise CombatNotFoundPersistenceError(str(combat_id))
        return combat, event

    def consume_action(self, *, binding: StoredTableActorBinding, combat_id: UUID, entry_id: UUID,
                       subject_seat_id: UUID | None, execution_mode: str, action_kind: str,
                       economy_cost: str, payload: dict[str, Any], idempotency_key: str | None,
                       attack_use: bool = False):
        action_id = uuid4()

        def projection(connection, event_id: UUID, _seq: int) -> None:
            combat = connection.execute(select(combats).where(
                combats.c.id == combat_id, combats.c.campaign_id == binding.campaign_id
            ).with_for_update()).mappings().one_or_none()
            entry = connection.execute(select(combat_entries).where(
                combat_entries.c.id == entry_id, combat_entries.c.combat_id == combat_id
            ).with_for_update()).mappings().one_or_none()
            if combat is None or entry is None:
                raise CombatNotFoundPersistenceError(str(combat_id))
            if combat["status"] != "running" or entry["status"] != "active":
                raise CombatStateConflictPersistenceError("Combat entry is not active in a running Combat")
            connection.execute(update(session_events).where(session_events.c.id == event_id).values(
                subject_character_id=entry["character_id"]
            ))
            values: dict[str, Any] = {"updated_at": datetime.now().astimezone()}
            if economy_cost in {"action", "bonus_action"} and combat["current_turn_entry_id"] != entry_id:
                raise CombatStateConflictPersistenceError(f"{economy_cost} can only be used on the entry's current turn")
            if entry["surprised"] and economy_cost in {"action", "bonus_action"}:
                raise CombatStateConflictPersistenceError(
                    "Surprised combatant cannot use an Action or Bonus Action on its first turn"
                )
            if economy_cost == "action":
                if attack_use and int(entry["attacks_used"]) > 0:
                    if int(entry["attacks_used"]) >= int(entry["attacks_allowed"]):
                        raise CombatStateConflictPersistenceError("Extra Attack budget is exhausted")
                else:
                    if not entry["action_available"]:
                        raise CombatStateConflictPersistenceError("Action is already spent")
                    values["action_available"] = False
                if attack_use:
                    if int(entry["attacks_used"]) >= int(entry["attacks_allowed"]):
                        raise CombatStateConflictPersistenceError("Attack budget is exhausted")
                    values["attacks_used"] = int(entry["attacks_used"]) + 1
            elif economy_cost == "bonus_action":
                if not entry["bonus_action_available"]:
                    raise CombatStateConflictPersistenceError("Bonus Action is already spent")
                values["bonus_action_available"] = False
            elif economy_cost == "reaction":
                pending = dict(entry["pending_reaction_state"] or {})
                if not entry["reaction_available"]:
                    raise CombatStateConflictPersistenceError("Reaction is unavailable")
                if not pending.get("open"):
                    raise CombatStateConflictPersistenceError("No reaction window is open")
                values["reaction_available"] = False
                values["pending_reaction_state"] = {}
            elif economy_cost != "none":
                raise CombatStateConflictPersistenceError("unsupported action economy cost")
            if action_kind == "ready":
                values["ready_state"] = dict(payload)
            connection.execute(update(combat_entries).where(combat_entries.c.id == entry_id).values(**values))
            connection.execute(insert(combat_actions).values(
                id=action_id, combat_id=combat_id, entry_id=entry_id, session_id=binding.session_id,
                acting_seat_id=binding.seat_id, subject_seat_id=subject_seat_id, execution_mode=execution_mode,
                action_kind=action_kind, economy_cost=economy_cost, payload=dict(payload), idempotency_key=idempotency_key,
            ))
            connection.execute(update(combats).where(combats.c.id == combat_id).values(
                revision=combats.c.revision + 1, updated_at=datetime.now().astimezone()
            ))

        event = self.event_repository.append(
            room_id=binding.room_id, campaign_id=binding.campaign_id, session_id=binding.session_id,
            kind="combat.action_used", acting_seat_id=binding.seat_id, subject_seat_id=subject_seat_id,
            subject_character_id=None, execution_mode=execution_mode, visibility="public", recipient_seat_ids=(),
            payload_version=1, payload={"combat_id": str(combat_id), "entry_id": str(entry_id), "action_id": str(action_id),
                "action_kind": action_kind, "economy_cost": economy_cost, "intent": dict(payload)},
            idempotency_key=f"p4b-action:{idempotency_key}" if idempotency_key else None,
            expected_actor_binding=binding, transaction_projection=projection,
        )
        canonical_id = UUID(str(event.payload["action_id"]))
        with self.engine.connect() as connection:
            row = connection.execute(select(combat_actions).where(combat_actions.c.id == canonical_id)).mappings().one_or_none()
        if row is None:
            raise CombatNotFoundPersistenceError(str(canonical_id))
        return self._action(row), event

    def set_reaction_window(self, *, binding: StoredTableActorBinding, combat_id: UUID, entry_id: UUID,
                            state: dict[str, Any], idempotency_key: str | None):
        def projection(connection, _event_id: UUID, _seq: int) -> None:
            result = connection.execute(update(combat_entries).where(
                combat_entries.c.id == entry_id, combat_entries.c.combat_id == combat_id,
                combat_entries.c.status == "active",
            ).values(pending_reaction_state=dict(state), updated_at=datetime.now().astimezone()))
            if result.rowcount != 1:
                raise CombatNotFoundPersistenceError(str(entry_id))

        event = self.event_repository.append(
            room_id=binding.room_id, campaign_id=binding.campaign_id, session_id=binding.session_id,
            kind="combat.reaction_window", acting_seat_id=binding.seat_id, subject_seat_id=None,
            subject_character_id=None, execution_mode="self", visibility="public", recipient_seat_ids=(),
            payload_version=1, payload={"combat_id": str(combat_id), "entry_id": str(entry_id), "open": bool(state.get("open"))},
            idempotency_key=f"p4b-reaction-window:{idempotency_key}" if idempotency_key else None,
            expected_actor_binding=binding, transaction_projection=projection,
        )
        stored = self.get_entry(UUID(str(event.payload["entry_id"])))
        if stored is None:
            raise CombatNotFoundPersistenceError(str(entry_id))
        return stored, event

    def _set_entry_status(self, *, binding: StoredTableActorBinding, combat_id: UUID, entry_id: UUID,
                          status: str, event_kind: str, idempotency_prefix: str,
                          idempotency_key: str | None):
        if status not in {"withdrawn", "removed"}:
            raise ValueError("unsupported inactive CombatEntry status")

        def projection(connection, event_id: UUID, _seq: int) -> None:
            combat = connection.execute(select(combats).where(
                combats.c.id == combat_id, combats.c.campaign_id == binding.campaign_id
            ).with_for_update()).mappings().one_or_none()
            if combat is None:
                raise CombatNotFoundPersistenceError(str(combat_id))
            entry = connection.execute(select(combat_entries).where(
                combat_entries.c.id == entry_id, combat_entries.c.combat_id == combat_id
            ).with_for_update()).mappings().one_or_none()
            if entry is None or entry["status"] != "active":
                raise CombatNotFoundPersistenceError(str(entry_id))
            if combat["current_turn_entry_id"] == entry_id and combat["status"] == "running":
                raise CombatStateConflictPersistenceError(
                    f"advance the turn before marking the current turn entry {status}"
                )
            connection.execute(update(session_events).where(session_events.c.id == event_id).values(
                subject_character_id=entry["character_id"]
            ))
            connection.execute(update(combat_entries).where(
                combat_entries.c.id == entry_id
            ).values(
                status=status,
                ready_state={},
                pending_reaction_state={},
                updated_at=datetime.now().astimezone(),
            ))
            connection.execute(update(combats).where(combats.c.id == combat_id).values(
                revision=combats.c.revision + 1, updated_at=datetime.now().astimezone()
            ))

        event = self.event_repository.append(
            room_id=binding.room_id, campaign_id=binding.campaign_id, session_id=binding.session_id,
            kind=event_kind, acting_seat_id=binding.seat_id, subject_seat_id=None,
            subject_character_id=None, execution_mode="self", visibility="public", recipient_seat_ids=(),
            payload_version=1, payload={"combat_id": str(combat_id), "entry_id": str(entry_id), "status": status},
            idempotency_key=f"{idempotency_prefix}:{idempotency_key}" if idempotency_key else None,
            expected_actor_binding=binding, transaction_projection=projection,
        )
        stored = self.get_entry(UUID(str(event.payload["entry_id"])))
        if stored is None:
            raise CombatNotFoundPersistenceError(str(entry_id))
        return stored, event

    def withdraw_entry(self, *, binding: StoredTableActorBinding, combat_id: UUID, entry_id: UUID, idempotency_key: str | None):
        return self._set_entry_status(
            binding=binding,
            combat_id=combat_id,
            entry_id=entry_id,
            status="withdrawn",
            event_kind="combat.entry_withdrawn",
            idempotency_prefix="p4b-entry-withdraw",
            idempotency_key=idempotency_key,
        )

    def remove_entry(self, *, binding: StoredTableActorBinding, combat_id: UUID, entry_id: UUID, idempotency_key: str | None):
        return self._set_entry_status(
            binding=binding,
            combat_id=combat_id,
            entry_id=entry_id,
            status="removed",
            event_kind="combat.entry_removed",
            idempotency_prefix="p4b-entry-remove",
            idempotency_key=idempotency_key,
        )

    def end_combat(self, *, binding: StoredTableActorBinding, combat_id: UUID, idempotency_key: str | None):
        def projection(connection, _event_id: UUID, _seq: int) -> None:
            combat = connection.execute(select(combats).where(
                combats.c.id == combat_id, combats.c.campaign_id == binding.campaign_id
            ).with_for_update()).mappings().one_or_none()
            if combat is None:
                raise CombatNotFoundPersistenceError(str(combat_id))
            if combat["status"] == "ended":
                return
            now = datetime.now().astimezone()
            connection.execute(update(combat_entries).where(combat_entries.c.combat_id == combat_id).values(
                initiative_roll_request_id=None, initiative_roll_result_id=None, initiative_total=None,
                turn_order=None, surprised=False, action_available=True, bonus_action_available=True,
                reaction_available=True, attacks_used=0, ready_state={}, pending_reaction_state={}, updated_at=now,
            ))
            connection.execute(update(combats).where(combats.c.id == combat_id).values(
                ended_session_id=binding.session_id, status="ended", round_number=None,
                current_turn_entry_id=None, ended_at=now, revision=combats.c.revision + 1, updated_at=now,
            ))

        event = self.event_repository.append(
            room_id=binding.room_id, campaign_id=binding.campaign_id, session_id=binding.session_id,
            kind="combat.ended", acting_seat_id=binding.seat_id, subject_seat_id=None,
            subject_character_id=None, execution_mode="self", visibility="public", recipient_seat_ids=(),
            payload_version=1, payload={"combat_id": str(combat_id)},
            idempotency_key=f"p4b-combat-end:{idempotency_key}" if idempotency_key else None,
            expected_actor_binding=binding, transaction_projection=projection,
        )
        combat = self.get(UUID(str(event.payload["combat_id"])))
        if combat is None:
            raise CombatNotFoundPersistenceError(str(combat_id))
        return combat, event


__all__ = [
    "ActiveCombatExistsPersistenceError", "CombatNotFoundPersistenceError", "CombatPersistenceError",
    "CombatRepository", "CombatStateConflictPersistenceError", "NewCombatEntry", "SessionCharacterBinding",
    "StoredCombat", "StoredCombatAction", "StoredCombatEntry", "actor_binding",
]
