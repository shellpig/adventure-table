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
    BuilderReferenceSelection,
)
from app.domain.character_builder.service import CharacterBuilderService
from app.persistence.builder_drafts import BuilderDraftRepository


def _service(tmp_path, filename: str):
    database_path = tmp_path / filename
    database_url = f"sqlite+pysqlite:///{database_path}"
    engine = create_engine(database_url)
    metadata.create_all(engine)
    return database_url, engine, CharacterBuilderService(
        BuilderDraftRepository(engine), load_default_content_registry()
    )


def test_scag_near_name_background_persists_full_stable_key_across_reload(tmp_path) -> None:
    database_url, engine, service = _service(tmp_path, "m01c-source.sqlite3")
    created = service.create_draft(
        BuilderDraftCreateInput(
            draft_payload=BuilderDraftPayload(
                basic=BuilderBasicInput(name="Waterdeep Source Hero"),
                target_level=1,
                race_selection=BuilderReferenceSelection(
                    reference_id="srd5.1:race:human"
                ),
                background_selection=BuilderReferenceSelection(
                    reference_id="scag:background:waterdhavian-noble"
                ),
            )
        )
    )

    assert created.draft.draft_payload.background_selection is not None
    assert (
        created.draft.draft_payload.background_selection.reference_id
        == "scag:background:waterdhavian-noble"
    )
    selector = next(
        choice for choice in created.choices if choice.option_source == "content:background"
    )
    labels = {option.option_id: option.label for option in selector.options}
    assert labels["phb2014:background:noble"].endswith(
        "· Player's Handbook 2014 Additions"
    )
    assert labels["scag:background:waterdhavian-noble"].endswith(
        "· Sword Coast Adventurer's Guide"
    )

    draft_id = created.draft.id
    engine.dispose()

    fresh_engine = create_engine(database_url)
    fresh_service = CharacterBuilderService(
        BuilderDraftRepository(fresh_engine), load_default_content_registry()
    )
    reloaded = fresh_service.get_draft(draft_id)
    assert reloaded.draft.draft_payload.background_selection is not None
    assert (
        reloaded.draft.draft_payload.background_selection.reference_id
        == "scag:background:waterdhavian-noble"
    )
    assert reloaded.resolved_summary.background_name == "Waterdhavian Noble"
    fresh_engine.dispose()


def test_scag_investigator_variant_switch_drops_inactive_city_watch_branch(tmp_path) -> None:
    _, engine, service = _service(tmp_path, "m01c-variant.sqlite3")
    created = service.create_draft(
        BuilderDraftCreateInput(
            draft_payload=BuilderDraftPayload(
                basic=BuilderBasicInput(name="Variant Branch Hero"),
                target_level=1,
                race_selection=BuilderReferenceSelection(
                    reference_id="srd5.1:race:human"
                ),
                background_selection=BuilderReferenceSelection(
                    reference_id="scag:background:city-watch"
                ),
            )
        )
    )
    city_language_choice = next(
        choice
        for choice in created.choices
        if choice.source_ref == "scag:background:city-watch"
        and choice.option_source == "content:language_options"
    )
    selected_city_languages = tuple(
        option.option_id for option in city_language_choice.options[:2]
    )
    with_city_branch = service.patch_draft(
        created.draft.id,
        BuilderDraftPatchInput(
            expected_revision=created.draft.revision,
            draft_payload=BuilderDraftPayloadPatch(
                choice_selections={
                    city_language_choice.choice_id: BuilderChoiceSelection(
                        choice_id=city_language_choice.choice_id,
                        source_ref="scag:background:city-watch",
                        selected_option_ids=selected_city_languages,
                    )
                }
            ),
        ),
    )
    assert any(
        grant.source_ref == "scag:background:city-watch"
        and grant.reference_id in selected_city_languages
        for grant in with_city_branch.resolved_summary.grants
    )

    switched = service.patch_draft(
        created.draft.id,
        BuilderDraftPatchInput(
            expected_revision=with_city_branch.draft.revision,
            draft_payload=BuilderDraftPayloadPatch(
                background_selection=BuilderReferenceSelection(
                    reference_id="scag:background:investigator"
                )
            ),
        ),
    )

    assert switched.draft.draft_payload.background_selection is not None
    assert (
        switched.draft.draft_payload.background_selection.reference_id
        == "scag:background:investigator"
    )
    assert switched.resolved_summary.background_name == "Investigator"
    investigator_grants = [
        grant
        for grant in switched.resolved_summary.grants
        if grant.source_ref == "scag:background:investigator"
    ]
    assert {
        grant.reference_id for grant in investigator_grants if grant.reference_id is not None
    } >= {
        "srd5.1:proficiency:skill-insight",
        "srd5.1:proficiency:skill-investigation",
    }
    assert not any(
        grant.source_ref == "scag:background:city-watch"
        for grant in switched.resolved_summary.grants
    )
    assert not any(
        grant.reference_id in selected_city_languages
        for grant in switched.resolved_summary.grants
    )
    investigator_language_choice = next(
        choice
        for choice in switched.choices
        if choice.source_ref == "scag:background:investigator"
        and choice.option_source == "content:language_options"
    )
    assert investigator_language_choice.choose_count == 2
    engine.dispose()
