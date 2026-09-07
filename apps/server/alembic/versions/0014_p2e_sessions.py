"""Add P2-E Session lifecycle persistence.

Revision ID: 0014_p2e_sessions
Revises: 0013_p2d_campaign_seats
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0014_p2e_sessions"
down_revision = "0013_p2d_campaign_seats"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "campaign_id",
            sa.Uuid(),
            sa.ForeignKey("campaigns.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "dm_seat_id",
            sa.Uuid(),
            sa.ForeignKey("campaign_seats.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("dm_controller_kind", sa.String(length=16), nullable=False),
        sa.Column(
            "dm_controller_access_session_id",
            sa.Uuid(),
            sa.ForeignKey("room_access_sessions.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('active', 'ended', 'abandoned')",
            name="ck_sessions_status",
        ),
        sa.CheckConstraint(
            "(dm_controller_kind = 'human' AND dm_controller_access_session_id IS NOT NULL) OR "
            "(dm_controller_kind IN ('ai', 'none') AND dm_controller_access_session_id IS NULL)",
            name="ck_sessions_dm_controller_binding",
        ),
    )
    op.create_index("ix_sessions_campaign_id", "sessions", ["campaign_id"])
    op.create_index("ix_sessions_dm_seat_id", "sessions", ["dm_seat_id"])
    op.create_index(
        "ix_sessions_dm_controller_access_session_id",
        "sessions",
        ["dm_controller_access_session_id"],
    )
    op.create_index("ix_sessions_status", "sessions", ["status"])

    op.create_table(
        "session_participants",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "seat_id",
            sa.Uuid(),
            sa.ForeignKey("campaign_seats.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("role_snapshot", sa.String(length=16), nullable=False),
        sa.Column("controller_kind_at_join", sa.String(length=16), nullable=False),
        sa.Column(
            "controller_access_session_id_at_join",
            sa.Uuid(),
            sa.ForeignKey("room_access_sessions.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "active_character_id",
            sa.Uuid(),
            sa.ForeignKey("characters.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "role_snapshot IN ('dm', 'player', 'spectator')",
            name="ck_session_participants_role_snapshot",
        ),
        sa.CheckConstraint(
            "controller_kind_at_join IN ('human', 'ai', 'none')",
            name="ck_session_participants_controller_kind",
        ),
        sa.CheckConstraint(
            "(controller_kind_at_join = 'human' AND controller_access_session_id_at_join IS NOT NULL) OR "
            "(controller_kind_at_join IN ('ai', 'none') AND controller_access_session_id_at_join IS NULL)",
            name="ck_session_participants_controller_binding",
        ),
        sa.CheckConstraint(
            "role_snapshot = 'player' OR active_character_id IS NULL",
            name="ck_session_participants_player_character_only",
        ),
        sa.UniqueConstraint("session_id", "seat_id", name="uq_session_participants_session_seat"),
        sa.UniqueConstraint(
            "session_id",
            "active_character_id",
            name="uq_session_participants_session_character",
        ),
    )
    op.create_index("ix_session_participants_session_id", "session_participants", ["session_id"])
    op.create_index("ix_session_participants_seat_id", "session_participants", ["seat_id"])
    op.create_index(
        "ix_session_participants_active_character_id",
        "session_participants",
        ["active_character_id"],
    )

    op.create_table(
        "active_character_session_leases",
        sa.Column(
            "character_id",
            sa.Uuid(),
            sa.ForeignKey("characters.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "participant_id",
            sa.Uuid(),
            sa.ForeignKey("session_participants.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
    )
    op.create_index(
        "ix_active_character_session_leases_session_id",
        "active_character_session_leases",
        ["session_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_active_character_session_leases_session_id",
        table_name="active_character_session_leases",
    )
    op.drop_table("active_character_session_leases")
    op.drop_index("ix_session_participants_active_character_id", table_name="session_participants")
    op.drop_index("ix_session_participants_seat_id", table_name="session_participants")
    op.drop_index("ix_session_participants_session_id", table_name="session_participants")
    op.drop_table("session_participants")
    op.drop_index("ix_sessions_status", table_name="sessions")
    op.drop_index("ix_sessions_dm_controller_access_session_id", table_name="sessions")
    op.drop_index("ix_sessions_dm_seat_id", table_name="sessions")
    op.drop_index("ix_sessions_campaign_id", table_name="sessions")
    op.drop_table("sessions")
