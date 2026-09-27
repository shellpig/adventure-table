"""Add battle_map_image asset kind and Battle Map Definition tables (P5-A).

Revision ID: 0036_p5a_battle_maps
Revises: 0035_p5a_combat_mode_tactical
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0036_p5a_battle_maps"
down_revision = "0035_p5a_combat_mode_tactical"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("room_assets") as batch_op:
        batch_op.drop_constraint("ck_room_assets_kind", type_="check")
        batch_op.create_check_constraint(
            "ck_room_assets_kind",
            "kind IN ('image', 'source_document', 'battle_map_image')",
        )

    op.create_table(
        "battle_maps",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("room_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("source_kind", sa.String(length=16), nullable=False),
        sa.Column("image_asset_id", sa.Uuid(), nullable=True),
        sa.Column("width_cells", sa.Integer(), nullable=False),
        sa.Column("height_cells", sa.Integer(), nullable=False),
        sa.Column("grid_pixel_size", sa.Integer(), nullable=True),
        sa.Column("grid_offset_x", sa.Integer(), nullable=True),
        sa.Column("grid_offset_y", sa.Integer(), nullable=True),
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
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "source_kind IN ('blank', 'image')",
            name="ck_battle_maps_source_kind",
        ),
        sa.CheckConstraint(
            "(source_kind = 'image' AND image_asset_id IS NOT NULL) OR "
            "(source_kind = 'blank' AND image_asset_id IS NULL)",
            name="ck_battle_maps_image_asset_consistency",
        ),
        sa.CheckConstraint(
            "(source_kind = 'image') OR "
            "(grid_pixel_size IS NULL AND grid_offset_x IS NULL "
            "AND grid_offset_y IS NULL)",
            name="ck_battle_maps_grid_alignment",
        ),
        sa.CheckConstraint(
            "width_cells >= 1 AND width_cells <= 200",
            name="ck_battle_maps_width_cells",
        ),
        sa.CheckConstraint(
            "height_cells >= 1 AND height_cells <= 200",
            name="ck_battle_maps_height_cells",
        ),
        sa.CheckConstraint(
            "grid_pixel_size IS NULL OR grid_pixel_size > 0",
            name="ck_battle_maps_grid_pixel_size_positive",
        ),
        sa.CheckConstraint(
            "revision > 0",
            name="ck_battle_maps_revision_positive",
        ),
        sa.ForeignKeyConstraint(
            ["room_id"], ["rooms.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["image_asset_id"], ["room_assets.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_battle_maps_room_id",
        "battle_maps",
        ["room_id"],
        unique=False,
    )

    op.create_table(
        "battle_map_walls",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("battle_map_id", sa.Uuid(), nullable=False),
        sa.Column("x1", sa.Integer(), nullable=False),
        sa.Column("y1", sa.Integer(), nullable=False),
        sa.Column("x2", sa.Integer(), nullable=False),
        sa.Column("y2", sa.Integer(), nullable=False),
        sa.Column("visibility", sa.String(length=16), nullable=False),
        sa.CheckConstraint(
            "visibility IN ('public', 'hidden')",
            name="ck_battle_map_walls_visibility",
        ),
        sa.CheckConstraint(
            "(x1 = x2 AND y1 != y2) OR (y1 = y2 AND x1 != x2)",
            name="ck_battle_map_walls_axis_aligned",
        ),
        sa.ForeignKeyConstraint(
            ["battle_map_id"], ["battle_maps.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_battle_map_walls_battle_map_id",
        "battle_map_walls",
        ["battle_map_id"],
        unique=False,
    )

    op.create_table(
        "battle_map_doors",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("battle_map_id", sa.Uuid(), nullable=False),
        sa.Column("x1", sa.Integer(), nullable=False),
        sa.Column("y1", sa.Integer(), nullable=False),
        sa.Column("x2", sa.Integer(), nullable=False),
        sa.Column("y2", sa.Integer(), nullable=False),
        sa.Column("default_state", sa.String(length=16), nullable=False),
        sa.Column("visibility", sa.String(length=16), nullable=False),
        sa.CheckConstraint(
            "default_state IN ('open', 'closed', 'locked', 'broken')",
            name="ck_battle_map_doors_default_state",
        ),
        sa.CheckConstraint(
            "visibility IN ('public', 'hidden')",
            name="ck_battle_map_doors_visibility",
        ),
        sa.CheckConstraint(
            "(x1 = x2 AND ABS(y1 - y2) = 1) OR (y1 = y2 AND ABS(x1 - x2) = 1)",
            name="ck_battle_map_doors_unit_edge",
        ),
        sa.ForeignKeyConstraint(
            ["battle_map_id"], ["battle_maps.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_battle_map_doors_battle_map_id",
        "battle_map_doors",
        ["battle_map_id"],
        unique=False,
    )

    op.create_table(
        "battle_map_terrain",
        sa.Column("battle_map_id", sa.Uuid(), nullable=False),
        sa.Column("x", sa.Integer(), nullable=False),
        sa.Column("y", sa.Integer(), nullable=False),
        sa.Column("terrain_kind", sa.String(length=16), nullable=False),
        sa.CheckConstraint(
            "terrain_kind IN ('difficult', 'blocked')",
            name="ck_battle_map_terrain_kind",
        ),
        sa.ForeignKeyConstraint(
            ["battle_map_id"], ["battle_maps.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("battle_map_id", "x", "y"),
    )
    op.create_index(
        "ix_battle_map_terrain_battle_map_id",
        "battle_map_terrain",
        ["battle_map_id"],
        unique=False,
    )

    op.create_table(
        "battle_map_drawings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("battle_map_id", sa.Uuid(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["battle_map_id"], ["battle_maps.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_battle_map_drawings_battle_map_id",
        "battle_map_drawings",
        ["battle_map_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_battle_map_drawings_battle_map_id",
        table_name="battle_map_drawings",
    )
    op.drop_table("battle_map_drawings")
    op.drop_index(
        "ix_battle_map_terrain_battle_map_id",
        table_name="battle_map_terrain",
    )
    op.drop_table("battle_map_terrain")
    op.drop_index(
        "ix_battle_map_doors_battle_map_id",
        table_name="battle_map_doors",
    )
    op.drop_table("battle_map_doors")
    op.drop_index(
        "ix_battle_map_walls_battle_map_id",
        table_name="battle_map_walls",
    )
    op.drop_table("battle_map_walls")
    op.drop_index(
        "ix_battle_maps_room_id",
        table_name="battle_maps",
    )
    op.drop_table("battle_maps")

    with op.batch_alter_table("room_assets") as batch_op:
        batch_op.drop_constraint("ck_room_assets_kind", type_="check")
        batch_op.create_check_constraint(
            "ck_room_assets_kind",
            "kind IN ('image', 'source_document')",
        )
