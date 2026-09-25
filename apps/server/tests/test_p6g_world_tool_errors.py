from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

import pytest

from app.domain.campaign_runtime.errors import CampaignRuntimeValidationError
from app.domain.campaign_runtime.payloads import RuntimeEntryPayloadError, parse_runtime_payload
from app.domain.rooms.ai_controllers import AIControllerAuthView
from app.mcp.tools import call_tool, tool_catalog


def _auth(role: str) -> AIControllerAuthView:
    return AIControllerAuthView(
        grant_id=uuid4(),
        room_id=uuid4(),
        campaign_id=uuid4(),
        seat_id=uuid4(),
        role=role,
        session_id=uuid4(),
        generation=1,
        is_current_dm=role == "dm",
    )


class _RaisingService:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def __getattr__(self, name: str) -> Any:
        def _raise(*args: Any, **kwargs: Any) -> Any:
            raise self.exc

        return _raise


def _bad_holder_error() -> RuntimeEntryPayloadError:
    # The shape an AI guessed in G4: `id` instead of `target_id`.
    with pytest.raises(RuntimeEntryPayloadError) as caught:
        parse_runtime_payload(
            "item", {"kind": "item", "holder_ref": {"kind": "character", "id": str(uuid4())}}
        )
    return caught.value


def _update_args() -> dict[str, Any]:
    return {
        "entry_id": str(uuid4()),
        "idempotency_key": "k",
        "patch": {"expected_revision": 1, "state": {"kind": "item"}},
    }


def test_dm_world_write_payload_error_carries_detail() -> None:
    exc = _bad_holder_error()
    res = asyncio.run(
        call_tool(
            _RaisingService(exc),  # type: ignore[arg-type]
            token="t",
            auth=_auth("dm"),
            name="world_update_entry",
            arguments=_update_args(),
        )
    )

    error = res["structuredContent"]["error"]
    assert error["code"] == "invalid_arguments"
    assert error["detail"] == "item.holder_ref.id: Extra inputs are not permitted"


def test_dm_world_write_business_validation_error_carries_detail() -> None:
    exc = CampaignRuntimeValidationError("Item holder character abc does not belong to room xyz")
    res = asyncio.run(
        call_tool(
            _RaisingService(exc),  # type: ignore[arg-type]
            token="t",
            auth=_auth("dm"),
            name="world_update_entry",
            arguments=_update_args(),
        )
    )

    assert res["structuredContent"]["error"]["detail"] == str(exc)


def test_player_validation_error_has_no_detail() -> None:
    exc = CampaignRuntimeValidationError("Search query cannot be empty")
    res = asyncio.run(
        call_tool(
            _RaisingService(exc),  # type: ignore[arg-type]
            token="t",
            auth=_auth("player"),
            name="search_campaign_context",
            arguments={"query": "x"},
        )
    )

    error = res["structuredContent"]["error"]
    assert error["code"] == "invalid_arguments"
    assert "detail" not in error


@pytest.mark.parametrize("tool_name", ["world_create_entry", "world_update_entry"])
def test_world_write_descriptions_document_state_shapes(tool_name: str) -> None:
    (row,) = [item for item in tool_catalog(_auth("dm")) if item["name"] == tool_name]
    english, zh = row["description"].split(" / ", 1)
    for text in (english, zh):
        assert "holder_ref" in text
        assert "target_id" in text
        assert "party[].active_character_id" in text
        assert "monster_template_ref" in text
