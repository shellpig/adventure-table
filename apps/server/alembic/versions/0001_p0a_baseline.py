"""P0-A baseline migration.

Revision ID: 0001_p0a_baseline
Revises:
Create Date: 2026-08-29
"""

from typing import Sequence, Union

revision: str = "0001_p0a_baseline"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # P0-A intentionally creates no domain tables.
    pass


def downgrade() -> None:
    pass
