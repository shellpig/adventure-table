from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.persistence.rooms.p3c_rolls import RollRepository, StoredRollRequest
from app.persistence.rooms.p3c_runtime import roll_requests


class CombatAwareRollRepository(RollRepository):
    """Keep P4 Combat-targeted formal rolls out of the legacy P3 Check surface.

    P4-B reuses the canonical roll tables for initiative, including seatless
    Monster requests. P3 Check APIs and Session Resume still model a Player Seat
    target, so they must only project the legacy Seat-targeted rows.
    """

    def get_request(
        self,
        *,
        session_id: UUID,
        request_id: UUID,
    ) -> StoredRollRequest | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(roll_requests).where(
                    roll_requests.c.id == request_id,
                    roll_requests.c.session_id == session_id,
                    roll_requests.c.target_combat_entry_id.is_(None),
                )
            ).mappings().one_or_none()
        return self._request(row) if row is not None else None

    def list_requests(self, *, session_id: UUID) -> tuple[StoredRollRequest, ...]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(roll_requests)
                .where(
                    roll_requests.c.session_id == session_id,
                    roll_requests.c.target_combat_entry_id.is_(None),
                )
                .order_by(roll_requests.c.created_at, roll_requests.c.id)
            ).mappings().all()
        return tuple(self._request(row) for row in rows)


__all__ = ["CombatAwareRollRepository"]
