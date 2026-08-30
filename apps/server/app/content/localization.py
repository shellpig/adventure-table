from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from app.content.identity import parse_stable_key
from app.content.registry import ContentRegistry, ContentValidationError


SUPPORTED_CONTENT_LOCALES = ("zh-TW", "en")
DEFAULT_SERVER_PRESENTATION_LOCALE = "en"
ROLEPLAY_FIELDS = ("personality_traits", "ideals", "bonds", "flaws")


def require_content_locale(locale: str) -> str:
    if locale not in SUPPORTED_CONTENT_LOCALES:
        raise ValueError(
            f"unsupported content locale {locale!r}; expected one of {SUPPORTED_CONTENT_LOCALES}"
        )
    return locale


@dataclass(frozen=True)
class LocalizableFieldRule:
    pack: str
    kind: str
    field_path: str
    localizable: bool
    currently_user_visible: bool
    required_locales: tuple[str, ...]
    surfaces: tuple[str, ...]
    reason: str

    def matches(self, pack: str, kind: str, field_path: str) -> bool:
        return (
            (self.pack == "*" or self.pack == pack)
            and (self.kind == "*" or self.kind == kind)
            and fnmatchcase(field_path, self.field_path)
        )

    def requires(self, locale: str) -> bool:
        return (
            self.localizable
            and self.currently_user_visible
            and locale in self.required_locales
        )


class LocalizableFieldPolicy:
    """Machine-readable SSOT for the current rules-content localization scope."""

    def __init__(self, rules: Iterable[LocalizableFieldRule]) -> None:
        self.rules = tuple(rules)
        if not self.rules:
            raise ContentValidationError("localizable field policy cannot be empty")

    @classmethod
    def from_path(cls, path: Path) -> "LocalizableFieldPolicy":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContentValidationError(f"cannot load localizable field policy: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise ContentValidationError("localizable field policy schema_version must be 1")
        locales = payload.get("supported_locales")
        if locales != list(SUPPORTED_CONTENT_LOCALES):
            raise ContentValidationError(
                "localizable field policy supported_locales must be ['zh-TW', 'en']"
            )
        raw_rules = payload.get("rules")
        if not isinstance(raw_rules, list):
            raise ContentValidationError("localizable field policy rules must be a list")

        rules: list[LocalizableFieldRule] = []
        seen: set[tuple[str, str, str]] = set()
        for index, raw in enumerate(raw_rules):
            if not isinstance(raw, dict):
                raise ContentValidationError(f"field policy rule {index} must be an object")
            try:
                rule = LocalizableFieldRule(
                    pack=str(raw["pack"]),
                    kind=str(raw["kind"]),
                    field_path=str(raw["field_path"]),
                    localizable=bool(raw["localizable"]),
                    currently_user_visible=bool(raw["currently_user_visible"]),
                    required_locales=tuple(str(value) for value in raw["required_locales"]),
                    surfaces=tuple(str(value) for value in raw["surfaces"]),
                    reason=str(raw["reason"]),
                )
            except (KeyError, TypeError) as exc:
                raise ContentValidationError(
                    f"field policy rule {index} is missing required fields"
                ) from exc
            if not rule.field_path or not rule.reason:
                raise ContentValidationError(f"field policy rule {index} has blank fields")
            if any(locale not in SUPPORTED_CONTENT_LOCALES for locale in rule.required_locales):
                raise ContentValidationError(
                    f"field policy rule {index} contains unsupported required locale"
                )
            identity = (rule.pack, rule.kind, rule.field_path)
            if identity in seen:
                raise ContentValidationError(f"duplicate field policy rule: {identity}")
            seen.add(identity)
            rules.append(rule)
        return cls(rules)

    def rule_for(self, pack: str, kind: str, field_path: str) -> LocalizableFieldRule | None:
        matches = [rule for rule in self.rules if rule.matches(pack, kind, field_path)]
        if not matches:
            return None
        # Prefer source-specific, then kind-specific, then the most concrete path.
        return max(
            matches,
            key=lambda rule: (
                rule.pack != "*",
                rule.kind != "*",
                sum(part != "*" for part in rule.field_path.split(".")),
            ),
        )

    def is_required(self, pack: str, kind: str, field_path: str, locale: str) -> bool:
        rule = self.rule_for(pack, kind, field_path)
        return bool(rule and rule.requires(locale))


@dataclass(frozen=True)
class LocalizedField:
    key: str
    field_path: str
    locale: str
    value: Any
    canonical_value: Any
    source: str
    fallback_used: bool
    missing_required: bool


@dataclass(frozen=True)
class TranslationCompletenessIssue:
    key: str
    field_path: str
    locale: str
    reason: str
    surfaces: tuple[str, ...]


@dataclass(frozen=True)
class LocalizedRoleplaySuggestion:
    suggestion_id: str
    background_key: str
    field: str
    position: int
    text: str
    locale: str
    missing_required: bool


def _tokens(path: str) -> tuple[str, ...]:
    if not path or path.startswith(".") or path.endswith("."):
        raise ValueError(f"invalid localization field path: {path!r}")
    return tuple(path.split("."))


def _read_path(root: Any, path: str) -> Any:
    current = root
    for token in _tokens(path):
        if isinstance(current, Mapping):
            if token not in current:
                raise KeyError(path)
            current = current[token]
            continue
        if isinstance(current, (list, tuple)) and token.isdigit():
            position = int(token)
            if position >= len(current):
                raise KeyError(path)
            current = current[position]
            continue
        raise KeyError(path)
    return current


def _iter_matching_paths(root: Any, pattern: str) -> Iterable[str]:
    tokens = _tokens(pattern)

    def walk(current: Any, offset: int, concrete: list[str]) -> Iterable[str]:
        if offset == len(tokens):
            yield ".".join(concrete)
            return
        token = tokens[offset]
        if token == "*":
            if isinstance(current, Mapping):
                for key in sorted(current):
                    yield from walk(current[key], offset + 1, [*concrete, str(key)])
            elif isinstance(current, (list, tuple)):
                for index, value in enumerate(current):
                    yield from walk(value, offset + 1, [*concrete, str(index)])
            return
        if isinstance(current, Mapping) and token in current:
            yield from walk(current[token], offset + 1, [*concrete, token])
            return
        if isinstance(current, (list, tuple)) and token.isdigit():
            index = int(token)
            if index < len(current):
                yield from walk(current[index], offset + 1, [*concrete, token])

    yield from walk(root, 0, [])


class ContentLocalizationCatalog:
    """Resolve presentation fields without changing StableKey or mechanics.

    Canonical pack data remains the English/mechanical source of truth. Locale
    overlays contain presentation fields only. Missing required translations are
    observable even when a defensive canonical fallback is returned.
    """

    def __init__(
        self,
        registry: ContentRegistry,
        policy: LocalizableFieldPolicy,
        overlays: Mapping[tuple[str, str], Mapping[str, Mapping[str, Any]]] | None = None,
    ) -> None:
        self.registry = registry
        self.policy = policy
        self._overlays = {
            (source, require_content_locale(locale)): {
                key: dict(fields) for key, fields in entries.items()
            }
            for (source, locale), entries in (overlays or {}).items()
        }

    @classmethod
    def from_root(
        cls,
        registry: ContentRegistry,
        content_root: Path,
        *,
        policy_path: Path | None = None,
    ) -> "ContentLocalizationCatalog":
        policy = LocalizableFieldPolicy.from_path(
            policy_path or content_root / "localization" / "localizable-fields.json"
        )
        overlays: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
        for source in registry.enabled_pack_ids:
            for locale in SUPPORTED_CONTENT_LOCALES:
                path = content_root / source / "locales" / f"{locale}.json"
                if not path.is_file():
                    continue
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise ContentValidationError(f"cannot load locale overlay {path}: {exc}") from exc
                if not isinstance(payload, dict) or payload.get("schema_version") != 1:
                    raise ContentValidationError(f"locale overlay {path} schema_version must be 1")
                if payload.get("locale") != locale:
                    raise ContentValidationError(f"locale overlay {path} locale mismatch")
                raw_entries = payload.get("entries")
                if not isinstance(raw_entries, dict):
                    raise ContentValidationError(f"locale overlay {path} entries must be an object")
                normalized: dict[str, dict[str, Any]] = {}
                for key, fields in raw_entries.items():
                    if not isinstance(key, str) or not isinstance(fields, dict):
                        raise ContentValidationError(f"locale overlay {path} has invalid entry payload")
                    parsed = parse_stable_key(key)
                    if parsed.source != source:
                        raise ContentValidationError(
                            f"locale overlay {path} contains cross-pack key {key}"
                        )
                    if registry.get_optional(key) is None:
                        raise ContentValidationError(
                            f"locale overlay {path} references unknown content key {key}"
                        )
                    normalized[key] = dict(fields)
                overlays[(source, locale)] = normalized
        return cls(registry, policy, overlays)

    def _canonical_payload(self, key: str) -> dict[str, Any]:
        entry = self.registry.get(key)
        return entry.model_dump(mode="python")

    def resolve_field(self, key: str, field_path: str, locale: str) -> LocalizedField:
        locale = require_content_locale(locale)
        parsed = parse_stable_key(key)
        payload = self._canonical_payload(key)
        try:
            canonical = _read_path(payload, field_path)
        except KeyError as exc:
            raise ContentValidationError(f"{key}: unknown localization field {field_path}") from exc

        overlay_fields = self._overlays.get((parsed.source, locale), {}).get(key, {})
        if field_path in overlay_fields:
            return LocalizedField(
                key=key,
                field_path=field_path,
                locale=locale,
                value=overlay_fields[field_path],
                canonical_value=canonical,
                source="overlay",
                fallback_used=False,
                missing_required=False,
            )

        # Canonical English is authoritative and is resolved through the same
        # service contract rather than bypassing localization in callers.
        if locale == "en":
            return LocalizedField(
                key=key,
                field_path=field_path,
                locale=locale,
                value=canonical,
                canonical_value=canonical,
                source="canonical",
                fallback_used=False,
                missing_required=False,
            )

        required = self.policy.is_required(parsed.source, parsed.kind, field_path, locale)
        return LocalizedField(
            key=key,
            field_path=field_path,
            locale=locale,
            value=canonical,
            canonical_value=canonical,
            source="canonical_fallback",
            fallback_used=True,
            missing_required=required,
        )

    def resolve_name(self, key: str, locale: str) -> LocalizedField:
        return self.resolve_field(key, "name", locale)

    def roleplay_suggestions(
        self,
        background_key: str,
        locale: str,
    ) -> tuple[LocalizedRoleplaySuggestion, ...]:
        locale = require_content_locale(locale)
        parsed = parse_stable_key(background_key, kinds={"background"})
        if parsed.kind != "background":
            raise ValueError("roleplay suggestions require a background StableKey")
        entry = self.registry.get(background_key)
        raw = entry.data.get("roleplay_suggestions")
        if not isinstance(raw, dict):
            return ()
        suggestions: list[LocalizedRoleplaySuggestion] = []
        for field in ROLEPLAY_FIELDS:
            values = raw.get(field)
            if not isinstance(values, list):
                continue
            for position, _value in enumerate(values):
                path = f"data.roleplay_suggestions.{field}.{position}"
                localized = self.resolve_field(background_key, path, locale)
                if not isinstance(localized.value, str):
                    raise ContentValidationError(f"{background_key}: {path} must resolve to text")
                suggestions.append(
                    LocalizedRoleplaySuggestion(
                        suggestion_id=roleplay_suggestion_id(background_key, field, position),
                        background_key=background_key,
                        field=field,
                        position=position,
                        text=localized.value,
                        locale=locale,
                        missing_required=localized.missing_required,
                    )
                )
        return tuple(suggestions)

    def completeness_issues(
        self,
        *,
        locales: Iterable[str] = SUPPORTED_CONTENT_LOCALES,
        sources: set[str] | None = None,
        kinds: set[str] | None = None,
    ) -> tuple[TranslationCompletenessIssue, ...]:
        requested_locales = tuple(require_content_locale(locale) for locale in locales)
        issues: list[TranslationCompletenessIssue] = []
        for rule in self.policy.rules:
            if not rule.localizable or not rule.currently_user_visible:
                continue
            for source in self.registry.enabled_pack_ids:
                if sources is not None and source not in sources:
                    continue
                if rule.pack not in {"*", source}:
                    continue
                candidate_kinds = (
                    {rule.kind}
                    if rule.kind != "*"
                    else {
                        parse_stable_key(entry.key).kind
                        for entry in self.registry.list_kind("background")
                    }
                )
                for kind in candidate_kinds:
                    if kinds is not None and kind not in kinds:
                        continue
                    if rule.kind not in {"*", kind}:
                        continue
                    for entry in self.registry.list_kind(kind, source=source):
                        payload = entry.model_dump(mode="python")
                        concrete_paths = tuple(_iter_matching_paths(payload, rule.field_path))
                        for field_path in concrete_paths:
                            for locale in requested_locales:
                                if not rule.requires(locale):
                                    continue
                                localized = self.resolve_field(entry.key, field_path, locale)
                                if localized.missing_required:
                                    issues.append(
                                        TranslationCompletenessIssue(
                                            key=entry.key,
                                            field_path=field_path,
                                            locale=locale,
                                            reason=rule.reason,
                                            surfaces=rule.surfaces,
                                        )
                                    )
        return tuple(issues)


def roleplay_suggestion_id(background_key: str, field: str, position: int) -> str:
    parse_stable_key(background_key, kinds={"background"})
    if field not in ROLEPLAY_FIELDS:
        raise ValueError(f"unsupported roleplay field: {field}")
    if position < 0:
        raise ValueError("roleplay suggestion position must be non-negative")
    return f"{background_key}:roleplay:{field}:{position + 1:02d}"


@dataclass(frozen=True)
class GlossaryTerm:
    term: str
    zh_tw: str
    reference_zh_tw: str | None
    reference_source: str | None
    decision_note: str | None
    reviewed: bool


class TerminologyGlossary:
    """Review-time terminology SSOT; runtime never regex-replaces prose from it."""

    def __init__(self, terms: Iterable[GlossaryTerm]) -> None:
        self.terms = tuple(terms)
        names = [term.term for term in self.terms]
        if len(names) != len(set(names)):
            raise ContentValidationError("terminology glossary contains duplicate English terms")
        if any(not term.reviewed for term in self.terms):
            raise ContentValidationError("terminology glossary contains unreviewed terms")
        for term in self.terms:
            if not term.term.strip() or not term.zh_tw.strip():
                raise ContentValidationError("terminology glossary terms cannot be blank")
            if (
                term.reference_zh_tw is not None
                and term.reference_zh_tw != term.zh_tw
                and not (term.decision_note and term.decision_note.strip())
            ):
                raise ContentValidationError(
                    f"terminology divergence for {term.term} requires a decision_note"
                )

    @classmethod
    def from_path(cls, path: Path) -> "TerminologyGlossary":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContentValidationError(f"cannot load terminology glossary: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise ContentValidationError("terminology glossary schema_version must be 1")
        if payload.get("ruleset") != "dnd5e-2014":
            raise ContentValidationError("terminology glossary ruleset must be dnd5e-2014")
        raw_terms = payload.get("terms")
        if not isinstance(raw_terms, list):
            raise ContentValidationError("terminology glossary terms must be a list")
        terms: list[GlossaryTerm] = []
        for index, raw in enumerate(raw_terms):
            if not isinstance(raw, dict):
                raise ContentValidationError(f"terminology glossary term {index} must be an object")
            terms.append(
                GlossaryTerm(
                    term=str(raw.get("en", "")),
                    zh_tw=str(raw.get("zh-TW", "")),
                    reference_zh_tw=(
                        str(raw["reference_zh-TW"])
                        if raw.get("reference_zh-TW") is not None
                        else None
                    ),
                    reference_source=(
                        str(raw["reference_source"])
                        if raw.get("reference_source") is not None
                        else None
                    ),
                    decision_note=(
                        str(raw["decision_note"])
                        if raw.get("decision_note") is not None
                        else None
                    ),
                    reviewed=raw.get("reviewed") is True,
                )
            )
        return cls(terms)
