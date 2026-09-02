from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.content import load_default_content_registry
from app.domain.character_builder.m01j_runtime import prepare_m01j_subclasses
from app.domain.character_builder.schemas import (
    BuilderChoiceSelection,
    BuilderDraft,
    BuilderDraftPayload,
    BuilderLevelChoice,
    BuilderMode,
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


def _choice(runtime, suffix: str):
    return next(choice for choice in runtime.choices if choice.choice_id.endswith(suffix))


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
    skills = _choice(runtime, "lore-bonus-proficiencies")
    secrets = _choice(runtime, "additional-magical-secrets")
    assert skills.choose_count == 3
    assert secrets.choose_count == 2
    assert all(
        registry.get(option.option_id).data.get("level") in {0, 1, 2, 3}
        for option in secrets.options
    )


def test_land_choice_uses_existing_srd_feature_prerequisite_identity() -> None:
    registry = load_default_content_registry()
    runtime = prepare_m01j_subclasses(
        _draft(
            _payload(
                "druid",
                "srd5.1:subclass:land",
                target_level=3,
                acquisition_level=2,
            )
        ),
        registry,
    )
    choice = _choice(runtime, "circle-of-the-land-terrain")
    arctic = next(
        option for option in choice.options if option.option_id == "srd5.1:feature:circle-of-the-land-arctic"
    )
    selected = {
        choice.choice_id: BuilderChoiceSelection(
            choice_id=choice.choice_id,
            source_ref=choice.source_ref,
            selected_option_ids=(arctic.option_id,),
        )
    }
    selected_runtime = prepare_m01j_subclasses(
        _draft(
            _payload(
                "druid",
                "srd5.1:subclass:land",
                target_level=3,
                acquisition_level=2,
                selections=selected,
            )
        ),
        registry,
    )
    assert arctic.option_id in selected_runtime.base.base.selected_option_feature_refs


def test_hunter_has_four_server_authoritative_persistent_choices() -> None:
    registry = load_default_content_registry()
    runtime = prepare_m01j_subclasses(
        _draft(
            _payload(
                "ranger",
                "srd5.1:subclass:hunter",
                target_level=15,
                acquisition_level=3,
            )
        ),
        registry,
    )
    expected = {
        "hunters-prey": 3,
        "defensive-tactics": 3,
        "multiattack": 2,
        "superior-hunters-defense": 3,
    }
    for suffix, option_count in expected.items():
        choice = _choice(runtime, suffix)
        assert choice.choose_count == 1
        assert len(choice.options) == option_count


def test_draconic_has_one_of_ten_ancestors_and_fixed_draconic_language() -> None:
    registry = load_default_content_registry()
    subclass = registry.get("srd5.1:subclass:draconic")
    assert "srd5.1:language:draconic" in subclass.data["fixed_grants"]["languages"]
    runtime = prepare_m01j_subclasses(
        _draft(
            _payload(
                "sorcerer",
                "srd5.1:subclass:draconic",
                target_level=1,
                acquisition_level=1,
            )
        ),
        registry,
    )
    ancestor = _choice(runtime, "dragon-ancestor")
    assert ancestor.choose_count == 1
    assert len(ancestor.options) == 10


def test_champion_second_style_shares_fighting_style_uniqueness_pool() -> None:
    registry = load_default_content_registry()
    runtime = prepare_m01j_subclasses(
        _draft(
            _payload(
                "fighter",
                "srd5.1:subclass:champion",
                target_level=10,
                acquisition_level=3,
            )
        ),
        registry,
    )
    choice = _choice(runtime, "champion-additional-fighting-style")
    assert choice.choose_count == 1
    assert len(choice.options) >= 6
    for option in choice.options:
        spec = registry.get(option.option_id).data.get("choice_pool_option")
        assert isinstance(spec, dict)
        assert spec.get("pool") == "fighting-style"
        assert "srd5.1:class:fighter" in spec.get("eligible_class_refs", ())
