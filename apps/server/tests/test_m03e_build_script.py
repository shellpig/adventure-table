from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts/build-standalone.cmd"


def test_build_script_contract_keeps_web_extra_out_and_copies_external_roots() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "%SERVER_DIR%[standalone]" in text
    assert "[web" not in text
    assert "npm ci" in text
    assert "npm run build" in text
    assert "standalone.spec" in text
    assert "Copy-Item -Path '%ROOT%\\data'" in text
    assert "Copy-Item -Path '%WEB_DIR%\\dist'" in text
    assert "README-standalone.en.txt" in text
    assert "README-standalone.zh-TW.txt" in text
    assert "build-id.txt" in text
    assert "Compress-Archive" in text
    assert "--dry-run" in text
    assert "--skip-frontend" in text
    assert "--version" in text


@pytest.mark.skipif(os.name != "nt", reason="Windows cmd dry-run contract")
def test_build_script_dry_run_is_side_effect_free_on_windows() -> None:
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", str(SCRIPT), "--dry-run", "--version", "v-test"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[dry-run]" in result.stdout
    assert not (REPO_ROOT / ".standalone-venv").exists()
