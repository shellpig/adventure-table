from __future__ import annotations

import sqlite3

from sqlalchemy import Engine, MetaData, create_engine, event, text
from sqlalchemy.exc import SQLAlchemyError

from app.paths import resolve_database_url

metadata = MetaData()


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    """Enforce SQLite foreign-key semantics on every SQLAlchemy Engine connection."""

    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def create_database_engine(
    database_url: str | None = None,
    *,
    pool_pre_ping: bool = True,
    connect_args: dict[str, object] | None = None,
) -> Engine:
    """Create the shared runtime engine while preserving the database URL SSOT."""

    return create_engine(
        database_url or resolve_database_url(),
        pool_pre_ping=pool_pre_ping,
        connect_args=connect_args or {},
    )


def database_is_ready(database_url: str | None = None) -> bool:
    """Return True only when a real database connection can execute SELECT 1."""
    engine = None
    resolved_url = database_url or resolve_database_url()
    try:
        engine = create_database_engine(
            resolved_url,
            pool_pre_ping=True,
            connect_args={"connect_timeout": 2}
            if resolved_url.startswith("postgresql")
            else {},
        )
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except (SQLAlchemyError, ModuleNotFoundError, OSError):
        return False
    finally:
        if engine is not None:
            engine.dispose()
