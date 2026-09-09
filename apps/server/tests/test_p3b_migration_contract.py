from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.persistence.rooms.exploration import room_stage_images, session_stages
from app.persistence.rooms.exploration_messages import session_messages


def test_p3b_web_migration_extends_p3a_without_touching_character_track() -> None:
    server_root = Path(__file__).resolve().parents[1]
    config = Config(str(server_root / "alembic.ini"))
    config.set_main_option("script_location", str(server_root / "alembic"))
    scripts = ScriptDirectory.from_config(config)

    revision = scripts.get_revision("0017_p3b_exploration_stage")
    assert revision is not None
    assert revision.down_revision == "0016_p3a_table_runtime_events"
    p3c_revision = scripts.get_revision("0018_p3c_roll_pending")
    assert p3c_revision is not None
    assert p3c_revision.down_revision == revision.revision


def test_p3b_schema_keeps_messages_canonical_and_images_room_scoped() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0017_p3b_exploration_stage.py"
    ).read_text(encoding="utf-8")
    assert '"room_stage_images"' in source
    assert 'sa.ForeignKey("rooms.id", ondelete="CASCADE")' in source
    assert '"session_stages"' in source
    assert 'sa.ForeignKey("sessions.id", ondelete="CASCADE")' in source
    assert '"updated_by_seat_id"' in source
    assert 'sa.ForeignKey("campaign_seats.id", ondelete="RESTRICT")' in source
    assert session_stages.c.updated_by_seat_id.nullable is False
    assert '"session_messages"' in source
    assert 'sa.ForeignKey("session_events.id", ondelete="CASCADE")' in source
    assert "asset" not in source.lower().replace("stage_images", "")
    assert "scene" not in source.lower()


def test_p3b_metadata_and_migration_keep_indexes_in_sync() -> None:
    image_indexes = {index.name for index in room_stage_images.indexes}
    stage_indexes = {index.name for index in session_stages.indexes}
    message_indexes = {index.name for index in session_messages.indexes}
    assert image_indexes == {"ix_room_stage_images_room_id"}
    assert stage_indexes == {"ix_session_stages_image_id"}
    assert message_indexes == {"ix_session_messages_session_id"}

    source = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0017_p3b_exploration_stage.py"
    ).read_text(encoding="utf-8")
    for index_name in (
        "ix_room_stage_images_room_id",
        "ix_session_stages_image_id",
        "ix_session_messages_session_id",
    ):
        assert f'"{index_name}"' in source
