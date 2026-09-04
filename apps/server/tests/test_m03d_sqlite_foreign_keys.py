from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, delete, insert, select, text

from app.db import metadata
from app.persistence.builder_drafts import character_build_drafts
from app.persistence.character_imports import character_import_records
from app.persistence.characters import characters


def _sqlite_url(path: Path) -> str:
    return f"sqlite+pysqlite:///{path.as_posix()}"


def test_sqlite_connections_enable_foreign_keys_and_set_null_import_targets(
    tmp_path: Path,
) -> None:
    engine = create_engine(_sqlite_url(tmp_path / "fk.sqlite3"))
    metadata.create_all(engine)

    character_id = uuid4()
    draft_id = uuid4()
    character_record_id = uuid4()
    draft_record_id = uuid4()

    try:
        with engine.begin() as connection:
            assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1

            connection.execute(
                insert(characters).values(
                    id=character_id,
                    name="SQLite FK Character",
                    ruleset="dnd5e-2014",
                    current_version_id=None,
                )
            )
            connection.execute(
                insert(character_build_drafts).values(
                    id=draft_id,
                    mode="create",
                    character_id=None,
                    base_version_id=None,
                    revision=1,
                    draft_payload={},
                    confirmed_character_id=None,
                    confirmed_version_id=None,
                    confirmed_at=None,
                )
            )
            connection.execute(
                insert(character_import_records),
                [
                    {
                        "id": character_record_id,
                        "character_id": character_id,
                        "draft_id": None,
                        "source_character_id": uuid4(),
                        "source_export_id": uuid4(),
                        "landing_mode": "character",
                    },
                    {
                        "id": draft_record_id,
                        "character_id": None,
                        "draft_id": draft_id,
                        "source_character_id": uuid4(),
                        "source_export_id": uuid4(),
                        "landing_mode": "draft",
                    },
                ],
            )

            connection.execute(delete(characters).where(characters.c.id == character_id))
            connection.execute(
                delete(character_build_drafts).where(character_build_drafts.c.id == draft_id)
            )

            character_target = connection.execute(
                select(character_import_records.c.character_id).where(
                    character_import_records.c.id == character_record_id
                )
            ).scalar_one()
            draft_target = connection.execute(
                select(character_import_records.c.draft_id).where(
                    character_import_records.c.id == draft_record_id
                )
            ).scalar_one()

        assert character_target is None
        assert draft_target is None
    finally:
        engine.dispose()
