"""Allow P3-C /check provenance on canonical Exploration messages.

Revision ID: 0019_p3c_check_command
Revises: 0018_p3c_roll_pending
"""

from __future__ import annotations

from alembic import op


revision = "0019_p3c_check_command"
down_revision = "0018_p3c_roll_pending"
branch_labels = None
depends_on = None


_SOURCE_COMMAND_CONSTRAINT = "ck_session_messages_source_command"


def upgrade() -> None:
    with op.batch_alter_table("session_messages") as batch_op:
        batch_op.drop_constraint(_SOURCE_COMMAND_CONSTRAINT, type_="check")
        batch_op.create_check_constraint(
            _SOURCE_COMMAND_CONSTRAINT,
            "source_command IS NULL OR source_command IN ('search', 'check')",
        )


def downgrade() -> None:
    # P3-B cannot represent /check provenance. Normalize P3-C rows before the
    # narrower constraint is restored so a real database can downgrade safely.
    op.execute("UPDATE session_messages SET source_command = NULL WHERE source_command = 'check'")
    with op.batch_alter_table("session_messages") as batch_op:
        batch_op.drop_constraint(_SOURCE_COMMAND_CONSTRAINT, type_="check")
        batch_op.create_check_constraint(
            _SOURCE_COMMAND_CONSTRAINT,
            "source_command IS NULL OR source_command = 'search'",
        )
