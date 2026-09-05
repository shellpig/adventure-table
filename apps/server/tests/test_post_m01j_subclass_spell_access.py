"""One subclass spell record must produce one spell access entry.

Subclass spell grants have two producers: the pre-M01-J path in
`spellcasting._subclass_spell_access`, which reads the SRD record shape (no
`access_type`, feature prerequisites), and the M01-J path in
`m01j_subclasses`, which reads the expansion record shape (explicit
`access_type`, option refs, choice gating). Every dedup between them keys on
`entry_id`, and the two mint different ids, so a record both accept reaches the
character sheet twice.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.content import load_default_content_registry
from app.content.identity import reference_to_stable_key
from app.domain.character_builder.m01j_extension import prepare_m01j_subclasses
from app.domain.character_builder.schemas import (
    BuilderBasicInput,
    BuilderDraft,
    BuilderDraftPayload,
    BuilderLevelChoice,
    BuilderMode,
    BuilderReferenceSelection,
)
from app.domain.character_builder.spellcasting import compile_spellcasting


MAX_LEVEL = 20


def _draft(class_ref: str, subclass_ref: str) -> BuilderDraft:
    levels = tuple(
        BuilderLevelChoice(
            character_level=character_level,
            class_ref=class_ref,
            hp_method="first_level" if character_level == 1 else "fixed_average",
            hp_base_gain=8 if character_level == 1 else 5,
            subclass_ref=subclass_ref if character_level == 1 else None,
        )
        for character_level in range(1, MAX_LEVEL + 1)
    )
    payload = BuilderDraftPayload(
        basic=BuilderBasicInput(name="subclass spell access"),
        target_level=MAX_LEVEL,
        race_selection=BuilderReferenceSelection(reference_id="srd5.1:race:human"),
        background_selection=BuilderReferenceSelection(reference_id="srd5.1:background:acolyte"),
        ability_generation={
            "method": "standard_array",
            "scores": {
                "strength": 15,
                "dexterity": 14,
                "constitution": 13,
                "intelligence": 12,
                "wisdom": 10,
                "charisma": 8,
            },
        },
        level_choices=levels,
    )
    now = datetime.now(UTC)
    return BuilderDraft(
        id=uuid4(),
        mode=BuilderMode.CREATE,
        revision=1,
        draft_payload=payload,
        created_at=now,
        updated_at=now,
    )


def _producer_grants(registry, subclass_entry) -> tuple[dict, dict]:
    parent = subclass_entry.data.get("class")
    assert isinstance(parent, dict), subclass_entry.key
    class_ref = reference_to_stable_key(parent, kinds={"class"})
    assert class_ref is not None, subclass_entry.key

    draft = _draft(class_ref, subclass_entry.key)
    runtime = prepare_m01j_subclasses(draft, registry)
    expansion = {
        entry.spell_key: entry.access_type
        for entry in runtime.base.spell_access_entries
        if entry.source_key == subclass_entry.key
    }
    compilation = compile_spellcasting(
        draft,
        registry,
        effective_abilities=None,
        feature_refs=tuple(runtime.fixed_feature_refs),
    )
    legacy = {
        entry.spell_key: entry.access_type
        for entry in compilation.spell_access_entries
        if entry.source_type == "subclass" and entry.source_key == subclass_entry.key
    }
    return legacy, expansion


def _subclasses_with_spells(registry) -> list:
    return [
        entry
        for entry in registry.list_kind("subclass")
        if isinstance(entry.data.get("spells"), list) and entry.data["spells"]
    ]


def test_no_subclass_spell_is_granted_by_both_producers() -> None:
    registry = load_default_content_registry()
    subclasses = _subclasses_with_spells(registry)
    assert subclasses, "the installed packs must expose subclass spell records"

    overlaps: dict[str, list[str]] = {}
    for subclass_entry in subclasses:
        legacy, expansion = _producer_grants(registry, subclass_entry)
        shared = sorted(set(legacy) & set(expansion))
        if shared:
            overlaps[subclass_entry.key] = shared

    assert not overlaps, (
        "these subclass spells reach the build from both the legacy and the M01-J "
        f"producer, so the sheet lists each of them twice: {overlaps}"
    )


def test_each_record_shape_reaches_only_its_own_producer() -> None:
    registry = load_default_content_registry()
    covered = 0
    legacy_grants = 0
    expansion_grants = 0
    for subclass_entry in _subclasses_with_spells(registry):
        legacy, expansion = _producer_grants(registry, subclass_entry)
        declares_access_type = {
            record.get("access_type")
            for record in subclass_entry.data["spells"]
            if isinstance(record, dict)
        } != {None}
        if declares_access_type:
            assert not legacy, f"the legacy producer must not re-grant {subclass_entry.key}"
            expansion_grants += len(expansion)
        else:
            assert not expansion, f"M01-J must not claim SRD records for {subclass_entry.key}"
            legacy_grants += len(legacy)
        covered += 1

    assert covered >= 30, "the sweep must cover the installed subclass spell lists"
    # The synthetic draft answers no subclass choices, so a subclass whose
    # grants hang off one (Circle of the Land's terrain, Divine Soul's affinity)
    # legitimately produces nothing here. Assert each producer still carries its
    # own record shape in aggregate rather than for every single subclass.
    assert legacy_grants >= 20, "the legacy producer must still serve SRD records"
    assert expansion_grants >= 100, "M01-J must still serve expansion records"


def test_artillerist_grants_shield_and_thunderwave_once_each() -> None:
    registry = load_default_content_registry()
    subclass_entry = registry.get("tce:subclass:artillerist")
    legacy, expansion = _producer_grants(registry, subclass_entry)

    grants = {**legacy, **expansion}
    assert grants.get("srd5.1:spell:shield") == "always_prepared"
    assert grants.get("srd5.1:spell:thunderwave") == "always_prepared"
    assert not set(legacy) & set(expansion)
