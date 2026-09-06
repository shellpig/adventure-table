"""Add P2-B Room-to-Character workspace associations on the Web track.

Revision ID: 0011_p2b_room_character_workspace
Revises: 0010_p2a_web_rooms
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0011_p2b_room_character_workspace"
down_revision = "0010_p2a_web_rooms"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "room_characters",
        sa.Column("room_id", sa.Uuid(), nullable=False),
        sa.Column("character_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["room_id"], ["rooms.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["character_id"], ["characters.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("room_id", "character_id"),
        sa.UniqueConstraint("character_id", name="uq_room_characters_character_id"),
    )
    op.create_index(
        "ix_room_characters_room_id",
        "room_characters",
        ["room_id"],
        unique=False,
    )
    op.create_table(
        "room_builder_drafts",
        sa.Column("room_id", sa.Uuid(), nullable=False),
        sa.Column("draft_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["room_id"], ["rooms.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["draft_id"], ["character_build_drafts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("room_id", "draft_id"),
        sa.UniqueConstraint("draft_id", name="uq_room_builder_drafts_draft_id"),
    )
    op.create_index(
        "ix_room_builder_drafts_room_id",
        "room_builder_drafts",
        ["room_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_room_builder_drafts_room_id", table_name="room_builder_drafts")
    op.drop_table("room_builder_drafts")
    op.drop_index("ix_room_characters_room_id", table_name="room_characters")
    op.drop_table("room_characters")
