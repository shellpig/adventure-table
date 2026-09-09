from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


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
