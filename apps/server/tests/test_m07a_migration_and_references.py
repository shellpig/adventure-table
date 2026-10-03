from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import importlib.util
import os
from pathlib import Path
from threading import Barrier
import time
from typing import Generator
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from fastapi import Request
from fastapi.testclient import TestClient
import pytest
import sqlalchemy as sa
from sqlalchemy import (
    create_engine,
    event,
    insert,
    select,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from app.api.dependencies import (
    get_content_localization,
    get_content_registry,
    get_database_engine,
)
from app.api.errors import APIError
from app.api.rooms.access import get_room_access_context
from app.api.rooms.dependencies import (
    get_monster_instance_service,
    get_monster_library_service,
)
from app.content import load_default_content_registry
from app.content.localization_files import load_content_localization_catalog
from app.content.registry import resolve_content_root
from app.db import metadata
from app.domain.combat.monster_instances import (
    CreateMonsterFromContentInput,
    MonsterInstanceService,
)
from app.domain.monster_library.errors import (
    MonsterTemplateArchivedError,
    MonsterTemplateNotFoundError,
    MonsterTemplateReferencedError,
)
from app.domain.monster_library.references import validate_custom_monster_template_ref
from app.domain.monster_library.schemas import CreateCustomMonsterInput
from app.domain.monster_library.service import MonsterLibraryService
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.table_events import (
    TableActorContext,
    TableActorKind,
    TableEventService,
)
from app.main import app
from app.persistence.adventure_imports.tables import (
    adventure_import_drafts,
    adventure_imports,
)
from app.persistence.adventures.tables import (
    adventure_definitions,
    adventure_entries,
)
from app.domain.campaign_runtime.entry_mutations import (
    execute_create_entry_in_transaction,
    execute_update_entry_in_transaction,
)
from app.domain.campaign_runtime.schemas import (
    RuntimeWorldEntryCreate,
    RuntimeWorldEntryPatch,
)
from app.persistence.adventures.repository import CampaignAdventureLinkRepository
from app.persistence.campaign_runtime.mutations import CampaignWorldMutationRepository
from app.persistence.campaign_runtime.repository import CampaignRuntimeRepository
from app.persistence.campaign_runtime.tables import (
    campaign_adventure_overrides,
    campaign_world_entries,
)
from app.persistence.combat.repository import MonsterRepository
from app.persistence.combat.tables import monster_instances, monster_templates
from app.persistence.monster_library.repository import MonsterLibraryRepository
from app.persistence.rooms.table_runtime import TableEventRepository
from app.persistence.rooms.tables import campaigns, rooms
from app.persistence.rooms.workspace import RoomWorkspaceRepository

POSTGRES_URL = os.environ.get("P4_POSTGRES_URL")
SERVER_ROOT = Path(__file__).resolve().parents[1]


def _alembic_config() -> Config:
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SERVER_ROOT / "alembic"))
    if POSTGRES_URL:
        config.set_main_option("sqlalchemy.url", POSTGRES_URL)
        config.attributes["target_database_url"] = POSTGRES_URL
    return config


def _load_migration():
    path = SERVER_ROOT / "alembic" / "versions" / "0041_m07a_room_monster_templates.py"
    spec = importlib.util.spec_from_file_location("m07a_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
class RefFixture:
    client: TestClient
    engine: Engine
    room_a_id: UUID
    room_b_id: UUID
    campaign_a_id: UUID
    campaign_b_id: UUID
    token_owner_a: str
    token_owner_b: str
    ctx_owner_a: RoomAccessContext
    ctx_owner_b: RoomAccessContext
    library_service: MonsterLibraryService
    instance_service: MonsterInstanceService


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def ref_fixture() -> Generator[RefFixture, None, None]:
    engine = _engine()
    registry = load_default_content_registry()
    content_root = resolve_content_root()
    localization = load_content_localization_catalog(registry, content_root)

    room_a_id = uuid4()
    room_b_id = uuid4()
    campaign_a_id = uuid4()
    campaign_b_id = uuid4()
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
                        "owner_key_hash": b"owner_a",
                        "dm_key_hash": b"dm_a",
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": room_b_id,
                        "code": "ROOMB",
                        "name": "Room B",
                        "password_salt": b"salt",
                        "password_hash": b"pw",
                        "owner_key_hash": b"owner_b",
                        "dm_key_hash": b"dm_b",
                        "created_at": now,
                        "updated_at": now,
                    },
                ]
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
                        "status": "active",
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": campaign_b_id,
                        "room_id": room_b_id,
                        "name": "Campaign B",
                        "ruleset": "dnd-5e-2014",
                        "status": "active",
                        "created_at": now,
                        "updated_at": now,
                    },
                ]
            )
        )

    token_owner_a = "token-owner-a"
    token_owner_b = "token-owner-b"

    ctx_owner_a = RoomAccessContext(
        room_id=room_a_id,
        access_session_id=uuid4(),
        authority=RoomAccessAuthority.OWNER,
        display_name="Owner A",
    )
    ctx_owner_b = RoomAccessContext(
        room_id=room_b_id,
        access_session_id=uuid4(),
        authority=RoomAccessAuthority.OWNER,
        display_name="Owner B",
    )

    token_map = {
        token_owner_a: ctx_owner_a,
        token_owner_b: ctx_owner_b,
    }

    def _override_access(request: Request) -> RoomAccessContext:
        auth_hdr = request.headers.get("authorization", "")
        _, _, tok = auth_hdr.partition(" ")
        clean = tok.strip()
        if clean in token_map:
            return token_map[clean]
        raise APIError(401, "room_access_required", "Room access required")

    monster_repo = MonsterRepository(engine)
    library_repo = MonsterLibraryRepository(engine)
    event_repo = TableEventRepository(engine)
    table_event_service = TableEventService(event_repo)
    table_event_service.require_actor_current = lambda actor: None

    library_service = MonsterLibraryService(
        engine=engine,
        repository=library_repo,
        monster_repository=monster_repo,
        content_registry=registry,
        localization=localization,
        table_event_service=table_event_service,
    )
    instance_service = MonsterInstanceService(
        monster_repository=monster_repo,
        content_registry=registry,
        table_event_service=table_event_service,
    )

    app.state.content_registry = registry
    app.state.content_localization = localization
    app.state.monster_library_service = library_service
    app.state.monster_instance_service = instance_service

    app.dependency_overrides[get_database_engine] = lambda: engine
    app.dependency_overrides[get_content_registry] = lambda: registry
    app.dependency_overrides[get_content_localization] = lambda: localization
    app.dependency_overrides[get_room_access_context] = _override_access
    app.dependency_overrides[get_monster_library_service] = lambda: library_service
    app.dependency_overrides[get_monster_instance_service] = lambda: instance_service

    client = TestClient(app)
    try:
        yield RefFixture(
            client=client,
            engine=engine,
            room_a_id=room_a_id,
            room_b_id=room_b_id,
            campaign_a_id=campaign_a_id,
            campaign_b_id=campaign_b_id,
            token_owner_a=token_owner_a,
            token_owner_b=token_owner_b,
            ctx_owner_a=ctx_owner_a,
            ctx_owner_b=ctx_owner_b,
            library_service=library_service,
            instance_service=instance_service,
        )
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


# -----------------------------------------------------------------------------
# 1. SQLite migration tests (empty + seeded rows)
# -----------------------------------------------------------------------------

def test_sqlite_migration_0041_empty_table() -> None:
    migration = _load_migration()
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("CREATE TABLE rooms (id CHAR(32) PRIMARY KEY)")
            conn.exec_driver_sql("CREATE TABLE campaigns (id CHAR(32) PRIMARY KEY, room_id CHAR(32) REFERENCES rooms(id))")
            conn.exec_driver_sql(
                """
                CREATE TABLE monster_templates (
                    id CHAR(32) PRIMARY KEY,
                    campaign_id CHAR(32) REFERENCES campaigns(id),
                    name VARCHAR NOT NULL,
                    source_key VARCHAR,
                    rules JSON NOT NULL,
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP
                )
                """
            )
            conn.exec_driver_sql("CREATE INDEX ix_monster_templates_campaign_id ON monster_templates(campaign_id)")
            conn.exec_driver_sql(
                """
                CREATE TABLE monster_instances (
                    id CHAR(32) PRIMARY KEY,
                    campaign_id CHAR(32) REFERENCES campaigns(id),
                    name VARCHAR NOT NULL,
                    rules_snapshot JSON NOT NULL,
                    template_key VARCHAR,
                    custom_template_id CHAR(32) REFERENCES monster_templates(id) ON DELETE SET NULL,
                    current_hp INTEGER,
                    temp_hp INTEGER NOT NULL DEFAULT 0,
                    conditions JSON NOT NULL DEFAULT '[]',
                    effects JSON NOT NULL DEFAULT '[]',
                    combat_status VARCHAR NOT NULL DEFAULT 'active',
                    initiative INTEGER,
                    reaction_available BOOLEAN NOT NULL DEFAULT 1,
                    resources JSON NOT NULL DEFAULT '{}',
                    visibility VARCHAR NOT NULL DEFAULT 'public',
                    position_note VARCHAR,
                    reveal_state JSON NOT NULL DEFAULT '{}',
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP
                )
                """
            )
            context = MigrationContext.configure(conn)
            with Operations.context(context):
                migration.upgrade()

            cols = {c["name"] for c in sa.inspect(conn).get_columns("monster_templates")}
            assert "room_id" in cols
            assert "revision" in cols
            assert "archived_at" in cols
            assert "presentation_json" in cols
            assert "campaign_id" not in cols

            with Operations.context(context):
                migration.downgrade()

            cols_downgrade = {c["name"] for c in sa.inspect(conn).get_columns("monster_templates")}
            assert "campaign_id" in cols_downgrade
            assert "room_id" not in cols_downgrade
    finally:
        engine.dispose()


def test_sqlite_migration_0041_seeded_campaign_bound_rows() -> None:
    migration = _load_migration()
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    try:
        room_id = uuid4()
        camp_id = uuid4()
        tpl_id = uuid4()
        inst_id = uuid4()

        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.exec_driver_sql("PRAGMA foreign_keys = OFF")
            conn.exec_driver_sql("CREATE TABLE rooms (id CHAR(32) PRIMARY KEY)")
            conn.exec_driver_sql("CREATE TABLE campaigns (id CHAR(32) PRIMARY KEY, room_id CHAR(32) REFERENCES rooms(id))")
            conn.exec_driver_sql(
                """
                CREATE TABLE monster_templates (
                    id CHAR(32) PRIMARY KEY,
                    campaign_id CHAR(32) REFERENCES campaigns(id),
                    name VARCHAR NOT NULL,
                    source_key VARCHAR,
                    rules JSON NOT NULL,
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP
                )
                """
            )
            conn.exec_driver_sql("CREATE INDEX ix_monster_templates_campaign_id ON monster_templates(campaign_id)")
            conn.exec_driver_sql(
                """
                CREATE TABLE monster_instances (
                    id CHAR(32) PRIMARY KEY,
                    campaign_id CHAR(32) REFERENCES campaigns(id),
                    name VARCHAR NOT NULL,
                    rules_snapshot JSON NOT NULL,
                    template_key VARCHAR,
                    custom_template_id CHAR(32) REFERENCES monster_templates(id) ON DELETE SET NULL,
                    current_hp INTEGER,
                    temp_hp INTEGER NOT NULL DEFAULT 0,
                    conditions JSON NOT NULL DEFAULT '[]',
                    effects JSON NOT NULL DEFAULT '[]',
                    combat_status VARCHAR NOT NULL DEFAULT 'active',
                    initiative INTEGER,
                    reaction_available BOOLEAN NOT NULL DEFAULT 1,
                    resources JSON NOT NULL DEFAULT '{}',
                    visibility VARCHAR NOT NULL DEFAULT 'public',
                    position_note VARCHAR,
                    reveal_state JSON NOT NULL DEFAULT '{}',
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP
                )
                """
            )

            conn.execute(sa.text("INSERT INTO rooms VALUES (:id)"), {"id": room_id.hex})
            conn.execute(sa.text("INSERT INTO campaigns VALUES (:id, :room_id)"), {"id": camp_id.hex, "room_id": room_id.hex})
            conn.execute(
                sa.text(
                    "INSERT INTO monster_templates VALUES (:id, :camp_id, 'Orc Raider', 'srd:orc', '{\"armor_class\": 13, \"max_hp\": 15}', '2026-01-01', '2026-01-01')"
                ),
                {"id": tpl_id.hex, "camp_id": camp_id.hex},
            )
            conn.execute(
                sa.text(
                    "INSERT INTO monster_instances (id, campaign_id, name, rules_snapshot, custom_template_id) VALUES (:id, :camp_id, 'Orc 1', '{\"armor_class\": 13, \"max_hp\": 15}', :tpl_id)"
                ),
                {"id": inst_id.hex, "camp_id": camp_id.hex, "tpl_id": tpl_id.hex},
            )

            context = MigrationContext.configure(conn)
            with Operations.context(context):
                migration.upgrade()

            row = conn.execute(sa.text("SELECT * FROM monster_templates WHERE id = :id"), {"id": tpl_id.hex}).mappings().one()
            # room_id is backfilled from campaign's room_id
            assert row["room_id"] == room_id.hex or row["room_id"] == room_id
            assert row["name"] == "Orc Raider"
            assert row["source_key"] == "srd:orc"
            assert row["revision"] == 1
            assert row["archived_at"] is None

            # Instance snapshot untouched
            inst_row = conn.execute(sa.text("SELECT * FROM monster_instances WHERE id = :id"), {"id": inst_id.hex}).mappings().one()
            assert "Orc Raider" in str(row["name"])
            assert inst_row["custom_template_id"] == tpl_id.hex or inst_row["custom_template_id"] == tpl_id

            # Downgrade preserves campaign_id backfill
            with Operations.context(context):
                migration.downgrade()

            down_row = conn.execute(sa.text("SELECT * FROM monster_templates WHERE id = :id"), {"id": tpl_id.hex}).mappings().one()
            assert down_row["campaign_id"] == camp_id.hex or down_row["campaign_id"] == camp_id
    finally:
        engine.dispose()


# -----------------------------------------------------------------------------
# 2. PostgreSQL migration test (gated by P4_POSTGRES_URL + xdist_group)
# -----------------------------------------------------------------------------

@pytest.mark.xdist_group("postgres")
@pytest.mark.skipif(
    not POSTGRES_URL,
    reason="P4_POSTGRES_URL is only supplied by the PostgreSQL job",
)
def test_postgres_migration_0041() -> None:
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    try:
        with engine.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))

        cfg = _alembic_config()
        # Upgrade to 0040 (down revision)
        command.upgrade(cfg, "0040_p5g_terrain_normal")

        room_id = uuid4()
        camp_id = uuid4()
        tpl_id = uuid4()
        inst_id = uuid4()
        now = datetime.now(timezone.utc)

        with engine.begin() as conn:
            conn.execute(
                insert(rooms).values(
                    id=room_id,
                    code="PG-M07",
                    name="PG Room",
                    password_salt=b"salt" * 8,
                    password_hash=b"hash" * 16,
                    owner_key_hash=b"owner" * 6 + b"12",
                    dm_key_hash=b"dm" * 16,
                    created_at=now,
                    updated_at=now,
                )
            )
            conn.execute(
                insert(campaigns).values(
                    id=camp_id,
                    room_id=room_id,
                    name="PG Campaign",
                    ruleset="dnd-5e-2014",
                    status="active",
                    created_at=now,
                    updated_at=now,
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO monster_templates (id, campaign_id, name, source_key, rules, created_at, updated_at)
                    VALUES (:id, :camp_id, 'PG Bugbear', 'srd:bugbear', '{"armor_class": 16, "max_hp": 27}', :now, :now)
                    """
                ),
                {"id": tpl_id, "camp_id": camp_id, "now": now},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO monster_instances (
                        id, campaign_id, name, rules_snapshot, custom_template_id,
                        current_hp, temp_hp, conditions, effects, concentration,
                        combat_status, initiative, reaction_available, resources,
                        visibility, position_note, reveal_state, created_at, updated_at
                    )
                    VALUES (
                        :id, :camp_id, 'Bugbear 1', '{"armor_class": 16, "max_hp": 27}', :tpl_id,
                        27, 0, '[]', '[]', NULL,
                        'active', NULL, TRUE, '{}',
                        'public', NULL, '{}', :now, :now
                    )
                    """
                ),
                {"id": inst_id, "camp_id": camp_id, "tpl_id": tpl_id, "now": now},
            )

        # Upgrade to 0041
        command.upgrade(cfg, "0041_m07a_room_monster_templates")

        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM monster_templates WHERE id = :id"),
                {"id": tpl_id},
            ).mappings().one()
            assert row["room_id"] == room_id
            assert row["name"] == "PG Bugbear"
            assert row["revision"] == 1
            assert row["archived_at"] is None

            # Assert Instance snapshot is unchanged after upgrade
            inst_row = conn.execute(
                text("SELECT * FROM monster_instances WHERE id = :id"),
                {"id": inst_id},
            ).mappings().one()
            assert inst_row["name"] == "Bugbear 1"
            assert inst_row["custom_template_id"] == tpl_id
            assert inst_row["rules_snapshot"] == {"armor_class": 16, "max_hp": 27}

            # Verify RESTRICT on custom_template_id: deleting template with instance fails with IntegrityError
            with pytest.raises(sa.exc.IntegrityError):
                with engine.begin() as del_conn:
                    del_conn.execute(
                        text("DELETE FROM monster_templates WHERE id = :id"),
                        {"id": tpl_id},
                    )

        # Downgrade to 0040
        command.downgrade(cfg, "0040_p5g_terrain_normal")
        with engine.connect() as conn:
            down_row = conn.execute(
                text("SELECT * FROM monster_templates WHERE id = :id"),
                {"id": tpl_id},
            ).mappings().one()
            assert down_row["campaign_id"] == camp_id

        # Upgrade to heads
        command.upgrade(cfg, "heads")
    finally:
        engine.dispose()


# -----------------------------------------------------------------------------
# 3. Multi-room isolation
# -----------------------------------------------------------------------------

def test_multi_room_isolation(ref_fixture: RefFixture) -> None:
    fix = ref_fixture

    # Create template T_A in Room A
    t_a = fix.library_service.create_custom(
        fix.ctx_owner_a,
        fix.room_a_id,
        CreateCustomMonsterInput(name="Room A Beast", armor_class=12, max_hp=30),
    )
    t_a_uuid = UUID(t_a.ref.removeprefix("custom:"))

    # Room B attempts to GET T_A -> 404
    resp_get = fix.client.get(
        f"/api/rooms/{fix.room_b_id}/monster-library/custom:{t_a_uuid}",
        headers=_auth(fix.token_owner_b),
    )
    assert resp_get.status_code == 404

    # Room B attempts to PATCH T_A -> 404
    resp_patch = fix.client.patch(
        f"/api/rooms/{fix.room_b_id}/monster-library/custom/{t_a_uuid}",
        json={"expected_revision": 1, "armor_class": 15},
        headers=_auth(fix.token_owner_b),
    )
    assert resp_patch.status_code == 404

    # Room B attempts to DELETE T_A -> 404
    resp_del = fix.client.delete(
        f"/api/rooms/{fix.room_b_id}/monster-library/custom/{t_a_uuid}?expected_revision=1",
        headers=_auth(fix.token_owner_b),
    )
    assert resp_del.status_code == 404

    # Room B attempts to create instance from T_A in Room B's campaign -> fails 404
    seat_b_id = uuid4()
    actor_b = TableActorContext(
        actor_kind=TableActorKind.HUMAN,
        room_id=fix.room_b_id,
        campaign_id=fix.campaign_b_id,
        session_id=uuid4(),
        seat_id=seat_b_id,
        controlled_seat_ids=(seat_b_id,),
        role="dm",
        is_current_dm=True,
    )
    with pytest.raises(MonsterTemplateNotFoundError):
        fix.instance_service.create_from_content(
            actor_b,
            CreateMonsterFromContentInput(content_key=f"custom:{t_a_uuid}"),
        )


# -----------------------------------------------------------------------------
# 4. Reference protection on DELETE
# -----------------------------------------------------------------------------

def test_references_block_delete_matrix(ref_fixture: RefFixture) -> None:
    fix = ref_fixture

    # Case 0: Unreferenced template deletion succeeds
    t0 = fix.library_service.create_custom(
        fix.ctx_owner_a,
        fix.room_a_id,
        CreateCustomMonsterInput(name="T0 Unreferenced", armor_class=10, max_hp=10),
    )
    t0_id = t0.ref.removeprefix("custom:")
    del_r0 = fix.client.delete(
        f"/api/rooms/{fix.room_a_id}/monster-library/custom/{t0_id}?expected_revision=1",
        headers=_auth(fix.token_owner_a),
    )
    assert del_r0.status_code == 204

    # Case 1: Referenced by monster_instances
    t1 = fix.library_service.create_custom(
        fix.ctx_owner_a,
        fix.room_a_id,
        CreateCustomMonsterInput(name="T1 Instanced", armor_class=10, max_hp=10),
    )
    t1_id = UUID(t1.ref.removeprefix("custom:"))
    inst = fix.instance_service.monster_repository.create_instance(
        campaign_id=fix.campaign_a_id,
        name="T1 Instance",
        rules_snapshot=deepcopy(t1.rules),
        custom_template_id=t1_id,
    )
    del_r1 = fix.client.delete(
        f"/api/rooms/{fix.room_a_id}/monster-library/custom/{t1_id}?expected_revision=1",
        headers=_auth(fix.token_owner_a),
    )
    assert del_r1.status_code == 409
    assert del_r1.json()["error"]["code"] == "monster_template_referenced"

    # Case 2: Referenced by adventure_entries (kind="npc")
    t2 = fix.library_service.create_custom(
        fix.ctx_owner_a,
        fix.room_a_id,
        CreateCustomMonsterInput(name="T2 Adv NPC", armor_class=10, max_hp=10),
    )
    t2_id = UUID(t2.ref.removeprefix("custom:"))
    adv_id = uuid4()
    entry_id = uuid4()
    now = datetime.now(timezone.utc)
    with fix.engine.begin() as conn:
        conn.execute(
            insert(adventure_definitions).values(
                id=adv_id,
                room_id=fix.room_a_id,
                name="Adv A",
                summary="Adv A summary",
                status="finalized",
                created_at=now,
                updated_at=now,
            )
        )
        conn.execute(
            insert(adventure_entries).values(
                id=entry_id,
                adventure_id=adv_id,
                kind="npc",
                title="NPC Entry",
                body="Body",
                data_json={"kind": "npc", "monster_template_ref": f"custom:{t2_id}"},
                visibility="public",
                sort_order=1,
                created_at=now,
                updated_at=now,
            )
        )
    del_r2 = fix.client.delete(
        f"/api/rooms/{fix.room_a_id}/monster-library/custom/{t2_id}?expected_revision=1",
        headers=_auth(fix.token_owner_a),
    )
    assert del_r2.status_code == 409
    assert del_r2.json()["error"]["code"] == "monster_template_referenced"

    # Case 3: Referenced by adventure_entries (kind="monster_ref")
    t3 = fix.library_service.create_custom(
        fix.ctx_owner_a,
        fix.room_a_id,
        CreateCustomMonsterInput(name="T3 Adv Ref", armor_class=10, max_hp=10),
    )
    t3_id = UUID(t3.ref.removeprefix("custom:"))
    entry3_id = uuid4()
    with fix.engine.begin() as conn:
        conn.execute(
            insert(adventure_entries).values(
                id=entry3_id,
                adventure_id=adv_id,
                kind="monster_ref",
                title="Monster Ref Entry",
                body="Body",
                data_json={"kind": "monster_ref", "monster_template_ref": f"custom:{t3_id}"},
                visibility="public",
                sort_order=2,
                created_at=now,
                updated_at=now,
            )
        )
    del_r3 = fix.client.delete(
        f"/api/rooms/{fix.room_a_id}/monster-library/custom/{t3_id}?expected_revision=1",
        headers=_auth(fix.token_owner_a),
    )
    assert del_r3.status_code == 409
    assert del_r3.json()["error"]["code"] == "monster_template_referenced"

    # Case 4: Referenced by campaign_world_entries (kind="npc")
    t4 = fix.library_service.create_custom(
        fix.ctx_owner_a,
        fix.room_a_id,
        CreateCustomMonsterInput(name="T4 World NPC", armor_class=10, max_hp=10),
    )
    t4_id = UUID(t4.ref.removeprefix("custom:"))
    world_entry_id = uuid4()
    with fix.engine.begin() as conn:
        conn.execute(
            insert(campaign_world_entries).values(
                id=world_entry_id,
                campaign_id=fix.campaign_a_id,
                kind="npc",
                title="World NPC",
                body="Body",
                state_json={"kind": "npc", "monster_template_ref": f"custom:{t4_id}"},
                visibility="public",
                created_by_actor_kind="user",
                created_at=now,
                updated_at=now,
            )
        )
    del_r4 = fix.client.delete(
        f"/api/rooms/{fix.room_a_id}/monster-library/custom/{t4_id}?expected_revision=1",
        headers=_auth(fix.token_owner_a),
    )
    assert del_r4.status_code == 409
    assert del_r4.json()["error"]["code"] == "monster_template_referenced"

    # Case 5: Referenced by campaign_adventure_overrides
    t5 = fix.library_service.create_custom(
        fix.ctx_owner_a,
        fix.room_a_id,
        CreateCustomMonsterInput(name="T5 Override", armor_class=10, max_hp=10),
    )
    t5_id = UUID(t5.ref.removeprefix("custom:"))
    override_id = uuid4()
    dummy_entry_id = uuid4()
    with fix.engine.begin() as conn:
        conn.execute(
            insert(adventure_entries).values(
                id=dummy_entry_id,
                adventure_id=adv_id,
                kind="npc",
                title="Dummy Entry",
                body="Body",
                data_json={"kind": "npc"},
                visibility="public",
                sort_order=3,
                created_at=now,
                updated_at=now,
            )
        )
        conn.execute(
            insert(campaign_adventure_overrides).values(
                id=override_id,
                campaign_id=fix.campaign_a_id,
                adventure_entry_id=dummy_entry_id,
                state_json={"kind": "npc", "monster_template_ref": f"custom:{t5_id}"},
                needs_review=False,
                created_at=now,
                updated_at=now,
            )
        )
    del_r5 = fix.client.delete(
        f"/api/rooms/{fix.room_a_id}/monster-library/custom/{t5_id}?expected_revision=1",
        headers=_auth(fix.token_owner_a),
    )
    assert del_r5.status_code == 409
    assert del_r5.json()["error"]["code"] == "monster_template_referenced"

    # Case 6: Referenced by adventure_import_drafts
    t6 = fix.library_service.create_custom(
        fix.ctx_owner_a,
        fix.room_a_id,
        CreateCustomMonsterInput(name="T6 Draft", armor_class=10, max_hp=10),
    )
    t6_id = UUID(t6.ref.removeprefix("custom:"))
    import_id = uuid4()
    with fix.engine.begin() as conn:
        conn.execute(
            insert(adventure_imports).values(
                id=import_id,
                room_id=fix.room_a_id,
                name="Test Import",
                status="drafting",
                created_at=now,
                updated_at=now,
            )
        )
        conn.execute(
            insert(adventure_import_drafts).values(
                import_id=import_id,
                draft_json={
                    "entries": [
                        {
                            "entry_id": "e1",
                            "payload": {
                                "kind": "npc",
                                "monster_template_ref": f"custom:{t6_id}",
                            },
                        }
                    ]
                },
                warnings_json=[],
                updated_at=now,
            )
        )
    del_r6 = fix.client.delete(
        f"/api/rooms/{fix.room_a_id}/monster-library/custom/{t6_id}?expected_revision=1",
        headers=_auth(fix.token_owner_a),
    )
    assert del_r6.status_code == 409
    assert del_r6.json()["error"]["code"] == "monster_template_referenced"


# -----------------------------------------------------------------------------
# 5. Archive lifecycle & unchanged P6 reference
# -----------------------------------------------------------------------------

def test_archive_lifecycle_and_p6_references(ref_fixture: RefFixture) -> None:
    fix = ref_fixture

    t = fix.library_service.create_custom(
        fix.ctx_owner_a,
        fix.room_a_id,
        CreateCustomMonsterInput(name="Ancient Golem", armor_class=17, max_hp=120),
    )
    t_id = t.ref.removeprefix("custom:")
    t_uuid = UUID(t_id)

    # Archive the template
    arch_resp = fix.client.post(
        f"/api/rooms/{fix.room_a_id}/monster-library/custom/{t_id}/archive",
        json={"expected_revision": 1},
        headers=_auth(fix.token_owner_a),
    )
    assert arch_resp.status_code == 200
    arch_data = arch_resp.json()
    assert arch_data["archived_at"] is not None
    assert arch_data["revision"] == 2

    # Default list hides archived template
    list_r1 = fix.client.get(
        f"/api/rooms/{fix.room_a_id}/monster-library",
        headers=_auth(fix.token_owner_a),
    )
    assert list_r1.status_code == 200
    all_refs1 = [item["ref"] for item in list_r1.json()]
    assert t.ref not in all_refs1

    # list with include_archived=true includes it
    list_r2 = fix.client.get(
        f"/api/rooms/{fix.room_a_id}/monster-library?include_archived=true",
        headers=_auth(fix.token_owner_a),
    )
    assert list_r2.status_code == 200
    all_refs2 = [item["ref"] for item in list_r2.json()]
    assert t.ref in all_refs2

    # Human can read detail of archived template
    detail_r = fix.client.get(
        f"/api/rooms/{fix.room_a_id}/monster-library/custom:{t_id}",
        headers=_auth(fix.token_owner_a),
    )
    assert detail_r.status_code == 200
    assert detail_r.json()["archived_at"] is not None

    # Human can copy archived template to create a new active template
    copy_r = fix.client.post(
        f"/api/rooms/{fix.room_a_id}/monster-library/custom/{t_id}/copy",
        json={"expected_revision": 2, "name": "Restored Ancient Golem"},
        headers=_auth(fix.token_owner_a),
    )
    assert copy_r.status_code == 201
    copied = copy_r.json()
    assert copied["name"] == "Restored Ancient Golem"
    assert copied["archived_at"] is None

    # Normal create instance from archived template is REJECTED (409)
    seat_a_id = uuid4()
    actor_a = TableActorContext(
        actor_kind=TableActorKind.HUMAN,
        room_id=fix.room_a_id,
        campaign_id=fix.campaign_a_id,
        session_id=uuid4(),
        seat_id=seat_a_id,
        controlled_seat_ids=(seat_a_id,),
        role="dm",
        is_current_dm=True,
    )
    with pytest.raises(MonsterTemplateArchivedError):
        fix.instance_service.create_from_content(
            actor_a,
            CreateMonsterFromContentInput(content_key=f"custom:{t_id}"),
        )

    # New P6 reference to archived template is REJECTED
    with fix.engine.connect() as conn:
        with pytest.raises(MonsterTemplateArchivedError):
            validate_custom_monster_template_ref(
                conn,
                room_id=fix.room_a_id,
                ref=f"custom:{t_id}",
                previous_ref=None,
            )

        # Unchanged P6 reference to archived template is ALLOWED
        res = validate_custom_monster_template_ref(
            conn,
            room_id=fix.room_a_id,
            ref=f"custom:{t_id}",
            previous_ref=f"custom:{t_id}",
        )
        assert res == t_uuid


# -----------------------------------------------------------------------------
# 6. Room Hard Delete cleans instances and templates
# -----------------------------------------------------------------------------

def test_room_hard_delete_cleans_instances_and_templates(ref_fixture: RefFixture) -> None:
    fix = ref_fixture

    # Create template and instance in Room A
    t = fix.library_service.create_custom(
        fix.ctx_owner_a,
        fix.room_a_id,
        CreateCustomMonsterInput(name="Expendable Beast", armor_class=11, max_hp=20),
    )
    t_uuid = UUID(t.ref.removeprefix("custom:"))
    inst = fix.instance_service.monster_repository.create_instance(
        campaign_id=fix.campaign_a_id,
        name="Expendable Instance",
        rules_snapshot=deepcopy(t.rules),
        custom_template_id=t_uuid,
    )

    # Run hard delete
    workspace_repo = RoomWorkspaceRepository(fix.engine)
    workspace_repo.hard_delete_room(fix.room_a_id)

    # Verify everything in Room A is deleted
    with fix.engine.connect() as conn:
        r_count = conn.scalar(select(sa.func.count()).where(rooms.c.id == fix.room_a_id))
        assert r_count == 0
        t_count = conn.scalar(select(sa.func.count()).where(monster_templates.c.room_id == fix.room_a_id))
        assert t_count == 0
        i_count = conn.scalar(select(sa.func.count()).where(monster_instances.c.id == inst.id))
        assert i_count == 0


# -----------------------------------------------------------------------------
# 7. Stale expected_revision zero side effects
# -----------------------------------------------------------------------------

def test_stale_expected_revision_zero_side_effects(ref_fixture: RefFixture) -> None:
    fix = ref_fixture

    t = fix.library_service.create_custom(
        fix.ctx_owner_a,
        fix.room_a_id,
        CreateCustomMonsterInput(name="Stable Goblin", armor_class=12, max_hp=15),
    )
    t_id = t.ref.removeprefix("custom:")
    t_uuid = UUID(t_id)

    with fix.engine.connect() as conn:
        before_row = dict(
            conn.execute(
                select(monster_templates).where(monster_templates.c.id == t_uuid)
            ).mappings().one()
        )

    # Stale expected_revision on PATCH -> 409
    patch_resp = fix.client.patch(
        f"/api/rooms/{fix.room_a_id}/monster-library/custom/{t_id}",
        json={"expected_revision": 999, "armor_class": 20},
        headers=_auth(fix.token_owner_a),
    )
    assert patch_resp.status_code == 409
    assert patch_resp.json()["error"]["code"] == "monster_template_revision_conflict"

    with fix.engine.connect() as conn:
        after_patch_row = dict(
            conn.execute(
                select(monster_templates).where(monster_templates.c.id == t_uuid)
            ).mappings().one()
        )
    assert before_row == after_patch_row

    # Stale expected_revision on ARCHIVE -> 409
    arch_resp = fix.client.post(
        f"/api/rooms/{fix.room_a_id}/monster-library/custom/{t_id}/archive",
        json={"expected_revision": 999},
        headers=_auth(fix.token_owner_a),
    )
    assert arch_resp.status_code == 409
    assert arch_resp.json()["error"]["code"] == "monster_template_revision_conflict"

    with fix.engine.connect() as conn:
        after_arch_row = dict(
            conn.execute(
                select(monster_templates).where(monster_templates.c.id == t_uuid)
            ).mappings().one()
        )
    assert before_row == after_arch_row

    # Stale expected_revision on COPY -> 409
    copy_resp = fix.client.post(
        f"/api/rooms/{fix.room_a_id}/monster-library/custom/{t_id}/copy",
        json={"expected_revision": 999, "name": "Copy Stale"},
        headers=_auth(fix.token_owner_a),
    )
    assert copy_resp.status_code == 409
    assert copy_resp.json()["error"]["code"] == "monster_template_revision_conflict"

    with fix.engine.connect() as conn:
        after_copy_row = dict(
            conn.execute(
                select(monster_templates).where(monster_templates.c.id == t_uuid)
            ).mappings().one()
        )
        tpl_count = conn.scalar(select(sa.func.count()).where(monster_templates.c.room_id == fix.room_a_id))
        assert tpl_count == 1
    assert before_row == after_copy_row

    # Stale expected_revision on DELETE -> 409
    del_resp = fix.client.delete(
        f"/api/rooms/{fix.room_a_id}/monster-library/custom/{t_id}?expected_revision=999",
        headers=_auth(fix.token_owner_a),
    )
    assert del_resp.status_code == 409
    assert del_resp.json()["error"]["code"] == "monster_template_revision_conflict"

    with fix.engine.connect() as conn:
        after_del_row = dict(
            conn.execute(
                select(monster_templates).where(monster_templates.c.id == t_uuid)
            ).mappings().one()
        )
        tpl_count = conn.scalar(select(sa.func.count()).where(monster_templates.c.room_id == fix.room_a_id))
        assert tpl_count == 1
    assert before_row == after_del_row


# -----------------------------------------------------------------------------
# 8. PostgreSQL focused race test: P6 ref vs delete template
# -----------------------------------------------------------------------------

@pytest.mark.xdist_group("postgres")
@pytest.mark.skipif(
    not POSTGRES_URL,
    reason="P4_POSTGRES_URL is only supplied by the PostgreSQL job",
)
def test_postgres_race_add_p6_ref_vs_delete_template() -> None:
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    try:
        with engine.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))

        cfg = _alembic_config()
        command.upgrade(cfg, "heads")

        room_id = uuid4()
        camp_id = uuid4()
        adv_id = uuid4()
        owner_session_id = uuid4()
        now = datetime.now(timezone.utc)

        with engine.begin() as conn:
            conn.execute(
                insert(rooms).values(
                    id=room_id,
                    code="PGRACE",
                    name="PG Race Room",
                    password_salt=b"salt" * 8,
                    password_hash=b"hash" * 16,
                    owner_key_hash=b"owner" * 6 + b"12",
                    dm_key_hash=b"dm" * 16,
                    created_at=now,
                    updated_at=now,
                )
            )
            conn.execute(
                insert(campaigns).values(
                    id=camp_id,
                    room_id=room_id,
                    name="PG Campaign",
                    ruleset="dnd-5e-2014",
                    status="active",
                    created_at=now,
                    updated_at=now,
                )
            )
            conn.execute(
                insert(adventure_definitions).values(
                    id=adv_id,
                    room_id=room_id,
                    name="PG Adventure",
                    summary="Test Adventure",
                    status="finalized",
                    created_at=now,
                    updated_at=now,
                )
            )

        owner_ctx = RoomAccessContext(
            room_id=room_id,
            access_session_id=owner_session_id,
            authority=RoomAccessAuthority.OWNER,
            display_name="Owner",
        )

        lib_repo = MonsterLibraryRepository(engine)
        monster_repo = MonsterRepository(engine)
        registry = load_default_content_registry()
        localization = load_content_localization_catalog(registry, resolve_content_root())

        table_event_repo = TableEventRepository(engine)
        table_event_service = TableEventService(table_event_repo)

        lib_service = MonsterLibraryService(
            engine=engine,
            repository=lib_repo,
            monster_repository=monster_repo,
            content_registry=registry,
            localization=localization,
            table_event_service=table_event_service,
        )

        # Create template T
        t = lib_service.create_custom(
            owner_ctx,
            room_id,
            CreateCustomMonsterInput(name="Race Dragon", armor_class=18, max_hp=200),
        )
        t_uuid = UUID(t.ref.removeprefix("custom:"))

        barrier = Barrier(2)
        ref_err: Exception | None = None
        del_err: Exception | None = None

        def thread_add_ref() -> None:
            nonlocal ref_err
            try:
                barrier.wait(timeout=10)
                with engine.begin() as conn:
                    # Validate and lock template row
                    validate_custom_monster_template_ref(
                        conn,
                        room_id=room_id,
                        ref=f"custom:{t_uuid}",
                    )
                    time.sleep(0.05)
                    conn.execute(
                        insert(adventure_entries).values(
                            id=uuid4(),
                            adventure_id=adv_id,
                            kind="npc",
                            title="Race NPC",
                            body="Body",
                            data_json={"kind": "npc", "monster_template_ref": f"custom:{t_uuid}"},
                            visibility="public",
                            sort_order=1,
                            created_at=datetime.now(timezone.utc),
                            updated_at=datetime.now(timezone.utc),
                        )
                    )
            except Exception as e:
                ref_err = e

        def thread_delete() -> None:
            nonlocal del_err
            try:
                barrier.wait(timeout=10)
                lib_service.delete_custom(owner_ctx, room_id, t_uuid, expected_revision=1)
            except Exception as e:
                del_err = e

        with ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(thread_add_ref)
            f2 = executor.submit(thread_delete)
            f1.result()
            f2.result()

        # Outcome validation:
        # Either add_ref won: ref created, delete raised MonsterTemplateReferencedError
        # OR delete won: template deleted, add_ref raised MonsterTemplateNotFoundError
        if ref_err is None:
            # Ref succeeded -> delete MUST have failed with referenced error
            assert isinstance(del_err, MonsterTemplateReferencedError)
            with engine.connect() as conn:
                tpl_exists = conn.scalar(select(sa.func.count()).where(monster_templates.c.id == t_uuid))
                assert tpl_exists == 1
                adv_count = conn.scalar(select(sa.func.count()).where(adventure_entries.c.adventure_id == adv_id))
                assert adv_count == 1
        else:
            # Delete succeeded -> ref MUST have failed with not found error
            assert del_err is None
            assert isinstance(ref_err, MonsterTemplateNotFoundError)
            with engine.connect() as conn:
                tpl_exists = conn.scalar(select(sa.func.count()).where(monster_templates.c.id == t_uuid))
                assert tpl_exists == 0
                adv_count = conn.scalar(select(sa.func.count()).where(adventure_entries.c.adventure_id == adv_id))
                assert adv_count == 0
    finally:
        engine.dispose()


# -----------------------------------------------------------------------------
# 9. Durable mutation history blocks template delete (Fix 3)
# -----------------------------------------------------------------------------

def test_mutation_history_blocks_template_delete(ref_fixture: RefFixture) -> None:
    fix = ref_fixture

    # 1. Create custom template T in Room A
    t = fix.library_service.create_custom(
        fix.ctx_owner_a,
        fix.room_a_id,
        CreateCustomMonsterInput(name="Mutated Template NPC", armor_class=13, max_hp=25),
    )
    t_id = t.ref.removeprefix("custom:")
    t_uuid = UUID(t_id)

    runtime_repo = CampaignRuntimeRepository(fix.engine)
    mutation_repo = CampaignWorldMutationRepository(fix.engine)
    link_repo = CampaignAdventureLinkRepository(fix.engine)
    now = datetime.now(timezone.utc)

    # 2. Create runtime NPC with custom:<id>
    with fix.engine.begin() as conn:
        view, _ = execute_create_entry_in_transaction(
            conn,
            room_id=fix.room_a_id,
            campaign_id=fix.campaign_a_id,
            payload=RuntimeWorldEntryCreate(
                kind="npc",
                title="Historical NPC",
                body="Has monster ref initially.",
                state={"monster_template_ref": f"custom:{t_id}"},
                visibility="public",
            ),
            idempotency_key="create-hist-npc-1",
            actor_kind="human",
            actor_id=fix.ctx_owner_a.access_session_id,
            now=now,
            runtime_repo=runtime_repo,
            mutation_repo=mutation_repo,
            link_repo=link_repo,
        )

        # 3. Change runtime NPC to no ref
        execute_update_entry_in_transaction(
            conn,
            room_id=fix.room_a_id,
            campaign_id=fix.campaign_a_id,
            entry_id=view.id,
            patch=RuntimeWorldEntryPatch(
                expected_revision=1,
                state={"monster_template_ref": None},
            ),
            idempotency_key="update-hist-npc-1",
            actor_kind="human",
            actor_id=fix.ctx_owner_a.access_session_id,
            now=now,
            runtime_repo=runtime_repo,
            mutation_repo=mutation_repo,
            link_repo=link_repo,
        )

    # 4. Attempt to delete template -> 409 monster_template_referenced
    del_r = fix.client.delete(
        f"/api/rooms/{fix.room_a_id}/monster-library/custom/{t_id}?expected_revision=1",
        headers=_auth(fix.token_owner_a),
    )
    assert del_r.status_code == 409
    assert del_r.json()["error"]["code"] == "monster_template_referenced"

