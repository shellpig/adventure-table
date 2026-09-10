from __future__ import annotations

import asyncio
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.mcp.server as mcp_server
from app.api.rooms.ai_controllers import get_ai_controller_service
from app.domain.rooms.ai_controllers import AIControllerAuthView
from app.mcp.auth import MCPAuthenticatedRequest
from app.mcp.protocol import MCP_PROTOCOL_VERSION


def _body() -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": MCP_PROTOCOL_VERSION,
                "io.modelcontextprotocol/clientCapabilities": {},
            }
        },
    }


def _headers() -> dict[str, str]:
    return {
        "Authorization": "Bearer fake-token",
        "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
        "Mcp-Method": "tools/list",
    }


def test_mcp_authentication_runs_outside_asgi_event_loop(monkeypatch) -> None:
    auth = AIControllerAuthView(
        grant_id=uuid4(),
        room_id=uuid4(),
        campaign_id=uuid4(),
        seat_id=uuid4(),
        role="player",
        session_id=uuid4(),
        generation=1,
        active_character_id=uuid4(),
        is_current_dm=False,
        temporary_instruction=None,
    )
    saw_running_loop: list[bool] = []

    def fake_authenticate(request, service):
        del request, service
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            saw_running_loop.append(False)
        else:
            saw_running_loop.append(True)
        return MCPAuthenticatedRequest(token="fake-token", auth=auth)

    monkeypatch.setattr(mcp_server, "authenticate_request", fake_authenticate)

    app = FastAPI()
    app.include_router(mcp_server.router)
    app.dependency_overrides[get_ai_controller_service] = lambda: object()

    response = TestClient(app).post("/mcp", json=_body(), headers=_headers())

    assert response.status_code == 200
    assert saw_running_loop == [False]
