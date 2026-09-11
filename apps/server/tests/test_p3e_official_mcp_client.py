from __future__ import annotations

import asyncio
from uuid import uuid4

from fastapi import FastAPI
import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from app.api.rooms.ai_controllers import get_ai_controller_service
from app.domain.rooms.ai_controllers import AIControllerAuthView
from app.mcp.protocol import MCP_PROTOCOL_VERSION
from app.mcp.server import router


class _RecordingController:
    def __init__(self, auth: AIControllerAuthView) -> None:
        self.auth = auth
        self.tokens: list[str] = []

    def authenticate(self, token: str, *, touch: bool = False) -> AIControllerAuthView:
        del touch
        self.tokens.append(token)
        return self.auth


class _ToolFacade:
    def __init__(self) -> None:
        self.auth_seen: AIControllerAuthView | None = None

    def post_text(self, token: str, *, kind, input, authenticated=None):
        del token
        self.auth_seen = authenticated
        return {
            "kind": f"exploration.{kind.value}",
            "text": input.text,
        }


def _auth() -> AIControllerAuthView:
    return AIControllerAuthView(
        grant_id=uuid4(),
        room_id=uuid4(),
        campaign_id=uuid4(),
        seat_id=uuid4(),
        role="player",
        session_id=uuid4(),
        generation=4,
        active_character_id=uuid4(),
        is_current_dm=False,
        temporary_instruction="Stay quiet.",
    )


def test_official_mcp_v2_client_negotiates_modern_wire_and_parses_structured_tool_result() -> None:
    asyncio.run(_exercise_official_client())


async def _exercise_official_client() -> None:
    auth = _auth()
    controller = _RecordingController(auth)
    tools = _ToolFacade()
    app = FastAPI()
    app.include_router(router)
    app.state.ai_tool_application_service = tools
    app.dependency_overrides[get_ai_controller_service] = lambda: controller

    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"Authorization": "Bearer official-sdk-token"},
    ) as http_client:
        target = streamable_http_client(
            "http://testserver/mcp",
            http_client=http_client,
            terminate_on_close=False,
        )
        async with Client(target, mode="auto") as client:
            assert client.protocol_version == MCP_PROTOCOL_VERSION

            listed = await client.list_tools()
            names = [tool.name for tool in listed.tools]
            assert "post_action" in names
            assert "resolve_action" not in names

            result = await client.call_tool(
                "post_action",
                {"text": "Inspect the archway."},
            )
            assert result.is_error is False
            assert result.structured_content == {
                "ok": True,
                "data": {
                    "kind": "exploration.action",
                    "text": "Inspect the archway.",
                },
            }

    # The SDK's configured static Authorization header reached every modern
    # request, while the request-level auth object was reused by tool dispatch.
    assert controller.tokens
    assert set(controller.tokens) == {"official-sdk-token"}
    assert tools.auth_seen is auth
