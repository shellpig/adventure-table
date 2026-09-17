from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    true,
)

from app.db import metadata


monster_templates = Table(
    "monster_templates",
    metadata,
    Column("id", Uuid(), primary_key=True),
    Column("campaign_id", Uuid(), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
    Column("name", String(160), nullable=False),
    Column("source_key", String(255), nullable=True),
    Column("rules", JSON(), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
Index("ix_monster_templates_campaign_id", monster_templates.c.campaign_id)


monster_instances = Table(
    "monster_instances",
    metadata,
    Column("id", Uuid(), primary_key=True),
    Column("campaign_id", Uuid(), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
    Column("template_key", String(255), nullable=True),
    Column(
        "custom_template_id",
        Uuid(),
        ForeignKey("monster_templates.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("name", String(160), nullable=False),
    Column("rules_snapshot", JSON(), nullable=False),
    Column("current_hp", Integer(), nullable=False),
    Column("temp_hp", Integer(), nullable=False, server_default="0"),
    Column("conditions", JSON(), nullable=False),
    Column("effects", JSON(), nullable=False),
    Column("concentration", JSON(), nullable=True),
    Column("combat_status", String(16), nullable=False),
    Column("initiative", Integer(), nullable=True),
    Column("reaction_available", Boolean(), nullable=False, server_default=true()),
    Column("resources", JSON(), nullable=False),
    Column("visibility", String(16), nullable=False),
    Column("position_note", Text(), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "NOT (template_key IS NOT NULL AND custom_template_id IS NOT NULL)",
        name="ck_monster_instances_single_template_source",
    ),
    CheckConstraint("current_hp >= 0", name="ck_monster_instances_current_hp"),
    CheckConstraint("temp_hp >= 0", name="ck_monster_instances_temp_hp"),
    CheckConstraint(
        "combat_status IN ('active', 'down', 'dead', 'removed')",
        name="ck_monster_instances_combat_status",
    ),
    CheckConstraint(
        "visibility IN ('public', 'hidden')",
        name="ck_monster_instances_visibility",
    ),
)
Index("ix_monster_instances_campaign_id", monster_instances.c.campaign_id)
Index("ix_monster_instances_custom_template_id", monster_instances.c.custom_template_id)


combats = Table(
    "combats",
    metadata,
    Column("id", Uuid(), primary_key=True),
    Column("campaign_id", Uuid(), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
    Column("started_session_id", Uuid(), ForeignKey("sessions.id", ondelete="RESTRICT"), nullable=False),
    Column("ended_session_id", Uuid(), ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True),
    Column("mode", String(16), nullable=False, server_default="quick"),
    Column("status", String(24), nullable=False, server_default="initiative_pending"),
    Column("round_number", Integer(), nullable=True),
    Column("current_turn_entry_id", Uuid(), nullable=True),
    Column("revision", BigInteger(), nullable=False, server_default="1"),
    Column("started_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("ended_at", DateTime(timezone=True), nullable=True),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("mode = 'quick'", name="ck_combats_mode_quick"),
    CheckConstraint(
        "status IN ('initiative_pending', 'running', 'ended')",
        name="ck_combats_status",
    ),
    CheckConstraint(
        "(status = 'running' AND round_number IS NOT NULL AND round_number >= 1 "
        "AND current_turn_entry_id IS NOT NULL) OR "
        "(status != 'running' AND (round_number IS NULL OR round_number >= 1))",
        name="ck_combats_running_turn_state",
    ),
    CheckConstraint("revision > 0", name="ck_combats_revision_positive"),
)
Index("ix_combats_campaign_id", combats.c.campaign_id)
Index(
    "uq_combats_campaign_active",
    combats.c.campaign_id,
    unique=True,
    postgresql_where=combats.c.status.in_(("initiative_pending", "running")),
    sqlite_where=combats.c.status.in_(("initiative_pending", "running")),
)


combat_entries = Table(
    "combat_entries",
    metadata,
    Column("id", Uuid(), primary_key=True),
    Column("combat_id", Uuid(), ForeignKey("combats.id", ondelete="CASCADE"), nullable=False),
    Column("subject_kind", String(16), nullable=False),
    Column("character_id", Uuid(), ForeignKey("characters.id", ondelete="RESTRICT"), nullable=True),
    Column(
        "monster_instance_id",
        Uuid(),
        ForeignKey("monster_instances.id", ondelete="RESTRICT"),
        nullable=True,
    ),
    Column("display_name", String(160), nullable=False),
    Column("status", String(16), nullable=False, server_default="active"),
    Column("is_hostile", Boolean(), nullable=False, server_default="0"),
    Column("initiative_group_key", String(120), nullable=True),
    Column("initiative_roll_request_id", Uuid(), nullable=True),
    Column("initiative_roll_result_id", Uuid(), nullable=True),
    Column("initiative_total", Integer(), nullable=True),
    Column("turn_order", Integer(), nullable=True),
    Column("surprised", Boolean(), nullable=False, server_default="0"),
    Column("action_available", Boolean(), nullable=False, server_default=true()),
    Column("bonus_action_available", Boolean(), nullable=False, server_default=true()),
    Column("reaction_available", Boolean(), nullable=False, server_default=true()),
    Column("attacks_allowed", Integer(), nullable=False, server_default="1"),
    Column("attacks_used", Integer(), nullable=False, server_default="0"),
    Column("death_save_successes", Integer(), nullable=False, server_default="0"),
    Column("death_save_failures", Integer(), nullable=False, server_default="0"),
    Column("death_save_stable", Boolean(), nullable=False, server_default="0"),
    Column("death_save_dead", Boolean(), nullable=False, server_default="0"),
    Column("ready_state", JSON(), nullable=False),
    Column("pending_reaction_state", JSON(), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "(subject_kind = 'character' AND character_id IS NOT NULL AND monster_instance_id IS NULL) OR "
        "(subject_kind = 'monster' AND character_id IS NULL AND monster_instance_id IS NOT NULL)",
        name="ck_combat_entries_subject",
    ),
    CheckConstraint(
        "status IN ('active', 'withdrawn', 'removed')",
        name="ck_combat_entries_status",
    ),
    CheckConstraint("turn_order IS NULL OR turn_order >= 0", name="ck_combat_entries_turn_order"),
    CheckConstraint("attacks_allowed >= 1", name="ck_combat_entries_attacks_allowed"),
    CheckConstraint(
        "attacks_used >= 0 AND attacks_used <= attacks_allowed",
        name="ck_combat_entries_attacks_used",
    ),
    CheckConstraint(
        "death_save_successes >= 0 AND death_save_successes <= 2",
        name="ck_combat_entries_death_save_successes",
    ),
    CheckConstraint(
        "death_save_failures >= 0 AND death_save_failures <= 2",
        name="ck_combat_entries_death_save_failures",
    ),
    CheckConstraint(
        "NOT (death_save_stable AND death_save_dead)",
        name="ck_combat_entries_death_save_terminal",
    ),
    UniqueConstraint("combat_id", "character_id", name="uq_combat_entries_character"),
    UniqueConstraint("combat_id", "monster_instance_id", name="uq_combat_entries_monster"),
)
Index("ix_combat_entries_combat_id", combat_entries.c.combat_id)
Index("ix_combat_entries_character_id", combat_entries.c.character_id)
Index("ix_combat_entries_monster_instance_id", combat_entries.c.monster_instance_id)
Index("ix_combat_entries_turn_order", combat_entries.c.combat_id, combat_entries.c.turn_order)


combat_actions = Table(
    "combat_actions",
    metadata,
    Column("id", Uuid(), primary_key=True),
    Column("combat_id", Uuid(), ForeignKey("combats.id", ondelete="CASCADE"), nullable=False),
    Column("entry_id", Uuid(), ForeignKey("combat_entries.id", ondelete="CASCADE"), nullable=False),
    Column("target_entry_id", Uuid(), ForeignKey("combat_entries.id", ondelete="CASCADE"), nullable=True),
    Column("session_id", Uuid(), ForeignKey("sessions.id", ondelete="RESTRICT"), nullable=False),
    Column("acting_seat_id", Uuid(), ForeignKey("campaign_seats.id", ondelete="RESTRICT"), nullable=False),
    Column("subject_seat_id", Uuid(), ForeignKey("campaign_seats.id", ondelete="RESTRICT"), nullable=True),
    Column("execution_mode", String(16), nullable=False),
    Column("action_kind", String(32), nullable=False),
    Column("economy_cost", String(16), nullable=False),
    Column("payload", JSON(), nullable=False),
    Column("resolution_status", String(32), nullable=False, server_default="resolved"),
    Column("roll_request_id", Uuid(), nullable=True),
    Column("roll_result_id", Uuid(), nullable=True),
    Column("resolution_result", JSON(), nullable=True),
    Column("idempotency_key", String(160), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "execution_mode IN ('self', 'dm_proxy')",
        name="ck_combat_actions_execution_mode",
    ),
    CheckConstraint(
        "economy_cost IN ('action', 'bonus_action', 'reaction', 'none')",
        name="ck_combat_actions_economy_cost",
    ),
    CheckConstraint(
        "resolution_status IN ('waiting_for_roll', 'dm_adjudication_required', 'resolved', 'cancelled')",
        name="ck_combat_actions_resolution_status",
    ),
    UniqueConstraint("combat_id", "idempotency_key", name="uq_combat_actions_idempotency"),
)
Index("ix_combat_actions_combat_id", combat_actions.c.combat_id)
Index("ix_combat_actions_entry_id", combat_actions.c.entry_id)
Index("ix_combat_actions_target_entry_id", combat_actions.c.target_entry_id)
Index("ix_combat_actions_roll_request_id", combat_actions.c.roll_request_id)


__all__ = [
    "combat_actions",
    "combat_entries",
    "combats",
    "monster_instances",
    "monster_templates",
]
