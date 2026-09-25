from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect, text

from tests.migration_support import migration_heads
from tests.test_p4f_postgres_migration import _seed_room_and_campaign


POSTGRES_URL = os.environ.get("P4_POSTGRES_URL")
pytestmark = [
    pytest.mark.xdist_group("postgres"),
    pytest.mark.skipif(
        not POSTGRES_URL,
        reason="P4_POSTGRES_URL is only supplied by the P4 PostgreSQL job",
    ),
]
SERVER_ROOT = Path(__file__).resolve().parents[1]
M06B_PARENT = "0033_p6e_adventure_imports"


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


def _revision_set() -> set[str]:
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        with engine.connect() as connection:
            return set(
                connection.execute(text("SELECT version_num FROM alembic_version")).scalars()
            )
    finally:
        engine.dispose()


def test_m06b_real_postgres_upgrade_downgrade_upgrade() -> None:
    _reset()
    cfg = _config()
    command.upgrade(cfg, "character@head")
    command.upgrade(cfg, M06B_PARENT)
    assert M06B_PARENT in _revision_set()

    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        inspector = inspect(engine)
        cols_before = {c["name"]: c for c in inspector.get_columns("session_events")}
        assert "acting_ai_controller_grant_id" not in cols_before
        assert "acting_grant_generation" not in cols_before

        room_id = uuid4()
        campaign_id = uuid4()
        seat_id = uuid4()
        session_id = uuid4()
        event_id = uuid4()

        with engine.begin() as connection:
            _seed_room_and_campaign(connection, room_id=room_id, campaign_id=campaign_id)
            connection.execute(
                text(
                    "INSERT INTO campaign_seats (id, campaign_id, role, controller_kind) "
                    "VALUES (:seat_id, :campaign_id, 'dm', 'none')"
                ),
                {"seat_id": seat_id, "campaign_id": campaign_id},
            )
            connection.execute(
                text(
                    "INSERT INTO sessions (id, campaign_id, status, dm_seat_id, dm_controller_kind, started_at) "
                    "VALUES (:session_id, :campaign_id, 'active', :seat_id, 'none', now())"
                ),
                {"session_id": session_id, "campaign_id": campaign_id, "seat_id": seat_id},
            )
            connection.execute(
                text(
                    "INSERT INTO session_events (id, session_id, seq, kind, visibility, payload_version, payload) "
                    "VALUES (:event_id, :session_id, 1, 'stage.updated', 'public', 1, '{}')"
                ),
                {"event_id": event_id, "session_id": session_id},
            )

        command.upgrade(cfg, "heads")
        assert _revision_set() == set(migration_heads(cfg).values())

        inspector = inspect(engine)
        cols_after = {c["name"]: c for c in inspector.get_columns("session_events")}
        assert "acting_ai_controller_grant_id" in cols_after
        assert cols_after["acting_ai_controller_grant_id"]["nullable"] is True
        assert "acting_grant_generation" in cols_after
        assert cols_after["acting_grant_generation"]["nullable"] is True

        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT acting_ai_controller_grant_id, acting_grant_generation "
                    "FROM session_events WHERE id = :id"
                ),
                {"id": event_id},
            ).mappings().one()
            assert row["acting_ai_controller_grant_id"] is None
            assert row["acting_grant_generation"] is None

        command.downgrade(cfg, M06B_PARENT)
        assert M06B_PARENT in _revision_set()

        inspector = inspect(engine)
        cols_downgrade = {c["name"]: c for c in inspector.get_columns("session_events")}
        assert "acting_ai_controller_grant_id" not in cols_downgrade
        assert "acting_grant_generation" not in cols_downgrade

        with engine.connect() as connection:
            row = connection.execute(
                text("SELECT id, seq, kind FROM session_events WHERE id = :id"),
                {"id": event_id},
            ).mappings().one()
            assert row["id"] == event_id

        command.upgrade(cfg, "heads")
        assert _revision_set() == set(migration_heads(cfg).values())

        inspector = inspect(engine)
        cols_final = {c["name"]: c for c in inspector.get_columns("session_events")}
        assert "acting_ai_controller_grant_id" in cols_final
        assert "acting_grant_generation" in cols_final

        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT acting_ai_controller_grant_id, acting_grant_generation "
                    "FROM session_events WHERE id = :id"
                ),
                {"id": event_id},
            ).mappings().one()
            assert row["acting_ai_controller_grant_id"] is None
            assert row["acting_grant_generation"] is None
    finally:
        engine.dispose()
