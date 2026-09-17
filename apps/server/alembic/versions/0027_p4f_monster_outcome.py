"""Widen combat_entries.status and monster_instances.combat_status constraints for P4-F monster outcomes.

Revision ID: 0027_p4f_monster_outcome
Revises: 0026_p4e_monster_concentration
"""

from __future__ import annotations

from alembic import op


revision = "0027_p4f_monster_outcome"
down_revision = "0026_p4e_monster_concentration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("combat_entries") as batch:
        batch.drop_constraint("ck_combat_entries_status", type_="check")
        batch.create_check_constraint(
            "ck_combat_entries_status",
            "status IN ('active', 'withdrawn', 'removed', 'dead', 'unconscious', 'surrendered', 'fled')",
        )

    with op.batch_alter_table("monster_instances") as batch:
        batch.drop_constraint("ck_monster_instances_combat_status", type_="check")
        batch.create_check_constraint(
            "ck_monster_instances_combat_status",
            "combat_status IN ('active', 'down', 'dead', 'removed', 'unconscious', 'surrendered', 'fled')",
        )


def downgrade() -> None:
    with op.batch_alter_table("monster_instances") as batch:
        batch.drop_constraint("ck_monster_instances_combat_status", type_="check")
        batch.create_check_constraint(
            "ck_monster_instances_combat_status",
            "combat_status IN ('active', 'down', 'dead', 'removed')",
        )

    with op.batch_alter_table("combat_entries") as batch:
        batch.drop_constraint("ck_combat_entries_status", type_="check")
        batch.create_check_constraint(
            "ck_combat_entries_status",
            "status IN ('active', 'withdrawn', 'removed')",
        )
