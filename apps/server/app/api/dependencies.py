from __future__ import annotations

from fastapi import Request
from sqlalchemy import create_engine

from app.config import settings
from app.content.registry import ContentRegistry
from app.persistence.characters import CharacterRepository


def get_content_registry(request: Request) -> ContentRegistry:
    return request.app.state.content_registry


def get_character_repository(request: Request) -> CharacterRepository:
    repository = getattr(request.app.state, "character_repository", None)
    if repository is None:
        engine = getattr(request.app.state, "character_engine", None)
        if engine is None:
            engine = create_engine(settings.database_url, pool_pre_ping=True)
            request.app.state.character_engine = engine
        repository = CharacterRepository(engine, get_content_registry(request))
        request.app.state.character_repository = repository
    return repository
