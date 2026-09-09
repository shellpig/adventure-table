from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.engine import Engine

from app.persistence.characters import character_versions, characters


@dataclass(frozen=True)
class StoredSessionCharacterSummary:
    id: UUID
    name: str
    version_no: int
    build_payload: dict[str, Any]


class SessionResumeRepository:
    """Web-only batched reads needed to compose Session Resume projections."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def load_character_summaries(
        self,
        character_ids: Iterable[UUID],
    ) -> tuple[StoredSessionCharacterSummary, ...]:
        ordered_ids = tuple(dict.fromkeys(character_ids))
        if not ordered_ids:
            return ()

        with self.engine.connect() as connection:
            rows = connection.execute(
                select(
                    characters.c.id,
                    characters.c.name,
                    character_versions.c.version_no,
                    character_versions.c.build_payload,
                )
                .select_from(
                    characters.join(
                        character_versions,
                        character_versions.c.id == characters.c.current_version_id,
                    )
                )
                .where(characters.c.id.in_(ordered_ids))
            ).mappings().all()

        by_id = {
            row["id"]: StoredSessionCharacterSummary(
                id=row["id"],
                name=row["name"],
                version_no=int(row["version_no"]),
                build_payload=dict(row["build_payload"]),
            )
            for row in rows
        }
        missing = next((character_id for character_id in ordered_ids if character_id not in by_id), None)
        if missing is not None:
            raise LookupError(f"Session Resume Character {missing} was not found")
        return tuple(by_id[character_id] for character_id in ordered_ids)


__all__ = ["SessionResumeRepository", "StoredSessionCharacterSummary"]
