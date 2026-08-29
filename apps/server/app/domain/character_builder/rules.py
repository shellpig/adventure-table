from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from app.content.registry import REPOSITORY_ROOT


RULES_PATH = REPOSITORY_ROOT / "data" / "rules" / "dnd5e-2014" / "character-builder.json"

SpellAccessModel = Literal["known", "prepared", "spellbook"]
SlotContribution = Literal["full", "half", "none"]
SpellResourcePoolType = Literal["normal_multiclass_slots", "pact_magic"]
PreparedFormula = Literal["class_level_plus_ability", "half_class_level_plus_ability"]


@dataclass(frozen=True)
class AbilityGenerationRules:
    standard_array: tuple[int, ...]
    point_buy_budget: int
    point_buy_costs: dict[int, int]
    manual_standard_min: int
    manual_standard_max: int
    hard_min: int
    hard_max: int


@dataclass(frozen=True)
class SpellcastingClassRule:
    access_model: SpellAccessModel
    slot_contribution: SlotContribution
    resource_pool_type: SpellResourcePoolType
    prepared_formula: PreparedFormula | None = None
    spellbook_initial: int = 0
    spellbook_per_level: int = 0


@dataclass(frozen=True)
class SpellcastingRules:
    classes: dict[str, SpellcastingClassRule]
    combined_spell_slots: dict[int, tuple[int, ...]]


@lru_cache(maxsize=1)
def load_ability_generation_rules(path: Path = RULES_PATH) -> AbilityGenerationRules:
    payload = json.loads(path.read_text(encoding="utf-8"))
    source = payload["ability_generation"]
    point_buy = source["point_buy"]
    manual = source["manual"]
    return AbilityGenerationRules(
        standard_array=tuple(int(value) for value in source["standard_array"]),
        point_buy_budget=int(point_buy["budget"]),
        point_buy_costs={int(score): int(cost) for score, cost in point_buy["costs"].items()},
        manual_standard_min=int(manual["standard_min"]),
        manual_standard_max=int(manual["standard_max"]),
        hard_min=int(manual["hard_min"]),
        hard_max=int(manual["hard_max"]),
    )


@lru_cache(maxsize=1)
def load_spellcasting_rules(path: Path = RULES_PATH) -> SpellcastingRules:
    payload = json.loads(path.read_text(encoding="utf-8"))
    source = payload["spellcasting"]
    classes: dict[str, SpellcastingClassRule] = {}
    for class_ref, raw in source["classes"].items():
        classes[class_ref] = SpellcastingClassRule(
            access_model=raw["access_model"],
            slot_contribution=raw["slot_contribution"],
            resource_pool_type=raw["resource_pool_type"],
            prepared_formula=raw.get("prepared_formula"),
            spellbook_initial=int(raw.get("spellbook_initial", 0)),
            spellbook_per_level=int(raw.get("spellbook_per_level", 0)),
        )

    combined: dict[int, tuple[int, ...]] = {}
    for level, slots in source["combined_spell_slots"].items():
        caster_level = int(level)
        values = tuple(int(value) for value in slots)
        if len(values) != 9:
            raise ValueError(f"combined_spell_slots[{level}] must contain nine spell levels")
        combined[caster_level] = values

    expected_levels = set(range(1, 21))
    if set(combined) != expected_levels:
        raise ValueError("combined_spell_slots must define caster levels 1 through 20")

    return SpellcastingRules(classes=classes, combined_spell_slots=combined)
