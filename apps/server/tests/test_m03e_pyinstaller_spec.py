from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SPEC_PATH = REPO_ROOT / "apps/server/pyinstaller/standalone.spec"


def test_pyinstaller_spec_is_one_folder_console_build_without_content_duplicates() -> None:
    text = SPEC_PATH.read_text(encoding="utf-8")

    assert "ONEFILE = False" in text
    assert "exclude_binaries=True" in text
    assert "COLLECT(" in text
    assert "console=True" in text
    assert '"psycopg"' in text
    assert '"psycopg_binary"' in text
    assert '"app.standalone"' in text
    assert "data/" not in text
    assert "web/" not in text


def test_pyinstaller_spec_bundles_alembic_filesystem_resources() -> None:
    text = SPEC_PATH.read_text(encoding="utf-8")

    assert 'SERVER_ROOT / "alembic.ini"' in text
    assert 'ALEMBIC_ROOT / "env.py"' in text
    assert 'ALEMBIC_ROOT / "script.py.mako"' in text
    assert '"alembic/versions"' in text
    assert '.glob("*.py")' in text
