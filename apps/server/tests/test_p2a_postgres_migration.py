from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import UUID

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, inspect, text


POSTGRES_URL = os.environ.get("P2_POSTGRES_URL")
pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="P2_POSTGRES_URL is only supplied by the P2 Non-E2E PostgreSQL job",
)
SERVER_ROOT = Path(__file__).resolve().parents[1]
BRANCH_POINT = "0008_m03c_import_records"
CHARACTER_HEAD = "0009_p2a_character_head"
WEB_HEAD = "0011_p2b_room_character_workspace"


def _alembic_config() -> Config:
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SERVER_ROOT / "alembic"))
    assert POSTGRES_URL is not None
    config.set_main_option("sqlalchemy.url", POSTGRES_URL)
    return config


def _reset_database() -> None:
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
    finally:
        engine.dispose()


def _revision_set() -> set[str]:
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        with engine.connect() as connection:
            return set(connection.execute(text("SELECT version_num FROM alembic_version")).scalars())
    finally:
        engine.dispose()


def _expected_heads() -> set[str]:
    scripts = ScriptDirectory.from_config(_alembic_config())
    return set(scripts.get_heads())


def _seed_legacy_m03_data() -> None:
    assert POSTGRES_URL is not None
    character_id = UUID("10000000-0000-4000-8000-000000000001")
    version_one = UUID("10000000-0000-4000-8000-000000000011")
    version_two = UUID("10000000-0000-4000-8000-000000000012")
    create_draft = UUID("10000000-0000-4000-8000-000000000021")
    versioned_draft = UUID("10000000-0000-4000-8000-000000000022")
    import_record = UUID("10000000-0000-4000-8000-000000000031")
    build_one = json.dumps({"fixture": "legacy-v1", "level": 1}, sort_keys=True)
    build_two = json.dumps({"fixture": "legacy-v2", "level": 2}, sort_keys=True)
    provenance = json.dumps({"draft": "confirmed-v2"}, sort_keys=True)
    current_state = json.dumps({"hp": {"current": 17, "temp": 3}}, sort_keys=True)
    create_payload = json.dumps({"basic": {"name": "Open Create Draft"}}, sort_keys=True)
    versioned_payload = json.dumps({"basic": {"name": "Versioned Draft"}}, sort_keys=True)

    engine = create_engine(POSTGRES_URL)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO characters (id, name, ruleset, current_version_id)
                    VALUES (:id, 'P2 legacy fixture', 'dnd5e-2014', NULL)
                    """
                ),
                {"id": character_id},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO character_versions
                        (id, character_id, version_no, build_payload, version_kind,
                         parent_version_id, superseded_by_version_id, change_note,
                         builder_provenance)
                    VALUES
                        (:v1, :character_id, 1, CAST(:build_one AS jsonb), 'create',
                         NULL, :v2, 'legacy create', NULL),
                        (:v2, :character_id, 2, CAST(:build_two AS jsonb), 'level_up',
                         :v1, NULL, 'legacy level up', CAST(:provenance AS jsonb))
                    """
                ),
                {
                    "v1": version_one,
                    "v2": version_two,
                    "character_id": character_id,
                    "build_one": build_one,
                    "build_two": build_two,
                    "provenance": provenance,
                },
            )
            connection.execute(
                text("UPDATE characters SET current_version_id = :v2 WHERE id = :id"),
                {"v2": version_two, "id": character_id},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO character_states (character_id, state_payload)
                    VALUES (:character_id, CAST(:payload AS jsonb))
                    """
                ),
                {"character_id": character_id, "payload": current_state},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO character_build_drafts
                        (id, mode, character_id, base_version_id, revision, draft_payload)
                    VALUES
                        (:create_id, 'create', NULL, NULL, 1, CAST(:create_payload AS jsonb)),
                        (:versioned_id, 'level_up', :character_id, :base_version_id, 4,
                         CAST(:versioned_payload AS jsonb))
                    """
                ),
                {
                    "create_id": create_draft,
                    "versioned_id": versioned_draft,
                    "character_id": character_id,
                    "base_version_id": version_two,
                    "create_payload": create_payload,
                    "versioned_payload": versioned_payload,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO character_import_records
                        (id, character_id, draft_id, source_character_id,
                         source_export_id, landing_mode)
                    VALUES
                        (:id, :character_id, NULL, :source_character_id,
                         :source_export_id, 'create')
                    """
                ),
                {
                    "id": import_record,
                    "character_id": character_id,
                    "source_character_id": UUID("20000000-0000-4000-8000-000000000001"),
                    "source_export_id": UUID("20000000-0000-4000-8000-000000000002"),
                },
            )
    finally:
        engine.dispose()


def _legacy_payload_snapshot() -> dict[str, list[dict[str, object]]]:
    assert POSTGRES_URL is not None
    queries = {
        "characters": "SELECT * FROM characters ORDER BY id",
        "versions": "SELECT * FROM character_versions ORDER BY version_no",
        "states": "SELECT * FROM character_states ORDER BY character_id",
        "drafts": "SELECT * FROM character_build_drafts ORDER BY id",
        "imports": "SELECT * FROM character_import_records ORDER BY id",
    }
    engine = create_engine(POSTGRES_URL)
    try:
        with engine.connect() as connection:
            return {
                name: [dict(row) for row in connection.execute(text(query)).mappings()]
                for name, query in queries.items()
            }
    finally:
        engine.dispose()


def test_fresh_web_postgres_upgrade_heads_and_readiness() -> None:
    _reset_database()
    command.upgrade(_alembic_config(), "heads")

    assert _expected_heads() == {CHARACTER_HEAD, WEB_HEAD}
    assert _revision_set() == {CHARACTER_HEAD, WEB_HEAD}

    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert {
        "characters",
        "character_versions",
        "character_states",
        "character_build_drafts",
        "character_import_records",
        "rooms",
        "room_access_sessions",
        "room_characters",
        "room_builder_drafts",
    } <= tables

    from app.main import app

    response = TestClient(app).get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_legacy_m03_postgres_upgrade_heads_preserves_character_payloads() -> None:
    _reset_database()
    command.upgrade(_alembic_config(), BRANCH_POINT)
    assert _revision_set() == {BRANCH_POINT}
    _seed_legacy_m03_data()
    before = _legacy_payload_snapshot()

    command.upgrade(_alembic_config(), "heads")

    assert _revision_set() == {CHARACTER_HEAD, WEB_HEAD}
    assert _legacy_payload_snapshot() == before
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert {
        "rooms",
        "room_access_sessions",
        "room_characters",
        "room_builder_drafts",
    } <= tables
