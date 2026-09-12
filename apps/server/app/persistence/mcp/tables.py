from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    String,
    Table,
    Uuid,
    func,
)

from app.db import metadata
from app.persistence.rooms.tables import ai_controller_grants as _ai_controller_grants  # noqa: F401


ai_oauth_clients = Table(
    "ai_oauth_clients",
    metadata,
    Column("id", Uuid(), primary_key=True),
    Column("client_id", String(160), nullable=False, unique=True),
    Column("client_secret_hash", String(128), nullable=True),
    Column("redirect_uris", JSON(), nullable=False),
    Column("client_name", String(200), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

ai_oauth_authorizations = Table(
    "ai_oauth_authorizations",
    metadata,
    Column("id", Uuid(), primary_key=True),
    Column(
        "client_id",
        String(160),
        ForeignKey("ai_oauth_clients.client_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "grant_id",
        Uuid(),
        ForeignKey("ai_controller_grants.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("grant_generation", BigInteger(), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("revoked_at", DateTime(timezone=True), nullable=True),
)
Index("ix_ai_oauth_authorizations_client_id", ai_oauth_authorizations.c.client_id)
Index("ix_ai_oauth_authorizations_grant_id", ai_oauth_authorizations.c.grant_id)
Index(
    "uq_ai_oauth_authorizations_active_grant",
    ai_oauth_authorizations.c.grant_id,
    unique=True,
    sqlite_where=ai_oauth_authorizations.c.revoked_at.is_(None),
    postgresql_where=ai_oauth_authorizations.c.revoked_at.is_(None),
)

ai_oauth_authorization_codes = Table(
    "ai_oauth_authorization_codes",
    metadata,
    Column("code_hash", String(64), primary_key=True),
    Column(
        "authorization_id",
        Uuid(),
        ForeignKey("ai_oauth_authorizations.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("code_challenge", String(128), nullable=False),
    Column("redirect_uri", String(2048), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("consumed_at", DateTime(timezone=True), nullable=True),
)
Index(
    "ix_ai_oauth_authorization_codes_authorization_id",
    ai_oauth_authorization_codes.c.authorization_id,
)

ai_oauth_tokens = Table(
    "ai_oauth_tokens",
    metadata,
    Column("id", Uuid(), primary_key=True),
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("kind", String(16), nullable=False),
    Column(
        "authorization_id",
        Uuid(),
        ForeignKey("ai_oauth_authorizations.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True), nullable=True),
    Column("last_used_at", DateTime(timezone=True), nullable=True),
    CheckConstraint("kind IN ('access', 'refresh')", name="ck_ai_oauth_tokens_kind"),
)
Index("ix_ai_oauth_tokens_authorization_id", ai_oauth_tokens.c.authorization_id)
Index("ix_ai_oauth_tokens_kind", ai_oauth_tokens.c.kind)


__all__ = [
    "ai_oauth_authorization_codes",
    "ai_oauth_authorizations",
    "ai_oauth_clients",
    "ai_oauth_tokens",
]
