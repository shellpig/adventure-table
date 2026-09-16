from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping
from uuid import UUID, uuid4

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Engine

from app.domain.character.schemas import (
    CharacterBuild,
    CharacterConcentrationState,
    CharacterState,
    PersistentTemporaryEffect,
)
from app.domain.combat.aoe_adjudication import (
    AoeAdjudication,
    AoeTargetState,
    confirm_aoe,
    propose_aoe,
    resolve_aoe_save_spell,
)
from app.domain.combat.concentration_triggers import concentration_dc
from app.domain.combat.effect_resolver import EffectSpec
from app.domain.combat.resolution import DamageRollPart, HitPointState, RollMode, TargetKind
from app.domain.combat.spell_resolver import (
    SaveDamageMode,
    SpellCastMode,
    SpellCastRequest,
    SpellResolutionSpec,
    SpellTargetState,
    resolve_monster_spell,
    resolve_spell,
)
from app.domain.combat.spell_resources import (
    authorize_character_spell,
    resolve_monster_spell_source,
)
from app.domain.rules.hit_points import calculate_max_hp
from app.persistence.characters import character_states, character_versions, characters
from app.persistence.combat.effects import (
    strip_monster_items,
    condition_ref_for_effect,
    monster_effect_entry,
    strip_effects_from_state_payload,
    strip_linked_effects,
)
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


class CombatSpellNotFoundError(LookupError):
    pass


class CombatSpellStateConflictError(RuntimeError):
    pass


@dataclass(frozen=True)
class _DamagedTargetConcentration:
    entry_id: UUID
    character_id: UUID | None
    concentration: CharacterConcentrationState
    target_seat_id: UUID | None = None


@dataclass(frozen=True)
class StoredAoeSpellAction:
    action_id: UUID
    combat_id: UUID
    caster_entry_id: UUID
    status: str
    adjudication: AoeAdjudication
    spell_ref: str
    profile_id: str
    spell_level: int
    slot_level: int
    save_ability_ref: str
    save_dc: int
    save_damage_mode: SaveDamageMode
    resolution_result: dict[str, Any] | None


def _stored_aoe(row: Mapping[str, Any]) -> StoredAoeSpellAction:
    payload = dict(row["payload"] or {})
    spell = dict(payload.get("spell") or {})
    adjudication = AoeAdjudication.from_payload(dict(payload["adjudication"]))
    return StoredAoeSpellAction(
        action_id=row["id"],
        combat_id=row["combat_id"],
        caster_entry_id=row["entry_id"],
        status=str(row["resolution_status"]),
        adjudication=adjudication,
        spell_ref=str(spell["spell_ref"]),
        profile_id=str(spell["profile_id"]),
        spell_level=int(spell["spell_level"]),
        slot_level=int(spell["slot_level"]),
        save_ability_ref=str(spell["save_ability_ref"]),
        save_dc=int(spell["save_dc"]),
        save_damage_mode=SaveDamageMode(str(spell["save_damage_mode"])),
        resolution_result=(
            dict(row["resolution_result"] or {})
            if row["resolution_result"] is not None
            else None
        ),
    )


@dataclass(frozen=True)
class StoredSpellCastAction:
    action_id: UUID
    combat_id: UUID
    caster_entry_id: UUID
    target_entry_id: UUID | None
    status: str
    spell_ref: str
    cast_mode: SpellCastMode
    roll_request_id: UUID | None
    roll_result_id: UUID | None
    resolution_result: dict[str, Any] | None


def _stored_cast(row: Mapping[str, Any]) -> StoredSpellCastAction:
    spell = dict(dict(row["payload"] or {}).get("spell") or {})
    return StoredSpellCastAction(
        action_id=row["id"],
        combat_id=row["combat_id"],
        caster_entry_id=row["entry_id"],
        target_entry_id=row["target_entry_id"],
        status=str(row["resolution_status"]),
        spell_ref=str(spell["spell_ref"]),
        cast_mode=SpellCastMode(str(spell["cast_mode"])),
        roll_request_id=row["roll_request_id"],
        roll_result_id=row["roll_result_id"],
        resolution_result=(
            dict(row["resolution_result"] or {})
            if row["resolution_result"] is not None
            else None
        ),
    )


def _damage_payload(parts: tuple[DamageRollPart, ...]) -> list[dict[str, object]]:
    return [
        {
            "damage_type": part.damage_type.value,
            "dice": list(part.dice),
            "critical_dice": list(part.critical_dice),
            "flat_modifier": part.flat_modifier,
        }
        for part in parts
    ]


class CombatSpellRepository:
    """Durable P4-D spell transaction boundary.

    Single-target casts resolve in one projection; AoE casts add a DM target
    confirmation step first. In both, formal roll results, the caster spell
    resource, action economy, every target state mutation, concentration
    follow-up requests and the durable Session event commit together.
    """

    def __init__(self, engine: Engine, event_repository: TableEventRepository) -> None:
        self.engine = engine
        self.event_repository = event_repository

    def get_aoe_action(
        self, *, session_id: UUID, action_id: UUID
    ) -> StoredAoeSpellAction | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(combat_actions).where(
                    combat_actions.c.id == action_id,
                    combat_actions.c.session_id == session_id,
                    combat_actions.c.action_kind == "spell_aoe",
                )
            ).mappings().one_or_none()
        return _stored_aoe(row) if row is not None else None

    @staticmethod
    def _lock_entry(connection, *, combat_id: UUID, entry_id: UUID):
        row = connection.execute(
            select(combat_entries)
            .where(
                combat_entries.c.id == entry_id,
                combat_entries.c.combat_id == combat_id,
            )
            .with_for_update()
        ).mappings().one_or_none()
        if row is None:
            raise CombatSpellNotFoundError(str(entry_id))
        if row["status"] != "active":
            raise CombatSpellStateConflictError("Spell requires an active Combat entry")
        return row

    @staticmethod
    def _load_character_state(connection, character_id: UUID):
        row = connection.execute(
            select(
                character_states.c.state_payload,
                character_states.c.state_revision,
                character_versions.c.build_payload,
            )
            .select_from(
                character_states.join(
                    characters,
                    characters.c.id == character_states.c.character_id,
                ).join(
                    character_versions,
                    character_versions.c.id == characters.c.current_version_id,
                )
            )
            .where(character_states.c.character_id == character_id)
            .with_for_update()
        ).mappings().one_or_none()
        if row is None:
            raise CombatSpellNotFoundError(str(character_id))
        return (
            CharacterBuild.model_validate(row["build_payload"]),
            CharacterState.model_validate(row["state_payload"]),
            int(row["state_revision"]),
        )

    def propose_character_aoe(
        self,
        *,
        binding: StoredTableActorBinding,
        combat_id: UUID,
        caster_entry_id: UUID,
        subject_seat_id: UUID | None,
        execution_mode: str,
        profile_id: str,
        spell_ref: str,
        spell_level: int,
        slot_level: int,
        save_ability_ref: str,
        save_dc: int,
        save_damage_mode: SaveDamageMode,
        proposed_target_ids: tuple[UUID, ...],
        idempotency_key: str | None,
    ) -> tuple[StoredAoeSpellAction, StoredTableEvent]:
        if not proposed_target_ids:
            raise ValueError("AoE requires at least one proposed target")
        if len(proposed_target_ids) != len(set(proposed_target_ids)):
            raise ValueError("AoE proposed targets must be unique")

        action_id = uuid4()
        adjudication = propose_aoe(
            command_id=str(action_id),
            acting_entry_id=str(caster_entry_id),
            target_ids=tuple(str(value) for value in proposed_target_ids),
        )
        payload = {
            "spell": {
                "spell_ref": spell_ref,
                "profile_id": profile_id,
                "spell_level": spell_level,
                "slot_level": slot_level,
                "save_ability_ref": save_ability_ref,
                "save_dc": save_dc,
                "save_damage_mode": save_damage_mode.value,
            },
            "adjudication": adjudication.to_payload(),
        }

        def projection(connection, event_id: UUID, _seq: int) -> None:
            combat = connection.execute(
                select(combats)
                .where(
                    combats.c.id == combat_id,
                    combats.c.campaign_id == binding.campaign_id,
                )
                .with_for_update()
            ).mappings().one_or_none()
            if combat is None or combat["status"] != "running":
                raise CombatSpellStateConflictError("AoE requires a running Combat")
            caster = self._lock_entry(
                connection,
                combat_id=combat_id,
                entry_id=caster_entry_id,
            )
            if combat["current_turn_entry_id"] != caster_entry_id:
                raise CombatSpellStateConflictError("Spell can only be proposed on the caster's turn")
            if caster["surprised"]:
                raise CombatSpellStateConflictError("Surprised combatant cannot cast on its first turn")
            for target_id in sorted(set(proposed_target_ids), key=str):
                self._lock_entry(connection, combat_id=combat_id, entry_id=target_id)

            connection.execute(
                insert(combat_actions).values(
                    id=action_id,
                    combat_id=combat_id,
                    entry_id=caster_entry_id,
                    target_entry_id=None,
                    session_id=binding.session_id,
                    acting_seat_id=binding.seat_id,
                    subject_seat_id=subject_seat_id,
                    execution_mode=execution_mode,
                    action_kind="spell_aoe",
                    economy_cost="action",
                    payload=payload,
                    resolution_status="dm_adjudication_required",
                    roll_request_id=None,
                    roll_result_id=None,
                    resolution_result=None,
                    idempotency_key=idempotency_key,
                )
            )
            now = datetime.now().astimezone()
            connection.execute(
                update(combats)
                .where(combats.c.id == combat_id)
                .values(revision=combats.c.revision + 1, updated_at=now)
            )
            connection.execute(
                update(session_events)
                .where(session_events.c.id == event_id)
                .values(subject_character_id=caster["character_id"])
            )

        event = self.event_repository.append(
            room_id=binding.room_id,
            campaign_id=binding.campaign_id,
            session_id=binding.session_id,
            kind="combat.spell_aoe_adjudication_requested",
            acting_seat_id=binding.seat_id,
            subject_seat_id=subject_seat_id,
            subject_character_id=None,
            execution_mode=execution_mode,
            visibility="public",
            recipient_seat_ids=(),
            payload_version=1,
            payload={
                "combat_id": str(combat_id),
                "action_id": str(action_id),
                "caster_entry_id": str(caster_entry_id),
                "spell_ref": spell_ref,
                "proposed_target_ids": [str(value) for value in proposed_target_ids],
                "status": "dm_adjudication_required",
            },
            idempotency_key=(
                f"p4d-aoe-propose:{idempotency_key}" if idempotency_key else None
            ),
            expected_actor_binding=binding,
            transaction_projection=projection,
        )
        canonical_action_id = UUID(str(event.payload["action_id"]))
        stored = self.get_aoe_action(
            session_id=binding.session_id,
            action_id=canonical_action_id,
        )
        if stored is None:
            raise CombatSpellNotFoundError(str(canonical_action_id))
        return stored, event

    def resolve_character_aoe(
        self,
        *,
        binding: StoredTableActorBinding,
        action_id: UUID,
        confirmed_target_ids: tuple[UUID, ...],
        save_modifiers: Mapping[UUID, int],
        save_d20s: Mapping[UUID, int],
        damage_parts: tuple[DamageRollPart, ...],
        roll_source: str,
        idempotency_key: str | None,
        target_seat_ids: Mapping[UUID, UUID | None] | None = None,
    ) -> tuple[StoredAoeSpellAction, StoredTableEvent]:
        if roll_source not in {"server", "physical"}:
            raise ValueError("AoE formal save roll_source must be server or physical")
        if not confirmed_target_ids or len(confirmed_target_ids) != len(set(confirmed_target_ids)):
            raise ValueError("confirmed AoE targets must be a non-empty unique set")
        existing = self.get_aoe_action(session_id=binding.session_id, action_id=action_id)
        if existing is None:
            raise CombatSpellNotFoundError(str(action_id))

        target_seat_ids = dict(target_seat_ids or {})
        roll_group_id = uuid4()
        roll_ids = {target_id: (uuid4(), uuid4()) for target_id in confirmed_target_ids}

        def projection(connection, event_id: UUID, _seq: int) -> None:
            action = connection.execute(
                select(combat_actions)
                .where(
                    combat_actions.c.id == action_id,
                    combat_actions.c.session_id == binding.session_id,
                    combat_actions.c.action_kind == "spell_aoe",
                )
                .with_for_update()
            ).mappings().one_or_none()
            if action is None:
                raise CombatSpellNotFoundError(str(action_id))
            if action["resolution_status"] != "dm_adjudication_required":
                raise CombatSpellStateConflictError("AoE action is no longer awaiting adjudication")

            combat = connection.execute(
                select(combats)
                .where(
                    combats.c.id == action["combat_id"],
                    combats.c.campaign_id == binding.campaign_id,
                )
                .with_for_update()
            ).mappings().one_or_none()
            if combat is None or combat["status"] != "running":
                raise CombatSpellStateConflictError("AoE requires a running Combat")
            caster = self._lock_entry(
                connection,
                combat_id=action["combat_id"],
                entry_id=action["entry_id"],
            )
            if combat["current_turn_entry_id"] != caster["id"]:
                raise CombatSpellStateConflictError("Spell can only resolve on the caster's turn")
            if not caster["action_available"]:
                raise CombatSpellStateConflictError("Caster Action is already spent")
            if caster["character_id"] is None:
                raise CombatSpellStateConflictError("Character spell caster has no Character identity")

            payload = dict(action["payload"] or {})
            spell = dict(payload["spell"])
            proposed = AoeAdjudication.from_payload(dict(payload["adjudication"]))
            confirmed = confirm_aoe(
                proposed,
                confirmed_target_ids=tuple(str(value) for value in confirmed_target_ids),
            )
            if set(save_modifiers) != set(confirmed_target_ids):
                raise ValueError("save modifiers must exactly match confirmed AoE targets")
            if set(save_d20s) != set(confirmed_target_ids):
                raise ValueError("save d20s must exactly match confirmed AoE targets")

            target_entries = {
                target_id: self._lock_entry(
                    connection,
                    combat_id=action["combat_id"],
                    entry_id=target_id,
                )
                for target_id in sorted(set(confirmed_target_ids), key=str)
            }
            character_ids = {
                row["character_id"]
                for row in target_entries.values()
                if row["character_id"] is not None
            }
            character_ids.add(caster["character_id"])
            character_rows: dict[UUID, tuple[CharacterBuild, CharacterState, int]] = {}
            for character_id in sorted(character_ids, key=str):
                character_rows[character_id] = self._load_character_state(connection, character_id)

            caster_build, caster_state, _caster_revision = character_rows[caster["character_id"]]
            authorization = authorize_character_spell(
                build=caster_build,
                state=caster_state,
                profile_id=str(spell["profile_id"]),
                spell_ref=str(spell["spell_ref"]),
                spell_level=int(spell["spell_level"]),
                slot_level=int(spell["slot_level"]),
            )
            spec = SpellResolutionSpec(
                spell_ref=str(spell["spell_ref"]),
                cast_mode=SpellCastMode.SAVE,
                minimum_slot_level=int(spell["spell_level"]),
                save_dc=int(spell["save_dc"]),
                save_damage_mode=SaveDamageMode(str(spell["save_damage_mode"])),
            )

            domain_targets: dict[str, AoeTargetState] = {}
            monster_rows: dict[UUID, Mapping[str, Any]] = {}
            for target_id, entry in target_entries.items():
                if entry["subject_kind"] == "character":
                    character_id = entry["character_id"]
                    if character_id is None:
                        raise CombatSpellStateConflictError("Character target has no Character identity")
                    build, state, _revision = character_rows[character_id]
                    domain_targets[str(target_id)] = AoeTargetState(
                        entry_id=str(target_id),
                        target_kind=TargetKind.CHARACTER,
                        hp=HitPointState(
                            current_hp=state.current_hp,
                            max_hp=calculate_max_hp(build),
                            temp_hp=state.temporary_hp,
                        ),
                        save_modifier=int(save_modifiers[target_id]),
                        death_saves=_death_state(entry),
                    )
                elif entry["subject_kind"] == "monster":
                    monster_id = entry["monster_instance_id"]
                    if monster_id is None:
                        raise CombatSpellStateConflictError("Monster target has no Monster identity")
                    monster = connection.execute(
                        select(monster_instances)
                        .where(monster_instances.c.id == monster_id)
                        .with_for_update()
                    ).mappings().one_or_none()
                    if monster is None:
                        raise CombatSpellNotFoundError(str(monster_id))
                    monster_rows[monster_id] = monster
                    rules = dict(monster["rules_snapshot"] or {})
                    resistances, immunities, vulnerabilities = _damage_affinities(rules)
                    domain_targets[str(target_id)] = AoeTargetState(
                        entry_id=str(target_id),
                        target_kind=TargetKind.MONSTER,
                        hp=HitPointState(
                            current_hp=int(monster["current_hp"]),
                            max_hp=int(rules["max_hp"]),
                            temp_hp=int(monster["temp_hp"]),
                        ),
                        save_modifier=int(save_modifiers[target_id]),
                        resistances=resistances,
                        immunities=immunities,
                        vulnerabilities=vulnerabilities,
                    )
                else:
                    raise CombatSpellStateConflictError("unsupported AoE target kind")

            resolution = resolve_aoe_save_spell(
                adjudication=confirmed,
                spec=spec,
                state=caster_state,
                authorization=authorization,
                targets=domain_targets,
                save_d20s={str(key): int(value) for key, value in save_d20s.items()},
                damage_parts=damage_parts,
            )
            if resolution.character_state is None:
                raise CombatSpellStateConflictError("Character AoE did not return caster state")

            now = datetime.now().astimezone()
            next_states: dict[UUID, CharacterState] = {
                caster["character_id"]: resolution.character_state
            }
            outcomes_by_id = {UUID(row.entry_id): row for row in resolution.outcomes}
            for target_id, entry in target_entries.items():
                outcome = outcomes_by_id[target_id]
                if entry["subject_kind"] == "character":
                    character_id = entry["character_id"]
                    assert character_id is not None
                    base_state = next_states.get(character_id, character_rows[character_id][1])
                    state_payload = base_state.model_dump(mode="json")
                    state_payload["current_hp"] = outcome.hp.current_hp
                    state_payload["temporary_hp"] = outcome.hp.temp_hp
                    if outcome.death_saves is not None:
                        state_payload["death_saves"] = {
                            "successes": outcome.death_saves.successes,
                            "failures": outcome.death_saves.failures,
                            "stable": outcome.death_saves.stable,
                            "dead": outcome.death_saves.dead,
                        }
                    conditions = list(state_payload.get("conditions", []))
                    if outcome.apply_unconscious:
                        _add_condition(
                            conditions,
                            UNCONSCIOUS_REF,
                            "P4-D: AoE reduced target to zero hit points",
                        )
                    if outcome.apply_prone:
                        _add_condition(
                            conditions,
                            PRONE_REF,
                            "P4-D: AoE reduced target to zero hit points",
                        )
                    state_payload["conditions"] = conditions
                    next_states[character_id] = CharacterState.model_validate(state_payload)
                    connection.execute(
                        update(combat_entries)
                        .where(combat_entries.c.id == target_id)
                        .values(**_death_values(outcome.death_saves), updated_at=now)
                    )
                else:
                    monster_id = entry["monster_instance_id"]
                    assert monster_id is not None
                    connection.execute(
                        update(monster_instances)
                        .where(monster_instances.c.id == monster_id)
                        .values(
                            current_hp=outcome.hp.current_hp,
                            temp_hp=outcome.hp.temp_hp,
                            updated_at=now,
                        )
                    )

            for character_id, next_state in next_states.items():
                _build, _previous, revision = character_rows[character_id]
                state_update = connection.execute(
                    update(character_states)
                    .where(
                        character_states.c.character_id == character_id,
                        character_states.c.state_revision == revision,
                    )
                    .values(
                        state_payload=next_state.model_dump(mode="json"),
                        state_revision=revision + 1,
                        updated_at=now,
                    )
                )
                if state_update.rowcount != 1:
                    raise CombatSpellStateConflictError(
                        "Character State changed while resolving AoE spell"
                    )

            connection.execute(
                update(combat_entries)
                .where(combat_entries.c.id == caster["id"])
                .values(action_available=False, updated_at=now)
            )

            connection.execute(
                insert(roll_groups).values(
                    id=roll_group_id,
                    session_id=binding.session_id,
                    requested_by_seat_id=binding.seat_id,
                    label=f"Spell saves: {spec.spell_ref}",
                    visibility="public",
                    version=1,
                )
            )
            roll_payloads: list[dict[str, object]] = []
            for target_id in confirmed_target_ids:
                request_id, result_id = roll_ids[target_id]
                entry = target_entries[target_id]
                d20 = int(save_d20s[target_id])
                modifier = int(save_modifiers[target_id])
                total = d20 + modifier
                connection.execute(
                    insert(roll_requests).values(
                        id=request_id,
                        session_id=binding.session_id,
                        roll_group_id=roll_group_id,
                        target_seat_id=target_seat_ids.get(target_id),
                        target_character_id=entry["character_id"],
                        target_combat_entry_id=target_id,
                        request_type="saving_throw",
                        ability_ref=str(spell["save_ability_ref"]),
                        skill_ref=None,
                        dc=int(spell["save_dc"]),
                        modifier_mode="normal",
                        flat_adjustment=0,
                        visibility="public",
                        status="resolved",
                        requested_by_seat_id=binding.seat_id,
                        resolved_at=now,
                        version=2,
                    )
                )
                connection.execute(
                    insert(roll_results).values(
                        id=result_id,
                        roll_request_id=request_id,
                        session_id=binding.session_id,
                        acting_seat_id=binding.seat_id,
                        subject_seat_id=target_seat_ids.get(target_id),
                        subject_character_id=entry["character_id"],
                        subject_combat_entry_id=target_id,
                        execution_mode="system",
                        source=roll_source,
                        formula=f"1d20 + {modifier}",
                        raw_dice=[d20],
                        kept_dice=[d20],
                        base_modifier=modifier,
                        flat_adjustment=0,
                        total=total,
                        visibility="public",
                    )
                )
                roll_payloads.append(
                    {
                        "target_entry_id": str(target_id),
                        "roll_request_id": str(request_id),
                        "roll_result_id": str(result_id),
                        "d20": d20,
                        "modifier": modifier,
                        "total": total,
                    }
                )

            concentration_payloads: list[dict[str, object]] = []
            for target_id, entry in target_entries.items():
                if entry["subject_kind"] != "character":
                    continue
                character_id = entry["character_id"]
                assert character_id is not None
                outcome = outcomes_by_id[target_id]
                next_state = next_states[character_id]
                current = next_state.concentration
                if current is None or outcome.damage_taken <= 0:
                    continue
                concentration_group_id = uuid4()
                concentration_request_id = uuid4()
                dc = concentration_dc(outcome.damage_taken)
                connection.execute(
                    insert(roll_groups).values(
                        id=concentration_group_id,
                        session_id=binding.session_id,
                        requested_by_seat_id=binding.seat_id,
                        label="Concentration",
                        visibility="public",
                        version=1,
                    )
                )
                connection.execute(
                    insert(roll_requests).values(
                        id=concentration_request_id,
                        session_id=binding.session_id,
                        roll_group_id=concentration_group_id,
                        target_seat_id=target_seat_ids.get(target_id),
                        target_character_id=character_id,
                        target_combat_entry_id=target_id,
                        request_type="saving_throw",
                        ability_ref="srd5.1:ability:constitution",
                        skill_ref=None,
                        dc=dc,
                        modifier_mode="normal",
                        flat_adjustment=0,
                        visibility="public",
                        status="pending",
                        requested_by_seat_id=binding.seat_id,
                        version=1,
                    )
                )
                concentration_payloads.append(
                    {
                        "target_entry_id": str(target_id),
                        "target_character_id": str(character_id),
                        "source_ref": current.source_ref,
                        "damage_taken": outcome.damage_taken,
                        "dc": dc,
                        "roll_group_id": str(concentration_group_id),
                        "roll_request_id": str(concentration_request_id),
                    }
                )

            resolution_payload = {
                "spell_ref": spec.spell_ref,
                "adjudication": resolution.adjudication.to_payload(),
                "damage_parts": _damage_payload(damage_parts),
                "roll_group_id": str(roll_group_id),
                "rolls": roll_payloads,
                "outcomes": [
                    {
                        "target_entry_id": row.entry_id,
                        "save_total": row.save_total,
                        "saved": row.saved,
                        "damage": row.damage_taken,
                        "current_hp": row.hp.current_hp,
                        "temp_hp": row.hp.temp_hp,
                        "instant_death": row.instant_death,
                        "monster_outcome_required": row.monster_outcome_required,
                    }
                    for row in resolution.outcomes
                ],
                "concentration_checks": concentration_payloads,
                "domain_events": list(resolution.events),
            }
            first_target = confirmed_target_ids[0]
            first_request_id, first_result_id = roll_ids[first_target]
            payload["adjudication"] = resolution.adjudication.to_payload()
            connection.execute(
                update(combat_actions)
                .where(combat_actions.c.id == action_id)
                .values(
                    payload=payload,
                    resolution_status="resolved",
                    roll_request_id=first_request_id,
                    roll_result_id=first_result_id,
                    resolution_result=resolution_payload,
                )
            )
            connection.execute(
                update(session_events)
                .where(session_events.c.id == event_id)
                .values(
                    subject_character_id=caster["character_id"],
                    payload={
                        "combat_id": str(action["combat_id"]),
                        "action_id": str(action_id),
                        "caster_entry_id": str(caster["id"]),
                        **resolution_payload,
                    },
                )
            )
            connection.execute(
                update(combats)
                .where(combats.c.id == action["combat_id"])
                .values(revision=combats.c.revision + 1, updated_at=now)
            )

        event = self.event_repository.append(
            room_id=binding.room_id,
            campaign_id=binding.campaign_id,
            session_id=binding.session_id,
            kind="combat.spell_aoe_resolved",
            acting_seat_id=binding.seat_id,
            subject_seat_id=None,
            subject_character_id=None,
            execution_mode="dm_proxy" if binding.is_current_dm else "self",
            visibility="public",
            recipient_seat_ids=(),
            payload_version=1,
            payload={"combat_id": str(existing.combat_id), "action_id": str(action_id)},
            idempotency_key=(
                f"p4d-aoe-resolve:{idempotency_key}" if idempotency_key else None
            ),
            expected_actor_binding=binding,
            transaction_projection=projection,
        )
        stored = self.get_aoe_action(
            session_id=binding.session_id,
            action_id=action_id,
        )
        if stored is None:
            raise CombatSpellNotFoundError(str(action_id))
        return stored, event


    def get_cast_action(
        self, *, session_id: UUID, action_id: UUID
    ) -> StoredSpellCastAction | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(combat_actions).where(
                    combat_actions.c.id == action_id,
                    combat_actions.c.session_id == session_id,
                    combat_actions.c.action_kind == "spell_cast",
                )
            ).mappings().one_or_none()
        return _stored_cast(row) if row is not None else None

    def cast_character_spell(
        self,
        *,
        binding: StoredTableActorBinding,
        combat_id: UUID,
        caster_entry_id: UUID,
        subject_seat_id: UUID | None,
        execution_mode: str,
        profile_id: str,
        spell_ref: str,
        spell_level: int,
        slot_level: int,
        cast_mode: SpellCastMode,
        target_entry_id: UUID | None,
        roll_source: str,
        idempotency_key: str | None,
        target_seat_id: UUID | None = None,
        attack_modifier: int | None = None,
        attack_d20s: tuple[int, ...] = (),
        attack_mode: RollMode = RollMode.NORMAL,
        target_ac: int | None = None,
        save_ability_ref: str | None = None,
        save_dc: int | None = None,
        save_modifier: int | None = None,
        save_d20: int | None = None,
        save_damage_mode: SaveDamageMode = SaveDamageMode.NONE,
        damage_parts: tuple[DamageRollPart, ...] = (),
        healing_amount: int = 0,
        concentration: bool = False,
        apply_effects: tuple[EffectSpec, ...] = (),
    ) -> tuple[StoredSpellCastAction, StoredTableEvent]:
        """Resolve one single-target (or self / utility) Character spell atomically.

        Unlike AoE there is no adjudication step: the caller has already chosen
        the one legal target, so authorization, resource spend, attack / save
        formal rolls, target HP and conditions, applied effects, concentration
        replacement, the CON save request for a concentrating target and the
        Session event commit in one projection under one idempotency key.
        """

        if roll_source not in {"server", "physical"}:
            raise ValueError("spell formal roll_source must be server or physical")
        if cast_mode is SpellCastMode.SAVE and save_ability_ref is None:
            raise ValueError("save spells require save_ability_ref")
        if cast_mode is SpellCastMode.ATTACK and any(d20 < 1 or d20 > 20 for d20 in attack_d20s):
            raise ValueError("attack d20 must be between 1 and 20")

        action_id = uuid4()
        roll_group_id = uuid4()
        roll_request_id = uuid4()
        roll_result_id = uuid4()
        spell_payload = {
            "spell_ref": spell_ref,
            "profile_id": profile_id,
            "spell_level": spell_level,
            "slot_level": slot_level,
            "cast_mode": cast_mode.value,
            "concentration": concentration,
            "save_ability_ref": save_ability_ref,
            "save_dc": save_dc,
            "save_damage_mode": save_damage_mode.value,
            "attack_modifier": attack_modifier,
            "attack_mode": attack_mode.value,
            "damage_parts": _damage_payload(damage_parts),
            "healing_amount": healing_amount,
            "effects": [
                {"effect_type": item.effect_type, "tag": item.tag, "source_ref": item.source_ref}
                for item in apply_effects
            ],
        }

        def projection(connection, event_id: UUID, _seq: int) -> None:
            combat = connection.execute(
                select(combats)
                .where(
                    combats.c.id == combat_id,
                    combats.c.campaign_id == binding.campaign_id,
                )
                .with_for_update()
            ).mappings().one_or_none()
            if combat is None or combat["status"] != "running":
                raise CombatSpellStateConflictError("Spell requires a running Combat")
            caster = self._lock_entry(connection, combat_id=combat_id, entry_id=caster_entry_id)
            if combat["current_turn_entry_id"] != caster_entry_id:
                raise CombatSpellStateConflictError("Spell can only be cast on the caster's turn")
            if caster["surprised"]:
                raise CombatSpellStateConflictError("Surprised combatant cannot cast on its first turn")
            if not caster["action_available"]:
                raise CombatSpellStateConflictError("Caster Action is already spent")
            caster_character_id = caster["character_id"]
            if caster_character_id is None:
                raise CombatSpellStateConflictError("Character spell caster has no Character identity")

            caster_build, caster_state, caster_revision = self._load_character_state(
                connection, caster_character_id
            )
            authorization = authorize_character_spell(
                build=caster_build,
                state=caster_state,
                profile_id=profile_id,
                spell_ref=spell_ref,
                spell_level=spell_level,
                slot_level=slot_level,
            )
            spec = SpellResolutionSpec(
                spell_ref=spell_ref,
                cast_mode=cast_mode,
                minimum_slot_level=spell_level,
                attack_modifier=attack_modifier,
                save_dc=save_dc,
                save_damage_mode=save_damage_mode,
                concentration=concentration,
                apply_effects=apply_effects,
            )
            request = SpellCastRequest(
                caster_ref=str(caster_entry_id),
                slot_level=slot_level,
                attack_d20s=attack_d20s,
                attack_mode=attack_mode,
                save_d20=save_d20,
                damage_parts=damage_parts,
                healing_amount=healing_amount,
            )

            target_is_caster = target_entry_id == caster_entry_id
            target_entry, target_character, target_monster, domain_target = (
                self._load_spell_target(
                    connection,
                    combat_id=combat_id,
                    target_entry_id=target_entry_id,
                    caster_entry=caster,
                    caster_character=(caster_build, caster_state, caster_revision),
                    target_ac=target_ac,
                    save_modifier=save_modifier,
                )
            )

            resolution = resolve_spell(
                spec=spec,
                request=request,
                target=domain_target,
                state=caster_state,
                authorization=authorization,
                effect_id_prefix=f"{spell_ref}:{action_id}",
                effects_target="target" if domain_target is not None and not target_is_caster else "caster",
            )
            now = datetime.now().astimezone()

            replaced_ids = set(resolution.replaced_concentration_effect_ids)
            damaged_target: _DamagedTargetConcentration | None = None

            # Caster state: spend + concentration pointer (+ self-target HP/effects).
            caster_payload = resolution.character_state.model_dump(mode="json")
            strip_effects_from_state_payload(caster_payload, replaced_ids)
            if target_is_caster and resolution.target_hp is not None:
                self._apply_target_hp_to_payload(
                    caster_payload, resolution, "P4-D: spell reduced target to zero hit points"
                )
                connection.execute(
                    update(combat_entries)
                    .where(combat_entries.c.id == caster_entry_id)
                    .values(**_death_values(resolution.target_death_saves), updated_at=now)
                )
                state_after_dmg = CharacterState.model_validate(caster_payload)
                if state_after_dmg.concentration is not None:
                    damaged_target = _DamagedTargetConcentration(
                        entry_id=caster_entry_id,
                        character_id=caster_character_id,
                        concentration=state_after_dmg.concentration,
                        target_seat_id=subject_seat_id,
                    )
            if target_is_caster or domain_target is None:
                self._attach_effects_to_payload(caster_payload, resolution.applied_effects, spell_ref)
            self._write_character_state(
                connection, caster_character_id, caster_revision, caster_payload
            )

            # Target state.
            if domain_target is not None and not target_is_caster:
                assert target_entry is not None
                damaged_target = self._write_spell_target_state(
                    connection,
                    target_entry=target_entry,
                    target_character=target_character,
                    target_monster=target_monster,
                    resolution=resolution,
                    spell_ref=spell_ref,
                    replaced_ids=replaced_ids,
                    note_prefix="P4-D",
                    now=now,
                )

            # Replacing concentration ends the previous spell's effects everywhere.
            replaced = strip_linked_effects(
                connection,
                combat_id=combat_id,
                effect_ids=resolution.replaced_concentration_effect_ids,
                now=now,
                skip_character_ids=(
                    {caster_character_id, target_entry["character_id"]}
                    if target_character is not None and target_entry is not None
                    else {caster_character_id}
                ),
                skip_monster_ids=(
                    {target_monster["id"]}
                    if target_monster is not None
                    else ()
                ),
            )

            connection.execute(
                update(combat_entries)
                .where(combat_entries.c.id == caster_entry_id)
                .values(action_available=False, updated_at=now)
            )

            roll_payload = self._insert_spell_formal_roll(
                connection,
                binding=binding,
                cast_mode=cast_mode,
                resolution=resolution,
                attack_modifier=attack_modifier,
                attack_d20s=attack_d20s,
                attack_mode=attack_mode,
                save_ability_ref=save_ability_ref,
                save_dc=save_dc,
                save_modifier=save_modifier,
                save_d20=save_d20,
                spell_ref=spell_ref,
                subject_seat_id=subject_seat_id,
                target_seat_id=target_seat_id,
                caster_entry_id=caster_entry_id,
                target_entry_id=target_entry_id,
                caster_character_id=caster_character_id,
                target_character_id=target_entry["character_id"] if target_entry is not None else None,
                roll_source=roll_source,
                roll_group_id=roll_group_id,
                roll_request_id=roll_request_id,
                roll_result_id=roll_result_id,
                now=now,
            )

            damage_taken = resolution.damage.adjusted_total if resolution.damage is not None else 0
            concentration_payload = self._request_concentration_check_for_damaged_target(
                connection,
                binding=binding,
                damaged_target=damaged_target,
                target_entry_id=target_entry_id,
                target_seat_id=(subject_seat_id if target_is_caster else target_seat_id),
                damage_taken=damage_taken,
            )

            resolution_payload: dict[str, Any] = {
                "spell_ref": spell_ref,
                "cast_mode": cast_mode.value,
                "target_entry_id": str(target_entry_id) if target_entry_id is not None else None,
                "roll": roll_payload,
                "damage": damage_taken,
                "target_current_hp": resolution.target_hp.current_hp if resolution.target_hp else None,
                "target_temp_hp": resolution.target_hp.temp_hp if resolution.target_hp else None,
                "instant_death": bool(resolution.damage.instant_death) if resolution.damage else False,
                "monster_outcome_required": (
                    bool(resolution.damage.monster_outcome_required) if resolution.damage else False
                ),
                "applied_effect_ids": [effect.effect_id for effect in resolution.applied_effects],
                "concentration_started": resolution.concentration_started,
                "replaced_concentration_effect_ids": list(resolution.replaced_concentration_effect_ids),
                "replaced_effects_removed_from": replaced,
                "concentration_check": concentration_payload,
                "domain_events": list(resolution.events),
            }

            self._write_spell_action_and_event(
                connection,
                event_id=event_id,
                binding=binding,
                combat_id=combat_id,
                action_id=action_id,
                caster_entry_id=caster_entry_id,
                target_entry_id=target_entry_id,
                subject_seat_id=subject_seat_id,
                subject_character_id=caster_character_id,
                execution_mode=execution_mode,
                spell_payload=spell_payload,
                resolution_payload=resolution_payload,
                roll_payload=roll_payload,
                roll_request_id=roll_request_id,
                roll_result_id=roll_result_id,
                idempotency_key=idempotency_key,
                now=now,
            )

        event = self.event_repository.append(
            room_id=binding.room_id,
            campaign_id=binding.campaign_id,
            session_id=binding.session_id,
            kind="combat.spell_cast_resolved",
            acting_seat_id=binding.seat_id,
            subject_seat_id=subject_seat_id,
            subject_character_id=None,
            execution_mode=execution_mode,
            visibility="public",
            recipient_seat_ids=(),
            payload_version=1,
            payload={"combat_id": str(combat_id), "action_id": str(action_id)},
            idempotency_key=(
                f"p4d-spell-cast:{idempotency_key}" if idempotency_key else None
            ),
            expected_actor_binding=binding,
            transaction_projection=projection,
        )
        canonical_action_id = UUID(str(event.payload["action_id"]))
        stored = self.get_cast_action(session_id=binding.session_id, action_id=canonical_action_id)
        if stored is None:
            raise CombatSpellNotFoundError(str(canonical_action_id))
        return stored, event

    def cast_monster_spell(
        self,
        *,
        binding: StoredTableActorBinding,
        combat_id: UUID,
        caster_entry_id: UUID,
        subject_seat_id: UUID | None,
        execution_mode: str,
        spell_ref: str,
        spell_level: int,
        slot_level: int | None = None,
        cast_mode: SpellCastMode,
        target_entry_id: UUID | None,
        roll_source: str,
        idempotency_key: str | None,
        target_seat_id: UUID | None = None,
        attack_modifier: int | None = None,
        attack_d20s: tuple[int, ...] = (),
        attack_mode: RollMode = RollMode.NORMAL,
        target_ac: int | None = None,
        save_ability_ref: str | None = None,
        save_dc: int | None = None,
        save_modifier: int | None = None,
        save_d20: int | None = None,
        save_damage_mode: SaveDamageMode = SaveDamageMode.NONE,
        damage_parts: tuple[DamageRollPart, ...] = (),
        healing_amount: int = 0,
        concentration: bool = False,
        apply_effects: tuple[EffectSpec, ...] = (),
    ) -> tuple[StoredSpellCastAction, StoredTableEvent]:
        """Resolve one single-target (or self / utility) Monster spell atomically.

        Mirrors cast_character_spell, resolving resources via
        resolve_monster_spell_source and resolve_monster_spell on the monster
        instance's rules_snapshot and live resources. Slot deduction, target
        state mutation, roll records and the Session event commit together.
        """

        if roll_source not in {"server", "physical"}:
            raise ValueError("spell formal roll_source must be server or physical")
        if cast_mode is SpellCastMode.SAVE and save_ability_ref is None:
            raise ValueError("save spells require save_ability_ref")
        if cast_mode is SpellCastMode.ATTACK and any(d20 < 1 or d20 > 20 for d20 in attack_d20s):
            raise ValueError("attack d20 must be between 1 and 20")

        action_id = uuid4()
        roll_group_id = uuid4()
        roll_request_id = uuid4()
        roll_result_id = uuid4()
        effective_slot_level = slot_level if slot_level is not None else spell_level

        def projection(connection, event_id: UUID, _seq: int) -> None:
            combat = connection.execute(
                select(combats)
                .where(
                    combats.c.id == combat_id,
                    combats.c.campaign_id == binding.campaign_id,
                )
                .with_for_update()
            ).mappings().one_or_none()
            if combat is None or combat["status"] != "running":
                raise CombatSpellStateConflictError("Spell requires a running Combat")
            caster = self._lock_entry(connection, combat_id=combat_id, entry_id=caster_entry_id)
            if combat["current_turn_entry_id"] != caster_entry_id:
                raise CombatSpellStateConflictError("Spell can only be cast on the caster's turn")
            if caster["surprised"]:
                raise CombatSpellStateConflictError("Surprised combatant cannot cast on its first turn")
            if not caster["action_available"]:
                raise CombatSpellStateConflictError("Caster Action is already spent")
            if caster["subject_kind"] != "monster":
                raise CombatSpellStateConflictError("Monster spell caster must be a monster combatant")
            caster_monster_id = caster["monster_instance_id"]
            if caster_monster_id is None:
                raise CombatSpellStateConflictError("Monster spell caster has no Monster Instance identity")

            caster_monster = connection.execute(
                select(monster_instances)
                .where(monster_instances.c.id == caster_monster_id)
                .with_for_update()
            ).mappings().one_or_none()
            if caster_monster is None:
                raise CombatSpellNotFoundError(str(caster_monster_id))

            rules_snapshot = dict(caster_monster["rules_snapshot"] or {})
            live_resources = dict(caster_monster["resources"] or {})
            source = resolve_monster_spell_source(
                rules_snapshot=rules_snapshot,
                resources=live_resources,
                spell_ref=spell_ref,
                spell_level=spell_level,
                slot_level=effective_slot_level,
            )

            effective_attack_modifier = (
                attack_modifier if attack_modifier is not None else source.attack_bonus
            )
            effective_save_dc = save_dc if save_dc is not None else source.save_dc

            spec = SpellResolutionSpec(
                spell_ref=spell_ref,
                cast_mode=cast_mode,
                minimum_slot_level=spell_level,
                attack_modifier=effective_attack_modifier,
                save_dc=effective_save_dc,
                save_damage_mode=save_damage_mode,
                concentration=concentration,
                apply_effects=apply_effects,
            )
            request = SpellCastRequest(
                caster_ref=str(caster_entry_id),
                slot_level=effective_slot_level,
                attack_d20s=attack_d20s,
                attack_mode=attack_mode,
                save_d20=save_d20,
                damage_parts=damage_parts,
                healing_amount=healing_amount,
            )

            target_is_caster = target_entry_id == caster_entry_id
            target_entry, target_character, target_monster, domain_target = (
                self._load_spell_target(
                    connection,
                    combat_id=combat_id,
                    target_entry_id=target_entry_id,
                    caster_entry=caster,
                    caster_monster=caster_monster,
                    target_ac=target_ac,
                    save_modifier=save_modifier,
                )
            )

            resolution = resolve_monster_spell(
                spec=spec,
                request=request,
                target=domain_target,
                resources=live_resources,
                source=source,
                effect_id_prefix=f"{spell_ref}:{action_id}",
            )
            now = datetime.now().astimezone()

            previous_concentration = (
                dict(caster_monster["concentration"])
                if caster_monster["concentration"]
                else None
            )
            replaced_ids = (
                set(previous_concentration.get("effect_ids", []))
                if (concentration and previous_concentration)
                else set()
            )

            damaged_target: _DamagedTargetConcentration | None = None

            # 1) Target state mutation (if target is not the caster).
            if domain_target is not None and not target_is_caster:
                assert target_entry is not None
                damaged_target = self._write_spell_target_state(
                    connection,
                    target_entry=target_entry,
                    target_character=target_character,
                    target_monster=target_monster,
                    resolution=resolution,
                    spell_ref=spell_ref,
                    replaced_ids=replaced_ids,
                    note_prefix="P4-E",
                    now=now,
                )

            # 2) Caster monster state: deduct resource slot, plus self-target HP / effects if target_is_caster or utility.
            caster_values: dict[str, Any] = {
                "resources": resolution.resources,
                "updated_at": now,
            }
            if concentration:
                caster_values["concentration"] = {
                    "source_ref": spell_ref,
                    "effect_ids": [effect.effect_id for effect in resolution.applied_effects],
                }

            conditions = list(caster_monster["conditions"] or [])
            effects = list(caster_monster["effects"] or [])
            if replaced_ids:
                conditions, _ = strip_monster_items(conditions, replaced_ids)
                effects, _ = strip_monster_items(effects, replaced_ids)
                caster_values["conditions"] = conditions
                caster_values["effects"] = effects

            if target_is_caster or domain_target is None:
                if target_is_caster and resolution.target_hp is not None:
                    caster_values["current_hp"] = resolution.target_hp.current_hp
                    caster_values["temp_hp"] = resolution.target_hp.temp_hp
                    caster_conc = caster_values.get("concentration", caster_monster["concentration"])
                    if caster_conc is not None:
                        damaged_target = _DamagedTargetConcentration(
                            entry_id=caster_entry_id,
                            character_id=None,
                            concentration=CharacterConcentrationState.model_validate(caster_conc),
                            target_seat_id=subject_seat_id,
                        )
                self._append_monster_effects_and_conditions(
                    conditions=conditions,
                    effects=effects,
                    applied_effects=resolution.applied_effects,
                    spell_ref=spell_ref,
                    note_prefix="P4-E",
                )
                caster_values["conditions"] = conditions
                caster_values["effects"] = effects

            connection.execute(
                update(monster_instances)
                .where(monster_instances.c.id == caster_monster_id)
                .values(**caster_values)
            )

            # Replacing concentration ends the previous spell's effects everywhere.
            replaced = strip_linked_effects(
                connection,
                combat_id=combat_id,
                effect_ids=replaced_ids,
                now=now,
                skip_character_ids=(
                    {target_entry["character_id"]}
                    if target_character is not None and target_entry is not None and target_entry["character_id"]
                    else set()
                ),
                skip_monster_ids=(
                    {caster_monster_id, target_monster["id"]}
                    if target_monster is not None
                    else {caster_monster_id}
                ),
            )

            # 3) Caster action economy spent.
            connection.execute(
                update(combat_entries)
                .where(combat_entries.c.id == caster_entry_id)
                .values(action_available=False, updated_at=now)
            )

            # 4) Formal roll record for attack or saving throw.
            roll_payload = self._insert_spell_formal_roll(
                connection,
                binding=binding,
                cast_mode=cast_mode,
                resolution=resolution,
                attack_modifier=effective_attack_modifier,
                attack_d20s=attack_d20s,
                attack_mode=attack_mode,
                save_ability_ref=save_ability_ref,
                save_dc=effective_save_dc,
                save_modifier=save_modifier,
                save_d20=save_d20,
                spell_ref=spell_ref,
                subject_seat_id=subject_seat_id,
                target_seat_id=target_seat_id,
                caster_entry_id=caster_entry_id,
                target_entry_id=target_entry_id,
                caster_character_id=None,
                target_character_id=target_entry["character_id"] if target_entry is not None else None,
                roll_source=roll_source,
                roll_group_id=roll_group_id,
                roll_request_id=roll_request_id,
                roll_result_id=roll_result_id,
                now=now,
            )

            # 5) A concentrating target that took damage owes a CON save.
            damage_taken = resolution.damage.adjusted_total if resolution.damage is not None else 0
            concentration_payload = self._request_concentration_check_for_damaged_target(
                connection,
                binding=binding,
                damaged_target=damaged_target,
                target_entry_id=target_entry_id,
                target_seat_id=target_seat_id,
                damage_taken=damage_taken,
            )

            spell_payload = {
                "spell_ref": spell_ref,
                "spell_level": spell_level,
                "slot_level": effective_slot_level,
                "cast_mode": cast_mode.value,
                "concentration": concentration,
                "save_ability_ref": save_ability_ref,
                "save_dc": effective_save_dc,
                "save_damage_mode": save_damage_mode.value,
                "attack_modifier": effective_attack_modifier,
                "attack_mode": attack_mode.value,
                "damage_parts": _damage_payload(damage_parts),
                "healing_amount": healing_amount,
                "effects": [
                    {"effect_type": item.effect_type, "tag": item.tag, "source_ref": item.source_ref}
                    for item in apply_effects
                ],
            }

            domain_events = list(resolution.events)
            if concentration:
                if previous_concentration is not None:
                    domain_events.append({
                        "type": "concentration_ended",
                        "source_ref": previous_concentration["source_ref"],
                        "reason": "replaced",
                        "removed_effect_ids": sorted(replaced_ids),
                    })
                domain_events.append({
                    "type": "concentration_started",
                    "source_ref": spell_ref,
                    "effect_ids": [effect.effect_id for effect in resolution.applied_effects],
                })

            resolution_payload: dict[str, Any] = {
                "spell_ref": spell_ref,
                "cast_mode": cast_mode.value,
                "target_entry_id": str(target_entry_id) if target_entry_id is not None else None,
                "roll": roll_payload,
                "damage": damage_taken,
                "target_current_hp": resolution.target_hp.current_hp if resolution.target_hp else None,
                "target_temp_hp": resolution.target_hp.temp_hp if resolution.target_hp else None,
                "instant_death": bool(resolution.damage.instant_death) if resolution.damage else False,
                "monster_outcome_required": (
                    bool(resolution.damage.monster_outcome_required) if resolution.damage else False
                ),
                "applied_effect_ids": [effect.effect_id for effect in resolution.applied_effects],
                "concentration_started": concentration,
                "replaced_concentration_effect_ids": sorted(replaced_ids),
                "replaced_effects_removed_from": replaced,
                "concentration_check": concentration_payload,
                "domain_events": domain_events,
            }

            self._write_spell_action_and_event(
                connection,
                event_id=event_id,
                binding=binding,
                combat_id=combat_id,
                action_id=action_id,
                caster_entry_id=caster_entry_id,
                target_entry_id=target_entry_id,
                subject_seat_id=subject_seat_id,
                subject_character_id=None,
                execution_mode=execution_mode,
                spell_payload=spell_payload,
                resolution_payload=resolution_payload,
                roll_payload=roll_payload,
                roll_request_id=roll_request_id,
                roll_result_id=roll_result_id,
                idempotency_key=idempotency_key,
                now=now,
            )

        event = self.event_repository.append(
            room_id=binding.room_id,
            campaign_id=binding.campaign_id,
            session_id=binding.session_id,
            kind="combat.spell_cast_resolved",
            acting_seat_id=binding.seat_id,
            subject_seat_id=subject_seat_id,
            subject_character_id=None,
            execution_mode=execution_mode,
            visibility="public",
            recipient_seat_ids=(),
            payload_version=1,
            payload={"combat_id": str(combat_id), "action_id": str(action_id)},
            idempotency_key=(
                f"p4e-monster-cast:{idempotency_key}" if idempotency_key else None
            ),
            expected_actor_binding=binding,
            transaction_projection=projection,
        )
        canonical_action_id = UUID(str(event.payload["action_id"]))
        stored = self.get_cast_action(session_id=binding.session_id, action_id=canonical_action_id)
        if stored is None:
            raise CombatSpellNotFoundError(str(canonical_action_id))
        return stored, event

    @staticmethod
    def _append_monster_effects_and_conditions(
        conditions: list[dict[str, Any]],
        effects: list[dict[str, Any]],
        applied_effects: tuple[PersistentTemporaryEffect, ...],
        spell_ref: str,
        note_prefix: str = "P4-D",
    ) -> None:
        for effect in applied_effects:
            effects.append(monster_effect_entry(effect))
            condition_ref = condition_ref_for_effect(effect)
            if condition_ref is not None:
                conditions.append(
                    {
                        "condition_ref": condition_ref,
                        "note": f"{note_prefix}: {spell_ref}",
                        "effect_id": effect.effect_id,
                    }
                )

    def _load_spell_target(
        self,
        connection,
        *,
        combat_id: UUID,
        target_entry_id: UUID | None,
        caster_entry: Mapping[str, Any],
        caster_character: tuple[CharacterBuild, CharacterState, int] | None = None,
        caster_monster: Mapping[str, Any] | None = None,
        target_ac: int | None = None,
        save_modifier: int | None = None,
    ) -> tuple[
        Mapping[str, Any] | None,
        tuple[CharacterBuild, CharacterState, int] | None,
        Mapping[str, Any] | None,
        SpellTargetState | None,
    ]:
        if target_entry_id is None:
            return None, None, None, None

        target_is_caster = target_entry_id == caster_entry["id"]
        target_entry = (
            caster_entry
            if target_is_caster
            else self._lock_entry(connection, combat_id=combat_id, entry_id=target_entry_id)
        )
        target_character: tuple[CharacterBuild, CharacterState, int] | None = None
        target_monster: Mapping[str, Any] | None = None

        if target_entry["subject_kind"] == "character":
            character_id = target_entry["character_id"]
            if character_id is None:
                raise CombatSpellStateConflictError("Character target has no Character identity")
            target_character = (
                caster_character
                if (caster_character is not None and character_id == caster_entry.get("character_id"))
                else self._load_character_state(connection, character_id)
            )
            build, state, _revision = target_character
            domain_target = SpellTargetState(
                target_ref=str(target_entry_id),
                target_kind=TargetKind.CHARACTER,
                hp=HitPointState(
                    current_hp=state.current_hp,
                    max_hp=calculate_max_hp(build),
                    temp_hp=state.temporary_hp,
                ),
                target_ac=target_ac,
                save_modifier=save_modifier,
                death_saves=_death_state(target_entry),
            )
        elif target_entry["subject_kind"] == "monster":
            monster_id = target_entry["monster_instance_id"]
            if monster_id is None:
                raise CombatSpellStateConflictError("Monster target has no Monster identity")
            target_monster = (
                caster_monster
                if (caster_monster is not None and target_is_caster)
                else connection.execute(
                    select(monster_instances)
                    .where(monster_instances.c.id == monster_id)
                    .with_for_update()
                ).mappings().one_or_none()
            )
            if target_monster is None:
                raise CombatSpellNotFoundError(str(monster_id))
            rules = dict(target_monster["rules_snapshot"] or {})
            resistances, immunities, vulnerabilities = _damage_affinities(rules)
            monster_ac = rules.get("armor_class")
            domain_target = SpellTargetState(
                target_ref=str(target_entry_id),
                target_kind=TargetKind.MONSTER,
                hp=HitPointState(
                    current_hp=int(target_monster["current_hp"]),
                    max_hp=int(rules["max_hp"]),
                    temp_hp=int(target_monster["temp_hp"]),
                ),
                target_ac=(
                    target_ac
                    if target_ac is not None
                    else (int(monster_ac) if isinstance(monster_ac, int) else None)
                ),
                save_modifier=save_modifier,
                resistances=resistances,
                immunities=immunities,
                vulnerabilities=vulnerabilities,
            )
        else:
            raise CombatSpellStateConflictError("unsupported spell target kind")

        return target_entry, target_character, target_monster, domain_target

    def _write_spell_target_state(
        self,
        connection,
        *,
        target_entry: Mapping[str, Any],
        target_character: tuple[CharacterBuild, CharacterState, int] | None,
        target_monster: Mapping[str, Any] | None,
        resolution: Any,
        spell_ref: str,
        replaced_ids: set[str] = frozenset(),
        note_prefix: str = "P4-D",
        now: datetime,
    ) -> _DamagedTargetConcentration | None:
        if target_character is not None:
            _build, state, revision = target_character
            payload = state.model_dump(mode="json")
            if replaced_ids:
                strip_effects_from_state_payload(payload, replaced_ids)
            if resolution.target_hp is not None:
                self._apply_target_hp_to_payload(
                    payload, resolution, f"{note_prefix}: spell reduced target to zero hit points"
                )
                connection.execute(
                    update(combat_entries)
                    .where(combat_entries.c.id == target_entry["id"])
                    .values(**_death_values(resolution.target_death_saves), updated_at=now)
                )
            self._attach_effects_to_payload(
                payload, resolution.applied_effects, spell_ref, note_prefix=note_prefix
            )
            self._write_character_state(
                connection, target_entry["character_id"], revision, payload
            )
            state_after = CharacterState.model_validate(payload)
            if state_after.concentration is not None:
                return _DamagedTargetConcentration(
                    entry_id=target_entry["id"],
                    character_id=target_entry["character_id"],
                    concentration=state_after.concentration,
                )
            return None
        elif target_monster is not None:
            values: dict[str, Any] = {"updated_at": now}
            conditions = list(target_monster["conditions"] or [])
            effects = list(target_monster["effects"] or [])
            if replaced_ids:
                conditions, _ = strip_monster_items(conditions, replaced_ids)
                effects, _ = strip_monster_items(effects, replaced_ids)
            if resolution.target_hp is not None:
                values["current_hp"] = resolution.target_hp.current_hp
                values["temp_hp"] = resolution.target_hp.temp_hp
            self._append_monster_effects_and_conditions(
                conditions=conditions,
                effects=effects,
                applied_effects=resolution.applied_effects,
                spell_ref=spell_ref,
                note_prefix=note_prefix,
            )
            values["conditions"] = conditions
            values["effects"] = effects
            connection.execute(
                update(monster_instances)
                .where(monster_instances.c.id == target_monster["id"])
                .values(**values)
            )
            if target_monster.get("concentration") is not None:
                return _DamagedTargetConcentration(
                    entry_id=target_entry["id"],
                    character_id=None,
                    concentration=CharacterConcentrationState.model_validate(
                        target_monster["concentration"]
                    ),
                )
            return None
        return None

    @staticmethod
    def _insert_spell_formal_roll(
        connection,
        *,
        binding: StoredTableActorBinding,
        cast_mode: SpellCastMode,
        resolution: Any,
        attack_modifier: int | None,
        attack_d20s: tuple[int, ...],
        attack_mode: RollMode,
        save_ability_ref: str | None,
        save_dc: int | None,
        save_modifier: int | None,
        save_d20: int | None,
        spell_ref: str,
        subject_seat_id: UUID | None,
        target_seat_id: UUID | None,
        caster_entry_id: UUID,
        target_entry_id: UUID | None,
        caster_character_id: UUID | None,
        target_character_id: UUID | None,
        roll_source: str,
        roll_group_id: UUID,
        roll_request_id: UUID,
        roll_result_id: UUID,
        now: datetime,
    ) -> dict[str, object] | None:
        if cast_mode not in {SpellCastMode.ATTACK, SpellCastMode.SAVE}:
            return None
        assert target_entry_id is not None
        if cast_mode is SpellCastMode.ATTACK:
            attack_event = next(item for item in resolution.events if item["type"] == "attack_roll")
            modifier = int(attack_modifier or 0)
            raw_dice = list(attack_d20s)
            kept_dice = [int(attack_event["d20"])]
            total = int(attack_event["total"])
            request_type, ability_ref, dc = "other", None, None
            label = f"Spell attack: {spell_ref}"
            request_target_seat = subject_seat_id
            request_target_character = caster_character_id
            request_target_entry = caster_entry_id
            subject_character_id = caster_character_id
            subject_combat_entry_id = caster_entry_id
        else:
            save_event = next(item for item in resolution.events if item["type"] == "saving_throw")
            modifier = int(save_modifier or 0)
            raw_dice = [int(save_d20 or 0)]
            kept_dice = raw_dice
            total = int(save_event["total"])
            request_type, ability_ref, dc = "saving_throw", save_ability_ref, save_dc
            label = f"Spell save: {spell_ref}"
            request_target_seat = target_seat_id
            request_target_character = target_character_id
            request_target_entry = target_entry_id
            subject_character_id = target_character_id
            subject_combat_entry_id = target_entry_id

        connection.execute(
            insert(roll_groups).values(
                id=roll_group_id,
                session_id=binding.session_id,
                requested_by_seat_id=binding.seat_id,
                label=label,
                visibility="public",
                version=1,
            )
        )
        connection.execute(
            insert(roll_requests).values(
                id=roll_request_id,
                session_id=binding.session_id,
                roll_group_id=roll_group_id,
                target_seat_id=request_target_seat,
                target_character_id=request_target_character,
                target_combat_entry_id=request_target_entry,
                request_type=request_type,
                ability_ref=ability_ref,
                skill_ref=None,
                dc=dc,
                modifier_mode=attack_mode.value if cast_mode is SpellCastMode.ATTACK else "normal",
                flat_adjustment=0,
                visibility="public",
                status="resolved",
                requested_by_seat_id=binding.seat_id,
                resolved_at=now,
                version=2,
            )
        )
        connection.execute(
            insert(roll_results).values(
                id=roll_result_id,
                roll_request_id=roll_request_id,
                session_id=binding.session_id,
                acting_seat_id=binding.seat_id,
                subject_seat_id=request_target_seat,
                subject_character_id=subject_character_id,
                subject_combat_entry_id=subject_combat_entry_id,
                execution_mode="system",
                source=roll_source,
                formula=f"1d20 + {modifier}",
                raw_dice=raw_dice,
                kept_dice=kept_dice,
                base_modifier=modifier,
                flat_adjustment=0,
                total=total,
                visibility="public",
            )
        )
        return {
            "roll_group_id": str(roll_group_id),
            "roll_request_id": str(roll_request_id),
            "roll_result_id": str(roll_result_id),
            "raw_dice": raw_dice,
            "kept_dice": kept_dice,
            "modifier": modifier,
            "total": total,
        }

    @staticmethod
    def _request_concentration_check_for_damaged_target(
        connection,
        *,
        binding: StoredTableActorBinding,
        damaged_target: _DamagedTargetConcentration | None,
        target_entry_id: UUID | None,
        target_seat_id: UUID | None,
        damage_taken: int,
    ) -> dict[str, object] | None:
        if damaged_target is None or target_entry_id is None or damage_taken <= 0:
            return None
        source_ref = damaged_target.concentration.source_ref
        concentration_group_id = uuid4()
        concentration_request_id = uuid4()
        dc = concentration_dc(damage_taken)
        connection.execute(
            insert(roll_groups).values(
                id=concentration_group_id,
                session_id=binding.session_id,
                requested_by_seat_id=binding.seat_id,
                label="Concentration",
                visibility="public",
                version=1,
            )
        )
        effective_target_seat = (
            damaged_target.target_seat_id
            if damaged_target.target_seat_id is not None
            else target_seat_id
        )
        connection.execute(
            insert(roll_requests).values(
                id=concentration_request_id,
                session_id=binding.session_id,
                roll_group_id=concentration_group_id,
                target_seat_id=effective_target_seat,
                target_character_id=damaged_target.character_id,
                target_combat_entry_id=damaged_target.entry_id,
                request_type="saving_throw",
                ability_ref="srd5.1:ability:constitution",
                skill_ref=None,
                dc=dc,
                modifier_mode="normal",
                flat_adjustment=0,
                visibility="public",
                status="pending",
                requested_by_seat_id=binding.seat_id,
                version=1,
            )
        )
        return {
            "target_entry_id": str(damaged_target.entry_id),
            "target_character_id": (
                str(damaged_target.character_id)
                if damaged_target.character_id is not None
                else None
            ),
            "source_ref": str(source_ref),
            "damage_taken": damage_taken,
            "dc": dc,
            "roll_group_id": str(concentration_group_id),
            "roll_request_id": str(concentration_request_id),
        }

    @staticmethod
    def _write_spell_action_and_event(
        connection,
        *,
        event_id: UUID,
        binding: StoredTableActorBinding,
        combat_id: UUID,
        action_id: UUID,
        caster_entry_id: UUID,
        target_entry_id: UUID | None,
        subject_seat_id: UUID | None,
        subject_character_id: UUID | None,
        execution_mode: str,
        spell_payload: dict[str, Any],
        resolution_payload: dict[str, Any],
        roll_payload: dict[str, object] | None,
        roll_request_id: UUID,
        roll_result_id: UUID,
        idempotency_key: str | None,
        now: datetime,
    ) -> None:
        connection.execute(
            insert(combat_actions).values(
                id=action_id,
                combat_id=combat_id,
                entry_id=caster_entry_id,
                target_entry_id=target_entry_id,
                session_id=binding.session_id,
                acting_seat_id=binding.seat_id,
                subject_seat_id=subject_seat_id,
                execution_mode=execution_mode,
                action_kind="spell_cast",
                economy_cost="action",
                payload={"spell": spell_payload},
                resolution_status="resolved",
                roll_request_id=roll_request_id if roll_payload is not None else None,
                roll_result_id=roll_result_id if roll_payload is not None else None,
                resolution_result=resolution_payload,
                idempotency_key=idempotency_key,
            )
        )
        connection.execute(
            update(session_events)
            .where(session_events.c.id == event_id)
            .values(
                subject_character_id=subject_character_id,
                payload={
                    "combat_id": str(combat_id),
                    "action_id": str(action_id),
                    "caster_entry_id": str(caster_entry_id),
                    **resolution_payload,
                },
            )
        )
        connection.execute(
            update(combats)
            .where(combats.c.id == combat_id)
            .values(revision=combats.c.revision + 1, updated_at=now)
        )

    @staticmethod
    def _apply_target_hp_to_payload(payload: dict[str, Any], resolution, note: str) -> None:
        assert resolution.target_hp is not None
        payload["current_hp"] = resolution.target_hp.current_hp
        payload["temporary_hp"] = resolution.target_hp.temp_hp
        if resolution.target_death_saves is not None:
            payload["death_saves"] = {
                "successes": resolution.target_death_saves.successes,
                "failures": resolution.target_death_saves.failures,
                "stable": resolution.target_death_saves.stable,
                "dead": resolution.target_death_saves.dead,
            }
        conditions = list(payload.get("conditions", []))
        if resolution.damage is not None:
            if resolution.damage.apply_unconscious:
                _add_condition(conditions, UNCONSCIOUS_REF, note)
            if resolution.damage.apply_prone:
                _add_condition(conditions, PRONE_REF, note)
        payload["conditions"] = conditions

    @staticmethod
    def _attach_effects_to_payload(
        payload: dict[str, Any],
        effects: tuple[PersistentTemporaryEffect, ...],
        spell_ref: str,
        note_prefix: str = "P4-D",
    ) -> None:
        temporary_effects = list(payload.get("temporary_effects", []))
        conditions = list(payload.get("conditions", []))
        present = {item.get("effect_id") for item in temporary_effects}
        for effect in effects:
            if effect.effect_id not in present:
                temporary_effects.append(effect.model_dump(mode="json"))
            condition_ref = condition_ref_for_effect(effect)
            if condition_ref is not None and not any(
                item.get("condition_ref") == condition_ref for item in conditions
            ):
                conditions.append(
                    {
                        "condition_ref": condition_ref,
                        "note": f"{note_prefix}: {spell_ref}",
                        "effect_id": effect.effect_id,
                    }
                )
        payload["temporary_effects"] = temporary_effects
        payload["conditions"] = conditions

    @staticmethod
    def _write_character_state(connection, character_id: UUID, revision: int, payload: dict[str, Any]) -> None:
        result = connection.execute(
            update(character_states)
            .where(
                character_states.c.character_id == character_id,
                character_states.c.state_revision == revision,
            )
            .values(
                state_payload=CharacterState.model_validate(payload).model_dump(mode="json"),
                state_revision=revision + 1,
                updated_at=datetime.now().astimezone(),
            )
        )
        if result.rowcount != 1:
            raise CombatSpellStateConflictError("Character State changed while resolving spell")

__all__ = [
    "CombatSpellNotFoundError",
    "CombatSpellRepository",
    "CombatSpellStateConflictError",
    "StoredAoeSpellAction",
    "StoredSpellCastAction",
]
