"""Add M04-B ChatGPT web OAuth persistence.

Revision ID: 0021_m04b_ai_oauth
Revises: 0020_p3d_ai_controller_grants
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0021_m04b_ai_oauth"
down_revision = "0020_p3d_ai_controller_grants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_oauth_clients",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("client_id", sa.String(length=160), nullable=False),
        sa.Column("client_secret_hash", sa.String(length=128), nullable=True),
        sa.Column("redirect_uris", sa.JSON(), nullable=False),
        sa.Column("client_name", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("client_id", name="uq_ai_oauth_clients_client_id"),
    )
    op.create_table(
        "ai_oauth_authorizations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "client_id",
            sa.String(length=160),
            sa.ForeignKey("ai_oauth_clients.client_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "grant_id",
            sa.Uuid(),
            sa.ForeignKey("ai_controller_grants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("grant_generation", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_ai_oauth_authorizations_client_id",
        "ai_oauth_authorizations",
        ["client_id"],
    )
    op.create_index(
        "ix_ai_oauth_authorizations_grant_id",
        "ai_oauth_authorizations",
        ["grant_id"],
    )
    op.create_index(
        "uq_ai_oauth_authorizations_active_grant",
        "ai_oauth_authorizations",
        ["grant_id"],
        unique=True,
        sqlite_where=sa.text("revoked_at IS NULL"),
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_table(
        "ai_oauth_authorization_codes",
        sa.Column("code_hash", sa.String(length=64), primary_key=True),
        sa.Column(
            "authorization_id",
            sa.Uuid(),
            sa.ForeignKey("ai_oauth_authorizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code_challenge", sa.String(length=128), nullable=False),
        sa.Column("redirect_uri", sa.String(length=2048), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_ai_oauth_authorization_codes_authorization_id",
        "ai_oauth_authorization_codes",
        ["authorization_id"],
    )
    op.create_table(
        "ai_oauth_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column(
            "authorization_id",
            sa.Uuid(),
            sa.ForeignKey("ai_oauth_authorizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('access', 'refresh')", name="ck_ai_oauth_tokens_kind"),
        sa.UniqueConstraint("token_hash", name="uq_ai_oauth_tokens_token_hash"),
    )
    op.create_index(
        "ix_ai_oauth_tokens_authorization_id",
        "ai_oauth_tokens",
        ["authorization_id"],
    )
    op.create_index("ix_ai_oauth_tokens_kind", "ai_oauth_tokens", ["kind"])


def downgrade() -> None:
    op.drop_index("ix_ai_oauth_tokens_kind", table_name="ai_oauth_tokens")
    op.drop_index("ix_ai_oauth_tokens_authorization_id", table_name="ai_oauth_tokens")
    op.drop_table("ai_oauth_tokens")
    op.drop_index(
        "ix_ai_oauth_authorization_codes_authorization_id",
        table_name="ai_oauth_authorization_codes",
    )
    op.drop_table("ai_oauth_authorization_codes")
    op.drop_index(
        "uq_ai_oauth_authorizations_active_grant",
        table_name="ai_oauth_authorizations",
    )
    op.drop_index(
        "ix_ai_oauth_authorizations_grant_id",
        table_name="ai_oauth_authorizations",
    )
    op.drop_index(
        "ix_ai_oauth_authorizations_client_id",
        table_name="ai_oauth_authorizations",
    )
    op.drop_table("ai_oauth_authorizations")
    op.drop_table("ai_oauth_clients")
