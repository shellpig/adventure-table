"""Add P4-A Monster Template and Monster Instance persistence.

Revision ID: 0022_p4a_monster_instances
Revises: 0021_m04b_ai_oauth
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0022_p4a_monster_instances"
down_revision = "0021_m04b_ai_oauth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "monster_templates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "campaign_id",
            sa.Uuid(),
            sa.ForeignKey("campaigns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("source_key", sa.String(length=255), nullable=True),
        sa.Column("rules", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_monster_templates_campaign_id",
        "monster_templates",
        ["campaign_id"],
    )

    op.create_table(
        "monster_instances",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "campaign_id",
            sa.Uuid(),
            sa.ForeignKey("campaigns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("template_key", sa.String(length=255), nullable=True),
        sa.Column(
            "custom_template_id",
            sa.Uuid(),
            sa.ForeignKey("monster_templates.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("rules_snapshot", sa.JSON(), nullable=False),
        sa.Column("current_hp", sa.Integer(), nullable=False),
        sa.Column("temp_hp", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("conditions", sa.JSON(), nullable=False),
        sa.Column("effects", sa.JSON(), nullable=False),
        sa.Column("combat_status", sa.String(length=16), nullable=False),
        sa.Column("initiative", sa.Integer(), nullable=True),
        sa.Column("reaction_available", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("resources", sa.JSON(), nullable=False),
        sa.Column("visibility", sa.String(length=16), nullable=False),
        sa.Column("position_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "NOT (template_key IS NOT NULL AND custom_template_id IS NOT NULL)",
            name="ck_monster_instances_single_template_source",
        ),
        sa.CheckConstraint("current_hp >= 0", name="ck_monster_instances_current_hp"),
        sa.CheckConstraint("temp_hp >= 0", name="ck_monster_instances_temp_hp"),
        sa.CheckConstraint(
            "combat_status IN ('active', 'down', 'dead', 'removed')",
            name="ck_monster_instances_combat_status",
        ),
        sa.CheckConstraint(
            "visibility IN ('public', 'hidden')",
            name="ck_monster_instances_visibility",
        ),
    )
    op.create_index(
        "ix_monster_instances_campaign_id",
        "monster_instances",
        ["campaign_id"],
    )
    op.create_index(
        "ix_monster_instances_custom_template_id",
        "monster_instances",
        ["custom_template_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_monster_instances_custom_template_id", table_name="monster_instances")
    op.drop_index("ix_monster_instances_campaign_id", table_name="monster_instances")
    op.drop_table("monster_instances")
    op.drop_index("ix_monster_templates_campaign_id", table_name="monster_templates")
    op.drop_table("monster_templates")
