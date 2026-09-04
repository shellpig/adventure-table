from __future__ import annotations

import argparse
import ast
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import threading
import time
from urllib.error import URLError
from urllib.request import urlopen

LISTEN_RE = re.compile(r"Listening on:\s+(http://127\.0\.0\.1:\d+/)")
FORBIDDEN_OUTPUT = ("postgresql", "psycopg")


def _assigned_string(node: ast.stmt, name: str) -> str | None:
    value: ast.expr | None = None
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id == name:
            value = node.value
    elif isinstance(node, ast.AnnAssign):
        target = node.target
        if isinstance(target, ast.Name) and target.id == name:
            value = node.value
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value
    return None


def _migration_head(repo_root: Path) -> str:
    revisions: dict[str, str | None] = {}
    for path in sorted((repo_root / "apps/server/alembic/versions").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        revision: str | None = None
        down_revision: str | None = None
        for node in tree.body:
            revision = _assigned_string(node, "revision") or revision
            down_revision = _assigned_string(node, "down_revision") or down_revision
        if revision is not None:
            revisions[revision] = down_revision
    referenced = {down for down in revisions.values() if down is not None}
    heads = sorted(set(revisions) - referenced)
    if len(heads) != 1:
        raise RuntimeError(f"expected one Alembic head, found {heads}")
    return heads[0]


def _reader(stream, sink: list[str]) -> None:
    try:
        for line in iter(stream.readline, ""):
            sink.append(line)
    finally:
        stream.close()


def _get_json(url: str) -> object:
    with urlopen(url, timeout=2) as response:
        return json.loads(response.read())


def run_smoke(artifact_dir: Path, repo_root: Path, timeout: float = 20.0) -> None:
    artifact_dir = artifact_dir.resolve()
    executable = artifact_dir / ("adventure-table.exe" if os.name == "nt" else "adventure-table")
    if not executable.is_file():
        raise RuntimeError(f"standalone executable not found: {executable}")

    database_path = artifact_dir / "adventure-table.sqlite3"
    if database_path.exists():
        database_path.unlink()

    env = os.environ.copy()
    env.pop("ADVENTURE_TABLE_DATABASE_PATH", None)
    env["ADVENTURE_TABLE_NO_BROWSER"] = "1"
    process = subprocess.Popen(
        [str(executable)],
        cwd=artifact_dir,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    stdout_thread = threading.Thread(target=_reader, args=(process.stdout, stdout_lines), daemon=True)
    stderr_thread = threading.Thread(target=_reader, args=(process.stderr, stderr_lines), daemon=True)
    stdout_thread.start()
    stderr_thread.start()

    base_url: str | None = None
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            output = "".join(stdout_lines)
            match = LISTEN_RE.search(output)
            if match:
                base_url = match.group(1)
                try:
                    capabilities = _get_json(base_url + "api/meta/capabilities")
                    if isinstance(capabilities, dict) and capabilities.get("channel") == "standalone":
                        break
                except (URLError, TimeoutError, OSError, json.JSONDecodeError):
                    pass
            if process.poll() is not None:
                raise RuntimeError(
                    f"standalone exited early with {process.returncode}\n"
                    + "".join(stdout_lines + stderr_lines)
                )
            time.sleep(0.1)
        else:
            raise RuntimeError("standalone did not become ready before timeout")

        if base_url is None:
            raise RuntimeError("launcher never printed a listening URL")
        capabilities = _get_json(base_url + "api/meta/capabilities")
        characters = _get_json(base_url + "api/characters")
        if not isinstance(capabilities, dict) or capabilities.get("channel") != "standalone":
            raise RuntimeError(f"unexpected capabilities payload: {capabilities!r}")
        if characters != []:
            raise RuntimeError(f"expected empty character list, got {characters!r}")
        if not database_path.is_file():
            raise RuntimeError(f"default SQLite file was not created beside executable: {database_path}")

        expected_head = _migration_head(repo_root)
        with sqlite3.connect(database_path) as connection:
            row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        if row is None or row[0] != expected_head:
            raise RuntimeError(f"Alembic head mismatch: expected {expected_head}, got {row}")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        stdout_thread.join(timeout=1)
        stderr_thread.join(timeout=1)

    combined = ("".join(stdout_lines) + "\n" + "".join(stderr_lines)).lower()
    offenders = [token for token in FORBIDDEN_OUTPUT if token in combined]
    if offenders:
        raise RuntimeError(f"standalone output mentioned forbidden web DB dependencies: {offenders}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact_dir", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()
    run_smoke(args.artifact_dir, args.repo_root.resolve(), args.timeout)
    print("Standalone smoke passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
