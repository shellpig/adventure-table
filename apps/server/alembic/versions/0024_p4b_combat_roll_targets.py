"""Add P4-B CombatEntry targets to the existing formal roll substrate.

Revision ID: 0024_p4b_combat_roll_targets
Revises: 0023_p4b_combat_lifecycle
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0024_p4b_combat_roll_targets"
down_revision = "0023_p4b_combat_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("roll_requests") as batch:
        batch.alter_column("target_seat_id", existing_type=sa.Uuid(), nullable=True)
        batch.add_column(sa.Column("target_combat_entry_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_roll_requests_target_combat_entry_id",
            "combat_entries",
            ["target_combat_entry_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_check_constraint(
            "ck_roll_requests_target_present",
            "target_seat_id IS NOT NULL OR target_combat_entry_id IS NOT NULL",
        )
        batch.create_index(
            "ix_roll_requests_target_combat_entry_id",
            ["target_combat_entry_id"],
        )

    with op.batch_alter_table("roll_results") as batch:
        batch.alter_column("subject_seat_id", existing_type=sa.Uuid(), nullable=True)
        batch.add_column(sa.Column("subject_combat_entry_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_roll_results_subject_combat_entry_id",
            "combat_entries",
            ["subject_combat_entry_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_index(
            "ix_roll_results_subject_combat_entry_id",
            ["subject_combat_entry_id"],
        )


def downgrade() -> None:
    connection = op.get_bind()
    seatless_requests = connection.execute(
        sa.text(
            "SELECT COUNT(*) FROM roll_requests "
            "WHERE target_seat_id IS NULL AND target_combat_entry_id IS NOT NULL"
        )
    ).scalar_one()
    seatless_results = connection.execute(
        sa.text(
            "SELECT COUNT(*) FROM roll_results "
            "WHERE subject_seat_id IS NULL AND subject_combat_entry_id IS NOT NULL"
        )
    ).scalar_one()
    if seatless_requests or seatless_results:
        raise RuntimeError(
            "cannot downgrade P4-B Combat roll targets while seatless Monster initiative rolls exist"
        )

    with op.batch_alter_table("roll_results") as batch:
        batch.drop_index("ix_roll_results_subject_combat_entry_id")
        batch.drop_constraint("fk_roll_results_subject_combat_entry_id", type_="foreignkey")
        batch.drop_column("subject_combat_entry_id")
        batch.alter_column("subject_seat_id", existing_type=sa.Uuid(), nullable=False)

    with op.batch_alter_table("roll_requests") as batch:
        batch.drop_index("ix_roll_requests_target_combat_entry_id")
        batch.drop_constraint("ck_roll_requests_target_present", type_="check")
        batch.drop_constraint("fk_roll_requests_target_combat_entry_id", type_="foreignkey")
        batch.drop_column("target_combat_entry_id")
        batch.alter_column("target_seat_id", existing_type=sa.Uuid(), nullable=False)
