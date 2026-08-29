from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.content.registry import REPOSITORY_ROOT


RULES_PATH = REPOSITORY_ROOT / "data" / "rules" / "dnd5e-2014" / "character-builder.json"


@dataclass(frozen=True)
class AbilityGenerationRules:
    standard_array: tuple[int, ...]
    point_buy_budget: int
    point_buy_costs: dict[int, int]
    manual_standard_min: int
    manual_standard_max: int
    hard_min: int
    hard_max: int


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
