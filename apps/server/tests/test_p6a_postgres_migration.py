from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

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
P6A_PARENT = "0030_p4f_entry_dodging"
P6A_TABLES = {
    "room_assets",
    "adventure_definitions",
    "adventure_entries",
    "adventure_entry_assets",
    "campaign_adventure_links",
}


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


def test_p6a_real_postgres_upgrade_and_downgrade_from_p4f_parent() -> None:
    _reset()
    command.upgrade(_config(), P6A_PARENT)
    assert P6A_PARENT in _revision_set()

    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        table_names = set(inspect(engine).get_table_names())
        assert P6A_TABLES.isdisjoint(table_names)

        command.upgrade(_config(), "heads")
        assert _revision_set() == set(migration_heads(_config()).values())

        table_names = set(inspect(engine).get_table_names())
        assert P6A_TABLES.issubset(table_names)

        command.downgrade(_config(), P6A_PARENT)
        assert P6A_PARENT in _revision_set()

        table_names = set(inspect(engine).get_table_names())
        assert P6A_TABLES.isdisjoint(table_names)
    finally:
        engine.dispose()


def test_p6a_campaign_can_link_two_adventures() -> None:
    _reset()
    command.upgrade(_config(), "heads")
    assert _revision_set() == set(migration_heads(_config()).values())

    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        room_id = uuid4()
        campaign_id = uuid4()
        adv_id1 = uuid4()
        adv_id2 = uuid4()
        with engine.begin() as connection:
            _seed_room_and_campaign(connection, room_id=room_id, campaign_id=campaign_id)
            connection.execute(
                text(
                    "INSERT INTO adventure_definitions ("
                    "id, room_id, name, status"
                    ") VALUES ("
                    ":id, :room_id, 'Adventure 1', 'finalized'"
                    ")"
                ),
                {"id": adv_id1, "room_id": room_id},
            )
            connection.execute(
                text(
                    "INSERT INTO adventure_definitions ("
                    "id, room_id, name, status"
                    ") VALUES ("
                    ":id, :room_id, 'Adventure 2', 'finalized'"
                    ")"
                ),
                {"id": adv_id2, "room_id": room_id},
            )
            connection.execute(
                text(
                    "INSERT INTO campaign_adventure_links ("
                    "campaign_id, adventure_id, sort_order"
                    ") VALUES ("
                    ":campaign_id, :adv_id1, 0"
                    "), ("
                    ":campaign_id, :adv_id2, 1"
                    ")"
                ),
                {"campaign_id": campaign_id, "adv_id1": adv_id1, "adv_id2": adv_id2},
            )
            count = connection.execute(
                text("SELECT count(*) FROM campaign_adventure_links WHERE campaign_id = :campaign_id"),
                {"campaign_id": campaign_id},
            ).scalar()
            assert count == 2

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO campaign_adventure_links ("
                        "campaign_id, adventure_id, sort_order"
                        ") VALUES (:campaign_id, :adv_id1, 2)"
                    ),
                    {"campaign_id": campaign_id, "adv_id1": adv_id1},
                )
    finally:
        engine.dispose()


def test_p6a_source_document_visibility_check_constraint() -> None:
    _reset()
    command.upgrade(_config(), "heads")
    assert _revision_set() == set(migration_heads(_config()).values())

    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        room_id = uuid4()
        campaign_id = uuid4()
        with engine.begin() as connection:
            _seed_room_and_campaign(connection, room_id=room_id, campaign_id=campaign_id)
            connection.execute(
                text(
                    "INSERT INTO room_assets ("
                    "id, room_id, kind, storage_key, original_filename, mime_type, size_bytes, sha256, visibility"
                    ") VALUES ("
                    ":id, :room_id, 'source_document', 'key1', 'doc.pdf', 'application/pdf', 100, 'sha256_1', 'room'"
                    ")"
                ),
                {"id": uuid4(), "room_id": room_id},
            )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO room_assets ("
                        "id, room_id, kind, storage_key, original_filename, mime_type, size_bytes, sha256, visibility"
                        ") VALUES ("
                        ":id, :room_id, 'video', 'key2', 'doc.mp4', 'video/mp4', 100, 'sha256_2', 'room'"
                        ")"
                    ),
                    {"id": uuid4(), "room_id": room_id},
                )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO room_assets ("
                        "id, room_id, kind, storage_key, original_filename, mime_type, size_bytes, sha256, visibility"
                        ") VALUES ("
                        ":id, :room_id, 'image', 'key3', 'img.png', 'image/png', 100, 'sha256_3', 'public'"
                        ")"
                    ),
                    {"id": uuid4(), "room_id": room_id},
                )
    finally:
        engine.dispose()
