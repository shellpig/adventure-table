from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Collection, Mapping
from urllib.parse import urlparse


PACK_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]*$")
KIND_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
INDEX_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]*$")

URL_ROUTE_TO_KIND = {
    "ability-scores": "ability",
    "alignments": "alignment",
    "backgrounds": "background",
    "classes": "class",
    "conditions": "condition",
    "damage-types": "damage-type",
    "equipment-categories": "equipment-category",
    "equipment": "equipment",
    "feats": "feat",
    "features": "feature",
    "languages": "language",
    "magic-items": "item",
    "magic-schools": "magic-school",
    "proficiencies": "proficiency",
    "races": "race",
    "skills": "skill",
    "spells": "spell",
    "subclasses": "subclass",
    "subraces": "subrace",
    "traits": "trait",
    "weapon-properties": "weapon-property",
}


@dataclass(frozen=True)
class ParsedStableKey:
    source: str
    kind: str
    index: str


def require_pack_id(value: str) -> str:
    if not PACK_ID_PATTERN.fullmatch(value):
        raise ValueError("content pack id must match ^[a-z0-9][a-z0-9.-]*$")
    return value


def parse_stable_key(
    value: str,
    *,
    kinds: Collection[str] | None = None,
) -> ParsedStableKey:
    parts = value.split(":")
    if len(parts) != 3:
        raise ValueError("reference must use stable key format <pack-id>:<kind>:<index>")
    source, kind, index = parts
    require_pack_id(source)
    if not KIND_PATTERN.fullmatch(kind):
        raise ValueError("stable key kind is malformed")
    if not INDEX_PATTERN.fullmatch(index):
        raise ValueError("stable key index is malformed")
    if kinds is not None and kind not in kinds:
        expected = ", ".join(sorted(kinds))
        raise ValueError(f"reference kind must be one of: {expected}")
    return ParsedStableKey(source=source, kind=kind, index=index)


def stable_key(source: str, kind: str, index: str) -> str:
    value = f"{source}:{kind}:{index}"
    parse_stable_key(value)
    return value


def stable_key_is_kind(value: str, *kinds: str) -> bool:
    try:
        parsed = parse_stable_key(value)
    except ValueError:
        return False
    return parsed.kind in set(kinds)


def legacy_srd_key_from_api_url(url: str, index: str) -> str | None:
    path = urlparse(url).path
    parts = [part for part in path.split("/") if part]
    if len(parts) < 2 or parts[0:2] != ["api", "2014"]:
        return None
    if len(parts) != 4:
        raise ValueError(f"malformed legacy SRD reference URL: {url}")
    kind = URL_ROUTE_TO_KIND.get(parts[2])
    if kind is None:
        raise ValueError(f"unknown legacy SRD API route: {url}")
    if parts[3] != index:
        raise ValueError(f"reference URL/index mismatch: url={url}, index={index}")
    return stable_key("srd5.1", kind, index)


def reference_to_stable_key(
    reference: Mapping[str, Any],
    *,
    kinds: Collection[str] | None = None,
) -> str | None:
    explicit_key = reference.get("key")
    if explicit_key is not None:
        if not isinstance(explicit_key, str):
            raise ValueError("explicit content reference key must be a string")
        parsed = parse_stable_key(explicit_key, kinds=kinds)
        index = reference.get("index")
        if index is not None and index != parsed.index:
            raise ValueError(
                f"reference key/index mismatch: key={explicit_key}, index={index}"
            )
        return explicit_key

    index = reference.get("index")
    url = reference.get("url")
    if not isinstance(index, str) or not isinstance(url, str):
        return None
    key = legacy_srd_key_from_api_url(url, index)
    if key is None:
        return None
    parse_stable_key(key, kinds=kinds)
    return key


def collect_stable_key_sources(value: Any) -> tuple[str, ...]:
    sources: set[str] = set()

    def visit(item: Any) -> None:
        if isinstance(item, str):
            try:
                sources.add(parse_stable_key(item).source)
            except ValueError:
                pass
            return
        if isinstance(item, Mapping):
            for child in item.values():
                visit(child)
            return
        if isinstance(item, (list, tuple, set)):
            for child in item:
                visit(child)

    visit(value)
    return tuple(sorted(sources))
