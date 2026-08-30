"""P1-G confirmed-version provenance for versioned builder drafts.

Revision ID: 0005_p1g_character_versions
Revises: 0004_p1f_character_creation
Create Date: 2026-08-30
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005_p1g_character_versions"
down_revision: Union[str, Sequence[str], None] = "0004_p1f_character_creation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("character_build_drafts") as batch_op:
        batch_op.add_column(sa.Column("confirmed_version_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_character_build_drafts_confirmed_version_id",
            "character_versions",
            ["confirmed_version_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_character_build_drafts_confirmed_version_id",
            ["confirmed_version_id"],
            unique=False,
        )

    # P1-F is the only code that could have confirmed a Builder draft before this
    # migration, and it created Version 1 in the same atomic transaction. Backfill
    # those rows so P1-G can clone exact Builder provenance instead of reverse-
    # engineering the resolved Build snapshot.
    connection = op.get_bind()
    dialect = connection.dialect.name
    if dialect in {"sqlite", "postgresql"}:
        connection.execute(
            sa.text(
                """
                UPDATE character_build_drafts
                SET confirmed_version_id = (
                    SELECT cv.id
                    FROM character_versions AS cv
                    WHERE cv.character_id = character_build_drafts.confirmed_character_id
                      AND cv.version_no = 1
                )
                WHERE confirmed_character_id IS NOT NULL
                  AND confirmed_version_id IS NULL
                """
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("character_build_drafts") as batch_op:
        batch_op.drop_index("ix_character_build_drafts_confirmed_version_id")
        batch_op.drop_constraint(
            "fk_character_build_drafts_confirmed_version_id",
            type_="foreignkey",
        )
        batch_op.drop_column("confirmed_version_id")
