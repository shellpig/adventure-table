from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from uuid import uuid4

import pytest
from starlette.requests import Request

from app.mcp.auth import MCPAuthenticationError, authenticate_request
from app.persistence.rooms.ai_controllers import AIControllerGrantUnauthorizedPersistenceError


def _request(token: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/mcp",
            "headers": [(b"authorization", f"Bearer {token}".encode("ascii"))],
        }
    )


@dataclass
class FakeGrantRepository:
    current_scope: object | None = None
    error: Exception | None = None

    def resolve_current_scope(self, grant_id, *, touch=False):
        if self.error is not None:
            raise self.error
        return self.current_scope


class FakeService:
    def __init__(self, repository: FakeGrantRepository) -> None:
        self.repository = repository
        self.legacy_calls: list[tuple[str, bool]] = []

    def authenticate(self, token: str, *, touch: bool = False):
        self.legacy_calls.append((token, touch))
        return SimpleNamespace(grant_id=uuid4(), role="player")

    @staticmethod
    def _auth_view(scope):
        return scope


class FakeOAuthRepository:
    def __init__(self, authorization=None) -> None:
        self.authorization = authorization
        self.seen_hash: str | None = None
        self.revoked: list[object] = []

    def resolve_active_access(self, token_hash: str, *, touch: bool = False):
        self.seen_hash = token_hash
        if self.authorization is None:
            return None
        return SimpleNamespace(), self.authorization

    def revoke_authorization(self, authorization_id) -> None:
        self.revoked.append(authorization_id)


def test_legacy_ai_join_token_path_is_unchanged() -> None:
    service = FakeService(FakeGrantRepository())
    result = authenticate_request(
        _request("at_ai_12345678123456781234567812345678_long-enough-secret"),
        service,
    )
    assert result.auth.role == "player"
    assert service.legacy_calls == [
        ("at_ai_12345678123456781234567812345678_long-enough-secret", True)
    ]


def test_oauth_access_resolves_family_then_revalidates_current_grant() -> None:
    grant_id = uuid4()
    authorization_id = uuid4()
    current = SimpleNamespace(grant_id=grant_id, role="dm")
    service = FakeService(FakeGrantRepository(current_scope=current))
    oauth = FakeOAuthRepository(
        SimpleNamespace(id=authorization_id, grant_id=grant_id)
    )

    result = authenticate_request(
        _request("at_oa_example-token"),
        service,
        oauth_repository=oauth,
    )

    assert result.auth is current
    assert oauth.seen_hash is not None
    assert oauth.revoked == []


def test_oauth_access_denies_revoked_family_before_grant_lookup() -> None:
    service = FakeService(FakeGrantRepository(current_scope=SimpleNamespace()))
    oauth = FakeOAuthRepository()

    with pytest.raises(MCPAuthenticationError) as exc_info:
        authenticate_request(
            _request("at_oa_expired"),
            service,
            oauth_repository=oauth,
        )

    assert exc_info.value.stable_code == "ai_token_unauthorized"


def test_oauth_access_revokes_family_when_p3_authority_is_stale() -> None:
    grant_id = uuid4()
    authorization_id = uuid4()
    service = FakeService(
        FakeGrantRepository(
            error=AIControllerGrantUnauthorizedPersistenceError("stale")
        )
    )
    oauth = FakeOAuthRepository(
        SimpleNamespace(id=authorization_id, grant_id=grant_id)
    )

    with pytest.raises(MCPAuthenticationError) as exc_info:
        authenticate_request(
            _request("at_oa_stale"),
            service,
            oauth_repository=oauth,
        )

    assert exc_info.value.stable_code == "ai_token_unauthorized"
    assert oauth.revoked == [authorization_id]


def test_unknown_bearer_prefix_is_not_treated_as_legacy_join_token() -> None:
    service = FakeService(FakeGrantRepository())
    with pytest.raises(MCPAuthenticationError) as exc_info:
        authenticate_request(_request("something-else"), service)
    assert exc_info.value.stable_code == "ai_token_required"
    assert service.legacy_calls == []
