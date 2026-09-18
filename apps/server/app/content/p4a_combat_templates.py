from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import re
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


class DamagePart(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dice: str = Field(min_length=1)
    damage_type: str | None = None


class MonsterAction(BaseModel):
    """Canonical P4 combat action with upstream details preserved as extras."""

    model_config = ConfigDict(extra="allow", frozen=True)

    name: str = Field(min_length=1)
    kind: Literal["attack", "save", "utility", "other"]
    attack_kind: Literal[
        "melee_weapon",
        "ranged_weapon",
        "melee_spell",
        "ranged_spell",
    ] | None = None
    attack_bonus: int | None = None
    target: str | None = None
    range_normal: int | None = Field(default=None, ge=0)
    range_long: int | None = Field(default=None, ge=0)
    reach: int | None = Field(default=None, ge=0)
    damage_parts: list[DamagePart] = Field(default_factory=list)
    save_ability: str | None = None
    save_dc: int | None = Field(default=None, ge=0)
    desc: str | None = None
    automation_level: Literal["structured", "partial", "dm_adjudication"] = "partial"


class MonsterTemplateSource(Protocol):
    def model_dump(self, *, mode: str, exclude_none: bool) -> dict[str, Any]: ...


class MonsterTemplateNormalizationError(ValueError):
    pass


class MonsterActionNormalizationError(ValueError):
    pass


_ATTACK_KIND_PREFIXES: tuple[tuple[str, str], ...] = (
    ("Melee Spell Attack:", "melee_spell"),
    ("Ranged Spell Attack:", "ranged_spell"),
    ("Melee Weapon Attack:", "melee_weapon"),
    ("Ranged Weapon Attack:", "ranged_weapon"),
)
_CANONICAL_ATTACK_KINDS = frozenset(
    {"melee_weapon", "ranged_weapon", "melee_spell", "ranged_spell"}
)
_REACH_RE = re.compile(r"\breach\s+(\d+)\s*ft\.?", re.IGNORECASE)
_RANGE_RE = re.compile(r"\brange\s+(\d+)(?:/(\d+))?\s*ft\.?", re.IGNORECASE)
_TARGET_RE = re.compile(
    r"(?:reach\s+\d+\s*ft\.?|range\s+\d+(?:/\d+)?\s*ft\.?),\s*([^.;]+)",
    re.IGNORECASE,
)
_COMPLEX_RIDER_RE = re.compile(
    r"\b(?:saving throw|must succeed|grappled|restrained|poisoned|swallowed|"
    r"knocked prone|escape dc|on a failed save|on a successful save)\b",
    re.IGNORECASE,
)
_COMPLEX_ACTION_KEYS = (
    "dc",
    "usage",
    "multiattack_type",
    "actions",
    "action_options",
    "attacks",
    "options",
)


def _reference_key(value: object) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, Mapping):
        for key in ("index", "name"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    return None


def split_damage_expression(value: str) -> tuple[str, str | None]:
    """Split a damage expression into dice formula and optional damage type."""
    cleaned = value.strip()
    if not cleaned:
        return "", None
    parts = cleaned.split(None, 1)
    dice = parts[0]
    damage_type: str | None = None
    if len(parts) > 1:
        type_str = parts[1].strip().casefold()
        if type_str.endswith(" damage"):
            type_str = type_str[:-7].strip()
        damage_type = type_str or None
    return dice, damage_type


def _damage_parts(action: Mapping[str, Any]) -> list[DamagePart]:
    raw_parts = action.get("damage_parts")
    if isinstance(raw_parts, list):
        normalized: list[DamagePart] = []
        for part in raw_parts:
            if isinstance(part, DamagePart):
                normalized.append(part)
                continue
            if not isinstance(part, Mapping):
                continue
            dice = part.get("dice") or part.get("damage_dice")
            if not isinstance(dice, str) or not dice.strip():
                continue
            normalized.append(
                DamagePart(
                    dice=dice.strip(),
                    damage_type=_reference_key(part.get("damage_type")),
                )
            )
        if normalized:
            return normalized

    raw_damage = action.get("damage")
    if isinstance(raw_damage, str):
        dice, damage_type = split_damage_expression(raw_damage)
        return [DamagePart(dice=dice, damage_type=damage_type)] if dice else []
    if not isinstance(raw_damage, list):
        return []

    normalized = []
    for part in raw_damage:
        if not isinstance(part, Mapping):
            continue
        dice = part.get("damage_dice") or part.get("dice")
        if not isinstance(dice, str) or not dice.strip():
            continue
        normalized.append(
            DamagePart(
                dice=dice.strip(),
                damage_type=_reference_key(part.get("damage_type")),
            )
        )
    return normalized


def _attack_kind(action: Mapping[str, Any], desc: str | None) -> str | None:
    explicit = action.get("attack_kind")
    if explicit in _CANONICAL_ATTACK_KINDS:
        return str(explicit)
    if not isinstance(action.get("attack_bonus"), int):
        return None
    if desc:
        folded = desc.casefold()
        for prefix, attack_kind in _ATTACK_KIND_PREFIXES:
            if prefix.casefold() in folded:
                return attack_kind
    return None


def _save_fields(action: Mapping[str, Any]) -> tuple[str | None, int | None]:
    explicit_ability = action.get("save_ability")
    explicit_dc = action.get("save_dc")
    ability = (
        explicit_ability.strip()
        if isinstance(explicit_ability, str) and explicit_ability.strip()
        else None
    )
    dc_value = explicit_dc if isinstance(explicit_dc, int) and explicit_dc >= 0 else None

    raw_dc = action.get("dc")
    if isinstance(raw_dc, Mapping):
        if ability is None:
            ability = _reference_key(raw_dc.get("dc_type"))
        candidate = raw_dc.get("dc_value")
        if dc_value is None and isinstance(candidate, int) and candidate >= 0:
            dc_value = candidate
    return ability, dc_value


def _range_fields(desc: str | None) -> tuple[int | None, int | None, int | None, str | None]:
    if not desc:
        return None, None, None, None
    reach_match = _REACH_RE.search(desc)
    range_match = _RANGE_RE.search(desc)
    target_match = _TARGET_RE.search(desc)
    reach = int(reach_match.group(1)) if reach_match else None
    range_normal = int(range_match.group(1)) if range_match else None
    range_long = int(range_match.group(2)) if range_match and range_match.group(2) else None
    target = target_match.group(1).strip() if target_match else None
    return range_normal, range_long, reach, target


def _automation_level(
    action: Mapping[str, Any],
    *,
    kind: str,
    attack_kind: str | None,
    attack_bonus: int | None,
    damage_parts: list[DamagePart],
    save_dc: int | None,
    desc: str | None,
) -> str:
    has_complex_structure = any(
        action.get(key) not in (None, [], {}) for key in _COMPLEX_ACTION_KEYS
    )
    has_machine_structure = (
        attack_bonus is not None
        or bool(damage_parts)
        or save_dc is not None
        or has_complex_structure
    )
    simple_attack = (
        kind == "attack"
        and attack_bonus is not None
        and attack_kind in _CANONICAL_ATTACK_KINDS
        and bool(damage_parts)
        and save_dc is None
        and not has_complex_structure
        and not (desc and _COMPLEX_RIDER_RE.search(desc))
    )
    if simple_attack:
        return "structured"
    if has_machine_structure:
        return "partial"
    return "dm_adjudication"


def normalize_monster_action(action: Mapping[str, Any]) -> dict[str, Any]:
    """Add the canonical P4 action contract without discarding upstream fields."""

    raw = deepcopy(dict(action))
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise MonsterActionNormalizationError("monster action name must not be blank")
    desc_value = raw.get("desc")
    desc = desc_value if isinstance(desc_value, str) and desc_value.strip() else None
    attack_bonus_value = raw.get("attack_bonus")
    attack_bonus = attack_bonus_value if isinstance(attack_bonus_value, int) else None
    damage_parts = _damage_parts(raw)
    save_ability, save_dc = _save_fields(raw)

    explicit_kind = raw.get("kind")
    if explicit_kind in {"attack", "save", "utility", "other"}:
        kind = str(explicit_kind)
    elif attack_bonus is not None:
        kind = "attack"
    elif save_dc is not None:
        kind = "save"
    elif raw.get("usage") is not None:
        kind = "utility"
    else:
        kind = "other"

    attack_kind = _attack_kind(raw, desc)
    range_normal, range_long, reach, target = _range_fields(desc)
    canonical_payload = {
        **raw,
        "name": name.strip(),
        "kind": kind,
        "attack_kind": attack_kind,
        "attack_bonus": attack_bonus,
        "target": target,
        "range_normal": range_normal,
        "range_long": range_long,
        "reach": reach,
        "damage_parts": damage_parts,
        "save_ability": save_ability,
        "save_dc": save_dc,
        "desc": desc,
        "automation_level": _automation_level(
            raw,
            kind=kind,
            attack_kind=attack_kind,
            attack_bonus=attack_bonus,
            damage_parts=damage_parts,
            save_dc=save_dc,
            desc=desc,
        ),
    }
    canonical = MonsterAction.model_validate(canonical_payload)
    return canonical.model_dump(mode="python")


def _normalize_action_list(value: object) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise MonsterActionNormalizationError("monster action collection must be a list")
    normalized: list[dict[str, Any]] = []
    for action in value:
        if not isinstance(action, Mapping):
            raise MonsterActionNormalizationError("monster action entries must be objects")
        normalized.append(normalize_monster_action(action))
    return normalized


def monster_to_reusable_rules(monster: MonsterTemplateSource) -> dict[str, Any]:
    """Normalize a typed SRD Monster into P4-A reusable combat rules.

    Reusable templates keep upstream details, but common combat actions also
    receive P4's canonical action fields. Live combat state (HP remaining,
    initiative, reaction availability, etc.) is never part of template rules.
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
        "actions": _normalize_action_list(payload.get("actions")),
        "bonus_actions": _normalize_action_list(payload.get("bonus_actions")),
        "reactions": _normalize_action_list(payload.get("reactions")),
        "legendary_actions": _normalize_action_list(payload.get("legendary_actions")),
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
    "DamagePart",
    "MonsterAction",
    "MonsterActionNormalizationError",
    "MonsterTemplateNormalizationError",
    "MonsterTemplateSource",
    "monster_to_reusable_rules",
    "normalize_monster_action",
    "split_damage_expression",
]
