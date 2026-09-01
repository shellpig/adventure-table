from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from app.content.registry import REPOSITORY_ROOT


RULES_PATH = REPOSITORY_ROOT / "data" / "rules" / "dnd5e-2014" / "character-builder.json"

SpellAccessModel = Literal["known", "prepared", "spellbook"]
SlotContributionFormula = Literal["full", "half", "none"]
SlotContributionRounding = Literal["floor", "ceil", "none"]
SpellResourcePoolType = Literal["normal_multiclass_slots", "pact_magic"]
PreparedFormula = Literal[
    "class_level_plus_ability",
    "half_class_level_floor_plus_ability",
]


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
class SlotContributionRule:
    formula: SlotContributionFormula
    rounding: SlotContributionRounding


@dataclass(frozen=True)
class SpellcastingClassRule:
    access_model: SpellAccessModel
    slot_contribution: SlotContributionRule
    resource_pool_type: SpellResourcePoolType
    prepared_formula: PreparedFormula | None = None
    prepared_minimum: int = 1
    spellbook_initial: int = 0
    spellbook_per_level: int = 0


@dataclass(frozen=True)
class SpellcastingRules:
    classes: dict[str, SpellcastingClassRule]
    combined_spell_slots: dict[int, tuple[int, ...]]


def normalize_slot_contribution(raw: object) -> SlotContributionRule:
    """Normalize legacy strings and canonical formula/rounding objects.

    Existing SRD rules intentionally remain on the legacy string shape so the
    compatibility path stays exercised. New content can use the canonical
    object without creating a second calculation path.
    """

    if isinstance(raw, str):
        legacy: dict[str, SlotContributionRule] = {
            "full": SlotContributionRule(formula="full", rounding="floor"),
            "half": SlotContributionRule(formula="half", rounding="floor"),
            "none": SlotContributionRule(formula="none", rounding="none"),
        }
        try:
            return legacy[raw]
        except KeyError as exc:
            raise ValueError(f"unsupported slot contribution: {raw!r}") from exc

    if not isinstance(raw, dict):
        raise ValueError("slot_contribution must be a legacy string or canonical object")
    formula = raw.get("formula")
    rounding = raw.get("rounding")
    if formula not in {"full", "half", "none"}:
        raise ValueError(f"unsupported slot contribution formula: {formula!r}")
    if rounding not in {"floor", "ceil", "none"}:
        raise ValueError(f"unsupported slot contribution rounding: {rounding!r}")
    if formula == "none" and rounding != "none":
        raise ValueError("slot contribution formula 'none' requires rounding 'none'")
    if formula != "none" and rounding == "none":
        raise ValueError("contributing spellcasting formulas require floor or ceil rounding")
    if formula == "full" and rounding != "floor":
        raise ValueError("full slot contribution uses canonical floor rounding")
    return SlotContributionRule(formula=formula, rounding=rounding)


def _normalize_prepared_formula(raw: object) -> PreparedFormula | None:
    if raw is None:
        return None
    if raw == "half_class_level_plus_ability":
        # P1 legacy spelling always meant floor(class level / 2).
        return "half_class_level_floor_plus_ability"
    if raw in {"class_level_plus_ability", "half_class_level_floor_plus_ability"}:
        return raw
    raise ValueError(f"unsupported prepared formula: {raw!r}")


def caster_level_contribution(
    class_ref: str,
    class_level: int,
    config: SpellcastingClassRule,
) -> int:
    """Return this class's contribution to normal multiclass caster level."""

    if class_level < 0:
        raise ValueError(f"class level cannot be negative for {class_ref}: {class_level}")
    contribution = config.slot_contribution
    if contribution.formula == "none":
        return 0
    if contribution.formula == "full":
        return class_level
    if contribution.formula != "half":
        raise ValueError(f"unsupported slot contribution formula: {contribution.formula}")
    if contribution.rounding == "floor":
        return class_level // 2
    if contribution.rounding == "ceil":
        return (class_level + 1) // 2
    raise ValueError(f"unsupported half-caster rounding: {contribution.rounding}")


def prepared_limit(
    config: SpellcastingClassRule,
    class_level: int,
    effective_ability_modifier: int,
) -> int | None:
    """Calculate daily prepared capacity independently of slot contribution."""

    formula = config.prepared_formula
    if formula is None:
        return None
    if formula == "class_level_plus_ability":
        value = class_level + effective_ability_modifier
    elif formula == "half_class_level_floor_plus_ability":
        value = class_level // 2 + effective_ability_modifier
    else:
        raise ValueError(f"unsupported prepared formula: {formula}")
    return max(config.prepared_minimum, value)


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
        prepared_minimum = int(raw.get("prepared_minimum", 1))
        if prepared_minimum < 0:
            raise ValueError(f"prepared_minimum cannot be negative for {class_ref}")
        classes[class_ref] = SpellcastingClassRule(
            access_model=raw["access_model"],
            slot_contribution=normalize_slot_contribution(raw["slot_contribution"]),
            resource_pool_type=raw["resource_pool_type"],
            prepared_formula=_normalize_prepared_formula(raw.get("prepared_formula")),
            prepared_minimum=prepared_minimum,
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
