from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_current_web_migration_commands_use_all_heads() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "alembic upgrade heads" in compose
    assert "alembic upgrade heads" in readme
    assert "alembic upgrade head\n" not in readme
    assert "alembic upgrade head`" not in readme


def test_standalone_launcher_uses_character_head_only() -> None:
    launcher = (REPO_ROOT / "apps/server/app/launcher.py").read_text(encoding="utf-8")

    assert 'command.upgrade(config, "character@head")' in launcher
    assert 'command.upgrade(config, "heads")' not in launcher
