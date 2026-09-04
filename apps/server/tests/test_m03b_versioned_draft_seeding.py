from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import select

import m01k_support as S
from app.content import load_default_content_registry
from app.domain.character_builder.schemas import BuilderDraftPayload
from app.persistence.builder_drafts import character_build_drafts
from app.persistence.characters import character_versions
from app.domain.character.fixture import (
    build_p0_fighter_wizard_fixture,
    build_p0_fighter_wizard_state,
)
from app.domain.character.schemas import PersistedCharacter
from app.domain.character_builder.schemas import BuilderMode
from app.domain.character_builder.versions import (
    legacy_payload_from_build,
    seed_version_draft_payload,
)


def _character() -> tuple[PersistedCharacter, object]:
    registry = load_default_content_registry()
    build = build_p0_fighter_wizard_fixture()
    state = build_p0_fighter_wizard_state(build)
    return (
        PersistedCharacter(
            id=uuid4(),
            name="Seed Priority",
            ruleset=build.ruleset,
            current_version_id=uuid4(),
            version_no=1,
            build=build,
            state=state,
        ),
        registry,
    )


def test_m03b_version_seed_prefers_builder_provenance_over_historical_draft() -> None:
    character, registry = _character()
    base = legacy_payload_from_build(character, registry)
    provenance = base.model_copy(deep=True)
    provenance.roleplay_profile = {"appearance": "from provenance"}
    stored = base.model_copy(deep=True)
    stored.roleplay_profile = {"appearance": "from stored draft"}

    seeded = seed_version_draft_payload(
        character,
        registry,
        mode=BuilderMode.BUILD_EDIT,
        builder_provenance=provenance.model_dump(mode="json"),
        stored_draft_payload=stored,
        state=character.state,
    )
    assert seeded.roleplay_profile["appearance"] == "from provenance"


def test_m03b_invalid_provenance_falls_back_to_historical_draft() -> None:
    character, registry = _character()
    stored = legacy_payload_from_build(character, registry)
    stored.roleplay_profile = {"appearance": "fallback draft"}

    seeded = seed_version_draft_payload(
        character,
        registry,
        mode=BuilderMode.BUILD_EDIT,
        builder_provenance={"not": "a BuilderDraftPayload"},
        stored_draft_payload=stored,
    )
    assert seeded.roleplay_profile["appearance"] == "fallback draft"


def test_m03b_no_provenance_or_confirmed_draft_uses_legacy_reconstruction() -> None:
    character, registry = _character()
    seeded = seed_version_draft_payload(
        character,
        registry,
        mode=BuilderMode.BUILD_EDIT,
    )
    assert seeded.initial_state_seed["p1g_legacy_import"] is True


# --- B.2.1 end to end: the service must actually wire the new SSOT ----------


def _confirmed_character(client) -> str:
    view = S.http_create_draft(
        client,
        {
            "basic": {"name": "M03-B Seed SSOT", "ruleset": "dnd5e-2014"},
            "target_level": 1,
            "race_selection": {"reference_id": "srd5.1:race:human"},
            "background_selection": {"reference_id": "srd5.1:background:acolyte"},
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
                "provenance": "m03b",
            },
            "level_choices": [
                {
                    "character_level": 1,
                    "class_ref": "srd5.1:class:fighter",
                    "hp_method": "first_level",
                    "hp_base_gain": 10,
                    "subclass_ref": None,
                }
            ],
        },
    )
    view = S.http_fill_equipment(client, S.http_fill_generic(client, view))
    return S.http_confirm(client, view)["character_id"]


def _mark_provenance(engine, character_id: str, marker: str) -> None:
    """Stamp the stored snapshot so its use is observable in the seeded draft."""

    with engine.begin() as connection:
        stored = connection.scalar(
            select(character_versions.c.builder_provenance).where(
                character_versions.c.character_id == UUID(character_id)
            )
        )
        assert stored is not None, "confirm must have written builder_provenance"
        payload = dict(stored)
        roleplay = dict(payload.get("roleplay_profile") or {})
        roleplay["appearance"] = marker
        payload["roleplay_profile"] = roleplay
        connection.execute(
            character_versions.update()
            .where(character_versions.c.character_id == UUID(character_id))
            .values(builder_provenance=payload)
        )


def _clear_draft_rows(engine) -> None:
    with engine.begin() as connection:
        connection.execute(character_build_drafts.delete())


def _open_level_up(client, character_id: str) -> dict:
    response = client.post(
        f"/api/character-builder/characters/{character_id}/drafts",
        json={"mode": "level_up"},
    )
    assert response.status_code == 201, response.text
    return response.json()["draft"]["draft_payload"]


def test_m03b_level_up_seeds_from_provenance_when_the_old_draft_row_is_gone() -> None:
    """The import landing case: no historical draft row exists to fall back to."""

    client, engine = S.seed_http()
    try:
        character_id = _confirmed_character(client)
        _mark_provenance(engine, character_id, "seeded from builder_provenance")
        _clear_draft_rows(engine)

        seeded = _open_level_up(client, character_id)
        assert seeded["roleplay_profile"]["appearance"] == "seeded from builder_provenance"
        assert "p1g_legacy_import" not in (seeded.get("initial_state_seed") or {})
        BuilderDraftPayload.model_validate(seeded)
    finally:
        engine.dispose()


def test_m03b_level_up_falls_back_to_legacy_reconstruction_without_provenance() -> None:
    client, engine = S.seed_http()
    try:
        character_id = _confirmed_character(client)
        with engine.begin() as connection:
            connection.execute(
                character_versions.update()
                .where(character_versions.c.character_id == UUID(character_id))
                .values(builder_provenance=None)
            )
        _clear_draft_rows(engine)

        seeded = _open_level_up(client, character_id)
        assert (seeded.get("initial_state_seed") or {}).get("p1g_legacy_import") is True
        BuilderDraftPayload.model_validate(seeded)
    finally:
        engine.dispose()
