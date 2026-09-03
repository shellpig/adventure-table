from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from pydantic import ValidationError

from app.content.identity import reference_to_stable_key, stable_key_is_kind
from app.content.m01m_models import M01MRacialSpellAccessData
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


def _entry_id(source_ref: str, spell_ref: str) -> str:
    digest = sha256(f"{source_ref}|{spell_ref}".encode("utf-8")).hexdigest()[:20]
    return f"race:{digest}:granted"


def compile_origin(
    *,
    grants: tuple[BuilderGrantSummary, ...],
    target_level: int | None,
    registry: ContentRegistry,
) -> OriginCompilation:
    """Compile permanent origin grants and ancestry spell access.

    M01-M keeps M01-L recharge semantics and additionally validates static
    racial/psionic casting metadata such as cast_at_level and waived components.
    Those static facts remain canonical content owned by the source entry and are
    losslessly re-resolvable through each SpellAccessEntry.source_key.

    Racial spell metadata may live on a feature (new M01-D+ content) or on an
    existing racial trait whose StableKey must remain canonical (the SRD/PHB
    Tiefling Infernal Legacy / MTF Asmodeus baseline). Both use one resolver;
    traits are never reclassified as CharacterBuild.feature_refs.
    """

    languages: list[str] = []
    candidate_features: list[str] = []
    candidate_traits: list[str] = []
    feats: list[str] = []
    issues: list[BuilderIssue] = []

    for grant in grants:
        reference_id = grant.reference_id
        if reference_id is None:
            continue
        if stable_key_is_kind(reference_id, "language"):
            languages.append(reference_id)
        elif stable_key_is_kind(reference_id, "feature"):
            candidate_features.append(reference_id)
        elif stable_key_is_kind(reference_id, "trait"):
            candidate_traits.append(reference_id)
        elif stable_key_is_kind(reference_id, "feat"):
            feats.append(reference_id)

    character_level = target_level or 0
    features: list[str] = []
    for feature_ref in dict.fromkeys(candidate_features):
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
        minimum_level = feature.data.get("minimum_character_level", 1)
        if not isinstance(minimum_level, int) or minimum_level < 1 or minimum_level > 20:
            issues.append(
                _issue(
                    "origin_rules_data_error",
                    f"content.{feature_ref}.minimum_character_level",
                    f"{feature.name} has an invalid character-level gate.",
                    feature_ref,
                )
            )
            continue
        if character_level < minimum_level:
            continue
        features.append(feature_ref)

    spell_sources: list[str] = list(features)
    for trait_ref in dict.fromkeys(candidate_traits):
        trait = registry.get_optional(trait_ref)
        if trait is None:
            continue
        # Most legacy SRD traits remain presentation-only. Only traits that have
        # explicit typed ancestry casting metadata participate in this compiler.
        if isinstance(trait.data.get("racial_spell_access"), list):
            spell_sources.append(trait_ref)

    access_entries: list[SpellAccessEntry] = []
    for source_ref in dict.fromkeys(spell_sources):
        source = registry.get_optional(source_ref)
        if source is None:
            continue
        raw_access = source.data.get("racial_spell_access")
        if raw_access is None:
            continue
        if not isinstance(raw_access, list):
            issues.append(
                _issue(
                    "origin_rules_data_error",
                    "draft_payload.race_selection",
                    f"{source.name} has malformed racial_spell_access data.",
                    source_ref,
                )
            )
            continue

        for index, raw in enumerate(raw_access):
            path = f"content.{source_ref}.racial_spell_access.{index}"
            try:
                access = M01MRacialSpellAccessData.model_validate(raw)
            except (ValidationError, ValueError):
                issues.append(
                    _issue(
                        "origin_rules_data_error",
                        path,
                        f"{source.name} has a malformed racial spell row.",
                        source_ref,
                    )
                )
                continue
            if character_level < access.min_character_level:
                continue
            try:
                spell_ref = reference_to_stable_key(
                    access.spell.model_dump(exclude_none=True), kinds={"spell"}
                )
            except ValueError:
                spell_ref = None
            if spell_ref is None or registry.get_optional(spell_ref) is None:
                issues.append(
                    _issue(
                        "origin_rules_data_error",
                        path,
                        f"{source.name} references an unknown racial spell.",
                        source_ref,
                        *(tuple([spell_ref]) if spell_ref else ()),
                    )
                )
                continue

            access_entries.append(
                SpellAccessEntry(
                    entry_id=_entry_id(source_ref, spell_ref),
                    spell_key=spell_ref,
                    source_type="race",
                    source_key=source_ref,
                    access_type="granted",
                    casting_ability=access.casting_ability,
                    uses_per_rest=access.uses_per_rest,
                    recharge_types=tuple(access.recharge_types),
                )
            )

    return OriginCompilation(
        language_refs=tuple(dict.fromkeys(languages)),
        feature_refs=tuple(dict.fromkeys(features)),
        feat_refs=tuple(dict.fromkeys(feats)),
        spell_access_entries=tuple({entry.entry_id: entry for entry in access_entries}.values()),
        issues=tuple(issues),
    )
