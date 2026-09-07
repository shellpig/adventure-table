from __future__ import annotations

import json
from uuid import UUID

import pytest

from app.content.registry import ContentRegistry
from app.domain.character.fixture import (
    P0_FIXTURE_NAME,
    build_p0_fighter_wizard_fixture,
    build_p0_fighter_wizard_state,
)
from app.domain.rooms.workspace import RoomCharacterWorkspaceService
from app.paths import resolve_content_root
from m03c_support import document
from test_p2b_room_character_api import _auth, _seed


def _create_scoped_character(repository, workspace, room_id: UUID):
    build = build_p0_fighter_wizard_fixture()
    character = repository.create_character(
        name=P0_FIXTURE_NAME,
        build=build,
        state=build_p0_fighter_wizard_state(build),
    )
    workspace.workspace_repository.attach_character(
        room_id=room_id,
        character_id=character.id,
    )
    return character


def _post_room_import(client, room_id: UUID, token: str, payload: dict, *, dry_run: bool = False):
    suffix = "?dry_run=true" if dry_run else ""
    return client.post(
        f"/api/rooms/{room_id}/characters/import{suffix}",
        headers={**_auth(token), "Content-Type": "application/json"},
        content=json.dumps(payload).encode("utf-8"),
    )


def test_room_import_full_character_and_duplicate_stay_in_target_room() -> None:
    client, engine, _, workspace, room_a, room_b = _seed()
    try:
        payload = document()
        first = _post_room_import(client, room_a.room.id, room_a.access_token, payload)
        second = _post_room_import(client, room_a.room.id, room_a.access_token, payload)

        assert first.status_code == 201, first.text
        assert second.status_code == 201, second.text
        first_id = UUID(first.json()["character_id"])
        second_id = UUID(second.json()["character_id"])
        assert first_id != second_id
        assert first.json()["draft_id"] is None
        assert second.json()["draft_id"] is None
        assert workspace.workspace_repository.character_room_id(first_id) == room_a.room.id
        assert workspace.workspace_repository.character_room_id(second_id) == room_a.room.id

        room_a_list = client.get(
            f"/api/rooms/{room_a.room.id}/characters",
            headers=_auth(room_a.access_token),
        )
        room_b_list = client.get(
            f"/api/rooms/{room_b.room.id}/characters",
            headers=_auth(room_b.access_token),
        )
        assert room_a_list.status_code == 200
        assert {UUID(item["id"]) for item in room_a_list.json()} == {first_id, second_id}
        assert room_b_list.status_code == 200
        assert room_b_list.json() == []

        forged = client.get(
            f"/api/rooms/{room_b.room.id}/characters/{first_id}",
            headers=_auth(room_b.access_token),
        )
        assert forged.status_code == 404
        assert forged.json()["error"]["code"] == "room_resource_not_found"
    finally:
        engine.dispose()


def test_room_import_missing_refs_repair_draft_stays_in_target_room() -> None:
    client, engine, _, _, room_a, room_b = _seed()
    try:
        enabled = tuple(
            pack
            for pack in client.app.state.content_registry.enabled_pack_ids
            if pack != "xge"
        )
        registry = ContentRegistry.from_root(resolve_content_root(), enabled)
        workspace = RoomCharacterWorkspaceService(engine, registry)
        client.app.state.content_registry = registry
        client.app.state.room_workspace_service = workspace

        response = _post_room_import(
            client,
            room_a.room.id,
            room_a.access_token,
            document("fixture_xge_dependent.json"),
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["character_id"] is None
        assert body["landing_mode"] == "draft"
        draft_id = UUID(body["draft_id"])
        assert workspace.workspace_repository.draft_room_id(draft_id) == room_a.room.id

        room_b_drafts = client.get(
            f"/api/rooms/{room_b.room.id}/character-builder/drafts",
            headers=_auth(room_b.access_token),
        )
        assert room_b_drafts.status_code == 200
        assert room_b_drafts.json() == []
        forged = client.get(
            f"/api/rooms/{room_b.room.id}/character-builder/drafts/{draft_id}",
            headers=_auth(room_b.access_token),
        )
        assert forged.status_code == 404
        assert forged.json()["error"]["code"] == "room_resource_not_found"
    finally:
        engine.dispose()


def test_room_import_history_loss_draft_and_dry_run_preserve_target_scope() -> None:
    client, engine, _, workspace, room_a, room_b = _seed()
    try:
        payload = document("fixture_state_only_missing_inventory.json")
        dry_run = _post_room_import(
            client,
            room_a.room.id,
            room_a.access_token,
            payload,
            dry_run=True,
        )
        assert dry_run.status_code == 200, dry_run.text
        assert dry_run.json()["dry_run"] is True
        assert dry_run.json()["committed"] is False
        assert workspace.workspace_repository.list_character_ids(room_a.room.id) == ()
        assert workspace.workspace_repository.list_draft_ids(room_a.room.id) == ()

        committed = _post_room_import(client, room_a.room.id, room_a.access_token, payload)
        assert committed.status_code == 201, committed.text
        body = committed.json()
        assert body["landing_mode"] == "draft_with_history_loss"
        assert body["character_id"] is None
        draft_id = UUID(body["draft_id"])
        assert workspace.workspace_repository.draft_room_id(draft_id) == room_a.room.id
        assert workspace.workspace_repository.list_draft_ids(room_b.room.id) == ()
    finally:
        engine.dispose()


@pytest.mark.parametrize("mode", ["level_up", "build_edit", "correction"])
def test_versioned_draft_inherits_character_room(mode: str) -> None:
    client, engine, repository, workspace, room_a, room_b = _seed()
    try:
        character = _create_scoped_character(repository, workspace, room_a.room.id)
        response = client.post(
            f"/api/rooms/{room_a.room.id}/character-builder/characters/{character.id}/drafts",
            headers=_auth(room_a.access_token),
            json={"mode": mode},
        )
        assert response.status_code == 201, response.text
        draft_id = UUID(response.json()["draft"]["id"])
        assert response.json()["draft"]["mode"] == mode
        assert workspace.workspace_repository.draft_room_id(draft_id) == room_a.room.id

        forged = client.get(
            f"/api/rooms/{room_b.room.id}/character-builder/drafts/{draft_id}",
            headers=_auth(room_b.access_token),
        )
        assert forged.status_code == 404
        assert forged.json()["error"]["code"] == "room_resource_not_found"
    finally:
        engine.dispose()


def test_member_and_dm_can_archive_but_cannot_permanently_delete_character() -> None:
    client, engine, repository, workspace, room_a, _ = _seed()
    try:
        character = _create_scoped_character(repository, workspace, room_a.room.id)
        room_id = room_a.room.id

        member = client.post(
            "/api/rooms/enter",
            json={
                "code": room_a.room.code,
                "password": "secret-a",
                "display_name": "Member",
            },
        )
        dm = client.post(
            "/api/rooms/enter",
            json={
                "code": room_a.room.code,
                "password": "secret-a",
                "elevated_key": room_a.dm_key,
                "display_name": "DM",
            },
        )
        assert member.status_code == 201, member.text
        assert member.json()["authority"] == "member"
        assert dm.status_code == 201, dm.text
        assert dm.json()["authority"] == "dm"

        archived = client.post(
            f"/api/rooms/{room_id}/characters/{character.id}/archive",
            headers=_auth(member.json()["access_token"]),
        )
        assert archived.status_code == 200, archived.text
        restored = client.post(
            f"/api/rooms/{room_id}/characters/{character.id}/unarchive",
            headers=_auth(dm.json()["access_token"]),
        )
        assert restored.status_code == 200, restored.text

        for grant in (member.json(), dm.json()):
            denied = client.delete(
                f"/api/rooms/{room_id}/characters/{character.id}",
                headers=_auth(grant["access_token"]),
            )
            assert denied.status_code == 403, denied.text
            assert denied.json()["error"]["code"] == "room_owner_required"

        owner_archive = client.post(
            f"/api/rooms/{room_id}/characters/{character.id}/archive",
            headers=_auth(room_a.access_token),
        )
        assert owner_archive.status_code == 200, owner_archive.text
        deleted = client.delete(
            f"/api/rooms/{room_id}/characters/{character.id}",
            headers=_auth(room_a.access_token),
        )
        assert deleted.status_code == 204, deleted.text
    finally:
        engine.dispose()
