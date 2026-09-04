from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


REVISION = "0007_m03b_builder_provenance"
PREDECESSOR = "0006_character_archive"


def _columns(database_path: Path) -> dict[str, dict]:
    engine = create_engine(f"sqlite+pysqlite:///{database_path.as_posix()}")
    try:
        return {
            column["name"]: column
            for column in inspect(engine).get_columns("character_versions")
        }
    finally:
        engine.dispose()


def test_m03b_migration_adds_nullable_provenance_and_downgrades_cleanly(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "m03b-migration.sqlite3"
    monkeypatch.setenv("ADVENTURE_TABLE_DATABASE_PATH", str(database_path))
    config = Config("alembic.ini")

    command.upgrade(config, REVISION)
    upgraded = _columns(database_path)
    assert "builder_provenance" in upgraded
    assert upgraded["builder_provenance"]["nullable"] is True

    command.downgrade(config, PREDECESSOR)
    downgraded = _columns(database_path)
    assert "builder_provenance" not in downgraded

    command.upgrade(config, REVISION)
    assert "builder_provenance" in _columns(database_path)


def test_m03b_migration_contains_no_legacy_backfill() -> None:
    source = Path("alembic/versions/0007_m03b_builder_provenance.py").read_text(
        encoding="utf-8"
    )
    lowered = source.lower()
    assert "update character_versions" not in lowered
    assert "execute(" not in lowered
    assert "nullable=true" in lowered.replace(" ", "")
