from __future__ import annotations

import inspect
from pathlib import Path

from app.domain.rooms.ai_oauth import AIControllerOAuthService
from app.persistence.mcp.tables import ai_oauth_authorizations


def _server_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_oauth_module_has_no_seat_writes() -> None:
    source = (_server_root() / "app" / "mcp" / "oauth.py").read_text(encoding="utf-8")
    forbidden = (
        "campaign_seats",
        "session_participants",
        "SeatRepository",
        "SessionRepository",
        "create_seat",
        "assign_seat",
        "reassign_seat",
        "controller_epoch",
    )
    for marker in forbidden:
        assert marker not in source


def test_oauth_flow_writes_zero_seat_rows_by_dependency_boundary() -> None:
    source = (_server_root() / "app" / "mcp" / "oauth.py").read_text(encoding="utf-8")
    assert "app.persistence.rooms" not in source
    assert "app.domain.rooms.seats" not in source
    assert "app.domain.rooms.sessions" not in source
    assert "AIControllerService" in source  # authority is read/revalidated through P3-D only
    assert "authenticate_grant" in source


def test_one_authorization_one_grant_for_lifetime() -> None:
    public_methods = {
        name
        for name, member in inspect.getmembers(AIControllerOAuthService, inspect.isfunction)
        if not name.startswith("_")
    }
    assert not ({"switch_grant", "rebind_grant", "update_grant", "set_grant"} & public_methods)
    assert "replace_authorization_for_grant" in public_methods
    assert ai_oauth_authorizations.c.grant_id.nullable is False


def test_one_active_family_per_grant_schema_contract() -> None:
    index = next(
        item for item in ai_oauth_authorizations.indexes
        if item.name == "uq_ai_oauth_authorizations_active_grant"
    )
    assert index.unique is True
    assert [column.name for column in index.columns] == ["grant_id"]
    assert index.dialect_options["postgresql"]["where"] is not None


def test_reauthorize_same_grant_revokes_previous_family_repository_contract() -> None:
    source = (_server_root() / "app" / "persistence" / "mcp" / "oauth.py").read_text(encoding="utf-8")
    start = source.index("def replace_authorization_for_grant")
    end = source.index("\n    def get_authorization", start)
    body = source[start:end]
    assert "ai_oauth_authorizations.c.grant_id == grant_id" in body
    assert "revoked_at.is_(None)" in body
    assert ".values(revoked_at=now)" in body
    assert "grant_id=grant_id" in body


def test_reauthorize_other_grant_same_client_keeps_previous_family() -> None:
    source = (_server_root() / "app" / "persistence" / "mcp" / "oauth.py").read_text(encoding="utf-8")
    start = source.index("def replace_authorization_for_grant")
    end = source.index("\n    def get_authorization", start)
    body = source[start:end]
    # Replacement scope is grant_id, not client_id: another grant for the same DCR
    # client therefore remains active.
    revoke_start = body.index("update(ai_oauth_authorizations)")
    revoke_end = body.index("connection.execute(\n                insert(ai_oauth_authorizations)", revoke_start)
    revoke_block = body[revoke_start:revoke_end]
    assert "grant_id == grant_id" in revoke_block
    assert "client_id == client_id" not in revoke_block
