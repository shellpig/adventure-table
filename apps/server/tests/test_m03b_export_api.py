from __future__ import annotations

from test_p1f_character_creation import _complete_fighter_draft, _seed


def _create_character(client, *, name: str = "M03-B Fighter") -> str:
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


def test_m03b_export_api_is_json_read_only_and_uses_manifest_versions() -> None:
    client, engine = _seed()
    character_id = _create_character(client)
    before = client.get(f"/api/characters/{character_id}").json()

    response = client.get(f"/api/characters/{character_id}/export")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["x-adventure-table-character-archived"] == "false"
    assert "attachment;" in response.headers["content-disposition"]

    document = response.json()
    assert document["envelope"]["schema_version"] == "unstable"
    assert document["envelope"]["schema_status"] == "unstable"
    assert document["envelope"]["content_requirements"]
    assert all(
        item["version"] == "1.0.0"
        for item in document["envelope"]["content_requirements"]
    )
    assert document["payload"]["current_version_no"] == 1

    after = client.get(f"/api/characters/{character_id}").json()
    assert after == before
    engine.dispose()


def test_m03b_archived_character_remains_exportable() -> None:
    client, engine = _seed()
    character_id = _create_character(client)
    archived = client.post(f"/api/characters/{character_id}/archive")
    assert archived.status_code == 200, archived.text

    response = client.get(f"/api/characters/{character_id}/export")
    assert response.status_code == 200, response.text
    assert response.headers["x-adventure-table-character-archived"] == "true"
    engine.dispose()


def test_m03b_unicode_name_uses_rfc5987_filename_with_ascii_fallback() -> None:
    client, engine = _seed()
    character_id = _create_character(client, name="測試 角色")

    response = client.get(f"/api/characters/{character_id}/export")
    disposition = response.headers["content-disposition"]
    assert 'filename="character-v1-' in disposition
    assert "filename*=UTF-8''%E6%B8%AC%E8%A9%A6%20%E8%A7%92%E8%89%B2-v1-" in disposition
    engine.dispose()
