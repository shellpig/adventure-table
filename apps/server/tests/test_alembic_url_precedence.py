"""Alembic must migrate the database the caller asked for.

`alembic.ini` ships a default `sqlalchemy.url`, so env.py cannot tell a caller's
override apart from the file default by reading the main option alone. It used to
resolve the shared application URL unconditionally, which meant a caller that
pointed a Config at another database got a successful-looking upgrade applied
somewhere else entirely — the failure mode that made the PostgreSQL gates depend
on DATABASE_URL happening to match.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

SERVER_ROOT = Path(__file__).resolve().parents[1]


def _config(url: str | None) -> Config:
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SERVER_ROOT / "alembic"))
    if url is not None:
        config.set_main_option("sqlalchemy.url", url)
        config.attributes["target_database_url"] = url
    return config


def test_declared_target_database_url_wins_over_the_shared_resolver(
    tmp_path: Path,
    monkeypatch,
) -> None:
    declared = tmp_path / "declared.sqlite3"
    resolver = tmp_path / "resolver.sqlite3"
    # What resolve_database_url() would return if nothing were declared.
    monkeypatch.setenv("ADVENTURE_TABLE_DATABASE_PATH", str(resolver))

    command.upgrade(
        _config(f"sqlite+pysqlite:///{declared.as_posix()}"),
        "character@head",
    )

    assert declared.exists()
    declared_tables = inspect(
        create_engine(f"sqlite+pysqlite:///{declared.as_posix()}")
    ).get_table_names()
    assert "characters" in declared_tables
    assert "alembic_version" in declared_tables
    # The resolver's database must not have been touched at all.
    assert not resolver.exists()


def test_without_a_declared_url_the_shared_resolver_still_applies(
    tmp_path: Path,
    monkeypatch,
) -> None:
    resolver = tmp_path / "resolver-only.sqlite3"
    monkeypatch.setenv("ADVENTURE_TABLE_DATABASE_PATH", str(resolver))

    command.upgrade(_config(None), "character@head")

    assert resolver.exists()
    assert "characters" in inspect(
        create_engine(f"sqlite+pysqlite:///{resolver.as_posix()}")
    ).get_table_names()
