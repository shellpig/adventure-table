from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, event, insert
from sqlalchemy.engine import Engine

from app.config import Settings
from app.domain.adventure_imports.errors import (
    AdventureImportForbiddenError,
    AdventureImportNotFoundError,
    AdventureImportRevisionConflictError,
    AdventureImportValidationError,
)
from app.domain.adventure_imports.schemas import (
    AdventureImportDraft,
    DraftEntry,
    DraftQuestion,
    DraftWarning,
    ImportDraft,
    ReviewStatus,
    unresolved_blocking_warnings,
)
from app.domain.adventure_imports.service import AdventureImportService
from app.domain.adventures.payloads import ScenePayload
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
from app.domain.adventures.service import AdventureService
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
class ReviewStateFixture:
    engine: Engine
    repo: AdventureImportRepository
    service: AdventureImportService
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


@pytest.fixture
def fixture(tmp_path: Path) -> ReviewStateFixture:
    db_path = tmp_path / "test_p6f_review_state.db"
    engine = _create_sqlite_engine(db_path)
    now = datetime.now(timezone.utc)
    room_a_id, room_b_id = uuid4(), uuid4()

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

    repo = AdventureImportRepository(engine)
    settings = Settings()
    asset_storage = FilesystemAssetStorage(tmp_path / "assets")
    asset_repo = RoomAssetRepository(engine)
    asset_service = RoomAssetService(
        asset_repo,
        asset_storage,
        max_image_bytes=settings.asset_max_image_bytes,
        max_source_document_bytes=settings.asset_max_source_document_bytes,
    )
    adventure_repo = AdventureRepository(engine)
    adventure_service = AdventureService(adventure_repo, asset_repo)
    service = AdventureImportService(
        repo,
        settings,
        asset_service,
        adventure_service,
        TableEventService(TableEventRepository(engine)),
    )

    def _ctx(r_id: UUID, auth: RoomAccessAuthority, name: str) -> RoomAccessContext:
        return RoomAccessContext(room_id=r_id, access_session_id=uuid4(), authority=auth, display_name=name)

    return ReviewStateFixture(
        engine=engine,
        repo=repo,
        service=service,
        settings=settings,
        room_a_id=room_a_id,
        room_b_id=room_b_id,
        owner_a=_ctx(room_a_id, RoomAccessAuthority.OWNER, "Owner A"),
        dm_a=_ctx(room_a_id, RoomAccessAuthority.DM, "DM A"),
        member_a=_ctx(room_a_id, RoomAccessAuthority.MEMBER, "Member A"),
        owner_b=_ctx(room_b_id, RoomAccessAuthority.OWNER, "Owner B"),
    )


def _seed_import_with_draft(
    fixture: ReviewStateFixture,
    *,
    entries: list[DraftEntry] | None = None,
    warnings: list[DraftWarning] | None = None,
    questions: list[DraftQuestion] | None = None,
) -> tuple[UUID, AdventureImportDraft, AdventureImport]:
    imp = fixture.service.create_import(fixture.owner_a, fixture.room_a_id, "P6F Import")
    draft_entries = entries if entries is not None else [
        DraftEntry(entry_id="entry-1", entry_kind="scene", payload=ScenePayload(read_aloud="Entrance"), provenance="source_document")
    ]
    draft_warnings = warnings if warnings is not None else [
        DraftWarning(warning_id="warn-1", level="warning", code="missing_detail", message="Detail missing")
    ]
    draft_questions = questions if questions is not None else [
        DraftQuestion(question_id="quest-1", message="Question?")
    ]

    draft = fixture.service.update_draft(
        fixture.owner_a,
        fixture.room_a_id,
        imp.id,
        draft=ImportDraft(entries=draft_entries, questions=draft_questions),
        warnings=draft_warnings,
        expected_revision=0,
    )
    current_import = fixture.service.get_import(fixture.owner_a, fixture.room_a_id, imp.id)
    return imp.id, draft, current_import


def _assert_import_unchanged(
    fixture: ReviewStateFixture,
    import_id: UUID,
    initial_draft: AdventureImportDraft,
    initial_import: AdventureImport,
) -> None:
    draft = fixture.service.get_draft(fixture.owner_a, fixture.room_a_id, import_id)
    assert draft.revision == initial_draft.revision
    assert draft.draft.entries[0].review_status == initial_draft.draft.entries[0].review_status
    assert draft.warnings[0].resolved == initial_draft.warnings[0].resolved
    assert draft.draft.questions[0].answer == initial_draft.draft.questions[0].answer

    imp = fixture.service.get_import(fixture.owner_a, fixture.room_a_id, import_id)
    assert imp.status == initial_import.status
    assert imp.revision == initial_import.revision


REVIEW_INTENTS: dict[
    str,
    Callable[[AdventureImportService, RoomAccessContext, UUID, UUID, str, int], object],
] = {
    "entry_review": lambda s, ctx, r_id, imp_id, target, rev: s.set_entry_review(
        ctx, r_id, imp_id, entry_id=target, review_status="accepted", expected_revision=rev
    ),
    "resolve_warning": lambda s, ctx, r_id, imp_id, target, rev: s.resolve_import_warning(
        ctx, r_id, imp_id, warning_id=target, resolution="Fix", expected_revision=rev
    ),
    "answer_question": lambda s, ctx, r_id, imp_id, target, rev: s.answer_import_question(
        ctx, r_id, imp_id, question_id=target, answer="Ans", expected_revision=rev
    ),
}
VALID_TARGETS = {"entry_review": "entry-1", "resolve_warning": "warn-1", "answer_question": "quest-1"}
MISSING_TARGETS = {"entry_review": "missing-e", "resolve_warning": "missing-w", "answer_question": "missing-q"}
INTENT_NAMES = ["entry_review", "resolve_warning", "answer_question"]


# --- 1. Happy Path & Revision Increments for Three Intents ---


def test_set_entry_review_happy_path_and_revision_increments(
    fixture: ReviewStateFixture,
) -> None:
    asset_id = uuid4()
    entry = DraftEntry(
        entry_id="entry-dungeon",
        entry_kind="scene",
        payload=ScenePayload(read_aloud="Dungeon Cell"),
        provenance="ai_generated",
        note="Generated from excerpt",
        asset_ids=[asset_id],
    )
    import_id, draft, _ = _seed_import_with_draft(fixture, entries=[entry])
    assert draft.revision == 1
    assert draft.draft.entries[0].review_status == "pending"

    # Step through all four review statuses: pending -> accepted -> ignored -> uncertain -> pending
    expected_transitions: list[tuple[ReviewStatus, int]] = [
        ("accepted", 2),
        ("ignored", 3),
        ("uncertain", 4),
        ("pending", 5),
    ]
    for new_status, next_rev in expected_transitions:
        draft = fixture.service.set_entry_review(
            fixture.owner_a,
            fixture.room_a_id,
            import_id,
            entry_id="entry-dungeon",
            review_status=new_status,
            expected_revision=draft.revision,
        )
        assert draft.revision == next_rev
        assert draft.draft.entries[0].review_status == new_status
        assert draft.draft.entries[0].provenance == "ai_generated"
        assert draft.draft.entries[0].asset_ids == [asset_id]

    # Invalid review_status is rejected
    with pytest.raises(AdventureImportValidationError):
        fixture.service.set_entry_review(
            fixture.owner_a,
            fixture.room_a_id,
            import_id,
            entry_id="entry-dungeon",
            review_status="invalid_status",  # type: ignore[arg-type]
            expected_revision=draft.revision,
        )


def test_resolve_import_warning_happy_path_and_re_resolve_rejection(
    fixture: ReviewStateFixture,
) -> None:
    warning = DraftWarning(
        warning_id="warn-unmapped",
        level="warning",
        code="unmapped_npc",
        message="NPC has no location",
    )
    import_id, draft_1, _ = _seed_import_with_draft(fixture, warnings=[warning])
    assert draft_1.revision == 1
    assert draft_1.warnings[0].resolved is False

    # Resolve with note (revision 1 -> 2)
    draft_2 = fixture.service.resolve_import_warning(
        fixture.owner_a,
        fixture.room_a_id,
        import_id,
        warning_id="warn-unmapped",
        resolution="Assigned to Entrance Hall",
        expected_revision=1,
    )
    assert draft_2.revision == 2
    assert draft_2.warnings[0].resolved is True
    assert draft_2.warnings[0].resolution == "Assigned to Entrance Hall"

    # Re-resolving already resolved warning raises AdventureImportValidationError
    with pytest.raises(AdventureImportValidationError, match="already resolved"):
        fixture.service.resolve_import_warning(
            fixture.owner_a,
            fixture.room_a_id,
            import_id,
            warning_id="warn-unmapped",
            resolution="Trying to resolve again",
            expected_revision=2,
        )

    # Draft in DB remains at revision 2
    check_draft = fixture.service.get_draft(fixture.owner_a, fixture.room_a_id, import_id)
    assert check_draft.revision == 2
    assert check_draft.warnings[0].resolved is True


def test_answer_import_question_happy_path(
    fixture: ReviewStateFixture,
) -> None:
    question = DraftQuestion(
        question_id="quest-lock",
        message="What DC is the chest lock?",
    )
    import_id, draft_1, _ = _seed_import_with_draft(fixture, questions=[question])
    assert draft_1.revision == 1
    assert draft_1.draft.questions[0].answer is None

    # Answer question (revision 1 -> 2)
    draft_2 = fixture.service.answer_import_question(
        fixture.owner_a,
        fixture.room_a_id,
        import_id,
        question_id="quest-lock",
        answer="DC 14 Dexterity (Thieves' Tools)",
        expected_revision=1,
    )
    assert draft_2.revision == 2
    assert draft_2.draft.questions[0].answer == "DC 14 Dexterity (Thieves' Tools)"

    # Update answer (revision 2 -> 3)
    draft_3 = fixture.service.answer_import_question(
        fixture.dm_a,
        fixture.room_a_id,
        import_id,
        question_id="quest-lock",
        answer="DC 15 Dexterity (Thieves' Tools)",
        expected_revision=2,
    )
    assert draft_3.revision == 3
    assert draft_3.draft.questions[0].answer == "DC 15 Dexterity (Thieves' Tools)"


# --- 2. Stale Revision Zero Side Effect (Parametrized) ---


@pytest.mark.parametrize("intent", INTENT_NAMES)
def test_stale_revision_zero_side_effect(
    fixture: ReviewStateFixture,
    intent: str,
) -> None:
    import_id, initial_draft, initial_import = _seed_import_with_draft(fixture)
    caller = REVIEW_INTENTS[intent]
    target_id = VALID_TARGETS[intent]

    for stale_rev in (0, 99):
        with pytest.raises(AdventureImportRevisionConflictError) as exc_info:
            caller(fixture.service, fixture.owner_a, fixture.room_a_id, import_id, target_id, stale_rev)
        assert exc_info.value.expected_revision == stale_rev
        assert exc_info.value.current_revision == 1

    # Stale revision precedence holds even if target id is missing
    with pytest.raises(AdventureImportRevisionConflictError):
        caller(fixture.service, fixture.owner_a, fixture.room_a_id, import_id, MISSING_TARGETS[intent], 0)

    _assert_import_unchanged(fixture, import_id, initial_draft, initial_import)


# --- 3. Missing Target ID Zero Side Effect (Parametrized) ---


@pytest.mark.parametrize("intent", INTENT_NAMES)
def test_missing_target_id_zero_side_effect(
    fixture: ReviewStateFixture,
    intent: str,
) -> None:
    import_id, initial_draft, initial_import = _seed_import_with_draft(fixture)
    with pytest.raises(AdventureImportNotFoundError):
        REVIEW_INTENTS[intent](
            fixture.service, fixture.owner_a, fixture.room_a_id, import_id, MISSING_TARGETS[intent], 1
        )
    _assert_import_unchanged(fixture, import_id, initial_draft, initial_import)


@pytest.mark.parametrize("intent", INTENT_NAMES)
def test_missing_target_id_on_empty_draft_without_prior_update(
    fixture: ReviewStateFixture,
    intent: str,
) -> None:
    imp = fixture.service.create_import(fixture.owner_a, fixture.room_a_id, "No Draft Import")
    with pytest.raises(AdventureImportNotFoundError):
        REVIEW_INTENTS[intent](
            fixture.service, fixture.owner_a, fixture.room_a_id, imp.id, MISSING_TARGETS[intent], 0
        )
    imp_after = fixture.service.get_import(fixture.owner_a, fixture.room_a_id, imp.id)
    assert imp_after.status == "source"
    assert imp_after.revision == 0


# --- 4. Old JSON Backward Compatibility (Schema v1) ---


def test_old_json_backward_compatibility(fixture: ReviewStateFixture) -> None:
    imp = fixture.service.create_import(fixture.owner_a, fixture.room_a_id, "Old JSON Import")
    now = datetime.now(timezone.utc)

    old_draft_json = {
        "schema_version": 1,
        "entries": [
            {
                "entry_id": "legacy-entry",
                "entry_kind": "scene",
                "payload": {"kind": "scene", "read_aloud": "Old Room"},
                "provenance": "source_document",
            }
        ],
        "questions": [{"question_id": "legacy-quest", "message": "Legacy query?"}],
    }
    old_warnings_json = [
        {"warning_id": "legacy-warn", "level": "warning", "code": "legacy_code", "message": "Legacy warning"}
    ]

    with fixture.engine.begin() as conn:
        conn.execute(
            insert(adventure_import_drafts).values(
                import_id=imp.id,
                draft_json=old_draft_json,
                warnings_json=old_warnings_json,
                revision=1,
                updated_at=now,
            )
        )

    loaded_draft = fixture.service.get_draft(fixture.owner_a, fixture.room_a_id, imp.id)
    assert loaded_draft.draft.schema_version == 1
    assert loaded_draft.draft.entries[0].review_status == "pending"
    assert loaded_draft.draft.entries[0].asset_ids == []
    assert loaded_draft.warnings[0].resolved is False
    assert loaded_draft.warnings[0].resolution is None

    # Review operations work normally on legacy draft
    updated_entry = fixture.service.set_entry_review(
        fixture.owner_a, fixture.room_a_id, imp.id, entry_id="legacy-entry", review_status="accepted", expected_revision=1
    )
    assert updated_entry.revision == 2
    assert updated_entry.draft.entries[0].review_status == "accepted"

    updated_warn = fixture.service.resolve_import_warning(
        fixture.owner_a, fixture.room_a_id, imp.id, warning_id="legacy-warn", resolution="Fixed", expected_revision=2
    )
    assert updated_warn.revision == 3
    assert updated_warn.warnings[0].resolved is True


# --- 5. Warning Level Filter (unresolved_blocking_warnings) ---


def test_unresolved_blocking_warnings_filter() -> None:
    warnings = [
        DraftWarning(warning_id="w1", level="info", code="c1", message="m1", resolved=False),
        DraftWarning(warning_id="w2", level="info", code="c2", message="m2", resolved=True, resolution="ok"),
        DraftWarning(warning_id="w3", level="warning", code="c3", message="m3", resolved=False),
        DraftWarning(warning_id="w4", level="warning", code="c4", message="m4", resolved=True, resolution="ok"),
        DraftWarning(warning_id="w5", level="blocking", code="c5", message="Missing field", resolved=False),
        DraftWarning(warning_id="w6", level="blocking", code="c6", message="Dangling ref", resolved=False),
        DraftWarning(warning_id="w7", level="blocking", code="c7", message="Fixed ref", resolved=True, resolution="fixed"),
    ]

    assert [w.warning_id for w in unresolved_blocking_warnings(warnings)] == ["w5", "w6"]

    draft = AdventureImportDraft(
        import_id=uuid4(),
        draft=ImportDraft(),
        warnings=warnings,
        revision=1,
        updated_at=datetime.now(timezone.utc),
    )
    assert [w.warning_id for w in unresolved_blocking_warnings(draft)] == ["w5", "w6"]

    resolved_blocking_only = [warnings[0], warnings[2], warnings[6]]
    assert unresolved_blocking_warnings(resolved_blocking_only) == []


# --- 6. Non-Fabrication Provenance Fixture (F.2: "門很難撬") ---


def test_nonfabrication_provenance_door_hard_to_pick(
    fixture: ReviewStateFixture,
) -> None:
    # Original text: "門很難撬" (The door is hard to pick) gives no numerical DC.
    # Suggested DC must be 'user_approximation' or 'ai_generated', never 'source_document'.
    suggested_dc = DraftEntry(
        entry_id="door-suggested-dc",
        entry_kind="scene",
        payload=ScenePayload(read_aloud="Iron Door"),
        note="Suggested DC 15 Dexterity (Thieves' Tools)",
        provenance="user_approximation",
    )
    narrative_dm = DraftEntry(
        entry_id="door-dm-decides",
        entry_kind="scene",
        payload=ScenePayload(read_aloud="Wooden Door"),
        note="DM decides DC narratively during play based on circumstance",
        provenance="user_explicit",
    )

    import_id, draft, _ = _seed_import_with_draft(fixture, entries=[suggested_dc, narrative_dm])

    # Reviewing entries preserves provenance without rewriting to 'source_document'
    draft_2 = fixture.service.set_entry_review(
        fixture.owner_a, fixture.room_a_id, import_id, entry_id="door-suggested-dc", review_status="accepted", expected_revision=1
    )
    assert draft_2.draft.entries[0].review_status == "accepted"
    assert draft_2.draft.entries[0].provenance == "user_approximation"

    draft_3 = fixture.service.set_entry_review(
        fixture.dm_a, fixture.room_a_id, import_id, entry_id="door-dm-decides", review_status="accepted", expected_revision=2
    )
    assert draft_3.draft.entries[1].review_status == "accepted"
    assert draft_3.draft.entries[1].provenance == "user_explicit"


# --- 7. Pending Entries Do Not Block (F.3 / Scope E) ---


def test_pending_entries_do_not_block(fixture: ReviewStateFixture) -> None:
    entries = [
        DraftEntry(
            entry_id=f"entry-{i}",
            entry_kind="scene",
            payload=ScenePayload(read_aloud=f"Room {i}"),
            review_status="pending",
        )
        for i in range(5)
    ]
    _, draft, _ = _seed_import_with_draft(fixture, entries=entries, warnings=[])
    assert all(e.review_status == "pending" for e in draft.draft.entries)
    assert len(unresolved_blocking_warnings(draft)) == 0


# --- 8. Authority Denial: MEMBER & Cross-Room with Zero Side Effect ---


@pytest.mark.parametrize("intent", INTENT_NAMES)
@pytest.mark.parametrize(
    "auth_kind,expected_err",
    [
        ("member", AdventureImportForbiddenError),
        ("cross_room", (AdventureImportForbiddenError, AdventureImportNotFoundError)),
    ],
    ids=["member", "cross_room"],
)
def test_authority_denial_zero_side_effect(
    fixture: ReviewStateFixture,
    intent: str,
    auth_kind: str,
    expected_err: type[Exception] | tuple[type[Exception], ...],
) -> None:
    import_id, initial_draft, initial_import = _seed_import_with_draft(fixture)
    ctx = fixture.member_a if auth_kind == "member" else fixture.owner_b

    with pytest.raises(expected_err):
        REVIEW_INTENTS[intent](
            fixture.service, ctx, fixture.room_a_id, import_id, VALID_TARGETS[intent], 1
        )

    _assert_import_unchanged(fixture, import_id, initial_draft, initial_import)
