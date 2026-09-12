from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, insert
from starlette.requests import Request

from app.domain.rooms.ai_controllers import AIControllerAuthView, AIControllerUnauthorizedError
from app.mcp.auth import MCPAuthenticationError, authenticate_request
from app.mcp.tools import call_tool
from app.persistence.mcp.oauth import OAuthRepository, StoredOAuthAuthorization, StoredOAuthToken
from app.persistence.mcp.tables import ai_oauth_authorizations, ai_oauth_clients, ai_oauth_tokens


NOW = datetime(2026, 9, 12, tzinfo=timezone.utc)


def _request(token: str = "at_oa_test-token") -> Request:
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
        generation=4,
        active_character_id=uuid4(),
        is_current_dm=False,
    )


class _RejectingAuthority:
    def __init__(self, reason: str) -> None:
        self.reason = reason

    def authenticate_grant(self, grant_id, *, touch: bool = False):
        raise AIControllerUnauthorizedError(self.reason)


class _AcceptingAuthority:
    def __init__(self, view: AIControllerAuthView) -> None:
        self.view = view

    def authenticate(self, token: str, *, touch: bool = False):
        return self.view

    def authenticate_grant(self, grant_id, *, touch: bool = False):
        assert grant_id == self.view.grant_id
        return self.view


class _OAuthAccess:
    def __init__(self, authorization: StoredOAuthAuthorization) -> None:
        self.authorization = authorization
        self.revoked: list[object] = []

    def resolve_active_access(self, token_hash: str, *, touch: bool = False):
        return (
            StoredOAuthToken(
                uuid4(), token_hash, "access", self.authorization.id,
                NOW + timedelta(hours=1), None, None,
            ),
            self.authorization,
        )

    def revoke_authorization(self, authorization_id, *, now=None):
        self.revoked.append(authorization_id)


def _assert_stale_authority_denied(reason: str) -> None:
    grant_id = uuid4()
    authorization = StoredOAuthAuthorization(
        uuid4(), "atc_test", grant_id, 4, NOW, None
    )
    oauth = _OAuthAccess(authorization)
    with pytest.raises(MCPAuthenticationError) as exc_info:
        authenticate_request(_request(), _RejectingAuthority(reason), oauth)
    assert exc_info.value.stable_code == "ai_token_unauthorized"
    assert oauth.revoked == [authorization.id]


def test_seat_epoch_advance_invalidates_oauth_token() -> None:
    _assert_stale_authority_denied("Seat controller epoch changed")


def test_session_end_invalidates_oauth_tokens() -> None:
    _assert_stale_authority_denied("Session ended or abandoned")


def test_pre_session_ttl_expiry_invalidates_oauth_token() -> None:
    _assert_stale_authority_denied("Pre-session AI DM grant expired")


def test_grant_revoke_denies_oauth_access_and_revokes_family() -> None:
    _assert_stale_authority_denied("AI controller grant is revoked")


def test_tools_call_identical_via_both_tokens() -> None:
    grant_id = uuid4()
    view = _view(grant_id)

    class _ToolService:
        def get_session_context(self, token, *, authenticated):
            assert authenticated == view
            return {"phase": "active", "grant_id": str(authenticated.grant_id)}

    service = _ToolService()
    legacy = asyncio.run(
        call_tool(
            service,
            token="at_ai_test-token",
            auth=view,
            name="get_session_context",
            arguments={},
        )
    )
    oauth = asyncio.run(
        call_tool(
            service,
            token="at_oa_test-token",
            auth=view,
            name="get_session_context",
            arguments={},
        )
    )
    assert legacy["structuredContent"] == oauth["structuredContent"]


def test_oauth_token_expiry_enforced() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE ai_controller_grants (id CHAR(32) PRIMARY KEY)"
        )
    ai_oauth_clients.create(engine)
    ai_oauth_authorizations.create(engine)
    ai_oauth_tokens.create(engine)

    grant_id = uuid4()
    authorization_id = uuid4()
    token_hash = "a" * 64
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO ai_controller_grants (id) VALUES (?)", (grant_id.hex,)
        )
        connection.execute(insert(ai_oauth_clients).values(
            id=uuid4(), client_id="atc_expiry", client_secret_hash=None,
            redirect_uris=["https://chatgpt.com/callback"], client_name="test",
            created_at=NOW,
        ))
        connection.execute(insert(ai_oauth_authorizations).values(
            id=authorization_id, client_id="atc_expiry", grant_id=grant_id,
            grant_generation=1, created_at=NOW, revoked_at=None,
        ))
        connection.execute(insert(ai_oauth_tokens).values(
            id=uuid4(), token_hash=token_hash, kind="access",
            authorization_id=authorization_id,
            expires_at=NOW - timedelta(seconds=1), revoked_at=None,
            last_used_at=None,
        ))

    repository = OAuthRepository(engine)
    assert repository.resolve_active_access(token_hash, now=NOW) is None
