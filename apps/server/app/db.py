from __future__ import annotations

import sqlite3

from sqlalchemy import Engine, MetaData, create_engine, event, text
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings

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


def database_is_ready(database_url: str | None = None) -> bool:
    """Return True only when a real database connection can execute SELECT 1."""
    engine = None
    try:
        engine = create_engine(
            database_url or settings.database_url,
            pool_pre_ping=True,
            connect_args={"connect_timeout": 2}
            if (database_url or settings.database_url).startswith("postgresql")
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
