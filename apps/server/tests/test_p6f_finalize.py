from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, event, insert, select
from sqlalchemy.engine import Engine

from app.config import Settings
from app.domain.adventure_imports.errors import (
    AdventureImportBlockingWarningsError,
    AdventureImportForbiddenError,
    AdventureImportNotFoundError,
    AdventureImportRevisionConflictError,
    AdventureImportValidationError,
)
from app.domain.adventure_imports.schemas import (
    DraftEntry,
    DraftWarning,
    ImportDraft,
)
from app.domain.adventure_imports.service import AdventureImportService
from app.domain.adventures.payloads import (
    NpcPayload,
    ScenePayload,
    SectionPayload,
    SecretPayload,
)
from app.domain.adventures.schemas import AdventureEntryAssetNotFoundError
from app.domain.adventures.service import AdventureService
from app.domain.room_assets.service import RoomAssetService
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.table_events import TableEventService
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
class FinalizeFixture:
    engine: Engine
    import_repo: AdventureImportRepository
    asset_repo: RoomAssetRepository
    adventure_repo: AdventureRepository
    asset_service: RoomAssetService
    adventure_service: AdventureService
    import_service: AdventureImportService
    settings: Settings
    room_a_id: UUID
    room_b_id: UUID
    owner_a: RoomAccessContext
    dm_a: RoomAccessContext
    member_a: RoomAccessContext
    owner_b: RoomAccessContext


def _create_sqlite_engine(db_path: Path) -> Engine:
    engine = create_engine(f"sqlite+pysqlite:///{db_path.as_posix()}")

    @event.listens_for(engine, "connect")
    def _enable_fks(dbapi_conn, _connection_record) -> None:
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    for table in TABLES_TO_CREATE:
        table.create(engine, checkfirst=True)
    return engine


def _ctx(r_id: UUID, auth: RoomAccessAuthority, name: str) -> RoomAccessContext:
    return RoomAccessContext(
        room_id=r_id,
        access_session_id=uuid4(),
        authority=auth,
        display_name=name,
    )


def _import_with_draft(
    fix: FinalizeFixture,
    entries: list[DraftEntry],
    warnings: list[DraftWarning] | None = None,
) -> tuple[UUID, int]:
    imp = fix.import_service.create_import(fix.owner_a, fix.room_a_id, "Import")
    draft_view = fix.import_service.update_draft(
        fix.owner_a,
        fix.room_a_id,
        imp.id,
        draft=ImportDraft(entries=entries),
        warnings=warnings or [],
        expected_revision=0,
    )
    return imp.id, draft_view.revision


def _section(entry_id: str, **fields: object) -> DraftEntry:
    return DraftEntry.model_validate(
        {"entry_id": entry_id, "entry_kind": "section", "payload": {"kind": "section"}, **fields}
    )


@pytest.fixture
def fix(tmp_path: Path) -> FinalizeFixture:
    db_path = tmp_path / "test_finalize.db"
    engine = _create_sqlite_engine(db_path)
    now = datetime.now(timezone.utc)
    room_a_id = uuid4()
    room_b_id = uuid4()

    room_defaults = {
        "password_salt": b"salt",
        "password_hash": b"pw",
        "owner_key_hash": b"owner",
        "dm_key_hash": b"dm",
        "created_at": now,
        "updated_at": now,
    }
    with engine.begin() as conn:
        conn.execute(
            insert(rooms).values(
                [
                    {"id": room_a_id, "code": "ROOM-A", "name": "Room A", **room_defaults},
                    {"id": room_b_id, "code": "ROOM-B", "name": "Room B", **room_defaults},
                ]
            )
        )

    settings = Settings()
    import_repo = AdventureImportRepository(engine)
    asset_repo = RoomAssetRepository(engine)
    adventure_repo = AdventureRepository(engine)
    asset_storage = FilesystemAssetStorage(tmp_path / "assets")
    asset_service = RoomAssetService(
        asset_repo,
        asset_storage,
        max_image_bytes=settings.asset_max_image_bytes,
        max_source_document_bytes=settings.asset_max_source_document_bytes,
    )
    adventure_service = AdventureService(adventure_repo, asset_repo)
    import_service = AdventureImportService(
        import_repo,
        settings,
        asset_service,
        adventure_service,
        TableEventService(TableEventRepository(engine)),
    )

    return FinalizeFixture(
        engine=engine,
        import_repo=import_repo,
        asset_repo=asset_repo,
        adventure_repo=adventure_repo,
        asset_service=asset_service,
        adventure_service=adventure_service,
        import_service=import_service,
        settings=settings,
        room_a_id=room_a_id,
        room_b_id=room_b_id,
        owner_a=_ctx(room_a_id, RoomAccessAuthority.OWNER, "Owner A"),
        dm_a=_ctx(room_a_id, RoomAccessAuthority.DM, "DM A"),
        member_a=_ctx(room_a_id, RoomAccessAuthority.MEMBER, "Member A"),
        owner_b=_ctx(room_b_id, RoomAccessAuthority.OWNER, "Owner B"),
    )


def test_finalize_success_full_structure(fix: FinalizeFixture) -> None:
    # Upload an asset in Room A
    asset_a = fix.asset_service.create(
        fix.owner_a,
        room_id=fix.room_a_id,
        kind="source_document",
        filename="notes.pdf",
        mime_type="application/pdf",
        data=b"%PDF-1.4 test content",
        visibility="dm_only",
    )

    imp = fix.import_service.create_import(fix.owner_a, fix.room_a_id, "Import Alpha")

    # Draft with child listed before parent, ignored middle, child of ignored re-attached,
    # default visibility (dm_only) and explicit public visibility, and asset link
    entries = [
        DraftEntry(
            entry_id="child-early",
            entry_kind="npc",
            payload=NpcPayload(role="Guide", disposition="friendly"),
            parent_entry_id="parent-late",
            title="Guide Bob",
            body="Helpful guide",
            review_status="pending",
        ),
        DraftEntry(
            entry_id="parent-late",
            entry_kind="section",
            payload=SectionPayload(),
            parent_entry_id=None,
            title="Act I",
            body="Introduction section",
            review_status="pending",
        ),
        DraftEntry(
            entry_id="ignored-middle",
            entry_kind="section",
            payload=SectionPayload(),
            parent_entry_id="parent-late",
            title="Cut Content",
            review_status="ignored",
        ),
        DraftEntry(
            entry_id="scene-1",
            entry_kind="scene",
            payload=ScenePayload(dm_summary="Cave entrance", exits=("North",)),
            parent_entry_id="ignored-middle",
            title="Cave Entrance",
            body="Dark and damp",
            visibility="public",
            review_status="accepted",
            asset_ids=[asset_a.id],
        ),
        DraftEntry(
            entry_id="secret-1",
            entry_kind="secret",
            payload=SecretPayload(reveal_condition="DC 15 Perception"),
            parent_entry_id="scene-1",
            title="Hidden Stash",
            body="Behind loose rock",
            review_status="uncertain",
        ),
    ]

    draft_view = fix.import_service.update_draft(
        fix.owner_a,
        fix.room_a_id,
        imp.id,
        draft=ImportDraft(entries=entries),
        warnings=[],
        expected_revision=0,
    )

    finalized_def = fix.import_service.finalize_adventure(
        fix.owner_a,
        fix.room_a_id,
        imp.id,
        name="Finalized Adventure",
        summary="A grand quest",
        expected_revision=draft_view.revision,
    )

    assert finalized_def.status == "finalized"
    assert finalized_def.name == "Finalized Adventure"
    assert finalized_def.summary == "A grand quest"

    # Verify import row status and target_adventure_id
    stored_imp = fix.import_service.get_import(fix.owner_a, fix.room_a_id, imp.id)
    assert stored_imp.status == "finalized"
    assert stored_imp.target_adventure_id == finalized_def.id

    # Verify entries in AdventureDefinition
    created_entries = fix.adventure_service.list_entries(
        fix.owner_a, fix.room_a_id, finalized_def.id
    )
    assert len(created_entries) == 4

    by_title = {e.title: e for e in created_entries}
    assert "Cut Content" not in by_title

    parent_entry = by_title["Act I"]
    child_early_entry = by_title["Guide Bob"]
    scene_entry = by_title["Cave Entrance"]
    secret_entry = by_title["Hidden Stash"]

    # Explicit sort_order follows draft list order among included entries:
    # 0: child-early, 1: parent-late, 2: scene-1, 3: secret-1
    assert child_early_entry.sort_order == 0
    assert parent_entry.sort_order == 1
    assert scene_entry.sort_order == 2
    assert secret_entry.sort_order == 3

    # Hierarchy: parent_late is root
    assert parent_entry.parent_entry_id is None

    # child_early was child of parent_late
    assert child_early_entry.parent_entry_id == parent_entry.id

    # scene_1's draft parent was ignored-middle; re-attached to nearest ancestor (parent_late)
    assert scene_entry.parent_entry_id == parent_entry.id

    # secret_1's draft parent was scene_1
    assert secret_entry.parent_entry_id == scene_entry.id

    # Visibility: default is dm_only, scene_1 was explicitly public
    assert parent_entry.visibility == "dm_only"
    assert child_early_entry.visibility == "dm_only"
    assert scene_entry.visibility == "public"
    assert secret_entry.visibility == "dm_only"

    # Asset linked with role attachment
    assert len(scene_entry.assets) == 1
    assert scene_entry.assets[0].asset.id == asset_a.id
    assert scene_entry.assets[0].role == "attachment"

    # Payloads
    assert isinstance(scene_entry.data, ScenePayload)
    assert scene_entry.data.dm_summary == "Cave entrance"
    assert isinstance(child_early_entry.data, NpcPayload)
    assert child_early_entry.data.role == "Guide"


def test_finalize_pending_only_draft(fix: FinalizeFixture) -> None:
    import_id, revision = _import_with_draft(fix, [_section("sec-1"), _section("sec-2")])

    adv = fix.import_service.finalize_adventure(
        fix.dm_a, fix.room_a_id, import_id, name="Pending Adventure", expected_revision=revision
    )

    assert adv.status == "finalized"
    assert len(fix.adventure_service.list_entries(fix.owner_a, fix.room_a_id, adv.id)) == 2


def test_finalize_idempotency_retry(fix: FinalizeFixture) -> None:
    import_id, revision = _import_with_draft(fix, [_section("s1")])

    results = [
        fix.import_service.finalize_adventure(
            fix.owner_a, fix.room_a_id, import_id, name=name, expected_revision=expected
        )
        for name, expected in [("Idempotent Adv", revision), ("Retry", revision), ("Stale", 999)]
    ]

    assert {adv.id for adv in results} == {results[0].id}
    assert results[1].name == "Idempotent Adv"
    definitions = fix.adventure_service.list_definitions(fix.owner_a, fix.room_a_id)
    assert [d.id for d in definitions] == [results[0].id]


def test_finalize_blocking_warnings_gate(fix: FinalizeFixture) -> None:
    warnings = [
        DraftWarning(warning_id=f"w-{level}", level=level, code=level.upper(), message=level)
        for level in ("info", "warning", "blocking")
    ]
    import_id, revision = _import_with_draft(fix, [_section("s1")], warnings)

    with pytest.raises(AdventureImportBlockingWarningsError) as exc_info:
        fix.import_service.finalize_adventure(
            fix.owner_a, fix.room_a_id, import_id, name="Blocked", expected_revision=revision
        )
    assert exc_info.value.unresolved_warning_ids == ["w-blocking"]
    assert fix.adventure_service.list_definitions(fix.owner_a, fix.room_a_id) == []
    stored_imp = fix.import_service.get_import(fix.owner_a, fix.room_a_id, import_id)
    assert (stored_imp.status, stored_imp.target_adventure_id) == ("drafting", None)

    resolved_view = fix.import_service.resolve_import_warning(
        fix.owner_a,
        fix.room_a_id,
        import_id,
        warning_id="w-blocking",
        resolution="Resolved by DM",
        expected_revision=revision,
    )
    # Unresolved info / warning levels do not block.
    adv = fix.import_service.finalize_adventure(
        fix.owner_a,
        fix.room_a_id,
        import_id,
        name="Unblocked Adv",
        expected_revision=resolved_view.revision,
    )
    assert adv.status == "finalized"


def test_finalize_stale_expected_revision(fix: FinalizeFixture) -> None:
    import_id, revision = _import_with_draft(fix, [])
    assert revision == 1

    with pytest.raises(AdventureImportRevisionConflictError):
        fix.import_service.finalize_adventure(
            fix.owner_a, fix.room_a_id, import_id, name="Conflict", expected_revision=0
        )

    assert fix.adventure_service.list_definitions(fix.owner_a, fix.room_a_id) == []
    stored_imp = fix.import_service.get_import(fix.owner_a, fix.room_a_id, import_id)
    assert (stored_imp.status, stored_imp.revision) == ("drafting", 1)


def _assert_no_adventure_rows(fix: FinalizeFixture, import_id: UUID) -> None:
    with fix.engine.connect() as conn:
        for table in (adventure_definitions, adventure_entries, adventure_entry_assets):
            assert conn.execute(select(table)).all() == []
    stored_imp = fix.import_service.get_import(fix.owner_a, fix.room_a_id, import_id)
    assert (stored_imp.status, stored_imp.target_adventure_id, stored_imp.revision) == (
        "drafting",
        None,
        1,
    )


@pytest.mark.parametrize("invalid_asset_type", ["missing", "cross_room"])
def test_finalize_rollback_on_invalid_asset(
    fix: FinalizeFixture, invalid_asset_type: str
) -> None:
    if invalid_asset_type == "missing":
        bad_asset_id = uuid4()
    else:
        bad_asset_id = fix.asset_service.create(
            fix.owner_b,
            room_id=fix.room_b_id,
            kind="source_document",
            filename="room_b.pdf",
            mime_type="application/pdf",
            data=b"%PDF Room B only",
            visibility="dm_only",
        ).id
    # The first entry is created before the bad link fails, so rollback must remove it.
    import_id, revision = _import_with_draft(
        fix, [_section("ok"), _section("bad", asset_ids=[str(bad_asset_id)])]
    )

    with pytest.raises(AdventureEntryAssetNotFoundError):
        fix.import_service.finalize_adventure(
            fix.owner_a, fix.room_a_id, import_id, name="Rollback Def", expected_revision=revision
        )

    _assert_no_adventure_rows(fix, import_id)


def test_finalize_parent_cycle_rejected_and_rolled_back(fix: FinalizeFixture) -> None:
    import_id, revision = _import_with_draft(
        fix,
        [
            _section("root"),
            _section("a", parent_entry_id="b"),
            _section("b", parent_entry_id="a"),
        ],
    )

    with pytest.raises(AdventureImportValidationError, match="cycle"):
        fix.import_service.finalize_adventure(
            fix.owner_a, fix.room_a_id, import_id, name="Cycle", expected_revision=revision
        )

    _assert_no_adventure_rows(fix, import_id)

def test_finalize_cancelled_rejected(fix: FinalizeFixture) -> None:
    imp = fix.import_service.create_import(fix.owner_a, fix.room_a_id, "Cancel Test")
    fix.import_service.cancel_import(fix.owner_a, fix.room_a_id, imp.id, expected_revision=0)

    with pytest.raises(AdventureImportValidationError) as exc_info:
        fix.import_service.finalize_adventure(
            fix.owner_a,
            fix.room_a_id,
            imp.id,
            name="Cancelled Finalize",
            expected_revision=0,
        )
    assert "cancelled" in str(exc_info.value).lower()

    # Zero side effects
    assert len(fix.adventure_service.list_definitions(fix.owner_a, fix.room_a_id)) == 0


@pytest.mark.parametrize(
    "actor_key,expected_err",
    [
        ("member_a", AdventureImportForbiddenError),
        ("owner_b", AdventureImportNotFoundError),
    ],
)
def test_finalize_authority_rejected(
    fix: FinalizeFixture, actor_key: str, expected_err: type[Exception]
) -> None:
    context = fix.member_a if actor_key == "member_a" else fix.owner_b
    imp = fix.import_service.create_import(fix.owner_a, fix.room_a_id, "Auth Test")

    with pytest.raises(expected_err):
        fix.import_service.finalize_adventure(
            context,
            fix.room_a_id,
            imp.id,
            name="Auth Def",
            expected_revision=0,
        )

    # Zero side effects
    assert len(fix.adventure_service.list_definitions(fix.owner_a, fix.room_a_id)) == 0
    stored_imp = fix.import_service.get_import(fix.owner_a, fix.room_a_id, imp.id)
    assert stored_imp.status == "source"


def test_finalize_old_draft_json_defaults(fix: FinalizeFixture) -> None:
    imp = fix.import_service.create_import(fix.owner_a, fix.room_a_id, "Old JSON Test")

    # Manually insert a draft row with old JSON schema (no title, body, visibility)
    now = datetime.now(timezone.utc)
    old_draft_json = {
        "schema_version": 1,
        "entries": [
            {
                "entry_id": "old-entry-1",
                "entry_kind": "scene",
                "payload": {"kind": "scene", "dm_summary": "Ancient ruins"},
                "review_status": "accepted",
                "provenance": "source_document",
            }
        ],
        "questions": [],
    }
    with fix.engine.begin() as conn:
        conn.execute(
            insert(adventure_import_drafts).values(
                import_id=imp.id,
                draft_json=old_draft_json,
                warnings_json=[],
                revision=1,
                updated_at=now,
            )
        )

    # Load via get_draft and verify defaults
    draft_view = fix.import_service.get_draft(fix.owner_a, fix.room_a_id, imp.id)
    entry = draft_view.draft.entries[0]
    assert entry.title is None
    assert entry.body is None
    assert entry.visibility == "dm_only"

    # Finalize and verify the created entry has the defaults
    adv = fix.import_service.finalize_adventure(
        fix.owner_a,
        fix.room_a_id,
        imp.id,
        name="From Old Draft",
        expected_revision=1,
    )
    created_entries = fix.adventure_service.list_entries(fix.owner_a, fix.room_a_id, adv.id)
    assert len(created_entries) == 1
    assert created_entries[0].title is None
    assert created_entries[0].body is None
    assert created_entries[0].visibility == "dm_only"
