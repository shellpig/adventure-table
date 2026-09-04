from __future__ import annotations

from pathlib import Path
import tomllib


def test_psycopg_is_optional_and_postgres_workflows_install_web_extra() -> None:
    server_root = Path(__file__).resolve().parents[1]
    repo_root = server_root.parents[1]
    project = tomllib.loads((server_root / "pyproject.toml").read_text(encoding="utf-8"))

    core_dependencies = project["project"]["dependencies"]
    optional_dependencies = project["project"]["optional-dependencies"]

    assert not any(dependency.startswith("psycopg") for dependency in core_dependencies)
    assert any(
        dependency.startswith("psycopg")
        for dependency in optional_dependencies["web"]
    )

    dockerfile = (server_root / "Dockerfile").read_text(encoding="utf-8")
    assert 'pip install --no-cache-dir ".[web]"' in dockerfile

    postgres_workflows: list[Path] = []
    for workflow_path in sorted((repo_root / ".github" / "workflows").glob("*.yml")):
        workflow = workflow_path.read_text(encoding="utf-8")
        if "postgres:" not in workflow:
            continue
        postgres_workflows.append(workflow_path)
        install_lines = [
            line.strip()
            for line in workflow.splitlines()
            if "pip install -e" in line
        ]
        assert install_lines, f"{workflow_path} has Postgres but no backend install step"
        assert all('".[web,dev]"' in line for line in install_lines), (
            f"{workflow_path} must install the web extra: {install_lines}"
        )

    assert postgres_workflows
