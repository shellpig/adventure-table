from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Table,
    Text,
    Uuid,
    func,
    true,
)

from app.db import metadata


monster_templates = Table(
    "monster_templates",
    metadata,
    Column("id", Uuid(), primary_key=True),
    Column("campaign_id", Uuid(), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
    Column("name", String(160), nullable=False),
    Column("source_key", String(255), nullable=True),
    Column("rules", JSON(), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
Index("ix_monster_templates_campaign_id", monster_templates.c.campaign_id)


monster_instances = Table(
    "monster_instances",
    metadata,
    Column("id", Uuid(), primary_key=True),
    Column("campaign_id", Uuid(), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
    Column("template_key", String(255), nullable=True),
    Column(
        "custom_template_id",
        Uuid(),
        ForeignKey("monster_templates.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("name", String(160), nullable=False),
    Column("rules_snapshot", JSON(), nullable=False),
    Column("current_hp", Integer(), nullable=False),
    Column("temp_hp", Integer(), nullable=False, server_default="0"),
    Column("conditions", JSON(), nullable=False),
    Column("effects", JSON(), nullable=False),
    Column("combat_status", String(16), nullable=False),
    Column("initiative", Integer(), nullable=True),
    Column("reaction_available", Boolean(), nullable=False, server_default=true()),
    Column("resources", JSON(), nullable=False),
    Column("visibility", String(16), nullable=False),
    Column("position_note", Text(), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "NOT (template_key IS NOT NULL AND custom_template_id IS NOT NULL)",
        name="ck_monster_instances_single_template_source",
    ),
    CheckConstraint("current_hp >= 0", name="ck_monster_instances_current_hp"),
    CheckConstraint("temp_hp >= 0", name="ck_monster_instances_temp_hp"),
    CheckConstraint(
        "combat_status IN ('active', 'down', 'dead', 'removed')",
        name="ck_monster_instances_combat_status",
    ),
    CheckConstraint(
        "visibility IN ('public', 'hidden')",
        name="ck_monster_instances_visibility",
    ),
)
Index("ix_monster_instances_campaign_id", monster_instances.c.campaign_id)
Index("ix_monster_instances_custom_template_id", monster_instances.c.custom_template_id)
