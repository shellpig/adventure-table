from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from app.content.identity import reference_to_stable_key, stable_key_is_kind
from app.content.registry import ContentRegistry
from app.domain.character.schemas import SpellAccessEntry
from app.domain.character_builder.schemas import BuilderGrantSummary, BuilderIssue, BuilderIssueSeverity


@dataclass(frozen=True)
class OriginCompilation:
    language_refs: tuple[str, ...]
    feature_refs: tuple[str, ...]
    feat_refs: tuple[str, ...]
    spell_access_entries: tuple[SpellAccessEntry, ...]
    issues: tuple[BuilderIssue, ...]


def _issue(code: str, path: str, message: str, *refs: str) -> BuilderIssue:
    return BuilderIssue(
        code=code,
        severity=BuilderIssueSeverity.BLOCKING_ERROR,
        path=path,
        message=message,
        related_refs=tuple(refs),
    )


def _entry_id(feature_ref: str, spell_ref: str) -> str:
    digest = sha256(f"{feature_ref}|{spell_ref}".encode("utf-8")).hexdigest()[:20]
    return f"race:{digest}:granted"


def compile_origin(
    *,
    grants: tuple[BuilderGrantSummary, ...],
    target_level: int | None,
    registry: ContentRegistry,
) -> OriginCompilation:
    """Compile permanent origin selections that P1 did not previously persist.

    P1 already compiles selected proficiencies through the progression path and
    ability bonuses through the foundation summary. M01-B keeps those paths and
    adds the remaining origin identities here: languages, explicit racial
    features, Variant Human feats, and feature-owned racial spell access.
    """

    languages: list[str] = []
    features: list[str] = []
    feats: list[str] = []
    issues: list[BuilderIssue] = []

    for grant in grants:
        reference_id = grant.reference_id
        if reference_id is None:
            continue
        if stable_key_is_kind(reference_id, "language"):
            languages.append(reference_id)
        elif stable_key_is_kind(reference_id, "feature"):
            features.append(reference_id)
        elif stable_key_is_kind(reference_id, "feat"):
            feats.append(reference_id)

    access_entries: list[SpellAccessEntry] = []
    character_level = target_level or 0
    for feature_ref in dict.fromkeys(features):
        feature = registry.get_optional(feature_ref)
        if feature is None:
            issues.append(
                _issue(
                    "origin_rules_data_error",
                    "draft_payload.race_selection",
                    f"Unknown racial feature: {feature_ref}",
                    feature_ref,
                )
            )
            continue
        raw_access = feature.data.get("racial_spell_access")
        if raw_access is None:
            continue
        if not isinstance(raw_access, list):
            issues.append(
                _issue(
                    "origin_rules_data_error",
                    "draft_payload.race_selection",
                    f"{feature.name} has malformed racial_spell_access data.",
                    feature_ref,
                )
            )
            continue

        for index, raw in enumerate(raw_access):
            path = f"content.{feature_ref}.racial_spell_access.{index}"
            if not isinstance(raw, dict):
                issues.append(
                    _issue(
                        "origin_rules_data_error",
                        path,
                        f"{feature.name} has a malformed racial spell row.",
                        feature_ref,
                    )
                )
                continue
            min_level = raw.get("min_character_level", 1)
            if not isinstance(min_level, int) or min_level < 1:
                issues.append(
                    _issue(
                        "origin_rules_data_error",
                        path,
                        f"{feature.name} has an invalid racial spell level gate.",
                        feature_ref,
                    )
                )
                continue
            if character_level < min_level:
                continue
            spell = raw.get("spell")
            try:
                spell_ref = (
                    reference_to_stable_key(spell, kinds={"spell"})
                    if isinstance(spell, dict)
                    else None
                )
            except ValueError:
                spell_ref = None
            if spell_ref is None or registry.get_optional(spell_ref) is None:
                issues.append(
                    _issue(
                        "origin_rules_data_error",
                        path,
                        f"{feature.name} references an unknown racial spell.",
                        feature_ref,
                        *(tuple([spell_ref]) if spell_ref else ()),
                    )
                )
                continue
            if raw.get("uses_spell_slot") is not False:
                issues.append(
                    _issue(
                        "origin_rules_data_error",
                        path,
                        f"{feature.name} racial spell access must explicitly opt out of normal spell slots.",
                        feature_ref,
                        spell_ref,
                    )
                )
                continue
            access_entries.append(
                SpellAccessEntry(
                    entry_id=_entry_id(feature_ref, spell_ref),
                    spell_key=spell_ref,
                    source_type="race",
                    source_key=feature_ref,
                    access_type="granted",
                )
            )

    return OriginCompilation(
        language_refs=tuple(dict.fromkeys(languages)),
        feature_refs=tuple(dict.fromkeys(features)),
        feat_refs=tuple(dict.fromkeys(feats)),
        spell_access_entries=tuple({entry.entry_id: entry for entry in access_entries}.values()),
        issues=tuple(issues),
    )
