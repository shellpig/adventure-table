from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.mcp.oauth import get_oauth_repository, router
from app.persistence.mcp.oauth import StoredOAuthClient


class FakeOAuthRepository:
    def __init__(self) -> None:
        self.clients: dict[str, StoredOAuthClient] = {}

    def create_client(
        self,
        *,
        client_id: str,
        redirect_uris: tuple[str, ...],
        client_name: str | None,
        client_secret_hash: str | None = None,
        now=None,
    ) -> StoredOAuthClient:
        client = StoredOAuthClient(
            id=uuid4(),
            client_id=client_id,
            client_secret_hash=client_secret_hash,
            redirect_uris=redirect_uris,
            client_name=client_name,
            created_at=datetime.now(timezone.utc),
        )
        self.clients[client_id] = client
        return client

    def get_client(self, client_id: str) -> StoredOAuthClient | None:
        return self.clients.get(client_id)


def _client(repository: FakeOAuthRepository) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_oauth_repository] = lambda: repository
    return TestClient(app)


def test_oauth_metadata_advertises_preflight_contract() -> None:
    client = _client(FakeOAuthRepository())

    protected = client.get("/.well-known/oauth-protected-resource")
    assert protected.status_code == 200
    assert protected.json()["resource"] == "http://testserver/mcp"
    assert protected.json()["authorization_servers"] == ["http://testserver"]

    server = client.get("/.well-known/oauth-authorization-server")
    assert server.status_code == 200
    payload = server.json()
    assert payload["authorization_endpoint"].endswith("/mcp/oauth/authorize")
    assert payload["token_endpoint"].endswith("/mcp/oauth/token")
    assert payload["registration_endpoint"].endswith("/mcp/oauth/register")
    assert payload["grant_types_supported"] == ["authorization_code", "refresh_token"]
    assert payload["code_challenge_methods_supported"] == ["S256"]


def test_dynamic_registration_creates_public_client_with_exact_redirects() -> None:
    repository = FakeOAuthRepository()
    client = _client(repository)

    response = client.post(
        "/mcp/oauth/register",
        json={
            "client_name": "ChatGPT",
            "redirect_uris": [
                "https://chatgpt.com/connector_platform_oauth_redirect",
                "https://chatgpt.com/connector_platform_oauth_redirect",
            ],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["client_id"].startswith("atc_")
    assert payload["redirect_uris"] == [
        "https://chatgpt.com/connector_platform_oauth_redirect"
    ]
    assert payload["token_endpoint_auth_method"] == "none"
    assert payload["client_id"] in repository.clients


def test_dynamic_registration_rejects_non_https_redirect() -> None:
    client = _client(FakeOAuthRepository())
    response = client.post(
        "/mcp/oauth/register",
        json={"redirect_uris": ["http://example.test/callback"]},
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_redirect_uri"


def test_authorize_get_requires_exact_registered_redirect_and_pkce() -> None:
    repository = FakeOAuthRepository()
    stored = repository.create_client(
        client_id="atc_test",
        redirect_uris=("https://chatgpt.com/callback",),
        client_name="ChatGPT",
    )
    client = _client(repository)

    response = client.get(
        "/mcp/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": stored.client_id,
            "redirect_uri": "https://chatgpt.com/callback",
            "state": "opaque-state",
            "code_challenge": "challenge",
            "code_challenge_method": "S256",
            "locale": "zh-TW",
        },
    )
    assert response.status_code == 200
    assert 'name="ai_join_token"' in response.text
    assert "opaque-state" in response.text
    assert "授權 Adventure Table" in response.text

    wrong_redirect = client.get(
        "/mcp/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": stored.client_id,
            "redirect_uri": "https://evil.example/callback",
            "code_challenge": "challenge",
            "code_challenge_method": "S256",
        },
    )
    assert wrong_redirect.status_code == 400
    assert wrong_redirect.json()["error"] == "oauth_invalid_client"
