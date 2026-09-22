from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.domain.campaign_runtime.ai_tools import (
    CampaignContextAIToolApplicationService,
    SetStageImageToolInput,
    WorldArchiveEntryToolInput,
    WorldClearOverrideToolInput,
    WorldCreateEntryToolInput,
    WorldGrantKnowledgeToolInput,
    WorldResolveActionToolInput,
    WorldSetCurrentContextToolInput,
    WorldSetNeedsReviewToolInput,
    WorldSetOverrideToolInput,
    WorldUpdateEntryToolInput,
)
from app.domain.campaign_runtime.errors import (
    CampaignRuntimeAuthorityError,
    CampaignRuntimeNotFoundError,
    CampaignRuntimeRevisionConflictError,
    CampaignRuntimeSessionNotActiveError,
    CampaignRuntimeValidationError,
)
from app.domain.campaign_runtime.events import session_event_idempotency_key
from app.domain.campaign_runtime.schemas import (
    RuntimeWorldEntryCreate,
    RuntimeWorldEntryDmView,
)
from app.domain.campaign_runtime.stage import (
    CampaignStageBridgeService,
    RoomAssetStageSource,
    StageSourceInvalidError,
    StageSourceNotFoundError,
)
from app.domain.campaign_runtime.world import (
    CampaignWorldService,
    CreateWorldEntryChange,
    ResolveWorldActionRequest,
)
from app.domain.room_assets.service import RoomAssetService
from app.domain.rooms.ai_controllers import AIControllerAuthView
from app.domain.rooms.exploration import ExplorationStageService
from app.domain.rooms.schemas import StrictModel
from app.domain.rooms.table_events import (
    TableActorContext,
    TableEventActorUnauthorizedError,
    TableEventNotFoundError,
    TableEventSessionNotActiveError,
)
from app.mcp.guide_tool_names import guide_tool_names
from app.mcp.tools import call_tool, tool_catalog, tool_reference_rows
from app.persistence.adventures.repository import (
    AdventureRepository,
    CampaignAdventureLinkRepository,
)
from app.persistence.campaign_runtime.repository import CampaignRuntimeRepository
from app.persistence.room_assets.repository import RoomAssetRepository
from app.persistence.room_assets.storage import FilesystemAssetStorage
from app.persistence.rooms.exploration import ExplorationRepository
from app.persistence.rooms.table_runtime import session_events
from tests.p6_active_fixture import (
    ActiveFixture,
    _snapshot,
    context_seeded_fix,
    setup_authority_failure_actor,
)

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc`\x00\x00\x00"
    b"\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82"
)

P6D_TOOLS = (
    "world_create_entry",
    "world_update_entry",
    "world_archive_entry",
    "world_set_override",
    "world_clear_override",
    "world_set_current_context",
    "world_grant_knowledge",
    "world_set_needs_review",
    "world_resolve_action",
    "set_stage_image",
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


def _sample_input(
    tool_name: str,
    *,
    entry_id: UUID,
    adv_entry_id: UUID,
    asset_id: UUID,
    idempotency_key: str = "test-key",
) -> dict[str, Any]:
    if tool_name == "world_create_entry":
        return {
            "entry": {"kind": "scene", "title": "Test Scene", "body": "Body", "visibility": "public"},
            "idempotency_key": idempotency_key,
        }
    if tool_name == "world_update_entry":
        return {
            "entry_id": str(entry_id),
            "patch": {"expected_revision": 1, "title": "Updated Scene"},
            "idempotency_key": idempotency_key,
        }
    if tool_name == "world_archive_entry":
        return {
            "entry_id": str(entry_id),
            "expected_revision": 1,
            "idempotency_key": idempotency_key,
        }
    if tool_name == "world_set_override":
        return {
            "intent": {"adventure_entry_id": str(adv_entry_id), "state": {"cleared": True}},
            "idempotency_key": idempotency_key,
        }
    if tool_name == "world_clear_override":
        return {
            "intent": {
                "adventure_entry_id": str(adv_entry_id),
                "expected_override_id": str(uuid4()),
                "expected_revision": 1,
            },
            "idempotency_key": idempotency_key,
        }
    if tool_name == "world_set_current_context":
        return {
            "patch": {"expected_revision": 1, "current_situation": "Exploring the dungeon"},
            "idempotency_key": idempotency_key,
        }
    if tool_name == "world_grant_knowledge":
        return {
            "intent": {
                "entry_id": str(entry_id),
                "expected_revision": 1,
                "character_recipient_ids": [str(uuid4())],
            },
            "idempotency_key": idempotency_key,
        }
    if tool_name == "world_set_needs_review":
        return {
            "target": {
                "target_kind": "entry",
                "entry_id": str(entry_id),
                "expected_revision": 1,
                "needs_review": True,
            },
            "idempotency_key": idempotency_key,
        }
    if tool_name == "world_resolve_action":
        return {
            "request": {
                "change": {
                    "action": "create_entry",
                    "payload": {
                        "kind": "fact",
                        "title": "Secret Fact",
                        "body": "A hidden door was spotted.",
                        "visibility": "dm_only",
                    },
                },
                "narration": "You notice subtle scratches indicating a secret door.",
            },
            "idempotency_key": idempotency_key,
        }
    if tool_name == "set_stage_image":
        return {
            "source": {"kind": "room_asset", "asset_id": str(asset_id)},
            "expected_revision": 0,
            "idempotency_key": idempotency_key,
        }
    raise ValueError(f"Unknown tool: {tool_name}")


class _RaisingSpy:
    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"Unexpected dispatch to {name}")


class _SpyWorldService:
    def __init__(self) -> None:
        self.call_count = 0

    def __getattr__(self, name: str) -> Any:
        def _record(*args: object, **kwargs: object) -> None:
            self.call_count += 1
            raise AssertionError(f"Unexpected call to world service: {name}")

        return _record


class _SpyStageService:
    def __init__(self) -> None:
        self.call_count = 0

    def __getattr__(self, name: str) -> Any:
        def _record(*args: object, **kwargs: object) -> None:
            self.call_count += 1
            raise AssertionError(f"Unexpected call to stage service: {name}")

        return _record


class _DispatchSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object, object]] = []

    def world_create_entry(self, token: str, parsed: object, *, authenticated: object = None) -> dict[str, Any]:
        self.calls.append(("world_create_entry", parsed, authenticated))
        return {"delegated": True}

    def world_update_entry(self, token: str, parsed: object, *, authenticated: object = None) -> dict[str, Any]:
        self.calls.append(("world_update_entry", parsed, authenticated))
        return {"delegated": True}

    def world_archive_entry(self, token: str, parsed: object, *, authenticated: object = None) -> dict[str, Any]:
        self.calls.append(("world_archive_entry", parsed, authenticated))
        return {"delegated": True}

    def world_set_override(self, token: str, parsed: object, *, authenticated: object = None) -> dict[str, Any]:
        self.calls.append(("world_set_override", parsed, authenticated))
        return {"delegated": True}

    def world_clear_override(self, token: str, parsed: object, *, authenticated: object = None) -> dict[str, Any]:
        self.calls.append(("world_clear_override", parsed, authenticated))
        return {"delegated": True}

    def world_set_current_context(self, token: str, parsed: object, *, authenticated: object = None) -> dict[str, Any]:
        self.calls.append(("world_set_current_context", parsed, authenticated))
        return {"delegated": True}

    def world_grant_knowledge(self, token: str, parsed: object, *, authenticated: object = None) -> dict[str, Any]:
        self.calls.append(("world_grant_knowledge", parsed, authenticated))
        return {"delegated": True}

    def world_set_needs_review(self, token: str, parsed: object, *, authenticated: object = None) -> dict[str, Any]:
        self.calls.append(("world_set_needs_review", parsed, authenticated))
        return {"delegated": True}

    def world_resolve_action(self, token: str, parsed: object, *, authenticated: object = None) -> dict[str, Any]:
        self.calls.append(("world_resolve_action", parsed, authenticated))
        return {"delegated": True}

    def set_stage_image(self, token: str, parsed: object, *, authenticated: object = None) -> dict[str, Any]:
        self.calls.append(("set_stage_image", parsed, authenticated))
        return {"delegated": True}


class _FacadeUnderTest(CampaignContextAIToolApplicationService):
    """Bypasses token auth: `_actor` returns the fixture actor chosen by the test."""

    def __init__(
        self,
        actor: TableActorContext,
        world_svc: CampaignWorldService | None = None,
        stage_svc: CampaignStageBridgeService | None = None,
    ) -> None:
        self._test_actor = actor
        self.campaign_world_service = world_svc
        self.campaign_stage_service = stage_svc

    def _actor(self, token: str, *, authenticated: AIControllerAuthView | None = None) -> TableActorContext:
        return self._test_actor


class _RejectingActorFacade(CampaignContextAIToolApplicationService):
    def __init__(self, exc: Exception, world_spy: _SpyWorldService, stage_spy: _SpyStageService) -> None:
        self._exc = exc
        self.campaign_world_service = world_spy  # type: ignore[assignment]
        self.campaign_stage_service = stage_spy  # type: ignore[assignment]

    def _actor(self, token: str, *, authenticated: AIControllerAuthView | None = None) -> TableActorContext:
        raise self._exc


class _ErrorRaisingFacade:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def __getattr__(self, name: str) -> Any:
        def _raise(*args: object, **kwargs: object) -> None:
            raise self._exc

        return _raise


def _make_bridge(
    fix: ActiveFixture, tmp_path: Path
) -> tuple[CampaignStageBridgeService, RoomAssetService, ExplorationStageService]:
    storage = FilesystemAssetStorage(tmp_path)
    asset_repo = RoomAssetRepository(fix.engine)
    asset_service = RoomAssetService(
        asset_repo,
        storage,
        max_image_bytes=10 * 1024 * 1024,
        max_source_document_bytes=10 * 1024 * 1024,
    )
    stage_repo = ExplorationRepository(fix.engine)
    event_service = fix.service.event_service
    stage_service = ExplorationStageService(stage_repo, event_service)
    bridge = CampaignStageBridgeService(
        room_asset_service=asset_service,
        adventure_repository=AdventureRepository(fix.engine),
        campaign_adventure_link_repository=CampaignAdventureLinkRepository(fix.engine),
        campaign_runtime_repository=CampaignRuntimeRepository(fix.engine),
        stage_service=stage_service,
        table_event_service=event_service,
    )
    return bridge, asset_service, stage_service


_INPUT_TYPES: dict[str, type[StrictModel]] = {
    "world_create_entry": WorldCreateEntryToolInput,
    "world_update_entry": WorldUpdateEntryToolInput,
    "world_archive_entry": WorldArchiveEntryToolInput,
    "world_set_override": WorldSetOverrideToolInput,
    "world_clear_override": WorldClearOverrideToolInput,
    "world_set_current_context": WorldSetCurrentContextToolInput,
    "world_grant_knowledge": WorldGrantKnowledgeToolInput,
    "world_set_needs_review": WorldSetNeedsReviewToolInput,
    "world_resolve_action": WorldResolveActionToolInput,
    "set_stage_image": SetStageImageToolInput,
}


def _invoke(
    facade: _FacadeUnderTest,
    tool_name: str,
    *,
    entry_id: UUID,
    adv_entry_id: UUID,
    asset_id: UUID,
    idempotency_key: str = "invoke-key",
) -> dict[str, Any]:
    args = _sample_input(
        tool_name,
        entry_id=entry_id,
        adv_entry_id=adv_entry_id,
        asset_id=asset_id,
        idempotency_key=idempotency_key,
    )
    method: Callable[..., dict[str, Any]] = getattr(facade, tool_name)
    return method("ai-token", _INPUT_TYPES[tool_name].model_validate(args))


# ------------------------------------------------------------------------------
# 1. Catalog / guide parity
# ------------------------------------------------------------------------------
def test_mcp_catalog_and_guide_tool_names() -> None:
    dm_tools = {item["name"] for item in tool_catalog(_auth("dm", active=True))}
    player_tools = {item["name"] for item in tool_catalog(_auth("player", active=True))}
    pre_player_tools = {item["name"] for item in tool_catalog(_auth("player", active=False))}

    assert set(P6D_TOOLS) <= dm_tools
    assert not (set(P6D_TOOLS) & player_tools)
    assert not (set(P6D_TOOLS) & pre_player_tools)
    assert guide_tool_names() is not None

    rows = {
        row["name"]: row["description"]
        for row in tool_reference_rows("dm")
        if row["name"] in P6D_TOOLS
    }
    assert len(rows) == len(P6D_TOOLS)
    for name, desc in rows.items():
        assert "When to use:" in desc
        assert "使用時機：" in desc
        assert "Key parameters and legal values:" in desc
        assert "關鍵參數與合法值：" in desc


# ------------------------------------------------------------------------------
# 2. Authority failures & zero dispatch / zero DB side effects
# ------------------------------------------------------------------------------
@pytest.mark.parametrize("tool_name", P6D_TOOLS)
def test_pre_session_auth_requires_active_session(tool_name: str) -> None:
    spy = _RaisingSpy()
    auth = _auth("dm", active=False)
    args = _sample_input(tool_name, entry_id=uuid4(), adv_entry_id=uuid4(), asset_id=uuid4())
    res = asyncio.run(call_tool(spy, token="ai-token", auth=auth, name=tool_name, arguments=args))  # type: ignore[arg-type]
    assert res["isError"] is True
    assert res["structuredContent"]["error"]["code"] == "active_session_required"


@pytest.mark.parametrize("tool_name", P6D_TOOLS)
def test_player_role_rejected_by_call_tool(tool_name: str) -> None:
    spy = _RaisingSpy()
    auth = _auth("player", active=True)
    args = _sample_input(tool_name, entry_id=uuid4(), adv_entry_id=uuid4(), asset_id=uuid4())
    res = asyncio.run(call_tool(spy, token="ai-token", auth=auth, name=tool_name, arguments=args))  # type: ignore[arg-type]
    assert res["isError"] is True
    assert res["structuredContent"]["error"]["code"] == "permission_denied"


@pytest.mark.parametrize("tool_name", P6D_TOOLS)
def test_actor_rejection_zero_service_dispatch(tool_name: str) -> None:
    world_spy = _SpyWorldService()
    stage_spy = _SpyStageService()
    facade = _RejectingActorFacade(PermissionError("stale or revoked"), world_spy, stage_spy)
    auth = _auth("dm", active=True)
    args = _sample_input(tool_name, entry_id=uuid4(), adv_entry_id=uuid4(), asset_id=uuid4())
    res = asyncio.run(call_tool(facade, token="ai-token", auth=auth, name=tool_name, arguments=args))  # type: ignore[arg-type]
    assert res["isError"] is True
    assert res["structuredContent"]["error"]["code"] == "permission_denied"
    assert world_spy.call_count == 0
    assert stage_spy.call_count == 0


@pytest.mark.parametrize("failure_kind", ["revoked_ai", "controller_epoch", "inactive_session"])
@pytest.mark.parametrize("tool_name", P6D_TOOLS)
def test_authority_lifecycle_zero_db_side_effects(
    context_seeded_fix: ActiveFixture, tmp_path: Path, failure_kind: str, tool_name: str
) -> None:
    fix = context_seeded_fix
    actor, _ = setup_authority_failure_actor(fix, failure_kind)
    world_svc = CampaignWorldService(fix.service)
    bridge, _, _ = _make_bridge(fix, tmp_path)
    facade = _FacadeUnderTest(actor, world_svc, bridge)

    before = _snapshot(fix.engine, actor.campaign_id)
    with pytest.raises((PermissionError, RuntimeError, LookupError)):
        _invoke(
            facade,
            tool_name,
            entry_id=uuid4(),
            adv_entry_id=fix.adv_entry_id,
            asset_id=uuid4(),
        )
    assert _snapshot(fix.engine, actor.campaign_id) == before


# ------------------------------------------------------------------------------
# 3. Dispatch & validation
# ------------------------------------------------------------------------------
@pytest.mark.parametrize(("tool_name", "expected_type"), sorted(_INPUT_TYPES.items()))
def test_mcp_dispatch_validates_and_delegates(tool_name: str, expected_type: type) -> None:
    auth = _auth("dm")
    spy = _DispatchSpy()
    args = _sample_input(tool_name, entry_id=uuid4(), adv_entry_id=uuid4(), asset_id=uuid4())
    res = asyncio.run(call_tool(spy, token="ai-token", auth=auth, name=tool_name, arguments=args))  # type: ignore[arg-type]
    assert res["isError"] is False
    assert res["structuredContent"]["data"]["delegated"] is True
    assert len(spy.calls) == 1
    name, parsed, seen_auth = spy.calls[0]
    assert name == tool_name
    assert seen_auth == auth
    assert isinstance(parsed, expected_type)


@pytest.mark.parametrize("tool_name", P6D_TOOLS)
def test_missing_idempotency_key_maps_to_invalid_arguments(tool_name: str) -> None:
    auth = _auth("dm")
    spy = _DispatchSpy()
    args = _sample_input(tool_name, entry_id=uuid4(), adv_entry_id=uuid4(), asset_id=uuid4())
    del args["idempotency_key"]
    res = asyncio.run(call_tool(spy, token="ai-token", auth=auth, name=tool_name, arguments=args))  # type: ignore[arg-type]
    assert res["isError"] is True
    assert res["structuredContent"]["error"]["code"] == "invalid_arguments"
    assert len(spy.calls) == 0


@pytest.mark.parametrize("tool_name", P6D_TOOLS)
def test_malformed_input_maps_to_invalid_arguments(tool_name: str) -> None:
    auth = _auth("dm")
    spy = _DispatchSpy()
    res = asyncio.run(call_tool(spy, token="ai-token", auth=auth, name=tool_name, arguments={"bad": "payload"}))  # type: ignore[arg-type]
    assert res["isError"] is True
    assert res["structuredContent"]["error"]["code"] == "invalid_arguments"
    assert len(spy.calls) == 0


# ------------------------------------------------------------------------------
# 4. Facade output equals service.model_dump
# ------------------------------------------------------------------------------
def test_facade_output_equals_service_model_dump(
    context_seeded_fix: ActiveFixture, tmp_path: Path
) -> None:
    fix = context_seeded_fix
    world_svc = CampaignWorldService(fix.service)
    bridge, asset_service, _ = _make_bridge(fix, tmp_path)
    facade = _FacadeUnderTest(fix.ai_dm_actor, world_svc, bridge)

    # (A) world_create_entry
    create_input = WorldCreateEntryToolInput(
        entry=RuntimeWorldEntryCreate(
            kind="npc", title="Goblin Scout", body="Sneaky goblin", visibility="dm_only"
        ),
        idempotency_key="facade-real-create",
    )
    facade_create = facade.world_create_entry("ai-token", create_input)
    direct_create = world_svc.create_world_entry(
        fix.ai_dm_actor, create_input.entry, idempotency_key="facade-real-create"
    ).model_dump(mode="json")
    assert facade_create == direct_create

    # (B) world_resolve_action
    action_req = ResolveWorldActionRequest(
        change=CreateWorldEntryChange(
            payload=RuntimeWorldEntryCreate(
                kind="fact",
                title="Hidden Lever",
                body="Found behind the tapestry.",
                visibility="public",
            )
        ),
        narration="You pull the tapestry aside and reveal a lever.",
    )
    action_input = WorldResolveActionToolInput(
        request=action_req, idempotency_key="facade-real-resolve"
    )
    facade_action = facade.world_resolve_action("ai-token", action_input)
    direct_action = world_svc.resolve_world_action(
        fix.ai_dm_actor, action_req, idempotency_key="facade-real-resolve"
    ).model_dump(mode="json")
    assert facade_action == direct_action

    # (C) set_stage_image
    asset = asset_service.create(
        fix.owner_context,
        room_id=fix.room_id,
        kind="image",
        filename="d4_test.png",
        mime_type="image/png",
        data=PNG_BYTES,
        visibility="room",
    )
    stage_input = SetStageImageToolInput(
        source=RoomAssetStageSource(asset_id=asset.id),
        expected_revision=0,
        idempotency_key="facade-real-stage",
    )
    facade_stage = facade.set_stage_image("ai-token", stage_input)
    direct_stage = bridge.set_stage_image(
        fix.ai_dm_actor,
        RoomAssetStageSource(asset_id=asset.id),
        expected_revision=0,
        idempotency_key="facade-real-stage",
    ).model_dump(mode="json")
    assert facade_stage == direct_stage


# ------------------------------------------------------------------------------
# 5. Human / AI parity smoke
# ------------------------------------------------------------------------------
def test_human_ai_parity_smoke(context_seeded_fix: ActiveFixture) -> None:
    fix = context_seeded_fix
    world_svc = CampaignWorldService(fix.service)

    human_payload = RuntimeWorldEntryCreate(
        kind="npc", title="Innkeeper Human", body="A genial host.", visibility="public"
    )
    human_view = world_svc.create_world_entry(
        fix.human_dm_actor, human_payload, idempotency_key="parity-human-entry"
    )

    ai_facade = _FacadeUnderTest(fix.ai_dm_actor, world_svc, None)
    ai_payload = RuntimeWorldEntryCreate(
        kind="npc", title="Innkeeper AI", body="A genial host.", visibility="public"
    )
    ai_result_dict = ai_facade.world_create_entry(
        "ai-token",
        WorldCreateEntryToolInput(entry=ai_payload, idempotency_key="parity-ai-entry"),
    )
    ai_view = RuntimeWorldEntryDmView.model_validate(ai_result_dict)

    # Same view keys / shape
    assert set(human_view.model_dump().keys()) == set(ai_view.model_dump().keys())
    assert human_view.kind == ai_view.kind == "npc"
    assert human_view.visibility == ai_view.visibility == "public"

    # Both produced world.entry_created events in the table events
    with fix.engine.connect() as conn:
        human_events = conn.execute(
            select(session_events.c.kind, session_events.c.idempotency_key).where(
                session_events.c.idempotency_key == session_event_idempotency_key("parity-human-entry")
            )
        ).all()
        ai_events = conn.execute(
            select(session_events.c.kind, session_events.c.idempotency_key).where(
                session_events.c.idempotency_key == session_event_idempotency_key("parity-ai-entry")
            )
        ).all()
    assert len(human_events) == 1
    assert human_events[0][0] == "world.entry.created"
    assert len(ai_events) == 1
    assert ai_events[0][0] == "world.entry.created"


# ------------------------------------------------------------------------------
# 6. Error mapping through call_tool
# ------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("raised_exc", "expected_code"),
    [
        (CampaignRuntimeAuthorityError("unauthorized"), "permission_denied"),
        (TableEventActorUnauthorizedError("unauthorized"), "permission_denied"),
        (CampaignRuntimeNotFoundError("not found"), "not_found"),
        (StageSourceNotFoundError("stage source not found"), "not_found"),
        (TableEventNotFoundError("session not found"), "not_found"),
        (CampaignRuntimeValidationError("invalid"), "invalid_arguments"),
        (StageSourceInvalidError("invalid stage source"), "invalid_arguments"),
        (ValueError("bad value"), "invalid_arguments"),
        (
            CampaignRuntimeRevisionConflictError(uuid4(), uuid4(), 1, 2),
            "table_conflict",
        ),
        (CampaignRuntimeSessionNotActiveError("inactive"), "table_conflict"),
        (TableEventSessionNotActiveError("inactive"), "table_conflict"),
    ],
)
def test_error_mapping_through_call_tool(raised_exc: Exception, expected_code: str) -> None:
    facade = _ErrorRaisingFacade(raised_exc)
    auth = _auth("dm")
    args = _sample_input("world_create_entry", entry_id=uuid4(), adv_entry_id=uuid4(), asset_id=uuid4())
    res = asyncio.run(call_tool(facade, token="ai-token", auth=auth, name="world_create_entry", arguments=args))  # type: ignore[arg-type]
    assert res["isError"] is True
    assert res["structuredContent"]["error"]["code"] == expected_code
