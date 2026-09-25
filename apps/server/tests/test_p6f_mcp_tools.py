from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import Engine

from app.config import Settings
from app.domain.adventure_imports.ai_tools import (
    AdventureImportAIToolApplicationService,
    AnswerImportQuestionToolInput,
    FinalizeAdventureToolInput,
    GetImportDraftToolInput,
    ImportAdventureSourceToolInput,
    ResolveImportWarningToolInput,
    UpdateImportDraftToolInput,
)
from app.domain.adventure_imports.schemas import (
    DraftEntry,
    DraftWarning,
    ImportDraft,
)
from app.domain.adventure_imports.service import AdventureImportService
from app.domain.adventures.service import AdventureService
from app.domain.room_assets.service import RoomAssetService
from app.domain.rooms.ai_controllers import AIControllerAuthView
from app.domain.rooms.schemas import StrictModel
from app.domain.rooms.table_events import (
    TableActorContext,
    TableEventService,
)
from app.mcp.guide_tool_names import guide_tool_names
from app.mcp.tools import call_tool, tool_catalog, tool_reference_rows
from app.persistence.adventure_imports.repository import AdventureImportRepository
from app.persistence.adventure_imports.tables import (
    adventure_import_drafts,
    adventure_import_sources,
    adventure_imports,
)
from app.persistence.adventures.repository import AdventureRepository
from app.persistence.adventures.tables import (
    adventure_definitions,
    adventure_entries,
)
from app.persistence.room_assets.repository import RoomAssetRepository
from app.persistence.room_assets.storage import FilesystemAssetStorage
from app.persistence.rooms.table_runtime import TableEventRepository
from tests.p6_active_fixture import (
    ActiveFixture,
    context_seeded_fix,
    setup_authority_failure_actor,
)

P6F_TOOLS = (
    "import_adventure_source",
    "get_import_draft",
    "update_import_draft",
    "resolve_import_warning",
    "answer_import_question",
    "finalize_adventure",
)

_INPUT_TYPES: dict[str, type[StrictModel]] = {
    "import_adventure_source": ImportAdventureSourceToolInput,
    "get_import_draft": GetImportDraftToolInput,
    "update_import_draft": UpdateImportDraftToolInput,
    "resolve_import_warning": ResolveImportWarningToolInput,
    "answer_import_question": AnswerImportQuestionToolInput,
    "finalize_adventure": FinalizeAdventureToolInput,
}


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


_SAMPLE_ARGS: dict[str, dict[str, Any]] = {
    "import_adventure_source": {"source": {"source_kind": "paste", "text": "Sample adventure text."}},
    "get_import_draft": {},
    "update_import_draft": {
        "draft": {"schema_version": 1, "entries": [], "questions": []},
        "warnings": [],
        "expected_revision": 1,
    },
    "resolve_import_warning": {"warning_id": "warn_1", "resolution": "Fixed", "expected_revision": 1},
    "answer_import_question": {"question_id": "q_1", "answer": "Answered", "expected_revision": 1},
    "finalize_adventure": {"name": "Finalized Adventure", "summary": "Summary", "expected_revision": 1},
}


def _sample_input(tool_name: str, *, import_id: UUID) -> dict[str, Any]:
    return {"import_id": str(import_id), **_SAMPLE_ARGS[tool_name]}


def _call(service: object, auth: AIControllerAuthView, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    result = asyncio.run(call_tool(service, token="ai-token", auth=auth, name=name, arguments=arguments))  # type: ignore[arg-type]
    return result["structuredContent"]

def _snapshot_tables(engine: Engine) -> dict[str, int]:
    tables = (
        adventure_imports,
        adventure_import_sources,
        adventure_import_drafts,
        adventure_definitions,
        adventure_entries,
    )
    with engine.connect() as conn:
        return {
            table.name: conn.execute(select(func.count()).select_from(table)).scalar_one()
            for table in tables
        }


def _make_services(
    fix: ActiveFixture, tmp_path: Path
) -> tuple[AdventureImportService, RoomAssetService]:
    settings = Settings()
    asset_repo = RoomAssetRepository(fix.engine)
    storage = FilesystemAssetStorage(tmp_path)
    asset_service = RoomAssetService(
        asset_repo,
        storage,
        max_image_bytes=settings.asset_max_image_bytes,
        max_source_document_bytes=settings.asset_max_source_document_bytes,
    )
    adventure_repo = AdventureRepository(fix.engine)
    adventure_service = AdventureService(adventure_repo, asset_repo)
    import_repo = AdventureImportRepository(fix.engine)
    table_event_service = TableEventService(
        TableEventRepository(fix.engine),
        notifier=fix.notifier,
    )
    import_service = AdventureImportService(
        import_repo,
        settings,
        asset_service,
        adventure_service,
        table_event_service,
    )
    return import_service, asset_service


class _RaisingSpy:
    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"Unexpected dispatch to {name}")


class _DispatchSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object, object]] = []

    def __getattr__(self, name: str) -> Any:
        def record(token: str, parsed: object, *, authenticated: object = None) -> dict[str, Any]:
            self.calls.append((name, parsed, authenticated))
            return {"delegated": True}

        return record

class _TestAdventureImportFacade(AdventureImportAIToolApplicationService):
    def __init__(
        self,
        actor: TableActorContext,
        adventure_import_service: AdventureImportService,
    ) -> None:
        self._test_actor = actor
        self.adventure_import_service = adventure_import_service

    def _actor(
        self, token: str, *, authenticated: AIControllerAuthView | None = None
    ) -> TableActorContext:
        return self._test_actor


# ------------------------------------------------------------------------------
# 1. Catalog & guide parity
# ------------------------------------------------------------------------------
def test_mcp_catalog_and_guide_tool_names() -> None:
    dm_tools = {item["name"] for item in tool_catalog(_auth("dm", active=True))}
    player_tools = {item["name"] for item in tool_catalog(_auth("player", active=True))}
    pre_player_tools = {item["name"] for item in tool_catalog(_auth("player", active=False))}

    assert set(P6F_TOOLS) <= dm_tools
    assert not (set(P6F_TOOLS) & player_tools)
    assert not (set(P6F_TOOLS) & pre_player_tools)
    assert guide_tool_names() is not None

    rows = {
        row["name"]: row["description"]
        for row in tool_reference_rows("dm")
        if row["name"] in P6F_TOOLS
    }
    assert len(rows) == len(P6F_TOOLS)
    for name, desc in rows.items():
        assert "When to use:" in desc
        assert "使用時機：" in desc
        assert "Key parameters and legal values:" in desc
        assert "關鍵參數與合法值：" in desc


# ------------------------------------------------------------------------------
# 2. Role and pre-session gates
# ------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("role", "active", "code"),
    [("dm", False, "active_session_required"), ("player", True, "permission_denied")],
)
@pytest.mark.parametrize("tool_name", P6F_TOOLS)
def test_gates_reject_before_dispatch(tool_name: str, role: str, active: bool, code: str) -> None:
    res = _call(_RaisingSpy(), _auth(role, active=active), tool_name, _sample_input(tool_name, import_id=uuid4()))
    assert res["error"]["code"] == code


# ------------------------------------------------------------------------------
# 3. Authority lifecycle with real fixture and zero DB side effects
# ------------------------------------------------------------------------------
@pytest.mark.parametrize("failure_kind", ["revoked_ai", "controller_epoch", "inactive_session"])
@pytest.mark.parametrize("tool_name", P6F_TOOLS)
def test_authority_lifecycle_zero_db_side_effects(
    context_seeded_fix: ActiveFixture,
    tmp_path: Path,
    failure_kind: str,
    tool_name: str,
) -> None:
    fix = context_seeded_fix
    import_service, _ = _make_services(fix, tmp_path)
    created = import_service.create_import(fix.ai_dm_actor, fix.room_id, "Seed Import")

    before = _snapshot_tables(fix.engine)
    actor, _ = setup_authority_failure_actor(fix, failure_kind)
    auth = _auth(actor.role, active=True, room_id=actor.room_id, session_id=actor.session_id)
    res = _call(
        _TestAdventureImportFacade(actor, import_service),
        auth,
        tool_name,
        _sample_input(tool_name, import_id=created.id),
    )

    assert res["error"]["code"] == "permission_denied"
    assert _snapshot_tables(fix.engine) == before


# ------------------------------------------------------------------------------
# 4. Dispatch, schema validation & invalid arguments
# ------------------------------------------------------------------------------
@pytest.mark.parametrize(("tool_name", "expected_type"), sorted(_INPUT_TYPES.items()))
def test_mcp_dispatch_validates_and_delegates(tool_name: str, expected_type: type) -> None:
    auth = _auth("dm", active=True)
    spy = _DispatchSpy()
    res = _call(spy, auth, tool_name, _sample_input(tool_name, import_id=uuid4()))
    assert res["data"]["delegated"] is True
    assert len(spy.calls) == 1
    name, parsed, seen_auth = spy.calls[0]
    assert name == tool_name
    assert seen_auth == auth
    assert isinstance(parsed, expected_type)


_INVALID_ARGS = [
    *(
        (name, {k: v for k, v in _sample_input(name, import_id=uuid4()).items() if k != "expected_revision"})
        for name in ("update_import_draft", "resolve_import_warning", "answer_import_question", "finalize_adventure")
    ),
    ("import_adventure_source", {"source": {"source_kind": "paste", "text": "orphan text"}}),
]


@pytest.mark.parametrize(("tool_name", "args"), _INVALID_ARGS)
def test_invalid_arguments_rejected_before_dispatch(tool_name: str, args: dict[str, Any]) -> None:
    spy = _DispatchSpy()
    res = _call(spy, _auth("dm", active=True), tool_name, args)
    assert res["error"]["code"] == "invalid_arguments"
    assert spy.calls == []


# ------------------------------------------------------------------------------
# 5. Real End-to-End through call_tool with fix.ai_dm_actor
# ------------------------------------------------------------------------------
def test_real_end_to_end_journey(context_seeded_fix: ActiveFixture, tmp_path: Path) -> None:
    fix = context_seeded_fix
    import_service, _ = _make_services(fix, tmp_path)
    facade = _TestAdventureImportFacade(fix.ai_dm_actor, import_service)
    auth = _auth("dm", active=True, room_id=fix.room_id, session_id=fix.ai_session_id)

    def call(tool: str, **arguments: Any) -> dict[str, Any]:
        res = _call(facade, auth, tool, arguments)
        assert res["ok"] is True, res
        return res["data"]

    def current_draft() -> dict[str, Any]:
        return import_service.get_draft(fix.ai_dm_actor, fix.room_id, import_id).model_dump(mode="json")

    created = call(
        "import_adventure_source",
        name="Lost Mine of Phandelver",
        source={"source_kind": "paste", "text": "Chapter 1: Goblin Arrows."},
    )
    import_id = UUID(created["import_id"])
    source_id = created["source"]["id"]
    assert created["source"]["source_kind"] == "paste"
    appended = call(
        "import_adventure_source",
        import_id=str(import_id),
        source={"source_kind": "markdown", "text": "## Room 2: Goblin Cave\nDark and damp."},
    )
    assert appended["import_id"] == str(import_id)
    assert appended["source"]["source_kind"] == "markdown"

    draft = call("get_import_draft", import_id=str(import_id))
    assert draft == current_draft()

    updated = call(
        "update_import_draft",
        import_id=str(import_id),
        draft={
            "schema_version": 1,
            "entries": [
                {
                    "entry_id": "goblin_ambush_scene",
                    "entry_kind": "scene",
                    "payload": {"kind": "scene", "dm_summary": "Goblins ambush the party on the road."},
                    "provenance": "source_document",
                    "source_ref": {"source_id": source_id},
                    "title": "Goblin Ambush",
                    "review_status": "accepted",
                }
            ],
            "questions": [{"question_id": "q_travel_pace", "message": "What is the party travel pace?"}],
        },
        warnings=[
            {"warning_id": "warn_dc_check", "level": "warning", "code": "inferred_dc", "message": "Inferred DC."}
        ],
        expected_revision=draft["revision"],
    )
    assert updated == current_draft()

    resolved = call(
        "resolve_import_warning",
        import_id=str(import_id),
        warning_id="warn_dc_check",
        resolution="DC 15 confirmed by DM",
        expected_revision=updated["revision"],
    )
    assert resolved == current_draft()
    assert resolved["warnings"][0]["resolved"] is True

    answered = call(
        "answer_import_question",
        import_id=str(import_id),
        question_id="q_travel_pace",
        answer="Normal travel pace.",
        expected_revision=resolved["revision"],
    )
    assert answered == current_draft()
    assert answered["draft"]["questions"][0]["answer"] == "Normal travel pace."

    finalize_args = {"import_id": str(import_id), "name": "Phandelver Baseline", "expected_revision": answered["revision"]}
    finalized = call("finalize_adventure", **finalize_args)
    assert finalized == import_service.adventure_service.get_definition(
        fix.ai_dm_actor, fix.room_id, UUID(finalized["id"])
    ).model_dump(mode="json")
    assert call("finalize_adventure", **finalize_args)["id"] == finalized["id"]


# ------------------------------------------------------------------------------
# 6. Specific error mappings
# ------------------------------------------------------------------------------
def _seeded_facade(
    fix: ActiveFixture, tmp_path: Path, draft: ImportDraft, warnings: list[DraftWarning]
) -> tuple[_TestAdventureImportFacade, AIControllerAuthView, UUID]:
    import_service, _ = _make_services(fix, tmp_path)
    created = import_service.create_import(fix.ai_dm_actor, fix.room_id, "Error Mapping Import")
    import_service.update_draft(
        fix.ai_dm_actor, fix.room_id, created.id, draft=draft, warnings=warnings, expected_revision=0
    )
    auth = _auth("dm", active=True, room_id=fix.room_id, session_id=fix.ai_session_id)
    return _TestAdventureImportFacade(fix.ai_dm_actor, import_service), auth, created.id


def test_error_mapping_stale_expected_revision(context_seeded_fix: ActiveFixture, tmp_path: Path) -> None:
    facade, auth, import_id = _seeded_facade(context_seeded_fix, tmp_path, ImportDraft(), [])
    res = _call(facade, auth, "update_import_draft", {
        "import_id": str(import_id),
        "draft": {"schema_version": 1, "entries": [], "questions": []},
        "expected_revision": 999,
    })
    assert res["error"]["code"] == "adventure_import_revision_conflict"
    assert "expected revision 999" in res["error"]["detail"]


def test_error_mapping_unresolved_blocking_warning(context_seeded_fix: ActiveFixture, tmp_path: Path) -> None:
    blocker = DraftWarning(warning_id="blocker_99", level="blocking", code="missing_map", message="Missing map")
    facade, auth, import_id = _seeded_facade(context_seeded_fix, tmp_path, ImportDraft(), [blocker])
    res = _call(facade, auth, "finalize_adventure", {"import_id": str(import_id), "name": "Blocked", "expected_revision": 1})
    assert res["error"]["code"] == "adventure_import_blocking_warnings"
    assert res["error"]["detail"] == "blocker_99"


def test_error_mapping_draft_entry_missing_asset_id(context_seeded_fix: ActiveFixture, tmp_path: Path) -> None:
    fix = context_seeded_fix
    entry = DraftEntry.model_validate(
        {"entry_id": "bad_asset", "entry_kind": "scene", "payload": {"kind": "scene"}, "asset_ids": [str(uuid4())]}
    )
    facade, auth, import_id = _seeded_facade(fix, tmp_path, ImportDraft(entries=[entry]), [])
    before = _snapshot_tables(fix.engine)
    res = _call(facade, auth, "finalize_adventure", {"import_id": str(import_id), "name": "Missing", "expected_revision": 1})
    assert res["error"]["code"] == "not_found"
    assert _snapshot_tables(fix.engine) == before
