"""Migrate monster_templates to room scope and set monster_instances custom_template_id to RESTRICT (M07-A).

Revision ID: 0041_m07a_room_monster_templates
Revises: 0040_p5g_terrain_normal
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0041_m07a_room_monster_templates"
down_revision = "0040_p5g_terrain_normal"
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
        op.add_column("monster_templates", sa.Column("room_id", sa.Uuid(), nullable=True))
        op.add_column(
            "monster_templates",
            sa.Column("revision", sa.BigInteger(), nullable=False, server_default="1"),
        )
        op.add_column(
            "monster_templates",
            sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.add_column(
            "monster_templates",
            sa.Column(
                "presentation_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            ),
        )

        connection.execute(
            sa.text(
                """
                UPDATE monster_templates
                SET room_id = (
                    SELECT campaigns.room_id
                    FROM campaigns
                    WHERE campaigns.id = monster_templates.campaign_id
                )
                WHERE monster_templates.room_id IS NULL
                """
            )
        )

        op.alter_column("monster_templates", "room_id", nullable=False)
        op.create_foreign_key(
            "fk_monster_templates_room_id_rooms",
            "monster_templates",
            "rooms",
            ["room_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.drop_index("ix_monster_templates_campaign_id", table_name="monster_templates")
        op.execute(
            "ALTER TABLE monster_templates DROP CONSTRAINT IF EXISTS monster_templates_campaign_id_fkey"
        )
        op.drop_column("monster_templates", "campaign_id")
        op.create_check_constraint(
            "ck_monster_templates_revision_positive",
            "monster_templates",
            "revision > 0",
        )
        op.create_index(
            "ix_monster_templates_room_id",
            "monster_templates",
            ["room_id"],
        )
        op.create_index(
            "ix_monster_templates_room_archived_name",
            "monster_templates",
            ["room_id", "archived_at", "name"],
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
                        WHERE table_name = 'monster_instances'
                          AND column_name = 'custom_template_id'
                          AND position_in_unique_constraint IS NOT NULL
                    ) LOOP
                        EXECUTE 'ALTER TABLE monster_instances DROP CONSTRAINT ' || quote_ident(r.constraint_name);
                    END LOOP;
                END $$;
                """
            )
        )
        op.create_foreign_key(
            "fk_monster_instances_custom_template_id_monster_templates",
            "monster_instances",
            "monster_templates",
            ["custom_template_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    else:
        with op.batch_alter_table(
            "monster_templates", naming_convention=NAMING_CONVENTION
        ) as batch_op:
            batch_op.add_column(sa.Column("room_id", sa.Uuid(), nullable=True))
            batch_op.add_column(
                sa.Column("revision", sa.BigInteger(), nullable=False, server_default="1")
            )
            batch_op.add_column(
                sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True)
            )
            batch_op.add_column(
                sa.Column(
                    "presentation_json",
                    sa.JSON(),
                    nullable=False,
                    server_default=sa.text("'{}'"),
                )
            )

        connection.execute(
            sa.text(
                """
                UPDATE monster_templates
                SET room_id = (
                    SELECT campaigns.room_id
                    FROM campaigns
                    WHERE campaigns.id = monster_templates.campaign_id
                )
                WHERE monster_templates.room_id IS NULL
                """
            )
        )

        with op.batch_alter_table(
            "monster_templates", naming_convention=NAMING_CONVENTION
        ) as batch_op:
            batch_op.drop_index("ix_monster_templates_campaign_id")
            batch_op.drop_constraint(
                "fk_monster_templates_campaign_id_campaigns", type_="foreignkey"
            )
            batch_op.drop_column("campaign_id")
            batch_op.alter_column("room_id", nullable=False)
            batch_op.create_foreign_key(
                "fk_monster_templates_room_id_rooms",
                "rooms",
                ["room_id"],
                ["id"],
                ondelete="CASCADE",
            )
            batch_op.create_check_constraint(
                "revision_positive",
                "revision > 0",
            )
            batch_op.create_index("ix_monster_templates_room_id", ["room_id"])
            batch_op.create_index(
                "ix_monster_templates_room_archived_name",
                ["room_id", "archived_at", "name"],
            )

        with op.batch_alter_table(
            "monster_instances", naming_convention=NAMING_CONVENTION
        ) as batch_op:
            batch_op.drop_constraint(
                "fk_monster_instances_custom_template_id_monster_templates",
                type_="foreignkey",
            )
            batch_op.create_foreign_key(
                "fk_monster_instances_custom_template_id_monster_templates",
                "monster_templates",
                ["custom_template_id"],
                ["id"],
                ondelete="RESTRICT",
            )


def downgrade() -> None:
    connection = op.get_bind()
    dialect = connection.dialect.name

    if dialect == "postgresql":
        op.drop_constraint(
            "fk_monster_instances_custom_template_id_monster_templates",
            "monster_instances",
            type_="foreignkey",
        )
        op.create_foreign_key(
            "monster_instances_custom_template_id_fkey",
            "monster_instances",
            "monster_templates",
            ["custom_template_id"],
            ["id"],
            ondelete="SET NULL",
        )

        op.add_column("monster_templates", sa.Column("campaign_id", sa.Uuid(), nullable=True))
        connection.execute(
            sa.text(
                """
                UPDATE monster_templates
                SET campaign_id = (
                    SELECT campaigns.id
                    FROM campaigns
                    WHERE campaigns.room_id = monster_templates.room_id
                    LIMIT 1
                )
                WHERE monster_templates.campaign_id IS NULL
                """
            )
        )
        op.alter_column("monster_templates", "campaign_id", nullable=False)
        op.create_foreign_key(
            "monster_templates_campaign_id_fkey",
            "monster_templates",
            "campaigns",
            ["campaign_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.create_index(
            "ix_monster_templates_campaign_id",
            "monster_templates",
            ["campaign_id"],
        )
        op.drop_index("ix_monster_templates_room_archived_name", table_name="monster_templates")
        op.drop_index("ix_monster_templates_room_id", table_name="monster_templates")
        op.drop_constraint(
            "ck_monster_templates_revision_positive",
            "monster_templates",
            type_="check",
        )
        op.drop_constraint(
            "fk_monster_templates_room_id_rooms",
            "monster_templates",
            type_="foreignkey",
        )
        op.drop_column("monster_templates", "presentation_json")
        op.drop_column("monster_templates", "archived_at")
        op.drop_column("monster_templates", "revision")
        op.drop_column("monster_templates", "room_id")
    else:
        with op.batch_alter_table(
            "monster_templates", naming_convention=NAMING_CONVENTION
        ) as batch_op:
            batch_op.add_column(sa.Column("campaign_id", sa.Uuid(), nullable=True))

        connection.execute(
            sa.text(
                """
                UPDATE monster_templates
                SET campaign_id = (
                    SELECT campaigns.id
                    FROM campaigns
                    WHERE campaigns.room_id = monster_templates.room_id
                    LIMIT 1
                )
                WHERE monster_templates.campaign_id IS NULL
                """
            )
        )

        with op.batch_alter_table(
            "monster_templates", naming_convention=NAMING_CONVENTION
        ) as batch_op:
            batch_op.drop_index("ix_monster_templates_room_archived_name")
            batch_op.drop_index("ix_monster_templates_room_id")
            batch_op.drop_constraint("ck_monster_templates_revision_positive", type_="check")
            batch_op.drop_constraint("fk_monster_templates_room_id_rooms", type_="foreignkey")
            batch_op.drop_column("presentation_json")
            batch_op.drop_column("archived_at")
            batch_op.drop_column("revision")
            batch_op.drop_column("room_id")
            batch_op.alter_column("campaign_id", nullable=False)
            batch_op.create_foreign_key(
                "fk_monster_templates_campaign_id_campaigns",
                "campaigns",
                ["campaign_id"],
                ["id"],
                ondelete="CASCADE",
            )
            batch_op.create_index("ix_monster_templates_campaign_id", ["campaign_id"])

        with op.batch_alter_table(
            "monster_instances", naming_convention=NAMING_CONVENTION
        ) as batch_op:
            batch_op.drop_constraint(
                "fk_monster_instances_custom_template_id_monster_templates",
                type_="foreignkey",
            )
            batch_op.create_foreign_key(
                "fk_monster_instances_custom_template_id_monster_templates",
                "monster_templates",
                ["custom_template_id"],
                ["id"],
                ondelete="SET NULL",
            )
