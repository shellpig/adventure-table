from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.content import load_default_content_registry
from app.content.localization_files import load_content_localization_catalog
from app.content.registry import CONTENT_PACKS_ROOT
from app.domain.character.schemas import (
    AbilityScores,
    AncestralLegacySelection,
    CharacterBuild,
    CharacterState,
    PersistedCharacter,
)
from app.domain.character_builder.lineages import (
    ASI_PATTERN_2_1,
    LINEAGE_ASI_PATTERN_CHOICE_ID,
    LINEAGE_ASI_PLUS_ONE_CHOICE_ID,
    LINEAGE_ASI_PLUS_TWO_CHOICE_ID,
    LINEAGE_LANGUAGE_CHOICE_ID,
    LINEAGE_MOVEMENT_CHOICE_ID,
    LINEAGE_SIZE_CHOICE_ID,
    LINEAGE_SKILL_CHOICE_ID,
    build_lineage_choices,
    compile_lineage,
    eligible_ancestral_skills,
)
from app.domain.character_builder.schemas import (
    BuilderChoiceSelection,
    BuilderDraft,
    BuilderDraftPayload,
    BuilderMode,
    BuilderReferenceSelection,
)
from app.domain.character_builder.structural import validate_structural_choice_integrity
from app.domain.character_builder.versions import (
    legacy_payload_from_build,
    seed_version_draft_payload,
)
from app.domain.rules.feature_resources import feature_resource_capacities


DHAMPIR = "vrgr:lineage:dhampir"
DARKVISION = "vrgr:feature:dhampir-darkvision"
DEATHLESS_NATURE = "vrgr:feature:deathless-nature"
SPIDER_CLIMB = "vrgr:feature:spider-climb"
VAMPIRIC_BITE = "vrgr:feature:vampiric-bite"
HALF_ELF = "srd5.1:race:half-elf"
FIGHTER = "srd5.1:class:fighter"
COMMON = "srd5.1:language:common"
ELVISH = "srd5.1:language:elvish"
PERCEPTION = "srd5.1:skill:perception"
STEALTH = "srd5.1:skill:stealth"
ARCANA = "srd5.1:skill:arcana"
SKILL_VERSATILITY = "srd5.1:trait:skill-versatility"
PERCEPTION_PROFICIENCY = "srd5.1:proficiency:skill-perception"


def _selection(
    choice_id: str,
    *option_ids: str,
    source_ref: str | None = DHAMPIR,
) -> BuilderChoiceSelection:
    return BuilderChoiceSelection(
        choice_id=choice_id,
        source_ref=source_ref,
        selected_option_ids=tuple(option_ids),
    )


def _draft(
    *,
    mode: BuilderMode = BuilderMode.CREATE,
    target_level: int = 1,
    lineage_ref: str | None = DHAMPIR,
    selections: dict[str, BuilderChoiceSelection] | None = None,
) -> BuilderDraft:
    now = datetime.now(UTC)
    versioned = mode is not BuilderMode.CREATE
    return BuilderDraft(
        id=uuid4(),
        mode=mode,
        character_id=uuid4() if versioned else None,
        base_version_id=uuid4() if versioned else None,
        revision=1,
        draft_payload=BuilderDraftPayload(
            target_level=target_level,
            race_selection=BuilderReferenceSelection(reference_id=HALF_ELF),
            lineage_selection=(
                BuilderReferenceSelection(reference_id=lineage_ref)
                if lineage_ref is not None
                else None
            ),
            choice_selections=selections or {},
        ),
        created_at=now,
        updated_at=now,
    )


def _base_build(
    *,
    level: int = 1,
    lineage: bool = False,
    skill_choices: tuple[str, ...] = (PERCEPTION, ARCANA),
    fly_speed: int | None = 50,
) -> CharacterBuild:
    return CharacterBuild(
        race_ref=HALF_ELF,
        lineage_ref=DHAMPIR if lineage else None,
        ancestral_origin_ref=HALF_ELF if lineage else None,
        ancestral_legacy=(
            AncestralLegacySelection(retained_skill_refs=(PERCEPTION,))
            if lineage
            else None
        ),
        size="medium" if lineage else None,
        character_level=level,
        class_progression=tuple(FIGHTER for _ in range(level)),
        ability_scores=AbilityScores(
            strength=14,
            dexterity=14,
            constitution=14,
            intelligence=10,
            wisdom=12,
            charisma=10,
        ),
        skill_choices=skill_choices,
        language_refs=(COMMON, ELVISH),
        feature_refs=(VAMPIRIC_BITE,) if lineage else (),
        walking_speed=35 if lineage else 30,
        climb_speed=35 if lineage else 20,
        fly_speed=fly_speed,
        hp_progression=tuple(10 if index == 0 else 6 for index in range(level)),
    )


def _direct_lineage_selections() -> dict[str, BuilderChoiceSelection]:
    return {
        LINEAGE_ASI_PATTERN_CHOICE_ID: _selection(
            LINEAGE_ASI_PATTERN_CHOICE_ID,
            ASI_PATTERN_2_1,
        ),
        LINEAGE_ASI_PLUS_TWO_CHOICE_ID: _selection(
            LINEAGE_ASI_PLUS_TWO_CHOICE_ID,
            "lineage-ability:con:2",
        ),
        LINEAGE_ASI_PLUS_ONE_CHOICE_ID: _selection(
            LINEAGE_ASI_PLUS_ONE_CHOICE_ID,
            "lineage-ability:cha:1",
        ),
        LINEAGE_SIZE_CHOICE_ID: _selection(
            LINEAGE_SIZE_CHOICE_ID,
            "lineage-size:medium",
        ),
        LINEAGE_LANGUAGE_CHOICE_ID: _selection(
            LINEAGE_LANGUAGE_CHOICE_ID,
            ELVISH,
        ),
        LINEAGE_SKILL_CHOICE_ID: _selection(
            LINEAGE_SKILL_CHOICE_ID,
            PERCEPTION,
            STEALTH,
        ),
    }


def test_f1_dhampir_content_has_machine_readable_core_and_bite_contract() -> None:
    registry = load_default_content_registry()
    lineage = registry.get(DHAMPIR)
    bite = registry.get(VAMPIRIC_BITE)

    assert lineage.data["creature_type"] == "humanoid"
    assert lineage.data["sizes"] == ["medium", "small"]
    assert lineage.data["walking_speed"] == 35
    assert lineage.data["climb_speed"] == 35
    assert lineage.data["ability_score_patterns"] == [[2, 1], [1, 1, 1]]

    weapon = bite.data["natural_weapon"]
    assert weapon["attack_ability"] == "constitution"
    assert weapon["damage_ability"] == "constitution"
    assert weapon["damage_dice"] == "1d4"
    assert weapon["damage_type"] == "piercing"
    assert weapon["advantage_condition"]["self_hp_at_or_below_half_max"] is True
    assert bite.data["invalid_target_creature_types"] == ["construct", "undead"]
    assert bite.data["resource"] == {
        "capacity": {"type": "proficiency_bonus"},
        "recharge": ["long_rest"],
    }


def test_f2_f7_direct_create_choices_and_spider_climb_level_gate() -> None:
    registry = load_default_content_registry()
    draft = _draft(selections=_direct_lineage_selections())
    choices = build_lineage_choices(draft, registry)
    compiled = compile_lineage(draft, registry)

    assert not validate_structural_choice_integrity(draft, choices)
    assert compiled.size == "medium"
    assert compiled.ancestral_origin_ref is None
    assert compiled.ancestral_legacy is not None
    assert set(compiled.ancestral_legacy.retained_skill_refs) == {PERCEPTION, STEALTH}
    assert compiled.language_refs == (COMMON, ELVISH)
    assert compiled.walking_speed == 35
    assert compiled.climb_speed == 35
    assert {DARKVISION, DEATHLESS_NATURE, VAMPIRIC_BITE}.issubset(
        set(compiled.feature_refs)
    )
    assert SPIDER_CLIMB not in compiled.feature_refs

    level_three = draft.model_copy(
        update={
            "draft_payload": draft.draft_payload.model_copy(update={"target_level": 3})
        }
    )
    assert SPIDER_CLIMB in compile_lineage(level_three, registry).feature_refs


def test_f2_server_blocks_same_ability_for_plus_two_and_plus_one() -> None:
    registry = load_default_content_registry()
    selections = _direct_lineage_selections()
    selections[LINEAGE_ASI_PLUS_ONE_CHOICE_ID] = _selection(
        LINEAGE_ASI_PLUS_ONE_CHOICE_ID,
        "lineage-ability:con:1",
    )
    draft = _draft(selections=selections)
    choices = build_lineage_choices(draft, registry)

    issues = validate_structural_choice_integrity(draft, choices)
    assert any(issue.code == "disabled_choice_option_selected" for issue in issues)


def test_f4_f5_existing_transformation_only_offers_race_origin_skills_and_movement() -> None:
    registry = load_default_content_registry()
    base = _base_build()
    selections = {
        "legacy:skill-versatility": _selection(
            "legacy:skill-versatility",
            PERCEPTION_PROFICIENCY,
            source_ref=SKILL_VERSATILITY,
        ),
        LINEAGE_SIZE_CHOICE_ID: _selection(
            LINEAGE_SIZE_CHOICE_ID,
            "lineage-size:medium",
        ),
        LINEAGE_SKILL_CHOICE_ID: _selection(
            LINEAGE_SKILL_CHOICE_ID,
            PERCEPTION,
        ),
        LINEAGE_MOVEMENT_CHOICE_ID: _selection(
            LINEAGE_MOVEMENT_CHOICE_ID,
            "lineage-movement:fly",
        ),
    }
    draft = _draft(mode=BuilderMode.BUILD_EDIT, selections=selections)

    assert eligible_ancestral_skills(draft, registry, base) == (PERCEPTION,)
    compiled = compile_lineage(draft, registry, base_build=base)
    assert not compiled.issues
    assert compiled.ancestral_origin_ref == HALF_ELF
    assert compiled.language_refs == base.language_refs
    assert compiled.skill_refs == (PERCEPTION,)
    assert compiled.walking_speed == 35
    assert compiled.climb_speed == 35
    assert compiled.fly_speed == 50

    malicious = dict(selections)
    malicious[LINEAGE_SKILL_CHOICE_ID] = _selection(
        LINEAGE_SKILL_CHOICE_ID,
        ARCANA,
    )
    rejected = compile_lineage(
        _draft(mode=BuilderMode.BUILD_EDIT, selections=malicious),
        registry,
        base_build=base,
    )
    assert any(issue.code == "illegal_ancestral_legacy_skill" for issue in rejected.issues)


def test_f8_bite_proficiency_bonus_resource_scales_with_character_level() -> None:
    registry = load_default_content_registry()
    level_one = _base_build(lineage=True, level=1)
    level_five = _base_build(lineage=True, level=5)

    assert feature_resource_capacities(level_one, registry)[
        f"feature:{VAMPIRIC_BITE}"
    ] == 2
    assert feature_resource_capacities(level_five, registry)[
        f"feature:{VAMPIRIC_BITE}"
    ] == 3


def test_f3_version_seeding_preserves_authoritative_lineage_identity() -> None:
    registry = load_default_content_registry()
    build = _base_build(lineage=True)
    character = PersistedCharacter(
        id=uuid4(),
        name="Dhampir Test",
        ruleset=build.ruleset,
        current_version_id=uuid4(),
        version_no=2,
        build=build,
        state=CharacterState(current_hp=12),
    )

    legacy = legacy_payload_from_build(character, registry)
    assert legacy.lineage_selection is not None
    assert legacy.lineage_selection.reference_id == DHAMPIR

    stale_payload = legacy.model_copy(update={"lineage_selection": None})
    seeded = seed_version_draft_payload(
        character,
        registry,
        mode=BuilderMode.BUILD_EDIT,
        source_payload=stale_payload,
        state=character.state,
    )
    assert seeded.lineage_selection is not None
    assert seeded.lineage_selection.reference_id == DHAMPIR


def test_level_up_cannot_add_remove_or_replace_lineage() -> None:
    registry = load_default_content_registry()
    base = _base_build(lineage=True)
    draft = _draft(
        mode=BuilderMode.LEVEL_UP,
        target_level=2,
        lineage_ref=None,
    )

    compiled = compile_lineage(draft, registry, base_build=base)
    assert any(issue.code == "level_up_lineage_changed" for issue in compiled.issues)


def test_m01f_lineage_name_is_required_bilingual_presentation() -> None:
    registry = load_default_content_registry()
    catalog = load_content_localization_catalog(registry, CONTENT_PACKS_ROOT)

    issues = catalog.completeness_issues(
        locales=("zh-TW", "en"),
        sources={"vrgr"},
        kinds={"lineage"},
    )
    assert issues == ()
    assert catalog.policy.is_required("vrgr", "lineage", "name", "zh-TW")
    localized = catalog.resolve_name(DHAMPIR, "zh-TW")
    assert localized.missing_required is False
    assert localized.fallback_used is False
    assert localized.value == "達姆匹爾"
