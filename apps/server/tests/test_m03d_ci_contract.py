from __future__ import annotations

from pathlib import Path


def test_m03d_non_e2e_workflow_is_manual_and_installs_web_extra() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    workflow = (repo_root / ".github" / "workflows" / "m03d-non-e2e.yml").read_text(
        encoding="utf-8"
    )

    assert "workflow_dispatch:" in workflow
    assert "push:" not in workflow
    assert 'pip install -e ".[dev,web]"' in workflow
    assert "pytest tests/test_m03d_*.py -q" in workflow
    assert "pytest tests/test_m03c_migration.py -q" in workflow
    assert "npm test -- --run" in workflow
    assert "npm run build" in workflow
    assert "docker compose config" in workflow
