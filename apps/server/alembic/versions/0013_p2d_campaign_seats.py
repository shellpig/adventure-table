"""Add P2-D Campaign Seat persistence on the Web track.

Revision ID: 0013_p2d_campaign_seats
Revises: 0012_p2c_campaigns
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0013_p2d_campaign_seats"
down_revision = "0012_p2c_campaigns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "campaign_seats",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=True),
        sa.Column("controller_kind", sa.String(length=16), nullable=False),
        sa.Column("controller_access_session_id", sa.Uuid(), nullable=True),
        sa.Column("selected_character_id", sa.Uuid(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "role IN ('dm', 'player', 'spectator')",
            name="ck_campaign_seats_role",
        ),
        sa.CheckConstraint(
            "controller_kind IN ('human', 'ai', 'none')",
            name="ck_campaign_seats_controller_kind",
        ),
        sa.CheckConstraint(
            "(controller_kind = 'human' AND controller_access_session_id IS NOT NULL) OR "
            "(controller_kind IN ('ai', 'none') AND controller_access_session_id IS NULL)",
            name="ck_campaign_seats_controller_binding",
        ),
        sa.CheckConstraint(
            "role = 'player' OR selected_character_id IS NULL",
            name="ck_campaign_seats_player_character_only",
        ),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["controller_access_session_id"],
            ["room_access_sessions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["selected_character_id"], ["characters.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_campaign_seats_campaign_id", "campaign_seats", ["campaign_id"], unique=False)
    op.create_index(
        "ix_campaign_seats_controller_access_session_id",
        "campaign_seats",
        ["controller_access_session_id"],
        unique=False,
    )
    op.create_index(
        "ix_campaign_seats_selected_character_id",
        "campaign_seats",
        ["selected_character_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_campaign_seats_selected_character_id", table_name="campaign_seats")
    op.drop_index("ix_campaign_seats_controller_access_session_id", table_name="campaign_seats")
    op.drop_index("ix_campaign_seats_campaign_id", table_name="campaign_seats")
    op.drop_table("campaign_seats")
