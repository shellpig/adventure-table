"""M03-B B.1 — the builder_provenance column, on every supported backend.

The spec requires Postgres up/down to be green in M03-B (SQLite is only
guaranteed from M03-D). SQLite runs unconditionally here because it needs no
service; Postgres runs whenever ``M03B_POSTGRES_URL`` names a reachable
database, which CI supplies through a service container.
"""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import (
    Column,
    Integer,
    JSON,
    MetaData,
    String,
    Table,
    Uuid,
    create_engine,
    inspect,
    insert,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB


REVISION = "0007_m03b_builder_provenance"
PREDECESSOR = "0006_character_archive"

POSTGRES_URL = os.getenv("M03B_POSTGRES_URL")

# The pre-0007 shape of the two tables this migration touches. Declared locally
# so the seeded legacy row cannot accidentally carry the new column.
_legacy_metadata = MetaData()
_json = JSON().with_variant(JSONB(), "postgresql")
_characters = Table(
    "characters",
    _legacy_metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("name", String(200), nullable=False),
    Column("ruleset", String(80), nullable=False),
)
_versions = Table(
    "character_versions",
    _legacy_metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("character_id", Uuid(as_uuid=True), nullable=False),
    Column("version_no", Integer, nullable=False),
    Column("build_payload", _json, nullable=False),
    Column("version_kind", String(32), nullable=False),
)


def _columns(url: str) -> dict[str, dict]:
    engine = create_engine(url)
    try:
        return {
            column["name"]: column
            for column in inspect(engine).get_columns("character_versions")
        }
    finally:
        engine.dispose()


def _seed_legacy_version(url: str) -> None:
    engine = create_engine(url)
    try:
        character_id = uuid4()
        with engine.begin() as connection:
            connection.execute(
                insert(_characters).values(
                    id=character_id, name="M03-B legacy", ruleset="dnd5e-2014"
                )
            )
            connection.execute(
                insert(_versions).values(
                    id=uuid4(),
                    character_id=character_id,
                    version_no=1,
                    build_payload={},
                    version_kind="legacy",
                )
            )
    finally:
        engine.dispose()


def _provenance_values(url: str) -> list:
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            return list(
                connection.scalars(
                    select(text("builder_provenance")).select_from(text("character_versions"))
                )
            )
    finally:
        engine.dispose()


def _row_count(url: str) -> int:
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            return connection.scalar(text("select count(*) from character_versions"))
    finally:
        engine.dispose()


def _reset_postgres(url: str) -> None:
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(text("drop schema public cascade"))
            connection.execute(text("create schema public"))
    finally:
        engine.dispose()


@pytest.fixture(params=["sqlite", "postgresql"])
def migration_url(request, tmp_path: Path, monkeypatch) -> str:
    if request.param == "postgresql":
        if not POSTGRES_URL:
            pytest.skip("M03B_POSTGRES_URL is not set")
        _reset_postgres(POSTGRES_URL)
        # env.py resolves the URL through app.paths on every alembic run, and
        # ADVENTURE_TABLE_DATABASE_PATH would otherwise force SQLite.
        monkeypatch.delenv("ADVENTURE_TABLE_DATABASE_PATH", raising=False)
        monkeypatch.setattr("app.paths.resolve_database_url", lambda: POSTGRES_URL)
        return POSTGRES_URL

    database_path = tmp_path / "m03b-migration.sqlite3"
    monkeypatch.setenv("ADVENTURE_TABLE_DATABASE_PATH", str(database_path))
    return f"sqlite+pysqlite:///{database_path.as_posix()}"


def test_m03b_migration_adds_nullable_provenance_and_downgrades_cleanly(
    migration_url: str,
) -> None:
    config = Config("alembic.ini")

    command.upgrade(config, PREDECESSOR)
    _seed_legacy_version(migration_url)
    assert _row_count(migration_url) == 1

    command.upgrade(config, REVISION)
    upgraded = _columns(migration_url)
    assert "builder_provenance" in upgraded
    assert upgraded["builder_provenance"]["nullable"] is True
    # Rows that predate the migration must stay NULL: only Confirm operations
    # from M03-B onward have an exact BuilderDraftPayload snapshot to preserve.
    assert _provenance_values(migration_url) == [None]

    command.downgrade(config, PREDECESSOR)
    assert "builder_provenance" not in _columns(migration_url)
    assert _row_count(migration_url) == 1

    command.upgrade(config, REVISION)
    assert "builder_provenance" in _columns(migration_url)
    assert _provenance_values(migration_url) == [None]


def test_m03b_migration_contains_no_legacy_backfill() -> None:
    source = Path("alembic/versions/0007_m03b_builder_provenance.py").read_text(
        encoding="utf-8"
    )
    lowered = source.lower()
    assert "update character_versions" not in lowered
    assert "execute(" not in lowered
    assert "nullable=true" in lowered.replace(" ", "")
