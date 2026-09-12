from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.engine import Connection, Engine

from app.persistence.mcp.lifecycle import revoke_grant_authorizations_in_transaction
from app.persistence.rooms.seats import SeatRepository
from app.persistence.rooms.sessions import SessionRepository
from app.persistence.rooms.tables import ai_controller_grants


class M04BSeatRepository(SeatRepository):
    """Web repository that revokes OAuth families with Seat AI grants."""

    @staticmethod
    def _revoke_ai_grants_for_seat(
        connection: Connection,
        *,
        seat_id: UUID,
        now: datetime,
    ) -> None:
        query = select(ai_controller_grants.c.id).where(
            ai_controller_grants.c.seat_id == seat_id,
            ai_controller_grants.c.status == "active",
        )
        if connection.dialect.name == "postgresql":
            query = query.with_for_update()
        grant_ids = tuple(connection.scalars(query).all())
        SeatRepository._revoke_ai_grants_for_seat(
            connection,
            seat_id=seat_id,
            now=now,
        )
        revoke_grant_authorizations_in_transaction(
            connection,
            grant_ids,
            now=now,
        )


class M04BSessionRepository(SessionRepository):
    """Web repository that revokes OAuth families with Session grants."""

    def __init__(self, engine: Engine) -> None:
        super().__init__(engine)

    def finalize_in_transaction(
        self,
        connection: Connection,
        *,
        session_id: UUID,
        status: str,
        now: datetime | None = None,
    ) -> bool:
        query = select(ai_controller_grants.c.id).where(
            ai_controller_grants.c.session_id == session_id,
            ai_controller_grants.c.status == "active",
        )
        if connection.dialect.name == "postgresql":
            query = query.with_for_update()
        grant_ids = tuple(connection.scalars(query).all())
        effective_now = now
        result = super().finalize_in_transaction(
            connection,
            session_id=session_id,
            status=status,
            now=effective_now,
        )
        if result and grant_ids:
            if effective_now is None:
                # Read the timestamp written by the base repository so both rows share
                # one logical revoke instant without opening another transaction.
                effective_now = connection.scalar(
                    select(ai_controller_grants.c.revoked_at)
                    .where(ai_controller_grants.c.id == grant_ids[0])
                )
            if effective_now is None:
                raise RuntimeError("finalized AI grant did not record revoked_at")
            revoke_grant_authorizations_in_transaction(
                connection,
                grant_ids,
                now=effective_now,
            )
        return result


__all__ = ["M04BSeatRepository", "M04BSessionRepository"]
