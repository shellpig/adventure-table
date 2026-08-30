from __future__ import annotations

from app.domain.character.fixture import (
    build_p0_fighter_wizard_fixture,
    build_p0_fighter_wizard_state,
)
from app.main import app
from test_p1f_character_creation import _seed


def test_p1g_p0_legacy_character_can_open_level_up_draft_without_mutation() -> None:
    client, engine = _seed()
    build = build_p0_fighter_wizard_fixture()
    state = build_p0_fighter_wizard_state(build)
    character = app.state.character_repository.create_character(
        name="P0 Legacy Fighter Wizard",
        build=build,
        state=state,
        version_kind="legacy",
    )
    before = client.get(f"/api/characters/{character.id}").json()

    response = client.post(
        f"/api/character-builder/characters/{character.id}/drafts",
        json={"mode": "level_up"},
    )
    assert response.status_code == 201, response.text
    view = response.json()
    draft = view["draft"]

    assert draft["mode"] == "level_up"
    assert draft["character_id"] == str(character.id)
    assert draft["base_version_id"] == str(character.current_version_id)
    assert draft["draft_payload"]["target_level"] == build.character_level + 1
    assert len(draft["draft_payload"]["level_choices"]) == build.character_level
    assert draft["draft_payload"]["initial_state_seed"]["p1g_legacy_import"] is True

    # Opening/cancelling an imported Draft is never an official Build or State change.
    after_open = client.get(f"/api/characters/{character.id}").json()
    assert after_open == before
    cancelled = client.delete(f"/api/character-builder/drafts/{draft['id']}")
    assert cancelled.status_code == 204, cancelled.text
    after_cancel = client.get(f"/api/characters/{character.id}").json()
    assert after_cancel == before

    history = client.get(f"/api/characters/{character.id}/versions").json()
    assert len(history) == 1
    assert history[0]["version_kind"] == "legacy"
    assert history[0]["is_current"] is True

    engine.dispose()
