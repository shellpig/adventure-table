from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.db import metadata
from app.paths import resolve_database_url
from app.persistence import characters as _character_tables  # noqa: F401
from app.persistence import builder_drafts as _builder_draft_tables  # noqa: F401
from app.persistence import character_imports as _character_import_tables  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _target_database_url() -> str:
    """Resolve which database this run migrates.

    `alembic.ini` always carries a URL, so a caller that only rewrites
    `sqlalchemy.url` cannot be told apart from the file default — and used to be
    silently overridden by the shared resolver, migrating a different database
    than the caller asked for. Callers that own their own URL declare it here.
    """

    override = config.attributes.get("target_database_url")
    return str(override) if override else resolve_database_url()


config.set_main_option("sqlalchemy.url", _target_database_url())
target_metadata = metadata


def run_migrations_offline() -> None:
    context.configure(
        url=_target_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
