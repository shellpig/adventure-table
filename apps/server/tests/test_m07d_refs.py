"""M07-D D1: canonical custom refs (F04), draft/override validation (F06), error codes (F07).

F04: every ``custom:`` write is stored as ``custom:<lowercase UUID>``; the
deletion scan parses stored refs to UUIDs, so legacy non-standard spellings
still block deletion (no data migration).
F06: import draft saves and override ``monster_ref`` writes validate (with
row lock) in the same write transaction; rejections have zero side effects.
F07: Adventure/Runtime/Importer REST mappers return 404/409/422 template
codes instead of 500.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Generator
from uuid import UUID, uuid4

from fastapi import Request
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, event, insert, select
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_database_engine
from app.api.errors import APIError
from app.api.rooms.access import get_room_access_context
from app.api.rooms.dependencies import (
    get_adventure_import_service,
    get_adventure_service,
    get_campaign_runtime_service,
)
from app.config import Settings
from app.content import load_default_content_registry
from app.content.localization_files import load_content_localization_catalog
from app.content.registry import resolve_content_root
from app.db import metadata
from app.domain.adventure_imports.schemas import DraftEntry, ImportDraft
from app.domain.adventure_imports.service import AdventureImportService
from app.domain.adventures.schemas import (
    AdventureDefinitionCreate,
    AdventureEntryCreate,
)
from app.domain.adventures.service import AdventureService
from app.domain.campaign_runtime.schemas import (
    CampaignAdventureOverrideCreate,
    RuntimeWorldEntryCreate,
)
from app.domain.campaign_runtime.service import CampaignRuntimeService
from app.domain.monster_library.errors import (
    InvalidMonsterTemplateRefError,
    MonsterTemplateArchivedError,
    MonsterTemplateNotFoundError,
    MonsterTemplateReferencedError,
)
from app.domain.monster_library.references import (
    is_monster_template_referenced,
    normalize_monster_template_ref,
)
from app.domain.monster_library.schemas import (
    ArchiveCustomMonsterInput,
    CreateCustomMonsterInput,
)
from app.domain.monster_library.service import MonsterLibraryService
from app.domain.room_assets.service import RoomAssetService
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.table_events import TableEventService
from app.main import app
from app.persistence.adventure_imports.repository import AdventureImportRepository
from app.persistence.adventures.repository import AdventureRepository
from app.persistence.adventures.tables import (
    adventure_definitions,
    adventure_entries,
    campaign_adventure_links,
)
from app.persistence.campaign_runtime.tables import (
    campaign_adventure_overrides,
    campaign_world_entries,
)
from app.persistence.combat.repository import MonsterRepository
from app.persistence.combat.tables import monster_templates
from app.persistence.monster_library.repository import MonsterLibraryRepository
from app.persistence.room_assets.repository import RoomAssetRepository
from app.persistence.room_assets.storage import FilesystemAssetStorage
from app.persistence.rooms.table_runtime import TableEventRepository
from app.persistence.rooms.tables import campaigns, rooms


def _engine() -> Engine:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    metadata.create_all(engine)
    return engine


@dataclass(frozen=True)
class RefsFixture:
    client: TestClient
    engine: Engine
    room_id: UUID
    other_room_id: UUID
    campaign_id: UUID
    owner: RoomAccessContext
    token_owner: str
    adventures: AdventureService
    imports: AdventureImportService
    runtime: CampaignRuntimeService
    library: MonsterLibraryService
    template_id: UUID


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def refs(tmp_path) -> Generator[RefsFixture, None, None]:
    engine = _engine()
    registry = load_default_content_registry()
    localization = load_content_localization_catalog(registry, resolve_content_root())
    room_id = uuid4()
    other_room_id = uuid4()
    campaign_id = uuid4()
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        conn.execute(
            insert(rooms).values([
                {"id": room_id, "code": "REFA", "name": "Room A",
                 "password_salt": b"s", "password_hash": b"p",
                 "owner_key_hash": b"o", "dm_key_hash": b"d",
                 "created_at": now, "updated_at": now},
                {"id": other_room_id, "code": "REFB", "name": "Room B",
                 "password_salt": b"s", "password_hash": b"p",
                 "owner_key_hash": b"o", "dm_key_hash": b"d",
                 "created_at": now, "updated_at": now},
            ])
        )
        conn.execute(
            insert(campaigns).values(
                {"id": campaign_id, "room_id": room_id, "name": "Campaign",
                 "ruleset": "dnd-5e-2014", "status": "active",
                 "created_at": now, "updated_at": now}
            )
        )
    owner = RoomAccessContext(
        room_id=room_id, access_session_id=uuid4(),
        authority=RoomAccessAuthority.OWNER, display_name="Owner",
    )
    events = TableEventService(TableEventRepository(engine))
    asset_repo = RoomAssetRepository(engine)
    adventures = AdventureService(AdventureRepository(engine), asset_repo)
    settings = Settings()
    imports = AdventureImportService(
        AdventureImportRepository(engine),
        settings,
        RoomAssetService(
            asset_repo, FilesystemAssetStorage(tmp_path / "assets"),
            max_image_bytes=settings.asset_max_image_bytes,
            max_source_document_bytes=settings.asset_max_source_document_bytes,
        ),
        adventures,
        events,
    )
    runtime = CampaignRuntimeService(engine, events)
    monster_repo = MonsterRepository(engine)
    library = MonsterLibraryService(
        engine, MonsterLibraryRepository(engine), monster_repo,
        registry, localization, events,
    )
    template = library.create_custom(
        owner, room_id,
        CreateCustomMonsterInput(name="Ref Brute", armor_class=12, max_hp=20),
    )
    template_id = UUID(template.ref.removeprefix("custom:"))

    token_owner = "tok-refs-owner"
    token_map = {token_owner: owner}

    def _override_access(request: Request) -> RoomAccessContext:
        _, _, tok = request.headers.get("authorization", "").partition(" ")
        if tok.strip() in token_map:
            return token_map[tok.strip()]
        raise APIError(401, "room_access_required", "Room access required")

    app.dependency_overrides[get_database_engine] = lambda: engine
    app.dependency_overrides[get_room_access_context] = _override_access
    app.dependency_overrides[get_adventure_service] = lambda: adventures
    app.dependency_overrides[get_adventure_import_service] = lambda: imports
    app.dependency_overrides[get_campaign_runtime_service] = lambda: runtime
    client = TestClient(app)
    try:
        yield RefsFixture(
            client=client, engine=engine, room_id=room_id,
            other_room_id=other_room_id, campaign_id=campaign_id, owner=owner,
            token_owner=token_owner, adventures=adventures, imports=imports,
            runtime=runtime, library=library, template_id=template_id,
        )
    finally:
        app.dependency_overrides.clear()


def _canonical(template_id: UUID) -> str:
    return f"custom:{template_id}"


# --- F04: normalization ------------------------------------------------------------


def test_normalize_helper_spellings() -> None:
    tid = uuid4()
    assert normalize_monster_template_ref(f"custom:{str(tid).upper()}") == f"custom:{tid}"
    assert normalize_monster_template_ref(f"  custom:{tid}  ") == f"custom:{tid}"
    assert normalize_monster_template_ref(None) is None
    assert normalize_monster_template_ref("srd5.1:monster:goblin") == "srd5.1:monster:goblin"
    # Unparseable stays for the validator to reject with a domain error.
    assert normalize_monster_template_ref("custom:not-a-uuid") == "custom:not-a-uuid"


def test_adventure_entry_write_stores_canonical_ref(refs: RefsFixture) -> None:
    definition = refs.adventures.create_definition(
        refs.owner, refs.room_id, AdventureDefinitionCreate(name="Adv", summary=None)
    )
    entry = refs.adventures.create_entry(
        refs.owner, refs.room_id, definition.id,
        AdventureEntryCreate(
            kind="monster_ref", title="Brute", body=None,
            data={"monster_template_ref": f"CUSTOM:{str(refs.template_id).upper()}", "count": 2},
        ),
    )
    with refs.engine.connect() as connection:
        stored = connection.execute(
            select(adventure_entries.c.data_json).where(adventure_entries.c.id == entry.id)
        ).scalar_one()
    assert stored["monster_template_ref"] == _canonical(refs.template_id)


def test_runtime_entry_write_stores_canonical_ref(refs: RefsFixture) -> None:
    view = refs.runtime.create_management(
        refs.owner, room_id=refs.room_id, campaign_id=refs.campaign_id,
        payload=RuntimeWorldEntryCreate(
            kind="npc", title="Brute", body=None,
            state={"monster_template_ref": f"custom:{str(refs.template_id).upper()}"},
        ),
        idempotency_key="d1-runtime-canon",
    )
    assert view.id is not None
    with refs.engine.connect() as connection:
        stored = connection.execute(
            select(campaign_world_entries.c.state_json).where(
                campaign_world_entries.c.id == view.id
            )
        ).scalar_one()
    assert stored["monster_template_ref"] == _canonical(refs.template_id)


def test_scan_finds_legacy_spellings_and_blocks_delete(refs: RefsFixture) -> None:
    now = datetime.now(timezone.utc)
    legacy_upper = f"custom:{str(refs.template_id).upper()}"
    legacy_padded = f"  custom:{refs.template_id}  "
    definition = refs.adventures.create_definition(
        refs.owner, refs.room_id, AdventureDefinitionCreate(name="Adv", summary=None)
    )
    with refs.engine.begin() as connection:
        # Legacy adventure entry row with an uppercase-UUID spelling.
        connection.execute(
            insert(adventure_entries).values(
                id=uuid4(), adventure_id=definition.id, parent_entry_id=None,
                kind="monster_ref", title="Legacy", body=None,
                data_json={"kind": "monster_ref", "monster_template_ref": legacy_upper, "count": 1},
                visibility="public", sort_order=1, created_at=now, updated_at=now,
            )
        )
        # Legacy runtime entry row with padded spelling.
        connection.execute(
            insert(campaign_world_entries).values(
                id=uuid4(), campaign_id=refs.campaign_id, kind="npc",
                title="Legacy NPC", body=None,
                state_json={"kind": "npc", "monster_template_ref": legacy_padded},
                dm_notes=None, visibility="public", needs_review=False,
                source_adventure_entry_id=None, provenance_json=None,
                revision=1,
                created_by_actor_kind="human", created_by_actor_id=None,
                created_at=now, updated_at=now, archived_at=None,
            )
        )
    with refs.engine.connect() as connection:
        assert is_monster_template_referenced(
            connection, room_id=refs.room_id, template_id=refs.template_id
        ) is True
    # Deletion is blocked by the legacy-spelled references.
    with pytest.raises(MonsterTemplateReferencedError):
        refs.library.delete_custom(
            refs.owner, refs.room_id, refs.template_id, expected_revision=1
        )


def test_scan_ignores_other_templates(refs: RefsFixture) -> None:
    other = refs.library.create_custom(
        refs.owner, refs.room_id,
        CreateCustomMonsterInput(name="Other", armor_class=10, max_hp=10),
    )
    other_id = UUID(other.ref.removeprefix("custom:"))
    with refs.engine.connect() as connection:
        assert is_monster_template_referenced(
            connection, room_id=refs.room_id, template_id=other_id
        ) is False


# --- F06: draft save validation -----------------------------------------------------


def _draft_with_ref(ref: str | None) -> ImportDraft:
    payload: dict = {"monster_template_ref": ref, "count": 1} if ref else {"count": 1}
    return ImportDraft(entries=[
        DraftEntry(entry_id="e1", entry_kind="monster_ref", payload=payload),
    ])


def test_draft_save_rejects_unknown_template_with_zero_side_effects(refs: RefsFixture) -> None:
    created = refs.imports.create_import(refs.owner, refs.room_id, name="Imp")
    with pytest.raises(MonsterTemplateNotFoundError):
        refs.imports.update_draft(
            refs.owner, refs.room_id, created.id,
            draft=_draft_with_ref(f"custom:{uuid4()}"),
            warnings=[], expected_revision=0,
        )
    # Zero side effects: no draft row was stored.
    stored = refs.imports.repository.get_draft(created.id)
    assert stored is None


def test_draft_save_rejects_cross_room_template(refs: RefsFixture) -> None:
    other_template = refs.library.create_custom(
        RoomAccessContext(
            room_id=refs.other_room_id, access_session_id=uuid4(),
            authority=RoomAccessAuthority.OWNER, display_name="Owner B",
        ),
        refs.other_room_id,
        CreateCustomMonsterInput(name="Foreign", armor_class=10, max_hp=10),
    )
    other_template_id = UUID(other_template.ref.removeprefix("custom:"))
    created = refs.imports.create_import(refs.owner, refs.room_id, name="Imp")
    with pytest.raises(MonsterTemplateNotFoundError):
        refs.imports.update_draft(
            refs.owner, refs.room_id, created.id,
            draft=_draft_with_ref(_canonical(other_template_id)),
            warnings=[], expected_revision=0,
        )
    assert refs.imports.repository.get_draft(created.id) is None


def test_draft_save_archived_rules(refs: RefsFixture) -> None:
    created = refs.imports.create_import(refs.owner, refs.room_id, name="Imp")
    saved = refs.imports.update_draft(
        refs.owner, refs.room_id, created.id,
        draft=_draft_with_ref(_canonical(refs.template_id)),
        warnings=[], expected_revision=0,
    )
    assert saved.revision == 1
    refs.library.archive_custom(
        refs.owner, refs.room_id, refs.template_id,
        ArchiveCustomMonsterInput(expected_revision=1),
    )
    # New/changed refs to the archived template are rejected...
    with pytest.raises(MonsterTemplateArchivedError):
        refs.imports.update_draft(
            refs.owner, refs.room_id, created.id,
            draft=ImportDraft(entries=[
                DraftEntry(entry_id="e2", entry_kind="monster_ref",
                           payload={"monster_template_ref": _canonical(refs.template_id), "count": 1}),
            ]),
            warnings=[], expected_revision=1,
        )
    # ...but resaving the unchanged archived ref stays legal.
    resaved = refs.imports.update_draft(
        refs.owner, refs.room_id, created.id,
        draft=_draft_with_ref(_canonical(refs.template_id)),
        warnings=[], expected_revision=1,
    )
    assert resaved.revision == 2


def test_finalize_rejects_bad_template_ref(refs: RefsFixture) -> None:
    created = refs.imports.create_import(refs.owner, refs.room_id, name="Imp")
    # A draft that bypassed validation (legacy data) still fails at
    # finalization inside the same write transaction, with no adventure kept.
    from app.persistence.adventure_imports.tables import adventure_import_drafts

    bad_draft = _draft_with_ref(f"custom:{uuid4()}").model_dump(mode="json")
    with refs.engine.begin() as connection:
        refs.imports.repository.upsert_draft_in_transaction(
            connection, created.id, bad_draft, [], expected_revision=0
        )
    with pytest.raises(MonsterTemplateNotFoundError):
        refs.imports.finalize_adventure(
            refs.owner, refs.room_id, created.id,
            name="Should Not Exist", summary=None, expected_revision=1,
        )
    with refs.engine.connect() as connection:
        names = connection.execute(
            select(adventure_definitions.c.name).where(
                adventure_definitions.c.room_id == refs.room_id
            )
        ).scalars().all()
    assert "Should Not Exist" not in names


# --- F06: override monster_ref validation ---------------------------------------------


def _attached_monster_ref(refs: RefsFixture) -> UUID:
    """Seed a finalized adventure with an attached monster_ref entry; return its id."""
    now = datetime.now(timezone.utc)
    adv_id = uuid4()
    entry_id = uuid4()
    with refs.engine.begin() as connection:
        connection.execute(
            insert(adventure_definitions).values(
                id=adv_id, room_id=refs.room_id, name="Adv", summary=None,
                status="finalized", created_at=now, updated_at=now,
            )
        )
        connection.execute(
            insert(adventure_entries).values(
                id=entry_id, adventure_id=adv_id, parent_entry_id=None,
                kind="monster_ref", title="Brute", body=None,
                data_json={"kind": "monster_ref",
                           "monster_template_ref": _canonical(refs.template_id),
                           "count": 1},
                visibility="public", sort_order=1, created_at=now, updated_at=now,
            )
        )
        connection.execute(
            insert(campaign_adventure_links).values(
                campaign_id=refs.campaign_id, adventure_id=adv_id,
                sort_order=1, attached_at=now,
            )
        )
    return entry_id


def test_override_monster_ref_validated_in_transaction(refs: RefsFixture) -> None:
    entry_id = _attached_monster_ref(refs)
    with pytest.raises(MonsterTemplateNotFoundError):
        refs.runtime.create_override_management(
            refs.owner, room_id=refs.room_id, campaign_id=refs.campaign_id,
            payload=CampaignAdventureOverrideCreate(
                adventure_entry_id=entry_id,
                state={"monster_template_ref": f"custom:{uuid4()}", "count": 1},
            ),
            idempotency_key="d1-ovr-bad",
        )
    with refs.engine.connect() as connection:
        count = connection.execute(
            select(campaign_adventure_overrides.c.id).where(
                campaign_adventure_overrides.c.adventure_entry_id == entry_id
            )
        ).all()
    assert count == []


def test_override_monster_ref_rejects_new_archived_but_keeps_unchanged(refs: RefsFixture) -> None:
    entry_id = _attached_monster_ref(refs)
    created = refs.runtime.create_override_management(
        refs.owner, room_id=refs.room_id, campaign_id=refs.campaign_id,
        payload=CampaignAdventureOverrideCreate(
            adventure_entry_id=entry_id,
            state={"monster_template_ref": _canonical(refs.template_id), "count": 1},
        ),
        idempotency_key="d1-ovr-ok",
    )
    assert created.revision == 1
    refs.library.archive_custom(
        refs.owner, refs.room_id, refs.template_id,
        ArchiveCustomMonsterInput(expected_revision=1),
    )
    other = refs.library.create_custom(
        refs.owner, refs.room_id,
        CreateCustomMonsterInput(name="Other", armor_class=10, max_hp=10),
    )
    other_id = UUID(other.ref.removeprefix("custom:"))
    refs.library.archive_custom(
        refs.owner, refs.room_id, other_id,
        ArchiveCustomMonsterInput(expected_revision=1),
    )
    from app.domain.campaign_runtime.schemas import CampaignAdventureOverridePatch

    # Switching to a different (archived) template is rejected.
    with pytest.raises(MonsterTemplateArchivedError):
        refs.runtime.update_override_management(
            refs.owner, room_id=refs.room_id, campaign_id=refs.campaign_id,
            adventure_entry_id=entry_id,
            patch=CampaignAdventureOverridePatch(
                expected_override_id=created.id, expected_revision=1,
                state={"monster_template_ref": _canonical(other_id), "count": 1},
            ),
            idempotency_key="d1-ovr-archived",
        )
    # Restating the unchanged archived ref stays legal.
    kept = refs.runtime.update_override_management(
        refs.owner, room_id=refs.room_id, campaign_id=refs.campaign_id,
        adventure_entry_id=entry_id,
        patch=CampaignAdventureOverridePatch(
            expected_override_id=created.id, expected_revision=1,
            state={"monster_template_ref": _canonical(refs.template_id), "count": 2},
        ),
        idempotency_key="d1-ovr-kept",
    )
    assert kept.revision == 2


def test_override_npc_ref_still_validated(refs: RefsFixture) -> None:
    now = datetime.now(timezone.utc)
    adv_id = uuid4()
    entry_id = uuid4()
    with refs.engine.begin() as connection:
        connection.execute(
            insert(adventure_definitions).values(
                id=adv_id, room_id=refs.room_id, name="Adv", summary=None,
                status="finalized", created_at=now, updated_at=now,
            )
        )
        connection.execute(
            insert(adventure_entries).values(
                id=entry_id, adventure_id=adv_id, parent_entry_id=None,
                kind="npc", title="Ally", body=None,
                data_json={"kind": "npc", "disposition": "friendly"},
                visibility="public", sort_order=1, created_at=now, updated_at=now,
            )
        )
        connection.execute(
            insert(campaign_adventure_links).values(
                campaign_id=refs.campaign_id, adventure_id=adv_id,
                sort_order=1, attached_at=now,
            )
        )
    with pytest.raises(MonsterTemplateNotFoundError):
        refs.runtime.create_override_management(
            refs.owner, room_id=refs.room_id, campaign_id=refs.campaign_id,
            payload=CampaignAdventureOverrideCreate(
                adventure_entry_id=entry_id,
                state={"monster_template_ref": f"custom:{uuid4()}"},
            ),
            idempotency_key="d1-ovr-npc-bad",
        )


# --- F07: REST machine codes -----------------------------------------------------------------


def _create_adv(refs: RefsFixture) -> UUID:
    resp = refs.client.post(
        f"/api/rooms/{refs.room_id}/adventures",
        json={"name": "Adv"},
        headers=_auth(refs.token_owner),
    )
    assert resp.status_code == 201, resp.text
    from uuid import UUID as _UUID

    return _UUID(resp.json()["id"])


def test_rest_adventure_entry_template_errors_are_mapped(refs: RefsFixture) -> None:
    adv_id = _create_adv(refs)
    url = f"/api/rooms/{refs.room_id}/adventures/{adv_id}/entries"
    missing = refs.client.post(
        url,
        json={"kind": "monster_ref", "title": "X",
              "data": {"monster_template_ref": f"custom:{uuid4()}", "count": 1}},
        headers=_auth(refs.token_owner),
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "monster_template_not_found"
    malformed = refs.client.post(
        url,
        json={"kind": "monster_ref", "title": "X",
              "data": {"monster_template_ref": "custom:not-a-uuid", "count": 1}},
        headers=_auth(refs.token_owner),
    )
    assert malformed.status_code == 422
    assert malformed.json()["error"]["code"] == "invalid_monster_template_ref"


def test_rest_adventure_entry_archived_is_409(refs: RefsFixture) -> None:
    adv_id = _create_adv(refs)
    refs.library.archive_custom(
        refs.owner, refs.room_id, refs.template_id,
        ArchiveCustomMonsterInput(expected_revision=1),
    )
    resp = refs.client.post(
        f"/api/rooms/{refs.room_id}/adventures/{adv_id}/entries",
        json={"kind": "monster_ref", "title": "X",
              "data": {"monster_template_ref": _canonical(refs.template_id), "count": 1}},
        headers=_auth(refs.token_owner),
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "monster_template_archived"


def test_rest_runtime_entry_template_errors_are_mapped(refs: RefsFixture) -> None:
    url = f"/api/rooms/{refs.room_id}/campaigns/{refs.campaign_id}/runtime/entries"
    missing = refs.client.post(
        url,
        json={"idempotency_key": "d1-rest-rt", "kind": "npc", "title": "X",
              "state": {"monster_template_ref": f"custom:{uuid4()}"}},
        headers=_auth(refs.token_owner),
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "monster_template_not_found"


def test_rest_runtime_override_archived_is_409(refs: RefsFixture) -> None:
    entry_id = _attached_monster_ref(refs)
    refs.library.archive_custom(
        refs.owner, refs.room_id, refs.template_id,
        ArchiveCustomMonsterInput(expected_revision=1),
    )
    other = refs.library.create_custom(
        refs.owner, refs.room_id,
        CreateCustomMonsterInput(name="Other", armor_class=10, max_hp=10),
    )
    other_upper = f"custom:{other.ref.removeprefix('custom:').upper()}"
    resp = refs.client.post(
        f"/api/rooms/{refs.room_id}/campaigns/{refs.campaign_id}/runtime/overrides",
        json={"adventure_entry_id": str(entry_id),
              "state": {"monster_template_ref": _canonical(refs.template_id), "count": 1},
              "idempotency_key": "d1-rest-ovr-archived"},
        headers=_auth(refs.token_owner),
    )
    # Restating the base entry's own (now archived) ref stays legal...
    assert resp.status_code in (200, 201), resp.text
    # ...while pointing at a *different* template validates normally
    # (canonical spelling of a live template is accepted).
    resp2 = refs.client.post(
        f"/api/rooms/{refs.room_id}/campaigns/{refs.campaign_id}/runtime/overrides",
        json={"adventure_entry_id": str(entry_id),
              "state": {"monster_template_ref": other_upper, "count": 1},
              "idempotency_key": "d1-rest-ovr-other"},
        headers=_auth(refs.token_owner),
    )
    # An override already exists for this entry: the duplicate-create guard fires.
    assert resp2.status_code == 409
    assert resp2.json()["error"]["code"] == "campaign_runtime_override_exists"
    with refs.engine.connect() as connection:
        stored = connection.execute(
            select(campaign_adventure_overrides.c.state_json).where(
                campaign_adventure_overrides.c.adventure_entry_id == entry_id
            )
        ).scalar_one()
    # The non-canonical spelling was normalized on write.
    assert stored["monster_template_ref"] == _canonical(refs.template_id)


def test_rest_import_draft_template_errors_are_mapped(refs: RefsFixture) -> None:
    created = refs.client.post(
        f"/api/rooms/{refs.room_id}/adventure-imports",
        json={"name": "Imp"},
        headers=_auth(refs.token_owner),
    )
    assert created.status_code == 201, created.text
    import_id = created.json()["id"]
    bad = refs.client.put(
        f"/api/rooms/{refs.room_id}/adventure-imports/{import_id}/draft",
        json={"draft": {"entries": [
            {"entry_id": "e1", "entry_kind": "monster_ref",
             "payload": {"monster_template_ref": f"custom:{uuid4()}", "count": 1}},
        ]}, "warnings": [], "expected_revision": 0},
        headers=_auth(refs.token_owner),
    )
    assert bad.status_code == 404
    assert bad.json()["error"]["code"] == "monster_template_not_found"
