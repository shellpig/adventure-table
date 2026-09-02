from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.content import load_default_content_registry
from app.domain.character_builder.m01i_validation import validate_unique_feature_pool_selections
from app.domain.character_builder.m01j_runtime import prepare_m01j_subclasses
from app.domain.character_builder.schemas import (
    BuilderChoiceSelection,
    BuilderDraft,
    BuilderDraftPayload,
    BuilderLevelChoice,
    BuilderMode,
)
from app.domain.character_builder.structural import (
    build_structural_choices,
    compile_structural_selections,
)


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


def _payload(
    class_index: str,
    subclass_ref: str,
    *,
    target_level: int,
    acquisition_level: int,
    selections: dict[str, BuilderChoiceSelection] | None = None,
) -> BuilderDraftPayload:
    hit_die = {
        "bard": 8,
        "druid": 8,
        "fighter": 10,
        "ranger": 10,
        "sorcerer": 6,
    }[class_index]
    return BuilderDraftPayload(
        target_level=target_level,
        level_choices=tuple(
            BuilderLevelChoice(
                character_level=level,
                class_ref=f"srd5.1:class:{class_index}",
                hp_method="first_level" if level == 1 else "fixed_average",
                hp_base_gain=hit_die if level == 1 else hit_die // 2 + 1,
                subclass_ref=subclass_ref if level == acquisition_level else None,
            )
            for level in range(1, target_level + 1)
        ),
        choice_selections=selections or {},
    )


def _m01j_choice(runtime, suffix: str):
    return next(choice for choice in runtime.choices if choice.choice_id.endswith(suffix))


def _structural_choice(choices, source_ref: str):
    matches = [
        choice
        for choice in choices
        if choice.source_ref == source_ref
        and (choice.option_source or "").startswith("content:feature:")
    ]
    assert len(matches) == 1
    return matches[0]


def test_lore_canonical_identity_has_bonus_skills_and_magical_secrets() -> None:
    registry = load_default_content_registry()
    runtime = prepare_m01j_subclasses(
        _draft(
            _payload(
                "bard",
                "srd5.1:subclass:lore",
                target_level=6,
                acquisition_level=3,
            )
        ),
        registry,
    )
    skills = _m01j_choice(runtime, "lore-bonus-proficiencies")
    secrets = _m01j_choice(runtime, "additional-magical-secrets")
    assert skills.choose_count == 3
    assert secrets.choose_count == 2
    assert all(
        registry.get(option.option_id).data.get("level") in {0, 1, 2, 3}
        for option in secrets.options
    )


def test_land_choice_reuses_structural_feature_and_compiles_feature_ref() -> None:
    registry = load_default_content_registry()
    payload = _payload(
        "druid",
        "srd5.1:subclass:land",
        target_level=3,
        acquisition_level=2,
    )
    choices = build_structural_choices(_draft(payload), registry, starting_abilities=None)
    choice = _structural_choice(choices, "srd5.1:feature:circle-of-the-land")
    arctic = next(
        option
        for option in choice.options
        if option.option_id == "srd5.1:feature:circle-of-the-land-arctic"
    )
    selection = BuilderChoiceSelection(
        choice_id=choice.choice_id,
        source_ref=choice.source_ref,
        selected_option_ids=(arctic.option_id,),
    )
    selected_payload = payload.model_copy(
        update={"choice_selections": {choice.choice_id: selection}}
    )
    selected_draft = _draft(selected_payload)
    selected_choices = build_structural_choices(
        selected_draft,
        registry,
        starting_abilities=None,
    )
    compiled = compile_structural_selections(selected_draft, registry, selected_choices)
    assert arctic.option_id in compiled.feature_refs


def test_hunter_reuses_four_structural_persistent_choices() -> None:
    registry = load_default_content_registry()
    payload = _payload(
        "ranger",
        "srd5.1:subclass:hunter",
        target_level=15,
        acquisition_level=3,
    )
    choices = build_structural_choices(_draft(payload), registry, starting_abilities=None)
    expected = {
        "srd5.1:feature:hunters-prey": 3,
        "srd5.1:feature:defensive-tactics": 3,
        "srd5.1:feature:multiattack": 2,
        "srd5.1:feature:superior-hunters-defense": 3,
    }
    for source_ref, option_count in expected.items():
        choice = _structural_choice(choices, source_ref)
        assert choice.choose_count == 1
        assert len(choice.options) == option_count


def test_draconic_reuses_structural_ancestor_and_adds_fixed_language() -> None:
    registry = load_default_content_registry()
    subclass = registry.get("srd5.1:subclass:draconic")
    assert "srd5.1:language:draconic" in subclass.data["fixed_grants"]["languages"]
    payload = _payload(
        "sorcerer",
        "srd5.1:subclass:draconic",
        target_level=1,
        acquisition_level=1,
    )
    choices = build_structural_choices(_draft(payload), registry, starting_abilities=None)
    ancestor = _structural_choice(choices, "srd5.1:feature:dragon-ancestor")
    assert ancestor.choose_count == 1
    assert len(ancestor.options) == 10


def test_champion_second_style_shares_fighting_style_uniqueness_pool() -> None:
    registry = load_default_content_registry()
    payload = _payload(
        "fighter",
        "srd5.1:subclass:champion",
        target_level=10,
        acquisition_level=3,
    )
    draft = _draft(payload)
    runtime = prepare_m01j_subclasses(draft, registry)
    choice = _m01j_choice(runtime, "champion-additional-fighting-style")
    assert choice.choose_count == 1
    assert len(choice.options) >= 6
    for option in choice.options:
        spec = registry.get(option.option_id).data.get("choice_pool_option")
        assert isinstance(spec, dict)
        assert spec.get("pool") == "fighting-style"
        assert "srd5.1:class:fighter" in spec.get("eligible_class_refs", ())

    structural = build_structural_choices(draft, registry, starting_abilities=None)
    first_style = _structural_choice(structural, "srd5.1:feature:fighter-fighting-style")
    duplicate_ref = "srd5.1:feature:fighter-fighting-style-defense"
    selections = {
        first_style.choice_id: BuilderChoiceSelection(
            choice_id=first_style.choice_id,
            source_ref=first_style.source_ref,
            selected_option_ids=(duplicate_ref,),
        ),
        choice.choice_id: BuilderChoiceSelection(
            choice_id=choice.choice_id,
            source_ref=choice.source_ref,
            selected_option_ids=(duplicate_ref,),
        ),
    }
    selected_draft = _draft(payload.model_copy(update={"choice_selections": selections}))
    selected_structural = build_structural_choices(
        selected_draft,
        registry,
        starting_abilities=None,
    )
    selected_runtime = prepare_m01j_subclasses(selected_draft, registry)
    issues = validate_unique_feature_pool_selections(
        selected_draft,
        tuple((*selected_structural, *selected_runtime.choices)),
        registry,
    )
    assert any(issue.code == "duplicate_optional_pool_selection" for issue in issues)
