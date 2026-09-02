from __future__ import annotations

from dataclasses import replace

from app.content.registry import ContentRegistry
from app.domain.character.schemas import CharacterBuild, SpellAccessEntry
from app.domain.character_builder.compiler import BuilderCompileResult
from app.domain.character_builder.schemas import (
    BuilderChoice,
    BuilderDraft,
    BuilderIssue,
    BuilderIssueSeverity,
)
from app.domain.character_builder.validation import make_validation_result
from app.domain.rules.spellcasting import spellcasting_ability


SPELL_SNIPER = "phb2014:feat:spell-sniper"
MAGIC_INITIATE = "phb2014:feat:magic-initiate"
RITUAL_CASTER = "phb2014:feat:ritual-caster"
FEAT_SPELL_SOURCES = {SPELL_SNIPER, MAGIC_INITIATE, RITUAL_CASTER}


def _blocking(
    code: str,
    path: str,
    message: str,
    *refs: str,
) -> BuilderIssue:
    return BuilderIssue(
        code=code,
        severity=BuilderIssueSeverity.BLOCKING_ERROR,
        path=path,
        message=message,
        related_refs=tuple(refs),
    )


def _spell_sniper_choices(
    draft: BuilderDraft,
    registry: ContentRegistry,
    choices: tuple[BuilderChoice, ...],
) -> tuple[tuple[BuilderChoice, ...], tuple[BuilderIssue, ...]]:
    """Restrict Spell Sniper to cantrips that actually make a spell attack.

    The generic feat compiler already applies source-class and cantrip-level
    filtering. K adds only the PHB rule's final predicate here, using the same
    canonical spell ``attack_type`` metadata used by SRD content. A forged stale
    or non-attack selection is blocked server-side as well as removed from UI.
    """

    result: list[BuilderChoice] = []
    issues: list[BuilderIssue] = []
    for choice in choices:
        if choice.source_ref != SPELL_SNIPER or choice.option_source != "content:feat:spell":
            result.append(choice)
            continue

        legal_options = tuple(
            option
            for option in choice.options
            if option.reference_id is not None
            and (spell := registry.get_optional(option.reference_id)) is not None
            and spell.data.get("level") == 0
            and spell.data.get("attack_type") in {"melee", "ranged"}
        )
        legal_ids = {option.option_id for option in legal_options}
        selected = draft.draft_payload.choice_selections.get(choice.choice_id)
        if selected is not None:
            illegal = tuple(
                option_id
                for option_id in selected.selected_option_ids
                if option_id not in legal_ids
            )
            if illegal:
                issues.append(
                    _blocking(
                        "illegal_feat_spell_choice",
                        f"draft_payload.choice_selections.{choice.choice_id}",
                        "Spell Sniper must select a cantrip that requires a spell attack roll from the chosen source class.",
                        SPELL_SNIPER,
                        *illegal,
                    )
                )
        result.append(choice.model_copy(update={"options": legal_options}))
    return tuple(result), tuple(issues)


def _feat_spell_source_ability(
    build: CharacterBuild,
    feat_ref: str,
    registry: ContentRegistry,
) -> str | None:
    acquisitions = tuple(
        acquisition
        for acquisition in build.feat_acquisitions
        if acquisition.feat_ref == feat_ref
    )
    if len(acquisitions) != 1:
        return None
    source = acquisitions[0].selections.get("spell-source", ())
    if len(source) != 1:
        return None
    return spellcasting_ability(source[0], registry)


def _normalize_feat_spell_access(
    build: CharacterBuild,
    registry: ContentRegistry,
) -> CharacterBuild:
    """Materialize casting-source semantics on feat-granted spell access rows.

    Magic Initiate's chosen 1st-level spell also receives its once-per-long-rest
    resource metadata. This stays on the existing SpellAccessEntry substrate, so
    creation/reconciliation automatically use the established generic resource
    path rather than a feat-only live-state bag.
    """

    ability_by_feat = {
        feat_ref: _feat_spell_source_ability(build, feat_ref, registry)
        for feat_ref in FEAT_SPELL_SOURCES
    }
    acquisitions_by_feat = {
        acquisition.feat_ref: acquisition
        for acquisition in build.feat_acquisitions
        if acquisition.feat_ref in FEAT_SPELL_SOURCES
    }

    entries: list[SpellAccessEntry] = []
    for entry in build.spell_access_entries:
        if entry.source_type != "feat" or entry.source_key not in FEAT_SPELL_SOURCES:
            entries.append(entry)
            continue

        updates: dict[str, object] = {}
        ability = ability_by_feat.get(entry.source_key)
        if ability is not None:
            updates["casting_ability"] = ability

        if entry.source_key == MAGIC_INITIATE:
            acquisition = acquisitions_by_feat.get(MAGIC_INITIATE)
            selected_level_one = (
                acquisition.selections.get("spell", ())
                if acquisition is not None
                else ()
            )
            if entry.spell_key in selected_level_one:
                updates["uses_per_rest"] = 1
                updates["rest_type"] = "long_rest"

        entries.append(entry.model_copy(update=updates) if updates else entry)

    return build.model_copy(update={"spell_access_entries": tuple(entries)})


def apply_m01k_post_compile(
    draft: BuilderDraft,
    registry: ContentRegistry,
    compiled: BuilderCompileResult,
) -> BuilderCompileResult:
    choices, issues = _spell_sniper_choices(draft, registry, compiled.choices)
    build = (
        _normalize_feat_spell_access(compiled.build_candidate, registry)
        if compiled.build_candidate is not None
        else None
    )
    validation = make_validation_result((*compiled.validation.issues, *issues))
    return replace(
        compiled,
        build_candidate=build,
        choices=choices,
        validation=validation,
    )
