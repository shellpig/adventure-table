from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.domain.campaign_runtime import CampaignContextService, RuntimeWorldEntryCreate
from app.domain.campaign_runtime.ai_tools import (
    AdventureEntryToolInput,
    CampaignContextAIToolApplicationService,
    SceneContextToolInput,
    SearchCampaignContextToolInput,
    WorldEntryToolInput,
)
from app.domain.rooms.ai_controllers import AIControllerAuthView, AIControllerService
from app.domain.rooms.ai_guidance import BRIEFING_MAX_CHARS
from app.domain.rooms.exploration import ExplorationStageService
from app.domain.rooms.sessions import SessionService
from app.domain.rooms.table_events import TableActorContext
from app.mcp.guide_tool_names import guide_tool_names
from app.mcp.tools import call_tool, tool_catalog
from app.persistence.mcp.room_lifecycle import M04BSessionRepository
from app.persistence.rooms.ai_controllers import AIControllerGrantRepository
from app.persistence.rooms.exploration import ExplorationRepository
from app.persistence.rooms.session_live import SessionLiveRepository
from tests.p6_active_fixture import (
    ActiveFixture,
    _scan_str,
    _snapshot,
    context_seeded_fix,
    setup_authority_failure_actor,
)

P6C_TOOLS = (
    "get_campaign_context",
    "get_scene_context",
    "search_campaign_context",
    "get_world_entry",
    "get_adventure_entry",
)


def _auth(
    role: str,
    *,
    active: bool = True,
    room_id: UUID | None = None,
    campaign_id: UUID | None = None,
    session_id: UUID | None = None,
    seat_id: UUID | None = None,
    grant_id: UUID | None = None,
) -> AIControllerAuthView:
    return AIControllerAuthView(
        grant_id=grant_id or uuid4(),
        room_id=room_id or uuid4(),
        campaign_id=campaign_id or uuid4(),
        seat_id=seat_id or uuid4(),
        role=role,
        session_id=(session_id or uuid4()) if active else None,
        generation=1,
        is_current_dm=role == "dm",
    )


def _has_forbidden_keys(obj: object, forbidden: set[str]) -> bool:
    if isinstance(obj, dict):
        return any(k in forbidden or _has_forbidden_keys(v, forbidden) for k, v in obj.items())
    if isinstance(obj, (list, tuple)):
        return any(_has_forbidden_keys(item, forbidden) for item in obj)
    return False


# (1) Catalog & Guide parity
def test_mcp_catalog_and_guide_tool_names() -> None:
    dm_tools = {item["name"] for item in tool_catalog(_auth("dm"))}
    player_tools = {item["name"] for item in tool_catalog(_auth("player"))}
    assert set(P6C_TOOLS) <= dm_tools
    assert set(P6C_TOOLS[:-1]) <= player_tools
    assert "get_adventure_entry" not in player_tools
    assert guide_tool_names() is not None


class _RaisingSpy:
    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"Unexpected dispatch to {name}")


@pytest.mark.parametrize("tool_name", P6C_TOOLS)
def test_pre_session_auth_requires_active_session(tool_name: str) -> None:
    spy = _RaisingSpy()
    auth = _auth("dm", active=False)
    res = asyncio.run(call_tool(spy, token="ai-token", auth=auth, name=tool_name, arguments={}))  # type: ignore[arg-type]
    assert res["isError"] is True
    assert res["structuredContent"]["error"]["code"] == "active_session_required"


class _FacadeUnderTest(CampaignContextAIToolApplicationService):
    """Bypasses token auth: `_actor` returns the fixture actor chosen by the test."""

    def __init__(self, actor: TableActorContext, svc: CampaignContextService) -> None:
        self._test_actor = actor
        self.campaign_context_service = svc

    def _actor(self, token: str, *, authenticated: AIControllerAuthView | None = None) -> TableActorContext:
        return self._test_actor


def _invoke(facade: _FacadeUnderTest, tool_name: str, *, world_entry_id: UUID, adventure_entry_id: UUID) -> dict[str, Any]:
    if tool_name == "get_campaign_context":
        return facade.get_campaign_context("ai-token")
    if tool_name == "get_scene_context":
        return facade.get_scene_context("ai-token", SceneContextToolInput())
    if tool_name == "search_campaign_context":
        return facade.search_campaign_context("ai-token", SearchCampaignContextToolInput(query="scene"))
    if tool_name == "get_world_entry":
        return facade.get_world_entry("ai-token", WorldEntryToolInput(world_entry_id=world_entry_id))
    return facade.get_adventure_entry("ai-token", AdventureEntryToolInput(adventure_entry_id=adventure_entry_id))


# (2) Dispatch
class _DispatchSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object, object]] = []

    def get_campaign_context(self, token: str, *, authenticated: object = None) -> dict[str, Any]:
        self.calls.append(("get_campaign_context", None, authenticated))
        return {"delegated": True}

    def get_scene_context(self, token: str, parsed: object, *, authenticated: object = None) -> dict[str, Any]:
        self.calls.append(("get_scene_context", parsed, authenticated))
        return {"delegated": True}

    def search_campaign_context(self, token: str, parsed: object, *, authenticated: object = None) -> dict[str, Any]:
        self.calls.append(("search_campaign_context", parsed, authenticated))
        return {"delegated": True}

    def get_world_entry(self, token: str, parsed: object, *, authenticated: object = None) -> dict[str, Any]:
        self.calls.append(("get_world_entry", parsed, authenticated))
        return {"delegated": True}

    def get_adventure_entry(self, token: str, parsed: object, *, authenticated: object = None) -> dict[str, Any]:
        self.calls.append(("get_adventure_entry", parsed, authenticated))
        return {"delegated": True}


@pytest.mark.parametrize(
    ("tool_name", "args", "expected_type"),
    [
        ("get_campaign_context", {}, type(None)),
        ("get_scene_context", {}, SceneContextToolInput),
        ("search_campaign_context", {"query": "dungeon"}, SearchCampaignContextToolInput),
        ("get_world_entry", {"world_entry_id": str(uuid4())}, WorldEntryToolInput),
        ("get_adventure_entry", {"adventure_entry_id": str(uuid4())}, AdventureEntryToolInput),
    ],
)
def test_mcp_dispatch_validates_and_delegates(tool_name: str, args: dict[str, Any], expected_type: type) -> None:
    auth = _auth("dm")
    spy = _DispatchSpy()
    res = asyncio.run(call_tool(spy, token="ai-token", auth=auth, name=tool_name, arguments=args))  # type: ignore[arg-type]
    assert res["isError"] is False
    assert res["structuredContent"]["data"]["delegated"] is True
    assert len(spy.calls) == 1
    name, parsed, seen_auth = spy.calls[0]
    assert name == tool_name
    assert seen_auth == auth
    if expected_type is not type(None):
        assert isinstance(parsed, expected_type)


@pytest.mark.parametrize(
    ("role", "tool_name", "args", "expected_code"),
    [
        ("player", "get_adventure_entry", {"adventure_entry_id": str(uuid4())}, "permission_denied"),
        ("dm", "get_scene_context", {"adventure_entry_id": str(uuid4()), "runtime_entry_id": str(uuid4())}, "invalid_arguments"),
        ("dm", "search_campaign_context", {"query": "dungeon", "limit": 51}, "invalid_arguments"),
    ],
)
def test_mcp_dispatch_validation_and_permission_failures(
    role: str, tool_name: str, args: dict[str, Any], expected_code: str
) -> None:
    auth = _auth(role)
    facade = _FacadeUnderTest(None, None)  # type: ignore[arg-type]
    res = asyncio.run(call_tool(facade, token="ai-token", auth=auth, name=tool_name, arguments=args))  # type: ignore[arg-type]
    assert res["isError"] is True
    assert res["structuredContent"]["error"]["code"] == expected_code


@pytest.mark.parametrize(
    ("actor_key", "tool_name"),
    [
        ("ai_dm_actor", "get_campaign_context"),
        ("ai_dm_actor", "get_scene_context"),
        ("ai_dm_actor", "search_campaign_context"),
        ("ai_dm_actor", "get_world_entry"),
        ("ai_dm_actor", "get_adventure_entry"),
        ("ai_player_2_actor", "get_campaign_context"),
        ("ai_player_2_actor", "get_scene_context"),
        ("ai_player_2_actor", "search_campaign_context"),
        ("ai_player_2_actor", "get_world_entry"),
    ],
)
def test_facade_with_real_services(
    context_seeded_fix: ActiveFixture, actor_key: str, tool_name: str
) -> None:
    fix = context_seeded_fix
    actor = getattr(fix, actor_key)
    svc = CampaignContextService(fix.service)
    facade = _FacadeUnderTest(actor, svc)
    # The AI DM campaign has no seeded runtime entries; give it one to read back.
    if actor.is_current_dm:
        fix.service.create_active(
            actor,
            RuntimeWorldEntryCreate(kind="scene", title="AI Scene", body="AI Scene body", visibility="public"),
            idempotency_key="facade-entry",
        )
    world_entry_id = svc.get_campaign_context(actor).world_entries[0].id

    out = _invoke(facade, tool_name, world_entry_id=world_entry_id, adventure_entry_id=fix.adv_entry_id)
    if tool_name == "get_campaign_context":
        exp = svc.get_campaign_context(actor).model_dump(mode="json")
    elif tool_name == "get_scene_context":
        exp = svc.get_scene_context(actor, None).model_dump(mode="json")
    elif tool_name == "search_campaign_context":
        exp = svc.search_campaign_context(actor, query="scene").model_dump(mode="json")
    elif tool_name == "get_world_entry":
        exp = svc.get_world_entry(actor, world_entry_id).model_dump(mode="json")
    else:
        exp = svc.get_adventure_entry(actor, fix.adv_entry_id).model_dump(mode="json")

    assert out == exp
    if actor.role == "player":
        assert not _scan_str(out, str(fix.adv_entry_id))
        assert not _has_forbidden_keys(out, {"attached_adventures", "baseline", "override", "dm_notes"})


# (4) Full get_session_context
class _EmptyListService:
    @staticmethod
    def list_requests(actor: object) -> list[object]:
        return []

    @staticmethod
    def list(actor: object) -> list[object]:
        return []


def test_get_session_context_full_path(context_seeded_fix: ActiveFixture) -> None:
    fix = context_seeded_fix
    engine = fix.engine
    events = fix.service.event_service
    session_service = SessionService(M04BSessionRepository(engine), SessionLiveRepository(engine), events)
    stage_service = ExplorationStageService(ExplorationRepository(engine), events)
    controller_service = AIControllerService(AIControllerGrantRepository(engine), events)
    svc = CampaignContextService(fix.service)
    empty = _EmptyListService()

    # Ensure AI DM campaign has at least one world entry for world_entry_refs
    fix.service.create_active(
        fix.ai_dm_actor,
        RuntimeWorldEntryCreate(
            kind="scene",
            title="AI Tavern",
            body="A peaceful tavern.",
            visibility="public",
        ),
        idempotency_key="ai-dm-full-path-scene",
    )

    facade = object.__new__(CampaignContextAIToolApplicationService)
    facade.campaign_context_service = svc
    facade.ai_controller_service = controller_service
    facade.session_service = session_service
    facade.stage_service = stage_service
    facade.roll_service = empty
    facade.pending_action_service = empty
    facade.event_service = events
    facade._combat_context = lambda actor: {"combat": None}

    # Active AI DM
    dm_auth = _auth(
        "dm",
        active=True,
        room_id=fix.room_id,
        campaign_id=fix.ai_campaign_id,
        session_id=fix.ai_session_id,
        seat_id=fix.ai_dm_seat_id,
        grant_id=fix.ai_dm_grant_id,
    )
    dm_ctx = facade.get_session_context("ai-token", authenticated=dm_auth)
    assert "campaign_context" in dm_ctx
    c_dm = dm_ctx["campaign_context"]
    assert c_dm["current_scene"]["kind"] == "adventure"
    assert c_dm["current_situation"] == "Party rests at the entrance."
    assert c_dm["attached_adventure_count"] == 1
    assert "get_adventure_entry" in c_dm["next_context_tools"]
    assert len(c_dm["world_entry_refs"]) > 0
    assert "body" not in c_dm["current_scene"]
    assert "data_json" not in c_dm["current_scene"]
    assert not _has_forbidden_keys(c_dm["current_scene"], {"body", "data_json", "dm_notes"})
    assert len(dm_ctx["briefing"]) <= BRIEFING_MAX_CHARS

    # Active AI Player
    player_auth = _auth(
        "player",
        active=True,
        room_id=fix.room_id,
        campaign_id=fix.campaign_id,
        session_id=fix.session_id,
        seat_id=fix.player_2_seat_id,
        grant_id=fix.ai_player_2_actor.ai_controller_grant_id,
    )
    p_ctx = facade.get_session_context("ai-token", authenticated=player_auth)
    assert "campaign_context" in p_ctx
    c_p = p_ctx["campaign_context"]
    assert "attached_adventure_count" not in c_p
    assert "get_adventure_entry" not in c_p["next_context_tools"]
    assert not _scan_str(c_p, str(fix.adv_entry_id))
    assert not _scan_str(c_p, "Secret Room")
    assert len(p_ctx["briefing"]) <= BRIEFING_MAX_CHARS

    # Pre-session DM
    pre_auth = _auth(
        "dm",
        active=False,
        room_id=fix.room_id,
        campaign_id=fix.ai_campaign_id,
        seat_id=fix.ai_dm_seat_id,
    )
    pre_ctx = facade.get_session_context("ai-token", authenticated=pre_auth)
    assert "campaign_context" not in pre_ctx


# (5) Authority lifecycle
@pytest.mark.parametrize("failure_kind", ["revoked_ai", "inactive_session"])
@pytest.mark.parametrize("tool_name", P6C_TOOLS)
def test_authority_lifecycle_at_facade_level(
    context_seeded_fix: ActiveFixture, failure_kind: str, tool_name: str
) -> None:
    fix = context_seeded_fix
    actor, expected_exc = setup_authority_failure_actor(fix, failure_kind)
    svc = CampaignContextService(fix.service)
    facade = _FacadeUnderTest(actor, svc)

    before = _snapshot(fix.engine, actor.campaign_id)
    with pytest.raises(expected_exc):
        _invoke(facade, tool_name, world_entry_id=uuid4(), adventure_entry_id=fix.adv_entry_id)
    assert _snapshot(fix.engine, actor.campaign_id) == before
