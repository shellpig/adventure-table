from __future__ import annotations

from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from app.config import settings
from app.content.localization import ContentLocalizationCatalog
from app.content.registry import CONTENT_PACKS_ROOT, ContentRegistry
from app.domain.character_builder.service import CharacterBuilderService
from app.persistence.builder_drafts import BuilderDraftRepository
from app.persistence.characters import CharacterRepository


def get_content_registry(request: Request) -> ContentRegistry:
    return request.app.state.content_registry


def get_content_localization(request: Request) -> ContentLocalizationCatalog:
    localization = getattr(request.app.state, "content_localization", None)
    if localization is None:
        localization = ContentLocalizationCatalog.from_root(
            get_content_registry(request),
            CONTENT_PACKS_ROOT,
        )
        request.app.state.content_localization = localization
    return localization


def get_database_engine(request: Request) -> Engine:
    engine = getattr(request.app.state, "character_engine", None)
    if engine is None:
        engine = create_engine(settings.database_url, pool_pre_ping=True)
        request.app.state.character_engine = engine
    return engine


def get_character_repository(request: Request) -> CharacterRepository:
    repository = getattr(request.app.state, "character_repository", None)
    if repository is None:
        repository = CharacterRepository(
            get_database_engine(request),
            get_content_registry(request),
        )
        request.app.state.character_repository = repository
    return repository


def get_character_builder_service(request: Request) -> CharacterBuilderService:
    service = getattr(request.app.state, "character_builder_service", None)
    if service is None:
        engine = get_database_engine(request)
        service = CharacterBuilderService(
            BuilderDraftRepository(engine),
            get_content_registry(request),
            get_character_repository(request),
        )
        request.app.state.character_builder_service = service
    return service
