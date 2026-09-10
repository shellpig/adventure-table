from fastapi import APIRouter

from app.api.rooms.access import router as access_router
from app.api.rooms.campaigns import router as campaigns_router
from app.api.rooms.character_builder import router as character_builder_router
from app.api.rooms.characters import router as characters_router
from app.api.rooms.exploration import router as exploration_router
from app.api.rooms.p3c_pending import router as p3c_pending_router
from app.api.rooms.p3c_rolls import router as p3c_rolls_router
from app.api.rooms.p3c_state import router as p3c_state_router
from app.api.rooms.seats import router as seats_router
from app.api.rooms.sessions import router as sessions_router
from app.api.rooms.table_events import router as table_events_router


router = APIRouter()
router.include_router(access_router)
router.include_router(campaigns_router)
router.include_router(seats_router)
router.include_router(sessions_router)
router.include_router(table_events_router)
router.include_router(exploration_router)
router.include_router(p3c_rolls_router)
router.include_router(p3c_pending_router)
router.include_router(p3c_state_router)
router.include_router(characters_router)
router.include_router(character_builder_router)


__all__ = ["router"]
