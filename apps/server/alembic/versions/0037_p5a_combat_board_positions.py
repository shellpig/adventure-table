"""Add combat board runtime tables (P5-A).

Revision ID: 0037_p5a_combat_board_positions
Revises: 0036_p5a_battle_maps

Web-only tables backing tactical combat boards: a frozen per-combat board
snapshot (never written back to the Map Definition), per-door runtime state,
and per-entry token placements.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0037_p5a_combat_board_positions"
down_revision = "0036_p5a_battle_maps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "combat_boards",
        sa.Column("combat_id", sa.Uuid(), nullable=False),
        sa.Column("source_battle_map_id", sa.Uuid(), nullable=True),
        sa.Column("source_battle_map_revision", sa.BigInteger(), nullable=True),
        sa.Column("width_cells", sa.Integer(), nullable=False),
        sa.Column("height_cells", sa.Integer(), nullable=False),
        sa.Column("grid_pixel_size", sa.Integer(), nullable=True),
        sa.Column("grid_offset_x", sa.Integer(), nullable=True),
        sa.Column("grid_offset_y", sa.Integer(), nullable=True),
        sa.Column("image_asset_id", sa.Uuid(), nullable=True),
        sa.Column("baseline", sa.JSON(), nullable=False),
        sa.Column(
            "runtime_revision",
            sa.BigInteger(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "width_cells >= 1 AND width_cells <= 200",
            name="ck_combat_boards_width_cells",
        ),
        sa.CheckConstraint(
            "height_cells >= 1 AND height_cells <= 200",
            name="ck_combat_boards_height_cells",
        ),
        sa.CheckConstraint(
            "grid_pixel_size IS NULL OR grid_pixel_size > 0",
            name="ck_combat_boards_grid_pixel_size_positive",
        ),
        sa.CheckConstraint(
            "runtime_revision > 0",
            name="ck_combat_boards_runtime_revision_positive",
        ),
        sa.ForeignKeyConstraint(
            ["combat_id"], ["combats.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_battle_map_id"], ["battle_maps.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["image_asset_id"], ["room_assets.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("combat_id"),
    )

    op.create_table(
        "combat_board_doors",
        sa.Column("combat_id", sa.Uuid(), nullable=False),
        sa.Column("door_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column(
            "revealed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "state IN ('open', 'closed', 'locked', 'broken')",
            name="ck_combat_board_doors_state",
        ),
        sa.ForeignKeyConstraint(
            ["combat_id"], ["combats.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("combat_id", "door_id"),
    )
    op.create_index(
        "ix_combat_board_doors_combat_id",
        "combat_board_doors",
        ["combat_id"],
        unique=False,
    )

    op.create_table(
        "combat_positions",
        sa.Column("combat_entry_id", sa.Uuid(), nullable=False),
        sa.Column("combat_id", sa.Uuid(), nullable=False),
        sa.Column("anchor_x", sa.Integer(), nullable=False),
        sa.Column("anchor_y", sa.Integer(), nullable=False),
        sa.Column("footprint_width", sa.Integer(), nullable=False),
        sa.Column("footprint_height", sa.Integer(), nullable=False),
        sa.Column(
            "revision",
            sa.BigInteger(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "anchor_x >= 0 AND anchor_y >= 0",
            name="ck_combat_positions_anchor_non_negative",
        ),
        sa.CheckConstraint(
            "footprint_width >= 1 AND footprint_height >= 1",
            name="ck_combat_positions_footprint_positive",
        ),
        sa.CheckConstraint(
            "revision > 0",
            name="ck_combat_positions_revision_positive",
        ),
        sa.ForeignKeyConstraint(
            ["combat_entry_id"], ["combat_entries.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["combat_id"], ["combats.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("combat_entry_id"),
    )
    op.create_index(
        "ix_combat_positions_combat_id",
        "combat_positions",
        ["combat_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_combat_positions_combat_id",
        table_name="combat_positions",
    )
    op.drop_table("combat_positions")
    op.drop_index(
        "ix_combat_board_doors_combat_id",
        table_name="combat_board_doors",
    )
    op.drop_table("combat_board_doors")
    op.drop_table("combat_boards")
