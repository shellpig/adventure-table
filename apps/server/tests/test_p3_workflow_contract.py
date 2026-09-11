from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
NON_E2E_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "p3-non-e2e.yml"
E2E_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "p3-e2e.yml"
P3A_BRANCH = "p3-a-session-table-runtime-event-stream"
P3B_BRANCH = "p3-b-exploration-chat-actions"
P3C_BRANCH = "p3-c-roll-check-pending-action"
P3D_BRANCH = "p3-d-ai-controller-scoped-token-handoff"
P3E_BRANCH = "p3-e-ai-tool-surface-event-delivery"
P3F_BRANCH = "p3-f-full-integration-closeout"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_p3_non_e2e_workflow_is_scoped_to_post_review_p3_triggers() -> None:
    source = _source(NON_E2E_WORKFLOW)

    assert source.startswith("name: P3 Non-E2E\n")
    assert "workflow_dispatch:" in source
    assert "\n  push:" in source
    for branch in (
        P3A_BRANCH,
        P3B_BRANCH,
        P3C_BRANCH,
        P3D_BRANCH,
        P3E_BRANCH,
        P3F_BRANCH,
    ):
        assert f"      - {branch}\n" in source
    assert "\n  pull_request:" not in source


def test_p3_non_e2e_workflow_has_real_postgres_and_all_required_urls() -> None:
    source = _source(NON_E2E_WORKFLOW)

    assert "image: postgres:17-alpine" in source
    for env_name in (
        "DATABASE_URL:",
        "P3_POSTGRES_URL:",
        "P2_POSTGRES_URL:",
        "M03C_POSTGRES_URL:",
    ):
        assert env_name in source


def test_p3_non_e2e_workflow_explicitly_runs_p3_and_legacy_postgres_gates() -> None:
    source = _source(NON_E2E_WORKFLOW)

    for test_file in (
        "tests/test_p3a_postgres_events.py",
        "tests/test_p3b_postgres_stage.py",
        "tests/test_p3c_postgres_rolls.py",
        "tests/test_p3d_postgres_controller.py",
        "tests/test_p3d_postgres_controller_matrix.py",
        "tests/test_p3f_waiter_resource_safety.py",
        "tests/test_p3f_postgres_restart_recovery.py",
        "tests/test_p2a_postgres_migration.py",
        "tests/test_p2b_postgres_workspace.py",
        "tests/test_p2e_postgres_sessions.py",
        "tests/test_p2f_postgres_seat_selection.py",
        "tests/test_postgres_roster_lock_order.py",
        "tests/test_m03c_migration.py",
    ):
        assert test_file in source


def test_p3_non_e2e_workflow_keeps_frontend_and_windows_standalone_gates() -> None:
    source = _source(NON_E2E_WORKFLOW)

    assert "npm test -- --run" in source
    assert "npm run build" in source
    assert "windows-standalone:" in source
    assert "runs-on: windows-latest" in source
    assert "scripts\\build-standalone.cmd --version p3-non-e2e" in source
    assert ".standalone-venv\\Scripts\\python.exe scripts\\smoke_standalone.py" in source


def test_p3_e2e_workflow_rebuilds_the_real_stack_and_runs_complete_playwright() -> None:
    source = _source(E2E_WORKFLOW)

    assert source.startswith("name: P3 Full-Stack E2E\n")
    assert "workflow_dispatch:" in source
    assert "\n  push:" not in source
    assert "\n  pull_request:" not in source
    assert "docker compose down -v --remove-orphans" in source
    assert "docker compose up -d --build" in source
    assert "http://127.0.0.1:8000/health" in source
    assert "http://127.0.0.1:8000/ready" in source
    assert "http://127.0.0.1:5173" in source
    assert "PLAYWRIGHT_MCP_URL: http://127.0.0.1:8000/mcp" in source
    assert "npm run test:e2e" in source


def test_p3_e2e_workflow_always_uploads_playwright_evidence_and_cleans_up() -> None:
    source = _source(E2E_WORKFLOW)

    assert "if: always()" in source
    assert "uses: actions/upload-artifact@v4" in source
    assert "name: p3-playwright-results" in source
    assert "apps/web/test-results" in source
    assert "apps/web/playwright-report" in source
    assert source.count("docker compose down -v --remove-orphans") >= 2
