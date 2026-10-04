from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    PrimaryKeyConstraint,
    String,
    Table,
    Uuid,
    func,
)

from app.db import metadata


battle_maps = Table(
    "battle_maps",
    metadata,
    Column("id", Uuid(), primary_key=True),
    Column("room_id", Uuid(), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False),
    Column("name", String(160), nullable=False),
    Column("source_kind", String(16), nullable=False),
    Column("image_asset_id", Uuid(), ForeignKey("room_assets.id", ondelete="RESTRICT"), nullable=True),
    Column("width_cells", Integer(), nullable=False),
    Column("height_cells", Integer(), nullable=False),
    Column("grid_pixel_size", Integer(), nullable=True),
    Column("grid_offset_x", Integer(), nullable=True),
    Column("grid_offset_y", Integer(), nullable=True),
    Column("revision", BigInteger(), nullable=False, server_default="1"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("archived_at", DateTime(timezone=True), nullable=True),
    CheckConstraint(
        "source_kind IN ('blank', 'image')",
        name="ck_battle_maps_source_kind",
    ),
    CheckConstraint(
        "(source_kind = 'image' AND image_asset_id IS NOT NULL) OR "
        "(source_kind = 'blank' AND image_asset_id IS NULL)",
        name="ck_battle_maps_image_asset_consistency",
    ),
    CheckConstraint(
        "(source_kind = 'image') OR "
        "(grid_pixel_size IS NULL AND grid_offset_x IS NULL "
        "AND grid_offset_y IS NULL)",
        name="ck_battle_maps_grid_alignment",
    ),
    CheckConstraint(
        "width_cells >= 1 AND width_cells <= 200",
        name="ck_battle_maps_width_cells",
    ),
    CheckConstraint(
        "height_cells >= 1 AND height_cells <= 200",
        name="ck_battle_maps_height_cells",
    ),
    CheckConstraint(
        "grid_pixel_size IS NULL OR grid_pixel_size > 0",
        name="ck_battle_maps_grid_pixel_size_positive",
    ),
    CheckConstraint("revision > 0", name="ck_battle_maps_revision_positive"),
)
Index("ix_battle_maps_room_id", battle_maps.c.room_id)
Index(
    "ix_battle_maps_room_archived_created",
    battle_maps.c.room_id,
    battle_maps.c.archived_at,
    battle_maps.c.created_at,
)


battle_map_walls = Table(
    "battle_map_walls",
    metadata,
    Column("id", Uuid(), primary_key=True),
    Column("battle_map_id", Uuid(), ForeignKey("battle_maps.id", ondelete="CASCADE"), nullable=False),
    Column("x1", Integer(), nullable=False),
    Column("y1", Integer(), nullable=False),
    Column("x2", Integer(), nullable=False),
    Column("y2", Integer(), nullable=False),
    Column("visibility", String(16), nullable=False),
    CheckConstraint(
        "visibility IN ('public', 'hidden')",
        name="ck_battle_map_walls_visibility",
    ),
    CheckConstraint(
        "(x1 = x2 AND y1 != y2) OR (y1 = y2 AND x1 != x2)",
        name="ck_battle_map_walls_axis_aligned",
    ),
)
Index("ix_battle_map_walls_battle_map_id", battle_map_walls.c.battle_map_id)


battle_map_doors = Table(
    "battle_map_doors",
    metadata,
    Column("id", Uuid(), primary_key=True),
    Column("battle_map_id", Uuid(), ForeignKey("battle_maps.id", ondelete="CASCADE"), nullable=False),
    Column("x1", Integer(), nullable=False),
    Column("y1", Integer(), nullable=False),
    Column("x2", Integer(), nullable=False),
    Column("y2", Integer(), nullable=False),
    Column("default_state", String(16), nullable=False),
    Column("visibility", String(16), nullable=False),
    CheckConstraint(
        "default_state IN ('open', 'closed', 'locked', 'broken')",
        name="ck_battle_map_doors_default_state",
    ),
    CheckConstraint(
        "visibility IN ('public', 'hidden')",
        name="ck_battle_map_doors_visibility",
    ),
    CheckConstraint(
        "(x1 = x2 AND ABS(y1 - y2) = 1) OR (y1 = y2 AND ABS(x1 - x2) = 1)",
        name="ck_battle_map_doors_unit_edge",
    ),
)
Index("ix_battle_map_doors_battle_map_id", battle_map_doors.c.battle_map_id)


battle_map_terrain = Table(
    "battle_map_terrain",
    metadata,
    Column("battle_map_id", Uuid(), ForeignKey("battle_maps.id", ondelete="CASCADE"), nullable=False),
    Column("x", Integer(), nullable=False),
    Column("y", Integer(), nullable=False),
    Column("terrain_kind", String(16), nullable=False),
    CheckConstraint(
        "terrain_kind IN ('normal', 'difficult', 'blocked')",
        name="ck_battle_map_terrain_kind",
    ),
    PrimaryKeyConstraint("battle_map_id", "x", "y"),
)
Index("ix_battle_map_terrain_battle_map_id", battle_map_terrain.c.battle_map_id)


battle_map_drawings = Table(
    "battle_map_drawings",
    metadata,
    Column("id", Uuid(), primary_key=True),
    Column("battle_map_id", Uuid(), ForeignKey("battle_maps.id", ondelete="CASCADE"), nullable=False),
    Column("payload", JSON(), nullable=False),
)
Index("ix_battle_map_drawings_battle_map_id", battle_map_drawings.c.battle_map_id)


battle_map_monster_placements = Table(
    "battle_map_monster_placements",
    metadata,
    Column("id", Uuid(), primary_key=True),
    Column("battle_map_id", Uuid(), ForeignKey("battle_maps.id", ondelete="CASCADE"), nullable=False),
    Column("template_key", String(255), nullable=True),
    Column(
        "custom_template_id",
        Uuid(),
        ForeignKey("monster_templates.id", ondelete="RESTRICT"),
        nullable=True,
    ),
    Column("anchor_x", Integer(), nullable=False),
    Column("anchor_y", Integer(), nullable=False),
    Column("visibility", String(16), nullable=False),
    Column("sort_order", Integer(), nullable=False),
    CheckConstraint(
        "visibility IN ('public', 'hidden')",
        name="ck_battle_map_monster_placements_visibility",
    ),
    CheckConstraint(
        "(template_key IS NULL) != (custom_template_id IS NULL)",
        name="ck_battle_map_monster_placements_single_template_source",
    ),
)
Index(
    "ix_battle_map_monster_placements_battle_map_id",
    battle_map_monster_placements.c.battle_map_id,
)
