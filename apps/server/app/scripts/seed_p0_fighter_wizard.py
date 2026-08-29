from __future__ import annotations

from sqlalchemy import create_engine

from app.config import settings
from app.content.registry import load_default_content_registry
from app.domain.character.fixture import (
    P0_FIXTURE_NAME,
    build_p0_fighter_wizard_fixture,
    build_p0_fighter_wizard_state,
)
from app.persistence.characters import CharacterRepository


def main() -> None:
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    try:
        repository = CharacterRepository(engine, load_default_content_registry())
        character = repository.create_character(
            name=P0_FIXTURE_NAME,
            build=build_p0_fighter_wizard_fixture(),
            state=build_p0_fighter_wizard_state(),
        )
        print(character.id)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
