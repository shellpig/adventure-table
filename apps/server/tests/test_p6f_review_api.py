from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator
from uuid import UUID, uuid4

from fastapi import Request
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, event, func, insert, select
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_database_engine
from app.api.errors import APIError
from app.api.rooms.access import get_room_access_context
from app.config import settings
from app.domain.adventure_imports.schemas import (
    DraftEntry,
    DraftQuestion,
    DraftWarning,
    ImportDraft,
)
from app.domain.adventure_imports.service import AdventureImportService
from app.domain.adventures.payloads import ScenePayload
from app.domain.adventures.service import AdventureService
from app.domain.room_assets.service import RoomAssetService
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.table_events import TableEventService
from app.main import app
from app.persistence.adventure_imports.repository import AdventureImportRepository
from app.persistence.rooms.table_runtime import TableEventRepository
from app.persistence.adventure_imports.tables import (
    adventure_import_drafts,
    adventure_import_sources,
    adventure_imports,
)
from app.persistence.adventures.repository import AdventureRepository
from app.persistence.adventures.tables import (
    adventure_definitions,
    adventure_entries,
    adventure_entry_assets,
)
from app.persistence.room_assets.repository import RoomAssetRepository
from app.persistence.room_assets.storage import FilesystemAssetStorage
from app.persistence.room_assets.tables import room_assets
from app.persistence.rooms.tables import campaigns, rooms

TABLES_TO_CREATE = [
    rooms,
    campaigns,
    adventure_definitions,
    adventure_entries,
    adventure_entry_assets,
    room_assets,
    adventure_imports,
    adventure_import_sources,
    adventure_import_drafts,
]


@dataclass(frozen=True)
class ReviewApiFixture:
    client: TestClient
    engine: Engine
    room_a_id: UUID
    room_b_id: UUID
    token_owner_a: str
    token_dm_a: str
    token_member_a: str
    token_owner_b: str
    owner_a: RoomAccessContext
    dm_a: RoomAccessContext
    member_a: RoomAccessContext
    owner_b: RoomAccessContext
    tmp_path: Path
    room_asset_service: RoomAssetService
    adventure_service: AdventureService
    import_service: AdventureImportService


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def api_fixture(tmp_path: Path) -> Generator[ReviewApiFixture, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_fks(dbapi_conn, _connection_record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    for table in TABLES_TO_CREATE:
        table.create(engine, checkfirst=True)

    storage = FilesystemAssetStorage(tmp_path)
    asset_repo = RoomAssetRepository(engine)
    room_asset_service = RoomAssetService(
        asset_repo,
        storage,
        max_image_bytes=settings.asset_max_image_bytes,
        max_source_document_bytes=settings.asset_max_source_document_bytes,
    )
    import_repo = AdventureImportRepository(engine)
    adventure_repo = AdventureRepository(engine)
    adventure_service = AdventureService(adventure_repo, asset_repo)
    import_service = AdventureImportService(
        import_repo,
        settings,
        room_asset_service,
        adventure_service,
        TableEventService(TableEventRepository(engine)),
    )

    room_a_id = uuid4()
    room_b_id = uuid4()
    now = datetime.now(timezone.utc)

    with engine.begin() as conn:
        conn.execute(
            insert(rooms).values(
                [
                    {
                        "id": room_a_id,
                        "code": "ROOMA",
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
                        "code": "ROOMB",
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

    token_owner_a = "token-owner-a"
    token_dm_a = "token-dm-a"
    token_member_a = "token-member-a"
    token_owner_b = "token-owner-b"

    owner_a = RoomAccessContext(
        room_id=room_a_id,
        access_session_id=uuid4(),
        authority=RoomAccessAuthority.OWNER,
        display_name="Owner A",
    )
    dm_a = RoomAccessContext(
        room_id=room_a_id,
        access_session_id=uuid4(),
        authority=RoomAccessAuthority.DM,
        display_name="DM A",
    )
    member_a = RoomAccessContext(
        room_id=room_a_id,
        access_session_id=uuid4(),
        authority=RoomAccessAuthority.MEMBER,
        display_name="Member A",
    )
    owner_b = RoomAccessContext(
        room_id=room_b_id,
        access_session_id=uuid4(),
        authority=RoomAccessAuthority.OWNER,
        display_name="Owner B",
    )

    token_to_context = {
        token_owner_a: owner_a,
        token_dm_a: dm_a,
        token_member_a: member_a,
        token_owner_b: owner_b,
    }

    def _override_access_context(request: Request) -> RoomAccessContext:
        auth_header = request.headers.get("authorization", "")
        scheme, _, token = auth_header.partition(" ")
        token_clean = token.strip()
        if token_clean in token_to_context:
            return token_to_context[token_clean]
        raise APIError(401, "room_access_required", "Room access token is required")

    app.state.room_asset_service = room_asset_service
    app.state.adventure_service = adventure_service
    app.state.adventure_import_service = import_service
    app.dependency_overrides[get_database_engine] = lambda: engine
    app.dependency_overrides[get_room_access_context] = _override_access_context

    client = TestClient(app)
    try:
        yield ReviewApiFixture(
            client=client,
            engine=engine,
            room_a_id=room_a_id,
            room_b_id=room_b_id,
            token_owner_a=token_owner_a,
            token_dm_a=token_dm_a,
            token_member_a=token_member_a,
            token_owner_b=token_owner_b,
            owner_a=owner_a,
            dm_a=dm_a,
            member_a=member_a,
            owner_b=owner_b,
            tmp_path=tmp_path,
            room_asset_service=room_asset_service,
            adventure_service=adventure_service,
            import_service=import_service,
        )
    finally:
        try:
            del app.state.room_asset_service
        except (AttributeError, KeyError):
            pass
        try:
            del app.state.adventure_service
        except (AttributeError, KeyError):
            pass
        try:
            del app.state.adventure_import_service
        except (AttributeError, KeyError):
            pass
        app.dependency_overrides.pop(get_database_engine, None)
        app.dependency_overrides.pop(get_room_access_context, None)


def _seed_import_with_draft(
    fix: ReviewApiFixture,
    room_id: UUID,
    *,
    entries: list[DraftEntry] | None = None,
    warnings: list[DraftWarning] | None = None,
    questions: list[DraftQuestion] | None = None,
) -> tuple[UUID, int]:
    context = fix.owner_a if room_id == fix.room_a_id else fix.owner_b
    imp = fix.import_service.create_import(
        context,
        room_id=room_id,
        name="Review Test Adventure",
    )
    entry_list = entries if entries is not None else [
        DraftEntry(
            entry_id="scene_1",
            entry_kind="scene",
            payload=ScenePayload(kind="scene", dm_summary="Ambush site"),
        )
    ]
    warning_list = warnings if warnings is not None else [
        DraftWarning(
            warning_id="warn_1",
            level="warning",
            code="test_warning",
            message="Test warning message",
        )
    ]
    question_list = questions if questions is not None else [
        DraftQuestion(
            question_id="q_1",
            message="Test question?",
        )
    ]
    draft_view = fix.import_service.update_draft(
        context,
        room_id=room_id,
        import_id=imp.id,
        draft=ImportDraft(entries=entry_list, questions=question_list),
        warnings=warning_list,
        expected_revision=0,
    )
    return imp.id, draft_view.revision


@pytest.mark.parametrize("role", ["owner", "dm"])
def test_all_four_routes_happy_path(api_fixture: ReviewApiFixture, role: str) -> None:
    token = api_fixture.token_owner_a if role == "owner" else api_fixture.token_dm_a
    room_id = api_fixture.room_a_id
    client = api_fixture.client
    import_id, rev = _seed_import_with_draft(api_fixture, room_id)
    assert rev == 1

    # Route 1: set entry review
    resp1 = client.post(
        f"/api/rooms/{room_id}/adventure-imports/{import_id}/draft/entries/scene_1/review",
        json={"review_status": "accepted", "expected_revision": rev},
        headers=_auth(token),
    )
    assert resp1.status_code == 200
    draft1 = resp1.json()
    assert draft1["revision"] == 2
    assert draft1["draft"]["entries"][0]["review_status"] == "accepted"
    rev = draft1["revision"]

    # Route 2: resolve warning
    resp2 = client.post(
        f"/api/rooms/{room_id}/adventure-imports/{import_id}/warnings/warn_1/resolve",
        json={"resolution": "Resolved by DM", "expected_revision": rev},
        headers=_auth(token),
    )
    assert resp2.status_code == 200
    draft2 = resp2.json()
    assert draft2["revision"] == 3
    assert draft2["warnings"][0]["resolved"] is True
    assert draft2["warnings"][0]["resolution"] == "Resolved by DM"
    rev = draft2["revision"]

    # Route 3: answer question
    resp3 = client.post(
        f"/api/rooms/{room_id}/adventure-imports/{import_id}/questions/q_1/answer",
        json={"answer": "Cragmaw Hideout", "expected_revision": rev},
        headers=_auth(token),
    )
    assert resp3.status_code == 200
    draft3 = resp3.json()
    assert draft3["revision"] == 4
    assert draft3["draft"]["questions"][0]["answer"] == "Cragmaw Hideout"
    rev = draft3["revision"]

    # Route 4: finalize
    resp4 = client.post(
        f"/api/rooms/{room_id}/adventure-imports/{import_id}/finalize",
        json={"name": "Phandelver Final", "summary": "Full summary", "expected_revision": rev},
        headers=_auth(token),
    )
    assert resp4.status_code == 200
    adv = resp4.json()
    assert adv["name"] == "Phandelver Final"
    assert adv["status"] == "finalized"
    adventure_id = adv["id"]

    # Check GET import shows finalized and target_adventure_id
    get_resp = client.get(
        f"/api/rooms/{room_id}/adventure-imports/{import_id}",
        headers=_auth(token),
    )
    assert get_resp.status_code == 200
    imp_data = get_resp.json()
    assert imp_data["status"] == "finalized"
    assert imp_data["target_adventure_id"] == adventure_id


def test_second_finalize_returns_same_adventure_id(api_fixture: ReviewApiFixture) -> None:
    room_id = api_fixture.room_a_id
    token = api_fixture.token_owner_a
    client = api_fixture.client
    import_id, rev = _seed_import_with_draft(api_fixture, room_id)

    resp1 = client.post(
        f"/api/rooms/{room_id}/adventure-imports/{import_id}/finalize",
        json={"name": "Adventure One", "expected_revision": rev},
        headers=_auth(token),
    )
    assert resp1.status_code == 200
    adv1 = resp1.json()

    # Retry finalize (with different revision or name) returns same Adventure
    resp2 = client.post(
        f"/api/rooms/{room_id}/adventure-imports/{import_id}/finalize",
        json={"name": "Adventure Retry", "expected_revision": 999},
        headers=_auth(token),
    )
    assert resp2.status_code == 200
    adv2 = resp2.json()
    assert adv2["id"] == adv1["id"]
    assert adv2["name"] == adv1["name"]


ROUTES_FOR_AUTH = [
    (
        "review_entry",
        "/draft/entries/scene_1/review",
        {"review_status": "accepted", "expected_revision": 1},
    ),
    (
        "resolve_warning",
        "/warnings/warn_1/resolve",
        {"resolution": "Resolved", "expected_revision": 1},
    ),
    (
        "answer_question",
        "/questions/q_1/answer",
        {"answer": "Answer", "expected_revision": 1},
    ),
    (
        "finalize",
        "/finalize",
        {"name": "Adv", "expected_revision": 1},
    ),
]


@pytest.mark.parametrize(
    ("route_name", "path_suffix", "payload"),
    ROUTES_FOR_AUTH,
)
def test_routes_denied_for_member_and_other_room_with_zero_side_effects(
    api_fixture: ReviewApiFixture,
    route_name: str,
    path_suffix: str,
    payload: dict[str, object],
) -> None:
    room_id = api_fixture.room_a_id
    client = api_fixture.client
    import_id, rev = _seed_import_with_draft(api_fixture, room_id)

    # 1. MEMBER denied 403
    resp_member = client.post(
        f"/api/rooms/{room_id}/adventure-imports/{import_id}{path_suffix}",
        json=payload,
        headers=_auth(api_fixture.token_member_a),
    )
    assert resp_member.status_code == 403
    assert resp_member.json()["error"]["code"] == "adventure_import_authority_required"

    # 2. Non-member / other-Room owner denied 404
    resp_b = client.post(
        f"/api/rooms/{room_id}/adventure-imports/{import_id}{path_suffix}",
        json=payload,
        headers=_auth(api_fixture.token_owner_b),
    )
    assert resp_b.status_code == 404
    assert resp_b.json()["error"]["code"] == "adventure_import_not_found"

    # 3. Verify zero side effects: draft revision unchanged, no adventure rows created
    with api_fixture.engine.connect() as conn:
        rev_db = conn.execute(
            select(adventure_import_drafts.c.revision).where(
                adventure_import_drafts.c.import_id == import_id
            )
        ).scalar_one()
        target_adv = conn.execute(
            select(adventure_imports.c.target_adventure_id).where(adventure_imports.c.id == import_id)
        ).scalar_one()
        adv_count = conn.execute(select(func.count()).select_from(adventure_definitions)).scalar_one()
    assert rev_db == rev
    assert target_adv is None
    assert adv_count == 0


@pytest.mark.parametrize(
    ("route_name", "path_suffix", "payload"),
    ROUTES_FOR_AUTH,
)
def test_routes_stale_expected_revision_returns_409(
    api_fixture: ReviewApiFixture,
    route_name: str,
    path_suffix: str,
    payload: dict[str, object],
) -> None:
    room_id = api_fixture.room_a_id
    token = api_fixture.token_owner_a
    client = api_fixture.client
    import_id, _ = _seed_import_with_draft(api_fixture, room_id)

    stale_payload = {**payload, "expected_revision": 999}
    resp = client.post(
        f"/api/rooms/{room_id}/adventure-imports/{import_id}{path_suffix}",
        json=stale_payload,
        headers=_auth(token),
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "adventure_import_revision_conflict"


def test_unresolved_blocking_warning_blocks_finalize_until_resolved(
    api_fixture: ReviewApiFixture,
) -> None:
    room_id = api_fixture.room_a_id
    token = api_fixture.token_owner_a
    client = api_fixture.client
    blocking_warn = DraftWarning(
        warning_id="blocker_99",
        level="blocking",
        code="missing_parent",
        message="Parent does not exist",
    )
    import_id, rev = _seed_import_with_draft(
        api_fixture,
        room_id,
        warnings=[blocking_warn],
    )

    # Attempt finalize -> 409 blocking
    resp = client.post(
        f"/api/rooms/{room_id}/adventure-imports/{import_id}/finalize",
        json={"name": "Will Fail", "expected_revision": rev},
        headers=_auth(token),
    )
    assert resp.status_code == 409
    err = resp.json()["error"]
    assert err["code"] == "adventure_import_blocking_warnings"
    assert err["params"]["warning_ids"] == ["blocker_99"]

    # Resolve the blocking warning via the resolve route
    resp_resolve = client.post(
        f"/api/rooms/{room_id}/adventure-imports/{import_id}/warnings/blocker_99/resolve",
        json={"resolution": "Parent remapped", "expected_revision": rev},
        headers=_auth(token),
    )
    assert resp_resolve.status_code == 200
    rev2 = resp_resolve.json()["revision"]
    assert rev2 == rev + 1

    # Now finalize succeeds
    resp_fin = client.post(
        f"/api/rooms/{room_id}/adventure-imports/{import_id}/finalize",
        json={"name": "Now Succeeds", "expected_revision": rev2},
        headers=_auth(token),
    )
    assert resp_fin.status_code == 200
    assert resp_fin.json()["status"] == "finalized"


@pytest.mark.parametrize(
    ("route_suffix", "body"),
    [
        (
            "/draft/entries/unknown_entry/review",
            {"review_status": "accepted", "expected_revision": 1},
        ),
        (
            "/warnings/unknown_warn/resolve",
            {"resolution": "Resolved", "expected_revision": 1},
        ),
        (
            "/questions/unknown_q/answer",
            {"answer": "Answer", "expected_revision": 1},
        ),
    ],
)
def test_unknown_item_id_returns_404(
    api_fixture: ReviewApiFixture,
    route_suffix: str,
    body: dict[str, object],
) -> None:
    room_id = api_fixture.room_a_id
    token = api_fixture.token_owner_a
    client = api_fixture.client
    import_id, _ = _seed_import_with_draft(api_fixture, room_id)

    resp = client.post(
        f"/api/rooms/{room_id}/adventure-imports/{import_id}{route_suffix}",
        json=body,
        headers=_auth(token),
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "adventure_import_not_found"


@pytest.mark.parametrize(
    ("route_suffix", "body"),
    [
        (
            "/draft/entries/scene_1/review",
            {"review_status": "accepted", "expected_revision": 1},
        ),
        (
            "/warnings/warn_1/resolve",
            {"resolution": "Resolved", "expected_revision": 1},
        ),
        (
            "/questions/q_1/answer",
            {"answer": "Answer", "expected_revision": 1},
        ),
        (
            "/finalize",
            {"name": "Cross Room Finalize", "expected_revision": 1},
        ),
    ],
)
def test_room_b_import_under_room_a_returns_404(
    api_fixture: ReviewApiFixture,
    route_suffix: str,
    body: dict[str, object],
) -> None:
    import_b_id, _ = _seed_import_with_draft(api_fixture, api_fixture.room_b_id)

    resp = api_fixture.client.post(
        f"/api/rooms/{api_fixture.room_a_id}/adventure-imports/{import_b_id}{route_suffix}",
        json=body,
        headers=_auth(api_fixture.token_owner_a),
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "adventure_import_not_found"


def test_finalize_missing_asset_id_returns_404_and_rolls_back(
    api_fixture: ReviewApiFixture,
) -> None:
    room_id = api_fixture.room_a_id
    token = api_fixture.token_owner_a
    client = api_fixture.client
    missing_asset_id = uuid4()
    entry = DraftEntry(
        entry_id="scene_with_bad_asset",
        entry_kind="scene",
        payload=ScenePayload(kind="scene", dm_summary="Cave with asset"),
        asset_ids=[missing_asset_id],
    )
    import_id, rev = _seed_import_with_draft(
        api_fixture,
        room_id,
        entries=[entry],
    )

    resp = client.post(
        f"/api/rooms/{room_id}/adventure-imports/{import_id}/finalize",
        json={"name": "Will Fail On Asset", "expected_revision": rev},
        headers=_auth(token),
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "adventure_entry_asset_not_found"

    # Verify zero adventure rows in database
    with api_fixture.engine.connect() as conn:
        def_count = conn.execute(select(func.count()).select_from(adventure_definitions)).scalar_one()
        entry_count = conn.execute(select(func.count()).select_from(adventure_entries)).scalar_one()
        asset_count = conn.execute(select(func.count()).select_from(adventure_entry_assets)).scalar_one()
    assert def_count == 0
    assert entry_count == 0
    assert asset_count == 0
