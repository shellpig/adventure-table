from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from pydantic import ValidationError

from app.content.schemas import ContentEntry, ContentManifest, DATA_MODELS


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CONTENT_ROOT = REPOSITORY_ROOT / "data" / "srd5.1"

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


class ContentValidationError(RuntimeError):
    pass


class ContentNotFoundError(KeyError):
    pass


class ContentRegistry:
    def __init__(
        self,
        manifest: ContentManifest,
        entries: dict[str, ContentEntry],
        by_kind: dict[str, tuple[ContentEntry, ...]],
    ) -> None:
        self.manifest = manifest
        self._entries = entries
        self._by_kind = by_kind

    @classmethod
    def from_directory(cls, root: Path) -> "ContentRegistry":
        root = root.resolve()
        manifest_path = root / "manifest.json"
        if not manifest_path.is_file():
            raise ContentValidationError(f"missing SRD manifest: {manifest_path}")

        try:
            manifest = ContentManifest.model_validate_json(
                manifest_path.read_text(encoding="utf-8")
            )
        except (OSError, ValidationError, ValueError) as exc:
            raise ContentValidationError(f"invalid SRD manifest: {exc}") from exc

        forbidden = [root / "monsters.json", root / "beasts.json"]
        present_forbidden = [path.name for path in forbidden if path.exists()]
        if present_forbidden:
            raise ContentValidationError(
                "P0 scope violation: Monster/Beast data must remain deferred to P4-A: "
                + ", ".join(present_forbidden)
            )

        entries: dict[str, ContentEntry] = {}
        by_kind_mutable: dict[str, list[ContentEntry]] = defaultdict(list)

        for category in manifest.categories:
            if category.kind in {"monster", "beast"} or category.name in {
                "monsters",
                "beasts",
            }:
                raise ContentValidationError(
                    f"P0 scope violation in manifest category: {category.name}"
                )

            category_path = root / category.file
            try:
                payload = json.loads(category_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ContentValidationError(
                    f"cannot load category {category.name}: {exc}"
                ) from exc
            if not isinstance(payload, list):
                raise ContentValidationError(
                    f"category {category.name} must contain a JSON array"
                )
            if len(payload) != category.count:
                raise ContentValidationError(
                    f"category {category.name} count mismatch: "
                    f"manifest={category.count}, file={len(payload)}"
                )

            data_model = DATA_MODELS[category.kind]
            for position, raw_entry in enumerate(payload):
                try:
                    entry = ContentEntry.model_validate(raw_entry)
                    typed_data = data_model.model_validate(entry.data)
                except ValidationError as exc:
                    raise ContentValidationError(
                        f"{category.name}[{position}] schema validation failed: {exc}"
                    ) from exc

                expected_key = f"srd5.1:{category.kind}:{entry.index}"
                if entry.key != expected_key:
                    raise ContentValidationError(
                        f"{entry.key}: expected stable key {expected_key}"
                    )
                if typed_data.index != entry.index:
                    raise ContentValidationError(
                        f"{entry.key}: envelope/data index mismatch"
                    )
                if typed_data.name is not None and typed_data.name != entry.name:
                    raise ContentValidationError(
                        f"{entry.key}: envelope/data name mismatch"
                    )
                if entry.key in entries:
                    raise ContentValidationError(f"duplicate content key: {entry.key}")

                entries[entry.key] = entry
                by_kind_mutable[category.kind].append(entry)

        if len(entries) != manifest.total_entries:
            raise ContentValidationError(
                f"registry entry count mismatch: manifest={manifest.total_entries}, "
                f"loaded={len(entries)}"
            )

        cls._validate_cross_references(entries.values(), entries)
        by_kind = {
            kind: tuple(kind_entries)
            for kind, kind_entries in by_kind_mutable.items()
        }
        return cls(manifest=manifest, entries=entries, by_kind=by_kind)

    @staticmethod
    def _validate_cross_references(
        source_entries: Iterable[ContentEntry],
        entries: dict[str, ContentEntry],
    ) -> None:
        for source_entry in source_entries:
            for target_key, url in _iter_stable_references(source_entry.data):
                if target_key not in entries:
                    raise ContentValidationError(
                        f"{source_entry.key}: dangling reference {url} -> {target_key}"
                    )

    def get(self, key: str) -> ContentEntry:
        try:
            return self._entries[key]
        except KeyError as exc:
            raise ContentNotFoundError(key) from exc

    def get_optional(self, key: str) -> ContentEntry | None:
        return self._entries.get(key)

    def resolve(self, kind: str, index: str) -> ContentEntry:
        return self.get(f"srd5.1:{kind}:{index}")

    def list_kind(self, kind: str) -> tuple[ContentEntry, ...]:
        return self._by_kind.get(kind, ())

    def __len__(self) -> int:
        return len(self._entries)


def _iter_stable_references(value: Any) -> Iterable[tuple[str, str]]:
    if isinstance(value, dict):
        url = value.get("url")
        index = value.get("index")
        if isinstance(url, str) and isinstance(index, str):
            target = _stable_key_from_api_url(url, index)
            if target is not None:
                yield target, url
        for child in value.values():
            yield from _iter_stable_references(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_stable_references(child)


def _stable_key_from_api_url(url: str, index: str) -> str | None:
    path = urlparse(url).path
    parts = [part for part in path.split("/") if part]
    if len(parts) != 4 or parts[0:2] != ["api", "2014"]:
        return None
    kind = URL_ROUTE_TO_KIND.get(parts[2])
    if kind is None:
        return None
    if parts[3] != index:
        raise ContentValidationError(
            f"reference URL/index mismatch: url={url}, index={index}"
        )
    return f"srd5.1:{kind}:{index}"


def load_default_content_registry() -> ContentRegistry:
    return ContentRegistry.from_directory(DEFAULT_CONTENT_ROOT)
