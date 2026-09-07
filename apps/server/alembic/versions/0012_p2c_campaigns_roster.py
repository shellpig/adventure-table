"""Add P2-C Campaign and Party Roster persistence on the Web track.

Revision ID: 0012_p2c_campaigns
Revises: 0011_p2b_room_workspace
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0012_p2c_campaigns"
down_revision = "0011_p2b_room_workspace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "campaigns",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("room_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("ruleset", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
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
            "status IN ('draft', 'active', 'completed', 'archived')",
            name="ck_campaigns_status",
        ),
        sa.ForeignKeyConstraint(["room_id"], ["rooms.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_campaigns_room_id", "campaigns", ["room_id"], unique=False)

    op.create_table(
        "campaign_roster_entries",
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("character_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "added_at",
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
            "status IN ('active', 'inactive', 'retired', 'dead')",
            name="ck_campaign_roster_entries_status",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"], ["campaigns.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["character_id"], ["characters.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("campaign_id", "character_id"),
    )
    op.create_index(
        "ix_campaign_roster_entries_character_id",
        "campaign_roster_entries",
        ["character_id"],
        unique=False,
    )

    op.add_column("rooms", sa.Column("active_campaign_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_rooms_active_campaign_id_campaigns",
        "rooms",
        "campaigns",
        ["active_campaign_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_rooms_active_campaign_id_campaigns",
        "rooms",
        type_="foreignkey",
    )
    op.drop_column("rooms", "active_campaign_id")
    op.drop_index(
        "ix_campaign_roster_entries_character_id",
        table_name="campaign_roster_entries",
    )
    op.drop_table("campaign_roster_entries")
    op.drop_index("ix_campaigns_room_id", table_name="campaigns")
    op.drop_table("campaigns")
