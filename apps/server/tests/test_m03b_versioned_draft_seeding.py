from __future__ import annotations

from uuid import uuid4

from app.content import load_default_content_registry
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
