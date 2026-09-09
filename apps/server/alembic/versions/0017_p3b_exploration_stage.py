"""Add P3-B canonical Main Stage and Room-scoped Stage images.

Revision ID: 0017_p3b_exploration_stage
Revises: 0016_p3a_table_runtime_events
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0017_p3b_exploration_stage"
down_revision = "0016_p3a_table_runtime_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "room_stage_images",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "room_id",
            sa.Uuid(),
            sa.ForeignKey("rooms.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("media_type", sa.String(length=40), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_room_stage_images_room_id",
        "room_stage_images",
        ["room_id"],
    )

    op.create_table(
        "session_stages",
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("revision", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column(
            "image_id",
            sa.Uuid(),
            sa.ForeignKey("room_stage_images.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
        sa.CheckConstraint(
            "revision >= 0",
            name="ck_session_stages_revision_nonnegative",
        ),
    )
    op.create_index(
        "ix_session_stages_image_id",
        "session_stages",
        ["image_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_session_stages_image_id", table_name="session_stages")
    op.drop_table("session_stages")
    op.drop_index("ix_room_stage_images_room_id", table_name="room_stage_images")
    op.drop_table("room_stage_images")
