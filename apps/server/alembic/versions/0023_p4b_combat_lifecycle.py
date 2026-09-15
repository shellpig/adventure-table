"""Add P4-B Quick Combat lifecycle and action-economy persistence.

Revision ID: 0023_p4b_combat_lifecycle
Revises: 0022_p4a_monster_instances
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0023_p4b_combat_lifecycle"
down_revision = "0022_p4a_monster_instances"
branch_labels = None
depends_on = None
json_payload_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "combats",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("campaign_id", sa.Uuid(), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("started_session_id", sa.Uuid(), sa.ForeignKey("sessions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("ended_session_id", sa.Uuid(), sa.ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("mode", sa.String(length=16), nullable=False, server_default="quick"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="initiative_pending"),
        sa.Column("round_number", sa.Integer(), nullable=True),
        sa.Column("current_turn_entry_id", sa.Uuid(), nullable=True),
        sa.Column("revision", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("mode = 'quick'", name="ck_combats_mode_quick"),
        sa.CheckConstraint("status IN ('initiative_pending', 'running', 'ended')", name="ck_combats_status"),
        sa.CheckConstraint(
            "(status = 'running' AND round_number IS NOT NULL AND round_number >= 1 AND current_turn_entry_id IS NOT NULL) OR "
            "(status != 'running' AND (round_number IS NULL OR round_number >= 1))",
            name="ck_combats_running_turn_state",
        ),
        sa.CheckConstraint("revision > 0", name="ck_combats_revision_positive"),
    )
    op.create_index("ix_combats_campaign_id", "combats", ["campaign_id"])
    op.create_index(
        "uq_combats_campaign_active", "combats", ["campaign_id"], unique=True,
        postgresql_where=sa.text("status IN ('initiative_pending', 'running')"),
        sqlite_where=sa.text("status IN ('initiative_pending', 'running')"),
    )
    op.create_table(
        "combat_entries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("combat_id", sa.Uuid(), sa.ForeignKey("combats.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subject_kind", sa.String(length=16), nullable=False),
        sa.Column("character_id", sa.Uuid(), sa.ForeignKey("characters.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("monster_instance_id", sa.Uuid(), sa.ForeignKey("monster_instances.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("is_hostile", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("initiative_group_key", sa.String(length=120), nullable=True),
        sa.Column("initiative_roll_request_id", sa.Uuid(), nullable=True),
        sa.Column("initiative_roll_result_id", sa.Uuid(), nullable=True),
        sa.Column("initiative_total", sa.Integer(), nullable=True),
        sa.Column("turn_order", sa.Integer(), nullable=True),
        sa.Column("surprised", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("action_available", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("bonus_action_available", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("reaction_available", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("attacks_allowed", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("attacks_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ready_state", json_payload_type, nullable=False),
        sa.Column("pending_reaction_state", json_payload_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "(subject_kind = 'character' AND character_id IS NOT NULL AND monster_instance_id IS NULL) OR "
            "(subject_kind = 'monster' AND character_id IS NULL AND monster_instance_id IS NOT NULL)",
            name="ck_combat_entries_subject",
        ),
        sa.CheckConstraint("status IN ('active', 'withdrawn', 'removed')", name="ck_combat_entries_status"),
        sa.CheckConstraint("turn_order IS NULL OR turn_order >= 0", name="ck_combat_entries_turn_order"),
        sa.CheckConstraint("attacks_allowed >= 1", name="ck_combat_entries_attacks_allowed"),
        sa.CheckConstraint("attacks_used >= 0 AND attacks_used <= attacks_allowed", name="ck_combat_entries_attacks_used"),
        sa.UniqueConstraint("combat_id", "character_id", name="uq_combat_entries_character"),
        sa.UniqueConstraint("combat_id", "monster_instance_id", name="uq_combat_entries_monster"),
    )
    op.create_index("ix_combat_entries_combat_id", "combat_entries", ["combat_id"])
    op.create_index("ix_combat_entries_character_id", "combat_entries", ["character_id"])
    op.create_index("ix_combat_entries_monster_instance_id", "combat_entries", ["monster_instance_id"])
    op.create_index("ix_combat_entries_turn_order", "combat_entries", ["combat_id", "turn_order"])
    op.create_table(
        "combat_actions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("combat_id", sa.Uuid(), sa.ForeignKey("combats.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entry_id", sa.Uuid(), sa.ForeignKey("combat_entries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("sessions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("acting_seat_id", sa.Uuid(), sa.ForeignKey("campaign_seats.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("subject_seat_id", sa.Uuid(), sa.ForeignKey("campaign_seats.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("execution_mode", sa.String(length=16), nullable=False),
        sa.Column("action_kind", sa.String(length=32), nullable=False),
        sa.Column("economy_cost", sa.String(length=16), nullable=False),
        sa.Column("payload", json_payload_type, nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("execution_mode IN ('self', 'dm_proxy')", name="ck_combat_actions_execution_mode"),
        sa.CheckConstraint("economy_cost IN ('action', 'bonus_action', 'reaction', 'none')", name="ck_combat_actions_economy_cost"),
        sa.UniqueConstraint("combat_id", "idempotency_key", name="uq_combat_actions_idempotency"),
    )
    op.create_index("ix_combat_actions_combat_id", "combat_actions", ["combat_id"])
    op.create_index("ix_combat_actions_entry_id", "combat_actions", ["entry_id"])


def downgrade() -> None:
    op.drop_index("ix_combat_actions_entry_id", table_name="combat_actions")
    op.drop_index("ix_combat_actions_combat_id", table_name="combat_actions")
    op.drop_table("combat_actions")
    op.drop_index("ix_combat_entries_turn_order", table_name="combat_entries")
    op.drop_index("ix_combat_entries_monster_instance_id", table_name="combat_entries")
    op.drop_index("ix_combat_entries_character_id", table_name="combat_entries")
    op.drop_index("ix_combat_entries_combat_id", table_name="combat_entries")
    op.drop_table("combat_entries")
    op.drop_index("uq_combats_campaign_active", table_name="combats")
    op.drop_index("ix_combats_campaign_id", table_name="combats")
    op.drop_table("combats")
