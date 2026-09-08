from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "p2-non-e2e.yml"
P2A_BRANCH = "p2-a-room-foundation-web-entry"
P2F_BRANCH = "p2-f-full-integration-closeout"
P2F_WORK_BRANCH = "p2-f-full-integration-closeout-work"


def test_p2_non_e2e_workflow_is_scoped_to_post_review_p2a_trigger() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert source.startswith("name: P2 Non-E2E\n")
    assert "workflow_dispatch:" in source
    assert "\n  push:" in source
    assert f"      - {P2A_BRANCH}\n" in source
    assert "\n  pull_request:" not in source


def test_p2_non_e2e_workflow_has_real_postgres_and_explicit_migration_test() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "image: postgres:17-alpine" in source
    assert "P2_POSTGRES_URL:" in source
    assert "pytest tests/test_p2a_postgres_migration.py" in source
    assert "npm test -- --run" in source
    assert "npm run build" in source


def test_p2f_final_non_e2e_workflow_closes_postgres_and_standalone_gates() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert f"      - {P2F_BRANCH}\n" in source
    assert P2F_WORK_BRANCH not in source
    assert "M03C_POSTGRES_URL:" in source
    assert "tests/test_m03c_migration.py" in source
    assert "tests/test_p2f_postgres_seat_selection.py" in source
    assert "windows-standalone:" in source
    assert "github.ref_name == 'p2-f-full-integration-closeout'" in source
    assert "scripts\\build-standalone.cmd --version p2f-non-e2e" in source
    assert ".standalone-venv\\Scripts\\python.exe scripts\\smoke_standalone.py" in source
