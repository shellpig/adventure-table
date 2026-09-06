from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "p2-non-e2e.yml"


def test_p2_non_e2e_workflow_is_manual_until_review_gate() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert source.startswith("name: P2 Non-E2E\n")
    assert "workflow_dispatch:" in source
    assert "\n  push:" not in source
    assert "\n  pull_request:" not in source


def test_p2_non_e2e_workflow_has_real_postgres_and_explicit_migration_test() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "image: postgres:17-alpine" in source
    assert "P2_POSTGRES_URL:" in source
    assert "pytest tests/test_p2a_postgres_migration.py" in source
    assert "npm test -- --run" in source
    assert "npm run build" in source
