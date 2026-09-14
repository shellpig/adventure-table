from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from app.content.p4a_monsters import MonsterData


class MonsterTemplateSource(Protocol):
    def model_dump(self, *, mode: str, exclude_none: bool) -> dict[str, Any]: ...


class MonsterTemplateNormalizationError(ValueError):
    pass


def monster_to_reusable_rules(monster: MonsterTemplateSource) -> dict[str, Any]:
    """Normalize a typed SRD Monster into P4-A reusable combat rules.

    The normalizer deliberately preserves upstream structured mechanics instead
    of interpreting prose. Live combat state (HP remaining, initiative,
    reaction availability, etc.) is not part of the returned template rules.
    """

    payload = deepcopy(monster.model_dump(mode="python", exclude_none=True))
    armor_options = payload.get("armor_class")
    if not isinstance(armor_options, list) or not armor_options:
        raise MonsterTemplateNormalizationError(
            "monster armor_class must contain at least one structured option"
        )
    default_ac = armor_options[0].get("value") if isinstance(armor_options[0], dict) else None
    if not isinstance(default_ac, int) or default_ac < 0:
        raise MonsterTemplateNormalizationError(
            "monster first armor_class option must contain a non-negative integer value"
        )

    hit_points = payload.get("hit_points")
    if not isinstance(hit_points, int) or hit_points < 0:
        raise MonsterTemplateNormalizationError(
            "monster hit_points must be a non-negative integer"
        )
    speed = payload.get("speed")
    if not isinstance(speed, dict) or not speed:
        raise MonsterTemplateNormalizationError("monster speed must be a non-empty object")

    rules: dict[str, Any] = {
        "name": payload["name"],
        "size": payload["size"],
        "type": payload["type"],
        "alignment": payload["alignment"],
        "armor_class": default_ac,
        "armor_class_options": armor_options,
        "max_hp": hit_points,
        "hit_dice": payload["hit_dice"],
        "hit_points_roll": payload["hit_points_roll"],
        "speed": speed,
        "ability_scores": {
            "strength": payload["strength"],
            "dexterity": payload["dexterity"],
            "constitution": payload["constitution"],
            "intelligence": payload["intelligence"],
            "wisdom": payload["wisdom"],
            "charisma": payload["charisma"],
        },
        "proficiencies": payload.get("proficiencies", []),
        "damage_vulnerabilities": payload.get("damage_vulnerabilities", []),
        "damage_resistances": payload.get("damage_resistances", []),
        "damage_immunities": payload.get("damage_immunities", []),
        "condition_immunities": payload.get("condition_immunities", []),
        "senses": payload["senses"],
        "languages": payload.get("languages", ""),
        "challenge_rating": payload["challenge_rating"],
        "xp": payload["xp"],
        "traits": payload.get("special_abilities", []),
        "actions": payload.get("actions", []),
        "bonus_actions": payload.get("bonus_actions", []),
        "reactions": payload.get("reactions", []),
        "legendary_actions": payload.get("legendary_actions", []),
    }
    optional_copy_fields = (
        ("desc", "description"),
        ("subtype", "subtype"),
        ("proficiency_bonus", "proficiency_bonus"),
        ("forms", "forms"),
    )
    for source_key, target_key in optional_copy_fields:
        if source_key in payload:
            rules[target_key] = payload[source_key]
    return deepcopy(rules)


__all__ = [
    "MonsterTemplateNormalizationError",
    "MonsterTemplateSource",
    "monster_to_reusable_rules",
]
