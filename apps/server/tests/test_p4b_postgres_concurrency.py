from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, func, select, text

from app.domain.combat.lifecycle import ActiveCombatExistsError, StartCombatInput
from app.persistence.combat.tables import combats
import tests.test_p4b_combat_lifecycle as support


POSTGRES_URL = os.environ.get("P4_POSTGRES_URL")
pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="P4_POSTGRES_URL is only supplied by the P4 PostgreSQL job",
)
SERVER_ROOT = Path(__file__).resolve().parents[1]


def _config() -> Config:
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SERVER_ROOT / "alembic"))
    assert POSTGRES_URL is not None
    config.set_main_option("sqlalchemy.url", POSTGRES_URL)
    config.attributes["target_database_url"] = POSTGRES_URL
    return config


def _reset() -> None:
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
    finally:
        engine.dispose()
    command.upgrade(_config(), "heads")


def test_concurrent_start_quick_combat_has_one_database_winner(monkeypatch) -> None:
    _reset()
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    # Reuse the full P4-B Room/Campaign/Session fixture, but point it at the real
    # PostgreSQL database that was just migrated instead of its default SQLite.
    monkeypatch.setattr(support, "create_engine", lambda *_args, **_kwargs: engine)
    table = support._setup()
    try:
        def start(key: str):
            try:
                view = table.combat.start_quick_combat(
                    table.dm_actor,
                    StartCombatInput(idempotency_key=key),
                )
                return ("ok", view.id)
            except ActiveCombatExistsError:
                return ("conflict", None)

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(start, ("concurrent-a", "concurrent-b")))

        assert sorted(result[0] for result in results) == ["conflict", "ok"]
        with engine.connect() as connection:
            active_count = connection.scalar(
                select(func.count()).select_from(combats).where(
                    combats.c.campaign_id == table.campaign_id,
                    combats.c.status.in_(("initiative_pending", "running")),
                )
            )
        assert active_count == 1
    finally:
        engine.dispose()
