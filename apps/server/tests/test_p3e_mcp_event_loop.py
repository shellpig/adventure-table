from __future__ import annotations

import asyncio
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.mcp.server as mcp_server
from app.api.rooms.ai_controllers import get_ai_controller_service
from app.domain.rooms.ai_controllers import AIControllerAuthView
from app.domain.rooms.ai_tools import AIToolApplicationService, WaitEventsInput
from app.domain.rooms.table_events import TableActorContext, TableActorKind
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


class _LoopCheckingController:
    def __init__(self, actor: TableActorContext) -> None:
        self.actor = actor
        self.saw_running_loop: list[bool] = []

    def resolve_actor(self, token: str, *, touch: bool = False) -> TableActorContext:
        del token, touch
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            self.saw_running_loop.append(False)
        else:
            self.saw_running_loop.append(True)
        return self.actor


class _EmptyEventPage:
    def __init__(self, after_seq: int) -> None:
        self.after_seq = after_seq

    def model_dump(self, *, mode: str) -> dict:
        del mode
        return {
            "after_seq": self.after_seq,
            "cursor": self.after_seq,
            "current_seq": self.after_seq,
            "events": [],
            "has_more": False,
        }


class _WaitEventService:
    async def wait_after(self, actor, *, after_seq, limit, timeout):
        del actor, limit, timeout
        return _EmptyEventPage(after_seq)


def test_direct_wait_facade_offloads_actor_resolution_before_async_wait() -> None:
    seat_id = uuid4()
    actor = TableActorContext(
        actor_kind=TableActorKind.AI,
        room_id=uuid4(),
        campaign_id=uuid4(),
        session_id=uuid4(),
        seat_id=seat_id,
        controlled_seat_ids=(seat_id,),
        role="player",
        is_current_dm=False,
        access_session_id=None,
        ai_controller_grant_id=uuid4(),
        grant_generation=1,
    )
    controller = _LoopCheckingController(actor)
    facade = AIToolApplicationService(
        ai_controller_service=controller,  # type: ignore[arg-type]
        session_service=None,  # type: ignore[arg-type]
        stage_service=None,  # type: ignore[arg-type]
        action_service=None,  # type: ignore[arg-type]
        roll_service=None,  # type: ignore[arg-type]
        state_service=None,  # type: ignore[arg-type]
        pending_action_service=None,  # type: ignore[arg-type]
        event_service=_WaitEventService(),  # type: ignore[arg-type]
        workspace_service=None,  # type: ignore[arg-type]
    )

    result = asyncio.run(
        facade.wait_for_event(
            "fake-token",
            WaitEventsInput(after_seq=7, limit=20, timeout=0),
        )
    )

    assert result["events"] == []
    assert result["cursor"] == 7
    assert controller.saw_running_loop == [False]
