from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.engine import Engine

from app.persistence.characters import character_versions, characters
from app.persistence.rooms.tables import (
    ai_controller_grants,
    campaign_seats,
    room_access_sessions,
)


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

    def self_take_back_seat_ids(
        self,
        *,
        room_id: UUID,
        session_id: UUID,
        access_session_id: UUID,
    ) -> tuple[UUID, ...]:
        """Return only current AI Player Seats this active Human credential may reclaim."""
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(ai_controller_grants.c.seat_id)
                .select_from(
                    ai_controller_grants
                    .join(
                        campaign_seats,
                        and_(
                            campaign_seats.c.id == ai_controller_grants.c.seat_id,
                            campaign_seats.c.campaign_id == ai_controller_grants.c.campaign_id,
                        ),
                    )
                    .join(
                        room_access_sessions,
                        room_access_sessions.c.id
                        == ai_controller_grants.c.handoff_return_access_session_id,
                    )
                )
                .where(
                    ai_controller_grants.c.room_id == room_id,
                    ai_controller_grants.c.session_id == session_id,
                    ai_controller_grants.c.role == "player",
                    ai_controller_grants.c.status == "active",
                    ai_controller_grants.c.handoff_return_access_session_id
                    == access_session_id,
                    campaign_seats.c.controller_kind == "ai",
                    campaign_seats.c.ai_controller_grant_id == ai_controller_grants.c.id,
                    campaign_seats.c.controller_epoch == ai_controller_grants.c.generation,
                    campaign_seats.c.archived_at.is_(None),
                    room_access_sessions.c.id == access_session_id,
                    room_access_sessions.c.room_id == room_id,
                    room_access_sessions.c.revoked_at.is_(None),
                )
                .order_by(ai_controller_grants.c.seat_id)
            ).scalars().all()
        return tuple(rows)


__all__ = ["SessionResumeRepository", "StoredSessionCharacterSummary"]
