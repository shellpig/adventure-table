from __future__ import annotations

from dataclasses import dataclass
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from pydantic import ValidationError

from app.content.identity import (
    URL_ROUTE_TO_KIND,
    parse_stable_key,
    reference_to_stable_key,
    require_pack_id,
    stable_key,
)
from app.content.schemas import ContentEntry, ContentManifest, DATA_MODELS


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
CONTENT_PACKS_ROOT = REPOSITORY_ROOT / "data"
DEFAULT_CONTENT_PACKS = ("srd5.1",)
# P0 compatibility: existing tests/importers use DEFAULT_CONTENT_ROOT as the
# direct SRD pack directory. Multi-pack loading uses CONTENT_PACKS_ROOT.
DEFAULT_CONTENT_ROOT = CONTENT_PACKS_ROOT / "srd5.1"
DEFAULT_SRD_CONTENT_ROOT = DEFAULT_CONTENT_ROOT

# The imported 5e SRD Rogue level feed carries several non-ASI rows whose
# cumulative ability_score_bonuses value is one lower than the immediately
# preceding ASI milestone. Normalize only these verified upstream anomalies at
# the content boundary so downstream progression code can keep treating the
# field as a monotonic cumulative counter and can still fail fast on any other
# decrease.
KNOWN_LEVEL_ABILITY_SCORE_BONUS_CORRECTIONS: dict[str, tuple[int, int]] = {
    "srd5.1:level:rogue-11": (2, 3),
    "srd5.1:level:rogue-13": (3, 4),
    "srd5.1:level:rogue-14": (3, 4),
    "srd5.1:level:rogue-15": (3, 4),
    "srd5.1:level:rogue-17": (4, 5),
    "srd5.1:level:rogue-18": (4, 5),
    "srd5.1:level:rogue-20": (5, 6),
}

_REFERENCE_KIND_BY_FIELD: dict[str, str] = {
    "ability_score": "ability",
    "class": "class",
    "classes": "class",
    "equipment": "equipment",
    "equipment_category": "equipment-category",
    "features": "feature",
    "languages": "language",
    "proficiencies": "proficiency",
    "race": "race",
    # Some legacy SRD records use plural `races` for a mixed race/subrace list,
    # so that field is intentionally validated only for existence, not one kind.
    # Likewise, generic option objects use `item` for many reference kinds
    # (proficiency, language, equipment, etc.), so `item` cannot imply one kind.
    "saving_throws": "ability",
    "school": "magic-school",
    "subclass": "subclass",
    "subclasses": "subclass",
    "subrace": "subrace",
    "subraces": "subrace",
    "traits": "trait",
    "racial_traits": "trait",
    "starting_proficiencies": "proficiency",
}


class ContentValidationError(RuntimeError):
    pass


class ContentNotFoundError(KeyError):
    pass


@dataclass(frozen=True)
class ContentPack:
    manifest: ContentManifest
    root: Path
    entries: tuple[ContentEntry, ...]


def _normalize_known_source_anomalies(entry: ContentEntry) -> ContentEntry:
    correction = KNOWN_LEVEL_ABILITY_SCORE_BONUS_CORRECTIONS.get(entry.key)
    if correction is None:
        return entry

    source_value, normalized_value = correction
    value = entry.data.get("ability_score_bonuses")
    if value == normalized_value:
        return entry
    if value != source_value:
        raise ContentValidationError(
            "known SRD ability_score_bonuses correction no longer matches "
            f"{entry.key}: expected {source_value}, got {value}"
        )

    data = dict(entry.data)
    data["ability_score_bonuses"] = normalized_value
    return entry.model_copy(update={"data": data})


class ContentRegistry:
    def __init__(
        self,
        manifest: ContentManifest | None = None,
        entries: dict[str, ContentEntry] | None = None,
        by_kind: dict[str, tuple[ContentEntry, ...]] | None = None,
        *,
        packs: dict[str, ContentPack] | None = None,
        by_source_kind: dict[tuple[str, str], tuple[ContentEntry, ...]] | None = None,
        enabled_pack_ids: tuple[str, ...] | None = None,
    ) -> None:
        """Create a registry while preserving the P0/P1 direct constructor.

        New code should use ``from_directory`` or ``from_root``. The positional
        ``(manifest, entries, by_kind)`` form remains supported because existing
        tests and small in-memory adapters use it to inject temporary SRD entries.
        """
        if manifest is not None:
            if entries is None or by_kind is None:
                raise TypeError("legacy ContentRegistry construction requires manifest, entries, and by_kind")
            if packs is not None or by_source_kind is not None or enabled_pack_ids is not None:
                raise TypeError("cannot mix legacy and multi-pack ContentRegistry constructor arguments")
            legacy_pack = ContentPack(
                manifest=manifest,
                root=DEFAULT_CONTENT_ROOT if manifest.id == "srd5.1" else Path("."),
                entries=tuple(entries.values()),
            )
            packs = {manifest.id: legacy_pack}
            by_source_kind_mutable: dict[tuple[str, str], list[ContentEntry]] = defaultdict(list)
            for entry in entries.values():
                parsed = parse_stable_key(entry.key)
                by_source_kind_mutable[(entry.source, parsed.kind)].append(entry)
            by_source_kind = {
                key: tuple(kind_entries)
                for key, kind_entries in by_source_kind_mutable.items()
            }
            enabled_pack_ids = (manifest.id,)

        if packs is None or entries is None or by_kind is None or by_source_kind is None or enabled_pack_ids is None:
            raise TypeError("ContentRegistry requires complete registry indexes")

        self._packs = packs
        self._entries = entries
        self._by_kind = by_kind
        self._by_source_kind = by_source_kind
        self.enabled_pack_ids = enabled_pack_ids

    @property
    def manifest(self) -> ContentManifest:
        """P0 compatibility: expose the SRD manifest when it is installed."""
        if "srd5.1" in self._packs:
            return self._packs["srd5.1"].manifest
        if len(self._packs) == 1:
            return next(iter(self._packs.values())).manifest
        raise ContentValidationError(
            "registry contains multiple non-SRD packs; use get_source_manifest(source)"
        )

    @property
    def pack_count(self) -> int:
        return len(self._packs)

    @classmethod
    def from_directory(cls, root: Path) -> "ContentRegistry":
        """Compatibility loader for one explicit pack directory."""
        pack = cls._load_pack(root.resolve())
        return cls._from_loaded_packs((pack,))

    @classmethod
    def from_root(
        cls,
        content_root: Path,
        enabled_pack_ids: Iterable[str],
    ) -> "ContentRegistry":
        root = content_root.resolve()
        pack_ids = tuple(enabled_pack_ids)
        if not pack_ids:
            raise ContentValidationError("enabled content pack list cannot be empty")
        if len(pack_ids) != len(set(pack_ids)):
            raise ContentValidationError("enabled content pack ids must be unique")

        packs: list[ContentPack] = []
        for pack_id in pack_ids:
            try:
                require_pack_id(pack_id)
            except ValueError as exc:
                raise ContentValidationError(f"invalid enabled content pack id {pack_id}: {exc}") from exc
            pack_root = root / pack_id
            if not pack_root.is_dir():
                raise ContentValidationError(f"enabled content pack directory is missing: {pack_root}")
            packs.append(cls._load_pack(pack_root))
        return cls._from_loaded_packs(tuple(packs))

    @classmethod
    def _from_loaded_packs(cls, loaded_packs: tuple[ContentPack, ...]) -> "ContentRegistry":
        packs: dict[str, ContentPack] = {}
        entries: dict[str, ContentEntry] = {}
        by_kind_mutable: dict[str, list[ContentEntry]] = defaultdict(list)
        by_source_kind_mutable: dict[tuple[str, str], list[ContentEntry]] = defaultdict(list)

        for pack in loaded_packs:
            source = pack.manifest.id
            if source in packs:
                raise ContentValidationError(f"duplicate content pack id: {source}")
            packs[source] = pack
            for entry in pack.entries:
                if entry.key in entries:
                    raise ContentValidationError(f"duplicate content key: {entry.key}")
                entries[entry.key] = entry
                kind = parse_stable_key(entry.key).kind
                by_kind_mutable[kind].append(entry)
                by_source_kind_mutable[(source, kind)].append(entry)

        cls._validate_cross_references(entries.values(), entries)
        by_kind = {
            kind: tuple(sorted(kind_entries, key=lambda entry: entry.key))
            for kind, kind_entries in by_kind_mutable.items()
        }
        by_source_kind = {
            key: tuple(sorted(kind_entries, key=lambda entry: entry.key))
            for key, kind_entries in by_source_kind_mutable.items()
        }
        return cls(
            packs=packs,
            entries=entries,
            by_kind=by_kind,
            by_source_kind=by_source_kind,
            enabled_pack_ids=tuple(pack.manifest.id for pack in loaded_packs),
        )

    @classmethod
    def _load_pack(cls, root: Path) -> ContentPack:
        manifest_path = root / "manifest.json"
        if not manifest_path.is_file():
            raise ContentValidationError(f"missing content manifest: {manifest_path}")

        try:
            manifest = ContentManifest.model_validate_json(
                manifest_path.read_text(encoding="utf-8")
            )
        except (OSError, ValidationError, ValueError) as exc:
            raise ContentValidationError(f"invalid content manifest: {exc}") from exc

        if root.name != manifest.id:
            raise ContentValidationError(
                f"content pack directory/id mismatch: directory={root.name}, manifest={manifest.id}"
            )

        if manifest.id == "srd5.1":
            forbidden = [root / "monsters.json", root / "beasts.json"]
            present_forbidden = [path.name for path in forbidden if path.exists()]
            if present_forbidden:
                raise ContentValidationError(
                    "P0 scope violation: Monster/Beast data must remain deferred to P4-A: "
                    + ", ".join(present_forbidden)
                )

        entries: dict[str, ContentEntry] = {}
        for category in manifest.categories:
            if manifest.id == "srd5.1" and (
                category.kind in {"monster", "beast"}
                or category.name in {"monsters", "beasts"}
            ):
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
                    f"{category.name} count mismatch: "
                    f"manifest={category.count}, file={len(payload)}"
                )

            data_model = DATA_MODELS[category.kind]
            for position, raw_entry in enumerate(payload):
                try:
                    entry = ContentEntry.model_validate(raw_entry)
                    entry = _normalize_known_source_anomalies(entry)
                    typed_data = data_model.model_validate(entry.data)
                except ValidationError as exc:
                    raise ContentValidationError(
                        f"{category.name}[{position}] schema validation failed: {exc}"
                    ) from exc
                except ValueError as exc:
                    raise ContentValidationError(
                        f"{category.name}[{position}] identity validation failed: {exc}"
                    ) from exc

                if entry.source != manifest.id:
                    raise ContentValidationError(
                        f"{entry.key}: entry source must match manifest id {manifest.id}"
                    )
                parsed = parse_stable_key(entry.key)
                expected_key = stable_key(manifest.id, category.kind, entry.index)
                if entry.key != expected_key or parsed.kind != category.kind:
                    raise ContentValidationError(
                        f"{entry.key}: expected stable key {expected_key}"
                    )
                if entry.ruleset != manifest.ruleset:
                    raise ContentValidationError(
                        f"{entry.key}: entry ruleset must match manifest ruleset {manifest.ruleset}"
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

                entries[entry.key] = entry.model_copy(
                    update={"source_label": manifest.name}
                )

        if len(entries) != manifest.total_entries:
            raise ContentValidationError(
                f"registry entry count mismatch for {manifest.id}: "
                f"manifest={manifest.total_entries}, loaded={len(entries)}"
            )
        return ContentPack(
            manifest=manifest,
            root=root,
            entries=tuple(entries.values()),
        )

    @staticmethod
    def _validate_cross_references(
        source_entries: Iterable[ContentEntry],
        entries: dict[str, ContentEntry],
    ) -> None:
        for source_entry in source_entries:
            try:
                references = tuple(_iter_stable_references(source_entry.data))
            except ValueError as exc:
                raise ContentValidationError(f"{source_entry.key}: invalid reference: {exc}") from exc
            for target_key, expected_kind, display in references:
                target = entries.get(target_key)
                if target is None:
                    raise ContentValidationError(
                        f"{source_entry.key}: dangling reference {display} -> {target_key}"
                    )
                if expected_kind is not None:
                    actual_kind = parse_stable_key(target.key).kind
                    if actual_kind != expected_kind:
                        raise ContentValidationError(
                            f"{source_entry.key}: wrong-kind reference {target_key}; "
                            f"expected {expected_kind}, got {actual_kind}"
                        )

    def get(self, key: str) -> ContentEntry:
        try:
            return self._entries[key]
        except KeyError as exc:
            raise ContentNotFoundError(key) from exc

    def get_optional(self, key: str) -> ContentEntry | None:
        return self._entries.get(key)

    def resolve(self, *parts: str) -> ContentEntry:
        """Resolve with the old SRD or new source-aware calling convention."""
        if len(parts) == 2:
            source = "srd5.1"
            kind, index = parts
        elif len(parts) == 3:
            source, kind, index = parts
        else:
            raise TypeError("resolve expects (kind, index) or (source, kind, index)")
        return self.get(stable_key(source, kind, index))

    def resolve_reference(
        self,
        reference: dict[str, Any],
        *,
        kinds: set[str] | None = None,
    ) -> ContentEntry:
        try:
            key = reference_to_stable_key(reference, kinds=kinds)
        except ValueError as exc:
            raise ContentValidationError(str(exc)) from exc
        if key is None:
            raise ContentValidationError("unsupported content reference shape")
        return self.get(key)

    def list_kind(
        self,
        kind: str,
        *,
        source: str | None = None,
    ) -> tuple[ContentEntry, ...]:
        if source is None:
            return self._by_kind.get(kind, ())
        return self._by_source_kind.get((source, kind), ())

    def get_source_manifest(self, source: str) -> ContentManifest:
        try:
            return self._packs[source].manifest
        except KeyError as exc:
            raise ContentNotFoundError(source) from exc

    def source_label(self, source: str) -> str:
        return self.get_source_manifest(source).name

    def __len__(self) -> int:
        return len(self._entries)


def _looks_like_reference(value: dict[str, Any]) -> bool:
    if "key" in value:
        return isinstance(value.get("key"), str) and isinstance(value.get("name"), str)
    return (
        isinstance(value.get("index"), str)
        and isinstance(value.get("name"), str)
        and isinstance(value.get("url"), str)
    )


def _iter_stable_references(
    value: Any,
    *,
    field_name: str | None = None,
) -> Iterable[tuple[str, str | None, str]]:
    if isinstance(value, dict):
        if field_name is not None and _looks_like_reference(value):
            key = reference_to_stable_key(value)
            if key is not None:
                expected_kind = _REFERENCE_KIND_BY_FIELD.get(field_name)
                yield key, expected_kind, str(value.get("url") or value.get("key"))
                return
        for child_name, child in value.items():
            yield from _iter_stable_references(child, field_name=child_name)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_stable_references(child, field_name=field_name)


def load_default_content_registry() -> ContentRegistry:
    return ContentRegistry.from_root(CONTENT_PACKS_ROOT, DEFAULT_CONTENT_PACKS)
