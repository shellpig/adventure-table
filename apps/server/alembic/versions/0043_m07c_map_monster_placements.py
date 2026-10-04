"""Add battle_map_monster_placements for M07-C map monster pre-placement (C1).

Revision ID: 0043_m07c_map_monster_placements
Revises: 0042_m07b_battle_map_lifecycle
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0043_m07c_map_monster_placements"
down_revision = "0042_m07b_battle_map_lifecycle"
branch_labels = None
depends_on = None

assert len(revision) <= 32, "M07-C contract: revision id must fit 32 characters"


def upgrade() -> None:
    op.create_table(
        "battle_map_monster_placements",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "battle_map_id",
            sa.Uuid(),
            sa.ForeignKey("battle_maps.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("template_key", sa.String(255), nullable=True),
        sa.Column(
            "custom_template_id",
            sa.Uuid(),
            sa.ForeignKey("monster_templates.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("anchor_x", sa.Integer(), nullable=False),
        sa.Column("anchor_y", sa.Integer(), nullable=False),
        sa.Column("visibility", sa.String(16), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "visibility IN ('public', 'hidden')",
            name="ck_battle_map_monster_placements_visibility",
        ),
        sa.CheckConstraint(
            "(template_key IS NULL) != (custom_template_id IS NULL)",
            name="ck_battle_map_monster_placements_single_template_source",
        ),
        sa.Index(
            "ix_battle_map_monster_placements_battle_map_id",
            "battle_map_id",
        ),
    )


def downgrade() -> None:
    op.drop_table("battle_map_monster_placements")
