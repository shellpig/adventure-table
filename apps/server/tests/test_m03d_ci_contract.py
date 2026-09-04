from __future__ import annotations

from pathlib import Path


def test_m03d_non_e2e_workflow_waits_for_review_trigger_and_installs_web_extra() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    workflow = (repo_root / ".github" / "workflows" / "m03d-non-e2e.yml").read_text(
        encoding="utf-8"
    )

    assert "push:" in workflow
    assert "m03-d-sqlite-migration-gate" in workflow
    assert ".github/m03d-non-e2e.trigger" in workflow
    assert "workflow_dispatch:" in workflow
    assert 'pip install -e ".[web,dev]"' in workflow
    assert "pytest tests/test_m03d_*.py -q" in workflow
    assert "pytest tests/test_m03c_migration.py -q" in workflow
    assert "npm test -- --run" in workflow
    assert "npm run build" in workflow
    assert "docker compose config" in workflow
