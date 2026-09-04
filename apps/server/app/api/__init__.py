from fastapi import APIRouter

from app.api.character_builder import router as character_builder_router
from app.api.character_export import router as _character_export_router
from app.api.character_import import router as _character_import_router
from app.api.characters import router as _character_core_router
from app.api.content_presentation import router as content_presentation_router
from app.api.reference import router as reference_router

# M03-E keeps Character I/O inside the single character router composition.
# Both web and standalone therefore mount the same character surface without
# counting import/export as separate distribution-level routers.
characters_router = APIRouter()
characters_router.include_router(_character_core_router)
characters_router.include_router(_character_export_router)
characters_router.include_router(_character_import_router)

__all__ = [
    "character_builder_router",
    "characters_router",
    "content_presentation_router",
    "reference_router",
]
