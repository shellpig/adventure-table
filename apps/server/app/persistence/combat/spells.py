from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping
from uuid import UUID, uuid4

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Engine

from app.domain.character.schemas import CharacterBuild, CharacterState
from app.domain.combat.aoe_adjudication import (
    AoeAdjudication,
    AoeTargetState,
    confirm_aoe,
    propose_aoe,
    resolve_aoe_save_spell,
)
from app.domain.combat.concentration_triggers import concentration_dc
from app.domain.combat.resolution import DamageRollPart, HitPointState, TargetKind
from app.domain.combat.spell_resolver import SaveDamageMode, SpellCastMode, SpellResolutionSpec
from app.domain.combat.spell_resources import authorize_character_spell
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


class CombatSpellNotFoundError(LookupError):
    pass


class CombatSpellStateConflictError(RuntimeError):
    pass


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
    """Durable P4-D AoE spell transaction boundary.

    Target confirmation, formal save results, the caster spell resource, action
    economy, every target state mutation, concentration follow-up requests and
    the durable Session event commit through one TableEventRepository projection.
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


__all__ = [
    "CombatSpellNotFoundError",
    "CombatSpellRepository",
    "CombatSpellStateConflictError",
    "StoredAoeSpellAction",
]
