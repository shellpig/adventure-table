from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, insert, update
from sqlalchemy.pool import StaticPool

from app.api.rooms.ai_controllers import get_ai_controller_service
from app.db import metadata
from app.domain.rooms.ai_controller_tokens import mint_ai_controller_token
from app.domain.rooms.ai_controllers import AIControllerService
from app.mcp.protocol import MCP_PROTOCOL_VERSION
from app.mcp.server import router
from app.persistence.characters import characters
from app.persistence.rooms.ai_controllers import AIControllerGrantRepository
from app.persistence.rooms.tables import (
    ai_controller_grants,
    campaign_seats,
    campaigns,
    room_access_sessions,
    rooms,
    sessions,
)


def _engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata.create_all(
        engine,
        tables=[
            characters,
            rooms,
            room_access_sessions,
            campaigns,
            campaign_seats,
            sessions,
            ai_controller_grants,
        ],
    )
    return engine


def _seed_pre_session_dm(connection):
    now = datetime.now(timezone.utc)
    room_id, campaign_id, seat_id = uuid4(), uuid4(), uuid4()
    connection.execute(
        insert(rooms).values(
            id=room_id,
            code="P3E001",
            name="P3E MCP Auth",
            password_salt=b"s" * 32,
            password_hash=b"h" * 64,
            owner_key_hash=b"o" * 32,
            dm_key_hash=b"d" * 32,
            active_campaign_id=None,
            created_at=now,
            updated_at=now,
        )
    )
    connection.execute(
        insert(campaigns).values(
            id=campaign_id,
            room_id=room_id,
            name="P3E Campaign",
            ruleset="dnd5e-2014",
            status="active",
        )
    )
    connection.execute(
        insert(campaign_seats).values(
            id=seat_id,
            campaign_id=campaign_id,
            role="dm",
            label="AI DM",
            controller_kind="none",
            controller_access_session_id=None,
            ai_controller_grant_id=None,
            controller_epoch=0,
            selected_character_id=None,
            archived_at=None,
        )
    )
    connection.execute(
        update(rooms).where(rooms.c.id == room_id).values(active_campaign_id=campaign_id)
    )
    return room_id, campaign_id, seat_id


def _mint(repo, *, room_id, campaign_id, seat_id, now, minutes=5):
    token = mint_ai_controller_token()
    grant = repo.mint_pre_session_dm(
        grant_id=token.grant_id,
        room_id=room_id,
        campaign_id=campaign_id,
        seat_id=seat_id,
        secret_hash=token.secret_hash,
        secret_prefix=token.display_hint,
        expires_at=now + timedelta(minutes=minutes),
        now=now,
    )
    return token, grant


def _client(service: AIControllerService) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_ai_controller_service] = lambda: service
    return TestClient(app)


def _body() -> dict:
    return {
        "jsonrpc": "2.0",
        "id": "auth-lifecycle",
        "method": "server/discover",
        "params": {
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": MCP_PROTOCOL_VERSION,
                "io.modelcontextprotocol/clientCapabilities": {},
                "io.modelcontextprotocol/clientInfo": {
                    "name": "p3e-auth-test",
                    "version": "1",
                },
            }
        },
    }


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
        "Mcp-Method": "server/discover",
    }


def _discover(client: TestClient, token: str):
    return client.post("/mcp", json=_body(), headers=_headers(token))


def _assert_unauthorized(response) -> None:
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    error = response.json()["error"]
    assert error["code"] == -32001
    assert error["data"]["code"] == "ai_token_unauthorized"


def test_mcp_reauthorizes_every_request_against_current_grant_generation() -> None:
    engine = _engine()
    repo = AIControllerGrantRepository(engine)
    service = AIControllerService(repo, None)  # type: ignore[arg-type]
    client = _client(service)
    now = datetime.now(timezone.utc)
    try:
        with engine.begin() as connection:
            room_id, campaign_id, seat_id = _seed_pre_session_dm(connection)

        first_token, first_grant = _mint(
            repo,
            room_id=room_id,
            campaign_id=campaign_id,
            seat_id=seat_id,
            now=now,
        )
        assert _discover(client, first_token.plaintext).status_code == 200

        wrong_secret = mint_ai_controller_token(grant_id=first_grant.id)
        _assert_unauthorized(_discover(client, wrong_secret.plaintext))

        second_token, second_grant = _mint(
            repo,
            room_id=room_id,
            campaign_id=campaign_id,
            seat_id=seat_id,
            now=now + timedelta(seconds=1),
        )
        assert second_grant.generation == first_grant.generation + 1
        _assert_unauthorized(_discover(client, first_token.plaintext))
        assert _discover(client, second_token.plaintext).status_code == 200

        with engine.begin() as connection:
            connection.execute(
                update(campaign_seats)
                .where(campaign_seats.c.id == seat_id)
                .values(controller_epoch=second_grant.generation + 1)
            )
        _assert_unauthorized(_discover(client, second_token.plaintext))
    finally:
        client.close()
        engine.dispose()


def test_mcp_rejects_expired_pre_session_grant_even_while_status_is_active() -> None:
    engine = _engine()
    repo = AIControllerGrantRepository(engine)
    service = AIControllerService(repo, None)  # type: ignore[arg-type]
    client = _client(service)
    now = datetime.now(timezone.utc)
    try:
        with engine.begin() as connection:
            room_id, campaign_id, seat_id = _seed_pre_session_dm(connection)
        token, grant = _mint(
            repo,
            room_id=room_id,
            campaign_id=campaign_id,
            seat_id=seat_id,
            now=now,
        )
        with engine.begin() as connection:
            connection.execute(
                update(ai_controller_grants)
                .where(ai_controller_grants.c.id == grant.id)
                .values(pre_session_expires_at=now - timedelta(seconds=1))
            )
        stored = repo.get(grant.id)
        assert stored is not None and stored.status == "active"

        _assert_unauthorized(_discover(client, token.plaintext))
    finally:
        client.close()
        engine.dispose()


def test_mcp_rejects_token_when_grant_scope_no_longer_matches_its_seat() -> None:
    engine = _engine()
    repo = AIControllerGrantRepository(engine)
    service = AIControllerService(repo, None)  # type: ignore[arg-type]
    client = _client(service)
    now = datetime.now(timezone.utc)
    try:
        with engine.begin() as connection:
            room_id, campaign_id, seat_id = _seed_pre_session_dm(connection)
            other_seat_id = uuid4()
            connection.execute(
                insert(campaign_seats).values(
                    id=other_seat_id,
                    campaign_id=campaign_id,
                    role="dm",
                    label="Other DM",
                    controller_kind="none",
                    controller_access_session_id=None,
                    ai_controller_grant_id=None,
                    controller_epoch=0,
                    selected_character_id=None,
                    archived_at=None,
                )
            )
        token, grant = _mint(
            repo,
            room_id=room_id,
            campaign_id=campaign_id,
            seat_id=seat_id,
            now=now,
        )
        assert _discover(client, token.plaintext).status_code == 200

        with engine.begin() as connection:
            connection.execute(
                update(ai_controller_grants)
                .where(ai_controller_grants.c.id == grant.id)
                .values(seat_id=other_seat_id)
            )
        _assert_unauthorized(_discover(client, token.plaintext))
    finally:
        client.close()
        engine.dispose()
