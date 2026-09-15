from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Engine

from app.domain.character.schemas import CharacterBuild, CharacterState
from app.domain.combat.resolution import (
    AttackKind,
    DamageFormulaPart,
    DamageRollPart,
    DamageType,
    DeathSaveState,
    HitPointState,
    ModifierSource,
    ResolvedAttack,
    RollMode,
    TargetKind,
    apply_damage,
    resolve_attack_roll,
)
from app.domain.rules.hit_points import calculate_max_hp
from app.persistence.characters import character_states, character_versions, characters
from app.persistence.combat.resolution import (
    PRONE_REF,
    UNCONSCIOUS_REF,
    _add_condition,
    _damage_affinities,
    _death_state,
    _death_values,
)
from app.persistence.combat.tables import combat_actions, combat_entries, combats, monster_instances
from app.persistence.rooms.p3c_runtime import roll_groups, roll_requests, roll_results
from app.persistence.rooms.table_runtime import (
    StoredTableActorBinding,
    StoredTableEvent,
    TableEventRepository,
    session_events,
)


class AttackPersistenceError(RuntimeError):
    pass


class AttackRequestNotFoundPersistenceError(LookupError):
    pass


class AttackRequestNotPendingPersistenceError(AttackPersistenceError):
    pass


class AttackStateConflictPersistenceError(AttackPersistenceError):
    pass


@dataclass(frozen=True)
class StoredAttackRequest:
    action_id: UUID
    combat_id: UUID
    attacker_entry_id: UUID
    target_entry_id: UUID
    subject_seat_id: UUID | None
    acting_seat_id: UUID
    execution_mode: str
    roll_request_id: UUID
    source_ref: str
    name: str
    modifier_mode: RollMode
    attack_bonus: int
    target_ac: int
    status: str


@dataclass(frozen=True)
class AttackRollComputation:
    source: str
    formula: str
    raw_dice: tuple[int, ...]
    kept_dice: tuple[int, ...]
    base_modifier: int
    flat_adjustment: int
    total: int


@dataclass(frozen=True)
class StoredAttackResolution:
    action_id: UUID
    roll_request_id: UUID
    roll_result_id: UUID
    attacker_entry_id: UUID
    target_entry_id: UUID
    hit: bool
    critical: bool
    attack_total: int
    target_ac: int
    damage_total: int
    before_hp: int | None
    after_hp: int | None
    resolution_result: dict[str, Any]


AttackRollFactory = Callable[[], AttackRollComputation]
DamageRollFactory = Callable[[ResolvedAttack, bool], tuple[DamageRollPart, ...]]


def _attack_payload(attack: ResolvedAttack) -> dict[str, Any]:
    return {
        "source_ref": attack.source_ref,
        "name": attack.name,
        "attack_bonus": attack.attack_bonus,
        "attack_kind": attack.attack_kind.value,
        "damage_parts": [
            {
                "damage_type": part.damage_type.value,
                "dice_count": part.dice_count,
                "die_size": part.die_size,
                "flat_modifier": part.flat_modifier,
            }
            for part in attack.damage_parts
        ],
        "modifier_sources": [
            {"source": item.source, "value": item.value}
            for item in attack.modifier_sources
        ],
        "notes": list(attack.notes),
    }


def _attack_from_payload(payload: dict[str, Any]) -> ResolvedAttack:
    return ResolvedAttack(
        source_ref=str(payload["source_ref"]),
        name=str(payload["name"]),
        attack_bonus=int(payload["attack_bonus"]),
        attack_kind=AttackKind(str(payload["attack_kind"])),
        damage_parts=tuple(
            DamageFormulaPart(
                damage_type=DamageType(str(item["damage_type"])),
                dice_count=int(item["dice_count"]),
                die_size=int(item["die_size"]),
                flat_modifier=int(item.get("flat_modifier", 0)),
            )
            for item in payload["damage_parts"]
        ),
        modifier_sources=tuple(
            ModifierSource(source=str(item["source"]), value=int(item["value"]))
            for item in payload.get("modifier_sources", [])
        ),
        notes=tuple(str(item) for item in payload.get("notes", [])),
    )


def _request_from_row(row: Any) -> StoredAttackRequest:
    payload = dict(row["payload"] or {})
    attack = dict(payload["resolved_attack"])
    target_entry_id = row["target_entry_id"]
    roll_request_id = row["roll_request_id"]
    if target_entry_id is None or roll_request_id is None:
        raise AttackRequestNotFoundPersistenceError(str(row["id"]))
    return StoredAttackRequest(
        action_id=row["id"],
        combat_id=row["combat_id"],
        attacker_entry_id=row["entry_id"],
        target_entry_id=target_entry_id,
        subject_seat_id=row["subject_seat_id"],
        acting_seat_id=row["acting_seat_id"],
        execution_mode=row["execution_mode"],
        roll_request_id=roll_request_id,
        source_ref=str(attack["source_ref"]),
        name=str(attack["name"]),
        modifier_mode=RollMode(str(payload["modifier_mode"])),
        attack_bonus=int(attack["attack_bonus"]),
        target_ac=int(payload["target_ac"]),
        status=str(row["resolution_status"]),
    )


def _resolution_from_row(row: Any) -> StoredAttackResolution:
    result = dict(row["resolution_result"] or {})
    roll_request_id = row["roll_request_id"]
    roll_result_id = row["roll_result_id"]
    target_entry_id = row["target_entry_id"]
    if roll_request_id is None or roll_result_id is None or target_entry_id is None or not result:
        raise AttackRequestNotPendingPersistenceError("Attack does not have a durable resolution")
    before = result.get("damage", {}).get("before") if isinstance(result.get("damage"), dict) else None
    after = result.get("damage", {}).get("after") if isinstance(result.get("damage"), dict) else None
    return StoredAttackResolution(
        action_id=row["id"],
        roll_request_id=roll_request_id,
        roll_result_id=roll_result_id,
        attacker_entry_id=row["entry_id"],
        target_entry_id=target_entry_id,
        hit=bool(result["attack"]["hit"]),
        critical=bool(result["attack"]["critical"]),
        attack_total=int(result["attack"]["total"]),
        target_ac=int(result["attack"]["target_ac"]),
        damage_total=int(result.get("damage", {}).get("adjusted_total", 0)),
        before_hp=int(before["current_hp"]) if isinstance(before, dict) else None,
        after_hp=int(after["current_hp"]) if isinstance(after, dict) else None,
        resolution_result=result,
    )


class CombatAttackRepository:
    """P4-C attack lifecycle on the canonical formal Roll + Combat event substrate."""

    def __init__(self, engine: Engine, event_repository: TableEventRepository) -> None:
        self.engine = engine
        self.event_repository = event_repository

    def get_request(self, *, session_id: UUID, roll_request_id: UUID) -> StoredAttackRequest | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(combat_actions).where(
                    combat_actions.c.session_id == session_id,
                    combat_actions.c.roll_request_id == roll_request_id,
                    combat_actions.c.action_kind == "attack",
                )
            ).mappings().one_or_none()
        return _request_from_row(row) if row is not None else None

    def get_resolution(self, *, action_id: UUID) -> StoredAttackResolution | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(combat_actions).where(combat_actions.c.id == action_id)
            ).mappings().one_or_none()
        if row is None or row["resolution_status"] != "resolved" or row["roll_result_id"] is None:
            return None
        return _resolution_from_row(row)

    def declare_attack(
        self,
        *,
        binding: StoredTableActorBinding,
        combat_id: UUID,
        attacker_entry_id: UUID,
        target_entry_id: UUID,
        subject_seat_id: UUID | None,
        execution_mode: str,
        attack: ResolvedAttack,
        target_ac: int,
        modifier_mode: RollMode,
        idempotency_key: str | None,
    ) -> tuple[StoredAttackRequest, StoredTableEvent]:
        action_id = uuid4()
        roll_group_id = uuid4()
        roll_request_id = uuid4()
        attack_payload = _attack_payload(attack)

        def projection(connection, event_id: UUID, _seq: int) -> None:
            combat = connection.execute(
                select(combats)
                .where(combats.c.id == combat_id, combats.c.campaign_id == binding.campaign_id)
                .with_for_update()
            ).mappings().one_or_none()
            attacker = connection.execute(
                select(combat_entries)
                .where(
                    combat_entries.c.id == attacker_entry_id,
                    combat_entries.c.combat_id == combat_id,
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
            if combat is None or attacker is None or target is None:
                raise AttackRequestNotFoundPersistenceError(str(combat_id))
            if combat["status"] != "running" or attacker["status"] != "active" or target["status"] != "active":
                raise AttackStateConflictPersistenceError("Attack requires active entries in a running Combat")
            if combat["current_turn_entry_id"] != attacker_entry_id:
                raise AttackStateConflictPersistenceError("Attack action can only be declared on the attacker's current turn")
            if attacker["surprised"]:
                raise AttackStateConflictPersistenceError("Surprised combatant cannot attack on its first turn")

            attacks_used = int(attacker["attacks_used"])
            attacks_allowed = int(attacker["attacks_allowed"])
            values: dict[str, Any] = {"updated_at": datetime.now().astimezone()}
            if attacks_used == 0:
                if not attacker["action_available"]:
                    raise AttackStateConflictPersistenceError("Action is already spent")
                values["action_available"] = False
            elif attacks_used >= attacks_allowed:
                raise AttackStateConflictPersistenceError("Extra Attack budget is exhausted")
            if attacks_used >= attacks_allowed:
                raise AttackStateConflictPersistenceError("Attack budget is exhausted")
            values["attacks_used"] = attacks_used + 1
            connection.execute(
                update(combat_entries).where(combat_entries.c.id == attacker_entry_id).values(**values)
            )

            connection.execute(
                insert(roll_groups).values(
                    id=roll_group_id,
                    session_id=binding.session_id,
                    requested_by_seat_id=binding.seat_id,
                    label=f"Attack: {attack.name}",
                    visibility="public",
                    version=1,
                )
            )
            connection.execute(
                insert(roll_requests).values(
                    id=roll_request_id,
                    session_id=binding.session_id,
                    roll_group_id=roll_group_id,
                    target_seat_id=subject_seat_id,
                    target_character_id=attacker["character_id"],
                    target_combat_entry_id=attacker_entry_id,
                    request_type="other",
                    ability_ref=None,
                    skill_ref=None,
                    dc=None,
                    modifier_mode=modifier_mode.value,
                    flat_adjustment=attack.attack_bonus,
                    visibility="public",
                    status="pending",
                    requested_by_seat_id=binding.seat_id,
                    version=1,
                )
            )
            connection.execute(
                insert(combat_actions).values(
                    id=action_id,
                    combat_id=combat_id,
                    entry_id=attacker_entry_id,
                    target_entry_id=target_entry_id,
                    session_id=binding.session_id,
                    acting_seat_id=binding.seat_id,
                    subject_seat_id=subject_seat_id,
                    execution_mode=execution_mode,
                    action_kind="attack",
                    economy_cost="action",
                    payload={
                        "resolved_attack": attack_payload,
                        "target_ac": target_ac,
                        "modifier_mode": modifier_mode.value,
                    },
                    resolution_status="waiting_for_roll",
                    roll_request_id=roll_request_id,
                    roll_result_id=None,
                    resolution_result=None,
                    idempotency_key=idempotency_key,
                )
            )
            connection.execute(
                update(session_events).where(session_events.c.id == event_id).values(
                    subject_character_id=attacker["character_id"]
                )
            )
            connection.execute(
                update(combats).where(combats.c.id == combat_id).values(
                    revision=combats.c.revision + 1,
                    updated_at=datetime.now().astimezone(),
                )
            )

        event = self.event_repository.append(
            room_id=binding.room_id,
            campaign_id=binding.campaign_id,
            session_id=binding.session_id,
            kind="roll.requested",
            acting_seat_id=binding.seat_id,
            subject_seat_id=subject_seat_id,
            subject_character_id=None,
            execution_mode=execution_mode,
            visibility="public",
            recipient_seat_ids=(subject_seat_id,) if subject_seat_id else (),
            payload_version=1,
            payload={
                "roll_group_id": str(roll_group_id),
                "roll_request_ids": [str(roll_request_id)],
                "roll_request_id": str(roll_request_id),
                "request_type": "attack",
                "modifier_mode": modifier_mode.value,
                "visibility": "public",
                "label": f"Attack: {attack.name}",
                "combat_id": str(combat_id),
                "action_id": str(action_id),
                "attacker_entry_id": str(attacker_entry_id),
                "target_entry_id": str(target_entry_id),
                "source_ref": attack.source_ref,
            },
            idempotency_key=f"p4c-attack-request:{idempotency_key}" if idempotency_key else None,
            expected_actor_binding=binding,
            transaction_projection=projection,
        )
        canonical_request_id = UUID(str(event.payload["roll_request_id"]))
        stored = self.get_request(session_id=binding.session_id, roll_request_id=canonical_request_id)
        if stored is None:
            raise AttackRequestNotFoundPersistenceError(str(canonical_request_id))
        return stored, event

    def complete_attack(
        self,
        *,
        binding: StoredTableActorBinding,
        roll_request_id: UUID,
        acting_seat_id: UUID,
        execution_mode: str,
        roll_factory: AttackRollFactory,
        damage_factory: DamageRollFactory,
        idempotency_key: str | None,
    ) -> tuple[StoredAttackResolution, StoredTableEvent | None]:
        request = self.get_request(session_id=binding.session_id, roll_request_id=roll_request_id)
        if request is None:
            raise AttackRequestNotFoundPersistenceError(str(roll_request_id))
        existing = self.get_resolution(action_id=request.action_id)
        if existing is not None:
            return existing, None

        roll_result_id = uuid4()

        def projection(connection, event_id: UUID, _seq: int) -> None:
            action = connection.execute(
                select(combat_actions)
                .where(
                    combat_actions.c.id == request.action_id,
                    combat_actions.c.roll_request_id == roll_request_id,
                )
                .with_for_update()
            ).mappings().one_or_none()
            roll_request = connection.execute(
                select(roll_requests)
                .where(
                    roll_requests.c.id == roll_request_id,
                    roll_requests.c.session_id == binding.session_id,
                )
                .with_for_update()
            ).mappings().one_or_none()
            if action is None or roll_request is None:
                raise AttackRequestNotFoundPersistenceError(str(roll_request_id))
            if action["resolution_status"] != "waiting_for_roll" or roll_request["status"] != "pending":
                raise AttackRequestNotPendingPersistenceError(str(roll_request_id))

            combat = connection.execute(
                select(combats)
                .where(combats.c.id == action["combat_id"], combats.c.campaign_id == binding.campaign_id)
                .with_for_update()
            ).mappings().one_or_none()
            attacker = connection.execute(
                select(combat_entries)
                .where(combat_entries.c.id == action["entry_id"])
                .with_for_update()
            ).mappings().one_or_none()
            target = connection.execute(
                select(combat_entries)
                .where(combat_entries.c.id == action["target_entry_id"])
                .with_for_update()
            ).mappings().one_or_none()
            if combat is None or attacker is None or target is None:
                raise AttackRequestNotFoundPersistenceError(str(roll_request_id))
            if combat["status"] != "running" or attacker["status"] != "active" or target["status"] != "active":
                raise AttackStateConflictPersistenceError("Attack target/attacker left the active Combat before resolution")

            payload = dict(action["payload"] or {})
            resolved_attack = _attack_from_payload(dict(payload["resolved_attack"]))
            target_ac = int(payload["target_ac"])
            mode = RollMode(str(payload["modifier_mode"]))
            computation = roll_factory()
            attack_outcome = resolve_attack_roll(
                d20_rolls=computation.raw_dice,
                modifier=resolved_attack.attack_bonus,
                target_ac=target_ac,
                mode=mode,
                modifier_sources=resolved_attack.modifier_sources,
            )

            connection.execute(
                insert(roll_results).values(
                    id=roll_result_id,
                    roll_request_id=roll_request_id,
                    session_id=binding.session_id,
                    acting_seat_id=acting_seat_id,
                    subject_seat_id=roll_request["target_seat_id"],
                    subject_character_id=attacker["character_id"],
                    subject_combat_entry_id=attacker["id"],
                    execution_mode=execution_mode,
                    source=computation.source,
                    formula=computation.formula,
                    raw_dice=list(computation.raw_dice),
                    kept_dice=list(computation.kept_dice),
                    base_modifier=computation.base_modifier,
                    flat_adjustment=computation.flat_adjustment,
                    total=computation.total,
                    visibility="public",
                )
            )
            now = datetime.now().astimezone()
            connection.execute(
                update(roll_requests).where(roll_requests.c.id == roll_request_id).values(
                    status="resolved",
                    resolved_at=now,
                    version=roll_requests.c.version + 1,
                )
            )

            damage_result: dict[str, Any] | None = None
            if attack_outcome.hit:
                damage_parts = damage_factory(resolved_attack, attack_outcome.critical)
                if target["subject_kind"] == "character":
                    character_id = target["character_id"]
                    if character_id is None:
                        raise AttackStateConflictPersistenceError("Character target has no Character identity")
                    state_row = connection.execute(
                        select(
                            character_states.c.state_payload,
                            character_states.c.state_revision,
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
                    if state_row is None:
                        raise AttackRequestNotFoundPersistenceError(str(character_id))
                    state = CharacterState.model_validate(state_row["state_payload"])
                    build = CharacterBuild.model_validate(state_row["build_payload"])
                    hp = HitPointState(state.current_hp, calculate_max_hp(build), state.temporary_hp)
                    damage_outcome = apply_damage(
                        hp,
                        damage_parts,
                        target_kind=TargetKind.CHARACTER,
                        critical=attack_outcome.critical,
                        death_saves=_death_state(target),
                        zero_hp_failure_count=2 if attack_outcome.critical else 1,
                    )
                    state_payload = state.model_dump(mode="json")
                    state_payload["current_hp"] = damage_outcome.after.current_hp
                    state_payload["temporary_hp"] = damage_outcome.after.temp_hp
                    conditions = list(state_payload.get("conditions", []))
                    if damage_outcome.apply_unconscious:
                        _add_condition(conditions, UNCONSCIOUS_REF, "P4-C: zero hit points")
                    if damage_outcome.apply_prone:
                        _add_condition(conditions, PRONE_REF, "P4-C: dropped to zero hit points")
                    state_payload["conditions"] = conditions
                    CharacterState.model_validate(state_payload)
                    state_update = connection.execute(
                        update(character_states)
                        .where(
                            character_states.c.character_id == character_id,
                            character_states.c.state_revision == int(state_row["state_revision"]),
                        )
                        .values(
                            state_payload=state_payload,
                            state_revision=int(state_row["state_revision"]) + 1,
                            updated_at=now,
                        )
                    )
                    if state_update.rowcount != 1:
                        raise AttackStateConflictPersistenceError(
                            "Character State changed while resolving Attack damage"
                        )
                    connection.execute(
                        update(combat_entries).where(combat_entries.c.id == target["id"]).values(
                            **_death_values(damage_outcome.death_saves),
                            updated_at=now,
                        )
                    )
                elif target["subject_kind"] == "monster":
                    monster_id = target["monster_instance_id"]
                    if monster_id is None:
                        raise AttackStateConflictPersistenceError("Monster target has no Monster identity")
                    monster = connection.execute(
                        select(monster_instances)
                        .where(monster_instances.c.id == monster_id)
                        .with_for_update()
                    ).mappings().one_or_none()
                    if monster is None:
                        raise AttackRequestNotFoundPersistenceError(str(monster_id))
                    rules = dict(monster["rules_snapshot"] or {})
                    resistances, immunities, vulnerabilities = _damage_affinities(rules)
                    hp = HitPointState(
                        int(monster["current_hp"]),
                        int(rules["max_hp"]),
                        int(monster["temp_hp"]),
                    )
                    damage_outcome = apply_damage(
                        hp,
                        damage_parts,
                        target_kind=TargetKind.MONSTER,
                        critical=attack_outcome.critical,
                        resistances=resistances,
                        immunities=immunities,
                        vulnerabilities=vulnerabilities,
                    )
                    connection.execute(
                        update(monster_instances).where(monster_instances.c.id == monster_id).values(
                            current_hp=damage_outcome.after.current_hp,
                            temp_hp=damage_outcome.after.temp_hp,
                            updated_at=now,
                        )
                    )
                else:
                    raise AttackStateConflictPersistenceError("unsupported CombatEntry target kind")

                damage_result = {
                    "parts": [
                        {
                            "damage_type": part.damage_type.value,
                            "dice": list(part.dice),
                            "critical_dice": list(part.critical_dice),
                            "flat_modifier": part.flat_modifier,
                        }
                        for part in damage_parts
                    ],
                    "raw_by_type": dict(damage_outcome.raw_by_type),
                    "adjusted_by_type": dict(damage_outcome.adjusted_by_type),
                    "raw_total": damage_outcome.raw_total,
                    "adjusted_total": damage_outcome.adjusted_total,
                    "before": {
                        "current_hp": damage_outcome.before.current_hp,
                        "max_hp": damage_outcome.before.max_hp,
                        "temp_hp": damage_outcome.before.temp_hp,
                    },
                    "after": {
                        "current_hp": damage_outcome.after.current_hp,
                        "max_hp": damage_outcome.after.max_hp,
                        "temp_hp": damage_outcome.after.temp_hp,
                    },
                    "temp_hp_absorbed": damage_outcome.temp_hp_absorbed,
                    "dropped_to_zero": damage_outcome.dropped_to_zero,
                    "instant_death": damage_outcome.instant_death,
                    "monster_outcome_required": damage_outcome.monster_outcome_required,
                }

            resolution_result = {
                "attack": {
                    "source_ref": resolved_attack.source_ref,
                    "name": resolved_attack.name,
                    "modifier_mode": mode.value,
                    "raw_d20": list(attack_outcome.raw_d20),
                    "selected_d20": attack_outcome.selected_d20,
                    "modifier": attack_outcome.modifier,
                    "modifier_sources": [
                        {"source": item.source, "value": item.value}
                        for item in attack_outcome.modifier_sources
                    ],
                    "total": attack_outcome.total,
                    "target_ac": attack_outcome.target_ac,
                    "hit": attack_outcome.hit,
                    "critical": attack_outcome.critical,
                    "automatic": attack_outcome.automatic,
                },
                "damage": damage_result,
            }
            connection.execute(
                update(combat_actions).where(combat_actions.c.id == action["id"]).values(
                    resolution_status="resolved",
                    roll_result_id=roll_result_id,
                    resolution_result=resolution_result,
                )
            )
            connection.execute(
                update(session_events).where(session_events.c.id == event_id).values(
                    subject_character_id=attacker["character_id"],
                    payload={
                        "roll_request_id": str(roll_request_id),
                        "roll_result_id": str(roll_result_id),
                        "source": computation.source,
                        "formula": computation.formula,
                        "raw_dice": list(computation.raw_dice),
                        "kept_dice": list(computation.kept_dice),
                        "base_modifier": computation.base_modifier,
                        "flat_adjustment": computation.flat_adjustment,
                        "total": computation.total,
                        "visibility": "public",
                        "combat_id": str(action["combat_id"]),
                        "action_id": str(action["id"]),
                        "attacker_entry_id": str(attacker["id"]),
                        "target_entry_id": str(target["id"]),
                        "attack_resolution": resolution_result,
                    },
                )
            )
            connection.execute(
                update(combats).where(combats.c.id == action["combat_id"]).values(
                    revision=combats.c.revision + 1,
                    updated_at=now,
                )
            )

        event = self.event_repository.append(
            room_id=binding.room_id,
            campaign_id=binding.campaign_id,
            session_id=binding.session_id,
            kind="roll.resolved",
            acting_seat_id=acting_seat_id,
            subject_seat_id=request.subject_seat_id,
            subject_character_id=None,
            execution_mode=execution_mode,
            visibility="public",
            recipient_seat_ids=(request.subject_seat_id,) if request.subject_seat_id else (),
            payload_version=1,
            payload={
                "roll_request_id": str(roll_request_id),
                "visibility": "public",
                "action_id": str(request.action_id),
            },
            idempotency_key=f"p4c-attack-result:{idempotency_key}" if idempotency_key else None,
            expected_actor_binding=binding,
            transaction_projection=projection,
        )
        stored = self.get_resolution(action_id=request.action_id)
        if stored is None:
            raise AttackRequestNotPendingPersistenceError(str(request.action_id))
        return stored, event


__all__ = [
    "AttackPersistenceError",
    "AttackRequestNotFoundPersistenceError",
    "AttackRequestNotPendingPersistenceError",
    "AttackRollComputation",
    "AttackStateConflictPersistenceError",
    "CombatAttackRepository",
    "StoredAttackRequest",
    "StoredAttackResolution",
]
