from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import select

from app.persistence.characters import character_versions
from test_p1f_character_creation import _complete_fighter_draft, _seed
from test_p1g_character_versions import _complete_fighter_level_two, _start_level_up


def _provenance(engine, character_id: str, version_no: int) -> dict | None:
    with engine.connect() as connection:
        return connection.scalar(
            select(character_versions.c.builder_provenance).where(
                character_versions.c.character_id == UUID(character_id),
                character_versions.c.version_no == version_no,
            )
        )


def _confirm_create(client):
    view = _complete_fighter_draft(client)
    expected = view["draft"]["draft_payload"]
    response = client.post(
        f"/api/character-builder/drafts/{view['draft']['id']}/confirm"
    )
    assert response.status_code == 200, response.text
    return response.json(), expected


def test_m03b_create_confirm_snapshots_exact_locked_draft_payload() -> None:
    client, engine = _seed()
    created, expected = _confirm_create(client)
    assert _provenance(engine, created["character_id"], 1) == expected
    engine.dispose()


def test_m03b_level_up_confirm_snapshots_exact_locked_draft_payload() -> None:
    client, engine = _seed()
    created, _ = _confirm_create(client)
    view = _complete_fighter_level_two(
        client,
        _start_level_up(client, created["character_id"]),
    )
    expected = view["draft"]["draft_payload"]
    response = client.post(
        f"/api/character-builder/drafts/{view['draft']['id']}/confirm"
    )
    assert response.status_code == 200, response.text
    assert response.json()["version_no"] == 2
    assert _provenance(engine, created["character_id"], 2) == expected
    engine.dispose()


@pytest.mark.parametrize("mode", ["build_edit", "correction"])
def test_m03b_non_level_confirm_snapshots_exact_locked_draft_payload(mode: str) -> None:
    client, engine = _seed()
    created, _ = _confirm_create(client)
    character_id = created["character_id"]

    started = client.post(
        f"/api/character-builder/characters/{character_id}/drafts",
        json={"mode": mode},
    )
    assert started.status_code == 201, started.text
    view = started.json()
    patched = client.patch(
        f"/api/character-builder/drafts/{view['draft']['id']}",
        json={
            "expected_revision": view["draft"]["revision"],
            "draft_payload": {
                "roleplay_profile": {
                    "appearance": f"M03-B {mode} provenance",
                    "biography": "",
                }
            },
        },
    )
    assert patched.status_code == 200, patched.text
    view = patched.json()
    review = client.get(f"/api/character-builder/drafts/{view['draft']['id']}/review")
    assert review.status_code == 200, review.text
    assert review.json()["can_confirm"] is True, review.json()["issues"]

    expected = view["draft"]["draft_payload"]
    confirmed = client.post(
        f"/api/character-builder/drafts/{view['draft']['id']}/confirm"
    )
    assert confirmed.status_code == 200, confirmed.text
    assert _provenance(engine, character_id, 2) == expected
    engine.dispose()
