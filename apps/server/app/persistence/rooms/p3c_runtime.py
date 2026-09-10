from __future__ import annotations

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

from app.db import metadata


json_payload_type = JSON().with_variant(JSONB(), "postgresql")


roll_groups = Table(
    "roll_groups",
    metadata,
    Column("id", Uuid(), primary_key=True),
    Column("session_id", Uuid(), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False),
    Column("requested_by_seat_id", Uuid(), ForeignKey("campaign_seats.id", ondelete="RESTRICT"), nullable=False),
    Column("label", String(160), nullable=True),
    Column("visibility", String(24), nullable=False),
    Column("version", BigInteger, nullable=False, server_default="1"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "visibility IN ('public', 'roller_and_dm', 'dm_only')",
        name="ck_roll_groups_visibility",
    ),
    CheckConstraint("version > 0", name="ck_roll_groups_version_positive"),
)
Index("ix_roll_groups_session_id", roll_groups.c.session_id)


roll_requests = Table(
    "roll_requests",
    metadata,
    Column("id", Uuid(), primary_key=True),
    Column("session_id", Uuid(), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False),
    Column("roll_group_id", Uuid(), ForeignKey("roll_groups.id", ondelete="CASCADE"), nullable=True),
    Column("target_seat_id", Uuid(), ForeignKey("campaign_seats.id", ondelete="RESTRICT"), nullable=False),
    Column("target_character_id", Uuid(), ForeignKey("characters.id", ondelete="RESTRICT"), nullable=True),
    Column("request_type", String(32), nullable=False),
    Column("ability_ref", String(80), nullable=True),
    Column("skill_ref", String(120), nullable=True),
    Column("dc", Integer, nullable=True),
    Column("modifier_mode", String(16), nullable=False),
    Column("flat_adjustment", Integer, nullable=False, server_default="0"),
    Column("visibility", String(24), nullable=False),
    Column("status", String(16), nullable=False, server_default="pending"),
    Column("requested_by_seat_id", Uuid(), ForeignKey("campaign_seats.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("resolved_at", DateTime(timezone=True), nullable=True),
    Column("version", BigInteger, nullable=False, server_default="1"),
    CheckConstraint(
        "request_type IN ('ability', 'skill', 'saving_throw', 'other')",
        name="ck_roll_requests_request_type",
    ),
    CheckConstraint(
        "modifier_mode IN ('normal', 'advantage', 'disadvantage')",
        name="ck_roll_requests_modifier_mode",
    ),
    CheckConstraint(
        "visibility IN ('public', 'roller_and_dm', 'dm_only')",
        name="ck_roll_requests_visibility",
    ),
    CheckConstraint(
        "status IN ('pending', 'resolved', 'cancelled')",
        name="ck_roll_requests_status",
    ),
    CheckConstraint("dc IS NULL OR dc >= 0", name="ck_roll_requests_dc_nonnegative"),
    CheckConstraint("version > 0", name="ck_roll_requests_version_positive"),
)
Index("ix_roll_requests_session_status", roll_requests.c.session_id, roll_requests.c.status)
Index("ix_roll_requests_group_id", roll_requests.c.roll_group_id)
Index("ix_roll_requests_target_seat_id", roll_requests.c.target_seat_id)


roll_results = Table(
    "roll_results",
    metadata,
    Column("id", Uuid(), primary_key=True),
    Column("roll_request_id", Uuid(), ForeignKey("roll_requests.id", ondelete="CASCADE"), nullable=True),
    Column("session_id", Uuid(), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False),
    Column("acting_seat_id", Uuid(), ForeignKey("campaign_seats.id", ondelete="RESTRICT"), nullable=False),
    Column("subject_seat_id", Uuid(), ForeignKey("campaign_seats.id", ondelete="RESTRICT"), nullable=False),
    Column("subject_character_id", Uuid(), ForeignKey("characters.id", ondelete="RESTRICT"), nullable=True),
    Column("execution_mode", String(16), nullable=False),
    Column("source", String(16), nullable=False),
    Column("formula", String(120), nullable=False),
    Column("raw_dice", json_payload_type, nullable=False),
    Column("kept_dice", json_payload_type, nullable=False),
    Column("base_modifier", Integer, nullable=False),
    Column("flat_adjustment", Integer, nullable=False, server_default="0"),
    Column("total", Integer, nullable=False),
    Column("visibility", String(24), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "execution_mode IN ('self', 'dm_proxy', 'system')",
        name="ck_roll_results_execution_mode",
    ),
    CheckConstraint(
        "source IN ('server', 'physical', 'quick')",
        name="ck_roll_results_source",
    ),
    CheckConstraint(
        "visibility IN ('public', 'roller_and_dm', 'dm_only')",
        name="ck_roll_results_visibility",
    ),
    CheckConstraint(
        "(source = 'quick' AND roll_request_id IS NULL) OR "
        "(source IN ('server', 'physical') AND roll_request_id IS NOT NULL)",
        name="ck_roll_results_request_binding",
    ),
    UniqueConstraint("roll_request_id", name="uq_roll_results_roll_request_id"),
)
Index("ix_roll_results_session_id", roll_results.c.session_id)
Index("ix_roll_results_subject_seat_id", roll_results.c.subject_seat_id)


pending_actions = Table(
    "pending_actions",
    metadata,
    Column("id", Uuid(), primary_key=True),
    Column("session_id", Uuid(), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False),
    Column("acting_seat_id", Uuid(), ForeignKey("campaign_seats.id", ondelete="RESTRICT"), nullable=False),
    Column("subject_seat_id", Uuid(), ForeignKey("campaign_seats.id", ondelete="RESTRICT"), nullable=False),
    Column("subject_character_id", Uuid(), ForeignKey("characters.id", ondelete="RESTRICT"), nullable=True),
    Column("execution_mode", String(16), nullable=False),
    Column("text", Text(), nullable=True),
    Column("intent_payload", json_payload_type, nullable=True),
    Column("status", String(24), nullable=False, server_default="pending"),
    Column("roll_request_id", Uuid(), ForeignKey("roll_requests.id", ondelete="SET NULL"), nullable=True),
    Column("window_id", Uuid(), nullable=True),
    Column("version", BigInteger, nullable=False, server_default="1"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "execution_mode IN ('self', 'dm_proxy', 'system')",
        name="ck_pending_actions_execution_mode",
    ),
    CheckConstraint(
        "status IN ('pending', 'processing', 'waiting_for_roll', 'resolved', 'cancelled')",
        name="ck_pending_actions_status",
    ),
    CheckConstraint(
        "text IS NOT NULL OR intent_payload IS NOT NULL",
        name="ck_pending_actions_intent_present",
    ),
    CheckConstraint("version > 0", name="ck_pending_actions_version_positive"),
)
Index("ix_pending_actions_session_status", pending_actions.c.session_id, pending_actions.c.status)
Index("ix_pending_actions_roll_request_id", pending_actions.c.roll_request_id)


__all__ = [
    "pending_actions",
    "roll_groups",
    "roll_requests",
    "roll_results",
]
