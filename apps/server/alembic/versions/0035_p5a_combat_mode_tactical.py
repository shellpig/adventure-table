"""Widen combats.mode check to allow tactical mode (P5-A).

Revision ID: 0035_p5a_combat_mode_tactical
Revises: 0034_m06b_event_actor_stamp
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0035_p5a_combat_mode_tactical"
down_revision = "0034_m06b_event_actor_stamp"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("combats") as batch_op:
        batch_op.drop_constraint("ck_combats_mode_quick", type_="check")
        batch_op.create_check_constraint(
            "ck_combats_mode",
            "mode IN ('quick', 'tactical')",
        )


def downgrade() -> None:
    bind = op.get_bind()
    tactical_exists = bind.execute(
        sa.text("SELECT 1 FROM combats WHERE mode = 'tactical' LIMIT 1")
    ).first()
    if tactical_exists is not None:
        raise RuntimeError(
            "Cannot downgrade 0035_p5a_combat_mode_tactical while "
            "tactical combats exist; resolve or delete them first."
        )
    with op.batch_alter_table("combats") as batch_op:
        batch_op.drop_constraint("ck_combats_mode", type_="check")
        batch_op.create_check_constraint(
            "ck_combats_mode_quick",
            "mode = 'quick'",
        )
