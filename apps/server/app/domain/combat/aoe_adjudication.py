from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal, Mapping

from app.domain.character.schemas import CharacterState, ResourceCounter
from app.domain.combat.resolution import (
    DamageRollPart,
    DamageType,
    DeathSaveState,
    HitPointState,
    TargetKind,
    apply_damage,
)
from app.domain.combat.spell_resolver import (
    SaveDamageMode,
    SpellCastMode,
    SpellResolutionSpec,
    half_damage_parts,
)
from app.domain.combat.spell_resources import (
    CharacterSpellAuthorization,
    MonsterSpellSource,
    spend_character_spell,
    spend_monster_spell,
)


AoeStatus = Literal["proposed", "confirmed", "resolved", "cancelled"]


@dataclass(frozen=True)
class AoeAdjudication:
    command_id: str
    acting_entry_id: str
    proposed_target_ids: tuple[str, ...]
    confirmed_target_ids: tuple[str, ...] = ()
    status: AoeStatus = "proposed"

    def __post_init__(self) -> None:
        if not self.command_id.strip() or not self.acting_entry_id.strip():
            raise ValueError("AoE command and acting entry are required")
        if not self.proposed_target_ids:
            raise ValueError("AoE requires at least one proposed target")
        if len(self.proposed_target_ids) != len(set(self.proposed_target_ids)):
            raise ValueError("AoE proposed targets must be unique")
        if len(self.confirmed_target_ids) != len(set(self.confirmed_target_ids)):
            raise ValueError("AoE confirmed targets must be unique")

    def to_payload(self) -> dict[str, object]:
        return {
            "version": 1,
            "command_id": self.command_id,
            "acting_entry_id": self.acting_entry_id,
            "proposed_target_ids": list(self.proposed_target_ids),
            "confirmed_target_ids": list(self.confirmed_target_ids),
            "status": self.status,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "AoeAdjudication":
        return cls(
            command_id=str(payload["command_id"]),
            acting_entry_id=str(payload["acting_entry_id"]),
            proposed_target_ids=tuple(
                str(value) for value in payload.get("proposed_target_ids", ())
            ),
            confirmed_target_ids=tuple(
                str(value) for value in payload.get("confirmed_target_ids", ())
            ),
            status=str(payload.get("status", "proposed")),  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class AoeTargetState:
    entry_id: str
    target_kind: TargetKind
    hp: HitPointState
    save_modifier: int
    death_saves: DeathSaveState | None = None
    resistances: tuple[DamageType, ...] = ()
    immunities: tuple[DamageType, ...] = ()
    vulnerabilities: tuple[DamageType, ...] = ()


@dataclass(frozen=True)
class AoeTargetOutcome:
    entry_id: str
    save_total: int
    saved: bool
    hp: HitPointState
    damage_taken: int
    death_saves: DeathSaveState | None = None
    apply_unconscious: bool = False
    apply_prone: bool = False
    instant_death: bool = False
    monster_outcome_required: bool = False


@dataclass(frozen=True)
class AoeResolution:
    adjudication: AoeAdjudication
    outcomes: tuple[AoeTargetOutcome, ...]
    events: tuple[dict[str, object], ...]
    character_state: CharacterState | None = None
    monster_resources: dict[str, int | ResourceCounter] | None = None


def propose_aoe(
    *, command_id: str, acting_entry_id: str, target_ids: tuple[str, ...]
) -> AoeAdjudication:
    """Create identity-only Quick Combat targeting; no fake geometry is stored."""

    return AoeAdjudication(command_id, acting_entry_id, target_ids)


def confirm_aoe(
    adjudication: AoeAdjudication, *, confirmed_target_ids: tuple[str, ...]
) -> AoeAdjudication:
    if adjudication.status != "proposed":
        raise ValueError("AoE adjudication is not awaiting confirmation")
    if not confirmed_target_ids:
        raise ValueError("confirmed AoE target set cannot be empty")
    if not set(confirmed_target_ids).issubset(set(adjudication.proposed_target_ids)):
        raise ValueError("confirmed AoE targets must come from the proposed identity set")
    return replace(
        adjudication,
        confirmed_target_ids=confirmed_target_ids,
        status="confirmed",
    )


def cancel_aoe(adjudication: AoeAdjudication) -> AoeAdjudication:
    if adjudication.status in {"resolved", "cancelled"}:
        return adjudication
    return replace(adjudication, status="cancelled")


def _resolve_confirmed_targets(
    *,
    adjudication: AoeAdjudication,
    spec: SpellResolutionSpec,
    targets: Mapping[str, AoeTargetState],
    save_d20s: Mapping[str, int],
    damage_parts: tuple[DamageRollPart, ...],
    resource_event: dict[str, object] | None,
) -> tuple[tuple[AoeTargetOutcome, ...], tuple[dict[str, object], ...]]:
    if adjudication.status != "confirmed":
        raise ValueError("AoE must be DM-confirmed before resolution")
    if spec.cast_mode is not SpellCastMode.SAVE or spec.save_dc is None:
        raise ValueError("AoE group resolver requires a save-based spell")

    confirmed = adjudication.confirmed_target_ids
    if set(targets) != set(confirmed) or set(save_d20s) != set(confirmed):
        raise ValueError("AoE target state and save rolls must exactly match confirmed targets")
    if any(value < 1 or value > 20 for value in save_d20s.values()):
        raise ValueError("AoE saving throw d20 must be between 1 and 20")

    events: list[dict[str, object]] = [
        {
            "type": "aoe_targets_confirmed",
            "command_id": adjudication.command_id,
            "target_entry_ids": list(confirmed),
        }
    ]
    if resource_event is not None:
        events.append(resource_event)

    outcomes: list[AoeTargetOutcome] = []
    for entry_id in confirmed:
        target = targets[entry_id]
        d20 = save_d20s[entry_id]
        total = d20 + target.save_modifier
        saved = total >= spec.save_dc
        parts = damage_parts
        if saved and spec.save_damage_mode is SaveDamageMode.NONE:
            parts = ()
        elif saved and spec.save_damage_mode is SaveDamageMode.HALF:
            parts = half_damage_parts(parts)
        if parts:
            damage = apply_damage(
                target.hp,
                parts,
                target_kind=target.target_kind,
                resistances=target.resistances,
                immunities=target.immunities,
                vulnerabilities=target.vulnerabilities,
                death_saves=target.death_saves,
            )
            hp = damage.after
            amount = damage.adjusted_total
            death_saves = damage.death_saves
            apply_unconscious = damage.apply_unconscious
            apply_prone = damage.apply_prone
            instant_death = damage.instant_death
            monster_outcome_required = damage.monster_outcome_required
        else:
            hp = target.hp
            amount = 0
            death_saves = target.death_saves
            apply_unconscious = False
            apply_prone = False
            instant_death = False
            monster_outcome_required = False
        outcomes.append(
            AoeTargetOutcome(
                entry_id=entry_id,
                save_total=total,
                saved=saved,
                hp=hp,
                damage_taken=amount,
                death_saves=death_saves,
                apply_unconscious=apply_unconscious,
                apply_prone=apply_prone,
                instant_death=instant_death,
                monster_outcome_required=monster_outcome_required,
            )
        )
        events.append(
            {
                "type": "aoe_target_resolved",
                "command_id": adjudication.command_id,
                "target_entry_id": entry_id,
                "save_total": total,
                "saved": saved,
                "damage": amount,
            }
        )
    return tuple(outcomes), tuple(events)


def resolve_aoe_save_spell(
    *,
    adjudication: AoeAdjudication,
    spec: SpellResolutionSpec,
    state: CharacterState,
    authorization: CharacterSpellAuthorization,
    targets: Mapping[str, AoeTargetState],
    save_d20s: Mapping[str, int],
    damage_parts: tuple[DamageRollPart, ...],
) -> AoeResolution:
    """Resolve a character AoE and spend through the canonical spell resource layer."""

    if authorization.spell_ref != spec.spell_ref:
        raise ValueError("AoE spell authorization does not match resolution spec")
    if authorization.slot_level < spec.minimum_slot_level:
        raise ValueError("AoE spell authorization is below the spell minimum")
    spend = spend_character_spell(state=state, authorization=authorization)
    outcomes, events = _resolve_confirmed_targets(
        adjudication=adjudication,
        spec=spec,
        targets=targets,
        save_d20s=save_d20s,
        damage_parts=damage_parts,
        resource_event=spend.event,
    )
    return AoeResolution(
        adjudication=replace(adjudication, status="resolved"),
        outcomes=outcomes,
        events=events,
        character_state=spend.state,
    )


def resolve_monster_aoe_save_spell(
    *,
    adjudication: AoeAdjudication,
    spec: SpellResolutionSpec,
    resources: Mapping[str, int | ResourceCounter],
    source: MonsterSpellSource,
    targets: Mapping[str, AoeTargetState],
    save_d20s: Mapping[str, int],
    damage_parts: tuple[DamageRollPart, ...],
) -> AoeResolution:
    """Resolve a monster AoE using the same authoritative monster resource spend."""

    if source.spell_ref != spec.spell_ref:
        raise ValueError("AoE monster spell source does not match resolution spec")
    spend = spend_monster_spell(resources=resources, source=source)
    outcomes, events = _resolve_confirmed_targets(
        adjudication=adjudication,
        spec=spec,
        targets=targets,
        save_d20s=save_d20s,
        damage_parts=damage_parts,
        resource_event=spend.event,
    )
    return AoeResolution(
        adjudication=replace(adjudication, status="resolved"),
        outcomes=outcomes,
        events=events,
        monster_resources=spend.resources,
    )
