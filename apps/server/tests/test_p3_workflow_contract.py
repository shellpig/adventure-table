from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "p3-non-e2e.yml"
P3A_BRANCH = "p3-a-session-table-runtime-event-stream"


def _source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_p3_non_e2e_workflow_is_scoped_to_post_review_p3a_trigger() -> None:
    source = _source()

    assert source.startswith("name: P3 Non-E2E\n")
    assert "workflow_dispatch:" in source
    assert "\n  push:" in source
    assert f"      - {P3A_BRANCH}\n" in source
    assert "\n  pull_request:" not in source


def test_p3_non_e2e_workflow_has_real_postgres_and_all_required_urls() -> None:
    source = _source()

    assert "image: postgres:17-alpine" in source
    for env_name in (
        "DATABASE_URL:",
        "P3_POSTGRES_URL:",
        "P2_POSTGRES_URL:",
        "M03C_POSTGRES_URL:",
    ):
        assert env_name in source


def test_p3_non_e2e_workflow_explicitly_runs_p3_and_legacy_postgres_gates() -> None:
    source = _source()

    for test_file in (
        "tests/test_p3a_postgres_events.py",
        "tests/test_p2a_postgres_migration.py",
        "tests/test_p2b_postgres_workspace.py",
        "tests/test_p2e_postgres_sessions.py",
        "tests/test_p2f_postgres_seat_selection.py",
        "tests/test_postgres_roster_lock_order.py",
        "tests/test_m03c_migration.py",
    ):
        assert test_file in source


def test_p3_non_e2e_workflow_keeps_frontend_and_windows_standalone_gates() -> None:
    source = _source()

    assert "npm test -- --run" in source
    assert "npm run build" in source
    assert "windows-standalone:" in source
    assert "runs-on: windows-latest" in source
    assert "scripts\\build-standalone.cmd --version p3a-non-e2e" in source
    assert ".standalone-venv\\Scripts\\python.exe scripts\\smoke_standalone.py" in source
