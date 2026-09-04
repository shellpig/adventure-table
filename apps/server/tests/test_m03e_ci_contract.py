from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github/workflows/m03e-non-e2e.yml"
TRIGGER = ".github/m03e-non-e2e.trigger"


def test_m03e_non_e2e_workflow_waits_for_explicit_trigger_commit() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "m03-e-standalone-packaging" in text
    assert TRIGGER in text
    assert "workflow_dispatch:" in text
    assert "pull_request:" not in text
    assert "paths:" in text


def test_m03e_non_e2e_workflow_covers_changed_sides_without_browser_e2e() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert 'pip install -e ".[web,dev,standalone]"' in text
    assert "pytest tests/test_m03e_*.py -q" in text
    assert "run: pytest" in text
    assert "npm test -- --run" in text
    assert "npm run build" in text
    assert "docker compose config" in text
    assert "windows-latest" in text
    assert "build-standalone.cmd --dry-run --version m03e-ci" in text
    assert "playwright" not in text.lower()
    assert "test:e2e" not in text.lower()


def test_e0_frozen_smoke_is_real_freeze_but_not_m03f_release_build() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "pyinstaller.exe" in text
    assert "standalone.spec" in text
    assert "smoke_standalone.py" in text
    assert "dist\\adventure-table-standalone\\data" in text
    assert "apps\\web\\dist" not in text
    assert "Compress-Archive" not in text
    assert "upload-artifact" not in text
    assert "gh release" not in text.lower()
