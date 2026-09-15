"""Author P4-A SRD Monster zh-TW labels from pinned project/reference data.

P4-A requires explicit Traditional Chinese coverage for every Monster name and
for every user-visible named combat affordance. Canonical English descriptions
remain untouched until a later P4 subphase exposes those long-form fields.

This script owns ``data/srd5.1/locales/zh-TW/monster.json``. Runtime never reads
the external reference checkout; only the generated checked-in locale shard is
consumed at runtime.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Iterable

SCRIPTS_ROOT = Path(__file__).resolve().parent
ROOT = SCRIPTS_ROOT.parent
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

import build_m02d_srd_locale as base
import build_m02d_srd_locale_reviewed as reviewed
import run_m02d_srd_locale_authoring as authoring

MONSTERS_PATH = ROOT / "data" / "srd5.1" / "monsters.json"
DEFAULT_OVERLAY = ROOT / "data" / "srd5.1" / "locales" / "zh-TW" / "monster.json"
DEFAULT_REPORT = ROOT / "data" / "localization" / "p4a-monster-zh-tw-report.json"
REFERENCE_COMMIT = authoring.AUTHORING_REFERENCE_COMMIT
REFERENCE_SUBDIR = authoring.AUTHORING_REFERENCE_SUBDIR

AFFORDANCE_COLLECTIONS = (
    "special_abilities",
    "actions",
    "bonus_actions",
    "reactions",
    "legendary_actions",
)
HAN_RE = re.compile(r"[\u3400-\u9fff]")
ASCII_WORD_RE = re.compile(r"[A-Za-z]{2,}")
UNTRANSLATED_RE = re.compile(r"〔未譯:[^〕]+〕")
COST_SUFFIX_RE = re.compile(r"^(?P<base>.+) \(Costs (?P<count>\d+) Actions?\)$")
FORM_ONLY_RE = re.compile(r"^(?P<base>.+) \((?P<form>Object|Hag|Fiend) Form Only\)$")
BEAST_BITE_RE = re.compile(r"^(?P<base>.+) \(Bite in Beast Form\)$")
CREATURE_FORM_RE = re.compile(
    r"^(?P<creature>Vampire|Werebear|Wereboar|Wererat|Weretiger|Werewolf), "
    r"(?P<form>Bat|Mist|Vampire|Bear|Boar|Human|Hybrid|Rat|Tiger|Wolf) Form$"
)

P4A_EXACT_NAMES: dict[str, str] = {
    "Multiattack": "多重攻擊",
    "Spellcasting": "施法",
    "Innate Spellcasting": "天生施法",
    "Legendary Resistance": "傳奇抗性",
    "Magic Resistance": "魔法抗性",
    "Magic Weapons": "魔法武器",
    "Keen Hearing": "敏銳聽覺",
    "Keen Sight": "敏銳視覺",
    "Keen Smell": "敏銳嗅覺",
    "Keen Hearing and Smell": "敏銳聽覺與嗅覺",
    "Keen Sight and Smell": "敏銳視覺與嗅覺",
    "Pack Tactics": "群體戰術",
    "Flyby": "掠飛",
    "Amphibious": "水陸兩棲",
    "Hold Breath": "閉氣",
    "Water Breathing": "水下呼吸",
    "Spider Climb": "蛛行",
    "Web Sense": "蛛網感知",
    "Web Walker": "蛛網行者",
    "False Appearance": "虛假外貌",
    "Shapechanger": "變形者",
    "Regeneration": "再生",
    "Charge": "衝鋒",
    "Pounce": "撲擊",
    "Rampage": "暴走",
    "Trampling Charge": "踐踏衝鋒",
    "Sure-Footed": "穩健步伐",
    "Standing Leap": "立定跳躍",
    "Echolocation": "回聲定位",
    "Blood Frenzy": "嗜血狂暴",
    "Aggressive": "侵略性",
    "Brute": "蠻力",
    "Martial Advantage": "武技優勢",
    "Sunlight Sensitivity": "陽光敏感",
    "Nimble Escape": "靈巧脫逃",
    "Undead Fortitude": "不死強韌",
    "Turn Immunity": "驅散免疫",
    "Turn Resistance": "驅散抗性",
    "Immutable Form": "不變形體",
    "Damage Transfer": "傷害轉移",
    "Death Burst": "死亡爆發",
    "Illumination": "照明",
    "Light Sensitivity": "光線敏感",
    "Antimagic Susceptibility": "反魔法弱點",
    "Avoidance": "迴避本能",
    "Reactive": "快速反應",
    "Siege Monster": "攻城怪物",
    "Actions": "動作",
    "Detect": "偵測",
    "Tail Swipe": "掃尾",
    "Tail Attack": "尾擊",
    "Wing Attack": "翼擊",
    "Psychic Drain": "心靈吸取",
    "Teleport": "傳送",
    "Cast a Spell": "施放法術",
    "Fling": "拋擲",
    "Tentacle Attack or Fling": "觸手攻擊或拋擲",
    "Lightning Storm": "閃電風暴",
    "Ink Cloud": "墨雲",
    "Paralyzing Touch": "麻痺之觸",
    "Frightening Gaze": "恐懼凝視",
    "Disrupt Life": "擾亂生命",
    "Adhesive": "黏著",
    "Blasphemous Word": "褻瀆之言",
    "Channel Negative Energy": "引導負能量",
    "Whirlwind of Sand": "沙之旋風",
    "Night Hag Items": "夜鬼婆物品",
    "Shadow Stealth": "暗影隱匿",
    "Searing Burst": "灼熱爆發",
    "Blinding Gaze": "致盲凝視",
    "Chomp": "大口啃咬",
    "Shimmering Shield": "閃耀護盾",
    "Heal Self": "自我治療",
    "Tusks": "獠牙",
    "Bite": "啃咬",
    "Claw": "爪擊",
    "Claws": "爪擊",
    "Tail": "尾擊",
    "Tentacle": "觸手",
    "Tentacles": "觸手",
    "Slam": "猛擊",
    "Slam Attack": "猛擊",
    "Fist": "拳擊",
    "Hooves": "蹄擊",
    "Horns": "角擊",
    "Gore": "頂撞",
    "Ram": "衝撞",
    "Sting": "螫刺",
    "Beak": "喙擊",
    "Talons": "利爪",
    "Constrict": "纏勒",
    "Club": "棍棒",
    "Greatclub": "巨棍",
    "Mace": "釘頭錘",
    "Morningstar": "晨星錘",
    "Scimitar": "彎刀",
    "Shortsword": "短劍",
    "Longsword": "長劍",
    "Greatsword": "巨劍",
    "Dagger": "匕首",
    "Spear": "長矛",
    "Javelin": "標槍",
    "Trident": "三叉戟",
    "Quarterstaff": "長棍",
    "Warhammer": "戰錘",
    "Battleaxe": "戰斧",
    "Greataxe": "巨斧",
    "Handaxe": "手斧",
    "Light Hammer": "輕錘",
    "Longbow": "長弓",
    "Shortbow": "短弓",
    "Crossbow": "弩",
    "Heavy Crossbow": "重弩",
    "Light Crossbow": "輕弩",
    "Sling": "投石索",
    "Rock": "岩石",
    "Enslave": "奴役",
    "Frightful Presence": "恐懼威儀",
    "Adult Brass Dragon": "成年黃銅龍",
    "Young Silver Dragon": "幼年銀龍",
    "Deep Gnome (Svirfneblin)": "深地侏儒（斯弗涅布林）",
    "Succubus/Incubus": "魅魔／夢魔",
}

CREATURE_FORM_NAMES = {
    "Vampire": "吸血鬼",
    "Werebear": "熊人",
    "Wereboar": "野豬人",
    "Wererat": "鼠人",
    "Weretiger": "虎人",
    "Werewolf": "狼人",
}
FORM_NAMES = {
    "Bat": "蝙蝠",
    "Mist": "霧氣",
    "Vampire": "吸血鬼",
    "Bear": "熊",
    "Boar": "野豬",
    "Human": "人類",
    "Hybrid": "混合",
    "Rat": "老鼠",
    "Tiger": "老虎",
    "Wolf": "狼",
}
FORM_ONLY_NAMES = {
    "Object": "物件",
    "Hag": "鬼婆",
    "Fiend": "邪魔",
}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _empty_overlay() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "locale": "zh-TW",
        "review_status": "p4a-explicit-label-coverage",
        "translation_method": "pinned-reference-plus-project-terminology",
        "entries": {},
    }


def _iter_display_names(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        name = value.get("name")
        if isinstance(name, str):
            yield name
        for child in value.values():
            yield from _iter_display_names(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_display_names(child)


def load_deep_reference_names(reference_root: Path) -> dict[str, str]:
    """Collect unambiguous English -> zh-TW pairs from nested Foundry payloads."""

    names: dict[str, str] = {}
    conflicts: set[str] = set()
    for path in sorted(reference_root.rglob("*.json")):
        try:
            payload = _load_json(path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        for display_name in _iter_display_names(payload):
            pair = reviewed._reference_pair(display_name)
            if pair is None:
                continue
            normalized, zh = pair
            if normalized in conflicts:
                continue
            previous = names.get(normalized)
            if previous is not None and previous != zh:
                names.pop(normalized, None)
                conflicts.add(normalized)
                continue
            names[normalized] = zh
    return names


def _reference_root(checkout: Path) -> Path:
    try:
        head = subprocess.run(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(f"cannot read reference checkout HEAD: {checkout}") from exc
    if head != REFERENCE_COMMIT:
        raise ValueError(
            f"P4-A reference checkout must be pinned to {REFERENCE_COMMIT}; got {head}"
        )
    root = checkout / REFERENCE_SUBDIR
    if not root.is_dir():
        raise ValueError(f"P4-A reference data root is missing: {root}")
    return root


def _acceptable_translation(value: str, canonical: str) -> bool:
    return (
        bool(value.strip())
        and value.strip() != canonical.strip()
        and HAN_RE.search(value) is not None
        and UNTRANSLATED_RE.search(value) is None
        and ASCII_WORD_RE.search(value) is None
    )


def _translate_label(
    canonical: str,
    *,
    key: str,
    reference_names: dict[str, str],
    token_overrides: dict[str, str],
) -> tuple[str | None, str]:
    referenced = reference_names.get(reviewed._normalize_name(canonical))
    if referenced is not None and _acceptable_translation(referenced, canonical):
        return referenced, "reference"

    exact = P4A_EXACT_NAMES.get(canonical)
    if exact is not None:
        return exact, "project_exact"

    cost_match = COST_SUFFIX_RE.match(canonical)
    if cost_match:
        root, root_source = _translate_label(
            cost_match.group("base"),
            key=key,
            reference_names=reference_names,
            token_overrides=token_overrides,
        )
        if root is not None:
            return f"{root}（消耗{cost_match.group('count')}次動作）", f"structured:{root_source}"

    only_match = FORM_ONLY_RE.match(canonical)
    if only_match:
        root, root_source = _translate_label(
            only_match.group("base"),
            key=key,
            reference_names=reference_names,
            token_overrides=token_overrides,
        )
        if root is not None:
            form = FORM_ONLY_NAMES[only_match.group("form")]
            return f"{root}（僅{form}形態）", f"structured:{root_source}"

    beast_match = BEAST_BITE_RE.match(canonical)
    if beast_match:
        root, root_source = _translate_label(
            beast_match.group("base"),
            key=key,
            reference_names=reference_names,
            token_overrides=token_overrides,
        )
        if root is not None:
            return f"{root}（野獸形態時改為啃咬）", f"structured:{root_source}"

    creature_form = CREATURE_FORM_RE.match(canonical)
    if creature_form:
        creature = CREATURE_FORM_NAMES[creature_form.group("creature")]
        form = FORM_NAMES[creature_form.group("form")]
        return f"{creature}（{form}形態）", "structured:creature_form"

    exact = base.EXACT.get(canonical)
    if exact is not None and _acceptable_translation(exact, canonical):
        return exact, "project_existing_exact"

    unknowns: list[base.Unknown] = []
    drafted = base.translate_name(canonical, key=key, unknowns=unknowns)
    drafted = reviewed._replace_markers(drafted, token_overrides)
    if isinstance(drafted, str) and _acceptable_translation(drafted, canonical):
        return drafted, "project_composition"
    return None, "unresolved"


def _monster_rows() -> list[dict[str, Any]]:
    payload = _load_json(MONSTERS_PATH)
    if not isinstance(payload, list):
        raise ValueError("data/srd5.1/monsters.json must be a JSON array")
    rows = [row for row in payload if isinstance(row, dict)]
    if len(rows) != len(payload):
        raise ValueError("data/srd5.1/monsters.json contains a non-object entry")
    return rows


def augment_overlay(
    overlay: dict[str, Any],
    *,
    reference_names: dict[str, str],
    token_overrides: dict[str, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if overlay.get("schema_version") != 1 or overlay.get("locale") != "zh-TW":
        raise ValueError("P4-A Monster locale shard must be schema_version 1 / locale zh-TW")
    entries = overlay.get("entries")
    if not isinstance(entries, dict):
        raise ValueError("zh-TW locale overlay entries must be an object")

    source_counts: dict[str, int] = {}
    missing: list[dict[str, str]] = []
    monster_count = 0
    required_field_count = 0

    for row in _monster_rows():
        key = row.get("key")
        name = row.get("name")
        data = row.get("data")
        if not isinstance(key, str) or not isinstance(name, str) or not isinstance(data, dict):
            raise ValueError("Monster entry is missing key/name/data")
        monster_count += 1
        localized = entries.setdefault(key, {})
        if not isinstance(localized, dict):
            raise ValueError(f"locale overlay entry must be an object: {key}")

        required: list[tuple[str, str]] = [("name", name)]
        for collection in AFFORDANCE_COLLECTIONS:
            raw_values = data.get(collection, [])
            if raw_values is None:
                continue
            if not isinstance(raw_values, list):
                raise ValueError(f"{key}: data.{collection} must be a list")
            for index, affordance in enumerate(raw_values):
                if not isinstance(affordance, dict):
                    continue
                affordance_name = affordance.get("name")
                if isinstance(affordance_name, str) and affordance_name.strip():
                    required.append((f"data.{collection}.{index}.name", affordance_name))

        for field_path, canonical in required:
            required_field_count += 1
            existing = localized.get(field_path)
            if isinstance(existing, str) and _acceptable_translation(existing, canonical):
                source_counts["existing"] = source_counts.get("existing", 0) + 1
                continue
            translated, source = _translate_label(
                canonical,
                key=f"{key}#{field_path}",
                reference_names=reference_names,
                token_overrides=token_overrides,
            )
            if translated is None:
                localized.pop(field_path, None)
                missing.append(
                    {"key": key, "field_path": field_path, "canonical": canonical}
                )
                continue
            localized[field_path] = translated
            source_counts[source] = source_counts.get(source, 0) + 1

    report = {
        "schema_version": 1,
        "phase": "P4-A",
        "pack": "srd5.1",
        "locale": "zh-TW",
        "reference_repository": authoring.AUTHORING_REFERENCE_REPOSITORY,
        "reference_commit": REFERENCE_COMMIT,
        "reference_name_count": len(reference_names),
        "monster_count": monster_count,
        "required_label_count": required_field_count,
        "translated_label_count": required_field_count - len(missing),
        "translation_sources": dict(sorted(source_counts.items())),
        "missing_count": len(missing),
        "missing": missing,
        "long_form_descriptions": "deferred-until-first-user-visible-exposure",
    }
    return overlay, report


def write_overlay(
    reference_checkout: Path,
    overlay_path: Path,
    report_path: Path,
    *,
    strict: bool,
) -> int:
    overlay = _load_json(overlay_path) if overlay_path.is_file() else _empty_overlay()
    if not isinstance(overlay, dict):
        raise ValueError(f"locale overlay must be an object: {overlay_path}")
    reference_names = load_deep_reference_names(_reference_root(reference_checkout))
    token_overrides = authoring.load_token_overrides()
    overlay, report = augment_overlay(
        overlay,
        reference_names=reference_names,
        token_overrides=token_overrides,
    )

    overlay_path.parent.mkdir(parents=True, exist_ok=True)
    overlay_path.write_text(
        json.dumps(overlay, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(
        "P4-A Monster zh-TW labels: "
        f"{report['monster_count']} monsters / "
        f"{report['translated_label_count']}/{report['required_label_count']} labels / "
        f"{report['missing_count']} missing"
    )
    for item in report["missing"]:
        print(
            "MISSING "
            f"{item['key']} {item['field_path']}: {item['canonical']}"
        )
    return 2 if strict and report["missing_count"] else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build explicit P4-A SRD Monster zh-TW label coverage.",
    )
    parser.add_argument("--reference-checkout", type=Path, required=True)
    parser.add_argument("--overlay", type=Path, default=DEFAULT_OVERLAY)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    try:
        return write_overlay(
            args.reference_checkout,
            args.overlay,
            args.report,
            strict=args.strict,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
