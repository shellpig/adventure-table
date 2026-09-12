from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.engine import Connection

from app.persistence.mcp.tables import ai_oauth_authorizations


def revoke_grant_authorizations_in_transaction(
    connection: Connection,
    grant_ids: Iterable[UUID],
    *,
    now: datetime,
) -> None:
    ids = tuple(dict.fromkeys(grant_ids))
    if not ids:
        return
    connection.execute(
        update(ai_oauth_authorizations)
        .where(
            ai_oauth_authorizations.c.grant_id.in_(ids),
            ai_oauth_authorizations.c.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )


__all__ = ["revoke_grant_authorizations_in_transaction"]
