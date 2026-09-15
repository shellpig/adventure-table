from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.engine import Engine

from app.domain.character.schemas import CharacterBuild, CharacterState
from app.domain.combat.resolution import (
    DamageRollPart,
    DamageType,
    DeathSaveState,
    HitPointState,
    TargetKind,
    apply_damage,
    apply_healing,
)
from app.domain.rules.hit_points import calculate_max_hp
from app.persistence.characters import character_states, character_versions, characters
from app.persistence.combat.tables import combat_entries, combats, monster_instances
from app.persistence.rooms.table_runtime import (
    StoredTableActorBinding,
    StoredTableEvent,
    TableEventRepository,
    session_events,
)


UNCONSCIOUS_REF = "srd5.1:condition:unconscious"
PRONE_REF = "srd5.1:condition:prone"


class CombatResolutionPersistenceError(RuntimeError):
    pass


class CombatResolutionTargetNotFoundError(LookupError):
    pass


class CombatResolutionStateConflictError(CombatResolutionPersistenceError):
    pass


@dataclass(frozen=True)
class StoredSemanticResolution:
    event_id: UUID
    combat_id: UUID
    target_entry_id: UUID
    kind: str
    before_hp: int
    after_hp: int
    before_temp_hp: int
    after_temp_hp: int
    amount: int
    payload: dict[str, Any]


def _death_state(row: Any) -> DeathSaveState:
    return DeathSaveState(
        successes=int(row["death_save_successes"]),
        failures=int(row["death_save_failures"]),
        stable=bool(row["death_save_stable"]),
        dead=bool(row["death_save_dead"]),
    )


def _death_values(state: DeathSaveState | None) -> dict[str, Any]:
    state = state or DeathSaveState()
    return {
        "death_save_successes": state.successes,
        "death_save_failures": state.failures,
        "death_save_stable": state.stable,
        "death_save_dead": state.dead,
    }


def _condition_ref(item: object) -> str | None:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        value = item.get("condition_ref") or item.get("key") or item.get("name")
        return value if isinstance(value, str) else None
    return None


def _add_condition(items: list[dict[str, Any]], ref: str, note: str) -> None:
    if any(_condition_ref(item) == ref for item in items):
        return
    items.append({"condition_ref": ref, "note": note})


def _remove_condition(items: list[dict[str, Any]], ref: str) -> list[dict[str, Any]]:
    return [item for item in items if _condition_ref(item) != ref]


def _normalized_damage_type(value: object) -> DamageType | None:
    if isinstance(value, dict):
        for key in ("key", "index", "name"):
            if key in value:
                return _normalized_damage_type(value[key])
        return None
    if not isinstance(value, str):
        return None
    candidate = value.strip().casefold()
    if candidate.count(":") == 2:
        candidate = candidate.rsplit(":", 1)[-1]
    candidate = candidate.removesuffix(" damage").replace("_", "-")
    try:
        return DamageType(candidate)
    except ValueError:
        return None


def _damage_affinities(rules: dict[str, Any]) -> tuple[tuple[DamageType, ...], tuple[DamageType, ...], tuple[DamageType, ...]]:
    def values(key: str) -> tuple[DamageType, ...]:
        raw = rules.get(key, [])
        if not isinstance(raw, list):
            return ()
        parsed = tuple(item for value in raw if (item := _normalized_damage_type(value)) is not None)
        return tuple(dict.fromkeys(parsed))

    return (
        values("damage_resistances"),
        values("damage_immunities"),
        values("damage_vulnerabilities"),
    )


def _resolution_from_event(event: StoredTableEvent) -> StoredSemanticResolution:
    payload = dict(event.payload)
    return StoredSemanticResolution(
        event_id=event.id,
        combat_id=UUID(str(payload["combat_id"])),
        target_entry_id=UUID(str(payload["target_entry_id"])),
        kind=str(payload["kind"]),
        before_hp=int(payload["before"]["current_hp"]),
        after_hp=int(payload["after"]["current_hp"]),
        before_temp_hp=int(payload["before"]["temp_hp"]),
        after_temp_hp=int(payload["after"]["temp_hp"]),
        amount=int(payload["amount"]),
        payload=payload,
    )


class CombatResolutionRepository:
    """P4-C semantic HP mutations on the P3/P4 durable event transaction."""

    def __init__(self, engine: Engine, event_repository: TableEventRepository) -> None:
        self.engine = engine
        self.event_repository = event_repository

    @staticmethod
    def _lock_combat_and_target(connection, *, binding: StoredTableActorBinding, combat_id: UUID, target_entry_id: UUID):
        combat = connection.execute(
            select(combats)
            .where(
                combats.c.id == combat_id,
                combats.c.campaign_id == binding.campaign_id,
            )
            .with_for_update()
        ).mappings().one_or_none()
        target = connection.execute(
            select(combat_entries)
            .where(
                combat_entries.c.id == target_entry_id,
                combat_entries.c.combat_id == combat_id,
            )
            .with_for_update()
        ).mappings().one_or_none()
        if combat is None or target is None:
            raise CombatResolutionTargetNotFoundError(str(target_entry_id))
        if combat["status"] != "running" or target["status"] != "active":
            raise CombatResolutionStateConflictError("semantic HP resolution requires an active target in running Combat")
        return combat, target

    @staticmethod
    def _character_state(connection, character_id: UUID) -> tuple[CharacterState, int]:
        row = connection.execute(
            select(
                character_states.c.state_payload,
                character_versions.c.build_payload,
            )
            .select_from(
                character_states.join(characters, characters.c.id == character_states.c.character_id).join(
                    character_versions,
                    character_versions.c.id == characters.c.current_version_id,
                )
            )
            .where(character_states.c.character_id == character_id)
            .with_for_update()
        ).mappings().one_or_none()
        if row is None:
            raise CombatResolutionTargetNotFoundError(str(character_id))
        state = CharacterState.model_validate(row["state_payload"])
        build = CharacterBuild.model_validate(row["build_payload"])
        return state, calculate_max_hp(build)

    @staticmethod
    def _monster_state(connection, monster_instance_id: UUID):
        row = connection.execute(
            select(monster_instances)
            .where(monster_instances.c.id == monster_instance_id)
            .with_for_update()
        ).mappings().one_or_none()
        if row is None:
            raise CombatResolutionTargetNotFoundError(str(monster_instance_id))
        return row

    def apply_damage(
        self,
        *,
        binding: StoredTableActorBinding,
        combat_id: UUID,
        target_entry_id: UUID,
        damage_parts: Iterable[DamageRollPart],
        critical: bool,
        source_entry_id: UUID | None,
        subject_seat_id: UUID | None,
        execution_mode: str,
        idempotency_key: str | None,
    ) -> StoredSemanticResolution:
        parts = tuple(damage_parts)
        if not parts:
            raise ValueError("damage requires at least one damage part")

        def projection(connection, event_id: UUID, _seq: int) -> None:
            _combat, target = self._lock_combat_and_target(
                connection,
                binding=binding,
                combat_id=combat_id,
                target_entry_id=target_entry_id,
            )
            now = datetime.now().astimezone()
            if target["subject_kind"] == "character":
                if target["character_id"] is None:
                    raise CombatResolutionStateConflictError("Character target has no Character identity")
                state, max_hp = self._character_state(connection, target["character_id"])
                before = HitPointState(
                    current_hp=state.current_hp,
                    max_hp=max_hp,
                    temp_hp=state.temporary_hp,
                )
                outcome = apply_damage(
                    before,
                    parts,
                    target_kind=TargetKind.CHARACTER,
                    critical=critical,
                    death_saves=_death_state(target),
                    zero_hp_failure_count=2 if critical else 1,
                )
                state_payload = state.model_dump(mode="json")
                state_payload["current_hp"] = outcome.after.current_hp
                state_payload["temporary_hp"] = outcome.after.temp_hp
                conditions = list(state_payload.get("conditions", []))
                if outcome.apply_unconscious:
                    _add_condition(conditions, UNCONSCIOUS_REF, "P4-C: zero hit points")
                if outcome.apply_prone:
                    _add_condition(conditions, PRONE_REF, "P4-C: dropped to zero hit points")
                state_payload["conditions"] = conditions
                CharacterState.model_validate(state_payload)
                connection.execute(
                    update(character_states)
                    .where(character_states.c.character_id == target["character_id"])
                    .values(
                        state_payload=state_payload,
                        state_revision=character_states.c.state_revision + 1,
                        updated_at=func.now(),
                    )
                )
                connection.execute(
                    update(combat_entries)
                    .where(combat_entries.c.id == target_entry_id)
                    .values(**_death_values(outcome.death_saves), updated_at=now)
                )
                resistances: tuple[DamageType, ...] = ()
                immunities: tuple[DamageType, ...] = ()
                vulnerabilities: tuple[DamageType, ...] = ()
            elif target["subject_kind"] == "monster":
                if target["monster_instance_id"] is None:
                    raise CombatResolutionStateConflictError("Monster target has no Monster Instance identity")
                monster = self._monster_state(connection, target["monster_instance_id"])
                rules = dict(monster["rules_snapshot"] or {})
                max_hp = int(rules["max_hp"])
                before = HitPointState(
                    current_hp=int(monster["current_hp"]),
                    max_hp=max_hp,
                    temp_hp=int(monster["temp_hp"]),
                )
                resistances, immunities, vulnerabilities = _damage_affinities(rules)
                outcome = apply_damage(
                    before,
                    parts,
                    target_kind=TargetKind.MONSTER,
                    critical=critical,
                    resistances=resistances,
                    immunities=immunities,
                    vulnerabilities=vulnerabilities,
                )
                connection.execute(
                    update(monster_instances)
                    .where(monster_instances.c.id == target["monster_instance_id"])
                    .values(
                        current_hp=outcome.after.current_hp,
                        temp_hp=outcome.after.temp_hp,
                        updated_at=now,
                    )
                )
            else:
                raise CombatResolutionStateConflictError("unsupported CombatEntry subject kind")

            payload = {
                "combat_id": str(combat_id),
                "target_entry_id": str(target_entry_id),
                "source_entry_id": str(source_entry_id) if source_entry_id else None,
                "kind": "damage",
                "critical": critical,
                "amount": outcome.adjusted_total,
                "before": {
                    "current_hp": outcome.before.current_hp,
                    "max_hp": outcome.before.max_hp,
                    "temp_hp": outcome.before.temp_hp,
                },
                "after": {
                    "current_hp": outcome.after.current_hp,
                    "max_hp": outcome.after.max_hp,
                    "temp_hp": outcome.after.temp_hp,
                },
                "raw_by_type": dict(outcome.raw_by_type),
                "adjusted_by_type": dict(outcome.adjusted_by_type),
                "temp_hp_absorbed": outcome.temp_hp_absorbed,
                "hp_lost": outcome.hp_lost,
                "dropped_to_zero": outcome.dropped_to_zero,
                "instant_death": outcome.instant_death,
                "monster_outcome_required": outcome.monster_outcome_required,
                "death_saves": (
                    {
                        "successes": outcome.death_saves.successes,
                        "failures": outcome.death_saves.failures,
                        "stable": outcome.death_saves.stable,
                        "dead": outcome.death_saves.dead,
                    }
                    if outcome.death_saves is not None
                    else None
                ),
                "affinities": {
                    "resistances": [item.value for item in resistances],
                    "immunities": [item.value for item in immunities],
                    "vulnerabilities": [item.value for item in vulnerabilities],
                },
            }
            connection.execute(
                update(session_events)
                .where(session_events.c.id == event_id)
                .values(subject_character_id=target["character_id"], payload=payload)
            )
            connection.execute(
                update(combats)
                .where(combats.c.id == combat_id)
                .values(revision=combats.c.revision + 1, updated_at=now)
            )

        event = self.event_repository.append(
            room_id=binding.room_id,
            campaign_id=binding.campaign_id,
            session_id=binding.session_id,
            kind="combat.damage_applied",
            acting_seat_id=binding.seat_id,
            subject_seat_id=subject_seat_id,
            subject_character_id=None,
            execution_mode=execution_mode,
            visibility="public",
            recipient_seat_ids=(),
            payload_version=1,
            payload={
                "combat_id": str(combat_id),
                "target_entry_id": str(target_entry_id),
                "kind": "damage",
            },
            idempotency_key=f"p4c-damage:{idempotency_key}" if idempotency_key else None,
            expected_actor_binding=binding,
            transaction_projection=projection,
        )
        return _resolution_from_event(event)

    def apply_healing(
        self,
        *,
        binding: StoredTableActorBinding,
        combat_id: UUID,
        target_entry_id: UUID,
        amount: int,
        source_entry_id: UUID | None,
        subject_seat_id: UUID | None,
        execution_mode: str,
        idempotency_key: str | None,
    ) -> StoredSemanticResolution:
        if amount < 0:
            raise ValueError("healing amount cannot be negative")

        def projection(connection, event_id: UUID, _seq: int) -> None:
            _combat, target = self._lock_combat_and_target(
                connection,
                binding=binding,
                combat_id=combat_id,
                target_entry_id=target_entry_id,
            )
            now = datetime.now().astimezone()
            if target["subject_kind"] == "character":
                if target["character_id"] is None:
                    raise CombatResolutionStateConflictError("Character target has no Character identity")
                state, max_hp = self._character_state(connection, target["character_id"])
                before = HitPointState(state.current_hp, max_hp, state.temporary_hp)
                outcome = apply_healing(
                    before,
                    amount,
                    target_kind=TargetKind.CHARACTER,
                    death_saves=_death_state(target),
                )
                state_payload = state.model_dump(mode="json")
                state_payload["current_hp"] = outcome.after.current_hp
                if outcome.remove_unconscious:
                    state_payload["conditions"] = _remove_condition(
                        list(state_payload.get("conditions", [])),
                        UNCONSCIOUS_REF,
                    )
                CharacterState.model_validate(state_payload)
                connection.execute(
                    update(character_states)
                    .where(character_states.c.character_id == target["character_id"])
                    .values(
                        state_payload=state_payload,
                        state_revision=character_states.c.state_revision + 1,
                        updated_at=func.now(),
                    )
                )
                connection.execute(
                    update(combat_entries)
                    .where(combat_entries.c.id == target_entry_id)
                    .values(**_death_values(outcome.death_saves), updated_at=now)
                )
            elif target["subject_kind"] == "monster":
                if target["monster_instance_id"] is None:
                    raise CombatResolutionStateConflictError("Monster target has no Monster Instance identity")
                monster = self._monster_state(connection, target["monster_instance_id"])
                rules = dict(monster["rules_snapshot"] or {})
                before = HitPointState(
                    int(monster["current_hp"]),
                    int(rules["max_hp"]),
                    int(monster["temp_hp"]),
                )
                outcome = apply_healing(before, amount, target_kind=TargetKind.MONSTER)
                connection.execute(
                    update(monster_instances)
                    .where(monster_instances.c.id == target["monster_instance_id"])
                    .values(current_hp=outcome.after.current_hp, updated_at=now)
                )
            else:
                raise CombatResolutionStateConflictError("unsupported CombatEntry subject kind")

            payload = {
                "combat_id": str(combat_id),
                "target_entry_id": str(target_entry_id),
                "source_entry_id": str(source_entry_id) if source_entry_id else None,
                "kind": "healing",
                "amount": outcome.restored,
                "requested_amount": amount,
                "before": {
                    "current_hp": outcome.before.current_hp,
                    "max_hp": outcome.before.max_hp,
                    "temp_hp": outcome.before.temp_hp,
                },
                "after": {
                    "current_hp": outcome.after.current_hp,
                    "max_hp": outcome.after.max_hp,
                    "temp_hp": outcome.after.temp_hp,
                },
                "remove_unconscious": outcome.remove_unconscious,
                "keep_prone": outcome.keep_prone,
            }
            connection.execute(
                update(session_events)
                .where(session_events.c.id == event_id)
                .values(subject_character_id=target["character_id"], payload=payload)
            )
            connection.execute(
                update(combats)
                .where(combats.c.id == combat_id)
                .values(revision=combats.c.revision + 1, updated_at=now)
            )

        event = self.event_repository.append(
            room_id=binding.room_id,
            campaign_id=binding.campaign_id,
            session_id=binding.session_id,
            kind="combat.healing_applied",
            acting_seat_id=binding.seat_id,
            subject_seat_id=subject_seat_id,
            subject_character_id=None,
            execution_mode=execution_mode,
            visibility="public",
            recipient_seat_ids=(),
            payload_version=1,
            payload={
                "combat_id": str(combat_id),
                "target_entry_id": str(target_entry_id),
                "kind": "healing",
            },
            idempotency_key=f"p4c-healing:{idempotency_key}" if idempotency_key else None,
            expected_actor_binding=binding,
            transaction_projection=projection,
        )
        return _resolution_from_event(event)


__all__ = [
    "CombatResolutionPersistenceError",
    "CombatResolutionRepository",
    "CombatResolutionStateConflictError",
    "CombatResolutionTargetNotFoundError",
    "PRONE_REF",
    "StoredSemanticResolution",
    "UNCONSCIOUS_REF",
]
