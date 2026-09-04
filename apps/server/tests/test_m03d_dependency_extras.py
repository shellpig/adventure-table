from __future__ import annotations

from pathlib import Path
import re
import tomllib


_EDITABLE_EXTRAS_RE = re.compile(r"\[([^\]]+)\]")


def _job_blocks(workflow: str) -> list[tuple[str, list[str]]]:
    """Return top-level GitHub Actions job blocks without adding a YAML dependency."""

    lines = workflow.splitlines()
    try:
        jobs_index = next(index for index, line in enumerate(lines) if line == "jobs:")
    except StopIteration:
        return []

    headers: list[tuple[int, str]] = []
    for index in range(jobs_index + 1, len(lines)):
        match = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", lines[index])
        if match:
            headers.append((index, match.group(1)))

    blocks: list[tuple[str, list[str]]] = []
    for position, (start, name) in enumerate(headers):
        end = headers[position + 1][0] if position + 1 < len(headers) else len(lines)
        blocks.append((name, lines[start:end]))
    return blocks


def _editable_install_extras(line: str) -> set[str]:
    match = _EDITABLE_EXTRAS_RE.search(line)
    if match is None:
        return set()
    return {extra.strip() for extra in match.group(1).split(",") if extra.strip()}


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

    postgres_jobs: list[str] = []
    for workflow_path in sorted((repo_root / ".github" / "workflows").glob("*.yml")):
        workflow = workflow_path.read_text(encoding="utf-8")
        for job_name, block in _job_blocks(workflow):
            if not any(line.strip() == "postgres:" for line in block):
                continue

            postgres_jobs.append(f"{workflow_path}:{job_name}")
            install_lines = [
                line.strip()
                for line in block
                if "pip install -e" in line
            ]
            assert install_lines, (
                f"{workflow_path}:{job_name} has Postgres but no backend install step"
            )
            assert all(
                {"web", "dev"}.issubset(_editable_install_extras(line))
                for line in install_lines
            ), (
                f"{workflow_path}:{job_name} must install web+dev extras: "
                f"{install_lines}"
            )

    assert postgres_jobs
