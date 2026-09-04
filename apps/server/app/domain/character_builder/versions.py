from __future__ import annotations

from collections import Counter
from datetime import datetime
from enum import StrEnum
import logging
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.content.registry import ContentRegistry
from app.domain.character.schemas import CharacterBuild, CharacterState, PersistedCharacter
from app.domain.character_builder.choices import deterministic_choice_id
from app.domain.character_builder.progression import fixed_hp_gain, subclass_selection_level
from app.domain.character_builder.schemas import (
    BuilderAbilityGenerationInput,
    BuilderAbilityScores,
    BuilderBasicInput,
    BuilderChoiceSelection,
    BuilderDraftPayload,
    BuilderHPMethod,
    BuilderLevelChoice,
    BuilderMode,
    BuilderReferenceSelection,
    BuilderSpellChoiceInput,
)
from app.domain.rules.artificer import ARTIFICER_REF, known_infusion_count


logger = logging.getLogger(__name__)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CharacterVersionKind(StrEnum):
    LEGACY = "legacy"
    CREATE = "create"
    LEVEL_UP = "level_up"
    BUILD_EDIT = "build_edit"
    CORRECTION = "correction"


class CharacterVersionSummary(StrictModel):
    id: UUID
    character_id: UUID
    version_no: int = Field(ge=1)
    version_kind: CharacterVersionKind
    parent_version_id: UUID | None = None
    superseded_by_version_id: UUID | None = None
    change_note: str | None = None
    created_at: datetime
    is_current: bool
    character_level: int = Field(ge=1, le=20)
    class_summary: str


class CharacterVersionDetail(CharacterVersionSummary):
    build: CharacterBuild


def _class_summary(build: CharacterBuild, registry: ContentRegistry) -> str:
    counts = Counter(build.class_progression)
    order = tuple(dict.fromkeys(build.class_progression))
    return " / ".join(
        f"{registry.get(class_ref).name} {counts[class_ref]}" for class_ref in order
    )


def build_version_summary(
    *,
    version_id: UUID,
    character_id: UUID,
    version_no: int,
    version_kind: str,
    parent_version_id: UUID | None,
    superseded_by_version_id: UUID | None,
    change_note: str | None,
    created_at: datetime,
    current_version_id: UUID,
    build: CharacterBuild,
    registry: ContentRegistry,
) -> CharacterVersionSummary:
    return CharacterVersionSummary(
        id=version_id,
        character_id=character_id,
        version_no=version_no,
        version_kind=CharacterVersionKind(version_kind),
        parent_version_id=parent_version_id,
        superseded_by_version_id=superseded_by_version_id,
        change_note=change_note,
        created_at=created_at,
        is_current=version_id == current_version_id,
        character_level=build.character_level,
        class_summary=_class_summary(build, registry),
    )


def _legacy_level_choices(
    build: CharacterBuild,
    registry: ContentRegistry,
) -> tuple[BuilderLevelChoice, ...]:
    class_counts: Counter[str] = Counter()
    subclass_by_class = {
        selection.class_ref: selection.subclass_ref for selection in build.subclasses
    }
    result: list[BuilderLevelChoice] = []
    for index, (class_ref, hp_gain) in enumerate(
        zip(build.class_progression, build.hp_progression, strict=True),
        start=1,
    ):
        class_counts[class_ref] += 1
        class_level = class_counts[class_ref]
        class_entry = registry.get(class_ref)
        if index == 1:
            method = BuilderHPMethod.FIRST_LEVEL
        elif hp_gain == fixed_hp_gain(class_entry):
            method = BuilderHPMethod.FIXED_AVERAGE
        else:
            method = BuilderHPMethod.MANUAL_ROLLED
        timing = subclass_selection_level(class_entry, registry)
        subclass_ref = (
            subclass_by_class.get(class_ref) if timing == class_level else None
        )
        result.append(
            BuilderLevelChoice(
                character_level=index,
                class_ref=class_ref,
                hp_method=method,
                hp_base_gain=int(hp_gain),
                subclass_ref=subclass_ref,
            )
        )
    return tuple(result)


def _legacy_spell_choices(
    build: CharacterBuild,
    registry: ContentRegistry,
) -> dict[str, BuilderSpellChoiceInput]:
    grouped: dict[str, dict[str, list[str]]] = {}
    for entry in build.spell_access_entries:
        if entry.source_type != "class" or not entry.source_key.startswith(
            "srd5.1:class:"
        ):
            continue
        profile_id = f"class:{entry.source_key.rsplit(':', 1)[-1]}"
        bucket = grouped.setdefault(
            profile_id,
            {"cantrips": [], "known": [], "spellbook": []},
        )
        spell = registry.get_optional(entry.spell_key)
        level = spell.data.get("level") if spell is not None else None
        if level == 0:
            bucket["cantrips"].append(entry.spell_key)
        elif entry.access_type == "spellbook":
            bucket["spellbook"].append(entry.spell_key)
        elif entry.access_type in {"known", "granted", "always_prepared"}:
            bucket["known"].append(entry.spell_key)
    return {
        profile_id: BuilderSpellChoiceInput(
            cantrip_keys=tuple(values["cantrips"]),
            known_spell_keys=tuple(values["known"]),
            spellbook_spell_keys=tuple(values["spellbook"]),
            prepared_spell_keys=(),
        )
        for profile_id, values in grouped.items()
    }


def _lineage_selection(build: CharacterBuild) -> BuilderReferenceSelection | None:
    return (
        BuilderReferenceSelection(reference_id=build.lineage_ref)
        if build.lineage_ref is not None
        else None
    )


def _seed_authoritative_race_variant_groups(
    payload: BuilderDraftPayload,
    build: CharacterBuild,
) -> None:
    """Restore race-variant provenance from the authoritative immutable Build.

    Older M01-E confirmed payloads may retain stale child selections even after
    their top-level variant was cleared or changed. Those stale ids were safe in
    the old compiler because inactive branches were ignored, but M01-M now has a
    server-authoritative cross-variant ownership gate. Prune only provenance that
    has no owner in the current Build (or belongs to a different top-level
    variant). If an older M01-E Build still owns a variant but has no typed group
    provenance, preserve that variant's historical child selections rather than
    reverse engineering its branch from resolved mechanics.
    """

    payload.race_variant_selection = (
        BuilderReferenceSelection(reference_id=build.race_variant_ref)
        if build.race_variant_ref is not None
        else None
    )

    active_prefix = (
        f"{deterministic_choice_id('race-variant', build.race_variant_ref)}:"
        if build.race_variant_ref is not None
        else None
    )
    selections = {
        choice_id: selection
        for choice_id, selection in payload.choice_selections.items()
        if not choice_id.startswith("race-variant:")
        or (active_prefix is not None and choice_id.startswith(active_prefix))
    }

    if not build.race_variant_group_selections:
        payload.choice_selections = selections
        return

    for group in build.race_variant_group_selections:
        choice_id = deterministic_choice_id(
            "race-variant",
            group.race_variant_ref,
            group.replacement_group_id,
        )
        selections[choice_id] = BuilderChoiceSelection(
            choice_id=choice_id,
            source_ref=group.race_variant_ref,
            selected_option_ids=(group.selected_option_id,),
            provenance_path="build.race_variant_group_selections",
        )
    payload.choice_selections = selections


def _seed_authoritative_artificer_infusions(
    payload: BuilderDraftPayload,
    build: CharacterBuild,
) -> None:
    """Seed H Build choices from Build identity, never stale UI provenance.

    Characters created before M01-H legitimately have an empty infusion_refs
    tuple. Those drafts remain blocking until the user supplies the newly
    required Known Infusions. H-era Builds, however, must reopen with their
    exact immutable Known list instead of forcing a redundant reselection.
    """

    artificer_character_levels = tuple(
        index
        for index, class_ref in enumerate(build.class_progression, start=1)
        if class_ref == ARTIFICER_REF
    )
    selections = dict(payload.choice_selections)
    for choice_id in tuple(selections):
        if choice_id.endswith(":artificer:infusions-known"):
            selections.pop(choice_id, None)

    artificer_level = len(artificer_character_levels)
    if artificer_level < 2:
        payload.choice_selections = selections
        return

    anchor = artificer_character_levels[-1]
    choice_id = deterministic_choice_id(
        "level",
        str(anchor),
        "artificer",
        "infusions-known",
    )
    # A pre-H Build has no canonical Known list to invent. Seed an explicit
    # empty choice so Review clearly requires the H migration choice instead of
    # pretending those Infusions were historically known.
    selected = (
        build.infusion_refs
        if len(build.infusion_refs) == known_infusion_count(artificer_level)
        else ()
    )
    selections[choice_id] = BuilderChoiceSelection(
        choice_id=choice_id,
        source_ref="tce:feature:infuse-item",
        selected_option_ids=selected,
        provenance_path="build.infusion_refs",
    )
    payload.choice_selections = selections


def legacy_payload_from_build(
    character: PersistedCharacter,
    registry: ContentRegistry,
) -> BuilderDraftPayload:
    """Best-effort P0 adapter for characters that predate Builder provenance.

    Resolved Build fields are kept as the import baseline and annotated in
    initial_state_seed. P1-G can therefore open a versioned draft instead of
    forcing legacy characters to be recreated. Historical choices that did not
    exist in P0 remain intentionally unclaimed provenance.
    """

    build = character.build
    payload = BuilderDraftPayload(
        basic=BuilderBasicInput(name=character.name, ruleset=build.ruleset),
        target_level=build.character_level,
        race_selection=BuilderReferenceSelection(reference_id=build.race_ref),
        race_variant_selection=(
            BuilderReferenceSelection(reference_id=build.race_variant_ref)
            if build.race_variant_ref is not None
            else None
        ),
        subrace_selection=(
            BuilderReferenceSelection(reference_id=build.subrace_ref)
            if build.subrace_ref is not None
            else None
        ),
        lineage_selection=_lineage_selection(build),
        background_selection=(
            BuilderReferenceSelection(reference_id=build.background_ref)
            if build.background_ref is not None
            else None
        ),
        alignment_selection=(
            BuilderReferenceSelection(reference_id=build.alignment_ref)
            if build.alignment_ref is not None
            else None
        ),
        ability_generation=BuilderAbilityGenerationInput(
            method="manual",
            scores=BuilderAbilityScores.model_validate(
                build.ability_scores.model_dump(mode="python")
            ),
            provenance="legacy_resolved_build_import",
        ),
        level_choices=_legacy_level_choices(build, registry),
        spell_choices=_legacy_spell_choices(build, registry),
        roleplay_profile=build.roleplay_profile.model_dump(mode="json"),
        numeric_overrides=build.numeric_overrides,
        initial_state_seed={
            "p1g_legacy_import": True,
            "base_character_level": build.character_level,
        },
    )
    _seed_authoritative_race_variant_groups(payload, build)
    _seed_authoritative_artificer_infusions(payload, build)
    return payload


def seed_version_draft_payload(
    character: PersistedCharacter,
    registry: ContentRegistry,
    *,
    mode: BuilderMode,
    builder_provenance: object | None,
    stored_draft_payload: BuilderDraftPayload | None,
    state: CharacterState | None = None,
) -> BuilderDraftPayload:
    if mode is BuilderMode.CREATE:
        raise ValueError("version draft seeding does not apply to create mode")

    source_payload: BuilderDraftPayload | None = None
    if builder_provenance is not None:
        try:
            source_payload = BuilderDraftPayload.model_validate(builder_provenance)
        except ValidationError:
            logger.warning(
                "invalid builder_provenance for character %s version %s; falling back",
                character.id,
                character.current_version_id,
                exc_info=True,
            )
    if source_payload is None:
        source_payload = stored_draft_payload

    if source_payload is None:
        payload = legacy_payload_from_build(character, registry)
    else:
        payload = source_payload.model_copy(deep=True)
        payload.basic = BuilderBasicInput(
            name=character.name,
            ruleset=character.build.ruleset,
        )
        payload.target_level = character.build.character_level
        # Origin identity is authoritative Build data. New M01-M Builds also
        # carry group selections so a Build Edit can reconstruct Feral/Legacy
        # branches without reverse engineering resolved values.
        _seed_authoritative_race_variant_groups(payload, character.build)
        # Lineage is Build identity, not merely historical UI provenance. Always
        # seed the typed selector from the authoritative current Build so a
        # later Level Up / Build Edit cannot silently lose it if an older source
        # payload did not yet carry M01-F fields.
        payload.lineage_selection = _lineage_selection(character.build)
        # Starting equipment is creation provenance and live inventory has long
        # since diverged. P1-G preserves the immutable baseline instead of asking
        # the user to choose starting equipment again.
        payload.starting_equipment_choices = {}
        payload.initial_state_seed = {}
        _seed_authoritative_artificer_infusions(payload, character.build)

    # Prepared lists are Current State, not Build provenance. Keeping the create
    # draft's initial prepared choice here would incorrectly make a later live
    # preparation change look like a Build edit. Reconciliation validates the
    # actual Current State against the proposed new Build.
    payload.spell_choices = {
        profile_id: choice.model_copy(update={"prepared_spell_keys": ()})
        for profile_id, choice in payload.spell_choices.items()
    }

    if mode is BuilderMode.LEVEL_UP:
        if character.build.character_level >= 20:
            raise ValueError("a level 20 character cannot level up further")
        payload.target_level = character.build.character_level + 1
        payload.level_choices = tuple(
            payload.level_choices[: character.build.character_level]
        )
    else:
        payload.target_level = character.build.character_level
        payload.level_choices = tuple(
            payload.level_choices[: character.build.character_level]
        )

    return payload
