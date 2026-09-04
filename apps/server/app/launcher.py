from __future__ import annotations

import os
from pathlib import Path
import socket
import sys
import threading
import time
import webbrowser

from alembic import command
from alembic.config import Config
import uvicorn

from app.paths import (
    mark_launcher_mode,
    resolve_content_root,
    resolve_database_path,
    resolve_database_url,
    resolve_spa_root,
)

PORT_RANGE_START = 8000
PORT_RANGE_END = 8100
SERVER_START_TIMEOUT_SECONDS = 10.0
BUILD_ID_FILENAME = "build-id.txt"


def _prepare_database_path() -> Path:
    """Pin the standalone SQLite path before migrations or app import."""

    mark_launcher_mode()
    # Resolve first: the shared resolver already implements the E.5 order
    # (env -> settings.database_path -> frozen exe dir -> launcher cwd), so
    # pinning a default into the environment beforehand would shadow a path
    # configured through settings rather than through the environment.
    database_path = resolve_database_path()
    if database_path is None:
        raise RuntimeError(
            "Unable to resolve standalone SQLite path; check "
            "ADVENTURE_TABLE_DATABASE_PATH."
        )
    database_path = database_path.resolve()
    os.environ["ADVENTURE_TABLE_DATABASE_PATH"] = str(database_path)
    try:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        database_path.touch(exist_ok=True)
    except OSError as exc:
        raise RuntimeError(
            f"Standalone database path is not writable: {database_path} ({exc})"
        ) from exc
    return database_path.resolve()


def _prepare_resource_roots() -> tuple[Path, Path | None]:
    content_root = resolve_content_root().resolve()
    os.environ.setdefault("ADVENTURE_TABLE_CONTENT_ROOT", str(content_root))

    spa_root = resolve_spa_root()
    if spa_root is not None:
        spa_root = spa_root.resolve()
        os.environ.setdefault("ADVENTURE_TABLE_SPA_ROOT", str(spa_root))
    return content_root, spa_root


def _alembic_config_path() -> Path:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if not meipass:
            raise RuntimeError("Frozen launcher is missing sys._MEIPASS for Alembic resources")
        return Path(meipass).resolve() / "alembic" / "alembic.ini"
    return Path(__file__).resolve().parents[1] / "alembic.ini"


def _alembic_script_location(config_path: Path) -> Path:
    """Resolve migration scripts independently from the Alembic config file.

    The source tree keeps ``alembic.ini`` at ``apps/server/`` and migration
    scripts under ``apps/server/alembic/``.  The frozen bundle deliberately
    co-locates the copied config with ``env.py`` and ``versions/`` under
    ``_MEIPASS/alembic/``.  Keeping these two layouts explicit prevents the
    launcher from depending on CWD or Alembic's relative-path semantics.
    """

    if getattr(sys, "frozen", False):
        return config_path.parent
    return config_path.parent / "alembic"


def run_migrations() -> None:
    config_path = _alembic_config_path()
    if not config_path.is_file():
        raise RuntimeError(f"Alembic config not found: {config_path}")

    script_location = _alembic_script_location(config_path)
    if not script_location.is_dir():
        raise RuntimeError(f"Alembic script directory not found: {script_location}")

    database_url = resolve_database_url()
    if not database_url.startswith("sqlite+pysqlite://"):
        raise RuntimeError(
            "Standalone migrations require SQLite; "
            f"resolved database URL is {database_url!r}. "
            "Check ADVENTURE_TABLE_DATABASE_PATH."
        )

    config = Config(str(config_path))
    config.set_main_option("sqlalchemy.url", database_url)
    config.set_main_option("script_location", str(script_location))
    try:
        command.upgrade(config, "head")
    except Exception as exc:
        raise RuntimeError(
            f"Alembic upgrade failed for {database_url!r} using {config_path}: {exc}"
        ) from exc


def _find_free_port(
    start: int = PORT_RANGE_START,
    end: int = PORT_RANGE_END,
) -> int:
    for port in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
            try:
                candidate.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"No free localhost port in range {start}-{end}")


def _build_id() -> str:
    configured = os.environ.get("ADVENTURE_TABLE_BUILD_ID")
    if configured:
        return configured.strip() or "dev"
    if getattr(sys, "frozen", False):
        build_id_path = Path(sys.executable).resolve().parent / BUILD_ID_FILENAME
        try:
            value = build_id_path.read_text(encoding="utf-8").strip()
        except OSError:
            return "dev"
        return value or "dev"
    return "dev"


def _print_banner(
    port: int,
    database_path: Path,
    content_root: Path,
    spa_root: Path | None,
) -> None:
    print(f"Adventure Table Standalone ({_build_id()})", flush=True)
    print(f"  Database: {database_path.resolve()}", flush=True)
    print(f"  Content root: {content_root.resolve()}", flush=True)
    print(
        f"  SPA root: {spa_root.resolve() if spa_root is not None else '<not mounted>'}",
        flush=True,
    )
    print(f"  Listening on: http://127.0.0.1:{port}/", flush=True)
    print("  Press Ctrl+C or close this window to stop.", flush=True)


def _wait_for_server(
    server: uvicorn.Server,
    thread: threading.Thread,
    *,
    timeout: float = SERVER_START_TIMEOUT_SECONDS,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if server.started:
            return
        if not thread.is_alive():
            raise RuntimeError("Standalone server stopped before reporting ready")
        time.sleep(0.05)
    raise RuntimeError(f"Standalone server did not start within {timeout:.1f} seconds")


def open_browser(url: str) -> bool:
    return webbrowser.open(url)


def _should_open_browser() -> bool:
    return os.environ.get("ADVENTURE_TABLE_NO_BROWSER", "").strip().lower() not in {
        "1",
        "true",
        "yes",
    }


def main() -> int:
    # The database path is deliberately the first runtime decision. It must be
    # pinned before Alembic and before uvicorn imports app.standalone.
    database_path = _prepare_database_path()
    content_root, spa_root = _prepare_resource_roots()
    run_migrations()

    port = _find_free_port()
    _print_banner(port, database_path, content_root, spa_root)
    url = f"http://127.0.0.1:{port}/"

    config = uvicorn.Config(
        "app.standalone:app",
        host="127.0.0.1",
        port=port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="adventure-table-server", daemon=True)
    thread.start()
    try:
        _wait_for_server(server, thread)
        if _should_open_browser():
            open_browser(url)
        while thread.is_alive():
            thread.join(timeout=0.5)
    except KeyboardInterrupt:
        server.should_exit = True
        thread.join(timeout=10.0)
    except BaseException:
        server.should_exit = True
        thread.join(timeout=5.0)
        raise
    finally:
        if thread.is_alive():
            server.should_exit = True
            thread.join(timeout=5.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "open_browser", "run_migrations"]
