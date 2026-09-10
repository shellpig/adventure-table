"""Add P3-C canonical Roll, Check, and PendingAction runtime tables.

Revision ID: 0018_p3c_roll_pending
Revises: 0017_p3b_exploration_stage
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0018_p3c_roll_pending"
down_revision = "0017_p3b_exploration_stage"
branch_labels = None
depends_on = None

json_payload_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "roll_groups",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requested_by_seat_id", sa.Uuid(), sa.ForeignKey("campaign_seats.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("label", sa.String(length=160), nullable=True),
        sa.Column("visibility", sa.String(length=24), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "visibility IN ('public', 'roller_and_dm', 'dm_only')",
            name="ck_roll_groups_visibility",
        ),
        sa.CheckConstraint("version > 0", name="ck_roll_groups_version_positive"),
    )
    op.create_index("ix_roll_groups_session_id", "roll_groups", ["session_id"])

    op.create_table(
        "roll_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("roll_group_id", sa.Uuid(), sa.ForeignKey("roll_groups.id", ondelete="CASCADE"), nullable=True),
        sa.Column("target_seat_id", sa.Uuid(), sa.ForeignKey("campaign_seats.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("target_character_id", sa.Uuid(), sa.ForeignKey("characters.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("request_type", sa.String(length=32), nullable=False),
        sa.Column("ability_ref", sa.String(length=80), nullable=True),
        sa.Column("skill_ref", sa.String(length=120), nullable=True),
        sa.Column("dc", sa.Integer(), nullable=True),
        sa.Column("modifier_mode", sa.String(length=16), nullable=False),
        sa.Column("flat_adjustment", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("visibility", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("requested_by_seat_id", sa.Uuid(), sa.ForeignKey("campaign_seats.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.CheckConstraint(
            "request_type IN ('ability', 'skill', 'saving_throw', 'other')",
            name="ck_roll_requests_request_type",
        ),
        sa.CheckConstraint(
            "modifier_mode IN ('normal', 'advantage', 'disadvantage')",
            name="ck_roll_requests_modifier_mode",
        ),
        sa.CheckConstraint(
            "visibility IN ('public', 'roller_and_dm', 'dm_only')",
            name="ck_roll_requests_visibility",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'resolved', 'cancelled')",
            name="ck_roll_requests_status",
        ),
        sa.CheckConstraint("dc IS NULL OR dc >= 0", name="ck_roll_requests_dc_nonnegative"),
        sa.CheckConstraint("version > 0", name="ck_roll_requests_version_positive"),
    )
    op.create_index("ix_roll_requests_session_status", "roll_requests", ["session_id", "status"])
    op.create_index("ix_roll_requests_group_id", "roll_requests", ["roll_group_id"])
    op.create_index("ix_roll_requests_target_seat_id", "roll_requests", ["target_seat_id"])

    op.create_table(
        "roll_results",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("roll_request_id", sa.Uuid(), sa.ForeignKey("roll_requests.id", ondelete="CASCADE"), nullable=True),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("acting_seat_id", sa.Uuid(), sa.ForeignKey("campaign_seats.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("subject_seat_id", sa.Uuid(), sa.ForeignKey("campaign_seats.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("subject_character_id", sa.Uuid(), sa.ForeignKey("characters.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("execution_mode", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("formula", sa.String(length=120), nullable=False),
        sa.Column("raw_dice", json_payload_type, nullable=False),
        sa.Column("kept_dice", json_payload_type, nullable=False),
        sa.Column("base_modifier", sa.Integer(), nullable=False),
        sa.Column("flat_adjustment", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("visibility", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "execution_mode IN ('self', 'dm_proxy', 'system')",
            name="ck_roll_results_execution_mode",
        ),
        sa.CheckConstraint(
            "source IN ('server', 'physical', 'quick')",
            name="ck_roll_results_source",
        ),
        sa.CheckConstraint(
            "visibility IN ('public', 'roller_and_dm', 'dm_only')",
            name="ck_roll_results_visibility",
        ),
        sa.CheckConstraint(
            "(source = 'quick' AND roll_request_id IS NULL) OR "
            "(source IN ('server', 'physical') AND roll_request_id IS NOT NULL)",
            name="ck_roll_results_request_binding",
        ),
        sa.UniqueConstraint("roll_request_id", name="uq_roll_results_roll_request_id"),
    )
    op.create_index("ix_roll_results_session_id", "roll_results", ["session_id"])
    op.create_index("ix_roll_results_subject_seat_id", "roll_results", ["subject_seat_id"])

    op.create_table(
        "pending_actions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("acting_seat_id", sa.Uuid(), sa.ForeignKey("campaign_seats.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("subject_seat_id", sa.Uuid(), sa.ForeignKey("campaign_seats.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("subject_character_id", sa.Uuid(), sa.ForeignKey("characters.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("execution_mode", sa.String(length=16), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("intent_payload", json_payload_type, nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
        sa.Column("roll_request_id", sa.Uuid(), sa.ForeignKey("roll_requests.id", ondelete="SET NULL"), nullable=True),
        sa.Column("window_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "execution_mode IN ('self', 'dm_proxy', 'system')",
            name="ck_pending_actions_execution_mode",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'waiting_for_roll', 'resolved', 'cancelled')",
            name="ck_pending_actions_status",
        ),
        sa.CheckConstraint(
            "text IS NOT NULL OR intent_payload IS NOT NULL",
            name="ck_pending_actions_intent_present",
        ),
        sa.CheckConstraint("version > 0", name="ck_pending_actions_version_positive"),
    )
    op.create_index("ix_pending_actions_session_status", "pending_actions", ["session_id", "status"])
    op.create_index("ix_pending_actions_roll_request_id", "pending_actions", ["roll_request_id"])


def downgrade() -> None:
    op.drop_index("ix_pending_actions_roll_request_id", table_name="pending_actions")
    op.drop_index("ix_pending_actions_session_status", table_name="pending_actions")
    op.drop_table("pending_actions")
    op.drop_index("ix_roll_results_subject_seat_id", table_name="roll_results")
    op.drop_index("ix_roll_results_session_id", table_name="roll_results")
    op.drop_table("roll_results")
    op.drop_index("ix_roll_requests_target_seat_id", table_name="roll_requests")
    op.drop_index("ix_roll_requests_group_id", table_name="roll_requests")
    op.drop_index("ix_roll_requests_session_status", table_name="roll_requests")
    op.drop_table("roll_requests")
    op.drop_index("ix_roll_groups_session_id", table_name="roll_groups")
    op.drop_table("roll_groups")
