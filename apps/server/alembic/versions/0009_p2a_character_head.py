"""Start the shared Character migration track after the M03 branch point.

Revision ID: 0009_p2a_character_head
Revises: 0008_m03c_import_records
"""

from __future__ import annotations


revision = "0009_p2a_character_head"
down_revision = "0008_m03c_import_records"
branch_labels = ("character",)
depends_on = None


def upgrade() -> None:
    """P2-A creates the Character branch without changing shared schema."""


def downgrade() -> None:
    """No schema objects were added by this branch marker."""
