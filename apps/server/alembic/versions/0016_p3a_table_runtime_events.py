"""Add P3-A durable Session table runtime and ordered events.

Revision ID: 0016_p3a_table_runtime_events
Revises: 0014_p2e_sessions
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0016_p3a_table_runtime_events"
down_revision = "0014_p2e_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "session_table_runtime",
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("revision", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("last_event_seq", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "revision >= 0",
            name="ck_session_table_runtime_revision_nonnegative",
        ),
        sa.CheckConstraint(
            "last_event_seq >= 0",
            name="ck_session_table_runtime_last_event_seq_nonnegative",
        ),
    )

    op.create_table(
        "session_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=80), nullable=False),
        sa.Column(
            "acting_seat_id",
            sa.Uuid(),
            sa.ForeignKey("campaign_seats.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "subject_seat_id",
            sa.Uuid(),
            sa.ForeignKey("campaign_seats.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "subject_character_id",
            sa.Uuid(),
            sa.ForeignKey("characters.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("execution_mode", sa.String(length=16), nullable=True),
        sa.Column("visibility", sa.String(length=24), nullable=False),
        sa.Column(
            "recipient_seat_ids",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column("payload_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("seq > 0", name="ck_session_events_seq_positive"),
        sa.CheckConstraint(
            "payload_version > 0",
            name="ck_session_events_payload_version_positive",
        ),
        sa.CheckConstraint(
            "visibility IN ('public', 'dm_only', 'actor_and_dm', 'seat_private')",
            name="ck_session_events_visibility",
        ),
        sa.CheckConstraint(
            "execution_mode IS NULL OR execution_mode IN ('self', 'dm_proxy', 'system')",
            name="ck_session_events_execution_mode",
        ),
        sa.UniqueConstraint(
            "session_id",
            "seq",
            name="uq_session_events_session_seq",
        ),
        sa.UniqueConstraint(
            "session_id",
            "idempotency_key",
            name="uq_session_events_session_idempotency",
        ),
    )
    op.create_index(
        "ix_session_events_session_seq",
        "session_events",
        ["session_id", "seq"],
    )

    # Existing P2 Sessions get an explicit zero cursor. Sessions created after
    # this migration are initialized lazily by the first P3 read/write while the
    # Session row is locked, so P2 Session creation stays independent of P3.
    op.execute(
        """
        INSERT INTO session_table_runtime (session_id, revision, last_event_seq)
        SELECT id, 0, 0
        FROM sessions
        """
    )


def downgrade() -> None:
    op.drop_index("ix_session_events_session_seq", table_name="session_events")
    op.drop_table("session_events")
    op.drop_table("session_table_runtime")
