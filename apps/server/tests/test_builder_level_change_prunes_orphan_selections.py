from __future__ import annotations

from sqlalchemy import create_engine

from app.content import load_default_content_registry
from app.db import metadata
from app.domain.character_builder.schemas import (
    BuilderBasicInput,
    BuilderChoiceSelection,
    BuilderDraftCreateInput,
    BuilderDraftPatchInput,
    BuilderDraftPayload,
    BuilderDraftPayloadPatch,
    BuilderLevelChoice,
    BuilderReferenceSelection,
)
from app.domain.character_builder.service import CharacterBuilderService
from app.persistence.builder_drafts import BuilderDraftRepository

BARD = "srd5.1:class:bard"
BARBARIAN = "srd5.1:class:barbarian"
FIGHTER = "srd5.1:class:fighter"
WIZARD = "srd5.1:class:wizard"
CHAMPION = "srd5.1:subclass:champion"


def _service() -> CharacterBuilderService:
    engine = create_engine("sqlite+pysqlite://")
    metadata.create_all(engine)
    return CharacterBuilderService(
        BuilderDraftRepository(engine), load_default_content_registry()
    )


def _level(
    character_level: int, class_ref: str, subclass_ref: str | None = None
) -> BuilderLevelChoice:
    return BuilderLevelChoice(
        character_level=character_level,
        class_ref=class_ref,
        hp_method="first_level" if character_level == 1 else "fixed_average",
        hp_base_gain=10 if character_level == 1 else 6,
        subclass_ref=subclass_ref,
    )


def _create(service: CharacterBuilderService, levels: list[BuilderLevelChoice]):
    return service.create_draft(
        BuilderDraftCreateInput(
            draft_payload=BuilderDraftPayload(
                basic=BuilderBasicInput(name="Class Switch Hero"),
                target_level=len(levels),
                race_selection=BuilderReferenceSelection(reference_id="srd5.1:race:human"),
                level_choices=levels,
            )
        )
    )


def _patch(service: CharacterBuilderService, view, **payload):
    return service.patch_draft(
        view.draft.id,
        BuilderDraftPatchInput(
            expected_revision=view.draft.revision,
            draft_payload=BuilderDraftPayloadPatch(**payload),
        ),
    )


def _select_first_options(view, predicate) -> dict[str, BuilderChoiceSelection]:
    selections: dict[str, BuilderChoiceSelection] = {}
    for choice in view.choices:
        if not predicate(choice):
            continue
        selections[choice.choice_id] = BuilderChoiceSelection(
            choice_id=choice.choice_id,
            source_ref=choice.source_ref,
            selected_option_ids=tuple(
                option.option_id for option in choice.options[: choice.choose_count]
            ),
        )
    return selections


def _bard_proficiency_selections(view) -> dict[str, BuilderChoiceSelection]:
    selections = _select_first_options(
        view,
        lambda choice: choice.source_ref == BARD
        and choice.option_source == "content:class-proficiency",
    )
    assert len(selections) == 2
    return selections


def _orphan_issues(view) -> list[str]:
    return [
        issue.path
        for issue in view.validation.issues
        if issue.code == "invalid_choice_option"
    ]


def test_switching_level_one_class_drops_previous_class_proficiency_selections() -> None:
    service = _service()
    created = _create(service, [_level(1, BARD)])
    with_bard = _patch(
        service, created, choice_selections=_bard_proficiency_selections(created)
    )
    assert all(key.startswith(f"level:1:{BARD}:") for key in with_bard.draft.draft_payload.choice_selections)

    switched = _patch(service, with_bard, level_choices=[_level(1, BARBARIAN)])

    assert switched.draft.draft_payload.choice_selections == {}
    assert _orphan_issues(switched) == []
    assert not any(choice.option_source == "draft:selection" for choice in switched.choices)
    assert any(choice.source_ref == BARBARIAN for choice in switched.choices)


def test_reclassing_level_one_drops_downstream_asi_selections_without_class_prefix() -> None:
    service = _service()
    created = _create(
        service,
        [_level(1, FIGHTER), _level(2, FIGHTER), _level(3, FIGHTER, CHAMPION), _level(4, FIGHTER)],
    )
    asi_branch = _select_first_options(
        created, lambda choice: choice.choice_id == "level:4:asi-feat:0"
    )
    assert asi_branch["level:4:asi-feat:0"].selected_option_ids == ("level:4:asi-feat:0:asi",)
    with_asi = _patch(service, created, choice_selections=asi_branch)
    assert "level:4:asi-feat:0" in with_asi.draft.draft_payload.choice_selections

    # Wizard 1 / Fighter 3: the level-4 ASI slot no longer exists.
    switched = _patch(
        service,
        with_asi,
        level_choices=[_level(1, WIZARD), _level(2, FIGHTER), _level(3, FIGHTER), _level(4, FIGHTER)],
    )

    assert "level:4:asi-feat:0" not in switched.draft.draft_payload.choice_selections
    assert _orphan_issues(switched) == []
    assert not any(choice.option_source == "draft:selection" for choice in switched.choices)


def test_shortening_progression_drops_selections_owned_by_removed_levels() -> None:
    service = _service()
    created = _create(
        service,
        [_level(1, FIGHTER), _level(2, FIGHTER), _level(3, FIGHTER, CHAMPION), _level(4, FIGHTER)],
    )
    with_asi = _patch(
        service,
        created,
        choice_selections=_select_first_options(
            created, lambda choice: choice.choice_id == "level:4:asi-feat:0"
        ),
    )

    shortened = _patch(
        service,
        with_asi,
        target_level=3,
        level_choices=[_level(1, FIGHTER), _level(2, FIGHTER), _level(3, FIGHTER, CHAMPION)],
    )

    assert "level:4:asi-feat:0" not in shortened.draft.draft_payload.choice_selections
    assert _orphan_issues(shortened) == []


def test_level_patch_without_class_change_keeps_selections() -> None:
    service = _service()
    created = _create(service, [_level(1, BARD)])
    selections = _bard_proficiency_selections(created)
    with_bard = _patch(service, created, choice_selections=selections)

    same_class_new_hp = _level(1, BARD).model_copy(update={"hp_base_gain": 8})
    patched = _patch(service, with_bard, level_choices=[same_class_new_hp])

    assert set(patched.draft.draft_payload.choice_selections) == set(selections)
    assert patched.draft.draft_payload.level_choices[0].hp_base_gain == 8
    assert _orphan_issues(patched) == []


def test_explicit_choice_selections_in_same_patch_are_not_pruned() -> None:
    service = _service()
    created = _create(service, [_level(1, BARD)])
    selections = _bard_proficiency_selections(created)
    with_bard = _patch(service, created, choice_selections=selections)

    forged = _patch(
        service,
        with_bard,
        level_choices=[_level(1, BARBARIAN)],
        choice_selections=selections,
    )

    # The caller asked for these rows explicitly; validation, not the prune,
    # is what rejects the cross-class combination.
    assert set(forged.draft.draft_payload.choice_selections) == set(selections)
    assert len(_orphan_issues(forged)) == 2
