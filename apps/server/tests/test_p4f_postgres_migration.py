from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError


POSTGRES_URL = os.environ.get("P4_POSTGRES_URL")
pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="P4_POSTGRES_URL is only supplied by the P4 PostgreSQL job",
)
SERVER_ROOT = Path(__file__).resolve().parents[1]
P4F_PARENT = "0026_p4e_monster_concentration"
P4F_HEAD = "0029_p4f_roll_request_auto_fail"


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
            return set(connection.execute(text("SELECT version_num FROM alembic_version")).scalars())
    finally:
        engine.dispose()


def _seed_room_and_campaign(connection, *, room_id, campaign_id) -> None:
    """Minimal parent rows for a monster_instances insert; every NOT NULL column is filled."""
    connection.execute(
        text(
            "INSERT INTO rooms (id, code, name, password_salt, password_hash, owner_key_hash, dm_key_hash, "
            "created_at, updated_at) VALUES (:room_id, :code, 'test room', :salt, :hash, :owner, :dm, now(), now())"
        ),
        {"room_id": room_id, "code": str(room_id)[:10], "salt": bytes(32), "hash": bytes(64),
         "owner": bytes(32), "dm": bytes(32)},
    )
    connection.execute(
        text(
            "INSERT INTO campaigns (id, room_id, name, ruleset, status) "
            "VALUES (:campaign_id, :room_id, 'test campaign', 'dnd5e-2014', 'active')"
        ),
        {"campaign_id": campaign_id, "room_id": room_id},
    )


def _assert_surrendered_status_accepted() -> None:
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        room_id = uuid4()
        campaign_id = uuid4()
        instance_id = uuid4()
        with engine.begin() as connection:
            _seed_room_and_campaign(connection, room_id=room_id, campaign_id=campaign_id)
            connection.execute(
                text(
                    "INSERT INTO monster_instances ("
                    "id, campaign_id, name, rules_snapshot, current_hp, temp_hp, "
                    "conditions, effects, combat_status, resources, visibility"
                    ") VALUES ("
                    ":id, :campaign_id, 'Goblin', '{}', 10, 0, '[]', '[]', 'surrendered', '{}', 'public'"
                    ")"
                ),
                {"id": instance_id, "campaign_id": campaign_id},
            )
    finally:
        engine.dispose()


def _assert_surrendered_status_rejected() -> None:
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        room_id = uuid4()
        campaign_id = uuid4()
        instance_id = uuid4()
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                _seed_room_and_campaign(connection, room_id=room_id, campaign_id=campaign_id)
                connection.execute(
                    text(
                        "INSERT INTO monster_instances ("
                        "id, campaign_id, name, rules_snapshot, current_hp, temp_hp, "
                        "conditions, effects, combat_status, resources, visibility"
                        ") VALUES ("
                        ":id, :campaign_id, 'Goblin', '{}', 10, 0, '[]', '[]', 'surrendered', '{}', 'public'"
                        ")"
                    ),
                    {"id": instance_id, "campaign_id": campaign_id},
                )
    finally:
        engine.dispose()


def test_p4f_real_postgres_upgrade_and_downgrade_from_p4e_parent() -> None:
    _reset()
    command.upgrade(_config(), P4F_PARENT)
    assert P4F_HEAD not in _revision_set()
    _assert_surrendered_status_rejected()

    _reset()
    command.upgrade(_config(), "heads")
    assert P4F_HEAD in _revision_set()
    _assert_surrendered_status_accepted()

    _reset()
    command.upgrade(_config(), "heads")
    command.downgrade(_config(), P4F_PARENT)
    assert P4F_HEAD not in _revision_set()
    _assert_surrendered_status_rejected()


def test_p4f_schema_survives_fresh_upgrade_to_heads() -> None:
    _reset()
    command.upgrade(_config(), "heads")
    assert P4F_HEAD in _revision_set()
    _assert_surrendered_status_accepted()


def test_p4f_real_postgres_monster_reveal_state_upgrade_and_downgrade() -> None:
    _reset()
    command.upgrade(_config(), "0027_p4f_monster_outcome")
    assert "0028_p4f_monster_reveal_state" not in _revision_set()
    _assert_surrendered_status_accepted()

    command.upgrade(_config(), "0028_p4f_monster_reveal_state")
    assert "0028_p4f_monster_reveal_state" in _revision_set()

    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        with engine.connect() as connection:
            value = connection.execute(
                text("SELECT reveal_state FROM monster_instances WHERE combat_status = 'surrendered'")
            ).scalar()
            assert value == {} or value == "{}"
    finally:
        engine.dispose()

    command.downgrade(_config(), "0027_p4f_monster_outcome")
    assert "0028_p4f_monster_reveal_state" not in _revision_set()
    engine = create_engine(POSTGRES_URL)
    try:
        with pytest.raises(Exception):
            with engine.connect() as connection:
                connection.execute(text("SELECT reveal_state FROM monster_instances")).all()
    finally:
        engine.dispose()


def test_p4f_real_postgres_roll_request_auto_fail_upgrade_and_downgrade() -> None:
    _reset()
    command.upgrade(_config(), "0028_p4f_monster_reveal_state")
    assert "0029_p4f_roll_request_auto_fail" not in _revision_set()

    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        with pytest.raises(Exception):
            with engine.connect() as connection:
                connection.execute(text("SELECT auto_fail FROM roll_requests")).all()
    finally:
        engine.dispose()

    command.upgrade(_config(), "heads")
    assert "0029_p4f_roll_request_auto_fail" in _revision_set()

    engine = create_engine(POSTGRES_URL)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT auto_fail FROM roll_requests")).all()
            col = connection.execute(
                text(
                    "SELECT column_name, is_nullable, column_default "
                    "FROM information_schema.columns "
                    "WHERE table_name = 'roll_requests' AND column_name = 'auto_fail'"
                )
            ).one_or_none()
            assert col is not None
            assert col[1] == "NO"
            assert "false" in str(col[2]).lower()
    finally:
        engine.dispose()

    command.downgrade(_config(), "0028_p4f_monster_reveal_state")
    assert "0029_p4f_roll_request_auto_fail" not in _revision_set()
    engine = create_engine(POSTGRES_URL)
    try:
        with pytest.raises(Exception):
            with engine.connect() as connection:
                connection.execute(text("SELECT auto_fail FROM roll_requests")).all()
    finally:
        engine.dispose()

