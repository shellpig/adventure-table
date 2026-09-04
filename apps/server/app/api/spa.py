from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


def mount_spa(app: FastAPI, spa_root: Path | None) -> None:
    """Mount a built SPA and its history fallback when standalone assets exist."""

    if spa_root is None:
        return

    root = spa_root.resolve()
    assets_dir = root / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")

        candidate = (root / full_path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Not Found") from exc
        if candidate.is_file():
            return FileResponse(candidate)

        index_path = root / "index.html"
        if not index_path.is_file():
            raise HTTPException(status_code=404, detail="Standalone SPA is unavailable")
        return FileResponse(index_path)


__all__ = ["mount_spa"]
