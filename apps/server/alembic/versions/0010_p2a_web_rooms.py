"""Create P2-A Room tables on the Web-only migration track.

Revision ID: 0010_p2a_web_rooms
Revises: 0008_m03c_import_records
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0010_p2a_web_rooms"
down_revision = "0008_m03c_import_records"
branch_labels = ("web",)
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rooms",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=10), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("password_salt", sa.LargeBinary(length=32), nullable=False),
        sa.Column("password_hash", sa.LargeBinary(length=64), nullable=False),
        sa.Column("owner_key_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("dm_key_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_rooms_code"),
    )
    op.create_table(
        "room_access_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("room_id", sa.Uuid(), nullable=False),
        sa.Column("authority", sa.String(length=16), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "authority IN ('member', 'dm', 'owner')",
            name="ck_room_access_sessions_authority",
        ),
        sa.ForeignKeyConstraint(
            ["room_id"], ["rooms.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_room_access_sessions_token_hash"),
    )
    op.create_index(
        "ix_room_access_sessions_room_id",
        "room_access_sessions",
        ["room_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_room_access_sessions_room_id", table_name="room_access_sessions"
    )
    op.drop_table("room_access_sessions")
    op.drop_table("rooms")
