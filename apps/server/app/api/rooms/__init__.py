from fastapi import APIRouter

from app.api.rooms.access import router as access_router
from app.api.rooms.campaigns import router as campaigns_router
from app.api.rooms.character_builder import router as character_builder_router
from app.api.rooms.characters import router as characters_router


router = APIRouter()
router.include_router(access_router)
router.include_router(campaigns_router)
router.include_router(characters_router)
router.include_router(character_builder_router)


__all__ = ["router"]
