from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.content import load_default_content_registry
from app.db import engine


content_registry = load_default_content_registry()

app = FastAPI(title="Adventure Table API")
app.state.content_registry = content_registry


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict[str, str]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        from fastapi import HTTPException

        raise HTTPException(status_code=503, detail="database unavailable")

    return {"status": "ready"}
