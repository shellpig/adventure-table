from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from app.domain.character.fixture import (
    build_p0_fighter_wizard_fixture,
    build_p0_fighter_wizard_state,
)
from test_p1f_character_creation import _complete_fighter_draft, _seed
from test_p1g_character_versions import _complete_fighter_level_two, _start_level_up


OUTPUT = Path("tests/data/m03")


def _write(name: str, payload: dict) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / name).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _create_builder_character(client, *, name: str) -> str:
    view = _complete_fighter_draft(client)
    patched = client.patch(
        f"/api/character-builder/drafts/{view['draft']['id']}",
        json={
            "expected_revision": view["draft"]["revision"],
            "draft_payload": {"basic": {"name": name, "ruleset": "dnd5e-2014"}},
        },
    )
    assert patched.status_code == 200, patched.text
    confirmed = client.post(
        f"/api/character-builder/drafts/{view['draft']['id']}/confirm"
    )
    assert confirmed.status_code == 200, confirmed.text
    return confirmed.json()["character_id"]


def _export(client, character_id: str) -> dict:
    response = client.get(f"/api/characters/{character_id}/export")
    assert response.status_code == 200, response.text
    return response.json()


def main() -> None:
    client, engine = _seed()
    try:
        unstable_id = _create_builder_character(client, name="M03-B Export Fixture")
        _write("character-export-unstable.json", _export(client, unstable_id))

        build = build_p0_fighter_wizard_fixture()
        state = build_p0_fighter_wizard_state(build)
        legacy = client.app.state.character_repository.create_character(
            name="M03-B Legacy Null Provenance",
            build=build,
            state=state,
            version_kind="legacy",
        )
        _write(
            "character-export-legacy-null-provenance.json",
            _export(client, str(legacy.id)),
        )

        multi_id = _create_builder_character(client, name="M03-B Multiversion")
        level_up = _complete_fighter_level_two(client, _start_level_up(client, multi_id))
        confirmed = client.post(
            f"/api/character-builder/drafts/{level_up['draft']['id']}/confirm"
        )
        assert confirmed.status_code == 200, confirmed.text
        multiversion = _export(client, multi_id)
        _write("character-export-multiversion.json", multiversion)

        archived_id = _create_builder_character(client, name="M03-B Archived")
        archived = client.post(f"/api/characters/{archived_id}/archive")
        assert archived.status_code == 200, archived.text
        _write("character-export-archived.json", _export(client, archived_id))

        bad_kind = deepcopy(multiversion)
        bad_kind["payload"]["versions"][-1]["version_kind"] = "future_kind"
        _write("character-export-bad-version-kind.json", bad_kind)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
