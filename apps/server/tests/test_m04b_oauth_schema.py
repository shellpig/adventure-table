from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.persistence.mcp.tables import (
    ai_oauth_authorization_codes,
    ai_oauth_authorizations,
    ai_oauth_clients,
    ai_oauth_tokens,
)


REVISION = "0021_m04b_ai_oauth"
EXPECTED_TABLES = {
    "ai_oauth_clients",
    "ai_oauth_authorizations",
    "ai_oauth_authorization_codes",
    "ai_oauth_tokens",
}


def _server_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _source() -> str:
    return (
        _server_root()
        / "alembic"
        / "versions"
        / "0021_m04b_ai_oauth.py"
    ).read_text(encoding="utf-8")


def test_m04b_revision_is_current_web_head_and_links_p3d() -> None:
    server_root = _server_root()
    config = Config(str(server_root / "alembic.ini"))
    config.set_main_option("script_location", str(server_root / "alembic"))
    scripts = ScriptDirectory.from_config(config)

    revision = scripts.get_revision(REVISION)
    assert revision is not None
    assert revision.down_revision == "0020_p3d_ai_controller_grants"
    assert REVISION in scripts.get_heads()


def test_m04b_metadata_contains_only_documented_oauth_tables() -> None:
    tables = {
        ai_oauth_clients.name: ai_oauth_clients,
        ai_oauth_authorizations.name: ai_oauth_authorizations,
        ai_oauth_authorization_codes.name: ai_oauth_authorization_codes,
        ai_oauth_tokens.name: ai_oauth_tokens,
    }
    assert set(tables) == EXPECTED_TABLES
    assert set(ai_oauth_tokens.c.keys()) == {
        "id",
        "token_hash",
        "kind",
        "authorization_id",
        "expires_at",
        "revoked_at",
        "last_used_at",
    }

    source = _source()
    for name in EXPECTED_TABLES:
        assert f'"{name}"' in source


def test_m04b_active_authorization_index_is_partial_and_unique() -> None:
    indexes = {index.name: index for index in ai_oauth_authorizations.indexes}
    active = indexes["uq_ai_oauth_authorizations_active_grant"]

    assert active.unique is True
    assert [column.name for column in active.columns] == ["grant_id"]
    assert active.dialect_options["sqlite"]["where"] is not None
    assert active.dialect_options["postgresql"]["where"] is not None

    source = _source()
    assert '"uq_ai_oauth_authorizations_active_grant"' in source
    assert "unique=True" in source
    assert "postgresql_where=sa.text(\"revoked_at IS NULL\")" in source
    assert "sqlite_where=sa.text(\"revoked_at IS NULL\")" in source


def test_m04b_foreign_keys_bind_oauth_to_existing_grant_authority() -> None:
    authorization_fks = {
        fk.parent.name: fk.target_fullname
        for fk in ai_oauth_authorizations.foreign_keys
    }
    assert authorization_fks == {
        "client_id": "ai_oauth_clients.client_id",
        "grant_id": "ai_controller_grants.id",
    }
    code_fks = {
        fk.parent.name: fk.target_fullname
        for fk in ai_oauth_authorization_codes.foreign_keys
    }
    token_fks = {
        fk.parent.name: fk.target_fullname
        for fk in ai_oauth_tokens.foreign_keys
    }
    assert code_fks == {
        "authorization_id": "ai_oauth_authorizations.id",
    }
    assert token_fks == {
        "authorization_id": "ai_oauth_authorizations.id",
    }
