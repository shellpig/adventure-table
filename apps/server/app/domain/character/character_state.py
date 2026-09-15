from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


CURRENT_CHARACTER_STATE_SCHEMA = 2


@dataclass(frozen=True)
class ConcentrationState:
    source_ref: str
    effect_ids: tuple[str, ...] = ()
    started_round: int | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "source_ref": self.source_ref,
            "effect_ids": list(self.effect_ids),
            "started_round": self.started_round,
        }


@dataclass(frozen=True)
class CharacterRuntimeState:
    """Shared durable Character/Combat state introduced by P4-D.

    Missing ``schema_version`` is treated as legacy v1. The normalized in-memory
    shape is always v2, and the writer always emits v2. Both old top-level HP
    keys and the v2 ``health`` object are accepted so pre-P4-D saves restore
    without a destructive migration.
    """

    current_hp: int
    max_hp: int
    temp_hp: int = 0
    conditions: tuple[str, ...] = ()
    concentration: ConcentrationState | None = None
    temporary_effects: tuple[dict[str, Any], ...] = ()
    reaction_available: bool = True
    ready: dict[str, Any] | None = None
    spell_slots: Mapping[int, int] = field(default_factory=dict)
    schema_version: int = CURRENT_CHARACTER_STATE_SCHEMA

    def __post_init__(self) -> None:
        if self.max_hp <= 0:
            raise ValueError("max_hp must be positive")
        if not 0 <= self.current_hp <= self.max_hp:
            raise ValueError("current_hp must be between 0 and max_hp")
        if self.temp_hp < 0:
            raise ValueError("temp_hp cannot be negative")
        if len(self.conditions) != len(set(self.conditions)):
            raise ValueError("conditions must be unique")
        if any(level < 1 or level > 9 or remaining < 0 for level, remaining in self.spell_slots.items()):
            raise ValueError("spell slots must use levels 1..9 and non-negative remaining counts")

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> "CharacterRuntimeState":
        version = int(payload.get("schema_version", 1))
        if version not in (1, 2):
            raise ValueError(f"unsupported character state schema_version: {version}")

        health = payload.get("health") if isinstance(payload.get("health"), Mapping) else payload
        current_hp = int(health.get("current_hp", payload.get("current_hp", 0)))
        max_hp = int(health.get("max_hp", payload.get("max_hp", 0)))
        temp_hp = int(health.get("temp_hp", payload.get("temp_hp", 0)))

        status = payload.get("status") if isinstance(payload.get("status"), Mapping) else {}
        combat = payload.get("combat") if isinstance(payload.get("combat"), Mapping) else {}
        resources = payload.get("resources") if isinstance(payload.get("resources"), Mapping) else {}

        concentration_payload = status.get("concentration")
        concentration = None
        if isinstance(concentration_payload, Mapping):
            concentration = ConcentrationState(
                source_ref=str(concentration_payload["source_ref"]),
                effect_ids=tuple(str(value) for value in concentration_payload.get("effect_ids", ())),
                started_round=(
                    int(concentration_payload["started_round"])
                    if concentration_payload.get("started_round") is not None
                    else None
                ),
            )

        raw_slots = resources.get("spell_slots", payload.get("spell_slots", {}))
        slots: dict[int, int] = {}
        if isinstance(raw_slots, Mapping):
            slots = {int(level): int(remaining) for level, remaining in raw_slots.items()}

        return cls(
            current_hp=current_hp,
            max_hp=max_hp,
            temp_hp=temp_hp,
            conditions=tuple(str(value) for value in status.get("conditions", payload.get("conditions", ()))),
            concentration=concentration,
            temporary_effects=tuple(dict(value) for value in status.get("temporary_effects", ())),
            reaction_available=bool(combat.get("reaction_available", payload.get("reaction_available", True))),
            ready=(dict(combat["ready"]) if isinstance(combat.get("ready"), Mapping) else None),
            spell_slots=slots,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": CURRENT_CHARACTER_STATE_SCHEMA,
            "health": {
                "current_hp": self.current_hp,
                "max_hp": self.max_hp,
                "temp_hp": self.temp_hp,
            },
            "status": {
                "conditions": list(self.conditions),
                "concentration": self.concentration.to_json() if self.concentration else None,
                "temporary_effects": [dict(effect) for effect in self.temporary_effects],
            },
            "combat": {
                "reaction_available": self.reaction_available,
                "ready": dict(self.ready) if self.ready is not None else None,
            },
            "resources": {
                "spell_slots": {str(level): remaining for level, remaining in sorted(self.spell_slots.items())},
            },
        }

    def spend_spell_slot(self, level: int) -> "CharacterRuntimeState":
        if level < 1 or level > 9:
            raise ValueError("spell slot level must be between 1 and 9")
        remaining = int(self.spell_slots.get(level, 0))
        if remaining <= 0:
            raise ValueError(f"no level {level} spell slot remains")
        slots = dict(self.spell_slots)
        slots[level] = remaining - 1
        return CharacterRuntimeState(
            current_hp=self.current_hp,
            max_hp=self.max_hp,
            temp_hp=self.temp_hp,
            conditions=self.conditions,
            concentration=self.concentration,
            temporary_effects=self.temporary_effects,
            reaction_available=self.reaction_available,
            ready=self.ready,
            spell_slots=slots,
        )
