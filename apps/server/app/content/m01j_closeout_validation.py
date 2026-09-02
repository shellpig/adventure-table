from __future__ import annotations

from typing import Any

from app.content.identity import parse_stable_key
from app.content.registry import ContentRegistry, ContentValidationError


SUPPORTED_GRANT_POOLS = frozenset(
    {
        "all_languages",
        "artisans_tools",
        "gaming_sets",
        "wizard_cantrips",
        "druid_cantrips",
        "kensei_melee_weapons",
        "kensei_ranged_weapons",
        "kensei_any_weapons",
        "one_handed_melee_weapons",
    }
)
SUPPORTED_GRANT_TARGETS = frozenset(
    {
        "proficiency",
        "skill",
        "language",
        "saving_throw",
        "spell",
        "mixed_skill_language",
    }
)
EXPECTED_FIXED_GRANT_KINDS = {
    "proficiencies": "proficiency",
    "skills": "skill",
    "languages": "language",
    "saving_throw_proficiencies": "ability",
}

# These are the layouts which static review found cannot be trusted to generic
# Markdown inference alone. Keeping the gate explicit prevents a future parser
# simplification from silently regressing the hard cases while still reporting
# a 112/112 inventory.
REQUIRED_NORMALIZED_RULES = {
    "phb2014:subclass:battle-master": {"persistent_choices", "grant_choices"},
    "xge:subclass:arcane-archer": {"persistent_choices", "grant_choices"},
    "tce:subclass:rune-knight": {"persistent_choices", "fixed_grants"},
    "phb2014:subclass:four-elements": {"persistent_choices", "fixed_feature_refs"},
    "xge:subclass:divine-soul": {"persistent_choices", "spells"},
    "tce:subclass:genie": {"persistent_choices", "expanded_spells"},
    "phb2014:subclass:eldritch-knight": {"subclass_spellcasting"},
    "phb2014:subclass:arcane-trickster": {"subclass_spellcasting"},
}


def _validate_fixed_grants(registry: ContentRegistry, subclass: Any) -> None:
    raw = subclass.data.get("fixed_grants")
    if raw is None:
        return
    if not isinstance(raw, dict):
        raise ContentValidationError(f"{subclass.key}: fixed_grants must be an object")
    for field, refs in raw.items():
        expected_kind = EXPECTED_FIXED_GRANT_KINDS.get(field)
        if expected_kind is None:
            raise ContentValidationError(f"{subclass.key}: unsupported fixed grant field {field}")
        if not isinstance(refs, (list, tuple)):
            raise ContentValidationError(f"{subclass.key}: {field} must be a list")
        for ref in refs:
            if not isinstance(ref, str):
                raise ContentValidationError(f"{subclass.key}: invalid fixed grant reference")
            entry = registry.get_optional(ref)
            if entry is None or parse_stable_key(entry.key).kind != expected_kind:
                raise ContentValidationError(
                    f"{subclass.key}: fixed grant {ref} must resolve to {expected_kind}"
                )


def _validate_grant_choices(registry: ContentRegistry, subclass: Any) -> None:
    raw_choices = subclass.data.get("grant_choices")
    if raw_choices is None:
        return
    if not isinstance(raw_choices, list):
        raise ContentValidationError(f"{subclass.key}: grant_choices must be a list")
    keys: set[str] = set()
    for raw in raw_choices:
        if not isinstance(raw, dict):
            raise ContentValidationError(f"{subclass.key}: grant choice must be an object")
        choice_key = raw.get("choice_key")
        minimum = raw.get("minimum_class_level")
        count = raw.get("choose_total")
        target = raw.get("grant_target")
        if not isinstance(choice_key, str) or not choice_key or choice_key in keys:
            raise ContentValidationError(f"{subclass.key}: invalid/duplicate grant choice key")
        keys.add(choice_key)
        if not isinstance(minimum, int) or not 1 <= minimum <= 20:
            raise ContentValidationError(f"{subclass.key}/{choice_key}: invalid minimum class level")
        if not isinstance(count, int) or count < 1:
            raise ContentValidationError(f"{subclass.key}/{choice_key}: invalid choose_total")
        if target not in SUPPORTED_GRANT_TARGETS:
            raise ContentValidationError(f"{subclass.key}/{choice_key}: unsupported grant target {target}")
        pool = raw.get("option_pool")
        if pool is not None and pool not in SUPPORTED_GRANT_POOLS:
            raise ContentValidationError(f"{subclass.key}/{choice_key}: unsupported option pool {pool}")
        refs = raw.get("option_refs", ())
        if not isinstance(refs, (list, tuple)):
            raise ContentValidationError(f"{subclass.key}/{choice_key}: option_refs must be a list")
        for ref in refs:
            if not isinstance(ref, str) or registry.get_optional(ref) is None:
                raise ContentValidationError(f"{subclass.key}/{choice_key}: missing option ref {ref}")
        if not refs and pool is None:
            raise ContentValidationError(f"{subclass.key}/{choice_key}: choice has no option source")
        progression = raw.get("progression", ())
        if not isinstance(progression, (list, tuple)):
            raise ContentValidationError(f"{subclass.key}/{choice_key}: invalid progression")
        previous_level = 0
        previous_count = 0
        for step in progression:
            if not isinstance(step, dict):
                raise ContentValidationError(f"{subclass.key}/{choice_key}: invalid progression step")
            level = step.get("class_level")
            total = step.get("choose_total")
            if (
                not isinstance(level, int)
                or not isinstance(total, int)
                or level <= previous_level
                or total < previous_count
            ):
                raise ContentValidationError(
                    f"{subclass.key}/{choice_key}: non-monotonic grant choice progression"
                )
            previous_level = level
            previous_count = total


def _validate_persistent_choice_gates(registry: ContentRegistry, subclass: Any) -> None:
    raw_choices = subclass.data.get("persistent_choices", [])
    if not isinstance(raw_choices, list):
        return
    for raw in raw_choices:
        if not isinstance(raw, dict):
            continue
        option_refs = raw.get("option_refs", ())
        option_set = {ref for ref in option_refs if isinstance(ref, str)} if isinstance(option_refs, (list, tuple)) else set()
        minimums = raw.get("option_minimum_levels", {})
        if not isinstance(minimums, dict):
            raise ContentValidationError(f"{subclass.key}: option_minimum_levels must be an object")
        for ref, level in minimums.items():
            if ref not in option_set:
                raise ContentValidationError(
                    f"{subclass.key}: option minimum level references non-option {ref}"
                )
            if not isinstance(level, int) or not 1 <= level <= 20:
                raise ContentValidationError(
                    f"{subclass.key}: invalid option minimum class level for {ref}"
                )
            if registry.get_optional(ref) is None:
                raise ContentValidationError(f"{subclass.key}: missing gated option {ref}")


def _validate_third_caster(registry: ContentRegistry, subclass: Any) -> None:
    raw = subclass.data.get("subclass_spellcasting")
    if raw is None:
        return
    if not isinstance(raw, dict):
        raise ContentValidationError(f"{subclass.key}: subclass_spellcasting must be an object")
    spell_class_ref = raw.get("spell_class_ref")
    if not isinstance(spell_class_ref, str):
        raise ContentValidationError(f"{subclass.key}: subclass spell source class is missing")
    source_class = registry.get_optional(spell_class_ref)
    if source_class is None or parse_stable_key(source_class.key).kind != "class":
        raise ContentValidationError(f"{subclass.key}: invalid subclass spell source class")
    if raw.get("ability") not in {
        "strength",
        "dexterity",
        "constitution",
        "intelligence",
        "wisdom",
        "charisma",
    }:
        raise ContentValidationError(f"{subclass.key}: invalid subclass spellcasting ability")
    schools = raw.get("school_indices")
    if not isinstance(schools, (list, tuple)) or not schools:
        raise ContentValidationError(f"{subclass.key}: restricted spell schools are missing")
    fixed = raw.get("fixed_cantrip_refs", ())
    if not isinstance(fixed, (list, tuple)):
        raise ContentValidationError(f"{subclass.key}: fixed cantrips must be a list")
    for ref in fixed:
        spell = registry.get_optional(ref) if isinstance(ref, str) else None
        if spell is None or parse_stable_key(spell.key).kind != "spell" or spell.data.get("level") != 0:
            raise ContentValidationError(f"{subclass.key}: invalid fixed subclass cantrip {ref}")
    rows = raw.get("rows")
    if not isinstance(rows, dict):
        raise ContentValidationError(f"{subclass.key}: spellcasting rows are missing")
    expected = set(range(3, 21))
    actual = {int(level) for level in rows if isinstance(level, int) or (isinstance(level, str) and level.isdigit())}
    if actual != expected:
        raise ContentValidationError(
            f"{subclass.key}: third-caster rows must cover class levels 3-20"
        )
    previous_known = 0
    previous_cantrips = 0
    for level in range(3, 21):
        row = rows.get(level) or rows.get(str(level))
        if not isinstance(row, dict):
            raise ContentValidationError(f"{subclass.key}: missing third-caster level {level}")
        cantrips = row.get("cantrips_known")
        known = row.get("spells_known")
        slots = row.get("slots")
        if (
            not isinstance(cantrips, int)
            or not isinstance(known, int)
            or cantrips < previous_cantrips
            or known < previous_known
            or not isinstance(slots, (list, tuple))
            or len(slots) != 4
            or any(not isinstance(value, int) or value < 0 for value in slots)
        ):
            raise ContentValidationError(f"{subclass.key}: invalid third-caster row at {level}")
        previous_cantrips = cantrips
        previous_known = known


def validate_m01j_closeout_metadata(registry: ContentRegistry) -> ContentRegistry:
    for subclass in registry.list_kind("subclass"):
        _validate_fixed_grants(registry, subclass)
        _validate_grant_choices(registry, subclass)
        _validate_persistent_choice_gates(registry, subclass)
        _validate_third_caster(registry, subclass)

    for subclass_ref, required_fields in REQUIRED_NORMALIZED_RULES.items():
        subclass = registry.get_optional(subclass_ref)
        if subclass is None:
            raise ContentValidationError(f"M01-J normalized closeout subclass is missing: {subclass_ref}")
        missing = sorted(field for field in required_fields if field not in subclass.data)
        if missing:
            raise ContentValidationError(
                f"{subclass_ref}: static-review normalization fields are missing: {missing}"
            )
    return registry
