"""Allow Normal terrain on Battle Map definitions (P5-G).

Revision ID: 0040_p5g_terrain_normal
Revises: 0039_p5e_disengaged

The P5 design lists terrain_kind = normal | difficult | blocked, but P5-A only
admitted difficult and blocked. A DM who paints a cell back to Normal in the
editor stores it as `normal`, which the rules treat exactly like an unpainted
cell (no extra movement cost, not blocking). Downgrade removes those rows, since
the old constraint cannot hold them and they carry no rule meaning.
"""

from __future__ import annotations

from alembic import op


revision = "0040_p5g_terrain_normal"
down_revision = "0039_p5e_disengaged"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("battle_map_terrain") as batch_op:
        batch_op.drop_constraint("ck_battle_map_terrain_kind", type_="check")
        batch_op.create_check_constraint(
            "ck_battle_map_terrain_kind",
            "terrain_kind IN ('normal', 'difficult', 'blocked')",
        )


def downgrade() -> None:
    op.execute("DELETE FROM battle_map_terrain WHERE terrain_kind = 'normal'")
    with op.batch_alter_table("battle_map_terrain") as batch_op:
        batch_op.drop_constraint("ck_battle_map_terrain_kind", type_="check")
        batch_op.create_check_constraint(
            "ck_battle_map_terrain_kind",
            "terrain_kind IN ('difficult', 'blocked')",
        )
