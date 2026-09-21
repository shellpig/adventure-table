from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, delete, event, insert, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

from app.db import metadata
from app.persistence.adventures.tables import (
    adventure_definitions,
    adventure_entries,
)
from app.persistence.campaign_runtime.repository import (
    CampaignRuntimeRepository,
    RuntimeWorldEntryArchivedError,
    RuntimeWorldEntryConflictError,
    RuntimeWorldEntryNotFoundError,
    StoredRuntimeWorldEntry,
    StoredRuntimeWorldEntryAggregate,
    StoredRuntimeWorldEntryUpdate,
)
from app.persistence.campaign_runtime.tables import (
    campaign_world_entries,
    campaign_world_entry_characters,
)
from app.persistence.characters import characters, character_states, character_versions
from app.persistence.rooms.tables import campaigns, rooms


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
class RuntimeRepoFixture:
    engine: Engine
    repo: CampaignRuntimeRepository
    room_a_id: UUID
    campaign_a_id: UUID
    campaign_b_id: UUID
    char_1_id: UUID
    char_2_id: UUID
    char_3_id: UUID
    adv_entry_id: UUID


@pytest.fixture
def repo_fixture() -> Sequence[RuntimeRepoFixture]:
    engine = _engine()
    repo = CampaignRuntimeRepository(engine)

    room_a_id = uuid4()
    campaign_a_id = uuid4()
    campaign_b_id = uuid4()
    c_ids = sorted([uuid4(), uuid4(), uuid4()])
    char_1_id, char_2_id, char_3_id = c_ids[0], c_ids[1], c_ids[2]
    adv_id = uuid4()
    adv_entry_id = uuid4()
    now = datetime.now(timezone.utc)

    with engine.begin() as conn:
        conn.execute(
            insert(rooms).values(
                id=room_a_id,
                code="ROOM-A",
                name="Room A",
                password_salt=b"salt",
                password_hash=b"pw",
                owner_key_hash=b"owner",
                dm_key_hash=b"dm",
                created_at=now,
                updated_at=now,
            )
        )
        conn.execute(
            insert(campaigns).values(
                [
                    {
                        "id": campaign_a_id,
                        "room_id": room_a_id,
                        "name": "Campaign A",
                        "ruleset": "dnd-5e-2014",
                        "status": "draft",
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": campaign_b_id,
                        "room_id": room_a_id,
                        "name": "Campaign B",
                        "ruleset": "dnd-5e-2014",
                        "status": "draft",
                        "created_at": now,
                        "updated_at": now,
                    },
                ]
            )
        )
        for cid, cname in [
            (char_1_id, "Character 1"),
            (char_2_id, "Character 2"),
            (char_3_id, "Character 3"),
        ]:
            vid = uuid4()
            conn.execute(
                insert(characters).values(
                    id=cid,
                    name=cname,
                    ruleset="dnd-5e-2014",
                    current_version_id=vid,
                    created_at=now,
                    updated_at=now,
                )
            )
            conn.execute(
                insert(character_versions).values(
                    id=vid,
                    character_id=cid,
                    version_no=1,
                    build_payload={"name": cname},
                    created_at=now,
                )
            )
            conn.execute(
                insert(character_states).values(
                    character_id=cid,
                    state_revision=1,
                    state_payload={"hp": 10},
                    updated_at=now,
                )
            )
        conn.execute(
            insert(adventure_definitions).values(
                id=adv_id,
                room_id=room_a_id,
                name="Adv 1",
                ruleset="dnd-5e-2014",
                status="draft",
                created_at=now,
                updated_at=now,
            )
        )
        conn.execute(
            insert(adventure_entries).values(
                id=adv_entry_id,
                adventure_id=adv_id,
                kind="scene",
                title="Tavern",
                data_json={},
                visibility="dm_only",
                sort_order=0,
                created_at=now,
                updated_at=now,
            )
        )

    try:
        yield RuntimeRepoFixture(
            engine=engine,
            repo=repo,
            room_a_id=room_a_id,
            campaign_a_id=campaign_a_id,
            campaign_b_id=campaign_b_id,
            char_1_id=char_1_id,
            char_2_id=char_2_id,
            char_3_id=char_3_id,
            adv_entry_id=adv_entry_id,
        )
    finally:
        engine.dispose()


def _make_stored_entry(
    campaign_id: UUID,
    *,
    entry_id: UUID | None = None,
    kind: str = "npc",
    title: str | None = "Gundren",
    body: str | None = "A dwarf patron",
    state_json: dict[str, object] | None = None,
    dm_notes: str | None = None,
    visibility: str = "public",
    needs_review: bool = False,
    source_adventure_entry_id: UUID | None = None,
    provenance_json: dict[str, object] | None = None,
    revision: int = 1,
    created_by_actor_kind: str = "human",
    created_by_actor_id: UUID | None = None,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
    archived_at: datetime | None = None,
) -> StoredRuntimeWorldEntry:
    now = datetime.now(timezone.utc)
    return StoredRuntimeWorldEntry(
        id=entry_id or uuid4(),
        campaign_id=campaign_id,
        kind=kind,
        title=title,
        body=body,
        state_json=state_json if state_json is not None else {"kind": kind},
        dm_notes=dm_notes,
        visibility=visibility,
        needs_review=needs_review,
        source_adventure_entry_id=source_adventure_entry_id,
        provenance_json=provenance_json,
        revision=revision,
        created_by_actor_kind=created_by_actor_kind,
        created_by_actor_id=created_by_actor_id,
        created_at=created_at or now,
        updated_at=updated_at or now,
        archived_at=archived_at,
    )


def test_empty_campaign_create_get_list(repo_fixture: RuntimeRepoFixture) -> None:
    repo = repo_fixture.repo
    campaign_id = repo_fixture.campaign_a_id

    # 1. Empty campaign initially
    assert repo.list_entries(campaign_id) == ()
    assert repo.get_entry(campaign_id, uuid4()) is None

    # 2. Create entry without recipients
    entry = _make_stored_entry(campaign_id, kind="scene", title="Green Dragon Inn")
    created = repo.create_entry(entry)

    assert isinstance(created, StoredRuntimeWorldEntryAggregate)
    assert created.entry.id == entry.id
    assert created.entry.campaign_id == campaign_id
    assert created.entry.kind == "scene"
    assert created.entry.title == "Green Dragon Inn"
    assert created.entry.revision == 1
    assert created.entry.archived_at is None
    assert created.character_recipient_ids == ()

    # 3. Get entry
    fetched = repo.get_entry(campaign_id, entry.id)
    assert fetched == created

    # 4. List entries
    entries = repo.list_entries(campaign_id)
    assert len(entries) == 1
    assert entries[0] == created


def test_deterministic_list_ordering(repo_fixture: RuntimeRepoFixture) -> None:
    repo = repo_fixture.repo
    campaign_id = repo_fixture.campaign_a_id

    t1 = datetime(2026, 9, 20, 10, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 20, 10, 5, 0, tzinfo=timezone.utc)
    t3 = datetime(2026, 9, 20, 10, 10, 0, tzinfo=timezone.utc)

    # Deterministic IDs for same timestamp
    id_low = UUID("00000000-0000-0000-0000-000000000001")
    id_high = UUID("00000000-0000-0000-0000-000000000002")

    e_t3 = _make_stored_entry(campaign_id, title="Late", created_at=t3)
    e_t2_high = _make_stored_entry(campaign_id, entry_id=id_high, title="Mid 2", created_at=t2)
    e_t2_low = _make_stored_entry(campaign_id, entry_id=id_low, title="Mid 1", created_at=t2)
    e_t1 = _make_stored_entry(campaign_id, title="Early", created_at=t1)

    # Insert in scrambled order
    repo.create_entry(e_t3)
    repo.create_entry(e_t2_high)
    repo.create_entry(e_t1)
    repo.create_entry(e_t2_low)

    listed = repo.list_entries(campaign_id)
    assert [x.entry.title for x in listed] == ["Early", "Mid 1", "Mid 2", "Late"]
    assert [x.entry.id for x in listed] == [e_t1.id, id_low, id_high, e_t3.id]


def test_recipient_round_trip_and_batched_query(repo_fixture: RuntimeRepoFixture) -> None:
    repo = repo_fixture.repo
    campaign_id = repo_fixture.campaign_a_id
    c1, c2, c3 = repo_fixture.char_1_id, repo_fixture.char_2_id, repo_fixture.char_3_id

    # Create 5 entries with different recipient configurations
    e1 = _make_stored_entry(campaign_id, visibility="character", title="Secret 1")
    e2 = _make_stored_entry(campaign_id, visibility="public", title="Public 2")
    e3 = _make_stored_entry(campaign_id, visibility="character", title="Secret 3")
    e4 = _make_stored_entry(campaign_id, visibility="character", title="Secret 4")
    e5 = _make_stored_entry(campaign_id, visibility="dm_only", title="DM 5")

    repo.create_entry(e1, character_recipient_ids=[c1, c2])
    repo.create_entry(e2, character_recipient_ids=[])
    repo.create_entry(e3, character_recipient_ids=[c2, c3])
    repo.create_entry(e4, character_recipient_ids=[c1])
    repo.create_entry(e5, character_recipient_ids=[])

    # Direct check: get_entry round-trip
    g1 = repo.get_entry(campaign_id, e1.id)
    assert g1 is not None
    assert g1.character_recipient_ids == (c1, c2)

    g2 = repo.get_entry(campaign_id, e2.id)
    assert g2 is not None
    assert g2.character_recipient_ids == ()

    # Instrument statement count on list_entries: exactly 2 queries regardless of entry count
    executed_statements: list[str] = []

    def _statement_listener(_conn, _cursor, statement, _parameters, _context, _executemany):
        executed_statements.append(statement)

    event.listen(repo_fixture.engine, "before_cursor_execute", _statement_listener)
    try:
        results = repo.list_entries(campaign_id)
        assert len(results) == 5
        # Verify statement count is exactly 2: 1 for campaign_world_entries, 1 for campaign_world_entry_characters
        assert len(executed_statements) == 2
        assert "campaign_world_entries" in executed_statements[0]
        assert "campaign_world_entry_characters" in executed_statements[1]

        # Verify all recipients match
        by_id = {r.entry.id: r.character_recipient_ids for r in results}
        assert by_id[e1.id] == (c1, c2)
        assert by_id[e2.id] == ()
        assert by_id[e3.id] == (c2, c3)
        assert by_id[e4.id] == (c1,)
        assert by_id[e5.id] == ()
    finally:
        event.remove(repo_fixture.engine, "before_cursor_execute", _statement_listener)

    # Empty campaign: exactly 1 statement (no recipient query)
    executed_statements.clear()
    event.listen(repo_fixture.engine, "before_cursor_execute", _statement_listener)
    try:
        empty_results = repo.list_entries(repo_fixture.campaign_b_id)
        assert empty_results == ()
        assert len(executed_statements) == 1
        assert "campaign_world_entries" in executed_statements[0]
    finally:
        event.remove(repo_fixture.engine, "before_cursor_execute", _statement_listener)


def test_update_with_expected_revision(repo_fixture: RuntimeRepoFixture) -> None:
    repo = repo_fixture.repo
    campaign_id = repo_fixture.campaign_a_id
    c1, c2 = repo_fixture.char_1_id, repo_fixture.char_2_id

    entry = _make_stored_entry(campaign_id, title="Original Title", visibility="public")
    repo.create_entry(entry)

    now2 = datetime.now(timezone.utc)
    update_cand = StoredRuntimeWorldEntryUpdate(
        expected_revision=1,
        title="Updated Title",
        body="Updated Body",
        state_json={"kind": "npc", "hp": 25},
        dm_notes="Secret DM info",
        visibility="character",
        needs_review=True,
        source_adventure_entry_id=repo_fixture.adv_entry_id,
        provenance_json={"origin": "manual"},
        updated_at=now2,
        character_recipient_ids=(c1, c2),
    )

    updated = repo.update_entry(campaign_id, entry.id, update_cand)

    assert updated.entry.revision == 2
    assert updated.entry.title == "Updated Title"
    assert updated.entry.body == "Updated Body"
    assert updated.entry.state_json == {"kind": "npc", "hp": 25}
    assert updated.entry.dm_notes == "Secret DM info"
    assert updated.entry.visibility == "character"
    assert updated.entry.needs_review is True
    assert updated.entry.source_adventure_entry_id == repo_fixture.adv_entry_id
    assert updated.entry.provenance_json == {"origin": "manual"}
    assert updated.entry.updated_at == now2
    assert updated.character_recipient_ids == (c1, c2)

    # Check fetched matches
    fetched = repo.get_entry(campaign_id, entry.id)
    assert fetched == updated


def test_recipient_replacement_atomicity(repo_fixture: RuntimeRepoFixture) -> None:
    repo = repo_fixture.repo
    campaign_id = repo_fixture.campaign_a_id
    c1, c2, c3 = repo_fixture.char_1_id, repo_fixture.char_2_id, repo_fixture.char_3_id

    duplicate_entry = _make_stored_entry(campaign_id, visibility="character")
    with pytest.raises(IntegrityError):
        repo.create_entry(duplicate_entry, character_recipient_ids=(c1, c1))
    assert repo.get_entry(campaign_id, duplicate_entry.id) is None

    entry = _make_stored_entry(campaign_id, visibility="character")
    repo.create_entry(entry, character_recipient_ids=[c1, c2])

    now = datetime.now(timezone.utc)

    # 1. Replace with c2, c3
    u1 = StoredRuntimeWorldEntryUpdate(
        expected_revision=1,
        title="Rev 2",
        body=None,
        state_json={"kind": "npc"},
        dm_notes=None,
        visibility="character",
        needs_review=False,
        source_adventure_entry_id=None,
        provenance_json=None,
        updated_at=now,
        character_recipient_ids=(c2, c3),
    )
    res1 = repo.update_entry(campaign_id, entry.id, u1)
    assert res1.entry.revision == 2
    assert res1.character_recipient_ids == (c2, c3)

    # 2. Replace with empty
    u2 = StoredRuntimeWorldEntryUpdate(
        expected_revision=2,
        title="Rev 3",
        body=None,
        state_json={"kind": "npc"},
        dm_notes=None,
        visibility="public",
        needs_review=False,
        source_adventure_entry_id=None,
        provenance_json=None,
        updated_at=now,
        character_recipient_ids=(),
    )
    res2 = repo.update_entry(campaign_id, entry.id, u2)
    assert res2.entry.revision == 3
    assert res2.character_recipient_ids == ()

    # 3. Atomicity on failure: invalid character ID violates FK in same transaction
    invalid_char_id = uuid4()
    u3 = StoredRuntimeWorldEntryUpdate(
        expected_revision=3,
        title="Rev 4 - Should Fail",
        body=None,
        state_json={"kind": "npc"},
        dm_notes=None,
        visibility="character",
        needs_review=False,
        source_adventure_entry_id=None,
        provenance_json=None,
        updated_at=now,
        character_recipient_ids=(invalid_char_id,),
    )

    with pytest.raises(IntegrityError):
        repo.update_entry(campaign_id, entry.id, u3)

    # Verify rollback: revision is still 3, title is still "Rev 3", recipients are still ()
    current = repo.get_entry(campaign_id, entry.id)
    assert current is not None
    assert current.entry.revision == 3
    assert current.entry.title == "Rev 3"
    assert current.character_recipient_ids == ()


def test_stale_revision_conflict_and_unchanged_data(repo_fixture: RuntimeRepoFixture) -> None:
    repo = repo_fixture.repo
    campaign_id = repo_fixture.campaign_a_id
    c1 = repo_fixture.char_1_id

    entry = _make_stored_entry(campaign_id, title="Version 1")
    repo.create_entry(entry, character_recipient_ids=[c1])

    # Advance to revision 2
    now = datetime.now(timezone.utc)
    u1 = StoredRuntimeWorldEntryUpdate(
        expected_revision=1,
        title="Version 2",
        body=None,
        state_json={"kind": "npc"},
        dm_notes=None,
        visibility="public",
        needs_review=False,
        source_adventure_entry_id=None,
        provenance_json=None,
        updated_at=now,
        character_recipient_ids=(c1,),
    )
    repo.update_entry(campaign_id, entry.id, u1)

    # Stale update attempting expected_revision=1 when revision is now 2
    stale_update = StoredRuntimeWorldEntryUpdate(
        expected_revision=1,
        title="Stale Overwrite",
        body=None,
        state_json={"kind": "npc"},
        dm_notes=None,
        visibility="public",
        needs_review=False,
        source_adventure_entry_id=None,
        provenance_json=None,
        updated_at=now,
        character_recipient_ids=(),
    )

    with pytest.raises(RuntimeWorldEntryConflictError) as exc_info:
        repo.update_entry(campaign_id, entry.id, stale_update)

    err = exc_info.value
    assert err.campaign_id == campaign_id
    assert err.entry_id == entry.id
    assert err.expected_revision == 1
    assert err.current_revision == 2

    # Verify DB row and recipients are completely unchanged
    current = repo.get_entry(campaign_id, entry.id)
    assert current is not None
    assert current.entry.revision == 2
    assert current.entry.title == "Version 2"
    assert current.character_recipient_ids == (c1,)


def test_wrong_campaign_not_found(repo_fixture: RuntimeRepoFixture) -> None:
    repo = repo_fixture.repo
    camp_a = repo_fixture.campaign_a_id
    camp_b = repo_fixture.campaign_b_id

    entry = _make_stored_entry(camp_a, title="Camp A Entry")
    repo.create_entry(entry)

    # 1. get_entry with wrong campaign returns None
    assert repo.get_entry(camp_b, entry.id) is None

    # 2. update_entry with wrong campaign raises RuntimeWorldEntryNotFoundError
    now = datetime.now(timezone.utc)
    update_cand = StoredRuntimeWorldEntryUpdate(
        expected_revision=1,
        title="Wrong Camp Update",
        body=None,
        state_json={"kind": "npc"},
        dm_notes=None,
        visibility="public",
        needs_review=False,
        source_adventure_entry_id=None,
        provenance_json=None,
        updated_at=now,
        character_recipient_ids=(),
    )
    with pytest.raises(RuntimeWorldEntryNotFoundError) as exc_info:
        repo.update_entry(camp_b, entry.id, update_cand)
    assert exc_info.value.campaign_id == camp_b
    assert exc_info.value.entry_id == entry.id

    # 3. archive_entry with wrong campaign raises RuntimeWorldEntryNotFoundError
    with pytest.raises(RuntimeWorldEntryNotFoundError) as exc_info:
        repo.archive_entry(camp_b, entry.id, expected_revision=1, archived_at=now)
    assert exc_info.value.campaign_id == camp_b
    assert exc_info.value.entry_id == entry.id

    # 4. Non-existent entry ID in camp_a also raises RuntimeWorldEntryNotFoundError
    missing_id = uuid4()
    assert repo.get_entry(camp_a, missing_id) is None
    with pytest.raises(RuntimeWorldEntryNotFoundError):
        repo.update_entry(camp_a, missing_id, update_cand)
    with pytest.raises(RuntimeWorldEntryNotFoundError):
        repo.archive_entry(camp_a, missing_id, expected_revision=1, archived_at=now)


def test_archive_excluded_by_default_and_include_archived(
    repo_fixture: RuntimeRepoFixture,
) -> None:
    repo = repo_fixture.repo
    campaign_id = repo_fixture.campaign_a_id
    c1 = repo_fixture.char_1_id

    entry = _make_stored_entry(campaign_id, title="To Archive")
    repo.create_entry(entry, character_recipient_ids=[c1])

    archive_time = datetime(2026, 9, 20, 11, 0, 0, tzinfo=timezone.utc)
    archived = repo.archive_entry(
        campaign_id,
        entry.id,
        expected_revision=1,
        archived_at=archive_time,
    )

    # Check returned aggregate
    assert archived.entry.revision == 2
    assert archived.entry.archived_at == archive_time
    assert archived.character_recipient_ids == (c1,)

    # 1. get_entry defaults to excluding archived
    assert repo.get_entry(campaign_id, entry.id) is None
    # 2. get_entry with include_archived=True returns it
    fetched = repo.get_entry(campaign_id, entry.id, include_archived=True)
    assert fetched == archived

    # 3. list_entries defaults to excluding archived
    assert repo.list_entries(campaign_id) == ()
    # 4. list_entries with include_archived=True includes it
    listed = repo.list_entries(campaign_id, include_archived=True)
    assert len(listed) == 1
    assert listed[0] == archived

    # 5. Durable row and recipients in database are preserved
    with repo_fixture.engine.connect() as conn:
        row = conn.execute(
            select(campaign_world_entries).where(campaign_world_entries.c.id == entry.id)
        ).mappings().one()
        assert row["archived_at"] is not None
        assert row["revision"] == 2

        recip_rows = conn.execute(
            select(campaign_world_entry_characters).where(
                campaign_world_entry_characters.c.world_entry_id == entry.id
            )
        ).all()
        assert len(recip_rows) == 1
        assert recip_rows[0][1] == c1


def test_re_archive_conflict_and_not_found_contract(
    repo_fixture: RuntimeRepoFixture,
) -> None:
    repo = repo_fixture.repo
    campaign_id = repo_fixture.campaign_a_id

    entry = _make_stored_entry(campaign_id, title="Archive Twice")
    repo.create_entry(entry)

    t1 = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)
    repo.archive_entry(campaign_id, entry.id, expected_revision=1, archived_at=t1)

    t2 = datetime(2026, 9, 20, 12, 5, 0, tzinfo=timezone.utc)

    # 1. Re-archive with old revision 1 -> conflict
    with pytest.raises(RuntimeWorldEntryConflictError) as exc_info:
        repo.archive_entry(campaign_id, entry.id, expected_revision=1, archived_at=t2)
    assert exc_info.value.expected_revision == 1
    assert exc_info.value.current_revision == 2

    # 2. Re-archive with new revision 2 -> RuntimeWorldEntryArchivedError (subclass of ConflictError)
    with pytest.raises(RuntimeWorldEntryArchivedError) as exc_info:
        repo.archive_entry(campaign_id, entry.id, expected_revision=2, archived_at=t2)
    assert exc_info.value.expected_revision == 2
    assert exc_info.value.current_revision == 2
    assert "already archived" in str(exc_info.value)

    # 3. Update an archived entry -> RuntimeWorldEntryArchivedError
    u = StoredRuntimeWorldEntryUpdate(
        expected_revision=2,
        title="Cannot Update Archived",
        body=None,
        state_json={"kind": "npc"},
        dm_notes=None,
        visibility="public",
        needs_review=False,
        source_adventure_entry_id=None,
        provenance_json=None,
        updated_at=t2,
        character_recipient_ids=(),
    )
    with pytest.raises(RuntimeWorldEntryArchivedError):
        repo.update_entry(campaign_id, entry.id, u)


def test_fk_cascade_behavior(repo_fixture: RuntimeRepoFixture) -> None:
    repo = repo_fixture.repo
    campaign_id = repo_fixture.campaign_a_id
    c1 = repo_fixture.char_1_id
    adv_entry_id = repo_fixture.adv_entry_id

    entry = _make_stored_entry(
        campaign_id,
        source_adventure_entry_id=adv_entry_id,
        visibility="character",
    )
    repo.create_entry(entry, character_recipient_ids=[c1])

    # 1. Deleting adventure entry sets source_adventure_entry_id to NULL
    with repo_fixture.engine.begin() as conn:
        conn.execute(
            delete(adventure_entries).where(adventure_entries.c.id == adv_entry_id)
        )

    fetched = repo.get_entry(campaign_id, entry.id)
    assert fetched is not None
    assert fetched.entry.source_adventure_entry_id is None

    # 2. Deleting character cascades to campaign_world_entry_characters
    with repo_fixture.engine.begin() as conn:
        conn.execute(delete(characters).where(characters.c.id == c1))

    fetched_after_char_del = repo.get_entry(campaign_id, entry.id)
    assert fetched_after_char_del is not None
    assert fetched_after_char_del.character_recipient_ids == ()

    # 3. Deleting campaign cascades to campaign_world_entries
    with repo_fixture.engine.begin() as conn:
        conn.execute(delete(campaigns).where(campaigns.c.id == campaign_id))

    with repo_fixture.engine.connect() as conn:
        rows = conn.execute(
            select(campaign_world_entries).where(campaign_world_entries.c.id == entry.id)
        ).all()
        assert len(rows) == 0


def test_sql_where_predicates_and_concurrency(repo_fixture: RuntimeRepoFixture) -> None:
    repo = repo_fixture.repo
    campaign_id = repo_fixture.campaign_a_id

    entry = _make_stored_entry(campaign_id, title="Concurrent Target")
    repo.create_entry(entry)

    # Directly verify the SQL WHERE predicates executed by update_entry
    executed_updates: list[str] = []

    def _update_listener(_conn, _cursor, statement, _parameters, _context, _executemany):
        if "UPDATE campaign_world_entries" in statement:
            executed_updates.append(statement)

    event.listen(repo_fixture.engine, "before_cursor_execute", _update_listener)
    try:
        now = datetime.now(timezone.utc)
        u1 = StoredRuntimeWorldEntryUpdate(
            expected_revision=1,
            title="Winner",
            body=None,
            state_json={"kind": "npc"},
            dm_notes=None,
            visibility="public",
            needs_review=False,
            source_adventure_entry_id=None,
            provenance_json=None,
            updated_at=now,
            character_recipient_ids=(),
        )
        repo.update_entry(campaign_id, entry.id, u1)

        # Assert WHERE clause contains id, campaign_id, revision, and archived_at IS NULL
        assert len(executed_updates) == 1
        stmt = executed_updates[0]
        assert "campaign_world_entries.id ==" in stmt or "campaign_world_entries.id =" in stmt
        assert "campaign_world_entries.campaign_id ==" in stmt or "campaign_world_entries.campaign_id =" in stmt
        assert "campaign_world_entries.revision ==" in stmt or "campaign_world_entries.revision =" in stmt
        assert "campaign_world_entries.archived_at IS NULL" in stmt

        # Simultaneous same-revision second update: must fail with conflict
        u2 = StoredRuntimeWorldEntryUpdate(
            expected_revision=1,
            title="Loser",
            body=None,
            state_json={"kind": "npc"},
            dm_notes=None,
            visibility="public",
            needs_review=False,
            source_adventure_entry_id=None,
            provenance_json=None,
            updated_at=now,
            character_recipient_ids=(),
        )
        with pytest.raises(RuntimeWorldEntryConflictError) as exc_info:
            repo.update_entry(campaign_id, entry.id, u2)

        assert exc_info.value.expected_revision == 1
        assert exc_info.value.current_revision == 2

        # Winner's data remained in place
        current = repo.get_entry(campaign_id, entry.id)
        assert current is not None
        assert current.entry.title == "Winner"
        assert current.entry.revision == 2
    finally:
        event.remove(repo_fixture.engine, "before_cursor_execute", _update_listener)
