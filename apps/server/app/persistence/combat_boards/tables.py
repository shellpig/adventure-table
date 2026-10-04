from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
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


combat_boards = Table(
    "combat_boards",
    metadata,
    Column("combat_id", Uuid(), ForeignKey("combats.id", ondelete="CASCADE"), primary_key=True),
    Column("source_battle_map_id", Uuid(), ForeignKey("battle_maps.id", ondelete="RESTRICT"), nullable=True),
    Column("source_battle_map_revision", BigInteger(), nullable=True),
    Column("width_cells", Integer(), nullable=False),
    Column("height_cells", Integer(), nullable=False),
    Column("grid_pixel_size", Integer(), nullable=True),
    Column("grid_offset_x", Integer(), nullable=True),
    Column("grid_offset_y", Integer(), nullable=True),
    Column("image_asset_id", Uuid(), ForeignKey("room_assets.id", ondelete="RESTRICT"), nullable=True),
    Column("baseline", JSON(), nullable=False),
    Column("runtime_revision", BigInteger(), nullable=False, server_default="1"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "width_cells >= 1 AND width_cells <= 200",
        name="ck_combat_boards_width_cells",
    ),
    CheckConstraint(
        "height_cells >= 1 AND height_cells <= 200",
        name="ck_combat_boards_height_cells",
    ),
    CheckConstraint(
        "grid_pixel_size IS NULL OR grid_pixel_size > 0",
        name="ck_combat_boards_grid_pixel_size_positive",
    ),
    CheckConstraint(
        "runtime_revision > 0",
        name="ck_combat_boards_runtime_revision_positive",
    ),
)


combat_board_doors = Table(
    "combat_board_doors",
    metadata,
    Column("combat_id", Uuid(), ForeignKey("combats.id", ondelete="CASCADE"), nullable=False),
    Column("door_id", Uuid(), nullable=False),
    Column("state", String(16), nullable=False),
    Column("revealed", Boolean(), nullable=False, server_default="0"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "state IN ('open', 'closed', 'locked', 'broken')",
        name="ck_combat_board_doors_state",
    ),
    PrimaryKeyConstraint("combat_id", "door_id"),
)
Index("ix_combat_board_doors_combat_id", combat_board_doors.c.combat_id)


combat_positions = Table(
    "combat_positions",
    metadata,
    Column("combat_entry_id", Uuid(), ForeignKey("combat_entries.id", ondelete="CASCADE"), primary_key=True),
    Column("combat_id", Uuid(), ForeignKey("combats.id", ondelete="CASCADE"), nullable=False),
    Column("anchor_x", Integer(), nullable=False),
    Column("anchor_y", Integer(), nullable=False),
    Column("footprint_width", Integer(), nullable=False),
    Column("footprint_height", Integer(), nullable=False),
    Column("revision", BigInteger(), nullable=False, server_default="1"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "anchor_x >= 0 AND anchor_y >= 0",
        name="ck_combat_positions_anchor_non_negative",
    ),
    CheckConstraint(
        "footprint_width >= 1 AND footprint_height >= 1",
        name="ck_combat_positions_footprint_positive",
    ),
    CheckConstraint("revision > 0", name="ck_combat_positions_revision_positive"),
)
Index("ix_combat_positions_combat_id", combat_positions.c.combat_id)


__all__ = ["combat_board_doors", "combat_boards", "combat_positions"]
