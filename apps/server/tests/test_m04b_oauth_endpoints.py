from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.rooms.ai_controllers import get_ai_controller_service
from app.domain.rooms.ai_controllers import AIControllerUnauthorizedError
from app.mcp.oauth import (
    _hash_secret,
    _pkce_s256,
    get_oauth_repository,
    router,
)
from app.persistence.mcp.oauth import (
    StoredOAuthAuthorization,
    StoredOAuthAuthorizationCode,
    StoredOAuthClient,
    StoredOAuthToken,
)


NOW = datetime(2026, 9, 12, tzinfo=timezone.utc)
REDIRECT = "https://chatgpt.com/connector_platform_oauth_redirect"
VERIFIER = "m04b-pkce-verifier-abcdefghijklmnopqrstuvwxyz-0123456789"


class FakeOAuthService:
    def __init__(self) -> None:
        self.clients: dict[str, StoredOAuthClient] = {}
        self.authorizations: dict[UUID, StoredOAuthAuthorization] = {}
        self.codes: dict[str, StoredOAuthAuthorizationCode] = {}
        self.tokens: dict[str, StoredOAuthToken] = {}
        self.grant_replace_calls: list[UUID] = []

    def create_client(self, *, client_id, redirect_uris, client_name, client_secret_hash=None, now=None):
        value = StoredOAuthClient(uuid4(), client_id, client_secret_hash, redirect_uris, client_name, now or NOW)
        self.clients[client_id] = value
        return value

    def get_client(self, client_id):
        return self.clients.get(client_id)

    def replace_authorization_for_grant(self, *, client_id, grant_id, now=None):
        stamp = now or NOW
        for key, value in tuple(self.authorizations.items()):
            if value.grant_id == grant_id and value.revoked_at is None:
                self.authorizations[key] = replace(value, revoked_at=stamp)
        value = StoredOAuthAuthorization(uuid4(), client_id, grant_id, 1, stamp, None)
        self.authorizations[value.id] = value
        self.grant_replace_calls.append(grant_id)
        return value

    def get_authorization(self, authorization_id):
        return self.authorizations.get(authorization_id)

    def revoke_authorization(self, authorization_id, *, now=None):
        value = self.authorizations[authorization_id]
        self.authorizations[authorization_id] = replace(value, revoked_at=now or NOW)

    def create_authorization_code(self, *, code_hash, authorization_id, code_challenge, redirect_uri, expires_at):
        value = StoredOAuthAuthorizationCode(code_hash, authorization_id, code_challenge, redirect_uri, expires_at, None)
        self.codes[code_hash] = value
        return value

    def get_authorization_code(self, code_hash):
        return self.codes.get(code_hash)

    def consume_authorization_code(self, code_hash, *, now=None):
        value = self.codes.get(code_hash)
        if value is None or value.consumed_at is not None:
            return False
        self.codes[code_hash] = replace(value, consumed_at=now or NOW)
        return True

    def issue_token_pair(self, *, authorization_id, access_hash, access_expires_at, refresh_hash, refresh_expires_at):
        self.tokens[access_hash] = StoredOAuthToken(uuid4(), access_hash, "access", authorization_id, access_expires_at, None, None)
        self.tokens[refresh_hash] = StoredOAuthToken(uuid4(), refresh_hash, "refresh", authorization_id, refresh_expires_at, None, None)

    def get_token(self, token_hash):
        return self.tokens.get(token_hash)

    def replace_refresh_token(self, *, presented_hash, new_refresh_hash, new_refresh_expires_at, new_access_hash, new_access_expires_at, now=None):
        old = self.tokens[presented_hash]
        if old.revoked_at is not None:
            self.revoke_authorization(old.authorization_id, now=now)
            return None, True
        stamp = now or NOW
        self.tokens[presented_hash] = replace(old, revoked_at=stamp)
        self.tokens[new_refresh_hash] = StoredOAuthToken(uuid4(), new_refresh_hash, "refresh", old.authorization_id, new_refresh_expires_at, None, None)
        self.tokens[new_access_hash] = StoredOAuthToken(uuid4(), new_access_hash, "access", old.authorization_id, new_access_expires_at, None, None)
        return self.tokens[new_refresh_hash], False

    def revoke_token_family(self, token_hash):
        token = self.tokens.get(token_hash)
        if token is not None:
            self.revoke_authorization(token.authorization_id)


class FakeAuthority:
    def __init__(self, grant_id: UUID) -> None:
        self.grant_id = grant_id
        self.valid = True
        self.join_calls: list[str] = []
        self.grant_calls: list[UUID] = []

    def authenticate(self, token: str, *, touch: bool = False):
        self.join_calls.append(token)
        if token != "valid-join-token" or not self.valid:
            raise AIControllerUnauthorizedError("invalid")
        return SimpleNamespace(grant_id=self.grant_id)

    def authenticate_grant(self, grant_id: UUID, *, touch: bool = False):
        self.grant_calls.append(grant_id)
        if grant_id != self.grant_id or not self.valid:
            raise AIControllerUnauthorizedError("invalid")
        return SimpleNamespace(grant_id=grant_id)


def _client(repo: FakeOAuthService, authority: FakeAuthority) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_oauth_repository] = lambda: repo
    app.dependency_overrides[get_ai_controller_service] = lambda: authority
    return TestClient(app)


def _register(client: TestClient) -> str:
    response = client.post("/mcp/oauth/register", json={"client_name": "ChatGPT", "redirect_uris": [REDIRECT]})
    assert response.status_code == 201
    return response.json()["client_id"]


def _authorize(client: TestClient, client_id: str, token: str = "valid-join-token"):
    response = client.post(
        "/mcp/oauth/authorize",
        data={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT,
            "state": "state-1",
            "code_challenge": _pkce_s256(VERIFIER),
            "code_challenge_method": "S256",
            "ai_join_token": token,
        },
        follow_redirects=False,
    )
    return response


def _exchange(client: TestClient, client_id: str, code: str, verifier: str = VERIFIER):
    return client.post(
        "/mcp/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "redirect_uri": REDIRECT,
            "code_verifier": verifier,
        },
    )


def test_metadata_endpoints_exist_when_required() -> None:
    repo, authority = FakeOAuthService(), FakeAuthority(uuid4())
    client = _client(repo, authority)
    assert client.get("/.well-known/oauth-protected-resource").status_code == 200
    payload = client.get("/.well-known/oauth-authorization-server").json()
    assert payload["authorization_endpoint"].endswith("/mcp/oauth/authorize")
    assert payload["token_endpoint_auth_methods_supported"] == ["none"]
    assert payload["code_challenge_methods_supported"] == ["S256"]


def test_register_returns_client_id() -> None:
    repo, authority = FakeOAuthService(), FakeAuthority(uuid4())
    client_id = _register(_client(repo, authority))
    assert client_id.startswith("atc_")
    assert repo.clients[client_id].client_secret_hash is None


def test_authorize_page_bilingual() -> None:
    repo, authority = FakeOAuthService(), FakeAuthority(uuid4())
    client = _client(repo, authority)
    client_id = _register(client)
    params = {"response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT, "code_challenge": _pkce_s256(VERIFIER), "code_challenge_method": "S256"}
    zh = client.get("/mcp/oauth/authorize", params={**params, "locale": "zh-TW"})
    en = client.get("/mcp/oauth/authorize", params={**params, "locale": "en"})
    assert zh.status_code == en.status_code == 200
    assert "授權 Adventure Table" in zh.text
    assert "Authorize Adventure Table" in en.text
    assert 'name="ai_join_token"' in zh.text and 'name="ai_join_token"' in en.text
    assert str(authority.grant_id) not in zh.text + en.text


def test_authorize_with_valid_join_token_redirects_with_code() -> None:
    repo, authority = FakeOAuthService(), FakeAuthority(uuid4())
    client = _client(repo, authority)
    response = _authorize(client, _register(client))
    assert response.status_code == 302
    query = parse_qs(urlparse(response.headers["location"]).query)
    assert query["state"] == ["state-1"]
    assert query["code"][0].startswith("ac_oa_")
    assert repo.grant_replace_calls == [authority.grant_id]


def test_authorize_with_bad_join_token_rejected_without_side_effect() -> None:
    repo, authority = FakeOAuthService(), FakeAuthority(uuid4())
    client = _client(repo, authority)
    response = _authorize(client, _register(client), "bad-token")
    assert response.status_code == 401
    assert repo.authorizations == {}
    assert repo.codes == {}


def test_token_exchange_with_pkce_and_code_single_use() -> None:
    repo, authority = FakeOAuthService(), FakeAuthority(uuid4())
    client = _client(repo, authority)
    client_id = _register(client)
    auth = _authorize(client, client_id)
    code = parse_qs(urlparse(auth.headers["location"]).query)["code"][0]
    first = _exchange(client, client_id, code)
    assert first.status_code == 200
    body = first.json()
    assert body["access_token"].startswith("at_oa_")
    assert body["refresh_token"].startswith("rt_oa_")
    assert body["access_token"] not in repo.tokens
    assert _hash_secret(body["access_token"]) in repo.tokens
    second = _exchange(client, client_id, code)
    assert second.status_code == 400
    assert second.json()["error"] == "invalid_grant"


def test_token_exchange_bad_pkce_rejected_without_consuming_code() -> None:
    repo, authority = FakeOAuthService(), FakeAuthority(uuid4())
    client = _client(repo, authority)
    client_id = _register(client)
    auth = _authorize(client, client_id)
    code = parse_qs(urlparse(auth.headers["location"]).query)["code"][0]
    response = _exchange(client, client_id, code, "wrong-verifier-abcdefghijklmnopqrstuvwxyz-0123456789")
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"
    assert repo.codes[_hash_secret(code)].consumed_at is None


def test_refresh_rotates_access_and_revalidates_grant_authority() -> None:
    repo, authority = FakeOAuthService(), FakeAuthority(uuid4())
    client = _client(repo, authority)
    client_id = _register(client)
    auth = _authorize(client, client_id)
    code = parse_qs(urlparse(auth.headers["location"]).query)["code"][0]
    issued = _exchange(client, client_id, code).json()
    old_refresh = issued["refresh_token"]
    response = client.post("/mcp/oauth/token", data={"grant_type": "refresh_token", "client_id": client_id, "refresh_token": old_refresh})
    assert response.status_code == 200
    rotated = response.json()
    assert rotated["access_token"] != issued["access_token"]
    assert rotated["refresh_token"] != old_refresh
    assert repo.tokens[_hash_secret(old_refresh)].revoked_at is not None
    assert authority.grant_calls[-1] == authority.grant_id

    authority.valid = False
    denied = client.post("/mcp/oauth/token", data={"grant_type": "refresh_token", "client_id": client_id, "refresh_token": rotated["refresh_token"]})
    assert denied.status_code == 400
    assert denied.json()["error"] == "invalid_grant"
    authorization_id = repo.tokens[_hash_secret(rotated["refresh_token"])].authorization_id
    assert repo.authorizations[authorization_id].revoked_at is not None


def test_refresh_replay_revokes_authorization_family() -> None:
    repo, authority = FakeOAuthService(), FakeAuthority(uuid4())
    client = _client(repo, authority)
    client_id = _register(client)
    auth = _authorize(client, client_id)
    code = parse_qs(urlparse(auth.headers["location"]).query)["code"][0]
    issued = _exchange(client, client_id, code).json()
    old_refresh = issued["refresh_token"]
    assert client.post("/mcp/oauth/token", data={"grant_type": "refresh_token", "client_id": client_id, "refresh_token": old_refresh}).status_code == 200
    replay = client.post("/mcp/oauth/token", data={"grant_type": "refresh_token", "client_id": client_id, "refresh_token": old_refresh})
    assert replay.status_code == 400
    authorization_id = repo.tokens[_hash_secret(old_refresh)].authorization_id
    assert repo.authorizations[authorization_id].revoked_at is not None
