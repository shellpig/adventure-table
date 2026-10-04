"""Add archived_at to battle_maps and change combat_boards.source_battle_map_id FK to RESTRICT (M07-B).

Revision ID: 0042_m07b_battle_map_lifecycle
Revises: 0041_m07a_room_monster_templates
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0042_m07b_battle_map_lifecycle"
down_revision = "0041_m07a_room_monster_templates"
branch_labels = None
depends_on = None

NAMING_CONVENTION = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "ix": "ix_%(table_name)s_%(column_0_name)s",
}


def upgrade() -> None:
    connection = op.get_bind()
    dialect = connection.dialect.name

    if dialect == "postgresql":
        op.add_column(
            "battle_maps",
            sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index(
            "ix_battle_maps_room_archived_created",
            "battle_maps",
            ["room_id", "archived_at", "created_at"],
        )

        connection.execute(
            sa.text(
                """
                DO $$
                DECLARE
                    r RECORD;
                BEGIN
                    FOR r IN (
                        SELECT constraint_name
                        FROM information_schema.key_column_usage
                        WHERE table_name = 'combat_boards'
                          AND column_name = 'source_battle_map_id'
                          AND position_in_unique_constraint IS NOT NULL
                    ) LOOP
                        EXECUTE 'ALTER TABLE combat_boards DROP CONSTRAINT ' || quote_ident(r.constraint_name);
                    END LOOP;
                END $$;
                """
            )
        )
        op.create_foreign_key(
            "fk_combat_boards_source_battle_map_id_battle_maps",
            "combat_boards",
            "battle_maps",
            ["source_battle_map_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    else:
        with op.batch_alter_table(
            "battle_maps", naming_convention=NAMING_CONVENTION
        ) as batch_op:
            batch_op.add_column(
                sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True)
            )
            batch_op.create_index(
                "ix_battle_maps_room_archived_created",
                ["room_id", "archived_at", "created_at"],
            )

        with op.batch_alter_table(
            "combat_boards", naming_convention=NAMING_CONVENTION
        ) as batch_op:
            batch_op.drop_constraint(
                "fk_combat_boards_source_battle_map_id_battle_maps",
                type_="foreignkey",
            )
            batch_op.create_foreign_key(
                "fk_combat_boards_source_battle_map_id_battle_maps",
                "battle_maps",
                ["source_battle_map_id"],
                ["id"],
                ondelete="RESTRICT",
            )


def downgrade() -> None:
    connection = op.get_bind()
    dialect = connection.dialect.name

    if dialect == "postgresql":
        op.drop_constraint(
            "fk_combat_boards_source_battle_map_id_battle_maps",
            "combat_boards",
            type_="foreignkey",
        )
        op.create_foreign_key(
            "combat_boards_source_battle_map_id_fkey",
            "combat_boards",
            "battle_maps",
            ["source_battle_map_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.drop_index(
            "ix_battle_maps_room_archived_created",
            table_name="battle_maps",
        )
        op.drop_column("battle_maps", "archived_at")
    else:
        with op.batch_alter_table(
            "combat_boards", naming_convention=NAMING_CONVENTION
        ) as batch_op:
            batch_op.drop_constraint(
                "fk_combat_boards_source_battle_map_id_battle_maps",
                type_="foreignkey",
            )
            batch_op.create_foreign_key(
                "fk_combat_boards_source_battle_map_id_battle_maps",
                "battle_maps",
                ["source_battle_map_id"],
                ["id"],
                ondelete="SET NULL",
            )

        with op.batch_alter_table(
            "battle_maps", naming_convention=NAMING_CONVENTION
        ) as batch_op:
            batch_op.drop_index("ix_battle_maps_room_archived_created")
            batch_op.drop_column("archived_at")
