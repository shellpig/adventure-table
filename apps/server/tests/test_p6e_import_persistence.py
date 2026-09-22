from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, delete, event, insert
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from app.db import metadata
from app.domain.adventure_imports.errors import (
    AdventureImportNotFoundError,
    AdventureImportRevisionConflictError,
)
from app.persistence.adventure_imports.repository import (
    AdventureImportRepository,
    StoredAdventureImport,
    StoredAdventureImportSource,
)
from app.persistence.adventure_imports.tables import (
    adventure_import_drafts,
    adventure_import_sources,
    adventure_imports,
)
from app.persistence.adventures.tables import adventure_definitions
from app.persistence.room_assets.tables import room_assets
from app.persistence.rooms.tables import campaigns, rooms


@dataclass(frozen=True)
class ImportRepoFixture:
    engine: Engine
    repo: AdventureImportRepository
    db_path: Path
    room_a_id: UUID
    room_b_id: UUID
    adv_id: UUID


TABLES_TO_CREATE = [
    rooms,
    campaigns,
    adventure_definitions,
    room_assets,
    adventure_imports,
    adventure_import_sources,
    adventure_import_drafts,
]


def _create_sqlite_engine(db_path: Path) -> Engine:
    engine = create_engine(f"sqlite+pysqlite:///{db_path.as_posix()}")

    @event.listens_for(engine, "connect")
    def _enable_fks(dbapi_conn, _connection_record) -> None:
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


@pytest.fixture
def repo_fixture(tmp_path: Path) -> ImportRepoFixture:
    db_path = tmp_path / "test_p6e_import.sqlite3"
    engine = _create_sqlite_engine(db_path)
    metadata.create_all(engine, tables=TABLES_TO_CREATE)
    repo = AdventureImportRepository(engine)

    room_a_id = uuid4()
    room_b_id = uuid4()
    adv_id = uuid4()
    now = datetime.now(timezone.utc)

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
            insert(adventure_definitions).values(
                id=adv_id,
                room_id=room_a_id,
                name="Adventure 1",
                summary=None,
                ruleset="dnd5e-2014",
                status="draft",
                created_at=now,
                updated_at=now,
            )
        )

    return ImportRepoFixture(
        engine=engine,
        repo=repo,
        db_path=db_path,
        room_a_id=room_a_id,
        room_b_id=room_b_id,
        adv_id=adv_id,
    )


def test_import_create_get_list_room_scoped(repo_fixture: ImportRepoFixture) -> None:
    repo = repo_fixture.repo
    now = datetime.now(timezone.utc)

    import_a1 = StoredAdventureImport(
        id=uuid4(),
        room_id=repo_fixture.room_a_id,
        name="Import A1",
        status="source",
        target_adventure_id=repo_fixture.adv_id,
        revision=0,
        created_at=now,
        updated_at=now,
    )
    import_a2 = StoredAdventureImport(
        id=uuid4(),
        room_id=repo_fixture.room_a_id,
        name="Import A2",
        status="source",
        target_adventure_id=None,
        revision=0,
        created_at=now,
        updated_at=now,
    )
    import_b1 = StoredAdventureImport(
        id=uuid4(),
        room_id=repo_fixture.room_b_id,
        name="Import B1",
        status="source",
        target_adventure_id=None,
        revision=0,
        created_at=now,
        updated_at=now,
    )

    repo.create_import(import_a1)
    repo.create_import(import_a2)
    repo.create_import(import_b1)

    fetched = repo.get_import(import_a1.id)
    assert fetched is not None
    assert fetched.id == import_a1.id
    assert fetched.name == "Import A1"
    assert fetched.target_adventure_id == repo_fixture.adv_id

    assert repo.get_import(uuid4()) is None

    list_a = repo.list_imports(repo_fixture.room_a_id)
    assert len(list_a) == 2
    assert {imp.id for imp in list_a} == {import_a1.id, import_a2.id}

    list_b = repo.list_imports(repo_fixture.room_b_id)
    assert len(list_b) == 1
    assert list_b[0].id == import_b1.id


def test_import_status_update_with_revision_guard(
    repo_fixture: ImportRepoFixture,
) -> None:
    repo = repo_fixture.repo
    now = datetime.now(timezone.utc)
    import_row = StoredAdventureImport(
        id=uuid4(),
        room_id=repo_fixture.room_a_id,
        name="Status Test",
        status="source",
        target_adventure_id=None,
        revision=0,
        created_at=now,
        updated_at=now,
    )
    repo.create_import(import_row)

    updated = repo.update_import_status(
        import_row.id,
        status="drafting",
        expected_revision=0,
    )
    assert updated.status == "drafting"
    assert updated.revision == 1

    with pytest.raises(AdventureImportRevisionConflictError) as exc_info:
        repo.update_import_status(
            import_row.id,
            status="review",
            expected_revision=0,
        )
    assert exc_info.value.expected_revision == 0
    assert exc_info.value.current_revision == 1

    current = repo.get_import(import_row.id)
    assert current is not None
    assert current.status == "drafting"
    assert current.revision == 1

    with pytest.raises(AdventureImportNotFoundError):
        repo.update_import_status(
            uuid4(),
            status="review",
            expected_revision=0,
        )


def test_source_add_find_and_uniqueness(repo_fixture: ImportRepoFixture) -> None:
    repo = repo_fixture.repo
    now = datetime.now(timezone.utc)
    import_id = uuid4()
    repo.create_import(
        StoredAdventureImport(
            id=import_id,
            room_id=repo_fixture.room_a_id,
            name="Source Test",
            status="source",
            target_adventure_id=None,
            revision=0,
            created_at=now,
            updated_at=now,
        )
    )

    sha = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    source = StoredAdventureImportSource(
        id=uuid4(),
        import_id=import_id,
        asset_id=None,
        source_kind="paste",
        source_url=None,
        metadata_json={"title": "Notes"},
        sha256=sha,
        created_at=now,
        normalized_text="Hello world adventure notes",
        text_length=len("Hello world adventure notes"),
    )
    repo.add_source(source)

    found = repo.find_source_by_sha256(import_id, sha)
    assert found is not None
    assert found.id == source.id
    assert found.normalized_text == "Hello world adventure notes"

    assert repo.find_source_by_sha256(import_id, "0" * 64) is None

    duplicate_source = StoredAdventureImportSource(
        id=uuid4(),
        import_id=import_id,
        asset_id=None,
        source_kind="txt",
        source_url=None,
        metadata_json={"title": "Notes duplicate"},
        sha256=sha,
        created_at=now,
        normalized_text="Different text same sha",
        text_length=len("Different text same sha"),
    )
    with pytest.raises(IntegrityError):
        repo.add_source(duplicate_source)


def test_list_sources_omits_normalized_text(repo_fixture: ImportRepoFixture) -> None:
    repo = repo_fixture.repo
    now = datetime.now(timezone.utc)
    import_id = uuid4()
    repo.create_import(
        StoredAdventureImport(
            id=import_id,
            room_id=repo_fixture.room_a_id,
            name="List Source Test",
            status="source",
            target_adventure_id=None,
            revision=0,
            created_at=now,
            updated_at=now,
        )
    )

    t1 = "First source text content"
    t2 = "Second source text content which is longer"
    s1 = StoredAdventureImportSource(
        id=uuid4(),
        import_id=import_id,
        asset_id=None,
        source_kind="paste",
        source_url=None,
        metadata_json={},
        sha256="1" * 64,
        created_at=now,
        normalized_text=t1,
        text_length=len(t1),
    )
    s2 = StoredAdventureImportSource(
        id=uuid4(),
        import_id=import_id,
        asset_id=None,
        source_kind="markdown",
        source_url=None,
        metadata_json={},
        sha256="2" * 64,
        created_at=now,
        normalized_text=t2,
        text_length=len(t2),
    )
    repo.add_source(s1)
    repo.add_source(s2)

    get1 = repo.get_source(s1.id)
    assert get1 is not None
    assert get1.normalized_text == t1
    assert get1.text_length == len(t1)

    listed = repo.list_sources(import_id)
    assert len(listed) == 2
    for s in listed:
        assert s.normalized_text is None
        expected_len = len(t1) if s.id == s1.id else len(t2)
        assert s.text_length == expected_len


def test_upsert_draft_lifecycle_and_restart_stability(
    repo_fixture: ImportRepoFixture,
) -> None:
    repo = repo_fixture.repo
    now = datetime.now(timezone.utc)
    import_id = uuid4()
    repo.create_import(
        StoredAdventureImport(
            id=import_id,
            room_id=repo_fixture.room_a_id,
            name="Draft Test",
            status="source",
            target_adventure_id=None,
            revision=0,
            created_at=now,
            updated_at=now,
        )
    )

    assert repo.get_draft(import_id) is None

    draft_v1 = {
        "schema_version": 1,
        "entries": [
            {
                "entry_id": "ent-1",
                "entry_kind": "scene",
                "payload": {"kind": "scene", "read_aloud": "Welcome to the tavern."},
                "parent_entry_id": None,
                "provenance": "source_document",
                "source_ref": None,
                "note": None,
            }
        ],
        "questions": [
            {
                "question_id": "q-1",
                "message": "Who is the innkeeper?",
                "entry_id": "ent-1",
                "answer": None,
            }
        ],
    }
    warnings_v1 = [
        {
            "warning_id": "w-1",
            "level": "info",
            "code": "MISSING_DC",
            "message": "Suggested check has no DC",
            "entry_id": "ent-1",
            "source_id": None,
        }
    ]

    stored_draft = repo.upsert_draft(
        import_id,
        draft_json=draft_v1,
        warnings_json=warnings_v1,
        expected_revision=0,
    )
    assert stored_draft.revision == 1
    assert stored_draft.draft_json == draft_v1

    for stale_rev in (0, 99):
        with pytest.raises(AdventureImportRevisionConflictError) as exc_info:
            repo.upsert_draft(
                import_id,
                draft_json={"schema_version": 1, "entries": [], "questions": []},
                warnings_json=[],
                expected_revision=stale_rev,
            )
        assert exc_info.value.expected_revision == stale_rev
        assert exc_info.value.current_revision == 1

    current = repo.get_draft(import_id)
    assert current is not None
    assert current.revision == 1
    assert current.draft_json == draft_v1
    assert current.warnings_json == warnings_v1

    draft_v2 = dict(draft_v1)
    draft_v2["entries"] = [
        *draft_v1["entries"],
        {
            "entry_id": "ent-2",
            "entry_kind": "npc",
            "payload": {"kind": "npc", "role": "Innkeeper"},
            "parent_entry_id": "ent-1",
            "provenance": "user_explicit",
            "source_ref": None,
            "note": None,
        },
    ]
    updated_draft = repo.upsert_draft(
        import_id,
        draft_json=draft_v2,
        warnings_json=warnings_v1,
        expected_revision=1,
    )
    assert updated_draft.revision == 2

    # E.4 restart stability: dispose engine and reopen
    repo_fixture.engine.dispose()
    reopened_engine = _create_sqlite_engine(repo_fixture.db_path)
    try:
        fresh_repo = AdventureImportRepository(reopened_engine)
        reopened_draft = fresh_repo.get_draft(import_id)
        assert reopened_draft is not None
        assert reopened_draft.revision == 2
        entries = reopened_draft.draft_json["entries"]
        assert [e["entry_id"] for e in entries] == ["ent-1", "ent-2"]
        assert [q["question_id"] for q in reopened_draft.draft_json["questions"]] == ["q-1"]
        assert [w["warning_id"] for w in reopened_draft.warnings_json] == ["w-1"]
    finally:
        reopened_engine.dispose()


def test_cascade_delete_import(repo_fixture: ImportRepoFixture) -> None:
    repo = repo_fixture.repo
    now = datetime.now(timezone.utc)
    import_id = uuid4()
    repo.create_import(
        StoredAdventureImport(
            id=import_id,
            room_id=repo_fixture.room_a_id,
            name="Cascade Test",
            status="source",
            target_adventure_id=None,
            revision=0,
            created_at=now,
            updated_at=now,
        )
    )

    source = StoredAdventureImportSource(
        id=uuid4(),
        import_id=import_id,
        asset_id=None,
        source_kind="paste",
        source_url=None,
        metadata_json={},
        sha256="3" * 64,
        created_at=now,
        normalized_text="Some text",
        text_length=len("Some text"),
    )
    repo.add_source(source)
    repo.upsert_draft(
        import_id,
        draft_json={"schema_version": 1, "entries": [], "questions": []},
        warnings_json=[],
        expected_revision=0,
    )

    with repo_fixture.engine.begin() as conn:
        conn.execute(
            delete(adventure_imports).where(adventure_imports.c.id == import_id)
        )

    assert repo.get_import(import_id) is None
    assert repo.get_source(source.id) is None
    assert repo.get_draft(import_id) is None
