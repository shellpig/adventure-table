from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import re
from typing import Any, Iterable

from app.content.identity import parse_stable_key, stable_key
from app.content.m01j_reference_content import M01JReferenceRegistry, _SpellResolver
from app.content.registry import ContentRegistry, ContentValidationError
from app.content.schemas import ContentEntry


# Rules in this module are deliberately narrow normalization for repository
# reference sections whose layout cannot be represented safely by the generic
# Markdown parser (for example a count table separated from its H5 option list).
# The source documents remain the human-readable rules SSOT; these constants
# only make their permanent Build semantics deterministic.

FIXED_GRANTS: dict[str, dict[str, tuple[str, ...]]] = {
    "phb2014:subclass:valor": {
        "proficiencies": (
            "srd5.1:proficiency:medium-armor",
            "srd5.1:proficiency:shields",
            "srd5.1:proficiency:martial-weapons",
        ),
    },
    "xge:subclass:swords": {
        "proficiencies": (
            "srd5.1:proficiency:medium-armor",
            "srd5.1:proficiency:scimitars",
        ),
    },
    "phb2014:subclass:nature": {
        "proficiencies": ("srd5.1:proficiency:heavy-armor",),
    },
    "phb2014:subclass:tempest": {
        "proficiencies": (
            "srd5.1:proficiency:martial-weapons",
            "srd5.1:proficiency:heavy-armor",
        ),
    },
    "phb2014:subclass:war": {
        "proficiencies": (
            "srd5.1:proficiency:martial-weapons",
            "srd5.1:proficiency:heavy-armor",
        ),
    },
    "xge:subclass:forge": {
        "proficiencies": (
            "srd5.1:proficiency:heavy-armor",
            "srd5.1:proficiency:smiths-tools",
        ),
    },
    "tce:subclass:order": {
        "proficiencies": ("srd5.1:proficiency:heavy-armor",),
    },
    "tce:subclass:twilight": {
        "proficiencies": (
            "srd5.1:proficiency:martial-weapons",
            "srd5.1:proficiency:heavy-armor",
        ),
    },
    "xge:subclass:assassin": {
        "proficiencies": (
            "srd5.1:proficiency:disguise-kit",
            "srd5.1:proficiency:poisoners-kit",
        ),
    },
    "xge:subclass:mastermind": {
        "proficiencies": (
            "srd5.1:proficiency:disguise-kit",
            "srd5.1:proficiency:forgery-kit",
        ),
    },
    "xge:subclass:scout": {
        "skills": (
            "srd5.1:skill:nature",
            "srd5.1:skill:survival",
        ),
    },
    "xge:subclass:storm-sorcery": {
        "languages": ("srd5.1:language:primordial",),
    },
    "xge:subclass:hexblade": {
        "proficiencies": (
            "srd5.1:proficiency:medium-armor",
            "srd5.1:proficiency:shields",
            "srd5.1:proficiency:martial-weapons",
        ),
    },
    "xge:subclass:drunken-master": {
        "proficiencies": ("srd5.1:proficiency:brewers-supplies",),
        "skills": ("srd5.1:skill:performance",),
    },
    "tce:subclass:mercy": {
        "proficiencies": ("srd5.1:proficiency:herbalism-kit",),
        "skills": (
            "srd5.1:skill:insight",
            "srd5.1:skill:medicine",
        ),
    },
    "tce:subclass:rune-knight": {
        "proficiencies": ("srd5.1:proficiency:smiths-tools",),
        "languages": ("srd5.1:language:giant",),
    },
    "tce:subclass:bladesinging": {
        "proficiencies": ("srd5.1:proficiency:light-armor",),
        "skills": ("srd5.1:skill:performance",),
    },
}


GRANT_CHOICES: dict[str, tuple[dict[str, Any], ...]] = {
    "phb2014:subclass:knowledge": (
        {
            "choice_key": "knowledge-domain-skills",
            "label": "Blessings of Knowledge — skills",
            "minimum_class_level": 1,
            "choose_total": 2,
            "grant_target": "skill",
            "option_refs": (
                "srd5.1:skill:arcana",
                "srd5.1:skill:history",
                "srd5.1:skill:nature",
                "srd5.1:skill:religion",
            ),
        },
        {
            "choice_key": "knowledge-domain-languages",
            "label": "Blessings of Knowledge — languages",
            "minimum_class_level": 1,
            "choose_total": 2,
            "grant_target": "language",
            "option_pool": "all_languages",
        },
    ),
    "phb2014:subclass:nature": (
        {
            "choice_key": "nature-domain-cantrip",
            "label": "Acolyte of Nature — Druid cantrip",
            "minimum_class_level": 1,
            "choose_total": 1,
            "grant_target": "spell",
            "option_pool": "druid_cantrips",
            "access_type": "granted",
        },
        {
            "choice_key": "nature-domain-skill",
            "label": "Acolyte of Nature — skill",
            "minimum_class_level": 1,
            "choose_total": 1,
            "grant_target": "skill",
            "option_refs": (
                "srd5.1:skill:animal-handling",
                "srd5.1:skill:nature",
                "srd5.1:skill:survival",
            ),
        },
    ),
    "scag:subclass:arcana": (
        {
            "choice_key": "arcana-domain-cantrips",
            "label": "Arcane Initiate — Wizard cantrips",
            "minimum_class_level": 1,
            "choose_total": 2,
            "grant_target": "spell",
            "option_pool": "wizard_cantrips",
            "access_type": "granted",
        },
    ),
    "tce:subclass:order": (
        {
            "choice_key": "order-domain-skill",
            "label": "Bonus Proficiency",
            "minimum_class_level": 1,
            "choose_total": 1,
            "grant_target": "skill",
            "option_refs": (
                "srd5.1:skill:intimidation",
                "srd5.1:skill:persuasion",
            ),
        },
    ),
    "tce:subclass:peace": (
        {
            "choice_key": "peace-domain-skill",
            "label": "Implement of Peace",
            "minimum_class_level": 1,
            "choose_total": 1,
            "grant_target": "skill",
            "option_refs": (
                "srd5.1:skill:insight",
                "srd5.1:skill:performance",
                "srd5.1:skill:persuasion",
            ),
        },
    ),
    "xge:subclass:samurai": (
        {
            "choice_key": "samurai-bonus-proficiency",
            "label": "Bonus Proficiency",
            "minimum_class_level": 3,
            "choose_total": 1,
            "grant_target": "mixed_skill_language",
            "option_refs": (
                "srd5.1:skill:history",
                "srd5.1:skill:insight",
                "srd5.1:skill:performance",
                "srd5.1:skill:persuasion",
            ),
            "option_pool": "all_languages",
        },
    ),
    "xge:subclass:cavalier": (
        {
            "choice_key": "cavalier-bonus-proficiency",
            "label": "Bonus Proficiency",
            "minimum_class_level": 3,
            "choose_total": 1,
            "grant_target": "mixed_skill_language",
            "option_refs": (
                "srd5.1:skill:animal-handling",
                "srd5.1:skill:history",
                "srd5.1:skill:insight",
                "srd5.1:skill:performance",
                "srd5.1:skill:persuasion",
            ),
            "option_pool": "all_languages",
        },
    ),
    "xge:subclass:arcane-archer": (
        {
            "choice_key": "arcane-archer-lore-skill",
            "label": "Arcane Archer Lore — skill",
            "minimum_class_level": 3,
            "choose_total": 1,
            "grant_target": "skill",
            "option_refs": (
                "srd5.1:skill:arcana",
                "srd5.1:skill:nature",
            ),
        },
        {
            "choice_key": "arcane-archer-lore-cantrip",
            "label": "Arcane Archer Lore — cantrip",
            "minimum_class_level": 3,
            "choose_total": 1,
            "grant_target": "spell",
            "option_refs": (
                "srd5.1:spell:prestidigitation",
                "srd5.1:spell:druidcraft",
            ),
            "access_type": "granted",
        },
    ),
    "xge:subclass:kensei": (
        {
            "choice_key": "kensei-melee-weapon",
            "label": "Kensei Weapons — melee",
            "minimum_class_level": 3,
            "choose_total": 1,
            "grant_target": "proficiency",
            "option_pool": "kensei_melee_weapons",
        },
        {
            "choice_key": "kensei-ranged-weapon",
            "label": "Kensei Weapons — ranged",
            "minimum_class_level": 3,
            "choose_total": 1,
            "grant_target": "proficiency",
            "option_pool": "kensei_ranged_weapons",
        },
        {
            "choice_key": "kensei-additional-weapons",
            "label": "Additional Kensei Weapons",
            "minimum_class_level": 6,
            "choose_total": 1,
            "progression": (
                {"class_level": 6, "choose_total": 1},
                {"class_level": 11, "choose_total": 2},
                {"class_level": 17, "choose_total": 3},
            ),
            "grant_target": "proficiency",
            "option_pool": "kensei_any_weapons",
        },
        {
            "choice_key": "kensei-artisan-tool",
            "label": "Way of the Brush",
            "minimum_class_level": 3,
            "choose_total": 1,
            "grant_target": "proficiency",
            "option_refs": (
                "srd5.1:proficiency:calligraphers-supplies",
                "srd5.1:proficiency:painters-supplies",
            ),
        },
    ),
    "phb2014:subclass:battle-master": (
        {
            "choice_key": "battle-master-student-of-war",
            "label": "Student of War — artisan tool",
            "minimum_class_level": 3,
            "choose_total": 1,
            "grant_target": "proficiency",
            "option_pool": "artisans_tools",
        },
    ),
    "xge:subclass:mastermind": (
        {
            "choice_key": "mastermind-gaming-set",
            "label": "Master of Intrigue — gaming set",
            "minimum_class_level": 3,
            "choose_total": 1,
            "grant_target": "proficiency",
            "option_pool": "gaming_sets",
        },
        {
            "choice_key": "mastermind-languages",
            "label": "Master of Intrigue — languages",
            "minimum_class_level": 3,
            "choose_total": 2,
            "grant_target": "language",
            "option_pool": "all_languages",
        },
    ),
    "tce:subclass:bladesinging": (
        {
            "choice_key": "bladesinger-weapon",
            "label": "Training in War and Song — weapon",
            "minimum_class_level": 2,
            "choose_total": 1,
            "grant_target": "proficiency",
            "option_pool": "one_handed_melee_weapons",
        },
    ),
}


FIXED_SPELLS: dict[str, tuple[dict[str, Any], ...]] = {
    "phb2014:subclass:light": (
        {"minimum_class_level": 1, "spell_ref": "srd5.1:spell:light", "access_type": "granted"},
    ),
    "xge:subclass:grave": (
        {"minimum_class_level": 1, "spell_ref": "srd5.1:spell:spare-the-dying", "access_type": "granted"},
    ),
    "xge:subclass:spores": (
        {"minimum_class_level": 2, "spell_ref": "srd5.1:spell:chill-touch", "access_type": "granted"},
    ),
    "tce:subclass:stars": (
        {"minimum_class_level": 2, "spell_ref": "srd5.1:spell:guidance", "access_type": "granted"},
    ),
    "phb2014:subclass:shadow": (
        {"minimum_class_level": 3, "spell_ref": "srd5.1:spell:minor-illusion", "access_type": "granted"},
    ),
    "xge:subclass:celestial": (
        {"minimum_class_level": 1, "spell_ref": "srd5.1:spell:light", "access_type": "granted"},
        {"minimum_class_level": 1, "spell_ref": "srd5.1:spell:sacred-flame", "access_type": "granted"},
    ),
    "scag:subclass:undying": (
        {"minimum_class_level": 1, "spell_ref": "srd5.1:spell:spare-the-dying", "access_type": "granted"},
    ),
    "xge:subclass:shadow-magic": (
        {"minimum_class_level": 3, "spell_ref": "srd5.1:spell:darkness", "access_type": "granted"},
    ),
    "tce:subclass:fathomless": (
        {"minimum_class_level": 10, "spell_ref": "srd5.1:spell:black-tentacles", "access_type": "granted"},
    ),
    "phb2014:subclass:totem-warrior": (
        {"minimum_class_level": 3, "spell_ref": "srd5.1:spell:beast-sense", "access_type": "granted"},
        {"minimum_class_level": 3, "spell_ref": "srd5.1:spell:speak-with-animals", "access_type": "granted"},
        {"minimum_class_level": 10, "spell_ref": "srd5.1:spell:commune-with-nature", "access_type": "granted"},
    ),
}


# Third-caster rows are verified against the PHB reference and a structured
# Aurora PHB transcription. Slots are class-local rows; multiclass merging is
# handled by the builder extension rather than by pretending Fighter/Rogue are
# full spellcasting classes.
THIRD_CASTER_ROWS: dict[int, dict[str, Any]] = {
    3: {"cantrips_known": 2, "spells_known": 3, "slots": (2, 0, 0, 0)},
    4: {"cantrips_known": 2, "spells_known": 4, "slots": (3, 0, 0, 0)},
    5: {"cantrips_known": 2, "spells_known": 4, "slots": (3, 0, 0, 0)},
    6: {"cantrips_known": 2, "spells_known": 4, "slots": (3, 0, 0, 0)},
    7: {"cantrips_known": 2, "spells_known": 5, "slots": (4, 2, 0, 0)},
    8: {"cantrips_known": 2, "spells_known": 6, "slots": (4, 2, 0, 0)},
    9: {"cantrips_known": 2, "spells_known": 6, "slots": (4, 2, 0, 0)},
    10: {"cantrips_known": 3, "spells_known": 7, "slots": (4, 3, 0, 0)},
    11: {"cantrips_known": 3, "spells_known": 8, "slots": (4, 3, 0, 0)},
    12: {"cantrips_known": 3, "spells_known": 8, "slots": (4, 3, 0, 0)},
    13: {"cantrips_known": 3, "spells_known": 9, "slots": (4, 3, 2, 0)},
    14: {"cantrips_known": 3, "spells_known": 10, "slots": (4, 3, 2, 0)},
    15: {"cantrips_known": 3, "spells_known": 10, "slots": (4, 3, 2, 0)},
    16: {"cantrips_known": 3, "spells_known": 11, "slots": (4, 3, 3, 0)},
    17: {"cantrips_known": 3, "spells_known": 11, "slots": (4, 3, 3, 0)},
    18: {"cantrips_known": 3, "spells_known": 11, "slots": (4, 3, 3, 0)},
    19: {"cantrips_known": 3, "spells_known": 12, "slots": (4, 3, 3, 1)},
    20: {"cantrips_known": 3, "spells_known": 13, "slots": (4, 3, 3, 1)},
}

THIRD_CASTERS: dict[str, dict[str, Any]] = {
    "phb2014:subclass:eldritch-knight": {
        "ability": "intelligence",
        "spell_class_ref": "srd5.1:class:wizard",
        "school_indices": ("abjuration", "evocation"),
        "fixed_cantrip_refs": (),
        "rows": THIRD_CASTER_ROWS,
    },
    "phb2014:subclass:arcane-trickster": {
        "ability": "intelligence",
        "spell_class_ref": "srd5.1:class:wizard",
        "school_indices": ("enchantment", "illusion"),
        "fixed_cantrip_refs": ("srd5.1:spell:mage-hand",),
        "rows": {
            level: {
                **row,
                "cantrips_known": row["cantrips_known"] + 1,
            }
            for level, row in THIRD_CASTER_ROWS.items()
        },
    },
}


UNRESOLVED_SPELL_ALIASES: dict[str, str] = {
    "畢格比之掌": "srd5.1:spell:arcane-hand",
    "畢格比之手": "srd5.1:spell:arcane-hand",
    "拉瑞心靈聯結": "srd5.1:spell:telepathic-bond",
    "拉瑞心靈連結": "srd5.1:spell:telepathic-bond",
    "涅斯圖魔法靈光": "srd5.1:spell:arcanists-magic-aura",
    "尼施圖魔法靈光": "srd5.1:spell:arcanists-magic-aura",
    "歐提路克彈力法球": "srd5.1:spell:resilient-sphere",
    "歐提路克韌性法球": "srd5.1:spell:resilient-sphere",
    "梅爾夫強酸箭": "srd5.1:spell:acid-arrow",
    "魔鄧肯忠犬": "srd5.1:spell:faithful-hound",
    "魔鄧肯之劍": "srd5.1:spell:arcane-sword",
    "譚森浮碟": "srd5.1:spell:floating-disk",
    "李歐蒙小屋": "srd5.1:spell:tiny-hut",
    "艾伐黑觸手": "srd5.1:spell:black-tentacles",
    "塔莎狂笑": "srd5.1:spell:hideous-laughter",
}


def _replace_entry(registry: M01JReferenceRegistry, entry: ContentEntry) -> None:
    if entry.key in registry.supplemental:
        registry.supplemental[entry.key] = entry
    else:
        registry.overrides[entry.key] = entry


def _update_subclass_data(
    registry: M01JReferenceRegistry,
    subclass_ref: str,
    **updates: Any,
) -> ContentEntry:
    entry = registry.get_optional(subclass_ref)
    if entry is None:
        raise ContentValidationError(f"M01-J rule fix references missing subclass {subclass_ref}")
    data = dict(entry.data)
    data.update(deepcopy(updates))
    next_entry = entry.model_copy(update={"data": data})
    _replace_entry(registry, next_entry)
    return next_entry


def _require_refs(registry: ContentRegistry, refs: Iterable[str], *, context: str) -> None:
    missing = [ref for ref in refs if registry.get_optional(ref) is None]
    if missing:
        raise ContentValidationError(f"{context}: missing canonical refs {missing}")


def _generated_options_for_parent(
    registry: M01JReferenceRegistry,
    subclass_ref: str,
    parent_names: set[str],
) -> tuple[str, ...]:
    refs: list[str] = []
    for feature in registry.list_kind("feature"):
        raw_subclass = feature.data.get("subclass")
        if not isinstance(raw_subclass, dict) or raw_subclass.get("key") != subclass_ref:
            continue
        parent_ref = feature.data.get("choice_option_for")
        if not isinstance(parent_ref, str):
            continue
        parent = registry.get_optional(parent_ref)
        if parent is not None and parent.name in parent_names:
            refs.append(feature.key)
    return tuple(dict.fromkeys(refs))


def _make_choice(
    *,
    key: str,
    feature_ref: str,
    label: str,
    level: int,
    count: int,
    option_refs: Iterable[str],
    progression: Iterable[dict[str, int]] = (),
    option_minimum_levels: dict[str, int] | None = None,
) -> dict[str, Any]:
    return {
        "choice_key": key,
        "feature_ref": feature_ref,
        "minimum_class_level": level,
        "choose_total": count,
        "progression": tuple(deepcopy(tuple(progression))),
        "option_refs": tuple(option_refs),
        "option_minimum_levels": dict(option_minimum_levels or {}),
        "label": label,
    }


def _feature_ref_by_name(
    registry: M01JReferenceRegistry,
    subclass_ref: str,
    name: str,
) -> str:
    for feature in registry.list_kind("feature"):
        parent = feature.data.get("subclass")
        if isinstance(parent, dict) and parent.get("key") == subclass_ref and feature.name == name:
            return feature.key
    raise ContentValidationError(f"{subclass_ref}: cannot find generated feature {name!r}")


def _normalize_feature_choices(registry: M01JReferenceRegistry) -> None:
    # Battle Master: the PHB/TCE maneuver entries already form one canonical
    # pool. Do not duplicate the same maneuvers as docs-generated option rows.
    battle_master = "phb2014:subclass:battle-master"
    maneuver_refs = tuple(
        entry.key
        for entry in registry.list_kind("feature")
        if isinstance(entry.data.get("choice_pool_option"), dict)
        and entry.data["choice_pool_option"].get("pool") == "battle-master-maneuver"
    )
    if not maneuver_refs:
        raise ContentValidationError("M01-J Battle Master has no canonical maneuver pool")
    battle_feature = _feature_ref_by_name(registry, battle_master, "Combat Superiority")
    _update_subclass_data(
        registry,
        battle_master,
        persistent_choices=[
            _make_choice(
                key="battle-master-maneuvers",
                feature_ref=battle_feature,
                label="Battle Master Maneuvers",
                level=3,
                count=3,
                option_refs=maneuver_refs,
                progression=(
                    {"class_level": 3, "choose_total": 3},
                    {"class_level": 7, "choose_total": 5},
                    {"class_level": 10, "choose_total": 7},
                    {"class_level": 15, "choose_total": 9},
                ),
            )
        ],
    )

    arcane_archer = "xge:subclass:arcane-archer"
    shot_refs = _generated_options_for_parent(
        registry,
        arcane_archer,
        {"Arcane Shot Options"},
    )
    if len(shot_refs) < 8:
        raise ContentValidationError(
            f"M01-J Arcane Archer expected at least 8 Arcane Shot options, got {len(shot_refs)}"
        )
    shot_feature = _feature_ref_by_name(registry, arcane_archer, "Arcane Shot")
    _update_subclass_data(
        registry,
        arcane_archer,
        persistent_choices=[
            _make_choice(
                key="arcane-shot-options",
                feature_ref=shot_feature,
                label="Arcane Shot Options",
                level=3,
                count=2,
                option_refs=shot_refs,
                progression=(
                    {"class_level": 3, "choose_total": 2},
                    {"class_level": 7, "choose_total": 3},
                    {"class_level": 10, "choose_total": 4},
                    {"class_level": 15, "choose_total": 5},
                    {"class_level": 18, "choose_total": 6},
                ),
            )
        ],
    )

    rune_knight = "tce:subclass:rune-knight"
    rune_refs = _generated_options_for_parent(registry, rune_knight, {"Rune Carver"})
    if len(rune_refs) < 6:
        raise ContentValidationError(
            f"M01-J Rune Knight expected at least 6 rune options, got {len(rune_refs)}"
        )
    rune_feature = _feature_ref_by_name(registry, rune_knight, "Rune Carver")
    min_levels = {
        ref: 7
        for ref in rune_refs
        if registry.get(ref).name in {"Hill Rune", "Storm Rune"}
    }
    _update_subclass_data(
        registry,
        rune_knight,
        persistent_choices=[
            _make_choice(
                key="rune-carver",
                feature_ref=rune_feature,
                label="Rune Carver",
                level=3,
                count=2,
                option_refs=rune_refs,
                progression=(
                    {"class_level": 3, "choose_total": 2},
                    {"class_level": 7, "choose_total": 3},
                    {"class_level": 10, "choose_total": 4},
                    {"class_level": 15, "choose_total": 5},
                ),
                option_minimum_levels=min_levels,
            )
        ],
    )

    four_elements = "phb2014:subclass:four-elements"
    discipline_refs = _generated_options_for_parent(
        registry,
        four_elements,
        {"Elemental Disciplines"},
    )
    if len(discipline_refs) < 10:
        raise ContentValidationError(
            f"M01-J Four Elements expected discipline options, got {len(discipline_refs)}"
        )
    attunement_ref = next(
        (ref for ref in discipline_refs if registry.get(ref).name == "Elemental Attunement"),
        None,
    )
    if attunement_ref is None:
        raise ContentValidationError("M01-J Four Elements is missing Elemental Attunement")
    selectable = tuple(ref for ref in discipline_refs if ref != attunement_ref)
    option_minimum_levels: dict[str, int] = {}
    for ref in selectable:
        heading = registry.get(ref).data.get("reference_heading_zh")
        if isinstance(heading, str):
            match = re.search(r"需要\s*(\d+)\s*級", heading)
            if match:
                option_minimum_levels[ref] = int(match.group(1))
    discipline_feature = _feature_ref_by_name(registry, four_elements, "Elemental Disciplines")
    _update_subclass_data(
        registry,
        four_elements,
        persistent_choices=[
            _make_choice(
                key="elemental-disciplines",
                feature_ref=discipline_feature,
                label="Elemental Disciplines",
                level=3,
                count=1,
                option_refs=selectable,
                progression=(
                    {"class_level": 3, "choose_total": 1},
                    {"class_level": 6, "choose_total": 2},
                    {"class_level": 11, "choose_total": 3},
                    {"class_level": 17, "choose_total": 4},
                ),
                option_minimum_levels=option_minimum_levels,
            )
        ],
        fixed_feature_refs=[attunement_ref],
    )

    # Form of the Beast choices are made each time Rage starts. They are not a
    # permanent Build choice, so the generic H5 parser must not persist them.
    _update_subclass_data(registry, "tce:subclass:beast", persistent_choices=[])

    # Storm Herald uses one current environment identity. Later Desert/Sea/
    # Tundra headings describe the effects of that same choice, not new choices.
    storm_herald = "xge:subclass:storm-herald"
    environment_refs = _generated_options_for_parent(registry, storm_herald, {"Storm Aura"})
    if environment_refs:
        aura_feature = _feature_ref_by_name(registry, storm_herald, "Storm Aura")
        _update_subclass_data(
            registry,
            storm_herald,
            persistent_choices=[
                _make_choice(
                    key="storm-aura-environment",
                    feature_ref=aura_feature,
                    label="Storm Aura Environment",
                    level=3,
                    count=1,
                    option_refs=environment_refs,
                )
            ],
        )


def _new_option_feature(
    registry: M01JReferenceRegistry,
    subclass_ref: str,
    *,
    suffix: str,
    name: str,
    zh_name: str,
    source_feature_ref: str,
) -> str:
    subclass = registry.get(subclass_ref)
    parsed = parse_stable_key(subclass_ref, kinds={"subclass"})
    index = f"{parsed.index}-m01j-choice-{suffix}"
    key = stable_key(parsed.source, "feature", index)
    if registry.get_optional(key) is not None:
        return key
    parent = subclass.data.get("class")
    if not isinstance(parent, dict):
        raise ContentValidationError(f"{subclass_ref}: missing class parent")
    entry = ContentEntry.model_validate(
        {
            "key": key,
            "index": index,
            "name": name,
            "source": parsed.source,
            "ruleset": "dnd5e-2014",
            "source_label": registry.source_label(parsed.source),
            "provenance": {
                "type": "repository-reference-normalization",
                "phase": "M01-J",
                "subclass_ref": subclass_ref,
            },
            "data": {
                "index": index,
                "name": name,
                "level": int(subclass.data.get("acquisition_class_level", 1)),
                "class": parent,
                "subclass": {"key": subclass_ref, "name": subclass.name},
                "choice_option_for": source_feature_ref,
                "reference_heading_zh": zh_name,
            },
        }
    )
    registry.supplemental[key] = entry
    registry.m01j_localization_overlays.setdefault((parsed.source, "zh-TW"), {}).setdefault(
        key, {"name": zh_name}
    )
    return key


def _spell_record(
    registry: ContentRegistry,
    spell_ref: str,
    *,
    minimum_class_level: int,
    access_type: str,
    choice_key: str | None = None,
    option_ref: str | None = None,
) -> dict[str, Any]:
    spell = registry.get_optional(spell_ref)
    if spell is None:
        raise ContentValidationError(f"M01-J missing normalized spell {spell_ref}")
    record: dict[str, Any] = {
        "prerequisites": [
            {
                "index": f"m01j-{minimum_class_level}",
                "type": "level",
                "name": f"Class Level {minimum_class_level}",
            }
        ],
        "spell": {"key": spell_ref, "name": spell.name},
        "access_type": access_type,
    }
    if choice_key is not None and option_ref is not None:
        record["choice_key"] = choice_key
        record["option_ref"] = option_ref
    return record


def _normalize_divine_soul(registry: M01JReferenceRegistry, resolver: _SpellResolver) -> None:
    subclass_ref = "xge:subclass:divine-soul"
    feature_ref = _feature_ref_by_name(registry, subclass_ref, "Divine Magic")
    affinities = (
        ("good", "Good", "善良", "治療傷勢"),
        ("evil", "Evil", "邪惡", "造成傷勢"),
        ("law", "Law", "守序", "祝福術"),
        ("chaos", "Chaos", "混亂", "災禍術"),
        ("neutrality", "Neutrality", "中立", "防護善惡"),
    )
    option_refs: list[str] = []
    spells: list[dict[str, Any]] = []
    choice_key = "divine-soul-affinity"
    for suffix, name, zh_name, spell_name in affinities:
        option_ref = _new_option_feature(
            registry,
            subclass_ref,
            suffix=f"affinity-{suffix}",
            name=name,
            zh_name=zh_name,
            source_feature_ref=feature_ref,
        )
        spell_ref = resolver.resolve(spell_name)
        if spell_ref is None:
            raise ContentValidationError(
                f"M01-J Divine Soul cannot resolve affinity spell {spell_name}"
            )
        option_refs.append(option_ref)
        spells.append(
            _spell_record(
                registry,
                spell_ref,
                minimum_class_level=1,
                access_type="granted",
                choice_key=choice_key,
                option_ref=option_ref,
            )
        )
    _update_subclass_data(
        registry,
        subclass_ref,
        persistent_choices=[
            _make_choice(
                key=choice_key,
                feature_ref=feature_ref,
                label="Divine Soul Affinity",
                level=1,
                count=1,
                option_refs=option_refs,
            )
        ],
        spells=spells,
    )


def _normalize_genie(registry: M01JReferenceRegistry, resolver: _SpellResolver) -> None:
    subclass_ref = "tce:subclass:genie"
    feature_ref = _feature_ref_by_name(registry, subclass_ref, "Expanded Spell List")
    choice_key = "genie-kind"
    kinds = (
        ("dao", "Dao", "土巨靈"),
        ("djinni", "Djinni", "氣巨靈"),
        ("efreeti", "Efreeti", "火巨靈"),
        ("marid", "Marid", "水巨靈"),
    )
    option_refs = {
        kind: _new_option_feature(
            registry,
            subclass_ref,
            suffix=f"genie-{kind}",
            name=name,
            zh_name=zh_name,
            source_feature_ref=feature_ref,
        )
        for kind, name, zh_name in kinds
    }
    common = (
        (1, "偵測善惡"),
        (2, "魅影之力"),
        (3, "創造飲食"),
        (4, "魅影殺手"),
        (5, "造物術"),
        (9, "祈願術"),
    )
    branches = {
        "dao": ((1, "聖域術"), (2, "荊棘叢生"), (3, "融身入石"), (4, "塑石術"), (5, "石牆術")),
        "djinni": ((1, "雷鳴波"), (2, "造風術"), (3, "風牆術"), (4, "高等隱形術"), (5, "偽裝術")),
        "efreeti": ((1, "燃燒之手"), (2, "灼熱射線"), (3, "火球術"), (4, "火焰護盾"), (5, "焰擊術")),
        "marid": ((1, "雲霧術"), (2, "朦朧術"), (3, "雪雨暴"), (4, "操控水體"), (5, "寒冰錐")),
    }
    expanded: list[dict[str, Any]] = []
    for level, spell_name in common:
        spell_ref = resolver.resolve(spell_name)
        if spell_ref is None:
            raise ContentValidationError(f"M01-J Genie cannot resolve common spell {spell_name}")
        expanded.append(
            _spell_record(
                registry,
                spell_ref,
                minimum_class_level=level,
                access_type="expanded",
            )
        )
    for kind, rows in branches.items():
        for level, spell_name in rows:
            spell_ref = resolver.resolve(spell_name)
            if spell_ref is None:
                raise ContentValidationError(
                    f"M01-J Genie cannot resolve {kind} spell {spell_name}"
                )
            expanded.append(
                _spell_record(
                    registry,
                    spell_ref,
                    minimum_class_level=level,
                    access_type="expanded",
                    choice_key=choice_key,
                    option_ref=option_refs[kind],
                )
            )
    subclass = registry.get(subclass_ref)
    prior_choices = [
        choice
        for choice in subclass.data.get("persistent_choices", [])
        if isinstance(choice, dict) and choice.get("choice_key") != choice_key
    ]
    prior_choices.append(
        _make_choice(
            key=choice_key,
            feature_ref=feature_ref,
            label="Genie Kind",
            level=1,
            count=1,
            option_refs=option_refs.values(),
        )
    )
    _update_subclass_data(
        registry,
        subclass_ref,
        persistent_choices=prior_choices,
        expanded_spells=expanded,
    )


def _normalize_unresolved_spells(registry: M01JReferenceRegistry, resolver: _SpellResolver) -> None:
    for subclass in tuple(registry.list_kind("subclass")):
        changed = False
        data = dict(subclass.data)
        for field in ("spells", "expanded_spells"):
            raw_rows = data.get(field)
            if not isinstance(raw_rows, list):
                continue
            rows: list[dict[str, Any]] = []
            for raw in raw_rows:
                if not isinstance(raw, dict):
                    rows.append(raw)
                    continue
                unresolved = raw.get("unresolved_spell_name")
                if not isinstance(unresolved, str):
                    rows.append(raw)
                    continue
                spell_ref = resolver.resolve(unresolved) or UNRESOLVED_SPELL_ALIASES.get(unresolved)
                if spell_ref is None or registry.get_optional(spell_ref) is None:
                    rows.append(raw)
                    continue
                next_raw = dict(raw)
                next_raw.pop("unresolved_spell_name", None)
                next_raw["spell"] = {
                    "key": spell_ref,
                    "name": registry.get(spell_ref).name,
                }
                rows.append(next_raw)
                changed = True
            data[field] = rows
        if changed:
            _replace_entry(registry, subclass.model_copy(update={"data": data}))


def _attach_static_metadata(registry: M01JReferenceRegistry) -> None:
    for subclass_ref, grants in FIXED_GRANTS.items():
        refs = tuple(ref for values in grants.values() for ref in values)
        _require_refs(registry, refs, context=f"{subclass_ref} fixed grants")
        _update_subclass_data(registry, subclass_ref, fixed_grants=grants)

    for subclass_ref, choices in GRANT_CHOICES.items():
        direct_refs = tuple(
            ref
            for choice in choices
            for ref in choice.get("option_refs", ())
            if isinstance(ref, str)
        )
        _require_refs(registry, direct_refs, context=f"{subclass_ref} grant choices")
        _update_subclass_data(registry, subclass_ref, grant_choices=list(choices))

    for subclass_ref, rows in FIXED_SPELLS.items():
        valid_rows: list[dict[str, Any]] = []
        for row in rows:
            spell_ref = str(row["spell_ref"])
            _require_refs(registry, (spell_ref,), context=f"{subclass_ref} fixed spell")
            valid_rows.append(
                _spell_record(
                    registry,
                    spell_ref,
                    minimum_class_level=int(row["minimum_class_level"]),
                    access_type=str(row["access_type"]),
                )
            )
        subclass = registry.get(subclass_ref)
        current = [row for row in subclass.data.get("spells", []) if isinstance(row, dict)]
        identities = {
            (row.get("spell", {}).get("key"), row.get("access_type"))
            for row in current
            if isinstance(row.get("spell"), dict)
        }
        for row in valid_rows:
            identity = (row["spell"]["key"], row["access_type"])
            if identity not in identities:
                current.append(row)
                identities.add(identity)
        _update_subclass_data(registry, subclass_ref, spells=current)

    for subclass_ref, spec in THIRD_CASTERS.items():
        fixed = tuple(spec.get("fixed_cantrip_refs", ()))
        _require_refs(registry, fixed, context=f"{subclass_ref} third-caster fixed cantrips")
        _update_subclass_data(registry, subclass_ref, subclass_spellcasting=spec)


def _validate_no_unresolved_spells(registry: M01JReferenceRegistry) -> None:
    unresolved: list[str] = []
    for subclass in registry.list_kind("subclass"):
        for field in ("spells", "expanded_spells"):
            rows = subclass.data.get(field, [])
            if not isinstance(rows, list):
                continue
            for row in rows:
                if isinstance(row, dict) and isinstance(row.get("unresolved_spell_name"), str):
                    unresolved.append(f"{subclass.key}:{field}:{row['unresolved_spell_name']}")
    if unresolved:
        raise ContentValidationError(
            "M01-J unresolved repository spell references remain: " + ", ".join(unresolved)
        )


def apply_m01j_reference_fixes(registry: ContentRegistry) -> ContentRegistry:
    """Normalize complex M01-J repository rules after generic MD generation."""

    if not isinstance(registry, M01JReferenceRegistry):
        raise ContentValidationError("M01-J reference fixes require M01JReferenceRegistry")
    resolver = _SpellResolver(registry)
    _normalize_feature_choices(registry)
    _normalize_divine_soul(registry, resolver)
    _normalize_genie(registry, resolver)
    _attach_static_metadata(registry)
    _normalize_unresolved_spells(registry, resolver)
    _validate_no_unresolved_spells(registry)
    return registry
