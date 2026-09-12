from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, insert, select
from starlette.requests import Request

from app.domain.rooms.ai_controllers import AIControllerAuthView
from app.mcp.auth import authenticate_request
from app.mcp.tools import tool_catalog
from app.persistence.mcp.lifecycle import revoke_grant_authorizations_in_transaction
from app.persistence.mcp.tables import ai_oauth_authorizations, ai_oauth_clients
from app.persistence.mcp.oauth import StoredOAuthAuthorization, StoredOAuthToken


NOW = datetime(2026, 9, 12, tzinfo=timezone.utc)


def _request(token: str) -> Request:
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": [(b"authorization", f"Bearer {token}".encode())],
    })


def _view(grant_id) -> AIControllerAuthView:
    return AIControllerAuthView(
        grant_id=grant_id,
        room_id=uuid4(),
        campaign_id=uuid4(),
        seat_id=uuid4(),
        role="player",
        session_id=uuid4(),
        generation=7,
        active_character_id=uuid4(),
        is_current_dm=False,
    )


class _Authority:
    def __init__(self, view: AIControllerAuthView) -> None:
        self.view = view

    def authenticate(self, token: str, *, touch: bool = False):
        return self.view

    def authenticate_grant(self, grant_id, *, touch: bool = False):
        assert grant_id == self.view.grant_id
        return self.view


class _OAuth:
    def __init__(self, authorization: StoredOAuthAuthorization) -> None:
        self.authorization = authorization

    def resolve_active_access(self, token_hash: str, *, touch: bool = False):
        return (
            StoredOAuthToken(uuid4(), token_hash, "access", self.authorization.id, NOW, None, None),
            self.authorization,
        )

    def revoke_authorization(self, authorization_id):
        raise AssertionError("active authorization must not be revoked")


def test_access_token_resolves_same_auth_view_as_join_token() -> None:
    grant_id = uuid4()
    view = _view(grant_id)
    authority = _Authority(view)
    authorization = StoredOAuthAuthorization(uuid4(), "atc_test", grant_id, 7, NOW, None)
    legacy = authenticate_request(_request("at_ai_fake-token"), authority)
    oauth = authenticate_request(_request("at_oa_fake-token"), authority, _OAuth(authorization))
    assert legacy.auth == oauth.auth == view


def test_oauth_source_gets_same_role_scoped_catalog() -> None:
    grant_id = uuid4()
    view = _view(grant_id)
    authority = _Authority(view)
    authorization = StoredOAuthAuthorization(uuid4(), "atc_test", grant_id, 7, NOW, None)
    legacy = authenticate_request(_request("at_ai_fake-token"), authority)
    oauth = authenticate_request(_request("at_oa_fake-token"), authority, _OAuth(authorization))
    assert tool_catalog(legacy.auth) == tool_catalog(oauth.auth)


def _engine_with_oauth_tables():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE ai_controller_grants (id CHAR(32) PRIMARY KEY)"
        )
    ai_oauth_clients.create(engine)
    ai_oauth_authorizations.create(engine)
    return engine


def _insert_authorization(connection, *, grant_id, client_id="atc_test"):
    connection.exec_driver_sql(
        "INSERT OR IGNORE INTO ai_controller_grants (id) VALUES (?)",
        (grant_id.hex,),
    )
    connection.execute(
        insert(ai_oauth_clients).values(
            id=uuid4(), client_id=client_id, client_secret_hash=None,
            redirect_uris=["https://chatgpt.com/callback"], client_name="test", created_at=NOW,
        )
    )
    authorization_id = uuid4()
    connection.execute(
        insert(ai_oauth_authorizations).values(
            id=authorization_id, client_id=client_id, grant_id=grant_id,
            grant_generation=1, created_at=NOW, revoked_at=None,
        )
    )
    return authorization_id


def test_grant_revoke_invalidates_oauth_tokens_atomically() -> None:
    engine = _engine_with_oauth_tables()
    grant_id = uuid4()
    with engine.begin() as connection:
        authorization_id = _insert_authorization(connection, grant_id=grant_id)
        savepoint = connection.begin_nested()
        revoke_grant_authorizations_in_transaction(connection, (grant_id,), now=NOW)
        assert connection.scalar(
            select(ai_oauth_authorizations.c.revoked_at).where(ai_oauth_authorizations.c.id == authorization_id)
        ) is not None
        savepoint.rollback()
        assert connection.scalar(
            select(ai_oauth_authorizations.c.revoked_at).where(ai_oauth_authorizations.c.id == authorization_id)
        ) is None


def test_revoke_scoped_to_authorization_family() -> None:
    engine = _engine_with_oauth_tables()
    grant_a, grant_b = uuid4(), uuid4()
    with engine.begin() as connection:
        auth_a = _insert_authorization(connection, grant_id=grant_a, client_id="atc_a")
        auth_b = _insert_authorization(connection, grant_id=grant_b, client_id="atc_b")
        revoke_grant_authorizations_in_transaction(connection, (grant_a,), now=NOW)
        rows = {
            row.id: row.revoked_at
            for row in connection.execute(
                select(
                    ai_oauth_authorizations.c.id,
                    ai_oauth_authorizations.c.revoked_at,
                )
            )
        }
        assert rows[auth_a] is not None
        assert rows[auth_b] is None


def test_lifecycle_repositories_wire_oauth_revocation_into_same_connection() -> None:
    root = Path(__file__).resolve().parents[1] / "app" / "persistence"
    grant_source = (root / "rooms" / "ai_controllers.py").read_text(encoding="utf-8")
    room_source = (root / "mcp" / "room_lifecycle.py").read_text(encoding="utf-8")
    assert "self.grant_authorization_revoker(connection, grant_ids, now=now)" in grant_source
    assert "revoke_grant_authorizations_in_transaction(\n            connection," in room_source
    assert "class M04BSeatRepository" in room_source
    assert "class M04BSessionRepository" in room_source
