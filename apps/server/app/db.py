from __future__ import annotations

from sqlalchemy import MetaData, create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings

metadata = MetaData()


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
