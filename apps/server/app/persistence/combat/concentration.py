from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Engine

from app.domain.character.schemas import CharacterConcentrationState, CharacterState
from app.domain.combat.concentration_triggers import (
    ConcentrationCheckRequest,
    evaluate_concentration_check,
    resolve_concentration_check,
)
from app.persistence.characters import character_states
from app.persistence.combat.effects import (
    strip_monster_items,
    strip_effects_from_state_payload,
    strip_linked_effects,
)
from app.persistence.combat.tables import combat_entries, combats, monster_instances
from app.persistence.rooms.p3c_runtime import roll_groups, roll_requests, roll_results
from app.persistence.rooms.table_runtime import (
    StoredTableActorBinding,
    StoredTableEvent,
    TableEventRepository,
    session_events,
)


class CombatConcentrationNotFoundError(LookupError):
    pass


class CombatConcentrationStateConflictError(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredConcentrationRequest:
    id: UUID
    roll_group_id: UUID | None
    session_id: UUID
    target_seat_id: UUID | None
    target_character_id: UUID | None
    target_combat_entry_id: UUID
    request_type: str
    ability_ref: str | None
    dc: int | None
    modifier_mode: str
    flat_adjustment: int
    visibility: str
    status: str
    roll_group_label: str | None


@dataclass(frozen=True)
class StoredConcentrationResolution:
    event_id: UUID
    roll_request_id: UUID
    roll_result_id: UUID
    target_entry_id: UUID
    source_ref: str
    damage_taken: int
    dc: int
    total: int
    succeeded: bool


def _stored(event: StoredTableEvent) -> StoredConcentrationResolution:
    payload = dict(event.payload)
    return StoredConcentrationResolution(
        event_id=event.id,
        roll_request_id=UUID(str(payload["roll_request_id"])),
        roll_result_id=UUID(str(payload["roll_result_id"])),
        target_entry_id=UUID(str(payload["target_entry_id"])),
        source_ref=str(payload["source_ref"]),
        damage_taken=int(payload["damage_taken"]),
        dc=int(payload["dc"]),
        total=int(payload["total"]),
        succeeded=bool(payload["succeeded"]),
    )


class CombatConcentrationRepository:
    """Resolve P4-D damage-triggered Concentration saves atomically.

    Damage and spell transactions create the pending formal CON RollRequest and
    store its exact source/damage/DC metadata in their durable event. This
    repository resolves that request, the formal RollResult, canonical Character
    State and the concentration-resolution event in one transaction projection.
    """

    def __init__(self, engine: Engine, event_repository: TableEventRepository) -> None:
        self.engine = engine
        self.event_repository = event_repository

    @staticmethod
    def _source_metadata(connection, *, session_id: UUID, request_id: UUID) -> dict[str, object]:
        rows = connection.execute(
            select(session_events.c.kind, session_events.c.payload)
            .where(session_events.c.session_id == session_id)
            .order_by(session_events.c.seq.desc())
        ).mappings()
        request_text = str(request_id)
        for row in rows:
            payload = dict(row["payload"] or {})
            direct = payload.get("concentration_check")
            if isinstance(direct, dict) and str(direct.get("roll_request_id")) == request_text:
                return dict(direct)
            group = payload.get("concentration_checks")
            if isinstance(group, list):
                for item in group:
                    if isinstance(item, dict) and str(item.get("roll_request_id")) == request_text:
                        return dict(item)
        raise CombatConcentrationNotFoundError(str(request_id))

    @staticmethod
    def _existing_resolution(
        connection, *, session_id: UUID, request_id: UUID
    ) -> StoredTableEvent | None:
        rows = connection.execute(
            select(session_events)
            .where(
                session_events.c.session_id == session_id,
                session_events.c.kind == "combat.concentration_resolved",
            )
            .order_by(session_events.c.seq.desc())
        ).mappings()
        request_text = str(request_id)
        for row in rows:
            payload = dict(row["payload"] or {})
            if str(payload.get("roll_request_id")) == request_text:
                return TableEventRepository._event(row)
        return None

    def get_request(
        self, *, session_id: UUID, request_id: UUID
    ) -> StoredConcentrationRequest | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(
                    roll_requests,
                    roll_groups.c.label.label("roll_group_label"),
                )
                .outerjoin(roll_groups, roll_groups.c.id == roll_requests.c.roll_group_id)
                .where(
                    roll_requests.c.id == request_id,
                    roll_requests.c.session_id == session_id,
                    roll_requests.c.target_combat_entry_id.is_not(None),
                )
            ).mappings().one_or_none()
        if row is None:
            return None
        return StoredConcentrationRequest(
            id=row["id"],
            roll_group_id=row["roll_group_id"],
            session_id=row["session_id"],
            target_seat_id=row["target_seat_id"],
            target_character_id=row["target_character_id"],
            target_combat_entry_id=row["target_combat_entry_id"],
            request_type=row["request_type"],
            ability_ref=row["ability_ref"],
            dc=row["dc"],
            modifier_mode=row["modifier_mode"],
            flat_adjustment=int(row["flat_adjustment"]),
            visibility=row["visibility"],
            status=row["status"],
            roll_group_label=row["roll_group_label"],
        )

    def get_resolution_event(
        self, *, session_id: UUID, request_id: UUID
    ) -> StoredTableEvent | None:
        with self.engine.connect() as connection:
            return self._existing_resolution(
                connection, session_id=session_id, request_id=request_id
            )

    def complete_check(
        self,
        *,
        binding: StoredTableActorBinding,
        request_id: UUID,
        acting_seat_id: UUID,
        execution_mode: str,
        d20: int,
        constitution_save_modifier: int,
        roll_source: str,
        idempotency_key: str | None,
    ) -> tuple[StoredConcentrationResolution, StoredTableEvent]:
        if d20 < 1 or d20 > 20:
            raise ValueError("concentration saving throw d20 must be between 1 and 20")
        if roll_source not in {"server", "physical"}:
            raise ValueError("concentration roll_source must be server or physical")
        result_id = uuid4()

        def projection(connection, event_id: UUID, _seq: int) -> None:
            request = connection.execute(
                select(roll_requests)
                .where(
                    roll_requests.c.id == request_id,
                    roll_requests.c.session_id == binding.session_id,
                )
                .with_for_update()
            ).mappings().one_or_none()
            if request is None:
                raise CombatConcentrationNotFoundError(str(request_id))
            group = connection.execute(
                select(roll_groups)
                .where(
                    roll_groups.c.id == request["roll_group_id"],
                    roll_groups.c.session_id == binding.session_id,
                )
                .with_for_update()
            ).mappings().one_or_none()
            if (
                group is None
                or group["label"] != "Concentration"
                or request["request_type"] != "saving_throw"
                or request["ability_ref"] != "srd5.1:ability:constitution"
            ):
                raise CombatConcentrationNotFoundError(str(request_id))
            if request["status"] != "pending":
                raise CombatConcentrationStateConflictError(
                    "Concentration RollRequest is already resolved"
                )
            target_entry_id = request["target_combat_entry_id"]
            if target_entry_id is None:
                raise CombatConcentrationStateConflictError(
                    "Concentration save must target a CombatEntry"
                )
            entry = connection.execute(
                select(combat_entries)
                .where(
                    combat_entries.c.id == target_entry_id,
                    combat_entries.c.status == "active",
                )
                .with_for_update()
            ).mappings().one_or_none()
            if entry is None:
                raise CombatConcentrationNotFoundError(str(target_entry_id))

            metadata = self._source_metadata(
                connection,
                session_id=binding.session_id,
                request_id=request_id,
            )
            dc = int(metadata["dc"])
            if request["dc"] is None or int(request["dc"]) != dc:
                raise CombatConcentrationStateConflictError(
                    "Concentration request DC no longer matches its source event"
                )

            total = d20 + constitution_save_modifier
            now = datetime.now().astimezone()

            if entry["subject_kind"] == "character":
                target_character_id = request["target_character_id"]
                if target_character_id is None or entry["character_id"] != target_character_id:
                    raise CombatConcentrationStateConflictError(
                        "Concentration save must target a Character CombatEntry"
                    )
                state_row = connection.execute(
                    select(
                        character_states.c.state_payload,
                        character_states.c.state_revision,
                    )
                    .where(character_states.c.character_id == target_character_id)
                    .with_for_update()
                ).mappings().one_or_none()
                if state_row is None:
                    raise CombatConcentrationNotFoundError(str(target_character_id))

                concentration_request = ConcentrationCheckRequest(
                    owner_ref=str(target_character_id),
                    source_ref=str(metadata["source_ref"]),
                    damage_taken=int(metadata["damage_taken"]),
                    dc=dc,
                )
                state = CharacterState.model_validate(state_row["state_payload"])
                linked_effect_ids = (
                    tuple(state.concentration.effect_ids) if state.concentration is not None else ()
                )
                resolved = resolve_concentration_check(
                    request=concentration_request,
                    state=state,
                    d20=d20,
                    constitution_save_modifier=constitution_save_modifier,
                )
                succeeded = resolved.success
                domain_events = list(resolved.events)
                next_payload = resolved.state.model_dump(mode="json")
                removed_from: list[dict[str, object]] = []
                if not succeeded:
                    strip_effects_from_state_payload(next_payload, set(linked_effect_ids))
                    removed_from = strip_linked_effects(
                        connection,
                        combat_id=entry["combat_id"],
                        effect_ids=linked_effect_ids,
                        now=now,
                        skip_character_ids=(target_character_id,),
                    )
                revision = int(state_row["state_revision"])
                state_update = connection.execute(
                    update(character_states)
                    .where(
                        character_states.c.character_id == target_character_id,
                        character_states.c.state_revision == revision,
                    )
                    .values(
                        state_payload=CharacterState.model_validate(next_payload).model_dump(mode="json"),
                        state_revision=revision + 1,
                        updated_at=now,
                    )
                )
                if state_update.rowcount != 1:
                    raise CombatConcentrationStateConflictError(
                        "Character State changed while resolving Concentration"
                    )
            elif entry["subject_kind"] == "monster":
                monster_id = entry["monster_instance_id"]
                if monster_id is None:
                    raise CombatConcentrationStateConflictError(
                        "Monster CombatEntry has no Monster Instance identity"
                    )
                monster = connection.execute(
                    select(monster_instances)
                    .where(monster_instances.c.id == monster_id)
                    .with_for_update()
                ).mappings().one_or_none()
                if monster is None:
                    raise CombatConcentrationNotFoundError(str(monster_id))

                current_conc = (
                    CharacterConcentrationState.model_validate(monster["concentration"])
                    if monster["concentration"]
                    else None
                )
                concentration_request = ConcentrationCheckRequest(
                    owner_ref=str(monster_id),
                    source_ref=str(metadata["source_ref"]),
                    damage_taken=int(metadata["damage_taken"]),
                    dc=dc,
                )
                succeeded, total, domain_events = evaluate_concentration_check(
                    request=concentration_request,
                    current=current_conc,
                    d20=d20,
                    constitution_save_modifier=constitution_save_modifier,
                )
                target_character_id = None
                linked_effect_ids = (
                    tuple(current_conc.effect_ids) if current_conc is not None else ()
                )
                removed_from = []
                if not succeeded:
                    conditions, _ = strip_monster_items(list(monster["conditions"] or []), set(linked_effect_ids))
                    effects, _ = strip_monster_items(list(monster["effects"] or []), set(linked_effect_ids))
                    connection.execute(
                        update(monster_instances)
                        .where(monster_instances.c.id == monster_id)
                        .values(
                            concentration=None,
                            conditions=conditions,
                            effects=effects,
                            updated_at=now,
                        )
                    )
                    removed_from = strip_linked_effects(
                        connection,
                        combat_id=entry["combat_id"],
                        effect_ids=linked_effect_ids,
                        now=now,
                        skip_monster_ids=(monster_id,),
                    )
            else:
                raise CombatConcentrationStateConflictError("unsupported CombatEntry subject kind")

            connection.execute(
                insert(roll_results).values(
                    id=result_id,
                    roll_request_id=request_id,
                    session_id=binding.session_id,
                    acting_seat_id=acting_seat_id,
                    subject_seat_id=request["target_seat_id"],
                    subject_character_id=target_character_id,
                    subject_combat_entry_id=target_entry_id,
                    execution_mode=execution_mode,
                    source=roll_source,
                    formula=f"1d20 + {constitution_save_modifier}",
                    raw_dice=[d20],
                    kept_dice=[d20],
                    base_modifier=constitution_save_modifier,
                    flat_adjustment=0,
                    total=total,
                    visibility=request["visibility"],
                )
            )
            connection.execute(
                update(roll_requests)
                .where(roll_requests.c.id == request_id)
                .values(
                    status="resolved",
                    resolved_at=now,
                    version=roll_requests.c.version + 1,
                )
            )
            connection.execute(
                update(combats)
                .where(combats.c.id == entry["combat_id"])
                .values(revision=combats.c.revision + 1, updated_at=now)
            )
            connection.execute(
                update(session_events)
                .where(session_events.c.id == event_id)
                .values(
                    subject_character_id=target_character_id,
                    payload={
                        "combat_id": str(entry["combat_id"]),
                        "roll_request_id": str(request_id),
                        "roll_result_id": str(result_id),
                        "target_entry_id": str(target_entry_id),
                        "target_is_hostile": bool(entry["is_hostile"]),
                        "source_ref": str(metadata["source_ref"]),
                        "damage_taken": int(metadata["damage_taken"]),
                        "dc": dc,
                        "d20": d20,
                        "modifier": constitution_save_modifier,
                        "total": total,
                        "succeeded": succeeded,
                        "linked_effect_ids": list(linked_effect_ids),
                        "linked_effects_removed_from": removed_from,
                        "domain_events": domain_events,
                    },
                )
            )

        event = self.event_repository.append(
            room_id=binding.room_id,
            campaign_id=binding.campaign_id,
            session_id=binding.session_id,
            kind="combat.concentration_resolved",
            acting_seat_id=acting_seat_id,
            subject_seat_id=None,
            subject_character_id=None,
            execution_mode=execution_mode,
            visibility="public",
            recipient_seat_ids=(),
            payload_version=1,
            payload={"roll_request_id": str(request_id)},
            idempotency_key=(
                f"p4d-concentration-result:{idempotency_key}"
                if idempotency_key
                else None
            ),
            expected_actor_binding=binding,
            transaction_projection=projection,
        )
        return _stored(event), event


__all__ = [
    "CombatConcentrationNotFoundError",
    "CombatConcentrationRepository",
    "CombatConcentrationStateConflictError",
    "StoredConcentrationRequest",
    "StoredConcentrationResolution",
]
