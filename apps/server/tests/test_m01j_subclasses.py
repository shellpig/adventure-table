from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.content import load_default_content_registry
from app.content.localization import SUPPORTED_CONTENT_LOCALES
from app.content.localization_files import load_content_localization_catalog
from app.content.m01j_inventory import m01j_inventory_summary
from app.content.registry import CONTENT_PACKS_ROOT
from app.domain.character_builder.equipment import compile_starting_equipment
from app.domain.character_builder.m01i_compiler import compile_builder_draft
from app.domain.character_builder.m01j_subclasses import prepare_m01j_subclasses
from app.domain.character_builder.progression import progression_summary
from app.domain.character_builder.schemas import (
    BuilderBasicInput,
    BuilderChoiceSelection,
    BuilderDraft,
    BuilderDraftPayload,
    BuilderLevelChoice,
    BuilderMode,
    BuilderReferenceSelection,
    BuilderSpellChoiceInput,
)


DIRECT_SOURCES = {
    "content:race",
    "content:background",
    "content:alignment",
    "content:subrace",
    "content:class",
    "content:subclass",
    "builder:ability-generation",
    "equipment",
}


def _draft(payload: BuilderDraftPayload) -> BuilderDraft:
    now = datetime.now(UTC)
    return BuilderDraft(
        id=uuid4(),
        mode=BuilderMode.CREATE,
        revision=1,
        draft_payload=payload,
        created_at=now,
        updated_at=now,
    )


def _level(
    character_level: int,
    class_index: str,
    *,
    subclass_ref: str | None = None,
) -> BuilderLevelChoice:
    hit_die = {
        "barbarian": 12,
        "bard": 8,
        "cleric": 8,
        "druid": 8,
        "fighter": 10,
        "monk": 8,
        "paladin": 10,
        "ranger": 10,
        "rogue": 8,
        "sorcerer": 6,
        "warlock": 8,
        "wizard": 6,
    }[class_index]
    return BuilderLevelChoice(
        character_level=character_level,
        class_ref=f"srd5.1:class:{class_index}",
        hp_method="first_level" if character_level == 1 else "fixed_average",
        hp_base_gain=hit_die if character_level == 1 else hit_die // 2 + 1,
        subclass_ref=subclass_ref,
    )


def _payload_for_subclass(class_index: str, subclass_ref: str, timing: int) -> BuilderDraftPayload:
    levels = tuple(
        _level(
            character_level,
            class_index,
            subclass_ref=subclass_ref if character_level == timing else None,
        )
        for character_level in range(1, timing + 1)
    )
    return BuilderDraftPayload(
        basic=BuilderBasicInput(name=f"M01-J {class_index}"),
        target_level=timing,
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


def _spell_choices(result) -> dict[str, BuilderSpellChoiceInput]:
    choices: dict[str, BuilderSpellChoiceInput] = {}
    for profile in result.resolved_summary.spellcasting_profiles:
        cantrips = tuple(
            spell.spell_key for spell in profile.available_spells if spell.level == 0
        )[: profile.cantrip_count]
        leveled = tuple(
            spell.spell_key
            for spell in profile.available_spells
            if 1 <= spell.level <= profile.max_spell_level
        )
        choices[profile.profile_id] = BuilderSpellChoiceInput(
            cantrip_keys=cantrips,
            known_spell_keys=leveled[: profile.known_spell_count],
            spellbook_spell_keys=leveled[: profile.spellbook_count],
            prepared_spell_keys=(),
        )
    return choices


def _complete_starting_equipment(payload: BuilderDraftPayload, registry) -> BuilderDraftPayload:
    """Resolve the real starting-equipment channel before generic builder choices."""

    selections = dict(payload.starting_equipment_choices)
    for _ in range(80):
        current = payload.model_copy(update={"starting_equipment_choices": selections})
        result = compile_starting_equipment(_draft(current), registry)
        unresolved = next(
            (
                choice
                for choice in result.choices
                if choice.required
                and choice.disabled_reason is None
                and choice.choice_id not in selections
            ),
            None,
        )
        if unresolved is None:
            return current

        available = [
            option for option in unresolved.options if option.disabled_reason is None
        ]
        assert len(available) >= unresolved.choose_count, unresolved.choice_id
        if unresolved.allow_duplicates:
            selected = [available[0].option_id for _ in range(unresolved.choose_count)]
        else:
            selected = [
                option.option_id for option in available[: unresolved.choose_count]
            ]
        selections[unresolved.choice_id] = selected
    raise AssertionError("M01-J starting equipment choices did not converge")


def _complete_required_choices(payload: BuilderDraftPayload, registry) -> BuilderDraft:
    payload = _complete_starting_equipment(payload, registry)
    selections = dict(payload.choice_selections)
    for _ in range(160):
        current = payload.model_copy(update={"choice_selections": selections})
        result = compile_builder_draft(_draft(current), registry)
        unresolved = next(
            (
                choice
                for choice in result.choices
                if choice.required
                and choice.disabled_reason is None
                and choice.option_source not in DIRECT_SOURCES
                and choice.choice_id not in selections
            ),
            None,
        )
        if unresolved is None:
            spell_choices = dict(current.spell_choices)
            for profile_id, selection in _spell_choices(result).items():
                spell_choices.setdefault(profile_id, selection)
            return _draft(current.model_copy(update={"spell_choices": spell_choices}))

        available = [
            option for option in unresolved.options if option.disabled_reason is None
        ]
        assert len(available) >= unresolved.choose_count, unresolved.choice_id
        if unresolved.allow_duplicates:
            selected = tuple(available[0].option_id for _ in range(unresolved.choose_count))
        else:
            selected = tuple(
                option.option_id for option in available[: unresolved.choose_count]
            )
        selections[unresolved.choice_id] = BuilderChoiceSelection(
            choice_id=unresolved.choice_id,
            source_ref=unresolved.source_ref,
            selected_option_ids=selected,
        )
    raise AssertionError("M01-J required choices did not converge")


def test_m01j_inventory_is_fully_accounted_without_data_blockers() -> None:
    registry = load_default_content_registry()
    summary = m01j_inventory_summary(registry)
    assert summary["expected"] == 112
    assert summary["implemented"] == 95
    assert summary["canonical_duplicates"] == 17
    assert summary["data_blockers"] == 0
    assert summary["sources"] == {"phb2014": 40, "scag": 11, "xge": 31, "tce": 30}


def test_m01j_reprints_have_one_canonical_builder_identity() -> None:
    registry = load_default_content_registry()
    mappings = {
        "scag:subclass:sun-soul": "xge:subclass:sun-soul",
        "scag:subclass:mastermind": "xge:subclass:mastermind",
        "scag:subclass:swashbuckler": "xge:subclass:swashbuckler",
        "scag:subclass:storm-sorcery": "xge:subclass:storm-sorcery",
        "scag:subclass:bladesinging": "tce:subclass:bladesinging",
    }
    for source_ref, canonical_ref in mappings.items():
        assert registry.get_optional(source_ref) is None
        assert registry.get(canonical_ref).key == canonical_ref


def test_m01j_generated_names_are_bilingual_complete() -> None:
    registry = load_default_content_registry()
    catalog = load_content_localization_catalog(registry, CONTENT_PACKS_ROOT)
    issues = catalog.completeness_issues(
        locales=SUPPORTED_CONTENT_LOCALES,
        sources={"phb2014", "scag", "xge", "tce"},
        kinds={"subclass", "feature"},
    )
    assert not issues, "\n".join(
        f"{issue.key} :: {issue.field_path} :: {issue.locale} :: {issue.reason}"
        for issue in issues
    )


@pytest.mark.parametrize(
    ("class_index", "subclass_ref", "timing"),
    (
        ("barbarian", "phb2014:subclass:totem-warrior", 3),
        ("bard", "phb2014:subclass:valor", 3),
        ("cleric", "phb2014:subclass:light", 1),
        ("druid", "phb2014:subclass:moon", 2),
        ("fighter", "phb2014:subclass:battle-master", 3),
        ("monk", "phb2014:subclass:shadow", 3),
        ("paladin", "phb2014:subclass:vengeance", 3),
        ("ranger", "phb2014:subclass:beast-master", 3),
        ("rogue", "phb2014:subclass:assassin", 3),
        ("sorcerer", "phb2014:subclass:wild-magic", 1),
        ("warlock", "phb2014:subclass:archfey", 1),
        ("wizard", "phb2014:subclass:divination", 2),
    ),
)
def test_every_phb_class_has_a_non_srd_subclass_compile_path(
    class_index: str,
    subclass_ref: str,
    timing: int,
) -> None:
    registry = load_default_content_registry()
    draft = _complete_required_choices(
        _payload_for_subclass(class_index, subclass_ref, timing),
        registry,
    )
    result = compile_builder_draft(draft, registry)
    assert result.build_candidate is not None
    assert any(
        selection.subclass_ref == subclass_ref
        for selection in result.build_candidate.subclasses
    )
    blocking = [issue for issue in result.validation.issues if issue.severity == "blocking_error"]
    assert not blocking, "\n".join(f"{issue.code}: {issue.message}" for issue in blocking)


def test_gloom_stalker_grants_source_aware_subclass_spells() -> None:
    registry = load_default_content_registry()
    payload = _payload_for_subclass("ranger", "xge:subclass:gloom-stalker", 3)
    runtime = prepare_m01j_subclasses(_draft(payload), registry)
    assert runtime.spell_access_entries
    assert all(entry.source_key == "xge:subclass:gloom-stalker" for entry in runtime.spell_access_entries)
    assert all(entry.access_type == "granted" for entry in runtime.spell_access_entries)


def test_warlock_patron_expands_spell_pool_without_auto_granting() -> None:
    registry = load_default_content_registry()
    payload = _payload_for_subclass("warlock", "phb2014:subclass:great-old-one", 1)
    runtime = prepare_m01j_subclasses(_draft(payload), registry)
    assert not runtime.spell_access_entries
    subclass = registry.get("phb2014:subclass:great-old-one")
    expanded = subclass.data.get("expanded_spells")
    assert isinstance(expanded, list) and expanded
    spell_ref = expanded[0]["spell"]["key"]
    overlaid = runtime.registry.get(spell_ref)
    class_refs = {reference.get("key") for reference in overlaid.data.get("classes", [])}
    assert "srd5.1:class:warlock" in class_refs


def test_resource_heavy_subclass_feature_uses_generic_resource_descriptor() -> None:
    registry = load_default_content_registry()
    samurai = registry.get("xge:subclass:samurai")
    resource_refs = samurai.data.get("resource_feature_refs")
    assert isinstance(resource_refs, list) and resource_refs
    assert any(registry.get(ref).data.get("resource") for ref in resource_refs)


def test_multiclass_subclass_threshold_uses_class_level_not_character_level() -> None:
    registry = load_default_content_registry()
    levels = (
        _level(1, "fighter"),
        _level(2, "fighter"),
        *tuple(_level(character_level, "wizard") for character_level in range(3, 13)),
        _level(13, "fighter", subclass_ref="phb2014:subclass:battle-master"),
    )
    payload = BuilderDraftPayload(target_level=13, level_choices=levels)
    nodes = progression_summary(_draft(payload), registry)
    fighter_nodes = [node for node in nodes if node.class_ref == "srd5.1:class:fighter"]
    assert [node.class_level for node in fighter_nodes] == [1, 2, 3]
    assert fighter_nodes[1].subclass_ref is None
    assert fighter_nodes[2].subclass_ref == "phb2014:subclass:battle-master"
