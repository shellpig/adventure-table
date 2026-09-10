from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.persistence.rooms.exploration_messages import session_messages
from app.persistence.rooms.p3c_runtime import (
    pending_actions,
    roll_groups,
    roll_requests,
    roll_results,
)


ROLL_PENDING_REVISION = "0018_p3c_roll_pending"
CHECK_COMMAND_REVISION = "0019_p3c_check_command"
P3D_REVISION = "0020_p3d_ai_controller_grants"


def _migration_source() -> str:
    return (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0018_p3c_roll_pending.py"
    ).read_text(encoding="utf-8")


def _check_command_migration_source() -> str:
    return (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0019_p3c_check_command.py"
    ).read_text(encoding="utf-8")


def test_p3c_web_migration_chain_links_check_command_into_current_head() -> None:
    server_root = Path(__file__).resolve().parents[1]
    config = Config(str(server_root / "alembic.ini"))
    config.set_main_option("script_location", str(server_root / "alembic"))
    scripts = ScriptDirectory.from_config(config)

    roll_revision = scripts.get_revision(ROLL_PENDING_REVISION)
    assert roll_revision is not None
    assert roll_revision.down_revision == "0017_p3b_exploration_stage"

    check_revision = scripts.get_revision(CHECK_COMMAND_REVISION)
    assert check_revision is not None
    assert check_revision.down_revision == ROLL_PENDING_REVISION

    p3d_revision = scripts.get_revision(P3D_REVISION)
    assert p3d_revision is not None
    assert p3d_revision.down_revision == CHECK_COMMAND_REVISION
    assert P3D_REVISION in scripts.get_heads()


def test_p3c_check_command_constraint_matches_metadata_and_downgrades_safely() -> None:
    source = _check_command_migration_source()
    check_text = " ".join(
        str(constraint.sqltext)
        for constraint in session_messages.constraints
        if hasattr(constraint, "sqltext")
        and constraint.name == "ck_session_messages_source_command"
    )
    assert "'search'" in check_text
    assert "'check'" in check_text
    assert "source_command IN ('search', 'check')" in source

    downgrade_source = source[source.index("def downgrade") :]
    normalize_at = downgrade_source.index(
        "UPDATE session_messages SET source_command = NULL WHERE source_command = 'check'"
    )
    restore_at = downgrade_source.index("source_command IS NULL OR source_command = 'search'")
    assert normalize_at < restore_at


def test_p3c_schema_has_canonical_roll_and_pending_tables() -> None:
    source = _migration_source()
    for table_name in ("roll_groups", "roll_requests", "roll_results", "pending_actions"):
        assert f'"{table_name}"' in source

    assert 'sa.ForeignKey("sessions.id", ondelete="CASCADE")' in source
    assert 'sa.ForeignKey("campaign_seats.id", ondelete="RESTRICT")' in source
    assert 'sa.ForeignKey("characters.id", ondelete="RESTRICT")' in source
    assert "uq_roll_results_roll_request_id" in source
    assert "waiting_for_roll" in source
    assert "roller_and_dm" in source
    assert "dm_only" in source


def test_p3c_metadata_and_migration_indexes_match() -> None:
    expected = {
        "roll_groups": {"ix_roll_groups_session_id"},
        "roll_requests": {
            "ix_roll_requests_session_status",
            "ix_roll_requests_group_id",
            "ix_roll_requests_target_seat_id",
        },
        "roll_results": {
            "ix_roll_results_session_id",
            "ix_roll_results_subject_seat_id",
        },
        "pending_actions": {
            "ix_pending_actions_session_status",
            "ix_pending_actions_roll_request_id",
        },
    }
    tables = {
        "roll_groups": roll_groups,
        "roll_requests": roll_requests,
        "roll_results": roll_results,
        "pending_actions": pending_actions,
    }
    source = _migration_source()

    for name, table in tables.items():
        assert {index.name for index in table.indexes} == expected[name]
        for index_name in expected[name]:
            assert f'"{index_name}"' in source


def test_formal_result_is_unique_per_request_and_quick_roll_is_unbound() -> None:
    unique_names = {constraint.name for constraint in roll_results.constraints}
    check_text = " ".join(
        str(constraint.sqltext)
        for constraint in roll_results.constraints
        if hasattr(constraint, "sqltext")
    )
    assert "uq_roll_results_roll_request_id" in unique_names
    assert "source = 'quick'" in check_text
    assert "roll_request_id IS NULL" in check_text
    assert "source IN ('server', 'physical')" in check_text


def test_pending_action_state_machine_values_are_schema_guarded() -> None:
    check_text = " ".join(
        str(constraint.sqltext)
        for constraint in pending_actions.constraints
        if hasattr(constraint, "sqltext")
    )
    for status in ("pending", "processing", "waiting_for_roll", "resolved", "cancelled"):
        assert status in check_text
    assert "text IS NOT NULL OR intent_payload IS NOT NULL" in check_text
