from fastapi import FastAPI, HTTPException, status

from app.config import settings
from app.content import load_default_content_registry
from app.db import database_is_ready


content_registry = load_default_content_registry()

app = FastAPI(title=settings.app_name)
app.state.content_registry = content_registry


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def readiness() -> dict[str, str]:
    if not database_is_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "database_unavailable"},
        )
    return {"status": "ready"}
