from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.engine import Engine

from app.persistence.rooms.tables import campaigns, session_participants, sessions


@dataclass(frozen=True)
class StoredExplorationSubject:
    seat_id: UUID
    role: str
    active_character_id: UUID | None


class ExplorationSubjectRepository:
    """Resolve immutable Session participant subject truth for P3-B actions."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def resolve_subject(
        self,
        *,
        room_id: UUID,
        campaign_id: UUID,
        session_id: UUID,
        seat_id: UUID,
    ) -> StoredExplorationSubject | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(
                    session_participants.c.seat_id,
                    session_participants.c.role_snapshot,
                    session_participants.c.active_character_id,
                )
                .select_from(
                    session_participants
                    .join(sessions, sessions.c.id == session_participants.c.session_id)
                    .join(campaigns, campaigns.c.id == sessions.c.campaign_id)
                )
                .where(
                    session_participants.c.session_id == session_id,
                    session_participants.c.seat_id == seat_id,
                    session_participants.c.left_at.is_(None),
                    sessions.c.campaign_id == campaign_id,
                    campaigns.c.room_id == room_id,
                )
            ).mappings().one_or_none()
        if row is None:
            return None
        return StoredExplorationSubject(
            seat_id=row["seat_id"],
            role=row["role_snapshot"],
            active_character_id=row["active_character_id"],
        )


__all__ = ["ExplorationSubjectRepository", "StoredExplorationSubject"]
