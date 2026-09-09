from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.persistence.rooms.exploration import room_stage_images, session_stages


def test_p3b_web_migration_extends_p3a_without_touching_character_track() -> None:
    server_root = Path(__file__).resolve().parents[1]
    config = Config(str(server_root / "alembic.ini"))
    config.set_main_option("script_location", str(server_root / "alembic"))
    scripts = ScriptDirectory.from_config(config)

    revision = scripts.get_revision("0017_p3b_exploration_stage")
    assert revision is not None
    assert revision.down_revision == "0016_p3a_table_runtime_events"
    assert "0017_p3b_exploration_stage" in scripts.get_heads()


def test_p3b_stage_schema_keeps_images_room_scoped_and_session_state_canonical() -> None:
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
    assert "asset" not in source.lower()
    assert "scene" not in source.lower()


def test_p3b_metadata_and_migration_keep_stage_indexes_in_sync() -> None:
    image_indexes = {index.name for index in room_stage_images.indexes}
    stage_indexes = {index.name for index in session_stages.indexes}
    assert image_indexes == {"ix_room_stage_images_room_id"}
    assert stage_indexes == {"ix_session_stages_image_id"}

    source = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0017_p3b_exploration_stage.py"
    ).read_text(encoding="utf-8")
    assert '"ix_room_stage_images_room_id"' in source
    assert '"ix_session_stages_image_id"' in source
