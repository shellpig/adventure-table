from __future__ import annotations

from pathlib import Path
import tomllib


def test_psycopg_is_web_only_and_docker_installs_web_extra() -> None:
    server_root = Path(__file__).resolve().parents[1]
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
