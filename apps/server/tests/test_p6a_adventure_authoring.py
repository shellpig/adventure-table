from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import time
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError
import pytest
from sqlalchemy import create_engine, event, insert
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from app.db import metadata
from app.domain.adventures.payloads import (
    AdventureEntryPayloadError,
)
from app.domain.adventures.schemas import (
    AdventureArchivedError,
    AdventureDefinitionCreate,
    AdventureDefinitionPatch,
    AdventureEntryCreate,
    AdventureEntryNotFoundError,
    AdventureEntryParentError,
    AdventureEntryPatch,
    AdventureEntryReorder,
    AdventureForbiddenError,
    AdventureNotFoundError,
)
from app.domain.adventures.service import AdventureService
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.persistence.adventures.repository import AdventureRepository
from app.persistence.room_assets.repository import RoomAssetRepository
from app.persistence.rooms.tables import rooms


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
class AdventureFixture:
    engine: Engine
    repository: AdventureRepository
    service: AdventureService
    room_a_id: UUID
    room_b_id: UUID
    owner_a: RoomAccessContext
    dm_a: RoomAccessContext
    member_a: RoomAccessContext
    owner_b: RoomAccessContext


@pytest.fixture
def fixture() -> AdventureFixture:
    engine = _engine()
    room_a_id = uuid4()
    room_b_id = uuid4()
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

    repository = AdventureRepository(engine)
    service = AdventureService(repository, RoomAssetRepository(engine))

    return AdventureFixture(
        engine=engine,
        repository=repository,
        service=service,
        room_a_id=room_a_id,
        room_b_id=room_b_id,
        owner_a=owner_a,
        dm_a=dm_a,
        member_a=member_a,
        owner_b=owner_b,
    )


# 1. test_owner_creates_adventure_with_only_a_name
def test_owner_creates_adventure_with_only_a_name(fixture: AdventureFixture) -> None:
    created = fixture.service.create_definition(
        fixture.owner_a,
        fixture.room_a_id,
        AdventureDefinitionCreate(name="Lost Mine"),
    )
    assert created.name == "Lost Mine"
    assert created.status == "draft"
    assert created.ruleset == "dnd5e-2014"
    assert created.summary is None
    assert created.room_id == fixture.room_a_id

    defs = fixture.service.list_definitions(fixture.owner_a, fixture.room_a_id)
    assert len(defs) == 1
    assert defs[0].id == created.id


# 2. test_dm_can_author_member_cannot_read_or_write
def test_dm_can_author_member_cannot_read_or_write(fixture: AdventureFixture) -> None:
    adv = fixture.service.create_definition(
        fixture.dm_a,
        fixture.room_a_id,
        AdventureDefinitionCreate(name="DM Adventure"),
    )
    entry = fixture.service.create_entry(
        fixture.dm_a,
        fixture.room_a_id,
        adv.id,
        AdventureEntryCreate(
            kind="scene",
            title="Public Scene",
            visibility="public",
            data={"read_aloud": "Welcome to the adventure!"},
        ),
    )
    assert entry.visibility == "public"

    # member_a write operations must fail with AdventureForbiddenError
    with pytest.raises(AdventureForbiddenError):
        fixture.service.create_definition(
            fixture.member_a,
            fixture.room_a_id,
            AdventureDefinitionCreate(name="Member Adventure"),
        )

    with pytest.raises(AdventureForbiddenError):
        fixture.service.create_entry(
            fixture.member_a,
            fixture.room_a_id,
            adv.id,
            AdventureEntryCreate(kind="dm_note", data={}),
        )

    with pytest.raises(AdventureForbiddenError):
        fixture.service.patch_definition(
            fixture.member_a,
            fixture.room_a_id,
            adv.id,
            AdventureDefinitionPatch(name="Hacked Name"),
        )

    with pytest.raises(AdventureForbiddenError):
        fixture.service.patch_entry(
            fixture.member_a,
            fixture.room_a_id,
            adv.id,
            entry.id,
            AdventureEntryPatch(body="Hacked Body"),
        )

    with pytest.raises(AdventureForbiddenError):
        fixture.service.delete_entry(
            fixture.member_a,
            fixture.room_a_id,
            adv.id,
            entry.id,
        )

    with pytest.raises(AdventureForbiddenError):
        fixture.service.reorder_entries(
            fixture.member_a,
            fixture.room_a_id,
            adv.id,
            AdventureEntryReorder(entry_ids=(entry.id,)),
        )

    # member_a read operations must fail with AdventureForbiddenError (NOT NotFound, NOT result)
    with pytest.raises(AdventureForbiddenError):
        fixture.service.get_definition(fixture.member_a, fixture.room_a_id, adv.id)

    with pytest.raises(AdventureForbiddenError):
        fixture.service.list_definitions(fixture.member_a, fixture.room_a_id)

    with pytest.raises(AdventureForbiddenError):
        fixture.service.list_entries(fixture.member_a, fixture.room_a_id, adv.id)

    with pytest.raises(AdventureForbiddenError):
        fixture.service.get_entry(fixture.member_a, fixture.room_a_id, adv.id, entry.id)


# 3. test_every_known_kind_accepts_a_valid_payload
@pytest.mark.parametrize(
    "kind,data",
    [
        ("section", {}),
        ("scene", {"read_aloud": "A cold wind blows through the tunnel."}),
        ("npc", {"disposition": "hostile"}),
        ("item", {"value_gp": 50}),
        ("monster_ref", {"monster_template_ref": "srd5.1:goblin", "count": 3}),
        ("quest", {"objective": "Find the lost talisman"}),
        ("secret", {"reveal_condition": "DC 14 Investigation"}),
        ("dm_note", {}),
        ("suggested_check", {"ability": "wis", "skill": "perception", "dc": 13}),
        ("map", {"caption": "Dungeon Level 1"}),
        ("lore", {"topic": "Founding of the town"}),
        ("other", {"data": {"weather": "rain", "day": 3, "night": True}}),
    ],
    ids=[
        "section",
        "scene",
        "npc",
        "item",
        "monster_ref",
        "quest",
        "secret",
        "dm_note",
        "suggested_check",
        "map",
        "lore",
        "other",
    ],
)
def test_every_known_kind_accepts_a_valid_payload(
    fixture: AdventureFixture,
    kind: str,
    data: dict[str, Any],
) -> None:
    adv = fixture.service.create_definition(
        fixture.owner_a,
        fixture.room_a_id,
        AdventureDefinitionCreate(name=f"Adv for {kind}"),
    )
    entry = fixture.service.create_entry(
        fixture.owner_a,
        fixture.room_a_id,
        adv.id,
        AdventureEntryCreate(kind=kind, data=data),  # type: ignore[arg-type]
    )
    assert entry.kind == kind
    assert entry.data.kind == kind


# 4. test_every_known_kind_rejects_an_invalid_payload
@pytest.mark.parametrize(
    "kind,invalid_data",
    [
        ("section", {"unexpected": 1}),
        ("scene", {"exits": "north"}),
        ("npc", {"disposition": "angry"}),
        ("item", {"value_gp": -5}),
        ("monster_ref", {}),
        ("quest", {}),
        ("secret", {"reveal_condition": 5}),
        ("dm_note", {"x": 1}),
        ("suggested_check", {"ability": "luck", "dc": 10}),
        ("map", {"grid": [[0, 1]]}),
        ("lore", {"topic": ["a"]}),
        ("other", {"data": {"nested": {"a": 1}}}),
    ],
    ids=[
        "section",
        "scene",
        "npc",
        "item",
        "monster_ref",
        "quest",
        "secret",
        "dm_note",
        "suggested_check",
        "map",
        "lore",
        "other",
    ],
)
def test_every_known_kind_rejects_an_invalid_payload(
    fixture: AdventureFixture,
    kind: str,
    invalid_data: dict[str, Any],
) -> None:
    adv = fixture.service.create_definition(
        fixture.owner_a,
        fixture.room_a_id,
        AdventureDefinitionCreate(name=f"Adv for invalid {kind}"),
    )
    with pytest.raises(AdventureEntryPayloadError):
        fixture.service.create_entry(
            fixture.owner_a,
            fixture.room_a_id,
            adv.id,
            AdventureEntryCreate(kind=kind, data=invalid_data),  # type: ignore[arg-type]
        )

    # Assert no adventure_entries row is written
    entries = fixture.service.list_entries(fixture.owner_a, fixture.room_a_id, adv.id)
    assert len(entries) == 0


# 5. test_unknown_kind_is_rejected
def test_unknown_kind_is_rejected(fixture: AdventureFixture) -> None:
    adv = fixture.service.create_definition(
        fixture.owner_a,
        fixture.room_a_id,
        AdventureDefinitionCreate(name="Adv unknown kind"),
    )
    with pytest.raises((AdventureEntryPayloadError, ValidationError)):
        fixture.service.create_entry(
            fixture.owner_a,
            fixture.room_a_id,
            adv.id,
            AdventureEntryCreate(kind="trap_grid", data={}),  # type: ignore[arg-type]
        )

    # Assert list_entries stays empty
    entries = fixture.service.list_entries(fixture.owner_a, fixture.room_a_id, adv.id)
    assert len(entries) == 0


# 6. test_parent_must_belong_to_same_adventure_and_not_cycle
def test_parent_must_belong_to_same_adventure_and_not_cycle(fixture: AdventureFixture) -> None:
    adv1 = fixture.service.create_definition(
        fixture.owner_a,
        fixture.room_a_id,
        AdventureDefinitionCreate(name="Adv 1"),
    )
    adv2 = fixture.service.create_definition(
        fixture.owner_a,
        fixture.room_a_id,
        AdventureDefinitionCreate(name="Adv 2"),
    )
    entry_foreign = fixture.service.create_entry(
        fixture.owner_a,
        fixture.room_a_id,
        adv2.id,
        AdventureEntryCreate(kind="section", data={}),
    )

    # Parent from another adventure -> AdventureEntryParentError
    with pytest.raises(AdventureEntryParentError):
        fixture.service.create_entry(
            fixture.owner_a,
            fixture.room_a_id,
            adv1.id,
            AdventureEntryCreate(
                kind="section",
                data={},
                parent_entry_id=entry_foreign.id,
            ),
        )

    entry_a = fixture.service.create_entry(
        fixture.owner_a,
        fixture.room_a_id,
        adv1.id,
        AdventureEntryCreate(kind="section", data={}),
    )

    # Patch entry X parent = X -> error
    with pytest.raises(AdventureEntryParentError):
        fixture.service.patch_entry(
            fixture.owner_a,
            fixture.room_a_id,
            adv1.id,
            entry_a.id,
            AdventureEntryPatch(parent_entry_id=entry_a.id),
        )

    entry_b = fixture.service.create_entry(
        fixture.owner_a,
        fixture.room_a_id,
        adv1.id,
        AdventureEntryCreate(
            kind="section",
            data={},
            parent_entry_id=entry_a.id,
        ),
    )
    entry_c = fixture.service.create_entry(
        fixture.owner_a,
        fixture.room_a_id,
        adv1.id,
        AdventureEntryCreate(
            kind="section",
            data={},
            parent_entry_id=entry_b.id,
        ),
    )

    # Parent chain A -> B -> C then patch A.parent = C -> error (cycle)
    with pytest.raises(AdventureEntryParentError):
        fixture.service.patch_entry(
            fixture.owner_a,
            fixture.room_a_id,
            adv1.id,
            entry_a.id,
            AdventureEntryPatch(parent_entry_id=entry_c.id),
        )

    # Valid parent works and list_entries preserves sort_order
    entries = fixture.service.list_entries(fixture.owner_a, fixture.room_a_id, adv1.id)
    assert len(entries) == 3
    assert [e.id for e in entries] == [entry_a.id, entry_b.id, entry_c.id]
    assert entries[1].parent_entry_id == entry_a.id
    assert entries[2].parent_entry_id == entry_b.id


# 7. test_cross_room_adventure_is_not_found
def test_cross_room_adventure_is_not_found(fixture: AdventureFixture) -> None:
    adv_a = fixture.service.create_definition(
        fixture.owner_a,
        fixture.room_a_id,
        AdventureDefinitionCreate(name="Room A Adventure"),
    )

    # owner_b get_definition(room_b, adventure_in_room_a) -> AdventureNotFoundError
    with pytest.raises(AdventureNotFoundError):
        fixture.service.get_definition(
            fixture.owner_b,
            fixture.room_b_id,
            adv_a.id,
        )

    # owner_a with room_id=room_b -> AdventureNotFoundError
    with pytest.raises(AdventureNotFoundError):
        fixture.service.get_definition(
            fixture.owner_a,
            fixture.room_b_id,
            adv_a.id,
        )


# 8. test_archived_adventure_rejects_authoring_writes
def test_archived_adventure_rejects_authoring_writes(fixture: AdventureFixture) -> None:
    adv = fixture.service.create_definition(
        fixture.owner_a,
        fixture.room_a_id,
        AdventureDefinitionCreate(name="To Archive"),
    )
    entry = fixture.service.create_entry(
        fixture.owner_a,
        fixture.room_a_id,
        adv.id,
        AdventureEntryCreate(kind="dm_note", data={}),
    )

    now = datetime.now(timezone.utc)
    fixture.repository.set_status(adv.id, "archived", now)

    # Writes must be rejected with AdventureArchivedError
    with pytest.raises(AdventureArchivedError):
        fixture.service.patch_definition(
            fixture.owner_a,
            fixture.room_a_id,
            adv.id,
            AdventureDefinitionPatch(name="New Name"),
        )

    with pytest.raises(AdventureArchivedError):
        fixture.service.create_entry(
            fixture.owner_a,
            fixture.room_a_id,
            adv.id,
            AdventureEntryCreate(kind="section", data={}),
        )

    with pytest.raises(AdventureArchivedError):
        fixture.service.patch_entry(
            fixture.owner_a,
            fixture.room_a_id,
            adv.id,
            entry.id,
            AdventureEntryPatch(body="New Body"),
        )

    with pytest.raises(AdventureArchivedError):
        fixture.service.delete_entry(
            fixture.owner_a,
            fixture.room_a_id,
            adv.id,
            entry.id,
        )

    with pytest.raises(AdventureArchivedError):
        fixture.service.reorder_entries(
            fixture.owner_a,
            fixture.room_a_id,
            adv.id,
            AdventureEntryReorder(entry_ids=(entry.id,)),
        )

    # get/list still work for owner
    fetched_adv = fixture.service.get_definition(fixture.owner_a, fixture.room_a_id, adv.id)
    assert fetched_adv.status == "archived"

    adv_list = fixture.service.list_definitions(fixture.owner_a, fixture.room_a_id)
    assert len(adv_list) == 1

    fetched_entry = fixture.service.get_entry(fixture.owner_a, fixture.room_a_id, adv.id, entry.id)
    assert fetched_entry.id == entry.id

    entry_list = fixture.service.list_entries(fixture.owner_a, fixture.room_a_id, adv.id)
    assert len(entry_list) == 1


# 9. test_finalized_adventure_still_accepts_authoring_corrections
def test_finalized_adventure_still_accepts_authoring_corrections(
    fixture: AdventureFixture,
) -> None:
    adv = fixture.service.create_definition(
        fixture.owner_a,
        fixture.room_a_id,
        AdventureDefinitionCreate(name="Initial Name"),
    )
    entry = fixture.service.create_entry(
        fixture.owner_a,
        fixture.room_a_id,
        adv.id,
        AdventureEntryCreate(kind="dm_note", body="Initial Body", data={}),
    )

    now = datetime.now(timezone.utc)
    fixture.repository.set_status(adv.id, "finalized", now)
    # Compare timestamps read back through the same path: SQLite returns naive
    # datetimes while the create() view carries the aware value it wrote.
    before_adv = fixture.service.get_definition(fixture.owner_a, fixture.room_a_id, adv.id)
    before_entry = fixture.service.get_entry(fixture.owner_a, fixture.room_a_id, adv.id, entry.id)

    time.sleep(0.01)

    updated_adv = fixture.service.patch_definition(
        fixture.owner_a,
        fixture.room_a_id,
        adv.id,
        AdventureDefinitionPatch(name="Updated Name"),
    )
    assert updated_adv.name == "Updated Name"
    assert updated_adv.status == "finalized"
    assert updated_adv.updated_at > before_adv.updated_at

    updated_entry = fixture.service.patch_entry(
        fixture.owner_a,
        fixture.room_a_id,
        adv.id,
        entry.id,
        AdventureEntryPatch(body="Updated Body"),
    )
    assert updated_entry.body == "Updated Body"
    assert updated_entry.updated_at > before_entry.updated_at


# 10. test_reorder_entries_assigns_contiguous_sort_order
def test_reorder_entries_assigns_contiguous_sort_order(fixture: AdventureFixture) -> None:
    adv = fixture.service.create_definition(
        fixture.owner_a,
        fixture.room_a_id,
        AdventureDefinitionCreate(name="Reorder Test"),
    )
    entry_a = fixture.service.create_entry(
        fixture.owner_a,
        fixture.room_a_id,
        adv.id,
        AdventureEntryCreate(kind="dm_note", title="A", data={}),
    )
    entry_b = fixture.service.create_entry(
        fixture.owner_a,
        fixture.room_a_id,
        adv.id,
        AdventureEntryCreate(kind="dm_note", title="B", data={}),
    )
    entry_c = fixture.service.create_entry(
        fixture.owner_a,
        fixture.room_a_id,
        adv.id,
        AdventureEntryCreate(kind="dm_note", title="C", data={}),
    )

    # Reorder [c, a, b] -> sort_order 0, 1, 2
    fixture.service.reorder_entries(
        fixture.owner_a,
        fixture.room_a_id,
        adv.id,
        AdventureEntryReorder(entry_ids=(entry_c.id, entry_a.id, entry_b.id)),
    )

    entries = fixture.service.list_entries(fixture.owner_a, fixture.room_a_id, adv.id)
    assert len(entries) == 3
    assert [e.id for e in entries] == [entry_c.id, entry_a.id, entry_b.id]
    assert [e.sort_order for e in entries] == [0, 1, 2]

    # Reorder with a foreign id -> AdventureEntryNotFoundError and order unchanged
    foreign_id = uuid4()
    with pytest.raises(AdventureEntryNotFoundError):
        fixture.service.reorder_entries(
            fixture.owner_a,
            fixture.room_a_id,
            adv.id,
            AdventureEntryReorder(entry_ids=(entry_c.id, foreign_id, entry_b.id)),
        )

    entries_after = fixture.service.list_entries(fixture.owner_a, fixture.room_a_id, adv.id)
    assert [e.id for e in entries_after] == [entry_c.id, entry_a.id, entry_b.id]
    assert [e.sort_order for e in entries_after] == [0, 1, 2]
