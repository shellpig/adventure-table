"""Add P4-C durable resolution bookkeeping.

Revision ID: 0025_p4c_core_resolution
Revises: 0024_p4b_combat_roll_targets
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0025_p4c_core_resolution"
down_revision = "0024_p4b_combat_roll_targets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("combat_entries") as batch:
        batch.add_column(sa.Column("death_save_successes", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("death_save_failures", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("death_save_stable", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("death_save_dead", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.create_check_constraint(
            "ck_combat_entries_death_save_successes",
            "death_save_successes >= 0 AND death_save_successes <= 2",
        )
        batch.create_check_constraint(
            "ck_combat_entries_death_save_failures",
            "death_save_failures >= 0 AND death_save_failures <= 2",
        )
        batch.create_check_constraint(
            "ck_combat_entries_death_save_terminal",
            "NOT (death_save_stable AND death_save_dead)",
        )

    with op.batch_alter_table("combat_actions") as batch:
        batch.add_column(sa.Column("target_entry_id", sa.Uuid(), nullable=True))
        batch.add_column(
            sa.Column(
                "resolution_status",
                sa.String(length=32),
                nullable=False,
                server_default="resolved",
            )
        )
        batch.add_column(sa.Column("roll_request_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("roll_result_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("resolution_result", sa.JSON(), nullable=True))
        batch.create_foreign_key(
            "fk_combat_actions_target_entry_id",
            "combat_entries",
            ["target_entry_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_check_constraint(
            "ck_combat_actions_resolution_status",
            "resolution_status IN ('waiting_for_roll', 'dm_adjudication_required', 'resolved', 'cancelled')",
        )
        batch.create_index("ix_combat_actions_target_entry_id", ["target_entry_id"])
        batch.create_index("ix_combat_actions_roll_request_id", ["roll_request_id"])


def downgrade() -> None:
    with op.batch_alter_table("combat_actions") as batch:
        batch.drop_index("ix_combat_actions_roll_request_id")
        batch.drop_index("ix_combat_actions_target_entry_id")
        batch.drop_constraint("ck_combat_actions_resolution_status", type_="check")
        batch.drop_constraint("fk_combat_actions_target_entry_id", type_="foreignkey")
        batch.drop_column("resolution_result")
        batch.drop_column("roll_result_id")
        batch.drop_column("roll_request_id")
        batch.drop_column("resolution_status")
        batch.drop_column("target_entry_id")

    with op.batch_alter_table("combat_entries") as batch:
        batch.drop_constraint("ck_combat_entries_death_save_terminal", type_="check")
        batch.drop_constraint("ck_combat_entries_death_save_failures", type_="check")
        batch.drop_constraint("ck_combat_entries_death_save_successes", type_="check")
        batch.drop_column("death_save_dead")
        batch.drop_column("death_save_stable")
        batch.drop_column("death_save_failures")
        batch.drop_column("death_save_successes")
