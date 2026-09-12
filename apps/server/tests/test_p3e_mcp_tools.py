from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.rooms.ai_controllers import get_ai_controller_service
from app.domain.rooms.ai_controllers import AIControllerAuthView
from app.domain.rooms.exploration import ExplorationInputKind
from app.mcp.protocol import MCP_PROTOCOL_VERSION
from app.mcp.server import router


class _FakeAIControllerService:
    def __init__(self, auth: AIControllerAuthView) -> None:
        self.auth = auth

    def authenticate(self, token: str, *, touch: bool = False) -> AIControllerAuthView:
        return self.auth


class _FakeToolService:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def get_session_context(self, token: str, *, authenticated=None):
        self.calls.append(("get_session_context", token, authenticated))
        return {"mode": "active_session", "scope": "fake"}

    def start_session(self, token: str, *, authenticated=None):
        self.calls.append(("start_session", token, authenticated))
        return {"id": str(uuid4()), "status": "active"}

    def get_character_context(self, token: str, *, authenticated=None):
        self.calls.append(("get_character_context", token, authenticated))
        return {"id": str(uuid4()), "name": "Ada"}

    def post_text(self, token: str, *, kind, input, authenticated=None):
        self.calls.append(("post_text", token, kind, input, authenticated))
        return {"kind": kind.value, "text": input.text}

    async def wait_for_event(self, token: str, input, *, authenticated=None):
        self.calls.append(("wait_for_event", token, input, authenticated))
        return {
            "after_seq": input.after_seq,
            "cursor": input.after_seq,
            "events": [],
        }


def _auth(*, role: str = "player", session_bound: bool = True) -> AIControllerAuthView:
    return AIControllerAuthView(
        grant_id=uuid4(),
        room_id=uuid4(),
        campaign_id=uuid4(),
        seat_id=uuid4(),
        role=role,
        session_id=uuid4() if session_bound else None,
        generation=3,
        active_character_id=uuid4() if role == "player" and session_bound else None,
        is_current_dm=role == "dm" and session_bound,
        temporary_instruction="Keep the torch low." if session_bound else None,
    )


def _client(auth: AIControllerAuthView) -> tuple[TestClient, _FakeToolService]:
    fake_controller = _FakeAIControllerService(auth)
    fake_tools = _FakeToolService()
    app = FastAPI()
    app.include_router(router)
    app.state.ai_tool_application_service = fake_tools
    app.dependency_overrides[get_ai_controller_service] = lambda: fake_controller
    return TestClient(app), fake_tools


def _body(method: str, *, params: dict | None = None, request_id=1) -> dict:
    merged = dict(params or {})
    merged["_meta"] = {
        "io.modelcontextprotocol/protocolVersion": MCP_PROTOCOL_VERSION,
        "io.modelcontextprotocol/clientCapabilities": {},
        "io.modelcontextprotocol/clientInfo": {"name": "p3e-test", "version": "1"},
    }
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": merged}


def _headers(method: str, *, name: str | None = None) -> dict[str, str]:
    result = {
        "Authorization": "Bearer fake-token",
        "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
        "Mcp-Method": method,
    }
    if name is not None:
        result["Mcp-Name"] = name
    return result


def test_tools_list_works_without_discovery_and_is_player_scoped() -> None:
    client, _ = _client(_auth(role="player"))

    response = client.post(
        "/mcp",
        json=_body("tools/list"),
        headers=_headers("tools/list"),
    )

    assert response.status_code == 200
    result = response.json()["result"]
    names = [tool["name"] for tool in result["tools"]]
    assert names[0] == "get_session_context"
    assert "get_character_context" in names
    assert "post_action" in names
    assert "wait_for_event" in names
    assert "start_session" not in names
    assert "set_stage_text" not in names
    assert "request_check" not in names
    assert "resolve_action" not in names
    assert result["ttlMs"] > 0
    assert result["cacheScope"] == "private"


def test_pre_session_dm_catalog_matches_active_dm_catalog() -> None:
    # 2026-09-12 (M04-C): the DM catalog no longer shrinks before start_session;
    # gameplay tools are listed but reject calls with active_session_required.
    before, _ = _client(_auth(role="dm", session_bound=False))
    after, _ = _client(_auth(role="dm"))

    listed_before = before.post("/mcp", json=_body("tools/list"), headers=_headers("tools/list"))
    listed_after = after.post("/mcp", json=_body("tools/list"), headers=_headers("tools/list"))

    assert listed_before.status_code == 200
    names_before = [item["name"] for item in listed_before.json()["result"]["tools"]]
    names_after = [item["name"] for item in listed_after.json()["result"]["tools"]]
    assert names_before == names_after
    assert names_before[:2] == ["get_session_context", "start_session"]
    assert "post_narration" in names_before
    assert "quick_roll" not in names_before


def test_active_dm_catalog_has_fine_grained_tools_but_no_resolve_action() -> None:
    client, _ = _client(_auth(role="dm"))

    response = client.post(
        "/mcp",
        json=_body("tools/list"),
        headers=_headers("tools/list"),
    )

    names = [item["name"] for item in response.json()["result"]["tools"]]
    assert "post_narration" in names
    assert "set_stage_text" in names
    assert "request_check" in names
    assert "update_character_state" in names
    assert "resolve_action" not in names
    assert "get_character_context" not in names
    assert "quick_roll" not in names


def test_post_action_dispatches_to_shared_application_facade() -> None:
    auth = _auth(role="player")
    client, tools = _client(auth)

    response = client.post(
        "/mcp",
        json=_body(
            "tools/call",
            params={
                "name": "post_action",
                "arguments": {"text": "I check the doorway.", "idempotency_key": "a-1"},
            },
        ),
        headers=_headers("tools/call", name="post_action"),
    )

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["isError"] is False
    assert result["structuredContent"] == {
        "ok": True,
        "data": {"kind": "action", "text": "I check the doorway."},
    }
    call = tools.calls[0]
    assert call[0:3] == ("post_text", "fake-token", ExplorationInputKind.ACTION)
    assert call[3].text == "I check the doorway."
    assert call[4] is auth


def test_role_forbidden_tool_returns_stable_structured_error_without_dispatch() -> None:
    client, tools = _client(_auth(role="player"))

    response = client.post(
        "/mcp",
        json=_body(
            "tools/call",
            params={
                "name": "set_stage_text",
                "arguments": {"expected_revision": 1, "text": "A locked door."},
            },
        ),
        headers=_headers("tools/call", name="set_stage_text"),
    )

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["isError"] is True
    assert result["structuredContent"]["error"]["code"] == "permission_denied"
    assert set(result["structuredContent"]["error"]["messages"]) == {"en", "zh-TW"}
    assert tools.calls == []


def test_pre_session_dm_gameplay_tool_returns_active_session_required() -> None:
    client, tools = _client(_auth(role="dm", session_bound=False))

    response = client.post(
        "/mcp",
        json=_body(
            "tools/call",
            params={"name": "post_narration", "arguments": {"text": "Welcome."}},
        ),
        headers=_headers("tools/call", name="post_narration"),
    )

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["isError"] is True
    assert result["structuredContent"]["error"]["code"] == "active_session_required"
    assert tools.calls == []


def test_wait_for_event_is_awaited_and_returns_normal_empty_success() -> None:
    auth = _auth(role="player")
    client, tools = _client(auth)

    response = client.post(
        "/mcp",
        json=_body(
            "tools/call",
            params={
                "name": "wait_for_event",
                "arguments": {"after_seq": 9, "limit": 20, "timeout": 0},
            },
        ),
        headers=_headers("tools/call", name="wait_for_event"),
    )

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["isError"] is False
    assert result["structuredContent"]["data"]["events"] == []
    assert result["structuredContent"]["data"]["cursor"] == 9
    assert tools.calls[0][0] == "wait_for_event"
    assert tools.calls[0][3] is auth


def test_invalid_tool_arguments_are_structured_not_transport_exceptions() -> None:
    client, _ = _client(_auth(role="player"))

    response = client.post(
        "/mcp",
        json=_body(
            "tools/call",
            params={"name": "post_action", "arguments": {"text": ""}},
        ),
        headers=_headers("tools/call", name="post_action"),
    )

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["isError"] is True
    assert result["structuredContent"]["error"]["code"] == "invalid_arguments"
