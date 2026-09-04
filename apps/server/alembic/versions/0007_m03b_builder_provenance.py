"""Persist Builder provenance on immutable Character Versions.

Revision ID: 0007_m03b_builder_provenance
Revises: 0006_character_archive
Create Date: 2026-09-04
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0007_m03b_builder_provenance"
down_revision: Union[str, Sequence[str], None] = "0006_character_archive"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


json_payload_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    # Existing versions intentionally remain NULL: only Confirm operations from
    # M03-B onward have an exact BuilderDraftPayload snapshot to preserve.
    with op.batch_alter_table("character_versions") as batch_op:
        batch_op.add_column(
            sa.Column("builder_provenance", json_payload_type, nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("character_versions") as batch_op:
        batch_op.drop_column("builder_provenance")
