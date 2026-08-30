from app.api.character_builder import router as character_builder_router
from app.api.characters import router as characters_router
from app.api.content_presentation import router as content_presentation_router
from app.api.reference import router as reference_router

__all__ = [
    "character_builder_router",
    "characters_router",
    "content_presentation_router",
    "reference_router",
]
