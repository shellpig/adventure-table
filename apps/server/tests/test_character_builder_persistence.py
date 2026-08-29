from __future__ import annotations

from sqlalchemy import create_engine, func, select

from app.content import load_default_content_registry
from app.db import metadata
from app.domain.character.fixture import (
    P0_FIXTURE_NAME,
    build_p0_fighter_wizard_fixture,
    build_p0_fighter_wizard_state,
)
from app.domain.character_builder.schemas import (
    BuilderBasicInput,
    BuilderChoiceSelection,
    BuilderDraftCreateInput,
    BuilderDraftPatchInput,
    BuilderDraftPayload,
    BuilderDraftPayloadPatch,
    BuilderReferenceSelection,
)
from app.domain.character_builder.service import CharacterBuilderService
from app.persistence.builder_drafts import (
    BuilderDraftNotFoundError,
    BuilderDraftRepository,
    BuilderDraftRevisionConflictError,
    character_build_drafts,
)
from app.persistence.characters import (
    CharacterRepository,
    characters,
    character_states,
    character_versions,
)


def _count(engine, table) -> int:
    with engine.connect() as connection:
        value = connection.scalar(select(func.count()).select_from(table))
    return int(value or 0)


def test_draft_save_reload_cancel_and_revision_do_not_pollute_character_history(
    tmp_path,
) -> None:
    database_path = tmp_path / "p1a.sqlite3"
    database_url = f"sqlite+pysqlite:///{database_path}"
    registry = load_default_content_registry()

    engine = create_engine(database_url)
    metadata.create_all(engine)

    character_repository = CharacterRepository(engine, registry)
    build = build_p0_fighter_wizard_fixture()
    p0_character = character_repository.create_character(
        name=P0_FIXTURE_NAME,
        build=build,
        state=build_p0_fighter_wizard_state(build),
    )

    formal_counts = (
        _count(engine, characters),
        _count(engine, character_versions),
        _count(engine, character_states),
    )
    assert formal_counts == (1, 1, 1)

    service = CharacterBuilderService(BuilderDraftRepository(engine), registry)
    created = service.create_draft(
        BuilderDraftCreateInput(
            draft_payload=BuilderDraftPayload(
                basic=BuilderBasicInput(name="Draft Hero"),
                target_level=2,
            )
        )
    )
    draft_id = created.draft.id
    first_choice_ids = [choice.choice_id for choice in created.choices]

    assert created.draft.revision == 1
    assert created.validation.can_confirm is False
    assert _count(engine, character_build_drafts) == 1
    assert (
        _count(engine, characters),
        _count(engine, character_versions),
        _count(engine, character_states),
    ) == formal_counts

    patched = service.patch_draft(
        draft_id,
        BuilderDraftPatchInput(
            expected_revision=1,
            draft_payload=BuilderDraftPayloadPatch(
                race_selection=BuilderReferenceSelection(
                    reference_id="srd5.1:race:human"
                ),
                choice_selections={
                    "custom:test-choice": BuilderChoiceSelection(
                        choice_id="custom:test-choice",
                        selected_option_ids=("srd5.1:language:common",),
                        provenance_path="test",
                    )
                },
            ),
        ),
    )
    assert patched.draft.revision == 2
    assert patched.draft.draft_payload.race_selection is not None
    assert "custom:test-choice" in patched.draft.draft_payload.choice_selections

    try:
        service.patch_draft(
            draft_id,
            BuilderDraftPatchInput(
                expected_revision=1,
                draft_payload=BuilderDraftPayloadPatch(
                    basic=BuilderBasicInput(name="Stale overwrite")
                ),
            ),
        )
    except BuilderDraftRevisionConflictError as exc:
        assert exc.expected_revision == 1
        assert exc.actual_revision == 2
    else:
        raise AssertionError("stale draft update must fail")

    assert service.get_draft(draft_id).draft.draft_payload.basic.name == "Draft Hero"

    engine.dispose()

    fresh_engine = create_engine(database_url)
    fresh_service = CharacterBuilderService(
        BuilderDraftRepository(fresh_engine),
        registry,
    )
    reloaded = fresh_service.get_draft(draft_id)

    assert reloaded.draft.revision == 2
    assert reloaded.draft.draft_payload.race_selection.reference_id == "srd5.1:race:human"
    assert [choice.choice_id for choice in reloaded.choices][: len(first_choice_ids)] == first_choice_ids
    assert reloaded.validation.can_confirm is False

    fresh_service.cancel_draft(draft_id)
    assert _count(fresh_engine, character_build_drafts) == 0
    try:
        fresh_service.get_draft(draft_id)
    except BuilderDraftNotFoundError:
        pass
    else:
        raise AssertionError("cancelled draft should no longer load")

    p0_reloaded = CharacterRepository(fresh_engine, registry).load_character(
        p0_character.id
    )
    assert p0_reloaded.build == build
    assert (
        _count(fresh_engine, characters),
        _count(fresh_engine, character_versions),
        _count(fresh_engine, character_states),
    ) == formal_counts

    fresh_engine.dispose()
