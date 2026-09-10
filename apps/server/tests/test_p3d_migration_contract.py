from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.persistence.rooms.tables import (
    ai_controller_grants,
    campaign_seats,
    session_participants,
    sessions,
)


REVISION = "0020_p3d_ai_controller_grants"


def _source() -> str:
    return (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0020_p3d_ai_controller_grants.py"
    ).read_text(encoding="utf-8")


def _check(table, name: str) -> str:
    return " ".join(
        str(constraint.sqltext)
        for constraint in table.constraints
        if getattr(constraint, "name", None) == name and hasattr(constraint, "sqltext")
    )


def test_p3d_revision_is_web_head() -> None:
    server_root = Path(__file__).resolve().parents[1]
    config = Config(str(server_root / "alembic.ini"))
    config.set_main_option("script_location", str(server_root / "alembic"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision(REVISION)
    assert revision is not None
    assert revision.down_revision == "0019_p3c_check_command"
    assert REVISION in scripts.get_heads()


def test_p3d_migration_replaces_all_three_named_controller_checks() -> None:
    source = _source()
    bindings = {
        "SEAT_BINDING": "ck_campaign_seats_controller_binding",
        "SESSION_BINDING": "ck_sessions_dm_controller_binding",
        "PARTICIPANT_BINDING": "ck_session_participants_controller_binding",
    }
    for constant, name in bindings.items():
        assert f'{constant} = "{name}"' in source
        assert source.count(constant) >= 4
    assert "0013_p2d_campaign_seats.py" not in source
    assert "0014_p2e_sessions.py" not in source


def test_p3d_metadata_has_epoch_and_typed_ai_bindings() -> None:
    assert not campaign_seats.c.controller_epoch.nullable
    assert campaign_seats.c.ai_controller_grant_id.nullable
    assert sessions.c.dm_controller_ai_grant_id.nullable
    assert sessions.c.dm_controller_generation.nullable
    assert session_participants.c.controller_ai_grant_id_at_join.nullable
    assert session_participants.c.controller_generation_at_join.nullable

    seat_check = _check(campaign_seats, "ck_campaign_seats_controller_binding")
    assert "controller_epoch IS NOT NULL" in seat_check
    assert "controller_kind = 'human'" in seat_check
    assert "controller_kind = 'ai'" in seat_check
    assert "controller_kind = 'none'" in seat_check
    assert "ai_controller_grant_id IS NOT NULL" in seat_check

    session_check = _check(sessions, "ck_sessions_dm_controller_binding")
    assert "dm_controller_ai_grant_id IS NOT NULL" in session_check
    assert "dm_controller_generation IS NOT NULL" in session_check

    participant_check = _check(
        session_participants,
        "ck_session_participants_controller_binding",
    )
    assert "controller_ai_grant_id_at_join IS NOT NULL" in participant_check
    assert "controller_generation_at_join IS NOT NULL" in participant_check


def test_p3d_migration_indexes_match_metadata() -> None:
    source = _source()
    expected = {
        campaign_seats: {
            "ix_campaign_seats_ai_controller_grant_id",
        },
        sessions: {
            "ix_sessions_dm_controller_ai_grant_id",
        },
        session_participants: {
            "ix_session_participants_controller_ai_grant_id",
        },
        ai_controller_grants: {
            "ix_ai_controller_grants_seat_status",
            "ix_ai_controller_grants_session_status",
            "ix_ai_controller_grants_campaign_id",
        },
    }
    for table, required in expected.items():
        metadata_indexes = {index.name for index in table.indexes}
        assert required <= metadata_indexes
        for name in required:
            assert name in source

    downgrade = source[source.index("def downgrade") :]
    named_indexes = {
        "SEAT_GRANT_INDEX": "ix_campaign_seats_ai_controller_grant_id",
        "SESSION_GRANT_INDEX": "ix_sessions_dm_controller_ai_grant_id",
        "PARTICIPANT_GRANT_INDEX": "ix_session_participants_controller_ai_grant_id",
    }
    for constant, name in named_indexes.items():
        assert f'{constant} = "{name}"' in source
        assert f"op.drop_index({constant}," in downgrade


def test_p3d_grant_schema_never_stores_plaintext_token() -> None:
    names = set(ai_controller_grants.c.keys())
    assert "secret_hash" in names
    assert "secret_prefix" in names
    assert "token" not in names
    assert "plaintext" not in names
    assert not ai_controller_grants.c.secret_hash.nullable
    assert not ai_controller_grants.c.generation.nullable

    scope_check = _check(ai_controller_grants, "ck_ai_controller_grants_scope")
    assert "role = 'player'" in scope_check
    assert "handoff_return_access_session_id IS NOT NULL" in scope_check
    assert "session_id IS NULL AND pre_session_expires_at IS NOT NULL" in scope_check


def test_p3d_migration_normalizes_uncredentialed_legacy_ai_rows() -> None:
    source = _source()
    assert "UPDATE campaign_seats SET controller_kind = 'none'" in source
    assert "UPDATE sessions SET dm_controller_kind = 'none'" in source
    assert "UPDATE session_participants SET controller_kind_at_join = 'none'" in source
