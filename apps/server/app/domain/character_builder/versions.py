from __future__ import annotations

from collections import Counter
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.content.registry import ContentRegistry
from app.domain.character.schemas import CharacterBuild, CharacterState, PersistedCharacter
from app.domain.character_builder.progression import fixed_hp_gain, subclass_selection_level
from app.domain.character_builder.schemas import (
    BuilderAbilityGenerationInput,
    BuilderAbilityScores,
    BuilderBasicInput,
    BuilderDraftPayload,
    BuilderHPMethod,
    BuilderLevelChoice,
    BuilderMode,
    BuilderReferenceSelection,
    BuilderSpellChoiceInput,
)


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
        hit_die = class_entry.data.get("hit_die")
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
    return BuilderDraftPayload(
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


def seed_version_draft_payload(
    character: PersistedCharacter,
    registry: ContentRegistry,
    *,
    mode: BuilderMode,
    source_payload: BuilderDraftPayload | None,
    state: CharacterState | None = None,
) -> BuilderDraftPayload:
    if mode is BuilderMode.CREATE:
        raise ValueError("version draft seeding does not apply to create mode")

    if source_payload is None:
        payload = legacy_payload_from_build(character, registry)
    else:
        payload = source_payload.model_copy(deep=True)
        payload.basic = BuilderBasicInput(
            name=character.name,
            ruleset=character.build.ruleset,
        )
        payload.target_level = character.build.character_level
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
