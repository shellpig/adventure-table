"""Add P3-D AI controller grants and current-controller epochs.

Revision ID: 0020_p3d_ai_controller_grants
Revises: 0019_p3c_check_command
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0020_p3d_ai_controller_grants"
down_revision = "0019_p3c_check_command"
branch_labels = None
depends_on = None


SEAT_BINDING = "ck_campaign_seats_controller_binding"
SESSION_BINDING = "ck_sessions_dm_controller_binding"
PARTICIPANT_BINDING = "ck_session_participants_controller_binding"
SEAT_GRANT_FK = "fk_campaign_seats_ai_grant"
SESSION_GRANT_FK = "fk_sessions_dm_ai_grant"
PARTICIPANT_GRANT_FK = "fk_session_participants_ai_grant"
SEAT_GRANT_INDEX = "ix_campaign_seats_ai_controller_grant_id"
SESSION_GRANT_INDEX = "ix_sessions_dm_controller_ai_grant_id"
PARTICIPANT_GRANT_INDEX = "ix_session_participants_controller_ai_grant_id"


def upgrade() -> None:
    op.create_table(
        "ai_controller_grants",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("room_id", sa.Uuid(), sa.ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seat_id", sa.Uuid(), sa.ForeignKey("campaign_seats.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=True),
        sa.Column("secret_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("secret_prefix", sa.String(length=80), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("pre_session_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "handoff_return_access_session_id",
            sa.Uuid(),
            sa.ForeignKey("room_access_sessions.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("temporary_instruction", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("bound_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("role IN ('dm', 'player')", name="ck_ai_controller_grants_role"),
        sa.CheckConstraint("status IN ('active', 'revoked')", name="ck_ai_controller_grants_status"),
        sa.CheckConstraint("generation >= 1", name="ck_ai_controller_grants_generation"),
        sa.CheckConstraint(
            "(role = 'player' AND session_id IS NOT NULL AND pre_session_expires_at IS NULL "
            "AND handoff_return_access_session_id IS NOT NULL) OR "
            "(role = 'dm' AND handoff_return_access_session_id IS NULL AND "
            "((session_id IS NULL AND pre_session_expires_at IS NOT NULL) OR "
            "(session_id IS NOT NULL AND pre_session_expires_at IS NULL)))",
            name="ck_ai_controller_grants_scope",
        ),
        sa.UniqueConstraint("secret_hash", name="uq_ai_controller_grants_secret_hash"),
    )
    op.create_index("ix_ai_controller_grants_seat_status", "ai_controller_grants", ["seat_id", "status"])
    op.create_index("ix_ai_controller_grants_session_status", "ai_controller_grants", ["session_id", "status"])
    op.create_index("ix_ai_controller_grants_campaign_id", "ai_controller_grants", ["campaign_id"])

    with op.batch_alter_table("campaign_seats") as batch_op:
        batch_op.add_column(sa.Column("ai_controller_grant_id", sa.Uuid(), nullable=True))
        batch_op.add_column(
            sa.Column("controller_epoch", sa.BigInteger(), nullable=False, server_default=sa.text("0"))
        )
        batch_op.create_foreign_key(
            SEAT_GRANT_FK,
            "ai_controller_grants",
            ["ai_controller_grant_id"],
            ["id"],
            ondelete="SET NULL",
        )

    # P2 exposed controller_kind='ai' as a reserved placeholder, but there was
    # no credential or grant identity that could safely be upgraded. Such rows
    # become unbound Seats rather than fabricating a bearer credential.
    op.execute(
        "UPDATE campaign_seats SET controller_kind = 'none', controller_access_session_id = NULL "
        "WHERE controller_kind = 'ai'"
    )
    op.execute(
        "UPDATE sessions SET dm_controller_kind = 'none', dm_controller_access_session_id = NULL "
        "WHERE dm_controller_kind = 'ai'"
    )
    op.execute(
        "UPDATE session_participants SET controller_kind_at_join = 'none', "
        "controller_access_session_id_at_join = NULL WHERE controller_kind_at_join = 'ai'"
    )

    with op.batch_alter_table("campaign_seats") as batch_op:
        batch_op.drop_constraint(SEAT_BINDING, type_="check")
        batch_op.create_check_constraint(
            SEAT_BINDING,
            "controller_epoch IS NOT NULL AND ("
            "(controller_kind = 'human' AND controller_access_session_id IS NOT NULL AND ai_controller_grant_id IS NULL) OR "
            "(controller_kind = 'ai' AND controller_access_session_id IS NULL AND ai_controller_grant_id IS NOT NULL) OR "
            "(controller_kind = 'none' AND controller_access_session_id IS NULL AND ai_controller_grant_id IS NULL))",
        )
    op.create_index(SEAT_GRANT_INDEX, "campaign_seats", ["ai_controller_grant_id"])

    with op.batch_alter_table("sessions") as batch_op:
        batch_op.add_column(sa.Column("dm_controller_ai_grant_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("dm_controller_generation", sa.BigInteger(), nullable=True))
        batch_op.create_foreign_key(
            SESSION_GRANT_FK,
            "ai_controller_grants",
            ["dm_controller_ai_grant_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.drop_constraint(SESSION_BINDING, type_="check")
        batch_op.create_check_constraint(
            SESSION_BINDING,
            "(dm_controller_kind = 'human' AND dm_controller_access_session_id IS NOT NULL "
            "AND dm_controller_ai_grant_id IS NULL AND dm_controller_generation IS NULL) OR "
            "(dm_controller_kind = 'ai' AND dm_controller_access_session_id IS NULL "
            "AND dm_controller_ai_grant_id IS NOT NULL AND dm_controller_generation IS NOT NULL) OR "
            "(dm_controller_kind = 'none' AND dm_controller_access_session_id IS NULL "
            "AND dm_controller_ai_grant_id IS NULL AND dm_controller_generation IS NULL)",
        )
    op.create_index(SESSION_GRANT_INDEX, "sessions", ["dm_controller_ai_grant_id"])

    with op.batch_alter_table("session_participants") as batch_op:
        batch_op.add_column(sa.Column("controller_ai_grant_id_at_join", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("controller_generation_at_join", sa.BigInteger(), nullable=True))
        batch_op.create_foreign_key(
            PARTICIPANT_GRANT_FK,
            "ai_controller_grants",
            ["controller_ai_grant_id_at_join"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.drop_constraint(PARTICIPANT_BINDING, type_="check")
        batch_op.create_check_constraint(
            PARTICIPANT_BINDING,
            "(controller_kind_at_join = 'human' AND controller_access_session_id_at_join IS NOT NULL "
            "AND controller_ai_grant_id_at_join IS NULL AND controller_generation_at_join IS NULL) OR "
            "(controller_kind_at_join = 'ai' AND controller_access_session_id_at_join IS NULL "
            "AND controller_ai_grant_id_at_join IS NOT NULL AND controller_generation_at_join IS NOT NULL) OR "
            "(controller_kind_at_join = 'none' AND controller_access_session_id_at_join IS NULL "
            "AND controller_ai_grant_id_at_join IS NULL AND controller_generation_at_join IS NULL)",
        )
    op.create_index(
        PARTICIPANT_GRANT_INDEX,
        "session_participants",
        ["controller_ai_grant_id_at_join"],
    )


def downgrade() -> None:
    op.drop_index(PARTICIPANT_GRANT_INDEX, table_name="session_participants")
    with op.batch_alter_table("session_participants") as batch_op:
        batch_op.drop_constraint(PARTICIPANT_BINDING, type_="check")
        batch_op.drop_constraint(PARTICIPANT_GRANT_FK, type_="foreignkey")
        batch_op.drop_column("controller_generation_at_join")
        batch_op.drop_column("controller_ai_grant_id_at_join")
        batch_op.create_check_constraint(
            PARTICIPANT_BINDING,
            "(controller_kind_at_join = 'human' AND controller_access_session_id_at_join IS NOT NULL) OR "
            "(controller_kind_at_join IN ('ai', 'none') AND controller_access_session_id_at_join IS NULL)",
        )

    op.drop_index(SESSION_GRANT_INDEX, table_name="sessions")
    with op.batch_alter_table("sessions") as batch_op:
        batch_op.drop_constraint(SESSION_BINDING, type_="check")
        batch_op.drop_constraint(SESSION_GRANT_FK, type_="foreignkey")
        batch_op.drop_column("dm_controller_generation")
        batch_op.drop_column("dm_controller_ai_grant_id")
        batch_op.create_check_constraint(
            SESSION_BINDING,
            "(dm_controller_kind = 'human' AND dm_controller_access_session_id IS NOT NULL) OR "
            "(dm_controller_kind IN ('ai', 'none') AND dm_controller_access_session_id IS NULL)",
        )

    op.drop_index(SEAT_GRANT_INDEX, table_name="campaign_seats")
    with op.batch_alter_table("campaign_seats") as batch_op:
        batch_op.drop_constraint(SEAT_BINDING, type_="check")
        batch_op.drop_constraint(SEAT_GRANT_FK, type_="foreignkey")
        batch_op.drop_column("controller_epoch")
        batch_op.drop_column("ai_controller_grant_id")
        batch_op.create_check_constraint(
            SEAT_BINDING,
            "(controller_kind = 'human' AND controller_access_session_id IS NOT NULL) OR "
            "(controller_kind IN ('ai', 'none') AND controller_access_session_id IS NULL)",
        )

    op.drop_index("ix_ai_controller_grants_campaign_id", table_name="ai_controller_grants")
    op.drop_index("ix_ai_controller_grants_session_status", table_name="ai_controller_grants")
    op.drop_index("ix_ai_controller_grants_seat_status", table_name="ai_controller_grants")
    op.drop_table("ai_controller_grants")