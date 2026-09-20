from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Generator
from uuid import UUID, uuid4

from fastapi import Request
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, event, insert, select
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_database_engine
from app.api.errors import APIError
from app.api.rooms.access import get_room_access_context
from app.api.rooms.campaign_runtime import map_campaign_runtime_error
from app.db import metadata
from app.domain.campaign_runtime.service import CampaignRuntimeService
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.table_events import TableEventService
from app.main import app as fastapi_app
from app.persistence.campaign_runtime.tables import (
    campaign_world_entries,
    campaign_world_mutations,
)
from app.persistence.rooms.table_runtime import TableEventRepository
from app.persistence.rooms.tables import (
    campaign_seats,
    campaigns,
    room_access_sessions,
    rooms,
    sessions,
)


def _engine() -> Engine:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    metadata.create_all(engine)
    return engine


@dataclass(frozen=True)
class RuntimeApiFixture:
    client: TestClient
    engine: Engine
    room_a_id: UUID
    room_b_id: UUID
    campaign_a1_id: UUID
    campaign_active_id: UUID
    campaign_b1_id: UUID
    token_owner_a: str
    token_dm_a: str
    token_member_a: str
    token_owner_b: str


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_error_mapper_does_not_hide_unexpected_value_errors() -> None:
    error = ValueError("programming error")

    with pytest.raises(ValueError, match="programming error"):
        map_campaign_runtime_error(error)


@pytest.fixture
def api_fixture() -> Generator[RuntimeApiFixture, None, None]:
    engine = _engine()
    event_service = TableEventService(TableEventRepository(engine))
    runtime_service = CampaignRuntimeService(engine, event_service)

    room_a_id = uuid4()
    room_b_id = uuid4()
    campaign_a1_id = uuid4()
    campaign_active_id = uuid4()
    campaign_b1_id = uuid4()
    now = datetime.now(timezone.utc)

    owner_session_id = uuid4()
    dm_session_id = uuid4()
    member_session_id = uuid4()
    owner_b_session_id = uuid4()

    dm_seat_id = uuid4()
    active_session_id = uuid4()

    with engine.begin() as conn:
        conn.execute(
            insert(rooms).values(
                [
                    {
                        "id": room_a_id,
                        "code": "ROOM-A",
                        "name": "Room A",
                        "password_salt": b"salt",
                        "password_hash": b"pw",
                        "owner_key_hash": b"owner",
                        "dm_key_hash": b"dm",
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": room_b_id,
                        "code": "ROOM-B",
                        "name": "Room B",
                        "password_salt": b"salt",
                        "password_hash": b"pw",
                        "owner_key_hash": b"owner",
                        "dm_key_hash": b"dm",
                        "created_at": now,
                        "updated_at": now,
                    },
                ]
            )
        )
        conn.execute(
            insert(room_access_sessions).values(
                [
                    {
                        "id": owner_session_id,
                        "room_id": room_a_id,
                        "authority": "owner",
                        "token_hash": b"tok_hash_owner_a_123456789012",
                        "display_name": "Owner A",
                        "created_at": now,
                        "last_seen_at": now,
                    },
                    {
                        "id": dm_session_id,
                        "room_id": room_a_id,
                        "authority": "dm",
                        "token_hash": b"tok_hash_dm_a_1234567890123456",
                        "display_name": "DM A",
                        "created_at": now,
                        "last_seen_at": now,
                    },
                    {
                        "id": member_session_id,
                        "room_id": room_a_id,
                        "authority": "member",
                        "token_hash": b"tok_hash_member_a_123456789012",
                        "display_name": "Member A",
                        "created_at": now,
                        "last_seen_at": now,
                    },
                    {
                        "id": owner_b_session_id,
                        "room_id": room_b_id,
                        "authority": "owner",
                        "token_hash": b"tok_hash_owner_b_123456789012",
                        "display_name": "Owner B",
                        "created_at": now,
                        "last_seen_at": now,
                    },
                ]
            )
        )
        conn.execute(
            insert(campaigns).values(
                [
                    {
                        "id": campaign_a1_id,
                        "room_id": room_a_id,
                        "name": "Campaign A1",
                        "ruleset": "dnd5e-2014",
                        "status": "active",
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": campaign_active_id,
                        "room_id": room_a_id,
                        "name": "Campaign A Active",
                        "ruleset": "dnd5e-2014",
                        "status": "active",
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": campaign_b1_id,
                        "room_id": room_b_id,
                        "name": "Campaign B1",
                        "ruleset": "dnd5e-2014",
                        "status": "active",
                        "created_at": now,
                        "updated_at": now,
                    },
                ]
            )
        )
        conn.execute(
            insert(campaign_seats).values(
                id=dm_seat_id,
                campaign_id=campaign_active_id,
                role="dm",
                controller_kind="human",
                controller_access_session_id=dm_session_id,
                controller_epoch=1,
                created_at=now,
                updated_at=now,
            )
        )
        conn.execute(
            insert(sessions).values(
                id=active_session_id,
                campaign_id=campaign_active_id,
                status="active",
                dm_seat_id=dm_seat_id,
                dm_controller_kind="human",
                dm_controller_access_session_id=dm_session_id,
                started_at=now,
                created_at=now,
            )
        )

    token_owner_a = "tok-owner-a"
    token_dm_a = "tok-dm-a"
    token_member_a = "tok-member-a"
    token_owner_b = "tok-owner-b"

    token_to_context = {
        token_owner_a: RoomAccessContext(
            room_id=room_a_id,
            access_session_id=owner_session_id,
            authority=RoomAccessAuthority.OWNER,
            display_name="Owner A",
        ),
        token_dm_a: RoomAccessContext(
            room_id=room_a_id,
            access_session_id=dm_session_id,
            authority=RoomAccessAuthority.DM,
            display_name="DM A",
        ),
        token_member_a: RoomAccessContext(
            room_id=room_a_id,
            access_session_id=member_session_id,
            authority=RoomAccessAuthority.MEMBER,
            display_name="Member A",
        ),
        token_owner_b: RoomAccessContext(
            room_id=room_b_id,
            access_session_id=owner_b_session_id,
            authority=RoomAccessAuthority.OWNER,
            display_name="Owner B",
        ),
    }

    def _override_access_context(request: Request) -> RoomAccessContext:
        auth = request.headers.get("authorization", "")
        _, _, token = auth.partition(" ")
        token_clean = token.strip()
        if token_clean in token_to_context:
            return token_to_context[token_clean]
        raise APIError(401, "room_access_required", "Room access token is required")

    fastapi_app.state.campaign_runtime_service = runtime_service
    fastapi_app.dependency_overrides[get_database_engine] = lambda: engine
    fastapi_app.dependency_overrides[get_room_access_context] = _override_access_context

    client = TestClient(fastapi_app)
    try:
        yield RuntimeApiFixture(
            client=client,
            engine=engine,
            room_a_id=room_a_id,
            room_b_id=room_b_id,
            campaign_a1_id=campaign_a1_id,
            campaign_active_id=campaign_active_id,
            campaign_b1_id=campaign_b1_id,
            token_owner_a=token_owner_a,
            token_dm_a=token_dm_a,
            token_member_a=token_member_a,
            token_owner_b=token_owner_b,
        )
    finally:
        try:
            del fastapi_app.state.campaign_runtime_service
        except AttributeError:
            pass
        fastapi_app.dependency_overrides.pop(get_database_engine, None)
        fastapi_app.dependency_overrides.pop(get_room_access_context, None)


def test_owner_and_dm_no_active_session_crud(api_fixture: RuntimeApiFixture) -> None:
    fix = api_fixture
    base = f"/api/rooms/{fix.room_a_id}/campaigns/{fix.campaign_a1_id}/runtime/entries"

    # 1. Owner creates an entry
    create_resp = fix.client.post(
        base,
        json={
            "idempotency_key": "k-create-1",
            "kind": "npc",
            "title": "Town Guard",
            "state": {"monster_template_ref": "srd5.1:monster:guard"},
            "dm_notes": "Knows about the castle secret",
        },
        headers=_auth(fix.token_owner_a),
    )
    assert create_resp.status_code == 201
    entry_data = create_resp.json()
    entry_id = entry_data["id"]
    assert entry_data["kind"] == "npc"
    assert entry_data["title"] == "Town Guard"
    assert entry_data["revision"] == 1
    assert entry_data["visibility"] == "public"
    assert entry_data["dm_notes"] == "Knows about the castle secret"
    assert entry_data["archived_at"] is None

    # 2. Owner reads entry
    get_resp = fix.client.get(f"{base}/{entry_id}", headers=_auth(fix.token_owner_a))
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == entry_id

    # 3. Owner lists entries
    list_resp = fix.client.get(base, headers=_auth(fix.token_owner_a))
    assert list_resp.status_code == 200
    entries = list_resp.json()
    assert len(entries) == 1
    assert entries[0]["id"] == entry_id

    # 4. DM updates entry
    patch_resp = fix.client.patch(
        f"{base}/{entry_id}",
        json={
            "idempotency_key": "k-patch-1",
            "expected_revision": 1,
            "title": "Senior Guard",
            "body": "Promoted recently",
        },
        headers=_auth(fix.token_dm_a),
    )
    assert patch_resp.status_code == 200
    updated = patch_resp.json()
    assert updated["title"] == "Senior Guard"
    assert updated["body"] == "Promoted recently"
    assert updated["revision"] == 2

    # 5. DM archives entry
    arch_resp = fix.client.post(
        f"{base}/{entry_id}/archive",
        json={
            "idempotency_key": "k-arch-1",
            "expected_revision": 2,
        },
        headers=_auth(fix.token_dm_a),
    )
    assert arch_resp.status_code == 200
    archived = arch_resp.json()
    assert archived["archived_at"] is not None
    assert archived["revision"] == 3


def test_player_cannot_list_get_or_write(api_fixture: RuntimeApiFixture) -> None:
    fix = api_fixture
    base = f"/api/rooms/{fix.room_a_id}/campaigns/{fix.campaign_a1_id}/runtime/entries"

    # Create entry with owner
    create_resp = fix.client.post(
        base,
        json={
            "idempotency_key": "k-owner-1",
            "kind": "fact",
            "body": "The tavern is closed",
        },
        headers=_auth(fix.token_owner_a),
    )
    assert create_resp.status_code == 201
    entry_id = create_resp.json()["id"]

    # Player token (member) attempts list
    list_resp = fix.client.get(base, headers=_auth(fix.token_member_a))
    assert list_resp.status_code == 403
    assert list_resp.json()["error"]["code"] == "campaign_runtime_forbidden"

    # Player attempts get
    get_resp = fix.client.get(f"{base}/{entry_id}", headers=_auth(fix.token_member_a))
    assert get_resp.status_code == 403
    assert get_resp.json()["error"]["code"] == "campaign_runtime_forbidden"

    # Player attempts create
    post_resp = fix.client.post(
        base,
        json={
            "idempotency_key": "k-player-1",
            "kind": "fact",
            "body": "Player secret",
        },
        headers=_auth(fix.token_member_a),
    )
    assert post_resp.status_code == 403
    assert post_resp.json()["error"]["code"] == "campaign_runtime_forbidden"

    # Player attempts patch
    patch_resp = fix.client.patch(
        f"{base}/{entry_id}",
        json={
            "idempotency_key": "k-player-patch",
            "expected_revision": 1,
            "body": "Tampered fact",
        },
        headers=_auth(fix.token_member_a),
    )
    assert patch_resp.status_code == 403
    assert patch_resp.json()["error"]["code"] == "campaign_runtime_forbidden"

    # Player attempts archive
    arch_resp = fix.client.post(
        f"{base}/{entry_id}/archive",
        json={
            "idempotency_key": "k-player-arch",
            "expected_revision": 1,
        },
        headers=_auth(fix.token_member_a),
    )
    assert arch_resp.status_code == 403
    assert arch_resp.json()["error"]["code"] == "campaign_runtime_forbidden"


def test_wrong_room_and_wrong_campaign(api_fixture: RuntimeApiFixture) -> None:
    fix = api_fixture
    # Owner of Room A calls Room B URL -> 404 not found (context room mismatch)
    resp = fix.client.get(
        f"/api/rooms/{fix.room_b_id}/campaigns/{fix.campaign_b1_id}/runtime/entries",
        headers=_auth(fix.token_owner_a),
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "campaign_runtime_not_found"

    # Owner of Room A calls Room A URL but campaign belongs to Room B -> 404 not found
    resp2 = fix.client.get(
        f"/api/rooms/{fix.room_a_id}/campaigns/{fix.campaign_b1_id}/runtime/entries",
        headers=_auth(fix.token_owner_a),
    )
    assert resp2.status_code == 404
    assert resp2.json()["error"]["code"] == "campaign_runtime_not_found"

    # Owner of Room A calls Room A URL with non-existent campaign -> 404 not found
    random_campaign = uuid4()
    resp3 = fix.client.get(
        f"/api/rooms/{fix.room_a_id}/campaigns/{random_campaign}/runtime/entries",
        headers=_auth(fix.token_owner_a),
    )
    assert resp3.status_code == 404
    assert resp3.json()["error"]["code"] == "campaign_runtime_not_found"

    # Create entry in campaign A1
    create_resp = fix.client.post(
        f"/api/rooms/{fix.room_a_id}/campaigns/{fix.campaign_a1_id}/runtime/entries",
        json={
            "idempotency_key": "k-a1-1",
            "kind": "fact",
            "body": "Fact A1",
        },
        headers=_auth(fix.token_owner_a),
    )
    assert create_resp.status_code == 201
    entry_id = create_resp.json()["id"]

    # Owner B calls Room B URL requesting entry from campaign A1 -> 404 not found
    resp4 = fix.client.get(
        f"/api/rooms/{fix.room_b_id}/campaigns/{fix.campaign_b1_id}/runtime/entries/{entry_id}",
        headers=_auth(fix.token_owner_b),
    )
    assert resp4.status_code == 404
    assert resp4.json()["error"]["code"] == "campaign_runtime_not_found"


def test_active_session_blocks_mutations_but_allows_management_reads(
    api_fixture: RuntimeApiFixture,
) -> None:
    fix = api_fixture
    # campaign_active_id has an active session.
    # Seed an entry into campaign_active_id before testing.
    now = datetime.now(timezone.utc)
    entry_id = uuid4()
    with fix.engine.begin() as conn:
        conn.execute(
            insert(campaign_world_entries).values(
                id=entry_id,
                campaign_id=fix.campaign_active_id,
                kind="scene",
                title="Active Scene",
                body="A bustling town square",
                state_json={},
                dm_notes=None,
                visibility="public",
                needs_review=False,
                source_adventure_entry_id=None,
                provenance_json=None,
                revision=1,
                created_by_actor_kind="human",
                created_by_actor_id=None,
                created_at=now,
                updated_at=now,
                archived_at=None,
            )
        )

    base = f"/api/rooms/{fix.room_a_id}/campaigns/{fix.campaign_active_id}/runtime/entries"

    # Management reads are permitted during active session
    list_resp = fix.client.get(base, headers=_auth(fix.token_owner_a))
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1
    assert list_resp.json()[0]["id"] == str(entry_id)

    get_resp = fix.client.get(f"{base}/{entry_id}", headers=_auth(fix.token_dm_a))
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == str(entry_id)

    # Management mutations are blocked with 409 campaign_runtime_active_session
    post_resp = fix.client.post(
        base,
        json={
            "idempotency_key": "k-active-block-post",
            "kind": "npc",
            "title": "Blocked NPC",
        },
        headers=_auth(fix.token_owner_a),
    )
    assert post_resp.status_code == 409
    assert post_resp.json()["error"]["code"] == "campaign_runtime_active_session"

    patch_resp = fix.client.patch(
        f"{base}/{entry_id}",
        json={
            "idempotency_key": "k-active-block-patch",
            "expected_revision": 1,
            "title": "Updated Scene Title",
        },
        headers=_auth(fix.token_owner_a),
    )
    assert patch_resp.status_code == 409
    assert patch_resp.json()["error"]["code"] == "campaign_runtime_active_session"

    arch_resp = fix.client.post(
        f"{base}/{entry_id}/archive",
        json={
            "idempotency_key": "k-active-block-arch",
            "expected_revision": 1,
        },
        headers=_auth(fix.token_owner_a),
    )
    assert arch_resp.status_code == 409
    assert arch_resp.json()["error"]["code"] == "campaign_runtime_active_session"


def test_stale_revision_conflict(api_fixture: RuntimeApiFixture) -> None:
    fix = api_fixture
    base = f"/api/rooms/{fix.room_a_id}/campaigns/{fix.campaign_a1_id}/runtime/entries"

    create_resp = fix.client.post(
        base,
        json={
            "idempotency_key": "k-stale-1",
            "kind": "scene",
            "title": "Forest",
        },
        headers=_auth(fix.token_owner_a),
    )
    assert create_resp.status_code == 201
    entry_id = create_resp.json()["id"]

    # PATCH with wrong expected_revision
    patch_resp = fix.client.patch(
        f"{base}/{entry_id}",
        json={
            "idempotency_key": "k-stale-patch",
            "expected_revision": 999,
            "title": "Deep Forest",
        },
        headers=_auth(fix.token_owner_a),
    )
    assert patch_resp.status_code == 409
    assert patch_resp.json()["error"]["code"] == "campaign_runtime_revision_conflict"

    # POST archive with wrong expected_revision
    arch_resp = fix.client.post(
        f"{base}/{entry_id}/archive",
        json={
            "idempotency_key": "k-stale-arch",
            "expected_revision": 999,
        },
        headers=_auth(fix.token_owner_a),
    )
    assert arch_resp.status_code == 409
    assert arch_resp.json()["error"]["code"] == "campaign_runtime_revision_conflict"


def test_idempotency_replay_and_conflicting_reuse(api_fixture: RuntimeApiFixture) -> None:
    fix = api_fixture
    base = f"/api/rooms/{fix.room_a_id}/campaigns/{fix.campaign_a1_id}/runtime/entries"

    # 1. POST create idempotency replay
    body_create = {
        "idempotency_key": "k-idem-create",
        "kind": "npc",
        "title": "Blacksmith",
        "state": {"monster_template_ref": "srd5.1:monster:commoner"},
    }
    resp1 = fix.client.post(base, json=body_create, headers=_auth(fix.token_owner_a))
    assert resp1.status_code == 201
    entry_id = resp1.json()["id"]

    # Replay with same key and identical body -> 201, same entry ID
    resp2 = fix.client.post(base, json=body_create, headers=_auth(fix.token_owner_a))
    assert resp2.status_code == 201
    assert resp2.json()["id"] == entry_id

    # Reuse with different body -> 409 campaign_runtime_idempotency_conflict
    conflicting_create = dict(body_create)
    conflicting_create["title"] = "Armorer"
    resp3 = fix.client.post(base, json=conflicting_create, headers=_auth(fix.token_owner_a))
    assert resp3.status_code == 409
    assert resp3.json()["error"]["code"] == "campaign_runtime_idempotency_conflict"

    # 2. PATCH update idempotency replay
    patch_body = {
        "idempotency_key": "k-idem-patch",
        "expected_revision": 1,
        "title": "Master Blacksmith",
    }
    patch1 = fix.client.patch(f"{base}/{entry_id}", json=patch_body, headers=_auth(fix.token_owner_a))
    assert patch1.status_code == 200
    assert patch1.json()["revision"] == 2

    # Replay identical patch
    patch2 = fix.client.patch(f"{base}/{entry_id}", json=patch_body, headers=_auth(fix.token_owner_a))
    assert patch2.status_code == 200
    assert patch2.json()["revision"] == 2

    # Conflicting reuse of same key
    conflicting_patch = dict(patch_body)
    conflicting_patch["title"] = "Novice Blacksmith"
    patch3 = fix.client.patch(f"{base}/{entry_id}", json=conflicting_patch, headers=_auth(fix.token_owner_a))
    assert patch3.status_code == 409
    assert patch3.json()["error"]["code"] == "campaign_runtime_idempotency_conflict"

    # 3. POST archive idempotency replay
    arch_body = {
        "idempotency_key": "k-idem-arch",
        "expected_revision": 2,
    }
    arch1 = fix.client.post(f"{base}/{entry_id}/archive", json=arch_body, headers=_auth(fix.token_owner_a))
    assert arch1.status_code == 200
    assert arch1.json()["revision"] == 3

    # Replay identical archive
    arch2 = fix.client.post(f"{base}/{entry_id}/archive", json=arch_body, headers=_auth(fix.token_owner_a))
    assert arch2.status_code == 200
    assert arch2.json()["revision"] == 3

    # Conflicting reuse of archive key
    conflicting_arch = dict(arch_body)
    conflicting_arch["expected_revision"] = 999
    arch3 = fix.client.post(f"{base}/{entry_id}/archive", json=conflicting_arch, headers=_auth(fix.token_owner_a))
    assert arch3.status_code == 409
    assert arch3.json()["error"]["code"] == "campaign_runtime_idempotency_conflict"


def test_archived_and_not_found(api_fixture: RuntimeApiFixture) -> None:
    fix = api_fixture
    base = f"/api/rooms/{fix.room_a_id}/campaigns/{fix.campaign_a1_id}/runtime/entries"

    # Non-existent entry
    missing_id = uuid4()
    r1 = fix.client.get(f"{base}/{missing_id}", headers=_auth(fix.token_owner_a))
    assert r1.status_code == 404
    assert r1.json()["error"]["code"] == "campaign_runtime_not_found"

    r2 = fix.client.patch(
        f"{base}/{missing_id}",
        json={"idempotency_key": "k-miss-p", "expected_revision": 1, "title": "X"},
        headers=_auth(fix.token_owner_a),
    )
    assert r2.status_code == 404
    assert r2.json()["error"]["code"] == "campaign_runtime_not_found"

    r3 = fix.client.post(
        f"{base}/{missing_id}/archive",
        json={"idempotency_key": "k-miss-a", "expected_revision": 1},
        headers=_auth(fix.token_owner_a),
    )
    assert r3.status_code == 404
    assert r3.json()["error"]["code"] == "campaign_runtime_not_found"

    # Create and archive an entry
    create_resp = fix.client.post(
        base,
        json={"idempotency_key": "k-to-arch", "kind": "item", "title": "Old Key"},
        headers=_auth(fix.token_owner_a),
    )
    assert create_resp.status_code == 201
    entry_id = create_resp.json()["id"]

    arch_resp = fix.client.post(
        f"{base}/{entry_id}/archive",
        json={"idempotency_key": "k-do-arch", "expected_revision": 1},
        headers=_auth(fix.token_owner_a),
    )
    assert arch_resp.status_code == 200

    # Default list excludes archived
    list_active = fix.client.get(base, headers=_auth(fix.token_owner_a))
    assert list_active.status_code == 200
    assert not any(e["id"] == entry_id for e in list_active.json())

    # List with include_archived=true includes it
    list_all = fix.client.get(f"{base}?include_archived=true", headers=_auth(fix.token_owner_a))
    assert list_all.status_code == 200
    assert any(e["id"] == entry_id for e in list_all.json())

    # GET item default exclude -> 404 not found
    get_def = fix.client.get(f"{base}/{entry_id}", headers=_auth(fix.token_owner_a))
    assert get_def.status_code == 404
    assert get_def.json()["error"]["code"] == "campaign_runtime_not_found"

    # GET item include_archived=true -> 200 with archived_at
    get_arch = fix.client.get(f"{base}/{entry_id}?include_archived=true", headers=_auth(fix.token_owner_a))
    assert get_arch.status_code == 200
    assert get_arch.json()["archived_at"] is not None

    # PATCH on archived entry -> 409 campaign_runtime_archived
    patch_arch = fix.client.patch(
        f"{base}/{entry_id}",
        json={"idempotency_key": "k-patch-arch", "expected_revision": 2, "title": "New Key"},
        headers=_auth(fix.token_owner_a),
    )
    assert patch_arch.status_code == 409
    assert patch_arch.json()["error"]["code"] == "campaign_runtime_archived"

    # POST archive on already-archived entry -> 409 campaign_runtime_archived
    re_arch = fix.client.post(
        f"{base}/{entry_id}/archive",
        json={"idempotency_key": "k-re-arch", "expected_revision": 2},
        headers=_auth(fix.token_owner_a),
    )
    assert re_arch.status_code == 409
    assert re_arch.json()["error"]["code"] == "campaign_runtime_archived"


def test_malformed_typed_payload_and_validation_422(api_fixture: RuntimeApiFixture) -> None:
    fix = api_fixture
    base = f"/api/rooms/{fix.room_a_id}/campaigns/{fix.campaign_a1_id}/runtime/entries"

    # 1. Invalid state for kind (bad disposition enum)
    r1 = fix.client.post(
        base,
        json={
            "idempotency_key": "k-bad-1",
            "kind": "npc",
            "title": "Guard",
            "state": {"disposition": "not_a_valid_disposition"},
        },
        headers=_auth(fix.token_owner_a),
    )
    assert r1.status_code == 422
    assert r1.json()["error"]["code"] == "campaign_runtime_invalid"

    # 2. Missing required title for npc
    r2 = fix.client.post(
        base,
        json={
            "idempotency_key": "k-bad-2",
            "kind": "npc",
            "title": "",
        },
        headers=_auth(fix.token_owner_a),
    )
    assert r2.status_code == 422
    assert r2.json()["error"]["code"] == "campaign_runtime_invalid"

    # 3. Missing required body for fact
    r3 = fix.client.post(
        base,
        json={
            "idempotency_key": "k-bad-3",
            "kind": "fact",
            "body": "",
        },
        headers=_auth(fix.token_owner_a),
    )
    assert r3.status_code == 422
    assert r3.json()["error"]["code"] == "campaign_runtime_invalid"

    # 4. Character visibility with empty character_recipient_ids
    r4 = fix.client.post(
        base,
        json={
            "idempotency_key": "k-bad-4",
            "kind": "secret",
            "title": "Secret",
            "visibility": "character",
            "character_recipient_ids": [],
        },
        headers=_auth(fix.token_owner_a),
    )
    assert r4.status_code == 422
    assert r4.json()["error"]["code"] == "campaign_runtime_invalid"

    # 5. Public visibility with character_recipient_ids
    r5 = fix.client.post(
        base,
        json={
            "idempotency_key": "k-bad-5",
            "kind": "secret",
            "title": "Secret",
            "visibility": "public",
            "character_recipient_ids": [str(uuid4())],
        },
        headers=_auth(fix.token_owner_a),
    )
    assert r5.status_code == 422
    assert r5.json()["error"]["code"] == "campaign_runtime_invalid"

    # Create a valid entry for patch testing
    valid_resp = fix.client.post(
        base,
        json={"idempotency_key": "k-valid-p", "kind": "item", "title": "Sword"},
        headers=_auth(fix.token_owner_a),
    )
    assert valid_resp.status_code == 201
    entry_id = valid_resp.json()["id"]

    # 6. PATCH with no patch fields set
    r6 = fix.client.patch(
        f"{base}/{entry_id}",
        json={"idempotency_key": "k-patch-empty", "expected_revision": 1},
        headers=_auth(fix.token_owner_a),
    )
    assert r6.status_code == 422
    assert r6.json()["error"]["code"] == "campaign_runtime_invalid"

    # 7. PATCH with visibility: null
    r7 = fix.client.patch(
        f"{base}/{entry_id}",
        json={"idempotency_key": "k-patch-null-vis", "expected_revision": 1, "visibility": None},
        headers=_auth(fix.token_owner_a),
    )
    assert r7.status_code == 422
    assert r7.json()["error"]["code"] == "campaign_runtime_invalid"


def test_rejected_requests_leave_row_revision_and_mutation_state_unchanged(
    api_fixture: RuntimeApiFixture,
) -> None:
    fix = api_fixture
    base = f"/api/rooms/{fix.room_a_id}/campaigns/{fix.campaign_a1_id}/runtime/entries"

    # Create a clean entry
    create_resp = fix.client.post(
        base,
        json={"idempotency_key": "k-clean-1", "kind": "scene", "title": "Stable Scene"},
        headers=_auth(fix.token_owner_a),
    )
    assert create_resp.status_code == 201
    entry_id = UUID(create_resp.json()["id"])

    def _snapshot() -> tuple[int, int, int]:
        with fix.engine.connect() as conn:
            entry_count = conn.scalar(
                select(campaign_world_entries.c.revision).where(
                    campaign_world_entries.c.id == entry_id
                )
            )
            total_entries = conn.scalar(
                select(campaign_world_entries.c.id).where(
                    campaign_world_entries.c.campaign_id == fix.campaign_a1_id
                )
            )
            mut_count = len(
                conn.execute(
                    select(campaign_world_mutations).where(
                        campaign_world_mutations.c.campaign_id == fix.campaign_a1_id
                    )
                ).fetchall()
            )
            return entry_count or 0, total_entries or 0, mut_count

    rev_before, total_before, muts_before = _snapshot()
    assert rev_before == 1

    # Attempt 1: Stale revision conflict (409)
    resp1 = fix.client.patch(
        f"{base}/{entry_id}",
        json={"idempotency_key": "k-fail-1", "expected_revision": 99, "title": "Changed"},
        headers=_auth(fix.token_owner_a),
    )
    assert resp1.status_code == 409
    assert _snapshot() == (rev_before, total_before, muts_before)

    # Attempt 2: Malformed payload (422)
    resp2 = fix.client.post(
        base,
        json={"idempotency_key": "k-fail-2", "kind": "npc", "title": ""},
        headers=_auth(fix.token_owner_a),
    )
    assert resp2.status_code == 422
    assert _snapshot() == (rev_before, total_before, muts_before)

    # Attempt 3: Unauthorized player (403)
    resp3 = fix.client.patch(
        f"{base}/{entry_id}",
        json={"idempotency_key": "k-fail-3", "expected_revision": 1, "title": "Player Hack"},
        headers=_auth(fix.token_member_a),
    )
    assert resp3.status_code == 403
    assert _snapshot() == (rev_before, total_before, muts_before)

    # Attempt 4: Active session block (409) on the other campaign
    active_base = f"/api/rooms/{fix.room_a_id}/campaigns/{fix.campaign_active_id}/runtime/entries"
    resp4 = fix.client.post(
        active_base,
        json={"idempotency_key": "k-fail-4", "kind": "fact", "body": "Fact in active session"},
        headers=_auth(fix.token_owner_a),
    )
    assert resp4.status_code == 409
    assert _snapshot() == (rev_before, total_before, muts_before)
