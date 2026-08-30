from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.content.registry import DEFAULT_CONTENT_ROOT, ContentRegistry
from app.domain.character.schemas import AbilityScores, CharacterBuild
from app.domain.character_builder.choices import build_foundation_choices
from app.domain.character_builder.compiler import _with_derived_content_sources
from app.domain.character_builder.schemas import BuilderDraft
from app.domain.character_builder.validation import validate_foundation_draft


def _draft_with_disallowed_background() -> BuilderDraft:
    now = datetime.now(timezone.utc)
    return BuilderDraft.model_validate(
        {
            "id": uuid4(),
            "mode": "create",
            "revision": 1,
            "draft_payload": {
                "basic": {"name": "Source Policy Test", "ruleset": "dnd5e-2014"},
                "target_level": 1,
                "race_selection": {"reference_id": "srd5.1:race:human"},
                "background_selection": {"reference_id": "pack-a:background:test-background"},
                "ability_generation": {
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
            },
            "created_at": now,
            "updated_at": now,
        }
    )


def test_builder_blocks_reference_from_pack_outside_enabled_registry() -> None:
    registry = ContentRegistry.from_directory(DEFAULT_CONTENT_ROOT)
    draft = _draft_with_disallowed_background()

    choices = build_foundation_choices(draft, registry)
    background_choice = next(
        choice for choice in choices if choice.option_source == "content:background"
    )

    assert registry.enabled_pack_ids == ("srd5.1",)
    assert "pack-a:background:test-background" not in {
        option.option_id for option in background_choice.options
    }

    issues = validate_foundation_draft(draft, registry, choices)
    assert any(
        issue.code == "unknown_reference"
        and issue.path == "draft_payload.background_selection.reference_id"
        and issue.related_refs == ("pack-a:background:test-background",)
        for issue in issues
    )


def test_final_content_sources_do_not_copy_an_enabled_or_client_allowlist() -> None:
    build = CharacterBuild(
        content_sources=("pack-a", "srd5.1"),
        race_ref="srd5.1:race:human",
        background_ref="srd5.1:background:acolyte",
        character_level=1,
        class_progression=("srd5.1:class:fighter",),
        ability_scores=AbilityScores(
            strength=15,
            dexterity=14,
            constitution=13,
            intelligence=12,
            wisdom=10,
            charisma=8,
        ),
        hp_progression=(10,),
    )

    derived = _with_derived_content_sources(build)

    assert derived.content_sources == ("srd5.1",)
