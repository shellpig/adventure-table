from fastapi import APIRouter

from app.mcp.oauth import router as oauth_router
from app.mcp.server import router as server_router

router = APIRouter()
router.include_router(oauth_router)
router.include_router(server_router)

__all__ = ["router"]
