"""M01-O — XGE/TCE feat automation classification and boundary tests."""

from __future__ import annotations

from pathlib import Path
import re

import m01k_support as S
from app.domain.character.schemas import CharacterState
from app.domain.rules.armor_class import calculate_armor_class
from app.domain.rules.hit_points import calculate_max_hp
from app.domain.rules.skills import passive_investigation, passive_perception


import m01m_support

APP_ROOT = Path(__file__).resolve().parents[1] / "app"

M01O_AUTOMATION_EXPECTATIONS: dict[str, str] = {
    # structured_deferred_reaction (3)
    "xge:feat:bountiful-luck": "structured_deferred_reaction",
    "xge:feat:second-chance": "structured_deferred_reaction",
    "xge:feat:fade-away": "structured_deferred_reaction",
    # structured_deferred_combat (7)
    "xge:feat:dragon-fear": "structured_deferred_combat",
    "tce:feat:crusher": "structured_deferred_combat",
    "tce:feat:slasher": "structured_deferred_combat",
    "tce:feat:telekinetic": "structured_deferred_combat",
    "xge:feat:dwarven-fortitude": "structured_deferred_combat",
    "xge:feat:orcish-fury": "structured_deferred_combat",
    "tce:feat:gunner": "structured_deferred_combat",
    # structured_deferred_roll (3)
    "xge:feat:elven-accuracy": "structured_deferred_roll",
    "xge:feat:flames-of-phlegethos": "structured_deferred_roll",
    "tce:feat:piercer": "structured_deferred_roll",
    # structured_deferred_inventory (1)
    "tce:feat:poisoner": "structured_deferred_inventory",
    # structured_deferred_rest (1)
    "tce:feat:chef": "structured_deferred_rest",
    # static_derived (4)
    "xge:feat:dragon-hide": "static_derived",
    "xge:feat:infernal-constitution": "static_derived",
    "xge:feat:squat-nimbleness": "static_derived",
    "tce:feat:telepathic": "static_derived",
    # full_structural (11)
    "xge:feat:prodigy": "full_structural",
    "xge:feat:drow-high-magic": "full_structural",
    "xge:feat:fey-teleportation": "full_structural",
    "xge:feat:wood-elf-magic": "full_structural",
    "tce:feat:artificer-initiate": "full_structural",
    "tce:feat:eldritch-adept": "full_structural",
    "tce:feat:fey-touched": "full_structural",
    "tce:feat:fighting-initiate": "full_structural",
    "tce:feat:metamagic-adept": "full_structural",
    "tce:feat:shadow-touched": "full_structural",
    "tce:feat:skill-expert": "full_structural",
}

DEFERRED_FEAT_CONFIGS: dict[str, dict] = {
    "xge:feat:bountiful-luck": {
        "race": "srd5.1:race:halfling",
        "subrace": "srd5.1:subrace:lightfoot-halfling",
    },
    "xge:feat:dragon-fear": {
        "race": "srd5.1:race:dragonborn",
        "nested": {"ability": ("ability:strength",)},
    },
    "xge:feat:dwarven-fortitude": {
        "race": "srd5.1:race:dwarf",
        "subrace": "srd5.1:subrace:hill-dwarf",
    },
    "xge:feat:elven-accuracy": {
        "race": "srd5.1:race:elf",
        "subrace": "srd5.1:subrace:high-elf",
        "nested": {"ability": ("ability:dexterity",)},
    },
    "xge:feat:fade-away": {
        "race": "srd5.1:race:gnome",
        "subrace": "srd5.1:subrace:rock-gnome",
        "nested": {"ability": ("ability:dexterity",)},
    },
    "xge:feat:flames-of-phlegethos": {
        "race": "srd5.1:race:tiefling",
        "nested": {"ability": ("ability:intelligence",)},
    },
    "xge:feat:orcish-fury": {
        "race": "srd5.1:race:half-orc",
        "nested": {"ability": ("ability:strength",)},
    },
    "xge:feat:second-chance": {
        "race": "srd5.1:race:halfling",
        "subrace": "srd5.1:subrace:lightfoot-halfling",
        "nested": {"ability": ("ability:dexterity",)},
    },
    "tce:feat:chef": {"nested": {"ability": ("ability:constitution",)}},
    "tce:feat:crusher": {"nested": {"ability": ("ability:strength",)}},
    "tce:feat:gunner": {},
    "tce:feat:piercer": {"nested": {"ability": ("ability:strength",)}},
    "tce:feat:poisoner": {},
    "tce:feat:slasher": {"nested": {"ability": ("ability:strength",)}},
    "tce:feat:telekinetic": {"nested": {"ability": ("ability:intelligence",)}},
}

EVEN_ABILITIES = {
    "strength": 14,
    "dexterity": 14,
    "constitution": 14,
    "intelligence": 14,
    "wisdom": 14,
    "charisma": 14,
}

FORBIDDEN_COMBAT_RE = re.compile(
    r"(?:app\.(?:domain\.)?combat|trigger_dsl|TriggerRule)",
    re.IGNORECASE,
)


def test_m01o_feats_are_not_mislabelled_as_fully_automated() -> None:
    content = S.registry()
    assert len(M01O_AUTOMATION_EXPECTATIONS) == 30

    for feat_key, expected_automation in M01O_AUTOMATION_EXPECTATIONS.items():
        entry = content.get(feat_key)
        actual = entry.data.get("automation")
        assert actual == expected_automation, f"{feat_key}: expected {expected_automation}, got {actual}"

    # Poisoner mechanics sub-automation check
    poisoner_entry = content.get("tce:feat:poisoner")
    mechanics = poisoner_entry.data.get("mechanics", [])
    ignore_mech = next((m for m in mechanics if m.get("kind") == "ignore_poison_resistance"), None)
    assert ignore_mech is not None, "missing ignore_poison_resistance in poisoner mechanics"
    assert ignore_mech.get("automation") == "structured_deferred_combat"


def test_deferred_m01o_feats_do_not_change_derived_sheet_values() -> None:
    content = S.registry()

    for feat_key, config in DEFERRED_FEAT_CONFIGS.items():
        race = config.get("race", "srd5.1:race:human")
        nested = config.get("nested")

        payload = S.payload(
            S.levels_for(S.FIGHTER_L4),
            race=race,
            abilities=EVEN_ABILITIES,
        )
        if "subrace" in config:
            payload = m01m_support.with_subrace(payload, config["subrace"])

        base = S.auto_fill(payload, content)
        result, _ = S.compile_payload(base, content)
        opp = S.feat_opportunities(result)[0]
        feat_payload = S.with_selections(
            base,
            {opp.choice_id: S.selection(opp.choice_id, feat_key, source_ref=opp.source_ref)},
        )
        if nested:
            feat_payload = S.with_selections(feat_payload, S.nested_selections(opp.choice_id, feat_key, nested))
        feat_payload = S.auto_fill(feat_payload, content, skip_sources=set())
        feat_res, _ = S.compile_payload(feat_payload, content)

        assert S.issue_codes(feat_res) == set(), f"{feat_key} had issues: {feat_res.validation.issues}"
        build = feat_res.build_candidate
        assert build is not None, f"{feat_key} build_candidate is None"

        # A deferred feat may never contribute a static derived modifier
        assert build.static_derived_modifiers == (), f"{feat_key} contributed static_derived_modifiers"

        # Derived values must obey standard rule formulas without silent feat adjustments
        con_mod = (build.ability_scores.constitution - 10) // 2
        dex_mod = (build.ability_scores.dexterity - 10) // 2
        wis_mod = (build.ability_scores.wisdom - 10) // 2
        int_mod = (build.ability_scores.intelligence - 10) // 2

        expected_hp = (10 + con_mod) + 3 * (6 + con_mod)
        assert calculate_max_hp(build) == expected_hp, f"{feat_key} unexpected HP"

        assert calculate_armor_class(build, CharacterState(current_hp=10), content) == 10 + dex_mod
        race_speed = content.get(race).data["speed"]
        assert build.walking_speed == race_speed

        perc_prof = 2 if "srd5.1:skill:perception" in build.skill_choices else 0
        inv_prof = 2 if "srd5.1:skill:investigation" in build.skill_choices else 0
        assert passive_perception(build, content) == 10 + wis_mod + perc_prof
        assert passive_investigation(build, content) == 10 + int_mod + inv_prof


def test_m01o_content_and_domain_do_not_import_combat_or_trigger_dsl() -> None:
    offenders: list[tuple[str, int, str]] = []

    scan_dirs = [
        APP_ROOT / "content",
        APP_ROOT / "domain" / "character",
        APP_ROOT / "domain" / "character_builder",
    ]

    for scan_dir in scan_dirs:
        for py_path in scan_dir.rglob("*.py"):
            text = py_path.read_text(encoding="utf-8")
            for line_no, line in enumerate(text.splitlines(), start=1):
                match = FORBIDDEN_COMBAT_RE.search(line)
                if match:
                    offenders.append((str(py_path.relative_to(APP_ROOT)), line_no, line.strip()))

    assert offenders == [], f"Found forbidden combat/trigger references in domain: {offenders}"
