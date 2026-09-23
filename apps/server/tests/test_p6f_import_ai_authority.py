from __future__ import annotations

from pathlib import Path
from typing import Callable
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import Engine

from app.config import Settings
from app.domain.adventure_imports.errors import (
    AdventureImportForbiddenError,
    AdventureImportNotFoundError,
)
from app.domain.adventure_imports.schemas import (
    DraftEntry,
    DraftQuestion,
    DraftWarning,
    ImportDraft,
)
from app.domain.adventure_imports.service import AdventureImportService
from app.domain.adventures.service import AdventureService
from app.domain.room_assets.service import RoomAssetService
from app.domain.rooms.table_events import TableActorContext, TableEventService
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
    _build_active_fixture,
    setup_authority_failure_actor,
)


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


def _setup_actor_for_case(fix: ActiveFixture, case: str) -> TableActorContext:
    if case == "ai_player_2_actor":
        return fix.ai_player_2_actor
    if case == "human_player_1_actor":
        return fix.human_player_1_actor
    actor, _ = setup_authority_failure_actor(fix, case)
    return actor


IntentCall = Callable[
    [AdventureImportService, TableActorContext, UUID, UUID, UUID, int], object
]

_INTENTS: dict[str, IntentCall] = {
    "create_import": lambda svc, actor, room, imp, asset, rev: svc.create_import(
        actor, room, "Forbidden Import"
    ),
    "add_text_source": lambda svc, actor, room, imp, asset, rev: svc.add_text_source(
        actor, room, imp, source_kind="paste", text="Forbidden text"
    ),
    "add_url_source": lambda svc, actor, room, imp, asset, rev: svc.add_url_source(
        actor, room, imp, url="https://forbidden.example.com", text="Forbidden url text"
    ),
    "add_asset_source": lambda svc, actor, room, imp, asset, rev: svc.add_asset_source(
        actor, room, imp, asset_id=asset
    ),
    "update_draft": lambda svc, actor, room, imp, asset, rev: svc.update_draft(
        actor, room, imp, draft=ImportDraft(), warnings=[], expected_revision=rev
    ),
    "resolve_import_warning": lambda svc, actor, room, imp, asset, rev: svc.resolve_import_warning(
        actor, room, imp, warning_id="w_test", resolution="Forbidden", expected_revision=rev
    ),
    "answer_import_question": lambda svc, actor, room, imp, asset, rev: svc.answer_import_question(
        actor, room, imp, question_id="q_test", answer="Forbidden", expected_revision=rev
    ),
    "finalize_adventure": lambda svc, actor, room, imp, asset, rev: svc.finalize_adventure(
        actor, room, imp, name="Forbidden Adventure", expected_revision=rev
    ),
    "get_draft": lambda svc, actor, room, imp, asset, rev: svc.get_draft(actor, room, imp),
}

WRITE_INTENTS = [intent for intent in _INTENTS if intent != "get_draft"]
FAILURE_ACTOR_CASES = [
    "ai_player_2_actor",
    "human_player_1_actor",
    "inactive_session",
    "revoked_ai",
    "controller_epoch",
    "revoked_human",
]


@pytest.mark.parametrize("actor_attr", ["ai_dm_actor", "human_dm_actor"])
def test_dm_actors_can_perform_all_import_actions(
    actor_attr: str, tmp_path: Path
) -> None:
    fix = _build_active_fixture()
    import_service, asset_service = _make_services(fix, tmp_path)
    actor: TableActorContext = getattr(fix, actor_attr)

    # 1. create_import
    imp = import_service.create_import(actor, fix.room_id, "Test Adventure")
    assert imp.room_id == fix.room_id
    assert imp.name == "Test Adventure"
    assert imp.status == "source"

    # 2. add_text_source (paste)
    text_source = import_service.add_text_source(
        actor,
        fix.room_id,
        imp.id,
        source_kind="paste",
        text="A dark dungeon entrance hidden by vines.",
    )
    assert text_source.source_kind == "paste"

    # 3. add_url_source
    url_source = import_service.add_url_source(
        actor,
        fix.room_id,
        imp.id,
        url="https://example.com/adventure-notes",
        text="External room description text.",
        title="Adventure Notes",
    )
    assert url_source.source_kind == "url"

    # 4. add_asset_source (upload a source_document asset with fix.owner_context first)
    stored_asset = asset_service.create(
        context=fix.owner_context,
        room_id=fix.room_id,
        kind="source_document",
        filename="scout_report.txt",
        mime_type="text/plain",
        data=b"Scout report notes for the entrance.",
        visibility="dm_only",
    )
    asset_source = import_service.add_asset_source(
        actor,
        fix.room_id,
        imp.id,
        asset_id=stored_asset.id,
    )
    assert asset_source.asset_id == stored_asset.id

    # 5. update_draft
    draft_view = import_service.get_draft(actor, fix.room_id, imp.id)
    draft = ImportDraft(
        entries=[
            DraftEntry(
                entry_id="scene_entrance",
                entry_kind="scene",
                title="Dungeon Entrance",
                body="You stand before the dark entrance.",
                payload={"kind": "scene"},
            )
        ],
        questions=[
            DraftQuestion(
                question_id="q_door",
                message="Is the door locked?",
            )
        ],
    )
    warnings = [
        DraftWarning(
            warning_id="w_danger",
            level="warning",
            code="danger_level",
            message="Check monster CR.",
        )
    ]
    draft_view = import_service.update_draft(
        actor,
        fix.room_id,
        imp.id,
        draft=draft,
        warnings=warnings,
        expected_revision=draft_view.revision,
    )
    assert draft_view.revision == 1

    # 6. resolve_import_warning
    draft_view = import_service.resolve_import_warning(
        actor,
        fix.room_id,
        imp.id,
        warning_id="w_danger",
        resolution="CR confirmed by DM",
        expected_revision=draft_view.revision,
    )
    assert draft_view.revision == 2
    assert draft_view.warnings[0].resolved is True

    # 7. answer_import_question
    draft_view = import_service.answer_import_question(
        actor,
        fix.room_id,
        imp.id,
        question_id="q_door",
        answer="The door is unlocked but heavy.",
        expected_revision=draft_view.revision,
    )
    assert draft_view.revision == 3
    assert draft_view.draft.questions[0].answer == "The door is unlocked but heavy."

    # 8. finalize_adventure -> finalized Adventure in the actor's Room
    finalized = import_service.finalize_adventure(
        actor,
        fix.room_id,
        imp.id,
        name="Finalized Dungeon",
        summary="A completed dungeon adventure.",
        expected_revision=draft_view.revision,
    )
    assert finalized.room_id == fix.room_id
    assert finalized.name == "Finalized Dungeon"
    assert finalized.status == "finalized"


@pytest.mark.parametrize("actor_case", FAILURE_ACTOR_CASES)
@pytest.mark.parametrize("intent", WRITE_INTENTS)
def test_unauthorized_actors_rejected_with_zero_side_effects(
    actor_case: str, intent: str, tmp_path: Path
) -> None:
    fix = _build_active_fixture()
    import_service, asset_service = _make_services(fix, tmp_path)

    # Seed baseline import and draft using room owner
    imp = import_service.create_import(fix.owner_context, fix.room_id, "Seed Import")
    asset = asset_service.create(
        context=fix.owner_context,
        room_id=fix.room_id,
        kind="source_document",
        filename="doc.txt",
        mime_type="text/plain",
        data=b"Doc bytes",
        visibility="dm_only",
    )
    draft = ImportDraft(
        entries=[
            DraftEntry(
                entry_id="s1",
                entry_kind="scene",
                title="S1",
                body="B1",
                payload={"kind": "scene"},
            )
        ],
        questions=[DraftQuestion(question_id="q_test", message="Test?")],
    )
    warnings = [
        DraftWarning(
            warning_id="w_test",
            level="warning",
            code="c_test",
            message="m_test",
        )
    ]
    draft_view = import_service.update_draft(
        fix.owner_context,
        fix.room_id,
        imp.id,
        draft=draft,
        warnings=warnings,
        expected_revision=0,
    )
    rev = draft_view.revision

    actor = _setup_actor_for_case(fix, actor_case)

    before_snapshot = _snapshot_tables(fix.engine)
    before_draft = import_service.get_draft(fix.owner_context, fix.room_id, imp.id)

    with pytest.raises(AdventureImportForbiddenError):
        _INTENTS[intent](import_service, actor, fix.room_id, imp.id, asset.id, rev)

    after_snapshot = _snapshot_tables(fix.engine)
    after_draft = import_service.get_draft(fix.owner_context, fix.room_id, imp.id)

    assert after_snapshot == before_snapshot
    assert after_draft.revision == before_draft.revision


@pytest.mark.parametrize("intent", list(_INTENTS))
def test_table_actor_wrong_room_raises_not_found(
    intent: str, tmp_path: Path
) -> None:
    fix = _build_active_fixture()
    import_service, _ = _make_services(fix, tmp_path)

    with pytest.raises(AdventureImportNotFoundError):
        _INTENTS[intent](import_service, fix.ai_dm_actor, uuid4(), uuid4(), uuid4(), 0)
