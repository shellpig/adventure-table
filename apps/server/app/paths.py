from __future__ import annotations

import os
from pathlib import Path
import sys

from app.config import settings


STANDALONE_DB_FILENAME = "adventure-table.sqlite3"
_launcher_mode = False


def _executable_dir() -> Path | None:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return None


def _meipass_root() -> Path | None:
    meipass = getattr(sys, "_MEIPASS", None)
    return Path(meipass).resolve() if meipass else None


def mark_launcher_mode() -> None:
    """Mark this process as a non-frozen standalone launcher invocation.

    M03-E's launcher calls this before resolving its database path. Keeping the
    marker here lets every database consumer continue to use one resolver.
    """

    global _launcher_mode
    _launcher_mode = True


def _running_as_launcher() -> bool:
    return _launcher_mode


def resolve_content_root() -> Path:
    """Resolve the runtime content/data root for web, frozen and test use."""

    configured = os.environ.get("ADVENTURE_TABLE_CONTENT_ROOT") or settings.content_root
    if configured:
        candidate = Path(configured).expanduser().resolve()
        if candidate.is_dir():
            return candidate
        raise RuntimeError(
            f"[env] ADVENTURE_TABLE_CONTENT_ROOT points to a missing directory: {candidate}"
        )

    exe_dir = _executable_dir()
    if exe_dir is not None:
        candidate = exe_dir / "data"
        if candidate.is_dir():
            return candidate
        meipass = _meipass_root()
        if meipass is not None:
            fallback = meipass / "data"
            if fallback.is_dir():
                return fallback
        raise RuntimeError(
            f"[frozen] content data directory not found: {candidate}; "
            "no usable _MEIPASS/data fallback"
        )

    candidate = Path(__file__).resolve().parents[3] / "data"
    if candidate.is_dir():
        return candidate
    raise RuntimeError(f"[repository] content data directory not found: {candidate}")


def resolve_srd_content_root() -> Path:
    return resolve_content_root() / "srd5.1"


def resolve_rules_path() -> Path:
    return resolve_content_root() / "rules" / "dnd5e-2014" / "character-builder.json"


def resolve_rules_root() -> Path:
    return resolve_content_root() / "rules" / "dnd5e-2014"


def resolve_localization_root() -> Path:
    return resolve_content_root() / "localization"


def resolve_spa_root() -> Path | None:
    """Resolve standalone SPA assets; development web mode intentionally returns None."""

    configured = os.environ.get("ADVENTURE_TABLE_SPA_ROOT") or settings.spa_root
    if configured:
        candidate = Path(configured).expanduser().resolve()
        return candidate if candidate.is_dir() else None

    exe_dir = _executable_dir()
    if exe_dir is None:
        return None

    candidate = exe_dir / "web"
    if candidate.is_dir():
        return candidate
    meipass = _meipass_root()
    if meipass is not None:
        fallback = meipass / "web"
        if fallback.is_dir():
            return fallback
    return None


def resolve_database_path() -> Path | None:
    """Return the standalone SQLite path, or None for the normal web entry."""

    configured = os.environ.get("ADVENTURE_TABLE_DATABASE_PATH") or settings.database_path
    if configured:
        return Path(configured).expanduser().resolve()

    exe_dir = _executable_dir()
    if exe_dir is not None:
        return (exe_dir / STANDALONE_DB_FILENAME).resolve()

    if _running_as_launcher():
        return (Path.cwd() / STANDALONE_DB_FILENAME).resolve()
    return None


def resolve_database_url() -> str:
    """Single database URL resolver shared by web, standalone and Alembic."""

    database_path = resolve_database_path()
    if database_path is not None:
        return f"sqlite+pysqlite:///{database_path.as_posix()}"
    return settings.database_url
