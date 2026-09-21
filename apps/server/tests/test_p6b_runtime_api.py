from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Generator
from uuid import UUID, uuid4

from fastapi import Request
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, event, func, insert, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_database_engine
from app.api.errors import APIError
from app.api.rooms.access import get_room_access_context
from app.api.rooms.campaign_runtime import map_campaign_runtime_error
from app.api.rooms.dependencies import (
    get_campaign_runtime_service,
    get_table_event_service,
)
from app.db import metadata
from app.domain.adventures.attachments import CampaignAdventureService
from app.domain.adventures.schemas import (
    CampaignAdventureAttach,
)
from app.domain.campaign_runtime.payloads import RuntimeEntryPayloadError
from app.domain.campaign_runtime.schemas import (
    CampaignAdventureOverrideAlreadyExistsError,
    RuntimeEntryValidationError,
    RuntimeEntryVisibilityError,
)
from app.domain.campaign_runtime.errors import (
    CampaignRuntimeActiveSessionError,
    CampaignRuntimeArchivedError,
    CampaignRuntimeAuthorityError,
    CampaignRuntimeIdempotencyConflictError,
    CampaignRuntimeNotFoundError,
    CampaignRuntimeRevisionConflictError,
    CampaignRuntimeSessionNotActiveError,
    CampaignRuntimeValidationError,
)
from app.domain.campaign_runtime.service import (
    CampaignRuntimeService,
)
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.table_events import (
    TableEventActorUnauthorizedError,
    TableEventNotFoundError,
    TableEventService,
    TableEventSessionNotActiveError,
)
from app.main import app as fastapi_app
from app.persistence.adventures.repository import (
    AdventureRepository,
    CampaignAdventureLinkRepository,
)
from app.persistence.adventures.tables import (
    adventure_definitions,
    adventure_entries,
    campaign_adventure_links,
)
from app.persistence.campaign_runtime.tables import (
    campaign_adventure_overrides,
    campaign_runtime_context,
    campaign_world_entries,
    campaign_world_entry_characters,
    campaign_world_mutations,
)
from app.persistence.characters import characters
from app.persistence.rooms.campaigns import CampaignRepository
from app.persistence.rooms.table_runtime import (
    TableEventRepository,
    session_events,
)
from app.persistence.rooms.tables import (
    campaign_seats,
    campaigns,
    room_access_sessions,
    room_characters,
    rooms,
    session_participants,
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
    adv_1_id: UUID
    adv_2_unattached_id: UUID
    npc_entry_id: UUID
    scene_entry_id: UUID
    unattached_entry_id: UUID
    adv_service: CampaignAdventureService
    owner_context_a: RoomAccessContext


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

        adv_1_id = uuid4()
        adv_2_unattached_id = uuid4()
        npc_entry_id = uuid4()
        scene_entry_id = uuid4()
        unattached_entry_id = uuid4()

        conn.execute(
            insert(adventure_definitions).values(
                [
                    {
                        "id": adv_1_id,
                        "room_id": room_a_id,
                        "name": "Lost Mine",
                        "summary": "Adventure 1",
                        "ruleset": "dnd5e-2014",
                        "status": "finalized",
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": adv_2_unattached_id,
                        "room_id": room_a_id,
                        "name": "Sunless Citadel",
                        "summary": "Adventure 2",
                        "ruleset": "dnd5e-2014",
                        "status": "finalized",
                        "created_at": now,
                        "updated_at": now,
                    },
                ]
            )
        )
        conn.execute(
            insert(adventure_entries).values(
                [
                    {
                        "id": npc_entry_id,
                        "adventure_id": adv_1_id,
                        "parent_entry_id": None,
                        "kind": "npc",
                        "title": "Goblin Sentry",
                        "body": "A small green creature",
                        "data_json": {"disposition": "neutral"},
                        "visibility": "public",
                        "sort_order": 1,
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": scene_entry_id,
                        "adventure_id": adv_1_id,
                        "parent_entry_id": None,
                        "kind": "scene",
                        "title": "Goblin Cave",
                        "body": "Dark and damp",
                        "data_json": {},
                        "visibility": "public",
                        "sort_order": 2,
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": unattached_entry_id,
                        "adventure_id": adv_2_unattached_id,
                        "parent_entry_id": None,
                        "kind": "scene",
                        "title": "Citadel Gate",
                        "body": "Overgrown entrance",
                        "data_json": {},
                        "visibility": "public",
                        "sort_order": 1,
                        "created_at": now,
                        "updated_at": now,
                    },
                ]
            )
        )
        conn.execute(
            insert(campaign_adventure_links).values(
                [
                    {
                        "campaign_id": campaign_a1_id,
                        "adventure_id": adv_1_id,
                        "sort_order": 1,
                        "attached_at": now,
                    },
                    {
                        "campaign_id": campaign_active_id,
                        "adventure_id": adv_1_id,
                        "sort_order": 1,
                        "attached_at": now,
                    },
                ]
            )
        )

    adv_service = CampaignAdventureService(
        CampaignAdventureLinkRepository(engine),
        AdventureRepository(engine),
        CampaignRepository(engine),
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
    fastapi_app.state.campaign_adventure_service = adv_service
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
            adv_1_id=adv_1_id,
            adv_2_unattached_id=adv_2_unattached_id,
            npc_entry_id=npc_entry_id,
            scene_entry_id=scene_entry_id,
            unattached_entry_id=unattached_entry_id,
            adv_service=adv_service,
            owner_context_a=token_to_context[token_owner_a],
        )
    finally:
        try:
            del fastapi_app.state.campaign_runtime_service
        except AttributeError:
            pass
        try:
            del fastapi_app.state.campaign_adventure_service
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


def _snapshot_runtime_state(fix: RuntimeApiFixture) -> tuple[int, int, int]:
    with fix.engine.connect() as conn:
        ovr_count = len(
            conn.execute(
                select(campaign_adventure_overrides).where(
                    campaign_adventure_overrides.c.campaign_id == fix.campaign_a1_id
                )
            ).fetchall()
        )
        ctx_row = conn.execute(
            select(campaign_runtime_context).where(
                campaign_runtime_context.c.campaign_id == fix.campaign_a1_id
            )
        ).mappings().one_or_none()
        ctx_rev = ctx_row["revision"] if ctx_row is not None else 0
        mut_count = len(
            conn.execute(
                select(campaign_world_mutations).where(
                    campaign_world_mutations.c.campaign_id == fix.campaign_a1_id
                )
            ).fetchall()
        )
        return ovr_count, ctx_rev, mut_count


def test_override_management_crud_and_overlay_reads(api_fixture: RuntimeApiFixture) -> None:
    fix = api_fixture
    base = f"/api/rooms/{fix.room_a_id}/campaigns/{fix.campaign_a1_id}/runtime"

    # 1. Overlay read before any override exists
    ov_resp = fix.client.get(
        f"{base}/adventure-overlays/{fix.npc_entry_id}",
        headers=_auth(fix.token_owner_a),
    )
    assert ov_resp.status_code == 200
    ov_data = ov_resp.json()
    assert ov_data["id"] == str(fix.npc_entry_id)
    assert ov_data["kind"] == "npc"
    assert ov_data["data"]["disposition"] == "neutral"
    assert ov_data["override"] is None

    # List overlays for adventure
    list_ov_resp = fix.client.get(
        f"{base}/adventures/{fix.adv_1_id}/overlays",
        headers=_auth(fix.token_owner_a),
    )
    assert list_ov_resp.status_code == 200
    overlays = list_ov_resp.json()
    assert len(overlays) == 2
    assert all(o["override"] is None for o in overlays)

    # Initial list overrides is empty
    list_ovr_0 = fix.client.get(f"{base}/overrides", headers=_auth(fix.token_owner_a))
    assert list_ovr_0.status_code == 200
    assert list_ovr_0.json() == []

    # 2. Owner creates override
    create_resp = fix.client.post(
        f"{base}/overrides",
        json={
            "idempotency_key": "k-ovr-c1",
            "adventure_entry_id": str(fix.npc_entry_id),
            "state": {"disposition": "hostile"},
            "note": "Ambushed party",
            "needs_review": False,
        },
        headers=_auth(fix.token_owner_a),
    )
    assert create_resp.status_code == 201
    created = create_resp.json()
    ovr_id = created["id"]
    assert created["adventure_entry_id"] == str(fix.npc_entry_id)
    assert created["state_json"] == {"disposition": "hostile"}
    assert created["note"] == "Ambushed party"
    assert created["needs_review"] is False
    assert created["revision"] == 1

    # 3. GET override by adventure_entry_id
    get_ovr = fix.client.get(
        f"{base}/overrides/{fix.npc_entry_id}",
        headers=_auth(fix.token_owner_a),
    )
    assert get_ovr.status_code == 200
    assert get_ovr.json()["id"] == ovr_id

    # 4. GET list overrides
    list_ovr_1 = fix.client.get(f"{base}/overrides", headers=_auth(fix.token_owner_a))
    assert list_ovr_1.status_code == 200
    assert len(list_ovr_1.json()) == 1
    assert list_ovr_1.json()[0]["id"] == ovr_id

    # 5. Overlay read with override present
    ov_resp_with = fix.client.get(
        f"{base}/adventure-overlays/{fix.npc_entry_id}",
        headers=_auth(fix.token_dm_a),
    )
    assert ov_resp_with.status_code == 200
    ov_with_data = ov_resp_with.json()
    assert ov_with_data["override"] is not None
    assert ov_with_data["override"]["id"] == ovr_id
    assert ov_with_data["override"]["state_json"] == {"disposition": "hostile"}

    # Assert underlying adventure_entries definition row is completely unchanged
    with fix.engine.connect() as conn:
        entry_row = conn.execute(
            select(adventure_entries).where(adventure_entries.c.id == fix.npc_entry_id)
        ).mappings().one()
        assert entry_row["data_json"] == {"disposition": "neutral"}

    # 6. DM updates override
    patch_resp = fix.client.patch(
        f"{base}/overrides/{fix.npc_entry_id}",
        json={
            "idempotency_key": "k-ovr-p1",
            "expected_override_id": ovr_id,
            "expected_revision": 1,
            "state": {"disposition": "friendly"},
            "note": "Bribed with rations",
            "needs_review": True,
        },
        headers=_auth(fix.token_dm_a),
    )
    assert patch_resp.status_code == 200
    updated = patch_resp.json()
    assert updated["revision"] == 2
    assert updated["state_json"] == {"disposition": "friendly"}
    assert updated["needs_review"] is True

    # 7. DM clears override
    clear_resp = fix.client.post(
        f"{base}/overrides/{fix.npc_entry_id}/clear",
        json={
            "idempotency_key": "k-ovr-clear1",
            "expected_override_id": ovr_id,
            "expected_revision": 2,
        },
        headers=_auth(fix.token_dm_a),
    )
    assert clear_resp.status_code == 200

    # 8. Verify cleared
    get_cleared = fix.client.get(
        f"{base}/overrides/{fix.npc_entry_id}",
        headers=_auth(fix.token_owner_a),
    )
    assert get_cleared.status_code == 404
    assert get_cleared.json()["error"]["code"] == "campaign_runtime_not_found"

    list_cleared = fix.client.get(f"{base}/overrides", headers=_auth(fix.token_owner_a))
    assert list_cleared.status_code == 200
    assert list_cleared.json() == []

    ov_after_clear = fix.client.get(
        f"{base}/adventure-overlays/{fix.npc_entry_id}",
        headers=_auth(fix.token_owner_a),
    )
    assert ov_after_clear.status_code == 200
    assert ov_after_clear.json()["override"] is None


def test_context_management_crud(api_fixture: RuntimeApiFixture) -> None:
    fix = api_fixture
    base = f"/api/rooms/{fix.room_a_id}/campaigns/{fix.campaign_a1_id}/runtime"

    # 1. Initial GET context (revision 0, all None)
    get_ctx_0 = fix.client.get(f"{base}/context", headers=_auth(fix.token_owner_a))
    assert get_ctx_0.status_code == 200
    ctx_0 = get_ctx_0.json()
    assert ctx_0["revision"] == 0
    assert ctx_0["current_adventure_scene_entry_id"] is None
    assert ctx_0["current_runtime_scene_entry_id"] is None
    assert ctx_0["current_situation"] is None

    # 2. Owner updates situation only
    patch_1 = fix.client.patch(
        f"{base}/context",
        json={
            "idempotency_key": "k-ctx-p1",
            "expected_revision": 0,
            "current_situation": "The party enters Phandalin.",
        },
        headers=_auth(fix.token_owner_a),
    )
    assert patch_1.status_code == 200
    ctx_1 = patch_1.json()
    assert ctx_1["revision"] == 1
    assert ctx_1["current_situation"] == "The party enters Phandalin."
    assert ctx_1["current_adventure_scene_entry_id"] is None

    # 3. DM updates with adventure scene reference
    patch_2 = fix.client.patch(
        f"{base}/context",
        json={
            "idempotency_key": "k-ctx-p2",
            "expected_revision": 1,
            "current_adventure_scene_entry_id": str(fix.scene_entry_id),
        },
        headers=_auth(fix.token_dm_a),
    )
    assert patch_2.status_code == 200
    ctx_2 = patch_2.json()
    assert ctx_2["revision"] == 2
    assert ctx_2["current_adventure_scene_entry_id"] == str(fix.scene_entry_id)
    assert ctx_2["current_situation"] == "The party enters Phandalin."

    # 4. Owner clears context
    clear_resp = fix.client.post(
        f"{base}/context/clear",
        json={
            "idempotency_key": "k-ctx-c1",
            "expected_revision": 2,
        },
        headers=_auth(fix.token_owner_a),
    )
    assert clear_resp.status_code == 200
    cleared_ctx = clear_resp.json()
    assert cleared_ctx["revision"] == 3
    assert cleared_ctx["current_adventure_scene_entry_id"] is None
    assert cleared_ctx["current_runtime_scene_entry_id"] is None
    assert cleared_ctx["current_situation"] is None


def test_player_forbidden_from_overrides_context_and_overlays(
    api_fixture: RuntimeApiFixture,
) -> None:
    fix = api_fixture
    base = f"/api/rooms/{fix.room_a_id}/campaigns/{fix.campaign_a1_id}/runtime"

    calls = [
        ("GET", f"{base}/overrides", None),
        ("GET", f"{base}/overrides/{fix.npc_entry_id}", None),
        (
            "POST",
            f"{base}/overrides",
            {
                "idempotency_key": "k-pl-1",
                "adventure_entry_id": str(fix.npc_entry_id),
                "state": {"disposition": "hostile"},
            },
        ),
        (
            "PATCH",
            f"{base}/overrides/{fix.npc_entry_id}",
            {
                "idempotency_key": "k-pl-2",
                "expected_override_id": str(uuid4()),
                "expected_revision": 1,
                "state": {"disposition": "friendly"},
            },
        ),
        (
            "POST",
            f"{base}/overrides/{fix.npc_entry_id}/clear",
            {
                "idempotency_key": "k-pl-3",
                "expected_override_id": str(uuid4()),
                "expected_revision": 1,
            },
        ),
        ("GET", f"{base}/context", None),
        (
            "PATCH",
            f"{base}/context",
            {"idempotency_key": "k-pl-4", "expected_revision": 0, "current_situation": "hack"},
        ),
        (
            "POST",
            f"{base}/context/clear",
            {"idempotency_key": "k-pl-5", "expected_revision": 0},
        ),
        ("GET", f"{base}/adventure-overlays/{fix.npc_entry_id}", None),
        ("GET", f"{base}/adventures/{fix.adv_1_id}/overlays", None),
    ]

    for method, url, json_body in calls:
        if method == "GET":
            r = fix.client.get(url, headers=_auth(fix.token_member_a))
        elif method == "POST":
            r = fix.client.post(url, json=json_body, headers=_auth(fix.token_member_a))
        elif method == "PATCH":
            r = fix.client.patch(url, json=json_body, headers=_auth(fix.token_member_a))
        else:
            raise AssertionError(f"Unknown method {method}")
        assert r.status_code == 403, f"{method} {url} returned {r.status_code}"
        assert r.json()["error"]["code"] == "campaign_runtime_forbidden"


def test_wrong_room_and_campaign_overrides_context_overlays(
    api_fixture: RuntimeApiFixture,
) -> None:
    fix = api_fixture
    # Wrong room context
    r1 = fix.client.get(
        f"/api/rooms/{fix.room_b_id}/campaigns/{fix.campaign_b1_id}/runtime/overrides",
        headers=_auth(fix.token_owner_a),
    )
    assert r1.status_code == 404
    assert r1.json()["error"]["code"] == "campaign_runtime_not_found"

    r2 = fix.client.get(
        f"/api/rooms/{fix.room_b_id}/campaigns/{fix.campaign_b1_id}/runtime/context",
        headers=_auth(fix.token_owner_a),
    )
    assert r2.status_code == 404
    assert r2.json()["error"]["code"] == "campaign_runtime_not_found"

    # Campaign not in room
    r3 = fix.client.get(
        f"/api/rooms/{fix.room_a_id}/campaigns/{fix.campaign_b1_id}/runtime/overrides",
        headers=_auth(fix.token_owner_a),
    )
    assert r3.status_code == 404
    assert r3.json()["error"]["code"] == "campaign_runtime_not_found"

    # Non-existent campaign
    rand_camp = uuid4()
    r4 = fix.client.get(
        f"/api/rooms/{fix.room_a_id}/campaigns/{rand_camp}/runtime/context",
        headers=_auth(fix.token_owner_a),
    )
    assert r4.status_code == 404
    assert r4.json()["error"]["code"] == "campaign_runtime_not_found"


def test_unattached_adventure_entry_and_duplicate_override(
    api_fixture: RuntimeApiFixture,
) -> None:
    fix = api_fixture
    base = f"/api/rooms/{fix.room_a_id}/campaigns/{fix.campaign_a1_id}/runtime"

    # 1. Override on unattached entry -> 422 campaign_runtime_invalid
    r_unattached = fix.client.post(
        f"{base}/overrides",
        json={
            "idempotency_key": "k-unattached-1",
            "adventure_entry_id": str(fix.unattached_entry_id),
            "state": {},
        },
        headers=_auth(fix.token_owner_a),
    )
    assert r_unattached.status_code == 422
    assert r_unattached.json()["error"]["code"] == "campaign_runtime_invalid"

    # 2. Override on non-existent entry -> 404 campaign_runtime_not_found
    r_missing = fix.client.post(
        f"{base}/overrides",
        json={
            "idempotency_key": "k-missing-entry",
            "adventure_entry_id": str(uuid4()),
            "state": {},
        },
        headers=_auth(fix.token_owner_a),
    )
    assert r_missing.status_code == 404
    assert r_missing.json()["error"]["code"] == "campaign_runtime_not_found"

    # 3. Create valid override
    r_valid = fix.client.post(
        f"{base}/overrides",
        json={
            "idempotency_key": "k-valid-ovr",
            "adventure_entry_id": str(fix.npc_entry_id),
            "state": {"disposition": "hostile"},
        },
        headers=_auth(fix.token_owner_a),
    )
    assert r_valid.status_code == 201

    # 4. Attempt to create duplicate override -> 409 campaign_runtime_override_exists
    r_dup = fix.client.post(
        f"{base}/overrides",
        json={
            "idempotency_key": "k-dup-ovr",
            "adventure_entry_id": str(fix.npc_entry_id),
            "state": {"disposition": "friendly"},
        },
        headers=_auth(fix.token_owner_a),
    )
    assert r_dup.status_code == 409
    assert r_dup.json()["error"]["code"] == "campaign_runtime_override_exists"


def test_invalid_and_dual_scene_references_in_context(
    api_fixture: RuntimeApiFixture,
) -> None:
    fix = api_fixture
    base = f"/api/rooms/{fix.room_a_id}/campaigns/{fix.campaign_a1_id}/runtime"

    # Create a runtime scene and a runtime fact
    scene_resp = fix.client.post(
        f"{base}/entries",
        json={"idempotency_key": "k-rt-scene", "kind": "scene", "title": "Runtime Scene"},
        headers=_auth(fix.token_owner_a),
    )
    assert scene_resp.status_code == 201
    rt_scene_id = scene_resp.json()["id"]

    fact_resp = fix.client.post(
        f"{base}/entries",
        json={"idempotency_key": "k-rt-fact", "kind": "fact", "body": "Runtime Fact"},
        headers=_auth(fix.token_owner_a),
    )
    assert fact_resp.status_code == 201
    rt_fact_id = fact_resp.json()["id"]

    # 1. Both scene references set -> 422 campaign_runtime_invalid
    r_dual = fix.client.patch(
        f"{base}/context",
        json={
            "idempotency_key": "k-ctx-dual",
            "expected_revision": 0,
            "current_adventure_scene_entry_id": str(fix.scene_entry_id),
            "current_runtime_scene_entry_id": rt_scene_id,
        },
        headers=_auth(fix.token_owner_a),
    )
    assert r_dual.status_code == 422
    assert r_dual.json()["error"]["code"] == "campaign_runtime_invalid"

    # 2. Adventure entry is not a scene (it's an NPC) -> 422 campaign_runtime_invalid
    r_non_scene_adv = fix.client.patch(
        f"{base}/context",
        json={
            "idempotency_key": "k-ctx-bad-adv",
            "expected_revision": 0,
            "current_adventure_scene_entry_id": str(fix.npc_entry_id),
        },
        headers=_auth(fix.token_owner_a),
    )
    assert r_non_scene_adv.status_code == 422
    assert r_non_scene_adv.json()["error"]["code"] == "campaign_runtime_invalid"

    # 3. Runtime entry is not a scene (it's a fact) -> 422 campaign_runtime_invalid
    r_non_scene_rt = fix.client.patch(
        f"{base}/context",
        json={
            "idempotency_key": "k-ctx-bad-rt",
            "expected_revision": 0,
            "current_runtime_scene_entry_id": rt_fact_id,
        },
        headers=_auth(fix.token_owner_a),
    )
    assert r_non_scene_rt.status_code == 422
    assert r_non_scene_rt.json()["error"]["code"] == "campaign_runtime_invalid"

    # 4. Non-existent adventure entry -> 404 campaign_runtime_not_found
    r_missing_adv = fix.client.patch(
        f"{base}/context",
        json={
            "idempotency_key": "k-ctx-miss-adv",
            "expected_revision": 0,
            "current_adventure_scene_entry_id": str(uuid4()),
        },
        headers=_auth(fix.token_owner_a),
    )
    assert r_missing_adv.status_code == 404
    assert r_missing_adv.json()["error"]["code"] == "campaign_runtime_not_found"

    # 5. Non-existent runtime entry -> 404 campaign_runtime_not_found
    r_missing_rt = fix.client.patch(
        f"{base}/context",
        json={
            "idempotency_key": "k-ctx-miss-rt",
            "expected_revision": 0,
            "current_runtime_scene_entry_id": str(uuid4()),
        },
        headers=_auth(fix.token_owner_a),
    )
    assert r_missing_rt.status_code == 404
    assert r_missing_rt.json()["error"]["code"] == "campaign_runtime_not_found"


def test_stale_override_and_context_revisions(api_fixture: RuntimeApiFixture) -> None:
    fix = api_fixture
    base = f"/api/rooms/{fix.room_a_id}/campaigns/{fix.campaign_a1_id}/runtime"

    # Create an override
    c_resp = fix.client.post(
        f"{base}/overrides",
        json={
            "idempotency_key": "k-stale-ovr-create",
            "adventure_entry_id": str(fix.npc_entry_id),
            "state": {"disposition": "hostile"},
        },
        headers=_auth(fix.token_owner_a),
    )
    assert c_resp.status_code == 201
    ovr_id = c_resp.json()["id"]

    # 1. PATCH override with wrong expected_override_id -> 409
    r1 = fix.client.patch(
        f"{base}/overrides/{fix.npc_entry_id}",
        json={
            "idempotency_key": "k-stale-p1",
            "expected_override_id": str(uuid4()),
            "expected_revision": 1,
            "note": "Bad id",
        },
        headers=_auth(fix.token_owner_a),
    )
    assert r1.status_code == 409
    assert r1.json()["error"]["code"] == "campaign_runtime_revision_conflict"

    # 2. PATCH override with wrong expected_revision -> 409
    r2 = fix.client.patch(
        f"{base}/overrides/{fix.npc_entry_id}",
        json={
            "idempotency_key": "k-stale-p2",
            "expected_override_id": ovr_id,
            "expected_revision": 999,
            "note": "Bad rev",
        },
        headers=_auth(fix.token_owner_a),
    )
    assert r2.status_code == 409
    assert r2.json()["error"]["code"] == "campaign_runtime_revision_conflict"

    # 3. POST clear override with wrong expected_override_id -> 409
    r3 = fix.client.post(
        f"{base}/overrides/{fix.npc_entry_id}/clear",
        json={
            "idempotency_key": "k-stale-c1",
            "expected_override_id": str(uuid4()),
            "expected_revision": 1,
        },
        headers=_auth(fix.token_owner_a),
    )
    assert r3.status_code == 409
    assert r3.json()["error"]["code"] == "campaign_runtime_revision_conflict"

    # 4. POST clear override with wrong expected_revision -> 409
    r4 = fix.client.post(
        f"{base}/overrides/{fix.npc_entry_id}/clear",
        json={
            "idempotency_key": "k-stale-c2",
            "expected_override_id": ovr_id,
            "expected_revision": 999,
        },
        headers=_auth(fix.token_owner_a),
    )
    assert r4.status_code == 409
    assert r4.json()["error"]["code"] == "campaign_runtime_revision_conflict"

    # 5. PATCH context with wrong expected_revision -> 409
    r5 = fix.client.patch(
        f"{base}/context",
        json={
            "idempotency_key": "k-stale-ctx-p",
            "expected_revision": 999,
            "current_situation": "Stale",
        },
        headers=_auth(fix.token_owner_a),
    )
    assert r5.status_code == 409
    assert r5.json()["error"]["code"] == "campaign_runtime_revision_conflict"

    # 6. POST clear context with wrong expected_revision -> 409
    r6 = fix.client.post(
        f"{base}/context/clear",
        json={
            "idempotency_key": "k-stale-ctx-c",
            "expected_revision": 999,
        },
        headers=_auth(fix.token_owner_a),
    )
    assert r6.status_code == 409
    assert r6.json()["error"]["code"] == "campaign_runtime_revision_conflict"


def test_active_session_blocks_override_and_context_mutations_but_allows_reads(
    api_fixture: RuntimeApiFixture,
) -> None:
    fix = api_fixture
    base = f"/api/rooms/{fix.room_a_id}/campaigns/{fix.campaign_active_id}/runtime"

    # Reads are permitted
    r_ovrs = fix.client.get(f"{base}/overrides", headers=_auth(fix.token_owner_a))
    assert r_ovrs.status_code == 200

    r_ctx = fix.client.get(f"{base}/context", headers=_auth(fix.token_owner_a))
    assert r_ctx.status_code == 200

    r_overlay = fix.client.get(
        f"{base}/adventure-overlays/{fix.npc_entry_id}",
        headers=_auth(fix.token_owner_a),
    )
    assert r_overlay.status_code == 200

    r_adv_overlays = fix.client.get(
        f"{base}/adventures/{fix.adv_1_id}/overlays",
        headers=_auth(fix.token_owner_a),
    )
    assert r_adv_overlays.status_code == 200

    # Mutations are blocked with 409 campaign_runtime_active_session
    m1 = fix.client.post(
        f"{base}/overrides",
        json={
            "idempotency_key": "k-act-ovr-c",
            "adventure_entry_id": str(fix.npc_entry_id),
            "state": {"disposition": "hostile"},
        },
        headers=_auth(fix.token_owner_a),
    )
    assert m1.status_code == 409
    assert m1.json()["error"]["code"] == "campaign_runtime_active_session"

    m2 = fix.client.patch(
        f"{base}/overrides/{fix.npc_entry_id}",
        json={
            "idempotency_key": "k-act-ovr-p",
            "expected_override_id": str(uuid4()),
            "expected_revision": 1,
            "note": "Blocked",
        },
        headers=_auth(fix.token_owner_a),
    )
    assert m2.status_code == 409
    assert m2.json()["error"]["code"] == "campaign_runtime_active_session"

    m3 = fix.client.post(
        f"{base}/overrides/{fix.npc_entry_id}/clear",
        json={
            "idempotency_key": "k-act-ovr-clr",
            "expected_override_id": str(uuid4()),
            "expected_revision": 1,
        },
        headers=_auth(fix.token_owner_a),
    )
    assert m3.status_code == 409
    assert m3.json()["error"]["code"] == "campaign_runtime_active_session"

    m4 = fix.client.patch(
        f"{base}/context",
        json={
            "idempotency_key": "k-act-ctx-p",
            "expected_revision": 0,
            "current_situation": "Blocked",
        },
        headers=_auth(fix.token_owner_a),
    )
    assert m4.status_code == 409
    assert m4.json()["error"]["code"] == "campaign_runtime_active_session"

    m5 = fix.client.post(
        f"{base}/context/clear",
        json={
            "idempotency_key": "k-act-ctx-clr",
            "expected_revision": 0,
        },
        headers=_auth(fix.token_owner_a),
    )
    assert m5.status_code == 409
    assert m5.json()["error"]["code"] == "campaign_runtime_active_session"


def test_override_and_context_idempotency_replay_and_conflict(
    api_fixture: RuntimeApiFixture,
) -> None:
    fix = api_fixture
    base = f"/api/rooms/{fix.room_a_id}/campaigns/{fix.campaign_a1_id}/runtime"

    # 1. Override create replay and conflict
    c_body = {
        "idempotency_key": "k-idem-ovr-c",
        "adventure_entry_id": str(fix.npc_entry_id),
        "state": {"disposition": "hostile"},
        "note": "First note",
    }
    r1 = fix.client.post(f"{base}/overrides", json=c_body, headers=_auth(fix.token_owner_a))
    assert r1.status_code == 201
    ovr_id = r1.json()["id"]

    # Replay
    r2 = fix.client.post(f"{base}/overrides", json=c_body, headers=_auth(fix.token_owner_a))
    assert r2.status_code == 201
    assert r2.json()["id"] == ovr_id

    # Conflict
    c_conflict = dict(c_body)
    c_conflict["note"] = "Different note"
    r3 = fix.client.post(f"{base}/overrides", json=c_conflict, headers=_auth(fix.token_owner_a))
    assert r3.status_code == 409
    assert r3.json()["error"]["code"] == "campaign_runtime_idempotency_conflict"

    # 2. Override patch replay and conflict
    p_body = {
        "idempotency_key": "k-idem-ovr-p",
        "expected_override_id": ovr_id,
        "expected_revision": 1,
        "note": "Updated note",
    }
    p1 = fix.client.patch(f"{base}/overrides/{fix.npc_entry_id}", json=p_body, headers=_auth(fix.token_owner_a))
    assert p1.status_code == 200
    assert p1.json()["revision"] == 2

    # Replay
    p2 = fix.client.patch(f"{base}/overrides/{fix.npc_entry_id}", json=p_body, headers=_auth(fix.token_owner_a))
    assert p2.status_code == 200
    assert p2.json()["revision"] == 2

    # Conflict
    p_conflict = dict(p_body)
    p_conflict["note"] = "Conflicting note"
    p3 = fix.client.patch(f"{base}/overrides/{fix.npc_entry_id}", json=p_conflict, headers=_auth(fix.token_owner_a))
    assert p3.status_code == 409
    assert p3.json()["error"]["code"] == "campaign_runtime_idempotency_conflict"

    # 3. Override clear replay and conflict
    clr_body = {
        "idempotency_key": "k-idem-ovr-clr",
        "expected_override_id": ovr_id,
        "expected_revision": 2,
    }
    clr1 = fix.client.post(f"{base}/overrides/{fix.npc_entry_id}/clear", json=clr_body, headers=_auth(fix.token_owner_a))
    assert clr1.status_code == 200

    # Replay
    clr2 = fix.client.post(f"{base}/overrides/{fix.npc_entry_id}/clear", json=clr_body, headers=_auth(fix.token_owner_a))
    assert clr2.status_code == 200

    # Conflict
    clr_conflict = dict(clr_body)
    clr_conflict["expected_revision"] = 999
    clr3 = fix.client.post(f"{base}/overrides/{fix.npc_entry_id}/clear", json=clr_conflict, headers=_auth(fix.token_owner_a))
    assert clr3.status_code == 409
    assert clr3.json()["error"]["code"] == "campaign_runtime_idempotency_conflict"

    # 4. Context patch replay and conflict
    ctx_p_body = {
        "idempotency_key": "k-idem-ctx-p",
        "expected_revision": 0,
        "current_situation": "In the inn",
    }
    cp1 = fix.client.patch(f"{base}/context", json=ctx_p_body, headers=_auth(fix.token_owner_a))
    assert cp1.status_code == 200
    assert cp1.json()["revision"] == 1

    # Replay
    cp2 = fix.client.patch(f"{base}/context", json=ctx_p_body, headers=_auth(fix.token_owner_a))
    assert cp2.status_code == 200
    assert cp2.json()["revision"] == 1

    # Conflict
    cp_conflict = dict(ctx_p_body)
    cp_conflict["current_situation"] = "Outside the inn"
    cp3 = fix.client.patch(f"{base}/context", json=cp_conflict, headers=_auth(fix.token_owner_a))
    assert cp3.status_code == 409
    assert cp3.json()["error"]["code"] == "campaign_runtime_idempotency_conflict"

    # 5. Context clear replay and conflict
    ctx_clr_body = {
        "idempotency_key": "k-idem-ctx-clr",
        "expected_revision": 1,
    }
    ccl1 = fix.client.post(f"{base}/context/clear", json=ctx_clr_body, headers=_auth(fix.token_owner_a))
    assert ccl1.status_code == 200
    assert ccl1.json()["revision"] == 2

    # Replay
    ccl2 = fix.client.post(f"{base}/context/clear", json=ctx_clr_body, headers=_auth(fix.token_owner_a))
    assert ccl2.status_code == 200
    assert ccl2.json()["revision"] == 2

    # Conflict
    ccl_conflict = dict(ctx_clr_body)
    ccl_conflict["expected_revision"] = 999
    ccl3 = fix.client.post(f"{base}/context/clear", json=ccl_conflict, headers=_auth(fix.token_owner_a))
    assert ccl3.status_code == 409
    assert ccl3.json()["error"]["code"] == "campaign_runtime_idempotency_conflict"


def test_clear_removes_detach_blockers_via_api(api_fixture: RuntimeApiFixture) -> None:
    fix = api_fixture
    base = f"/api/rooms/{fix.room_a_id}/campaigns/{fix.campaign_a1_id}/runtime"
    detach_url = (
        f"/api/rooms/{fix.room_a_id}/campaigns/{fix.campaign_a1_id}"
        f"/adventures/{fix.adv_1_id}"
    )

    # 1. Override blocker
    create_resp = fix.client.post(
        f"{base}/overrides",
        json={
            "idempotency_key": "k-blocker-ovr",
            "adventure_entry_id": str(fix.npc_entry_id),
            "state": {"disposition": "hostile"},
        },
        headers=_auth(fix.token_owner_a),
    )
    assert create_resp.status_code == 201
    ovr_id = create_resp.json()["id"]

    # Detach fails through the public route with a stable machine code.
    blocked_override = fix.client.delete(detach_url, headers=_auth(fix.token_owner_a))
    assert blocked_override.status_code == 409
    assert blocked_override.json()["error"]["code"] == "campaign_adventure_detach_blocked"

    # Clear override via API
    clear_resp = fix.client.post(
        f"{base}/overrides/{fix.npc_entry_id}/clear",
        json={
            "idempotency_key": "k-blocker-ovr-clear",
            "expected_override_id": ovr_id,
            "expected_revision": 1,
        },
        headers=_auth(fix.token_owner_a),
    )
    assert clear_resp.status_code == 200

    # Detach now succeeds through the same public route.
    detached_override = fix.client.delete(detach_url, headers=_auth(fix.token_owner_a))
    assert detached_override.status_code == 204

    # 2. Context scene blocker
    # Re-attach adventure
    fix.adv_service.attach(
        fix.owner_context_a,
        fix.room_a_id,
        fix.campaign_a1_id,
        CampaignAdventureAttach(adventure_id=fix.adv_1_id),
    )

    # Set context current adventure scene via API
    patch_ctx = fix.client.patch(
        f"{base}/context",
        json={
            "idempotency_key": "k-blocker-ctx-p",
            "expected_revision": 0,
            "current_adventure_scene_entry_id": str(fix.scene_entry_id),
        },
        headers=_auth(fix.token_owner_a),
    )
    assert patch_ctx.status_code == 200

    # The other blocker has the same stable public error contract.
    blocked_context = fix.client.delete(detach_url, headers=_auth(fix.token_owner_a))
    assert blocked_context.status_code == 409
    assert blocked_context.json()["error"]["code"] == "campaign_adventure_detach_blocked"

    # Clear context via API
    clear_ctx_resp = fix.client.post(
        f"{base}/context/clear",
        json={
            "idempotency_key": "k-blocker-ctx-clr",
            "expected_revision": 1,
        },
        headers=_auth(fix.token_owner_a),
    )
    assert clear_ctx_resp.status_code == 200

    detached_context = fix.client.delete(detach_url, headers=_auth(fix.token_owner_a))
    assert detached_context.status_code == 204


def test_rejected_override_and_context_leave_zero_side_effects(
    api_fixture: RuntimeApiFixture,
) -> None:
    fix = api_fixture
    base = f"/api/rooms/{fix.room_a_id}/campaigns/{fix.campaign_a1_id}/runtime"

    # Create a valid override to set a baseline state
    c_resp = fix.client.post(
        f"{base}/overrides",
        json={
            "idempotency_key": "k-zero-ovr-init",
            "adventure_entry_id": str(fix.npc_entry_id),
            "state": {"disposition": "hostile"},
        },
        headers=_auth(fix.token_owner_a),
    )
    assert c_resp.status_code == 201
    ovr_id = c_resp.json()["id"]

    snap_before = _snapshot_runtime_state(fix)

    # 1. Stale revision override patch
    r1 = fix.client.patch(
        f"{base}/overrides/{fix.npc_entry_id}",
        json={
            "idempotency_key": "k-zero-fail-1",
            "expected_override_id": ovr_id,
            "expected_revision": 999,
            "note": "Will fail",
        },
        headers=_auth(fix.token_owner_a),
    )
    assert r1.status_code == 409
    assert _snapshot_runtime_state(fix) == snap_before

    # 2. Dual scene in context patch (422)
    r2 = fix.client.patch(
        f"{base}/context",
        json={
            "idempotency_key": "k-zero-fail-2",
            "expected_revision": 0,
            "current_adventure_scene_entry_id": str(fix.scene_entry_id),
            "current_runtime_scene_entry_id": str(uuid4()),
        },
        headers=_auth(fix.token_owner_a),
    )
    assert r2.status_code == 422
    assert _snapshot_runtime_state(fix) == snap_before

    # 3. Unauthorized player patch (403)
    r3 = fix.client.patch(
        f"{base}/overrides/{fix.npc_entry_id}",
        json={
            "idempotency_key": "k-zero-fail-3",
            "expected_override_id": ovr_id,
            "expected_revision": 1,
            "note": "Player hack",
        },
        headers=_auth(fix.token_member_a),
    )
    assert r3.status_code == 403
    assert _snapshot_runtime_state(fix) == snap_before

    # 4. Active session block on active campaign (409)
    active_base = f"/api/rooms/{fix.room_a_id}/campaigns/{fix.campaign_active_id}/runtime"
    r4 = fix.client.post(
        f"{active_base}/overrides",
        json={
            "idempotency_key": "k-zero-fail-4",
            "adventure_entry_id": str(fix.npc_entry_id),
            "state": {"disposition": "friendly"},
        },
        headers=_auth(fix.token_owner_a),
    )
    assert r4.status_code == 409
    assert _snapshot_runtime_state(fix) == snap_before


class RecordingNotifier:
    def __init__(self) -> None:
        self.notifications: list[UUID] = []

    def notify(self, session_id: UUID) -> None:
        self.notifications.append(session_id)

    def register(self, session_id: UUID) -> object:
        return object()

    async def wait(self, handle: object, timeout: float) -> bool:
        return False

    def unregister(self, handle: object) -> None:
        pass


@dataclass(frozen=True)
class ActiveSessionApiFixture:
    client: TestClient
    engine: Engine
    room_id: UUID
    campaign_id: UUID
    session_id: UUID
    inactive_session_id: UUID
    dm_seat_id: UUID
    player_1_seat_id: UUID
    player_2_seat_id: UUID
    char_1_id: UUID
    char_2_id: UUID
    p2_access_id: UUID
    token_dm: str
    token_player_1: str
    token_player_2: str
    token_nonparticipant: str
    entry_public_id: UUID
    entry_own_id: UUID
    entry_other_id: UUID
    entry_dm_only_id: UUID
    adv_attached_id: UUID
    adv_unattached_id: UUID
    adv_entry_scene_id: UUID
    adv_entry_npc_id: UUID
    adv_entry_unattached_id: UUID
    notifier: RecordingNotifier


@pytest.fixture
def active_api_fixture() -> Generator[ActiveSessionApiFixture, None, None]:
    engine = _engine()
    notifier = RecordingNotifier()
    event_service = TableEventService(TableEventRepository(engine), notifier=notifier)
    runtime_service = CampaignRuntimeService(engine, event_service)

    room_id = uuid4()
    campaign_id = uuid4()
    session_id = uuid4()
    inactive_session_id = uuid4()
    now = datetime.now(timezone.utc)

    dm_access_id = uuid4()
    p1_access_id = uuid4()
    p2_access_id = uuid4()
    nonparticipant_access_id = uuid4()

    dm_seat_id = uuid4()
    p1_seat_id = uuid4()
    p2_seat_id = uuid4()

    char_1_id = uuid4()
    char_2_id = uuid4()

    entry_public_id = uuid4()
    entry_own_id = uuid4()
    entry_other_id = uuid4()
    entry_dm_only_id = uuid4()

    adv_attached_id = uuid4()
    adv_unattached_id = uuid4()
    adv_entry_scene_id = uuid4()
    adv_entry_npc_id = uuid4()
    adv_entry_unattached_id = uuid4()

    token_dm = "tok-act-dm"
    token_player_1 = "tok-act-p1"
    token_player_2 = "tok-act-p2"
    token_nonparticipant = "tok-act-nonpart"

    with engine.begin() as conn:
        conn.execute(
            insert(rooms).values(
                id=room_id,
                code="ROOM-ACT",
                name="Active Room",
                password_salt=b"salt",
                password_hash=b"pw",
                owner_key_hash=b"owner",
                dm_key_hash=b"dm",
                created_at=now,
                updated_at=now,
            )
        )
        conn.execute(
            insert(room_access_sessions).values(
                [
                    {
                        "id": dm_access_id,
                        "room_id": room_id,
                        "authority": "dm",
                        "token_hash": b"tok_dm_hash_1234567890123",
                        "display_name": "DM",
                        "created_at": now,
                        "last_seen_at": now,
                    },
                    {
                        "id": p1_access_id,
                        "room_id": room_id,
                        "authority": "member",
                        "token_hash": b"tok_p1_hash_1234567890123",
                        "display_name": "Player 1",
                        "created_at": now,
                        "last_seen_at": now,
                    },
                    {
                        "id": p2_access_id,
                        "room_id": room_id,
                        "authority": "member",
                        "token_hash": b"tok_p2_hash_1234567890123",
                        "display_name": "Player 2",
                        "created_at": now,
                        "last_seen_at": now,
                    },
                    {
                        "id": nonparticipant_access_id,
                        "room_id": room_id,
                        "authority": "member",
                        "token_hash": b"tok_nonpart_hash_12345678",
                        "display_name": "Nonparticipant",
                        "created_at": now,
                        "last_seen_at": now,
                    },
                ]
            )
        )
        conn.execute(
            insert(campaigns).values(
                id=campaign_id,
                room_id=room_id,
                name="Active Campaign",
                ruleset="dnd5e-2014",
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
        for cid, name in [(char_1_id, "Fighter 1"), (char_2_id, "Wizard 2")]:
            conn.execute(
                insert(characters).values(
                    id=cid,
                    name=name,
                    ruleset="dnd5e-2014",
                    created_at=now,
                    updated_at=now,
                )
            )
            conn.execute(
                insert(room_characters).values(
                    room_id=room_id,
                    character_id=cid,
                    created_at=now,
                )
            )
        conn.execute(
            insert(campaign_seats).values(
                [
                    {
                        "id": dm_seat_id,
                        "campaign_id": campaign_id,
                        "role": "dm",
                        "controller_kind": "human",
                        "controller_access_session_id": dm_access_id,
                        "ai_controller_grant_id": None,
                        "controller_epoch": 1,
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": p1_seat_id,
                        "campaign_id": campaign_id,
                        "role": "player",
                        "controller_kind": "human",
                        "controller_access_session_id": p1_access_id,
                        "ai_controller_grant_id": None,
                        "controller_epoch": 1,
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": p2_seat_id,
                        "campaign_id": campaign_id,
                        "role": "player",
                        "controller_kind": "human",
                        "controller_access_session_id": p2_access_id,
                        "ai_controller_grant_id": None,
                        "controller_epoch": 1,
                        "created_at": now,
                        "updated_at": now,
                    },
                ]
            )
        )
        conn.execute(
            insert(sessions).values(
                [
                    {
                        "id": session_id,
                        "campaign_id": campaign_id,
                        "status": "active",
                        "dm_seat_id": dm_seat_id,
                        "dm_controller_kind": "human",
                        "dm_controller_access_session_id": dm_access_id,
                        "started_at": now,
                        "created_at": now,
                    },
                    {
                        "id": inactive_session_id,
                        "campaign_id": campaign_id,
                        "status": "ended",
                        "dm_seat_id": dm_seat_id,
                        "dm_controller_kind": "human",
                        "dm_controller_access_session_id": dm_access_id,
                        "started_at": now,
                        "ended_at": now,
                        "created_at": now,
                    },
                ]
            )
        )
        conn.execute(
            insert(session_participants).values(
                [
                    {
                        "id": uuid4(),
                        "session_id": session_id,
                        "seat_id": dm_seat_id,
                        "role_snapshot": "dm",
                        "controller_kind_at_join": "human",
                        "controller_access_session_id_at_join": dm_access_id,
                        "controller_ai_grant_id_at_join": None,
                        "controller_generation_at_join": None,
                        "active_character_id": None,
                        "joined_at": now,
                    },
                    {
                        "id": uuid4(),
                        "session_id": session_id,
                        "seat_id": p1_seat_id,
                        "role_snapshot": "player",
                        "controller_kind_at_join": "human",
                        "controller_access_session_id_at_join": p1_access_id,
                        "controller_ai_grant_id_at_join": None,
                        "controller_generation_at_join": None,
                        "active_character_id": char_1_id,
                        "joined_at": now,
                    },
                    {
                        "id": uuid4(),
                        "session_id": session_id,
                        "seat_id": p2_seat_id,
                        "role_snapshot": "player",
                        "controller_kind_at_join": "human",
                        "controller_access_session_id_at_join": p2_access_id,
                        "controller_ai_grant_id_at_join": None,
                        "controller_generation_at_join": None,
                        "active_character_id": char_2_id,
                        "joined_at": now,
                    },
                ]
            )
        )
        conn.execute(
            insert(adventure_definitions).values(
                [
                    {
                        "id": adv_attached_id,
                        "room_id": room_id,
                        "name": "Attached Adventure",
                        "summary": "Adventure attached to active campaign",
                        "ruleset": "dnd5e-2014",
                        "status": "finalized",
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": adv_unattached_id,
                        "room_id": room_id,
                        "name": "Unattached Adventure",
                        "summary": "Adventure not attached",
                        "ruleset": "dnd5e-2014",
                        "status": "finalized",
                        "created_at": now,
                        "updated_at": now,
                    },
                ]
            )
        )
        conn.execute(
            insert(adventure_entries).values(
                [
                    {
                        "id": adv_entry_scene_id,
                        "adventure_id": adv_attached_id,
                        "parent_entry_id": None,
                        "kind": "scene",
                        "title": "Old Mill",
                        "body": "An abandoned water mill",
                        "data_json": {},
                        "visibility": "public",
                        "sort_order": 1,
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": adv_entry_npc_id,
                        "adventure_id": adv_attached_id,
                        "parent_entry_id": None,
                        "kind": "npc",
                        "title": "Miller John",
                        "body": "Retired miller",
                        "data_json": {},
                        "visibility": "public",
                        "sort_order": 2,
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": adv_entry_unattached_id,
                        "adventure_id": adv_unattached_id,
                        "parent_entry_id": None,
                        "kind": "scene",
                        "title": "Sunken Crypt",
                        "body": "Crypt in unattached adventure",
                        "data_json": {},
                        "visibility": "public",
                        "sort_order": 1,
                        "created_at": now,
                        "updated_at": now,
                    },
                ]
            )
        )
        conn.execute(
            insert(campaign_adventure_links).values(
                campaign_id=campaign_id,
                adventure_id=adv_attached_id,
                sort_order=1,
                attached_at=now,
            )
        )
        conn.execute(
            insert(campaign_world_entries).values(
                [
                    {
                        "id": entry_public_id,
                        "campaign_id": campaign_id,
                        "kind": "scene",
                        "title": "Town Square",
                        "body": "A bustling public town square",
                        "state_json": {},
                        "dm_notes": "Hidden smugglers tunnel beneath the fountain",
                        "visibility": "public",
                        "needs_review": False,
                        "source_adventure_entry_id": None,
                        "provenance_json": None,
                        "revision": 1,
                        "created_by_actor_kind": "human",
                        "created_by_actor_id": dm_access_id,
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": entry_own_id,
                        "campaign_id": campaign_id,
                        "kind": "secret",
                        "title": "Fighter Heirloom",
                        "body": "Family crest sword passed down generations",
                        "state_json": {},
                        "dm_notes": None,
                        "visibility": "character",
                        "needs_review": False,
                        "source_adventure_entry_id": None,
                        "provenance_json": None,
                        "revision": 1,
                        "created_by_actor_kind": "human",
                        "created_by_actor_id": dm_access_id,
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": entry_other_id,
                        "campaign_id": campaign_id,
                        "kind": "secret",
                        "title": "Wizard Spellbook",
                        "body": "Forbidden spell inscribed in invisible ink",
                        "state_json": {},
                        "dm_notes": None,
                        "visibility": "character",
                        "needs_review": False,
                        "source_adventure_entry_id": None,
                        "provenance_json": None,
                        "revision": 1,
                        "created_by_actor_kind": "human",
                        "created_by_actor_id": dm_access_id,
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": entry_dm_only_id,
                        "campaign_id": campaign_id,
                        "kind": "secret",
                        "title": "Vampire Lord Secret",
                        "body": "The local priest is secretly a vampire",
                        "state_json": {},
                        "dm_notes": "Bite marks on his neck are concealed with illusion",
                        "visibility": "dm_only",
                        "needs_review": False,
                        "source_adventure_entry_id": None,
                        "provenance_json": None,
                        "revision": 1,
                        "created_by_actor_kind": "human",
                        "created_by_actor_id": dm_access_id,
                        "created_at": now,
                        "updated_at": now,
                    },
                ]
            )
        )
        conn.execute(
            insert(campaign_world_entry_characters).values(
                [
                    {"world_entry_id": entry_own_id, "character_id": char_1_id},
                    {"world_entry_id": entry_other_id, "character_id": char_2_id},
                ]
            )
        )

    token_to_context = {
        token_dm: RoomAccessContext(
            room_id=room_id,
            access_session_id=dm_access_id,
            authority=RoomAccessAuthority.DM,
            display_name="DM",
        ),
        token_player_1: RoomAccessContext(
            room_id=room_id,
            access_session_id=p1_access_id,
            authority=RoomAccessAuthority.MEMBER,
            display_name="Player 1",
        ),
        token_player_2: RoomAccessContext(
            room_id=room_id,
            access_session_id=p2_access_id,
            authority=RoomAccessAuthority.MEMBER,
            display_name="Player 2",
        ),
        token_nonparticipant: RoomAccessContext(
            room_id=room_id,
            access_session_id=nonparticipant_access_id,
            authority=RoomAccessAuthority.MEMBER,
            display_name="Nonparticipant",
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
    fastapi_app.state.table_event_service = event_service
    fastapi_app.dependency_overrides[get_database_engine] = lambda: engine
    fastapi_app.dependency_overrides[get_room_access_context] = _override_access_context
    fastapi_app.dependency_overrides[get_campaign_runtime_service] = lambda: runtime_service
    fastapi_app.dependency_overrides[get_table_event_service] = lambda: event_service

    client = TestClient(fastapi_app)
    try:
        yield ActiveSessionApiFixture(
            client=client,
            engine=engine,
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            inactive_session_id=inactive_session_id,
            dm_seat_id=dm_seat_id,
            player_1_seat_id=p1_seat_id,
            player_2_seat_id=p2_seat_id,
            char_1_id=char_1_id,
            char_2_id=char_2_id,
            p2_access_id=p2_access_id,
            token_dm=token_dm,
            token_player_1=token_player_1,
            token_player_2=token_player_2,
            token_nonparticipant=token_nonparticipant,
            entry_public_id=entry_public_id,
            entry_own_id=entry_own_id,
            entry_other_id=entry_other_id,
            entry_dm_only_id=entry_dm_only_id,
            adv_attached_id=adv_attached_id,
            adv_unattached_id=adv_unattached_id,
            adv_entry_scene_id=adv_entry_scene_id,
            adv_entry_npc_id=adv_entry_npc_id,
            adv_entry_unattached_id=adv_entry_unattached_id,
            notifier=notifier,
        )
    finally:
        try:
            del fastapi_app.state.campaign_runtime_service
        except AttributeError:
            pass
        try:
            del fastapi_app.state.table_event_service
        except AttributeError:
            pass
        fastapi_app.dependency_overrides.pop(get_database_engine, None)
        fastapi_app.dependency_overrides.pop(get_room_access_context, None)
        fastapi_app.dependency_overrides.pop(get_campaign_runtime_service, None)
        fastapi_app.dependency_overrides.pop(get_table_event_service, None)


def test_active_session_player_secrecy_matrix_list_and_item(
    active_api_fixture: ActiveSessionApiFixture,
) -> None:
    fix = active_api_fixture
    base = f"/api/rooms/{fix.room_id}/campaigns/{fix.campaign_id}/sessions/{fix.session_id}/runtime/entries"

    # 1. Player 1 lists entries: should see public + own character only
    resp = fix.client.get(base, headers=_auth(fix.token_player_1))
    assert resp.status_code == 200
    entries = resp.json()
    assert len(entries) == 2
    entry_ids = {e["id"] for e in entries}
    assert entry_ids == {str(fix.entry_public_id), str(fix.entry_own_id)}
    assert str(fix.entry_other_id) not in entry_ids
    assert str(fix.entry_dm_only_id) not in entry_ids

    # Assert raw JSON keys for player view: exact fields, zero leakage
    expected_player_keys = {
        "id",
        "campaign_id",
        "kind",
        "title",
        "body",
        "state",
        "visibility",
        "revision",
        "created_at",
        "updated_at",
    }
    forbidden_keys = {
        "dm_notes",
        "character_recipient_ids",
        "needs_review",
        "source_adventure_entry_id",
        "provenance_json",
        "created_by_actor_kind",
        "created_by_actor_id",
        "archived_at",
    }
    for item in entries:
        assert set(item.keys()) == expected_player_keys
        for forbidden in forbidden_keys:
            assert forbidden not in item

    # 2. Player 1 GET item: public entry
    pub_resp = fix.client.get(f"{base}/{fix.entry_public_id}", headers=_auth(fix.token_player_1))
    assert pub_resp.status_code == 200
    pub_json = pub_resp.json()
    assert set(pub_json.keys()) == expected_player_keys
    assert "dm_notes" not in pub_json

    # 3. Player 1 GET item: own character entry
    own_resp = fix.client.get(f"{base}/{fix.entry_own_id}", headers=_auth(fix.token_player_1))
    assert own_resp.status_code == 200
    own_json = own_resp.json()
    assert set(own_json.keys()) == expected_player_keys
    assert "character_recipient_ids" not in own_json
    assert "dm_notes" not in own_json

    # 4. Player 1 GET item: other character entry -> 404 (not a visibility oracle)
    other_resp = fix.client.get(f"{base}/{fix.entry_other_id}", headers=_auth(fix.token_player_1))
    assert other_resp.status_code == 404
    assert other_resp.json()["error"]["code"] == "campaign_runtime_not_found"

    # 5. Player 1 GET item: dm_only entry -> 404
    dm_resp = fix.client.get(f"{base}/{fix.entry_dm_only_id}", headers=_auth(fix.token_player_1))
    assert dm_resp.status_code == 404
    assert dm_resp.json()["error"]["code"] == "campaign_runtime_not_found"


def test_active_session_dm_full_view(
    active_api_fixture: ActiveSessionApiFixture,
) -> None:
    fix = active_api_fixture
    base = f"/api/rooms/{fix.room_id}/campaigns/{fix.campaign_id}/sessions/{fix.session_id}/runtime/entries"

    # 1. DM lists entries: should see all 4 entries with full DM view
    resp = fix.client.get(base, headers=_auth(fix.token_dm))
    assert resp.status_code == 200
    entries = resp.json()
    assert len(entries) == 4
    entry_ids = {e["id"] for e in entries}
    assert entry_ids == {
        str(fix.entry_public_id),
        str(fix.entry_own_id),
        str(fix.entry_other_id),
        str(fix.entry_dm_only_id),
    }

    expected_dm_keys = {
        "id",
        "campaign_id",
        "kind",
        "title",
        "body",
        "state",
        "visibility",
        "dm_notes",
        "needs_review",
        "source_adventure_entry_id",
        "provenance_json",
        "character_recipient_ids",
        "revision",
        "created_by_actor_kind",
        "created_by_actor_id",
        "created_at",
        "updated_at",
        "archived_at",
    }
    for item in entries:
        assert set(item.keys()) == expected_dm_keys

    # Check specific fields
    by_id = {e["id"]: e for e in entries}
    assert by_id[str(fix.entry_public_id)]["dm_notes"] == "Hidden smugglers tunnel beneath the fountain"
    assert by_id[str(fix.entry_own_id)]["character_recipient_ids"] == [str(fix.char_1_id)]
    assert by_id[str(fix.entry_other_id)]["character_recipient_ids"] == [str(fix.char_2_id)]
    assert by_id[str(fix.entry_dm_only_id)]["visibility"] == "dm_only"
    assert by_id[str(fix.entry_dm_only_id)]["dm_notes"] == "Bite marks on his neck are concealed with illusion"

    # 2. DM GET item for all entries
    for eid in [fix.entry_public_id, fix.entry_own_id, fix.entry_other_id, fix.entry_dm_only_id]:
        item_resp = fix.client.get(f"{base}/{eid}", headers=_auth(fix.token_dm))
        assert item_resp.status_code == 200
        assert set(item_resp.json().keys()) == expected_dm_keys


def test_active_session_player_forbidden_writes_zero_side_effects(
    active_api_fixture: ActiveSessionApiFixture,
) -> None:
    fix = active_api_fixture
    base = f"/api/rooms/{fix.room_id}/campaigns/{fix.campaign_id}/sessions/{fix.session_id}/runtime/entries"

    def _counts() -> tuple[int, int, int]:
        with fix.engine.connect() as conn:
            entries_count = conn.execute(select(func.count()).select_from(campaign_world_entries)).scalar_one()
            mutations_count = conn.execute(select(func.count()).select_from(campaign_world_mutations)).scalar_one()
            events_count = conn.execute(select(func.count()).select_from(session_events)).scalar_one()
            return entries_count, mutations_count, events_count

    counts_before = _counts()

    # 1. Player POST /entries forbidden
    post_resp = fix.client.post(
        base,
        json={
            "idempotency_key": "k-p-write-1",
            "kind": "npc",
            "title": "Player Hack NPC",
        },
        headers=_auth(fix.token_player_1),
    )
    assert post_resp.status_code == 403
    assert post_resp.json()["error"]["code"] == "campaign_runtime_forbidden"
    assert _counts() == counts_before

    # 2. Player PATCH /entries/{id} forbidden
    patch_resp = fix.client.patch(
        f"{base}/{fix.entry_public_id}",
        json={
            "idempotency_key": "k-p-write-2",
            "expected_revision": 1,
            "title": "Player Modified Title",
        },
        headers=_auth(fix.token_player_1),
    )
    assert patch_resp.status_code == 403
    assert patch_resp.json()["error"]["code"] == "campaign_runtime_forbidden"
    assert _counts() == counts_before

    # 3. Player POST /entries/{id}/archive forbidden
    arch_resp = fix.client.post(
        f"{base}/{fix.entry_public_id}/archive",
        json={
            "idempotency_key": "k-p-write-3",
            "expected_revision": 1,
        },
        headers=_auth(fix.token_player_1),
    )
    assert arch_resp.status_code == 403
    assert arch_resp.json()["error"]["code"] == "campaign_runtime_forbidden"
    assert _counts() == counts_before


def test_active_session_nonparticipant_and_stale_and_scope_and_inactive(
    active_api_fixture: ActiveSessionApiFixture,
) -> None:
    fix = active_api_fixture
    base = f"/api/rooms/{fix.room_id}/campaigns/{fix.campaign_id}/sessions/{fix.session_id}/runtime/entries"

    # 1. Nonparticipant -> 404
    r_nonpart_list = fix.client.get(base, headers=_auth(fix.token_nonparticipant))
    assert r_nonpart_list.status_code == 404
    assert r_nonpart_list.json()["error"]["code"] == "campaign_runtime_not_found"

    r_nonpart_post = fix.client.post(
        base,
        json={"idempotency_key": "k-np-1", "kind": "npc", "title": "Fail NPC"},
        headers=_auth(fix.token_nonparticipant),
    )
    assert r_nonpart_post.status_code == 404
    assert r_nonpart_post.json()["error"]["code"] == "campaign_runtime_not_found"

    # 2. Wrong scope in URL
    # Wrong room
    r_wrong_room = fix.client.get(
        f"/api/rooms/{uuid4()}/campaigns/{fix.campaign_id}/sessions/{fix.session_id}/runtime/entries",
        headers=_auth(fix.token_dm),
    )
    assert r_wrong_room.status_code == 404
    assert r_wrong_room.json()["error"]["code"] == "campaign_runtime_not_found"

    # Wrong campaign
    r_wrong_camp = fix.client.get(
        f"/api/rooms/{fix.room_id}/campaigns/{uuid4()}/sessions/{fix.session_id}/runtime/entries",
        headers=_auth(fix.token_dm),
    )
    assert r_wrong_camp.status_code == 404
    assert r_wrong_camp.json()["error"]["code"] == "campaign_runtime_not_found"

    # Wrong session
    r_wrong_sess = fix.client.get(
        f"/api/rooms/{fix.room_id}/campaigns/{fix.campaign_id}/sessions/{uuid4()}/runtime/entries",
        headers=_auth(fix.token_dm),
    )
    assert r_wrong_sess.status_code == 404
    assert r_wrong_sess.json()["error"]["code"] == "campaign_runtime_not_found"

    # 3. Inactive session -> 409 session_not_active
    inactive_base = (
        f"/api/rooms/{fix.room_id}/campaigns/{fix.campaign_id}"
        f"/sessions/{fix.inactive_session_id}/runtime/entries"
    )
    r_inact_list = fix.client.get(inactive_base, headers=_auth(fix.token_dm))
    assert r_inact_list.status_code == 409
    assert r_inact_list.json()["error"]["code"] == "campaign_runtime_session_not_active"

    r_inact_post = fix.client.post(
        inactive_base,
        json={"idempotency_key": "k-inact-1", "kind": "npc", "title": "Fail NPC"},
        headers=_auth(fix.token_dm),
    )
    assert r_inact_post.status_code == 409
    assert r_inact_post.json()["error"]["code"] == "campaign_runtime_session_not_active"

    # 4. Stale controller epoch / reassigned DM -> 403 forbidden
    with fix.engine.begin() as conn:
        conn.execute(
            update(sessions)
            .where(sessions.c.id == fix.session_id)
            .values(dm_controller_access_session_id=fix.p2_access_id)
        )
    r_stale_dm = fix.client.post(
        base,
        json={"idempotency_key": "k-stale-1", "kind": "npc", "title": "Stale DM NPC"},
        headers=_auth(fix.token_dm),
    )
    assert r_stale_dm.status_code == 403
    assert r_stale_dm.json()["error"]["code"] == "campaign_runtime_forbidden"


def test_active_session_dm_crud_lifecycle_events_and_concurrency(
    active_api_fixture: ActiveSessionApiFixture,
) -> None:
    fix = active_api_fixture
    base = f"/api/rooms/{fix.room_id}/campaigns/{fix.campaign_id}/sessions/{fix.session_id}/runtime/entries"

    notifications_before = len(fix.notifier.notifications)

    # 1. DM creates an active entry
    create_resp = fix.client.post(
        base,
        json={
            "idempotency_key": "k-dm-act-create-1",
            "kind": "npc",
            "title": "Barkeep Bob",
            "body": "Friendly barkeep with a scar",
            "state": {},
            "visibility": "public",
            "dm_notes": "Knows the thieves guild secret entrance",
        },
        headers=_auth(fix.token_dm),
    )
    assert create_resp.status_code == 201
    created = create_resp.json()
    entry_id = created["id"]
    assert created["revision"] == 1
    assert created["title"] == "Barkeep Bob"

    # Verify event was emitted
    with fix.engine.connect() as conn:
        ev = conn.execute(
            select(session_events).where(
                session_events.c.session_id == fix.session_id,
                session_events.c.kind == "world.entry.created",
            )
        ).mappings().all()
        assert len(ev) == 1
    assert len(fix.notifier.notifications) == notifications_before + 1

    # 2. DM updates the active entry
    patch_resp = fix.client.patch(
        f"{base}/{entry_id}",
        json={
            "idempotency_key": "k-dm-act-patch-1",
            "expected_revision": 1,
            "title": "Master Barkeep Bob",
        },
        headers=_auth(fix.token_dm),
    )
    assert patch_resp.status_code == 200
    patched = patch_resp.json()
    assert patched["revision"] == 2
    assert patched["title"] == "Master Barkeep Bob"

    # Verify update event was emitted
    with fix.engine.connect() as conn:
        ev = conn.execute(
            select(session_events).where(
                session_events.c.session_id == fix.session_id,
                session_events.c.kind == "world.entry.updated",
            )
        ).mappings().all()
        assert len(ev) == 1
    assert len(fix.notifier.notifications) == notifications_before + 2

    # 3. Stale revision conflict on PATCH -> 409, no new event
    with fix.engine.connect() as connection:
        events_before_conflict = len(
            connection.execute(
                select(session_events).where(session_events.c.session_id == fix.session_id)
            ).all()
        )
    stale_resp = fix.client.patch(
        f"{base}/{entry_id}",
        json={
            "idempotency_key": "k-dm-act-stale-1",
            "expected_revision": 99,
            "title": "Stale Title",
        },
        headers=_auth(fix.token_dm),
    )
    assert stale_resp.status_code == 409
    assert stale_resp.json()["error"]["code"] == "campaign_runtime_revision_conflict"
    with fix.engine.connect() as connection:
        events_after_conflict = len(
            connection.execute(
                select(session_events).where(session_events.c.session_id == fix.session_id)
            ).all()
        )
    assert events_after_conflict == events_before_conflict

    # 4. Idempotency conflict on CREATE -> 409, no new event
    idemp_conflict_resp = fix.client.post(
        base,
        json={
            "idempotency_key": "k-dm-act-create-1",
            "kind": "npc",
            "title": "Different Title Same Key",
        },
        headers=_auth(fix.token_dm),
    )
    assert idemp_conflict_resp.status_code == 409
    assert idemp_conflict_resp.json()["error"]["code"] == "campaign_runtime_idempotency_conflict"

    # 5. Idempotent replay on CREATE -> 201 replay, no new event
    idemp_replay_resp = fix.client.post(
        base,
        json={
            "idempotency_key": "k-dm-act-create-1",
            "kind": "npc",
            "title": "Barkeep Bob",
            "body": "Friendly barkeep with a scar",
            "state": {},
            "visibility": "public",
            "dm_notes": "Knows the thieves guild secret entrance",
        },
        headers=_auth(fix.token_dm),
    )
    assert idemp_replay_resp.status_code in (200, 201)
    assert idemp_replay_resp.json()["id"] == entry_id

    # 6. DM archives the entry
    arch_resp = fix.client.post(
        f"{base}/{entry_id}/archive",
        json={
            "idempotency_key": "k-dm-act-arch-1",
            "expected_revision": 2,
        },
        headers=_auth(fix.token_dm),
    )
    assert arch_resp.status_code == 200
    archived = arch_resp.json()
    assert archived["archived_at"] is not None
    assert archived["revision"] == 3

    # Verify archive event was emitted
    with fix.engine.connect() as conn:
        ev = conn.execute(
            select(session_events).where(
                session_events.c.session_id == fix.session_id,
                session_events.c.kind == "world.entry.archived",
            )
        ).mappings().all()
        assert len(ev) == 1
    assert len(fix.notifier.notifications) == notifications_before + 3


def test_active_session_dm_override_crud_and_overlay_reads(
    active_api_fixture: ActiveSessionApiFixture,
) -> None:
    fix = active_api_fixture
    base = f"/api/rooms/{fix.room_id}/campaigns/{fix.campaign_id}/sessions/{fix.session_id}/runtime"

    notifications_before = len(fix.notifier.notifications)

    # 1. Initial list of overrides is empty
    resp_list_0 = fix.client.get(f"{base}/overrides", headers=_auth(fix.token_dm))
    assert resp_list_0.status_code == 200
    assert resp_list_0.json() == []

    # 2. DM creates an active override
    resp_create = fix.client.post(
        f"{base}/overrides",
        json={
            "idempotency_key": "k-dm-act-ov-create-1",
            "adventure_entry_id": str(fix.adv_entry_npc_id),
            "state": {"disposition": "hostile"},
            "note": "DM override note",
            "needs_review": True,
        },
        headers=_auth(fix.token_dm),
    )
    assert resp_create.status_code == 201
    created_ov = resp_create.json()
    ov_id = created_ov["id"]
    assert created_ov["adventure_entry_id"] == str(fix.adv_entry_npc_id)
    assert created_ov["revision"] == 1
    assert created_ov["needs_review"] is True
    assert created_ov["state_json"] == {"disposition": "hostile"}
    assert created_ov["note"] == "DM override note"

    # Verify event emitted
    with fix.engine.connect() as conn:
        ev = conn.execute(
            select(session_events).where(
                session_events.c.session_id == fix.session_id,
                session_events.c.kind == "world.override.created",
            )
        ).mappings().all()
        assert len(ev) == 1
    assert len(fix.notifier.notifications) == notifications_before + 1

    # 3. DM lists overrides -> contains created override
    resp_list_1 = fix.client.get(f"{base}/overrides", headers=_auth(fix.token_dm))
    assert resp_list_1.status_code == 200
    items = resp_list_1.json()
    assert len(items) == 1
    assert items[0]["id"] == ov_id

    # 4. DM gets override by adventure_entry_id
    resp_get = fix.client.get(
        f"{base}/overrides/{fix.adv_entry_npc_id}",
        headers=_auth(fix.token_dm),
    )
    assert resp_get.status_code == 200
    assert resp_get.json()["id"] == ov_id

    # 5. DM reads overlay by adventure_entry_id -> reflects override
    resp_overlay = fix.client.get(
        f"{base}/adventure-overlays/{fix.adv_entry_npc_id}",
        headers=_auth(fix.token_dm),
    )
    assert resp_overlay.status_code == 200
    overlay = resp_overlay.json()
    assert overlay["id"] == str(fix.adv_entry_npc_id)
    assert overlay["title"] == "Miller John"
    assert overlay["override"] is not None
    assert overlay["override"]["id"] == ov_id
    assert overlay["override"]["state_json"] == {"disposition": "hostile"}
    assert overlay["override"]["note"] == "DM override note"

    # 6. DM lists adventure overlays
    resp_overlays = fix.client.get(
        f"{base}/adventures/{fix.adv_attached_id}/overlays",
        headers=_auth(fix.token_dm),
    )
    assert resp_overlays.status_code == 200
    overlays = resp_overlays.json()
    assert len(overlays) == 2
    overlay_map = {o["id"]: o for o in overlays}
    assert overlay_map[str(fix.adv_entry_npc_id)]["override"] is not None
    assert overlay_map[str(fix.adv_entry_scene_id)]["override"] is None

    # 7. DM updates override
    resp_patch = fix.client.patch(
        f"{base}/overrides/{fix.adv_entry_npc_id}",
        json={
            "idempotency_key": "k-dm-act-ov-patch-1",
            "expected_override_id": ov_id,
            "expected_revision": 1,
            "state": {"disposition": "friendly"},
            "needs_review": False,
        },
        headers=_auth(fix.token_dm),
    )
    assert resp_patch.status_code == 200
    patched_ov = resp_patch.json()
    assert patched_ov["revision"] == 2
    assert patched_ov["needs_review"] is False
    assert patched_ov["state_json"] == {"disposition": "friendly"}

    with fix.engine.connect() as conn:
        ev = conn.execute(
            select(session_events).where(
                session_events.c.session_id == fix.session_id,
                session_events.c.kind == "world.override.updated",
            )
        ).mappings().all()
        assert len(ev) == 1
    assert len(fix.notifier.notifications) == notifications_before + 2

    # 8. DM clears override
    resp_clear = fix.client.post(
        f"{base}/overrides/{fix.adv_entry_npc_id}/clear",
        json={
            "idempotency_key": "k-dm-act-ov-clear-1",
            "expected_override_id": ov_id,
            "expected_revision": 2,
        },
        headers=_auth(fix.token_dm),
    )
    assert resp_clear.status_code == 200

    with fix.engine.connect() as conn:
        ev = conn.execute(
            select(session_events).where(
                session_events.c.session_id == fix.session_id,
                session_events.c.kind == "world.override.cleared",
            )
        ).mappings().all()
        assert len(ev) == 1
    assert len(fix.notifier.notifications) == notifications_before + 3

    # 9. GET cleared override -> 404
    resp_get_cleared = fix.client.get(
        f"{base}/overrides/{fix.adv_entry_npc_id}",
        headers=_auth(fix.token_dm),
    )
    assert resp_get_cleared.status_code == 404
    assert resp_get_cleared.json()["error"]["code"] == "campaign_runtime_not_found"

    # 10. Overlay has no override
    resp_overlay_cleared = fix.client.get(
        f"{base}/adventure-overlays/{fix.adv_entry_npc_id}",
        headers=_auth(fix.token_dm),
    )
    assert resp_overlay_cleared.status_code == 200
    assert resp_overlay_cleared.json()["override"] is None


def test_active_session_dm_context_lifecycle_and_events(
    active_api_fixture: ActiveSessionApiFixture,
) -> None:
    fix = active_api_fixture
    base = f"/api/rooms/{fix.room_id}/campaigns/{fix.campaign_id}/sessions/{fix.session_id}/runtime/context"

    notifications_before = len(fix.notifier.notifications)

    # 1. Initial context: revision 0, all null
    resp_get_0 = fix.client.get(base, headers=_auth(fix.token_dm))
    assert resp_get_0.status_code == 200
    ctx_0 = resp_get_0.json()
    assert ctx_0["campaign_id"] == str(fix.campaign_id)
    assert ctx_0["revision"] == 0
    assert ctx_0["current_adventure_scene_entry_id"] is None
    assert ctx_0["current_runtime_scene_entry_id"] is None
    assert ctx_0["current_situation"] is None

    # 2. DM updates context with adventure scene and situation
    resp_patch_1 = fix.client.patch(
        base,
        json={
            "idempotency_key": "k-dm-act-ctx-patch-1",
            "expected_revision": 0,
            "current_adventure_scene_entry_id": str(fix.adv_entry_scene_id),
            "current_situation": "Party investigating the old mill",
        },
        headers=_auth(fix.token_dm),
    )
    assert resp_patch_1.status_code == 200
    ctx_1 = resp_patch_1.json()
    assert ctx_1["revision"] == 1
    assert ctx_1["current_adventure_scene_entry_id"] == str(fix.adv_entry_scene_id)
    assert ctx_1["current_runtime_scene_entry_id"] is None
    assert ctx_1["current_situation"] == "Party investigating the old mill"

    with fix.engine.connect() as conn:
        ev = conn.execute(
            select(session_events).where(
                session_events.c.session_id == fix.session_id,
                session_events.c.kind == "world.context_changed",
            )
        ).mappings().all()
        assert len(ev) == 1
    assert len(fix.notifier.notifications) == notifications_before + 1

    # 3. DM switches to runtime scene
    resp_patch_2 = fix.client.patch(
        base,
        json={
            "idempotency_key": "k-dm-act-ctx-patch-2",
            "expected_revision": 1,
            "current_adventure_scene_entry_id": None,
            "current_runtime_scene_entry_id": str(fix.entry_public_id),
            "current_situation": "Party returned to town square",
        },
        headers=_auth(fix.token_dm),
    )
    assert resp_patch_2.status_code == 200
    ctx_2 = resp_patch_2.json()
    assert ctx_2["revision"] == 2
    assert ctx_2["current_adventure_scene_entry_id"] is None
    assert ctx_2["current_runtime_scene_entry_id"] == str(fix.entry_public_id)
    assert ctx_2["current_situation"] == "Party returned to town square"

    with fix.engine.connect() as conn:
        ev = conn.execute(
            select(session_events).where(
                session_events.c.session_id == fix.session_id,
                session_events.c.kind == "world.context_changed",
            )
        ).mappings().all()
        assert len(ev) == 2
    assert len(fix.notifier.notifications) == notifications_before + 2

    # 4. DM clears context
    resp_clear = fix.client.post(
        f"{base}/clear",
        json={
            "idempotency_key": "k-dm-act-ctx-clear-1",
            "expected_revision": 2,
        },
        headers=_auth(fix.token_dm),
    )
    assert resp_clear.status_code == 200
    ctx_cleared = resp_clear.json()
    assert ctx_cleared["revision"] == 3
    assert ctx_cleared["current_adventure_scene_entry_id"] is None
    assert ctx_cleared["current_runtime_scene_entry_id"] is None
    assert ctx_cleared["current_situation"] is None

    with fix.engine.connect() as conn:
        ev = conn.execute(
            select(session_events).where(
                session_events.c.session_id == fix.session_id,
                session_events.c.kind == "world.context_changed",
            )
        ).mappings().all()
        assert len(ev) == 3
    assert len(fix.notifier.notifications) == notifications_before + 3


def test_active_session_player_forbidden_from_overrides_context_and_overlays(
    active_api_fixture: ActiveSessionApiFixture,
) -> None:
    fix = active_api_fixture
    base = f"/api/rooms/{fix.room_id}/campaigns/{fix.campaign_id}/sessions/{fix.session_id}/runtime"

    # Seed an override first so read targets exist
    create_resp = fix.client.post(
        f"{base}/overrides",
        json={
            "idempotency_key": "k-dm-seed-ov-1",
            "adventure_entry_id": str(fix.adv_entry_npc_id),
            "state": {"disposition": "hostile"},
            "note": "Super secret DM note",
        },
        headers=_auth(fix.token_dm),
    )
    assert create_resp.status_code == 201
    ov_id = create_resp.json()["id"]

    events_before = len(fix.notifier.notifications)

    def _state_counts() -> tuple[int, int, int, int]:
        with fix.engine.connect() as connection:
            override_count = connection.execute(
                select(func.count())
                .select_from(campaign_adventure_overrides)
                .where(campaign_adventure_overrides.c.campaign_id == fix.campaign_id)
            ).scalar_one()
            context_count = connection.execute(
                select(func.count())
                .select_from(campaign_runtime_context)
                .where(campaign_runtime_context.c.campaign_id == fix.campaign_id)
            ).scalar_one()
            mutation_count = connection.execute(
                select(func.count())
                .select_from(campaign_world_mutations)
                .where(campaign_world_mutations.c.campaign_id == fix.campaign_id)
            ).scalar_one()
            event_count = connection.execute(
                select(func.count())
                .select_from(session_events)
                .where(session_events.c.session_id == fix.session_id)
            ).scalar_one()
            return override_count, context_count, mutation_count, event_count

    state_before = _state_counts()

    # For both Player 1 and Player 2, test all 10 endpoints
    for token in (fix.token_player_1, fix.token_player_2):
        # 1. GET /overrides
        r1 = fix.client.get(f"{base}/overrides", headers=_auth(token))
        assert r1.status_code == 403
        assert r1.json()["error"]["code"] == "campaign_runtime_forbidden"
        assert "secret" not in r1.text.lower()

        # 2. GET /overrides/{entry_id}
        r2 = fix.client.get(f"{base}/overrides/{fix.adv_entry_npc_id}", headers=_auth(token))
        assert r2.status_code == 403
        assert r2.json()["error"]["code"] == "campaign_runtime_forbidden"
        assert "secret" not in r2.text.lower()

        # 3. POST /overrides
        r3 = fix.client.post(
            f"{base}/overrides",
            json={
                "idempotency_key": "k-p-ov-create",
                "adventure_entry_id": str(fix.adv_entry_scene_id),
                "state": {},
            },
            headers=_auth(token),
        )
        assert r3.status_code == 403
        assert r3.json()["error"]["code"] == "campaign_runtime_forbidden"

        # 4. PATCH /overrides/{entry_id}
        r4 = fix.client.patch(
            f"{base}/overrides/{fix.adv_entry_npc_id}",
            json={
                "idempotency_key": "k-p-ov-patch",
                "expected_override_id": ov_id,
                "expected_revision": 1,
                "note": "player hack",
            },
            headers=_auth(token),
        )
        assert r4.status_code == 403
        assert r4.json()["error"]["code"] == "campaign_runtime_forbidden"

        # 5. POST /overrides/{entry_id}/clear
        r5 = fix.client.post(
            f"{base}/overrides/{fix.adv_entry_npc_id}/clear",
            json={
                "idempotency_key": "k-p-ov-clear",
                "expected_override_id": ov_id,
                "expected_revision": 1,
            },
            headers=_auth(token),
        )
        assert r5.status_code == 403
        assert r5.json()["error"]["code"] == "campaign_runtime_forbidden"

        # 6. GET /context
        r6 = fix.client.get(f"{base}/context", headers=_auth(token))
        assert r6.status_code == 403
        assert r6.json()["error"]["code"] == "campaign_runtime_forbidden"

        # 7. PATCH /context
        r7 = fix.client.patch(
            f"{base}/context",
            json={
                "idempotency_key": "k-p-ctx-patch",
                "expected_revision": 0,
                "current_situation": "player situation",
            },
            headers=_auth(token),
        )
        assert r7.status_code == 403
        assert r7.json()["error"]["code"] == "campaign_runtime_forbidden"

        # 8. POST /context/clear
        r8 = fix.client.post(
            f"{base}/context/clear",
            json={
                "idempotency_key": "k-p-ctx-clear",
                "expected_revision": 0,
            },
            headers=_auth(token),
        )
        assert r8.status_code == 403
        assert r8.json()["error"]["code"] == "campaign_runtime_forbidden"

        # 9. GET /adventure-overlays/{entry_id}
        r9 = fix.client.get(f"{base}/adventure-overlays/{fix.adv_entry_npc_id}", headers=_auth(token))
        assert r9.status_code == 403
        assert r9.json()["error"]["code"] == "campaign_runtime_forbidden"
        assert "secret" not in r9.text.lower()

        # 10. GET /adventures/{id}/overlays
        r10 = fix.client.get(f"{base}/adventures/{fix.adv_attached_id}/overlays", headers=_auth(token))
        assert r10.status_code == 403
        assert r10.json()["error"]["code"] == "campaign_runtime_forbidden"
        assert "secret" not in r10.text.lower()

    # Verify zero side effects across durable state, mutation records, events, and notifier.
    assert _state_counts() == state_before
    assert len(fix.notifier.notifications) == events_before


def test_active_session_override_and_context_errors_matrix(
    active_api_fixture: ActiveSessionApiFixture,
) -> None:
    fix = active_api_fixture
    base = f"/api/rooms/{fix.room_id}/campaigns/{fix.campaign_id}/sessions/{fix.session_id}/runtime"

    # 1. Nonparticipant -> 404 (session not found for nonparticipant)
    r_np_1 = fix.client.get(f"{base}/overrides", headers=_auth(fix.token_nonparticipant))
    assert r_np_1.status_code == 404
    assert r_np_1.json()["error"]["code"] == "campaign_runtime_not_found"

    r_np_2 = fix.client.get(f"{base}/context", headers=_auth(fix.token_nonparticipant))
    assert r_np_2.status_code == 404
    assert r_np_2.json()["error"]["code"] == "campaign_runtime_not_found"

    r_np_3 = fix.client.get(
        f"{base}/adventure-overlays/{fix.adv_entry_scene_id}",
        headers=_auth(fix.token_nonparticipant),
    )
    assert r_np_3.status_code == 404
    assert r_np_3.json()["error"]["code"] == "campaign_runtime_not_found"

    # 2. Inactive session -> 409 session_not_active
    inact_base = f"/api/rooms/{fix.room_id}/campaigns/{fix.campaign_id}/sessions/{fix.inactive_session_id}/runtime"
    r_inact_1 = fix.client.get(f"{inact_base}/overrides", headers=_auth(fix.token_dm))
    assert r_inact_1.status_code == 409
    assert r_inact_1.json()["error"]["code"] == "campaign_runtime_session_not_active"

    r_inact_2 = fix.client.post(
        f"{inact_base}/overrides",
        json={
            "idempotency_key": "k-inact-ov-1",
            "adventure_entry_id": str(fix.adv_entry_scene_id),
            "state": {},
        },
        headers=_auth(fix.token_dm),
    )
    assert r_inact_2.status_code == 409
    assert r_inact_2.json()["error"]["code"] == "campaign_runtime_session_not_active"

    r_inact_3 = fix.client.get(f"{inact_base}/context", headers=_auth(fix.token_dm))
    assert r_inact_3.status_code == 409
    assert r_inact_3.json()["error"]["code"] == "campaign_runtime_session_not_active"

    r_inact_4 = fix.client.patch(
        f"{inact_base}/context",
        json={
            "idempotency_key": "k-inact-ctx-1",
            "expected_revision": 0,
            "current_situation": "Inactive test",
        },
        headers=_auth(fix.token_dm),
    )
    assert r_inact_4.status_code == 409
    assert r_inact_4.json()["error"]["code"] == "campaign_runtime_session_not_active"

    r_inact_5 = fix.client.get(
        f"{inact_base}/adventure-overlays/{fix.adv_entry_scene_id}",
        headers=_auth(fix.token_dm),
    )
    assert r_inact_5.status_code == 409
    assert r_inact_5.json()["error"]["code"] == "campaign_runtime_session_not_active"

    # 3. Wrong scope -> 404
    wrong_room = uuid4()
    r_wrong_room = fix.client.get(
        f"/api/rooms/{wrong_room}/campaigns/{fix.campaign_id}/sessions/{fix.session_id}/runtime/overrides",
        headers=_auth(fix.token_dm),
    )
    assert r_wrong_room.status_code == 404
    assert r_wrong_room.json()["error"]["code"] == "campaign_runtime_not_found"

    wrong_camp = uuid4()
    r_wrong_camp = fix.client.get(
        f"/api/rooms/{fix.room_id}/campaigns/{wrong_camp}/sessions/{fix.session_id}/runtime/context",
        headers=_auth(fix.token_dm),
    )
    assert r_wrong_camp.status_code == 404
    assert r_wrong_camp.json()["error"]["code"] == "campaign_runtime_not_found"

    wrong_sess = uuid4()
    r_wrong_sess = fix.client.get(
        f"/api/rooms/{fix.room_id}/campaigns/{fix.campaign_id}/sessions/{wrong_sess}/runtime/overrides",
        headers=_auth(fix.token_dm),
    )
    assert r_wrong_sess.status_code == 404
    assert r_wrong_sess.json()["error"]["code"] == "campaign_runtime_not_found"

    # 4. Stale DM -> 403
    with fix.engine.begin() as conn:
        conn.execute(
            update(sessions)
            .where(sessions.c.id == fix.session_id)
            .values(dm_controller_access_session_id=fix.p2_access_id)
        )
    r_stale = fix.client.get(f"{base}/overrides", headers=_auth(fix.token_dm))
    assert r_stale.status_code == 403
    assert r_stale.json()["error"]["code"] == "campaign_runtime_forbidden"

    # Restore session DM
    with fix.engine.begin() as conn:
        conn.execute(
            update(sessions)
            .where(sessions.c.id == fix.session_id)
            .values(
                dm_controller_access_session_id=select(campaign_seats.c.controller_access_session_id)
                .where(campaign_seats.c.id == fix.dm_seat_id)
                .scalar_subquery()
            )
        )

    # 5. Override domain validation / conflict errors
    # Nonexistent adventure entry -> 404
    r_notfound = fix.client.post(
        f"{base}/overrides",
        json={
            "idempotency_key": "k-ov-notfound",
            "adventure_entry_id": str(uuid4()),
            "state": {},
        },
        headers=_auth(fix.token_dm),
    )
    assert r_notfound.status_code == 404
    assert r_notfound.json()["error"]["code"] == "campaign_runtime_not_found"

    # Unattached adventure entry -> 422 invalid
    r_unatt = fix.client.post(
        f"{base}/overrides",
        json={
            "idempotency_key": "k-ov-unattached",
            "adventure_entry_id": str(fix.adv_entry_unattached_id),
            "state": {},
        },
        headers=_auth(fix.token_dm),
    )
    assert r_unatt.status_code == 422
    assert r_unatt.json()["error"]["code"] == "campaign_runtime_invalid"

    # Create attached override
    r_ov_ok = fix.client.post(
        f"{base}/overrides",
        json={
            "idempotency_key": "k-ov-ok-1",
            "adventure_entry_id": str(fix.adv_entry_scene_id),
            "state": {"read_aloud": "Creaking gears"},
        },
        headers=_auth(fix.token_dm),
    )
    assert r_ov_ok.status_code == 201
    ov_scene_id = r_ov_ok.json()["id"]

    # Duplicate override -> 409 override_exists
    r_dup = fix.client.post(
        f"{base}/overrides",
        json={
            "idempotency_key": "k-ov-dup",
            "adventure_entry_id": str(fix.adv_entry_scene_id),
            "state": {},
        },
        headers=_auth(fix.token_dm),
    )
    assert r_dup.status_code == 409
    assert r_dup.json()["error"]["code"] == "campaign_runtime_override_exists"

    # Stale override revision on PATCH -> 409 revision_conflict
    r_stale_rev_patch = fix.client.patch(
        f"{base}/overrides/{fix.adv_entry_scene_id}",
        json={
            "idempotency_key": "k-ov-stale-rev",
            "expected_override_id": ov_scene_id,
            "expected_revision": 99,
            "note": "stale rev note",
        },
        headers=_auth(fix.token_dm),
    )
    assert r_stale_rev_patch.status_code == 409
    assert r_stale_rev_patch.json()["error"]["code"] == "campaign_runtime_revision_conflict"

    # Stale override identity on PATCH -> 409 revision_conflict
    r_stale_id_patch = fix.client.patch(
        f"{base}/overrides/{fix.adv_entry_scene_id}",
        json={
            "idempotency_key": "k-ov-stale-id",
            "expected_override_id": str(uuid4()),
            "expected_revision": 1,
            "note": "stale id note",
        },
        headers=_auth(fix.token_dm),
    )
    assert r_stale_id_patch.status_code == 409
    assert r_stale_id_patch.json()["error"]["code"] == "campaign_runtime_revision_conflict"

    # Stale override revision on CLEAR -> 409 revision_conflict
    r_stale_rev_clear = fix.client.post(
        f"{base}/overrides/{fix.adv_entry_scene_id}/clear",
        json={
            "idempotency_key": "k-ov-stale-clr-rev",
            "expected_override_id": ov_scene_id,
            "expected_revision": 99,
        },
        headers=_auth(fix.token_dm),
    )
    assert r_stale_rev_clear.status_code == 409
    assert r_stale_rev_clear.json()["error"]["code"] == "campaign_runtime_revision_conflict"

    # Stale override identity on CLEAR -> 409 revision_conflict
    r_stale_id_clear = fix.client.post(
        f"{base}/overrides/{fix.adv_entry_scene_id}/clear",
        json={
            "idempotency_key": "k-ov-stale-clr-id",
            "expected_override_id": str(uuid4()),
            "expected_revision": 1,
        },
        headers=_auth(fix.token_dm),
    )
    assert r_stale_id_clear.status_code == 409
    assert r_stale_id_clear.json()["error"]["code"] == "campaign_runtime_revision_conflict"

    # 6. Context domain validation / conflict errors
    # Context dual scene -> 422 invalid
    r_dual = fix.client.patch(
        f"{base}/context",
        json={
            "idempotency_key": "k-ctx-dual",
            "expected_revision": 0,
            "current_adventure_scene_entry_id": str(fix.adv_entry_scene_id),
            "current_runtime_scene_entry_id": str(fix.entry_public_id),
        },
        headers=_auth(fix.token_dm),
    )
    assert r_dual.status_code == 422
    assert r_dual.json()["error"]["code"] == "campaign_runtime_invalid"

    # Context non-scene entry (npc entry) -> 422 invalid
    r_non_scene = fix.client.patch(
        f"{base}/context",
        json={
            "idempotency_key": "k-ctx-non-scene",
            "expected_revision": 0,
            "current_adventure_scene_entry_id": str(fix.adv_entry_npc_id),
        },
        headers=_auth(fix.token_dm),
    )
    assert r_non_scene.status_code == 422
    assert r_non_scene.json()["error"]["code"] == "campaign_runtime_invalid"

    # Context unattached adventure scene -> 422 invalid
    r_unatt_scene = fix.client.patch(
        f"{base}/context",
        json={
            "idempotency_key": "k-ctx-unatt-scene",
            "expected_revision": 0,
            "current_adventure_scene_entry_id": str(fix.adv_entry_unattached_id),
        },
        headers=_auth(fix.token_dm),
    )
    assert r_unatt_scene.status_code == 422
    assert r_unatt_scene.json()["error"]["code"] == "campaign_runtime_invalid"

    # Stale context revision on PATCH -> 409 revision_conflict
    r_stale_ctx_patch = fix.client.patch(
        f"{base}/context",
        json={
            "idempotency_key": "k-ctx-stale-patch",
            "expected_revision": 99,
            "current_situation": "Stale",
        },
        headers=_auth(fix.token_dm),
    )
    assert r_stale_ctx_patch.status_code == 409
    assert r_stale_ctx_patch.json()["error"]["code"] == "campaign_runtime_revision_conflict"

    # Stale context revision on CLEAR -> 409 revision_conflict
    r_stale_ctx_clear = fix.client.post(
        f"{base}/context/clear",
        json={
            "idempotency_key": "k-ctx-stale-clear",
            "expected_revision": 99,
        },
        headers=_auth(fix.token_dm),
    )
    assert r_stale_ctx_clear.status_code == 409
    assert r_stale_ctx_clear.json()["error"]["code"] == "campaign_runtime_revision_conflict"

    # 7. Idempotency replay and conflict
    # Override replay
    r_replay_ov = fix.client.post(
        f"{base}/overrides",
        json={
            "idempotency_key": "k-ov-ok-1",
            "adventure_entry_id": str(fix.adv_entry_scene_id),
            "state": {"read_aloud": "Creaking gears"},
        },
        headers=_auth(fix.token_dm),
    )
    assert r_replay_ov.status_code in (200, 201)
    assert r_replay_ov.json()["id"] == ov_scene_id

    # Override idempotency conflict (different state with same key)
    r_conf_ov = fix.client.post(
        f"{base}/overrides",
        json={
            "idempotency_key": "k-ov-ok-1",
            "adventure_entry_id": str(fix.adv_entry_scene_id),
            "state": {"read_aloud": "Different text"},
        },
        headers=_auth(fix.token_dm),
    )
    assert r_conf_ov.status_code == 409
    assert r_conf_ov.json()["error"]["code"] == "campaign_runtime_idempotency_conflict"

    # Context update ok
    r_ctx_ok = fix.client.patch(
        f"{base}/context",
        json={
            "idempotency_key": "k-ctx-ok-1",
            "expected_revision": 0,
            "current_situation": "Situation OK",
        },
        headers=_auth(fix.token_dm),
    )
    assert r_ctx_ok.status_code == 200

    # Context replay
    r_ctx_replay = fix.client.patch(
        f"{base}/context",
        json={
            "idempotency_key": "k-ctx-ok-1",
            "expected_revision": 0,
            "current_situation": "Situation OK",
        },
        headers=_auth(fix.token_dm),
    )
    assert r_ctx_replay.status_code == 200
    assert r_ctx_replay.json()["current_situation"] == "Situation OK"

    # Context conflict
    r_ctx_conf = fix.client.patch(
        f"{base}/context",
        json={
            "idempotency_key": "k-ctx-ok-1",
            "expected_revision": 0,
            "current_situation": "Different Situation",
        },
        headers=_auth(fix.token_dm),
    )
    assert r_ctx_conf.status_code == 409
    assert r_ctx_conf.json()["error"]["code"] == "campaign_runtime_idempotency_conflict"


@pytest.mark.parametrize(
    ("exc", "expected_status", "expected_code"),
    [
        (CampaignRuntimeAuthorityError("forbidden"), 403, "campaign_runtime_forbidden"),
        (TableEventActorUnauthorizedError("unauth"), 403, "campaign_runtime_forbidden"),
        (CampaignRuntimeNotFoundError("not found"), 404, "campaign_runtime_not_found"),
        (TableEventNotFoundError("not found"), 404, "campaign_runtime_not_found"),
        (
            CampaignRuntimeArchivedError(
                UUID("00000000-0000-0000-0000-000000000001"),
                UUID("00000000-0000-0000-0000-000000000002"),
                1,
                2,
            ),
            409,
            "campaign_runtime_archived",
        ),
        (CampaignRuntimeActiveSessionError("active"), 409, "campaign_runtime_active_session"),
        (CampaignRuntimeSessionNotActiveError("inactive"), 409, "campaign_runtime_session_not_active"),
        (TableEventSessionNotActiveError("inactive"), 409, "campaign_runtime_session_not_active"),
        (CampaignRuntimeIdempotencyConflictError("idemp"), 409, "campaign_runtime_idempotency_conflict"),
        (
            CampaignRuntimeRevisionConflictError(
                UUID("00000000-0000-0000-0000-000000000001"),
                UUID("00000000-0000-0000-0000-000000000002"),
                1,
                2,
            ),
            409,
            "campaign_runtime_revision_conflict",
        ),
        (CampaignAdventureOverrideAlreadyExistsError("exists"), 409, "campaign_runtime_override_exists"),
        (CampaignRuntimeValidationError("invalid"), 422, "campaign_runtime_invalid"),
        (RuntimeEntryValidationError("entry invalid"), 422, "campaign_runtime_invalid"),
        (RuntimeEntryVisibilityError("visibility invalid"), 422, "campaign_runtime_invalid"),
        (RuntimeEntryPayloadError("payload invalid"), 422, "campaign_runtime_invalid"),
    ],
)
def test_error_mapper_parameterized_matrix(
    exc: Exception,
    expected_status: int,
    expected_code: str,
) -> None:
    api_error = map_campaign_runtime_error(exc)
    assert api_error.status_code == expected_status
    assert api_error.code == expected_code
