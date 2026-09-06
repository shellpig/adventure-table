from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


SERVER_ROOT = Path(__file__).resolve().parents[1]
CHARACTER_HEAD = "0009_p2a_character_head"
WEB_HEAD = "0010_p2a_web_rooms"
BRANCH_POINT = "0008_m03c_import_records"


def _scripts() -> ScriptDirectory:
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SERVER_ROOT / "alembic"))
    return ScriptDirectory.from_config(config)


def test_p2a_character_and_web_tracks_are_distinct_heads() -> None:
    scripts = _scripts()
    assert set(scripts.get_heads()) == {CHARACTER_HEAD, WEB_HEAD}

    character = scripts.get_revision(CHARACTER_HEAD)
    web = scripts.get_revision(WEB_HEAD)
    assert character is not None
    assert web is not None
    assert character.down_revision == BRANCH_POINT
    assert web.down_revision == BRANCH_POINT
    assert "character" in character.branch_labels
    assert "web" in web.branch_labels
    assert character.dependencies is None
    assert web.dependencies is None


def test_p2a_alembic_env_does_not_import_room_metadata_unconditionally() -> None:
    source = (SERVER_ROOT / "alembic" / "env.py").read_text(encoding="utf-8")
    assert "app.persistence.rooms" not in source
    assert "app.domain.rooms" not in source
