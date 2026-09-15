from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal, Mapping

from app.domain.combat.resolution import DamageRollPart, HitPointState, TargetKind, apply_damage
from app.domain.combat.spell_resolver import SaveDamageMode, SpellCastMode, SpellResolutionSpec, half_damage_parts


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


@dataclass(frozen=True)
class AoeTargetState:
    entry_id: str
    target_kind: TargetKind
    hp: HitPointState
    save_modifier: int


@dataclass(frozen=True)
class AoeTargetOutcome:
    entry_id: str
    save_total: int
    saved: bool
    hp: HitPointState
    damage_taken: int


@dataclass(frozen=True)
class AoeResolution:
    adjudication: AoeAdjudication
    remaining_slots: dict[int, int]
    outcomes: tuple[AoeTargetOutcome, ...]
    events: tuple[dict[str, object], ...]


def propose_aoe(*, command_id: str, acting_entry_id: str, target_ids: tuple[str, ...]) -> AoeAdjudication:
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
    return replace(adjudication, confirmed_target_ids=confirmed_target_ids, status="confirmed")


def cancel_aoe(adjudication: AoeAdjudication) -> AoeAdjudication:
    if adjudication.status in {"resolved", "cancelled"}:
        return adjudication
    return replace(adjudication, status="cancelled")


def resolve_aoe_save_spell(
    *,
    adjudication: AoeAdjudication,
    spec: SpellResolutionSpec,
    slot_level: int,
    spell_slots: Mapping[int, int],
    targets: Mapping[str, AoeTargetState],
    save_d20s: Mapping[str, int],
    damage_parts: tuple[DamageRollPart, ...],
) -> AoeResolution:
    """Resolve one confirmed save-based AoE with exactly one spell-slot spend."""

    if adjudication.status != "confirmed":
        raise ValueError("AoE must be DM-confirmed before resolution")
    if spec.cast_mode is not SpellCastMode.SAVE or spec.save_dc is None:
        raise ValueError("AoE group resolver requires a save-based spell")
    if slot_level < spec.minimum_slot_level or slot_level > 9:
        raise ValueError("invalid AoE spell slot level")
    if slot_level > 0 and int(spell_slots.get(slot_level, 0)) <= 0:
        raise ValueError(f"no level {slot_level} spell slot remains")

    confirmed = adjudication.confirmed_target_ids
    if set(targets) != set(confirmed) or set(save_d20s) != set(confirmed):
        raise ValueError("AoE target state and save rolls must exactly match confirmed targets")
    if any(value < 1 or value > 20 for value in save_d20s.values()):
        raise ValueError("AoE saving throw d20 must be between 1 and 20")

    remaining = dict(spell_slots)
    events: list[dict[str, object]] = [
        {
            "type": "aoe_targets_confirmed",
            "command_id": adjudication.command_id,
            "target_entry_ids": list(confirmed),
        }
    ]
    if slot_level > 0:
        remaining[slot_level] -= 1
        events.append({"type": "resource_spent", "resource": "spell_slot", "level": slot_level, "amount": 1})

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
            damage = apply_damage(target.hp, parts, target_kind=target.target_kind)
            hp = damage.after
            amount = damage.adjusted_total
        else:
            hp = target.hp
            amount = 0
        outcomes.append(AoeTargetOutcome(entry_id, total, saved, hp, amount))
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

    return AoeResolution(
        adjudication=replace(adjudication, status="resolved"),
        remaining_slots=remaining,
        outcomes=tuple(outcomes),
        events=tuple(events),
    )
