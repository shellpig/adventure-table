from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, event, insert
from sqlalchemy.engine import Engine

from app.db import metadata
from app.domain.adventures.schemas import (
    AdventureDefinitionCreate,
    AdventureEntryAssetLink,
    AdventureEntryAssetNotFoundError,
    AdventureEntryCreate,
    AdventureForbiddenError,
    AdventureNotFoundError,
)
from app.domain.adventures.service import AdventureService
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.persistence.adventures.repository import AdventureRepository
from app.persistence.room_assets.repository import RoomAssetRepository, StoredRoomAsset
from app.persistence.rooms.tables import rooms


def _create_engine(db_path: Path) -> Engine:
    engine = create_engine(f"sqlite+pysqlite:///{db_path.as_posix()}")

    @event.listens_for(engine, "connect")
    def _enable_fks(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    metadata.create_all(engine)
    return engine


@dataclass(frozen=True)
class AuthoringTransactionFixture:
    engine: Engine
    repo: AdventureRepository
    asset_repo: RoomAssetRepository
    service: AdventureService
    room_a_id: UUID
    room_b_id: UUID
    owner_a: RoomAccessContext
    dm_a: RoomAccessContext
    member_a: RoomAccessContext
    owner_b: RoomAccessContext


@pytest.fixture
def fixture(tmp_path: Path) -> AuthoringTransactionFixture:
    engine = _create_engine(tmp_path / "test_p6f_authoring_transaction.db")
    room_a_id, room_b_id = uuid4(), uuid4()
    now = datetime.now(timezone.utc)
    defaults = {
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
                    {"id": room_a_id, "code": "ROOM-A", "name": "Room A", **defaults},
                    {"id": room_b_id, "code": "ROOM-B", "name": "Room B", **defaults},
                ]
            )
        )

    def _ctx(room_id: UUID, authority: RoomAccessAuthority, name: str) -> RoomAccessContext:
        return RoomAccessContext(
            room_id=room_id,
            access_session_id=uuid4(),
            authority=authority,
            display_name=name,
        )

    repo, asset_repo = AdventureRepository(engine), RoomAssetRepository(engine)
    return AuthoringTransactionFixture(
        engine=engine,
        repo=repo,
        asset_repo=asset_repo,
        service=AdventureService(repo, asset_repo),
        room_a_id=room_a_id,
        room_b_id=room_b_id,
        owner_a=_ctx(room_a_id, RoomAccessAuthority.OWNER, "Owner A"),
        dm_a=_ctx(room_a_id, RoomAccessAuthority.DM, "DM A"),
        member_a=_ctx(room_a_id, RoomAccessAuthority.MEMBER, "Member A"),
        owner_b=_ctx(room_b_id, RoomAccessAuthority.OWNER, "Owner B"),
    )


def _create_sample_asset(room_id: UUID) -> StoredRoomAsset:
    return StoredRoomAsset(
        id=uuid4(),
        room_id=room_id,
        kind="image",
        storage_key=f"assets/{uuid4()}.png",
        original_filename="sample.png",
        mime_type="image/png",
        size_bytes=1024,
        sha256="fake-sha256",
        visibility="room",
        created_at=datetime.now(timezone.utc),
    )


def _assert_empty_adventure(fixture: AuthoringTransactionFixture, def_id: UUID) -> None:
    assert fixture.repo.get_definition(fixture.room_a_id, def_id) is None
    assert len(fixture.repo.list_entries(def_id)) == 0
    assert len(fixture.repo.list_entry_assets(def_id)) == 0


@pytest.mark.parametrize("actor_role", ["owner", "dm"])
def test_authoring_transaction_composition_happy_path(
    fixture: AuthoringTransactionFixture, actor_role: str
) -> None:
    actor = fixture.owner_a if actor_role == "owner" else fixture.dm_a
    asset = _create_sample_asset(fixture.room_a_id)
    fixture.asset_repo.insert(asset)

    with fixture.engine.begin() as conn:
        # Step 1: create definition
        def_view = fixture.service.create_definition(
            actor,
            fixture.room_a_id,
            AdventureDefinitionCreate(
                name=f"{actor_role.upper()} Phandelver",
                summary="Starter adventure",
            ),
            connection=conn,
        )
        assert def_view.status == "draft"

        # Step 2: create parent entry
        parent_entry = fixture.service.create_entry(
            actor,
            fixture.room_a_id,
            def_view.id,
            AdventureEntryCreate(kind="section", title="Chapter 1: Goblin Arrows"),
            connection=conn,
        )
        assert parent_entry.sort_order == 0

        # Step 3: create child entry referencing parent (sees uncommitted parent & sort order)
        child_entry = fixture.service.create_entry(
            actor,
            fixture.room_a_id,
            def_view.id,
            AdventureEntryCreate(
                kind="scene",
                title="Cragmaw Hideout",
                parent_entry_id=parent_entry.id,
            ),
            connection=conn,
        )
        assert child_entry.parent_entry_id == parent_entry.id and child_entry.sort_order == 1

        # Step 4: link room asset to child entry (sees uncommitted link & asset resolution)
        linked_entry = fixture.service.link_entry_asset(
            actor,
            fixture.room_a_id,
            def_view.id,
            child_entry.id,
            AdventureEntryAssetLink(asset_id=asset.id, role="image"),
            connection=conn,
        )
        assert len(linked_entry.assets) == 1 and linked_entry.assets[0].asset.id == asset.id

        # Step 5: finalize definition (sees uncommitted draft status & updates)
        final_def = fixture.service.finalize(actor, fixture.room_a_id, def_view.id, connection=conn)
        assert final_def.status == "finalized"

        # Uncommitted writes are visible within the caller transaction
        uncommitted_def = fixture.repo.get_definition(
            fixture.room_a_id, def_view.id, connection=conn
        )
        assert uncommitted_def is not None and uncommitted_def.status == "finalized"
        uncommitted_entry = fixture.repo.get_entry(
            def_view.id, child_entry.id, connection=conn
        )
        assert uncommitted_entry is not None and uncommitted_entry.parent_entry_id == parent_entry.id
        assert len(fixture.repo.list_entry_assets(def_view.id, connection=conn)) == 1

    # After commit: fresh queries read all persisted data
    persisted_def = fixture.service.get_definition(actor, fixture.room_a_id, def_view.id)
    assert persisted_def.status == "finalized"

    persisted_entries = fixture.service.list_entries(actor, fixture.room_a_id, def_view.id)
    assert len(persisted_entries) == 2
    assert persisted_entries[0].id == parent_entry.id and persisted_entries[0].sort_order == 0
    assert persisted_entries[1].id == child_entry.id and persisted_entries[1].sort_order == 1
    assert persisted_entries[1].parent_entry_id == parent_entry.id
    assert len(persisted_entries[1].assets) == 1 and persisted_entries[1].assets[0].asset.id == asset.id


def test_authoring_transaction_forced_failure_rolls_back_everything(
    fixture: AuthoringTransactionFixture,
) -> None:
    asset = _create_sample_asset(fixture.room_a_id)
    fixture.asset_repo.insert(asset)
    created_def_id: UUID | None = None

    with pytest.raises(RuntimeError, match="forced failure"):
        with fixture.engine.begin() as conn:
            def_view = fixture.service.create_definition(
                fixture.owner_a,
                fixture.room_a_id,
                AdventureDefinitionCreate(name="Doomed Adventure"),
                connection=conn,
            )
            created_def_id = def_view.id

            entry_view = fixture.service.create_entry(
                fixture.owner_a,
                fixture.room_a_id,
                def_view.id,
                AdventureEntryCreate(kind="section", title="Doomed Section"),
                connection=conn,
            )
            fixture.service.link_entry_asset(
                fixture.owner_a,
                fixture.room_a_id,
                def_view.id,
                entry_view.id,
                AdventureEntryAssetLink(asset_id=asset.id, role="image"),
                connection=conn,
            )
            raise RuntimeError("forced failure")

    assert created_def_id is not None
    _assert_empty_adventure(fixture, created_def_id)


@pytest.mark.parametrize("scenario", ["cross_room", "missing"])
def test_invalid_asset_denied_and_rolled_back(
    fixture: AuthoringTransactionFixture, scenario: str
) -> None:
    if scenario == "cross_room":
        asset_b = _create_sample_asset(fixture.room_b_id)
        fixture.asset_repo.insert(asset_b)
        target_asset_id = asset_b.id
    else:
        target_asset_id = uuid4()

    created_def_id: UUID | None = None
    with pytest.raises(AdventureEntryAssetNotFoundError):
        with fixture.engine.begin() as conn:
            def_view = fixture.service.create_definition(
                fixture.owner_a,
                fixture.room_a_id,
                AdventureDefinitionCreate(name="Invalid Asset Attempt"),
                connection=conn,
            )
            created_def_id = def_view.id

            entry_view = fixture.service.create_entry(
                fixture.owner_a,
                fixture.room_a_id,
                def_view.id,
                AdventureEntryCreate(kind="section", title="Section 1"),
                connection=conn,
            )
            fixture.service.link_entry_asset(
                fixture.owner_a,
                fixture.room_a_id,
                def_view.id,
                entry_view.id,
                AdventureEntryAssetLink(asset_id=target_asset_id, role="image"),
                connection=conn,
            )

    assert created_def_id is not None
    _assert_empty_adventure(fixture, created_def_id)


def test_member_and_cross_room_authority_denied_with_zero_side_effects(
    fixture: AuthoringTransactionFixture,
) -> None:
    # 1. Creation attempts by non-author actors are denied and produce zero rows
    for actor, exc in [
        (fixture.member_a, AdventureForbiddenError),
        (fixture.owner_b, AdventureNotFoundError),
    ]:
        with pytest.raises(exc):
            with fixture.engine.begin() as conn:
                fixture.service.create_definition(
                    actor,
                    fixture.room_a_id,
                    AdventureDefinitionCreate(name="Unauthorized Def"),
                    connection=conn,
                )
    assert len(fixture.repo.list_definitions(fixture.room_a_id)) == 0

    # 2. Existing draft definition rejects MEMBER writes in transaction with zero mutations
    valid_def = fixture.service.create_definition(
        fixture.owner_a,
        fixture.room_a_id,
        AdventureDefinitionCreate(name="Valid Draft"),
    )

    with pytest.raises(AdventureForbiddenError):
        with fixture.engine.begin() as conn:
            fixture.service.create_entry(
                fixture.member_a,
                fixture.room_a_id,
                valid_def.id,
                AdventureEntryCreate(kind="section", title="Unauthorized Entry"),
                connection=conn,
            )
    assert len(fixture.repo.list_entries(valid_def.id)) == 0

    with pytest.raises(AdventureForbiddenError):
        with fixture.engine.begin() as conn:
            fixture.service.finalize(
                fixture.member_a,
                fixture.room_a_id,
                valid_def.id,
                connection=conn,
            )
    check_def = fixture.repo.get_definition(fixture.room_a_id, valid_def.id)
    assert check_def is not None and check_def.status == "draft"


def test_authoring_without_connection_parameter_maintains_original_behavior(
    fixture: AuthoringTransactionFixture,
) -> None:
    asset = _create_sample_asset(fixture.room_a_id)
    fixture.asset_repo.insert(asset)

    def_view = fixture.service.create_definition(
        fixture.owner_a,
        fixture.room_a_id,
        AdventureDefinitionCreate(name="Standard Workflow"),
    )
    entry_view = fixture.service.create_entry(
        fixture.owner_a,
        fixture.room_a_id,
        def_view.id,
        AdventureEntryCreate(kind="section", title="Standard Section"),
    )
    linked_entry = fixture.service.link_entry_asset(
        fixture.owner_a,
        fixture.room_a_id,
        def_view.id,
        entry_view.id,
        AdventureEntryAssetLink(asset_id=asset.id, role="image"),
    )
    final_def = fixture.service.finalize(
        fixture.owner_a,
        fixture.room_a_id,
        def_view.id,
    )

    assert def_view.status == "draft"
    assert entry_view.sort_order == 0
    assert len(linked_entry.assets) == 1
    assert final_def.status == "finalized"
