from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
import json
from pathlib import Path
import re
import unicodedata
from typing import Any, Iterable

from pydantic import ValidationError

from app.content.identity import parse_stable_key, stable_key
from app.content.registry import (
    CONTENT_PACKS_ROOT,
    REPOSITORY_ROOT,
    ContentNotFoundError,
    ContentRegistry,
    ContentValidationError,
)
from app.content.schemas import ContentEntry, DATA_MODELS


CONFIG_PATH = CONTENT_PACKS_ROOT / "rules" / "dnd5e-2014" / "m01j-subclasses.json"
SOURCE_IDS = {"PHB": "phb2014", "SCAG": "scag", "XGE": "xge", "TCE": "tce"}
EXPECTED_SOURCES = ("phb2014", "scag", "xge", "tce")

CLASS_FLAVORS = {
    "artificer": "Artificer Specialist",
    "barbarian": "Primal Path",
    "bard": "Bard College",
    "cleric": "Divine Domain",
    "druid": "Druid Circle",
    "fighter": "Martial Archetype",
    "monk": "Monastic Tradition",
    "paladin": "Sacred Oath",
    "ranger": "Ranger Archetype",
    "rogue": "Roguish Archetype",
    "sorcerer": "Sorcerous Origin",
    "warlock": "Otherworldly Patron",
    "wizard": "Arcane Tradition",
}

# The reference documents are Chinese-first and occasionally use a translated
# spell title that differs from the reviewed locale overlay. These aliases only
# bridge names to existing canonical spell identities; they do not supply rules.
SPELL_INDEX_ALIASES = {
    "塔莎狂笑": "hideous-laughter",
    "塔莎狂笑術": "hideous-laughter",
    "艾伐黑觸手": "black-tentacles",
    "艾伐黑觸手術": "black-tentacles",
    "次元門": "dimension-door",
    "次元門術": "dimension-door",
    "虔誠守衛": "guardian-of-faith",
    "虔誠守衛術": "guardian-of-faith",
    "噪音暗語": "dissonant-whispers",
    "噪音暗語術": "dissonant-whispers",
    "心靈遙控": "telekinesis",
    "心靈遙控術": "telekinesis",
}

_CHINESE_NUMBERS = {
    "一": 1,
    "二": 2,
    "兩": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}

_OVERVIEW_ROW_RE = re.compile(
    r"^\|\s*\*\*(?P<zh>.+?)\*\*\s*\|\s*(?P<en>.+?)\s*\|\s*"
    r"(?P<source>PHB|SCAG|XGE|TCE)\s*\|\s*(?P<levels>[^|]+?)\s*\|"
)
_SECTION_RE = re.compile(
    r"^##\s+\d+\.\s+(?P<zh>.*?)\s+\((?P<en>.+)\)\s+—\s+《(?P<source>PHB|SCAG|XGE|TCE)》\s*$"
)
_LEVEL_RE = re.compile(r"^###\s+(?P<level>\d+)\s*級[:：]\s*(?P<title>.*)$")
_FEATURE_RE = re.compile(r"^####\s+(?P<title>.+?)\s*$")
_OPTION_RE = re.compile(r"^#####\s+(?P<title>.+?)\s*$")
_SOURCE_URL_RE = re.compile(r"資料來源網址[^：:]*[：:]\s*(https?://\S+)")


@dataclass(frozen=True)
class InventoryRow:
    source: str
    parent_class_ref: str
    subclass_key: str
    name: str
    zh_name: str
    acquisition_class_level: int
    progression_levels: tuple[int, ...]
    disposition: str
    canonical_key: str | None
    reference_doc: str


@dataclass(frozen=True)
class ParsedSubclass:
    inventory: InventoryRow
    source_url: str
    section_lines: tuple[str, ...]


class M01JReferenceRegistry:
    """Read-only registry overlay for docs-derived M01-J rule content.

    The physical pack manifests remain the installed-file contract. M01-J's
    temporary verified rule references live under docs/暫用規則資訊, so this
    overlay adds their runtime entries without pretending those generated rows
    were vendored pack files. StableKeys still use the owning PHB/SCAG/XGE/TCE
    source identity, and all ordinary registry callers see one combined view.
    """

    def __init__(
        self,
        base: ContentRegistry,
        *,
        supplemental: dict[str, ContentEntry],
        overrides: dict[str, ContentEntry],
        inventory_rows: tuple[InventoryRow, ...],
        localization_overlays: dict[tuple[str, str], dict[str, dict[str, Any]]],
    ) -> None:
        self.base = base
        self.supplemental = supplemental
        self.overrides = overrides
        self.m01j_inventory_rows = inventory_rows
        self.m01j_localization_overlays = localization_overlays
        self.enabled_pack_ids = base.enabled_pack_ids

    @property
    def manifest(self):
        return self.base.manifest

    @property
    def pack_count(self) -> int:
        return self.base.pack_count

    def get_source_manifest(self, source: str):
        return self.base.get_source_manifest(source)

    def source_label(self, source: str) -> str:
        return self.base.source_label(source)

    def get(self, key: str) -> ContentEntry:
        entry = self.get_optional(key)
        if entry is None:
            raise ContentNotFoundError(key)
        return entry

    def get_optional(self, key: str) -> ContentEntry | None:
        return self.overrides.get(key) or self.supplemental.get(key) or self.base.get_optional(key)

    def resolve(self, *parts: str) -> ContentEntry:
        if len(parts) == 2:
            source = "srd5.1"
            kind, index = parts
        elif len(parts) == 3:
            source, kind, index = parts
        else:
            raise TypeError("resolve expects (kind, index) or (source, kind, index)")
        return self.get(stable_key(source, kind, index))

    def list_kind(self, kind: str, *, source: str | None = None) -> tuple[ContentEntry, ...]:
        result: dict[str, ContentEntry] = {
            entry.key: self.overrides.get(entry.key, entry)
            for entry in self.base.list_kind(kind, source=source)
        }
        for entry in self.supplemental.values():
            parsed = parse_stable_key(entry.key)
            if parsed.kind != kind or (source is not None and entry.source != source):
                continue
            result[entry.key] = entry
        return tuple(result[key] for key in sorted(result))

    def __len__(self) -> int:
        return len(self.base) + len(self.supplemental)

    def __getattr__(self, name: str):
        return getattr(self.base, name)


def _load_config() -> dict[str, Any]:
    try:
        payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContentValidationError(f"cannot load M01-J subclass config: {exc}") from exc
    if not isinstance(payload, dict):
        raise ContentValidationError("M01-J subclass config must be an object")
    if payload.get("phase") != "M01-J" or payload.get("ruleset") != "dnd5e-2014":
        raise ContentValidationError("M01-J subclass config phase/ruleset mismatch")
    return payload


def _clean_text(value: str) -> str:
    return value.replace("\u200b", "").replace("\ufeff", "").strip()


def _slug(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    ascii_value = value.encode("ascii", "ignore").decode("ascii").lower()
    ascii_value = re.sub(r"[^a-z0-9]+", "-", ascii_value).strip("-")
    if ascii_value:
        return ascii_value
    # ContentEntry indices are ASCII-only. A deterministic unicode-codepoint
    # fallback keeps even Chinese-only option headings stable without hashing.
    codepoints = "-".join(f"u{ord(char):x}" for char in value if not char.isspace())
    return codepoints[:220] or "unnamed"


def _subclass_index(name: str) -> str:
    value = re.sub(r"\s*\([^)]*\)\s*$", "", _clean_text(name))
    prefixes = (
        "Path of the ",
        "Path of ",
        "College of ",
        "Circle of the ",
        "Circle of ",
        "Way of the ",
        "Way of ",
        "Oath of the ",
        "Oath of ",
        "School of ",
        "Order of ",
        "The ",
    )
    for prefix in prefixes:
        if value.lower().startswith(prefix.lower()):
            value = value[len(prefix) :]
            break
    if value.lower().endswith(" domain"):
        value = value[: -len(" domain")]
    if value.lower() == "draconic bloodline":
        value = "Draconic"
    return _slug(value)


def _parent_class_ref(class_index: str) -> str:
    source = "tce" if class_index == "artificer" else "srd5.1"
    return stable_key(source, "class", class_index)


def _parse_levels(value: str) -> tuple[int, ...]:
    levels = tuple(int(raw) for raw in re.findall(r"\d+", value))
    if not levels or any(not 1 <= level <= 20 for level in levels):
        raise ContentValidationError(f"invalid subclass progression levels: {value}")
    return levels


def _parse_reference_docs(config: dict[str, Any]) -> tuple[ParsedSubclass, ...]:
    raw_docs = config.get("reference_docs")
    if not isinstance(raw_docs, dict) or set(raw_docs) != set(CLASS_FLAVORS):
        raise ContentValidationError("M01-J reference_docs must cover all 13 supported classes")

    canonical_duplicates = config.get("canonical_duplicates")
    reprints = config.get("reprints")
    if not isinstance(canonical_duplicates, dict) or not isinstance(reprints, dict):
        raise ContentValidationError("M01-J canonical duplicate/reprint maps are required")

    parsed: list[ParsedSubclass] = []
    canonical_keys: set[str] = set()
    docs_by_class: dict[str, str] = {}

    for class_index, relative_path in raw_docs.items():
        if not isinstance(relative_path, str):
            raise ContentValidationError(f"invalid M01-J reference doc path for {class_index}")
        path = REPOSITORY_ROOT / relative_path
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ContentValidationError(f"cannot read M01-J reference doc {relative_path}: {exc}") from exc
        docs_by_class[class_index] = relative_path
        lines = tuple(text.splitlines())
        source_url_match = _SOURCE_URL_RE.search(text)
        source_url = source_url_match.group(1) if source_url_match else ""

        section_starts: list[tuple[int, str, str]] = []
        for position, line in enumerate(lines):
            match = _SECTION_RE.match(_clean_text(line))
            if match:
                source = SOURCE_IDS[match.group("source")]
                index = _subclass_index(match.group("en"))
                section_starts.append((position, source, index))
        sections: dict[tuple[str, str], tuple[str, ...]] = {}
        for offset, (start, source, index) in enumerate(section_starts):
            end = section_starts[offset + 1][0] if offset + 1 < len(section_starts) else len(lines)
            identity = (source, index)
            if identity in sections:
                raise ContentValidationError(
                    f"duplicate subclass section {source}/{class_index}/{index} in {relative_path}"
                )
            sections[identity] = lines[start:end]

        for line in lines:
            match = _OVERVIEW_ROW_RE.match(_clean_text(line))
            if not match:
                continue
            source = SOURCE_IDS[match.group("source")]
            name_en = _clean_text(match.group("en"))
            name_zh = _clean_text(match.group("zh"))
            index = _subclass_index(name_en)
            subclass_key = stable_key(source, "subclass", index)
            if subclass_key in canonical_keys:
                raise ContentValidationError(f"duplicate M01-J canonical subclass identity: {subclass_key}")
            canonical_keys.add(subclass_key)
            progression_levels = _parse_levels(match.group("levels"))
            canonical_key = canonical_duplicates.get(subclass_key)
            if canonical_key is not None and not isinstance(canonical_key, str):
                raise ContentValidationError(f"invalid canonical target for {subclass_key}")
            disposition = "canonical_duplicate" if canonical_key else "implemented"
            section = sections.get((source, index))
            if section is None:
                raise ContentValidationError(
                    f"M01-J overview row has no rules section: {subclass_key} in {relative_path}"
                )
            row = InventoryRow(
                source=source,
                parent_class_ref=_parent_class_ref(class_index),
                subclass_key=subclass_key,
                name=name_en,
                zh_name=name_zh,
                acquisition_class_level=progression_levels[0],
                progression_levels=progression_levels,
                disposition=disposition,
                canonical_key=canonical_key,
                reference_doc=relative_path,
            )
            parsed.append(ParsedSubclass(row, source_url, section))

    # SCAG printed five subclasses which the reference set intentionally files
    # under their later XGE/TCE canonical rules. Preserve those source-book
    # occurrences in J1 accounting without creating duplicate Builder options.
    canonical_by_index: dict[str, ParsedSubclass] = {
        item.inventory.subclass_key: item for item in parsed
    }
    for source_key, canonical_key in reprints.items():
        if not isinstance(source_key, str) or not isinstance(canonical_key, str):
            raise ContentValidationError("M01-J reprint map must contain StableKey strings")
        parsed_source = parse_stable_key(source_key, kinds={"subclass"})
        canonical = canonical_by_index.get(canonical_key)
        if canonical is None:
            raise ContentValidationError(f"M01-J reprint target missing from reference docs: {canonical_key}")
        if parsed_source.source != "scag":
            raise ContentValidationError(f"M01-J unexpected non-SCAG reprint source: {source_key}")
        class_index = parse_stable_key(canonical.inventory.parent_class_ref, kinds={"class"}).index
        parsed.append(
            ParsedSubclass(
                InventoryRow(
                    source="scag",
                    parent_class_ref=canonical.inventory.parent_class_ref,
                    subclass_key=source_key,
                    name=canonical.inventory.name,
                    zh_name=canonical.inventory.zh_name,
                    acquisition_class_level=canonical.inventory.acquisition_class_level,
                    progression_levels=canonical.inventory.progression_levels,
                    disposition="canonical_duplicate",
                    canonical_key=canonical_key,
                    reference_doc=docs_by_class[class_index],
                ),
                canonical.source_url,
                (),
            )
        )

    expected_counts = config.get("expected_counts")
    actual = Counter(item.inventory.source for item in parsed)
    maintained = {source: actual[source] for source in EXPECTED_SOURCES}
    if maintained != expected_counts:
        raise ContentValidationError(
            f"M01-J reference inventory count mismatch: expected={expected_counts}, actual={maintained}"
        )
    return tuple(parsed)


def _split_heading(title: str) -> tuple[str, str | None]:
    title = _clean_text(title)
    match = re.match(r"^(.*?)\s+\((.*)\)\s*$", title)
    if match:
        return _clean_text(match.group(1)), _clean_text(match.group(2))
    return title, None


def _number_value(value: str) -> int | None:
    if value.isdigit():
        return int(value)
    return _CHINESE_NUMBERS.get(value)


def _infer_choose_count(text: str) -> int:
    compact = text.replace(" ", "")
    patterns = (
        r"(?:學會|知曉|选择|選擇|獲得)[^。\n]{0,24}?([一二兩两三四五六七八九十\d]+)(?:個|种|種)",
        r"([一二兩两三四五六七八九十\d]+)(?:個|种|種)[^。\n]{0,16}?(?:自選|你所選擇|你选择)",
    )
    for pattern in patterns:
        match = re.search(pattern, compact)
        if match:
            value = _number_value(match.group(1))
            if value is not None and value > 0:
                return value
    return 1


def _infer_choice_progression(text: str, *, base_level: int, base_count: int) -> tuple[dict[str, int], ...]:
    progression: dict[int, int] = {base_level: base_count}
    sentences = re.split(r"[。\n]", text)
    running = base_count
    for sentence in sentences:
        if "級" not in sentence or not any(token in sentence for token in ("學會", "獲得", "选择", "選擇")):
            continue
        levels = [int(value) for value in re.findall(r"(\d+)\s*級", sentence)]
        levels = [level for level in levels if level > base_level]
        if not levels:
            continue
        count_match = re.search(
            r"(?:學會|獲得|选择|選擇)[^。]{0,18}?([一二兩两三四五六七八九十\d]+)(?:個|种|種)",
            sentence,
        )
        if count_match is None:
            count_match = re.search(r"([一二兩两三四五六七八九十\d]+)(?:個|种|種)額外", sentence)
        if count_match is None:
            continue
        extra = _number_value(count_match.group(1))
        if extra is None or extra <= 0:
            continue
        for level in sorted(set(levels)):
            running += extra
            progression[level] = running
    return tuple(
        {"class_level": level, "choose_total": count}
        for level, count in sorted(progression.items())
    )


def _infer_resource(text: str, class_ref: str) -> dict[str, Any] | None:
    compact = text.replace(" ", "")
    limited = any(token in compact for token in ("次數", "再次使用", "不能再使用", "恢復所有你花費", "恢复所有你花费"))
    if not limited:
        return None

    recharge: list[str] = []
    if any(token in compact for token in ("短休或長休", "短休或长休", "短休或一次長休", "短休或一次长休")):
        recharge = ["short_rest", "long_rest"]
    elif "長休" in compact or "长休" in compact:
        recharge = ["long_rest"]
    elif "短休" in compact:
        recharge = ["short_rest"]
    if not recharge:
        return None

    if "熟練加值" in compact or "熟练加值" in compact:
        capacity: dict[str, Any] = {"type": "proficiency_bonus"}
    else:
        abilities = {
            "力量": "strength",
            "敏捷": "dexterity",
            "體質": "constitution",
            "体质": "constitution",
            "智力": "intelligence",
            "感知": "wisdom",
            "魅力": "charisma",
        }
        ability = next(
            (value for label, value in abilities.items() if f"{label}調整值" in compact or f"{label}调整值" in compact),
            None,
        )
        if ability is not None and "次數" in compact:
            capacity = {
                "type": "ability_modifier",
                "ability": ability,
                "minimum": 1 if "最少一次" in compact else 0,
            }
        else:
            fixed = None
            for raw, value in (("一次", 1), ("二次", 2), ("兩次", 2), ("三次", 3), ("四次", 4), ("五次", 5)):
                if raw in compact:
                    fixed = value
                    break
            if fixed is None and any(token in compact for token in ("一旦你使用", "不能再使用", "再次使用")):
                fixed = 1
            if fixed is None:
                return None
            capacity = {"type": "fixed", "value": fixed}
    return {"capacity": capacity, "recharge": recharge}


def _normalize_spell_name(value: str) -> str:
    value = _clean_text(value)
    value = re.sub(r"[《》〈〉「」『』\s·・,，、/／:：'’\-]", "", value)
    value = value.replace("法術", "").replace("法术", "")
    if value.endswith("術"):
        value = value[:-1]
    return value.lower()


class _SpellResolver:
    def __init__(self, registry: ContentRegistry) -> None:
        self.registry = registry
        self.by_index: dict[str, str] = {}
        self.by_name: dict[str, set[str]] = defaultdict(set)
        for spell in registry.list_kind("spell"):
            self.by_index.setdefault(spell.index, spell.key)
            self.by_name[_normalize_spell_name(spell.name)].add(spell.key)

        for source in registry.enabled_pack_ids:
            locale_root = CONTENT_PACKS_ROOT / source / "locales"
            paths: list[Path] = []
            shard_root = locale_root / "zh-TW"
            if shard_root.is_dir():
                paths.extend(sorted(shard_root.glob("*.json")))
            monolith = locale_root / "zh-TW.json"
            if monolith.is_file():
                paths.append(monolith)
            for path in paths:
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                entries = payload.get("entries") if isinstance(payload, dict) else None
                if not isinstance(entries, dict):
                    continue
                for key, fields in entries.items():
                    if registry.get_optional(key) is None or not isinstance(fields, dict):
                        continue
                    name = fields.get("name")
                    if isinstance(name, str):
                        self.by_name[_normalize_spell_name(name)].add(key)

    def resolve(self, name: str) -> str | None:
        normalized = _normalize_spell_name(name)
        candidates = self.by_name.get(normalized, set())
        if len(candidates) == 1:
            return next(iter(candidates))

        alias_index = SPELL_INDEX_ALIASES.get(_clean_text(name)) or SPELL_INDEX_ALIASES.get(normalized)
        if alias_index is not None:
            target = self.by_index.get(alias_index)
            if target is not None:
                return target

        containment: set[str] = set()
        if len(normalized) >= 3:
            for localized, keys in self.by_name.items():
                if normalized in localized or localized in normalized:
                    containment.update(keys)
        if len(containment) == 1:
            return next(iter(containment))

        scored: list[tuple[float, str]] = []
        for localized, keys in self.by_name.items():
            if len(keys) != 1:
                continue
            score = SequenceMatcher(None, normalized, localized).ratio()
            if score >= 0.78:
                scored.append((score, next(iter(keys))))
        scored.sort(reverse=True)
        if scored and (len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.08):
            return scored[0][1]
        return None


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _spell_names_from_cell(value: str) -> tuple[str, ...]:
    bracketed = tuple(_clean_text(name) for name in re.findall(r"《([^》]+)》", value))
    if bracketed:
        return bracketed
    return tuple(
        _clean_text(part)
        for part in re.split(r"[,，、]", value)
        if _clean_text(part) and _clean_text(part) not in {"—", "-"}
    )


def _spell_access_mode(class_index: str, text: str) -> str:
    compact = text.replace(" ", "")
    if any(token in compact for token in ("加入契術師法術列表", "加入邪術師法術列表", "擴充套件法術列表", "扩充套件法术列表")):
        return "expanded"
    if any(token in compact for token in ("總是被視為已準備", "永遠視作已經準備", "加入你的準備法術", "视为已准备", "總是準備")):
        return "always_prepared"
    if class_index == "warlock":
        return "expanded"
    if class_index in {"cleric", "druid", "paladin", "artificer"}:
        return "always_prepared"
    if class_index in {"ranger", "sorcerer"}:
        return "granted"
    return "granted"


def _parse_spell_tables(
    lines: tuple[str, ...],
    *,
    acquisition_level: int,
    class_index: str,
    resolver: _SpellResolver,
) -> tuple[dict[str, Any], ...]:
    tables: list[dict[str, Any]] = []
    position = 0
    while position + 2 < len(lines):
        if not lines[position].lstrip().startswith("|") or not lines[position + 1].lstrip().startswith("|"):
            position += 1
            continue
        headers = _table_cells(lines[position])
        separator = _table_cells(lines[position + 1])
        if len(headers) < 2 or len(separator) != len(headers) or not all("-" in cell for cell in separator):
            position += 1
            continue
        if not any("法術" in header or "法术" in header or "Spell" in header for header in headers):
            position += 1
            continue

        title = ""
        context_option = ""
        for backwards in range(position - 1, max(-1, position - 8), -1):
            candidate = _clean_text(lines[backwards])
            if not candidate:
                continue
            option_match = _OPTION_RE.match(candidate)
            if option_match and not context_option:
                context_option = option_match.group("title")
            bold_match = re.match(r"^\*\*(.+?)\*\*$", candidate)
            if bold_match:
                title = _clean_text(bold_match.group(1))
                break
            if candidate.startswith("####") or candidate.startswith("###"):
                break

        spell_level_table = any("環階" in header or "环阶" in header or "Spell Level" in header for header in headers[:1])
        rows: list[dict[str, Any]] = []
        cursor = position + 2
        while cursor < len(lines) and lines[cursor].lstrip().startswith("|"):
            cells = _table_cells(lines[cursor])
            if len(cells) >= 2:
                raw_level = cells[0]
                raw_spells = cells[1]
                level_match = re.search(r"\d+", raw_level)
                required_level = acquisition_level
                if not spell_level_table and level_match:
                    required_level = int(level_match.group(0))
                spell_names = _spell_names_from_cell(raw_spells)
                resolved: list[str] = []
                gaps: list[str] = []
                for spell_name in spell_names:
                    spell_ref = resolver.resolve(spell_name)
                    if spell_ref is None:
                        gaps.append(spell_name)
                    else:
                        resolved.append(spell_ref)
                if spell_names:
                    rows.append(
                        {
                            "minimum_class_level": required_level,
                            "spell_refs": tuple(resolved),
                            "unresolved_spell_names": tuple(gaps),
                        }
                    )
            cursor += 1

        if rows:
            tables.append(
                {
                    "title": title,
                    "context_option": context_option,
                    "rows": tuple(rows),
                    "mode": _spell_access_mode(class_index, "\n".join(lines)),
                }
            )
        position = max(cursor, position + 1)
    return tuple(tables)


def _option_headings(lines: tuple[str, ...]) -> tuple[tuple[int, str], ...]:
    return tuple(
        (position, match.group("title"))
        for position, line in enumerate(lines)
        if (match := _OPTION_RE.match(_clean_text(line))) is not None
    )


def _choice_is_supported(feature_name: str, text: str, option_count: int) -> bool:
    if option_count < 2:
        return False
    compact = text.replace(" ", "")
    hints = ("選擇", "选择", "自選", "你所選擇", "其中一個", "其中一种", "學會", "知曉")
    if any(hint in compact for hint in hints):
        return True
    english = feature_name.lower()
    return any(token in english for token in ("maneuver", "discipline", "arcane shot", "rune", "totem"))


def _make_entry(
    registry: ContentRegistry,
    *,
    source: str,
    kind: str,
    index: str,
    name: str,
    data: dict[str, Any],
    provenance: dict[str, Any],
) -> ContentEntry:
    key = stable_key(source, kind, index)
    raw = {
        "key": key,
        "index": index,
        "name": name,
        "source": source,
        "ruleset": "dnd5e-2014",
        "provenance": provenance,
        "source_label": registry.source_label(source),
        "data": data,
    }
    try:
        entry = ContentEntry.model_validate(raw)
        typed = DATA_MODELS[kind].model_validate(entry.data)
    except (ValidationError, ValueError) as exc:
        raise ContentValidationError(f"M01-J generated {key} failed schema validation: {exc}") from exc
    if typed.index != index:
        raise ContentValidationError(f"M01-J generated envelope/data index mismatch: {key}")
    return entry


def _feature_blocks(section_lines: tuple[str, ...]) -> tuple[tuple[int, str, tuple[str, ...]], ...]:
    result: list[tuple[int, str, tuple[str, ...]]] = []
    current_level: int | None = None
    position = 1
    while position < len(section_lines):
        line = _clean_text(section_lines[position])
        level_match = _LEVEL_RE.match(line)
        if level_match:
            current_level = int(level_match.group("level"))
            position += 1
            continue
        feature_match = _FEATURE_RE.match(line)
        if feature_match and current_level is not None:
            start = position
            cursor = position + 1
            while cursor < len(section_lines):
                candidate = _clean_text(section_lines[cursor])
                if _FEATURE_RE.match(candidate) or _LEVEL_RE.match(candidate) or _SECTION_RE.match(candidate):
                    break
                cursor += 1
            result.append((current_level, feature_match.group("title"), section_lines[start:cursor]))
            position = cursor
            continue
        position += 1
    return tuple(result)


def _generate_for_subclass(
    registry: ContentRegistry,
    parsed: ParsedSubclass,
    resolver: _SpellResolver,
) -> tuple[
    dict[str, ContentEntry],
    ContentEntry,
    dict[str, dict[str, Any]],
]:
    row = parsed.inventory
    class_index = parse_stable_key(row.parent_class_ref, kinds={"class"}).index
    subclass_index = parse_stable_key(row.subclass_key, kinds={"subclass"}).index
    provenance = {
        "type": "repository-reference",
        "reference_doc": row.reference_doc,
        "reference_url": parsed.source_url,
        "phase": "M01-J",
    }

    supplemental: dict[str, ContentEntry] = {}
    zh_localization: dict[str, dict[str, Any]] = {}
    top_feature_refs: list[str] = []
    persistent_choices: list[dict[str, Any]] = []
    subclass_spells: list[dict[str, Any]] = []
    expanded_spells: list[dict[str, Any]] = []
    resource_feature_refs: list[str] = []
    level_feature_refs: dict[int, list[str]] = defaultdict(list)
    used_feature_indices: Counter[str] = Counter()

    for level, raw_title, block_lines in _feature_blocks(parsed.section_lines):
        title_zh, title_en = _split_heading(raw_title)
        block_text = "\n".join(block_lines[1:]).strip()
        # Pure table/list subheadings without an English rule name are retained
        # as subclass spell metadata, but do not become noisy feature grants.
        feature_marker = re.search(rf"\*{level}\s*級[^*]*(?:特性|feature)[^*]*\*", block_text, re.IGNORECASE)
        option_headings = _option_headings(block_lines)
        spell_tables = _parse_spell_tables(
            block_lines,
            acquisition_level=row.acquisition_class_level,
            class_index=class_index,
            resolver=resolver,
        )
        if title_en is None and feature_marker is None and not option_headings and not spell_tables:
            continue
        canonical_name = title_en or title_zh
        feature_slug = _slug(canonical_name)
        base_index = f"{subclass_index}-{level}-{feature_slug}"
        used_feature_indices[base_index] += 1
        feature_index = (
            base_index
            if used_feature_indices[base_index] == 1
            else f"{base_index}-{used_feature_indices[base_index]}"
        )
        feature_ref = stable_key(row.source, "feature", feature_index)

        option_refs_by_heading: dict[str, str] = {}
        generated_option_refs: list[str] = []
        if _choice_is_supported(canonical_name, block_text, len(option_headings)):
            for ordinal, (option_position, option_title) in enumerate(option_headings, start=1):
                option_zh, option_en = _split_heading(option_title)
                option_name = option_en or option_zh
                option_index = f"{feature_index}-option-{ordinal}-{_slug(option_name)}"
                option_ref = stable_key(row.source, "feature", option_index)
                next_position = (
                    option_headings[ordinal][0]
                    if ordinal < len(option_headings)
                    else len(block_lines)
                )
                option_text = "\n".join(block_lines[option_position + 1 : next_position]).strip()
                option_data = {
                    "index": option_index,
                    "name": option_name,
                    "level": level,
                    "class": {"key": row.parent_class_ref, "name": registry.get(row.parent_class_ref).name},
                    "subclass": {"key": row.subclass_key, "name": row.name},
                    "choice_option_for": feature_ref,
                    "reference_heading_zh": option_zh,
                    "reference_text_zh": option_text[:12000],
                }
                option_entry = _make_entry(
                    registry,
                    source=row.source,
                    kind="feature",
                    index=option_index,
                    name=option_name,
                    data=option_data,
                    provenance=provenance,
                )
                supplemental[option_ref] = option_entry
                zh_localization[option_ref] = {"name": option_zh}
                option_refs_by_heading[_clean_text(option_title)] = option_ref
                option_refs_by_heading[_clean_text(option_zh)] = option_ref
                option_refs_by_heading[_clean_text(option_name)] = option_ref
                generated_option_refs.append(option_ref)

        # Spell-table branches such as Circle of the Land use bold table titles
        # rather than H5 headings. Materialize those titles as persistent options.
        multi_table_branch = len(spell_tables) > 1 and not generated_option_refs
        if multi_table_branch:
            for ordinal, table in enumerate(spell_tables, start=1):
                table_title = _clean_text(str(table.get("title") or f"Option {ordinal}"))
                option_index = f"{feature_index}-spell-option-{ordinal}-{_slug(table_title)}"
                option_ref = stable_key(row.source, "feature", option_index)
                option_entry = _make_entry(
                    registry,
                    source=row.source,
                    kind="feature",
                    index=option_index,
                    name=table_title,
                    data={
                        "index": option_index,
                        "name": table_title,
                        "level": level,
                        "class": {"key": row.parent_class_ref, "name": registry.get(row.parent_class_ref).name},
                        "subclass": {"key": row.subclass_key, "name": row.name},
                        "choice_option_for": feature_ref,
                        "reference_heading_zh": table_title,
                    },
                    provenance=provenance,
                )
                supplemental[option_ref] = option_entry
                zh_localization[option_ref] = {"name": table_title}
                option_refs_by_heading[table_title] = option_ref
                generated_option_refs.append(option_ref)

        choice_key: str | None = None
        if generated_option_refs:
            choice_key = f"{feature_index}:0"
            base_choose = _infer_choose_count(block_text)
            persistent_choices.append(
                {
                    "choice_key": choice_key,
                    "feature_ref": feature_ref,
                    "minimum_class_level": level,
                    "choose_total": base_choose,
                    "progression": _infer_choice_progression(
                        block_text,
                        base_level=level,
                        base_count=base_choose,
                    ),
                    "option_refs": tuple(generated_option_refs),
                    "label": canonical_name,
                    "label_zh": title_zh,
                }
            )

        for table in spell_tables:
            mode = str(table["mode"])
            option_ref: str | None = None
            context = _clean_text(str(table.get("context_option") or ""))
            table_title = _clean_text(str(table.get("title") or ""))
            if choice_key is not None:
                option_ref = option_refs_by_heading.get(context) or option_refs_by_heading.get(table_title)
                if option_ref is None and len(generated_option_refs) == 1:
                    option_ref = generated_option_refs[0]
            for spell_row in table["rows"]:
                minimum_level = int(spell_row["minimum_class_level"])
                for spell_ref in spell_row["spell_refs"]:
                    record = {
                        "prerequisites": [
                            {
                                "index": f"{class_index}-{minimum_level}",
                                "type": "level",
                                "name": f"{registry.get(row.parent_class_ref).name} {minimum_level}",
                            }
                        ],
                        "spell": {"key": spell_ref, "name": registry.get(spell_ref).name},
                        "access_type": mode,
                    }
                    if choice_key is not None and option_ref is not None:
                        record["choice_key"] = choice_key
                        record["option_ref"] = option_ref
                    if mode == "expanded":
                        expanded_spells.append(record)
                    else:
                        subclass_spells.append(record)
                for unresolved in spell_row["unresolved_spell_names"]:
                    target = expanded_spells if mode == "expanded" else subclass_spells
                    target.append(
                        {
                            "prerequisites": [
                                {
                                    "index": f"{class_index}-{minimum_level}",
                                    "type": "level",
                                    "name": f"{registry.get(row.parent_class_ref).name} {minimum_level}",
                                }
                            ],
                            "unresolved_spell_name": unresolved,
                            "access_type": mode,
                            **(
                                {"choice_key": choice_key, "option_ref": option_ref}
                                if choice_key is not None and option_ref is not None
                                else {}
                            ),
                        }
                    )

        feature_data: dict[str, Any] = {
            "index": feature_index,
            "name": canonical_name,
            "level": level,
            "class": {"key": row.parent_class_ref, "name": registry.get(row.parent_class_ref).name},
            "subclass": {"key": row.subclass_key, "name": row.name},
            "reference_heading_zh": title_zh,
            "reference_text_zh": block_text[:16000],
            "automation_boundary": "structured_manual",
        }
        resource = _infer_resource(block_text.split("#####", 1)[0], row.parent_class_ref)
        if resource is not None:
            feature_data["resource"] = resource
            resource_feature_refs.append(feature_ref)
        feature_entry = _make_entry(
            registry,
            source=row.source,
            kind="feature",
            index=feature_index,
            name=canonical_name,
            data=feature_data,
            provenance=provenance,
        )
        supplemental[feature_ref] = feature_entry
        zh_localization[feature_ref] = {"name": title_zh}
        top_feature_refs.append(feature_ref)
        level_feature_refs[level].append(feature_ref)

    for level in row.progression_levels:
        level_index = f"{subclass_index}-{level}"
        level_ref = stable_key(row.source, "level", level_index)
        level_entry = _make_entry(
            registry,
            source=row.source,
            kind="level",
            index=level_index,
            name=f"{row.name} {level}",
            data={
                "index": level_index,
                "name": f"{row.name} {level}",
                "level": level,
                "features": [
                    {"key": feature_ref, "name": supplemental[feature_ref].name}
                    for feature_ref in level_feature_refs.get(level, [])
                ],
                "class": {"key": row.parent_class_ref, "name": registry.get(row.parent_class_ref).name},
                "subclass": {"key": row.subclass_key, "name": row.name},
            },
            provenance=provenance,
        )
        supplemental[level_ref] = level_entry

    subclass_data: dict[str, Any] = {
        "index": subclass_index,
        "name": row.name,
        "class": {"key": row.parent_class_ref, "name": registry.get(row.parent_class_ref).name},
        "subclass_flavor": CLASS_FLAVORS[class_index],
        "acquisition_class_level": row.acquisition_class_level,
        "progression_levels": list(row.progression_levels),
        "progression_feature_refs": list(top_feature_refs),
        "persistent_choices": persistent_choices,
        "resource_feature_refs": resource_feature_refs,
        "reference_doc": row.reference_doc,
        "reference_url": parsed.source_url,
    }
    if subclass_spells:
        subclass_data["spells"] = subclass_spells
    if expanded_spells:
        subclass_data["expanded_spells"] = expanded_spells

    subclass_entry = _make_entry(
        registry,
        source=row.source,
        kind="subclass",
        index=subclass_index,
        name=row.name,
        data=subclass_data,
        provenance=provenance,
    )
    zh_localization[row.subclass_key] = {"name": row.zh_name}
    return supplemental, subclass_entry, zh_localization


def _enhance_existing_subclass(
    registry: ContentRegistry,
    parsed: ParsedSubclass,
) -> ContentEntry:
    row = parsed.inventory
    existing = registry.get(row.subclass_key)
    data = dict(existing.data)
    data.setdefault("acquisition_class_level", row.acquisition_class_level)
    data.setdefault("progression_levels", list(row.progression_levels))
    feature_refs: list[str] = []
    for level in row.progression_levels:
        parsed_key = parse_stable_key(existing.key, kinds={"subclass"})
        level_entry = registry.get_optional(stable_key(parsed_key.source, "level", f"{parsed_key.index}-{level}"))
        if level_entry is None:
            continue
        raw_features = level_entry.data.get("features")
        if not isinstance(raw_features, list):
            continue
        for feature in raw_features:
            if isinstance(feature, dict) and isinstance(feature.get("key"), str):
                feature_refs.append(str(feature["key"]))
    data.setdefault("progression_feature_refs", list(dict.fromkeys(feature_refs)))
    data.setdefault("reference_doc", row.reference_doc)
    data.setdefault("reference_url", parsed.source_url)
    provenance = dict(existing.provenance or {})
    provenance.update(
        {
            "m01j_reference_doc": row.reference_doc,
            "m01j_reference_url": parsed.source_url,
        }
    )
    return existing.model_copy(update={"data": data, "provenance": provenance})


def _validate_generated_references(
    registry: M01JReferenceRegistry,
    inventory_rows: tuple[InventoryRow, ...],
) -> None:
    for row in inventory_rows:
        if registry.get_optional(row.parent_class_ref) is None:
            raise ContentValidationError(
                f"M01-J reference inventory missing parent class: {row.subclass_key} -> {row.parent_class_ref}"
            )
        if row.disposition == "canonical_duplicate":
            if row.canonical_key is None or registry.get_optional(row.canonical_key) is None:
                raise ContentValidationError(
                    f"M01-J canonical target missing: {row.subclass_key} -> {row.canonical_key}"
                )
            continue
        subclass = registry.get_optional(row.subclass_key)
        if subclass is None:
            raise ContentValidationError(f"M01-J generated subclass missing: {row.subclass_key}")
        for field in ("progression_feature_refs", "resource_feature_refs"):
            refs = subclass.data.get(field, [])
            if not isinstance(refs, list):
                raise ContentValidationError(f"{row.subclass_key}: {field} must be a list")
            for ref in refs:
                if not isinstance(ref, str) or registry.get_optional(ref) is None:
                    raise ContentValidationError(f"{row.subclass_key}: missing {field} target {ref}")
        choices = subclass.data.get("persistent_choices", [])
        if not isinstance(choices, list):
            raise ContentValidationError(f"{row.subclass_key}: persistent_choices must be a list")
        for choice in choices:
            if not isinstance(choice, dict):
                raise ContentValidationError(f"{row.subclass_key}: invalid persistent choice")
            for ref in choice.get("option_refs", ()):
                if not isinstance(ref, str) or registry.get_optional(ref) is None:
                    raise ContentValidationError(f"{row.subclass_key}: missing choice option {ref}")


def apply_m01j_reference_content(registry: ContentRegistry) -> M01JReferenceRegistry:
    """Materialize verified PHB/SCAG/XGE/TCE subclass rules from repository docs."""

    config = _load_config()
    parsed_subclasses = _parse_reference_docs(config)
    resolver = _SpellResolver(registry)
    supplemental: dict[str, ContentEntry] = {}
    overrides: dict[str, ContentEntry] = {}
    localization: dict[tuple[str, str], dict[str, dict[str, Any]]] = defaultdict(dict)

    for parsed in parsed_subclasses:
        row = parsed.inventory
        if row.disposition == "canonical_duplicate":
            continue
        existing = registry.get_optional(row.subclass_key)
        if existing is not None:
            overrides[row.subclass_key] = _enhance_existing_subclass(registry, parsed)
            continue
        generated, subclass_entry, zh_entries = _generate_for_subclass(
            registry,
            parsed,
            resolver,
        )
        for key, entry in generated.items():
            if key in supplemental or registry.get_optional(key) is not None:
                raise ContentValidationError(f"M01-J generated duplicate runtime key: {key}")
            supplemental[key] = entry
        supplemental[subclass_entry.key] = subclass_entry
        localization[(row.source, "zh-TW")].update(zh_entries)

    overlay = M01JReferenceRegistry(
        registry,
        supplemental=supplemental,
        overrides=overrides,
        inventory_rows=tuple(item.inventory for item in parsed_subclasses),
        localization_overlays=dict(localization),
    )
    _validate_generated_references(overlay, overlay.m01j_inventory_rows)
    return overlay


def m01j_reference_inventory(registry: object) -> tuple[InventoryRow, ...]:
    rows = getattr(registry, "m01j_inventory_rows", None)
    if isinstance(rows, tuple) and all(isinstance(row, InventoryRow) for row in rows):
        return rows
    return tuple(item.inventory for item in _parse_reference_docs(_load_config()))
