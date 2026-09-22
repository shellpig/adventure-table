from __future__ import annotations

import base64
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, insert, select
from sqlalchemy.engine import Engine

from app.api.dependencies import get_database_engine
from app.api.rooms.access import get_room_access_context
from app.api.rooms.dependencies import (
    get_campaign_stage_service,
    get_exploration_stage_service,
    get_room_asset_service,
    get_table_event_service,
)
from app.db import metadata
from app.domain.campaign_runtime import (
    AdventureEntryAssetStageSource,
    CampaignStageBridgeService,
    RoomAssetStageSource,
    RuntimeEntryImageStageSource,
    RuntimeWorldEntryCreate,
    StageSourceInvalidError,
    StageSourceNotFoundError,
)
from app.domain.room_assets.schemas import RoomAssetNotFoundError
from app.domain.room_assets.service import RoomAssetService
from app.domain.rooms.exploration import (
    ExplorationStageService,
    StageImageContent,
    StageImageInvalidError,
    StageRevisionConflictError,
    StageState,
    StageUpdateRequest,
)
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.table_events import (
    TableActorContext,
    TableEventActorUnauthorizedError,
    TableEventNotFoundError,
    TableEventService,
    TableEventSessionNotActiveError,
)
from app.main import app
from app.persistence.adventures.repository import (
    AdventureRepository,
    CampaignAdventureLinkRepository,
    StoredAdventureDefinition,
    StoredAdventureEntry,
    StoredAdventureEntryAsset,
    StoredCampaignAdventureLink,
)
from app.persistence.adventures.tables import (
    adventure_definitions,
    adventure_entries,
    adventure_entry_assets,
    campaign_adventure_links,
)
from app.persistence.campaign_runtime.repository import CampaignRuntimeRepository
from app.persistence.campaign_runtime.tables import campaign_world_entries
from app.persistence.room_assets.repository import RoomAssetRepository
from app.persistence.room_assets.storage import FilesystemAssetStorage
from app.persistence.room_assets.tables import room_assets
from app.persistence.rooms.exploration import (
    ExplorationRepository,
    room_stage_images,
    session_stages,
)
from app.persistence.rooms.table_runtime import TableEventRepository, session_events
from app.persistence.rooms.tables import room_access_sessions, rooms
from tests.p6_active_fixture import (
    ActiveFixture,
    _build_active_fixture,
    setup_authority_failure_actor,
)

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00"
    b"\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)

JPEG_BYTES = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb"
    b"\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c"
    b"\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.' "
    b"\",#\x1c\x1c(7),01444\x1f'9=82<.342\xff\xc0\x00\x0b\x08\x00\x01\x00\x01"
    b"\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b"
    b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9"
)

DOC_BYTES = b"Hello world source text document content"


def _snapshot_state(
    engine: Engine,
    room_id: UUID,
    session_id: UUID,
    notifier_notifications: list[object],
) -> dict[str, object]:
    with engine.connect() as conn:
        stage_row = conn.execute(
            select(session_stages).where(session_stages.c.session_id == session_id)
        ).mappings().first()
        images_count = conn.scalar(
            select(func.count()).select_from(room_stage_images).where(room_stage_images.c.room_id == room_id)
        ) or 0
        events_count = conn.scalar(
            select(func.count()).select_from(session_events).where(
                session_events.c.session_id == session_id,
                session_events.c.kind == "stage.updated",
            )
        ) or 0
    return {
        "stage_revision": stage_row["revision"] if stage_row is not None else None,
        "stage_image_id": stage_row["image_id"] if stage_row is not None else None,
        "stage_text": stage_row["text"] if stage_row is not None else None,
        "images_count": images_count,
        "events_count": events_count,
        "notifications_count": len(notifier_notifications),
    }


@pytest.fixture
def fix() -> ActiveFixture:
    return _build_active_fixture()


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


def _get_adv_id(fix: ActiveFixture) -> UUID:
    with fix.engine.connect() as conn:
        adv_id = conn.scalar(
            select(campaign_adventure_links.c.adventure_id).where(
                campaign_adventure_links.c.campaign_id == fix.campaign_id
            )
        )
        assert adv_id is not None
        return adv_id


def test_stage_bridge_human_ai_parity(fix: ActiveFixture, tmp_path: Path) -> None:
    bridge, asset_service, _ = _make_bridge(fix, tmp_path)
    asset = asset_service.create(
        fix.owner_context,
        room_id=fix.room_id,
        kind="image",
        filename="parity.png",
        mime_type="image/png",
        data=PNG_BYTES,
        visibility="room",
    )

    human_stage = bridge.set_stage_image(
        fix.human_dm_actor,
        RoomAssetStageSource(asset_id=asset.id),
        expected_revision=0,
        idempotency_key="parity-human",
    )

    ai_stage = bridge.set_stage_image(
        fix.ai_dm_actor,
        RoomAssetStageSource(asset_id=asset.id),
        expected_revision=0,
        idempotency_key="parity-ai",
    )

    assert human_stage.revision == 1
    assert ai_stage.revision == 1
    assert human_stage.text is None
    assert ai_stage.text is None
    assert human_stage.image_media_type == "image/png"
    assert ai_stage.image_media_type == "image/png"
    assert human_stage.image_filename == "parity.png"
    assert ai_stage.image_filename == "parity.png"
    assert human_stage.image_id is not None
    assert ai_stage.image_id is not None

    with fix.engine.connect() as conn:
        human_ev = conn.execute(
            select(session_events).where(
                session_events.c.session_id == fix.session_id,
                session_events.c.kind == "stage.updated",
            )
        ).mappings().one()
        ai_ev = conn.execute(
            select(session_events).where(
                session_events.c.session_id == fix.ai_session_id,
                session_events.c.kind == "stage.updated",
            )
        ).mappings().one()

        assert human_ev["payload"]["stage_revision"] == 1
        assert ai_ev["payload"]["stage_revision"] == 1
        assert human_ev["payload"]["image_id"] == str(human_stage.image_id)
        assert ai_ev["payload"]["image_id"] == str(ai_stage.image_id)
        assert human_ev["payload"]["image_media_type"] == "image/png"
        assert ai_ev["payload"]["image_media_type"] == "image/png"


def test_stage_bridge_bytes_copied(fix: ActiveFixture, tmp_path: Path) -> None:
    bridge, asset_service, _ = _make_bridge(fix, tmp_path)
    asset = asset_service.create(
        fix.owner_context,
        room_id=fix.room_id,
        kind="image",
        filename="copied.png",
        mime_type="image/png",
        data=PNG_BYTES,
        visibility="room",
    )

    stage = bridge.set_stage_image(
        fix.human_dm_actor,
        RoomAssetStageSource(asset_id=asset.id),
        expected_revision=0,
        idempotency_key="k-copied",
    )

    assert stage.image_id is not None
    assert stage.image_id != asset.id

    with fix.engine.connect() as conn:
        stage_img = conn.execute(
            select(room_stage_images).where(room_stage_images.c.id == stage.image_id)
        ).mappings().one()
        assert bytes(stage_img["data"]) == PNG_BYTES
        assert stage_img["room_id"] == fix.room_id
        assert stage_img["media_type"] == "image/png"

        stage_row = conn.execute(
            select(session_stages).where(session_stages.c.session_id == fix.session_id)
        ).mappings().one()
        assert stage_row["image_id"] == stage.image_id
        assert stage_row["revision"] == 1


def test_stage_bridge_delete_source_asset_independence(fix: ActiveFixture, tmp_path: Path) -> None:
    bridge, asset_service, stage_service = _make_bridge(fix, tmp_path)
    asset = asset_service.create(
        fix.owner_context,
        room_id=fix.room_id,
        kind="image",
        filename="indep.png",
        mime_type="image/png",
        data=PNG_BYTES,
        visibility="room",
    )

    stage = bridge.set_stage_image(
        fix.human_dm_actor,
        RoomAssetStageSource(asset_id=asset.id),
        expected_revision=0,
        idempotency_key="k-indep",
    )
    assert stage.image_id is not None

    asset_service.delete(fix.owner_context, fix.room_id, asset.id)

    with pytest.raises(RoomAssetNotFoundError):
        asset_service.get(fix.owner_context, fix.room_id, asset.id)

    current_stage = stage_service.get_stage(fix.human_dm_actor)
    assert current_stage.image_id == stage.image_id

    content = stage_service.get_image(fix.human_dm_actor, stage.image_id)
    assert content.data == PNG_BYTES
    assert content.media_type == "image/png"


def test_stage_bridge_room_asset_validation(fix: ActiveFixture, tmp_path: Path) -> None:
    bridge, asset_service, _ = _make_bridge(fix, tmp_path)

    # 1. Missing asset -> StageSourceNotFoundError, zero side effects
    snap_before = _snapshot_state(fix.engine, fix.room_id, fix.session_id, fix.notifier.notifications)
    with pytest.raises(StageSourceNotFoundError):
        bridge.set_stage_image(
            fix.human_dm_actor,
            RoomAssetStageSource(asset_id=uuid4()),
            expected_revision=0,
            idempotency_key="k-missing-room-asset",
        )
    snap_after = _snapshot_state(fix.engine, fix.room_id, fix.session_id, fix.notifier.notifications)
    assert snap_after == snap_before

    # 2. Real wrong-room asset -> StageSourceNotFoundError, zero side effects
    other_room_id = uuid4()
    other_access_id = uuid4()
    now = datetime.now(timezone.utc)
    with fix.engine.begin() as conn:
        conn.execute(
            insert(rooms).values(
                id=other_room_id,
                code="OTHER-ROOM",
                name="Other Room",
                password_salt=b"salt",
                password_hash=b"pw",
                owner_key_hash=b"owner",
                dm_key_hash=b"dm",
                created_at=now,
                updated_at=now,
            )
        )
        conn.execute(
            insert(room_access_sessions).values(
                id=other_access_id,
                room_id=other_room_id,
                authority="owner",
                token_hash=b"other_token_hash_1234567890",
                display_name="Other Owner",
                created_at=now,
                last_seen_at=now,
            )
        )
    other_owner_ctx = RoomAccessContext(
        room_id=other_room_id,
        access_session_id=other_access_id,
        authority=RoomAccessAuthority.OWNER,
        display_name="Other Owner",
    )
    other_asset = asset_service.create(
        other_owner_ctx,
        room_id=other_room_id,
        kind="image",
        filename="other.png",
        mime_type="image/png",
        data=PNG_BYTES,
        visibility="room",
    )

    snap_before = _snapshot_state(fix.engine, fix.room_id, fix.session_id, fix.notifier.notifications)
    with pytest.raises(StageSourceNotFoundError):
        bridge.set_stage_image(
            fix.human_dm_actor,
            RoomAssetStageSource(asset_id=other_asset.id),
            expected_revision=0,
            idempotency_key="k-wrong-room",
        )
    snap_after = _snapshot_state(fix.engine, fix.room_id, fix.session_id, fix.notifier.notifications)
    assert snap_after == snap_before

    # 3. Non-image asset (source_document) -> StageSourceInvalidError, zero side effects
    doc_asset = asset_service.create(
        fix.owner_context,
        room_id=fix.room_id,
        kind="source_document",
        filename="doc.txt",
        mime_type="text/plain",
        data=DOC_BYTES,
        visibility="dm_only",
    )
    snap_before = _snapshot_state(fix.engine, fix.room_id, fix.session_id, fix.notifier.notifications)
    with pytest.raises(StageSourceInvalidError):
        bridge.set_stage_image(
            fix.human_dm_actor,
            RoomAssetStageSource(asset_id=doc_asset.id),
            expected_revision=0,
            idempotency_key="k-doc-asset",
        )
    snap_after = _snapshot_state(fix.engine, fix.room_id, fix.session_id, fix.notifier.notifications)
    assert snap_after == snap_before


def test_stage_bridge_adventure_entry_asset_validation(fix: ActiveFixture, tmp_path: Path) -> None:
    bridge, asset_service, _ = _make_bridge(fix, tmp_path)
    adv_id = _get_adv_id(fix)

    asset = asset_service.create(
        fix.owner_context,
        room_id=fix.room_id,
        kind="image",
        filename="adv.png",
        mime_type="image/png",
        data=PNG_BYTES,
        visibility="room",
    )

    with fix.engine.begin() as conn:
        conn.execute(
            insert(adventure_entry_assets).values(
                adventure_entry_id=fix.adv_entry_id,
                asset_id=asset.id,
                role="image",
                sort_order=0,
            )
        )

    stage = bridge.set_stage_image(
        fix.human_dm_actor,
        AdventureEntryAssetStageSource(
            adventure_id=adv_id,
            adventure_entry_id=fix.adv_entry_id,
            asset_id=asset.id,
        ),
        expected_revision=0,
        idempotency_key="k-adv-success",
    )
    assert stage.revision == 1
    assert stage.image_id is not None

    # Negative 1: unattached adventure
    unattached_adv_id = uuid4()
    with fix.engine.begin() as conn:
        conn.execute(
            insert(adventure_definitions).values(
                id=unattached_adv_id,
                room_id=fix.room_id,
                name="Unattached",
                ruleset="dnd5e-2014",
                status="finalized",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
    snap_before = _snapshot_state(fix.engine, fix.room_id, fix.session_id, fix.notifier.notifications)
    with pytest.raises(StageSourceNotFoundError):
        bridge.set_stage_image(
            fix.human_dm_actor,
            AdventureEntryAssetStageSource(
                adventure_id=unattached_adv_id,
                adventure_entry_id=fix.adv_entry_id,
                asset_id=asset.id,
            ),
            expected_revision=1,
            idempotency_key="k-unattached",
        )
    snap_after = _snapshot_state(fix.engine, fix.room_id, fix.session_id, fix.notifier.notifications)
    assert snap_after == snap_before

    # Negative 2: wrong adventure entry
    snap_before = _snapshot_state(fix.engine, fix.room_id, fix.session_id, fix.notifier.notifications)
    with pytest.raises(StageSourceNotFoundError):
        bridge.set_stage_image(
            fix.human_dm_actor,
            AdventureEntryAssetStageSource(
                adventure_id=adv_id,
                adventure_entry_id=uuid4(),
                asset_id=asset.id,
            ),
            expected_revision=1,
            idempotency_key="k-wrong-entry",
        )
    snap_after = _snapshot_state(fix.engine, fix.room_id, fix.session_id, fix.notifier.notifications)
    assert snap_after == snap_before

    # Negative 3: unlinked asset
    unlinked_asset = asset_service.create(
        fix.owner_context,
        room_id=fix.room_id,
        kind="image",
        filename="unlinked.png",
        mime_type="image/png",
        data=PNG_BYTES,
        visibility="room",
    )
    snap_before = _snapshot_state(fix.engine, fix.room_id, fix.session_id, fix.notifier.notifications)
    with pytest.raises(StageSourceNotFoundError):
        bridge.set_stage_image(
            fix.human_dm_actor,
            AdventureEntryAssetStageSource(
                adventure_id=adv_id,
                adventure_entry_id=fix.adv_entry_id,
                asset_id=unlinked_asset.id,
            ),
            expected_revision=1,
            idempotency_key="k-unlinked",
        )
    snap_after = _snapshot_state(fix.engine, fix.room_id, fix.session_id, fix.notifier.notifications)
    assert snap_after == snap_before

    # Negative 4: linked image asset with role="source" rejects with StageSourceInvalidError
    source_role_asset = asset_service.create(
        fix.owner_context,
        room_id=fix.room_id,
        kind="image",
        filename="source_role.png",
        mime_type="image/png",
        data=PNG_BYTES,
        visibility="room",
    )
    with fix.engine.begin() as conn:
        conn.execute(
            insert(adventure_entry_assets).values(
                adventure_entry_id=fix.adv_entry_id,
                asset_id=source_role_asset.id,
                role="source",
                sort_order=1,
            )
        )
    snap_before = _snapshot_state(fix.engine, fix.room_id, fix.session_id, fix.notifier.notifications)
    with pytest.raises(StageSourceInvalidError):
        bridge.set_stage_image(
            fix.human_dm_actor,
            AdventureEntryAssetStageSource(
                adventure_id=adv_id,
                adventure_entry_id=fix.adv_entry_id,
                asset_id=source_role_asset.id,
            ),
            expected_revision=1,
            idempotency_key="k-source-role",
        )
    snap_after = _snapshot_state(fix.engine, fix.room_id, fix.session_id, fix.notifier.notifications)
    assert snap_after == snap_before

    # Negative 5: linked image asset with role="attachment" rejects with StageSourceInvalidError
    attach_role_asset = asset_service.create(
        fix.owner_context,
        room_id=fix.room_id,
        kind="image",
        filename="attach_role.png",
        mime_type="image/png",
        data=PNG_BYTES,
        visibility="room",
    )
    with fix.engine.begin() as conn:
        conn.execute(
            insert(adventure_entry_assets).values(
                adventure_entry_id=fix.adv_entry_id,
                asset_id=attach_role_asset.id,
                role="attachment",
                sort_order=2,
            )
        )
    snap_before = _snapshot_state(fix.engine, fix.room_id, fix.session_id, fix.notifier.notifications)
    with pytest.raises(StageSourceInvalidError):
        bridge.set_stage_image(
            fix.human_dm_actor,
            AdventureEntryAssetStageSource(
                adventure_id=adv_id,
                adventure_entry_id=fix.adv_entry_id,
                asset_id=attach_role_asset.id,
            ),
            expected_revision=1,
            idempotency_key="k-attach-role",
        )
    snap_after = _snapshot_state(fix.engine, fix.room_id, fix.session_id, fix.notifier.notifications)
    assert snap_after == snap_before


def test_stage_bridge_runtime_entry_image_validation(fix: ActiveFixture, tmp_path: Path) -> None:
    bridge, asset_service, _ = _make_bridge(fix, tmp_path)
    adv_id = _get_adv_id(fix)

    asset = asset_service.create(
        fix.owner_context,
        room_id=fix.room_id,
        kind="image",
        filename="runtime.png",
        mime_type="image/png",
        data=PNG_BYTES,
        visibility="room",
    )

    with fix.engine.begin() as conn:
        conn.execute(
            insert(adventure_entry_assets).values(
                adventure_entry_id=fix.adv_entry_id,
                asset_id=asset.id,
                role="image",
                sort_order=0,
            )
        )

    # Runtime entry with source_adventure_entry_id
    rt_entry = fix.service.create_active(
        actor=fix.human_dm_actor,
        payload=RuntimeWorldEntryCreate(
            kind="scene",
            title="Runtime Scene",
            source_adventure_entry_id=fix.adv_entry_id,
        ),
        idempotency_key="rt-1",
    )

    stage = bridge.set_stage_image(
        fix.human_dm_actor,
        RuntimeEntryImageStageSource(
            runtime_entry_id=rt_entry.id,
            adventure_id=adv_id,
            asset_id=asset.id,
        ),
        expected_revision=0,
        idempotency_key="k-rt-success",
    )
    assert stage.revision == 1

    # Negative 1: quick-added runtime entry without source_adventure_entry_id
    quick_entry = fix.service.create_active(
        actor=fix.human_dm_actor,
        payload=RuntimeWorldEntryCreate(
            kind="scene",
            title="Quick Scene",
            source_adventure_entry_id=None,
        ),
        idempotency_key="rt-quick",
    )
    snap_before = _snapshot_state(fix.engine, fix.room_id, fix.session_id, fix.notifier.notifications)
    with pytest.raises(StageSourceNotFoundError):
        bridge.set_stage_image(
            fix.human_dm_actor,
            RuntimeEntryImageStageSource(
                runtime_entry_id=quick_entry.id,
                adventure_id=adv_id,
                asset_id=asset.id,
            ),
            expected_revision=1,
            idempotency_key="k-no-src",
        )
    snap_after = _snapshot_state(fix.engine, fix.room_id, fix.session_id, fix.notifier.notifications)
    assert snap_after == snap_before

    # Negative 2: runtime entry from another campaign
    with fix.engine.begin() as conn:
        conn.execute(
            insert(campaign_adventure_links).values(
                campaign_id=fix.ai_campaign_id,
                adventure_id=adv_id,
                sort_order=0,
                attached_at=datetime.now(timezone.utc),
            )
        )
    other_rt_entry = fix.service.create_active(
        actor=fix.ai_dm_actor,
        payload=RuntimeWorldEntryCreate(
            kind="scene",
            title="AI Campaign Scene",
            source_adventure_entry_id=fix.adv_entry_id,
        ),
        idempotency_key="rt-other",
    )
    snap_before = _snapshot_state(fix.engine, fix.room_id, fix.session_id, fix.notifier.notifications)
    with pytest.raises(StageSourceNotFoundError):
        bridge.set_stage_image(
            fix.human_dm_actor,
            RuntimeEntryImageStageSource(
                runtime_entry_id=other_rt_entry.id,
                adventure_id=adv_id,
                asset_id=asset.id,
            ),
            expected_revision=1,
            idempotency_key="k-wrong-campaign",
        )
    snap_after = _snapshot_state(fix.engine, fix.room_id, fix.session_id, fix.notifier.notifications)
    assert snap_after == snap_before

    # Negative 3: nonexistent runtime entry
    snap_before = _snapshot_state(fix.engine, fix.room_id, fix.session_id, fix.notifier.notifications)
    with pytest.raises(StageSourceNotFoundError):
        bridge.set_stage_image(
            fix.human_dm_actor,
            RuntimeEntryImageStageSource(
                runtime_entry_id=uuid4(),
                adventure_id=adv_id,
                asset_id=asset.id,
            ),
            expected_revision=1,
            idempotency_key="k-missing-rt",
        )
    snap_after = _snapshot_state(fix.engine, fix.room_id, fix.session_id, fix.notifier.notifications)
    assert snap_after == snap_before

    # Negative 4: underlying asset has non-image/map role (attachment) -> StageSourceInvalidError
    rt_attach_asset = asset_service.create(
        fix.owner_context,
        room_id=fix.room_id,
        kind="image",
        filename="rt_attach.png",
        mime_type="image/png",
        data=PNG_BYTES,
        visibility="room",
    )
    with fix.engine.begin() as conn:
        conn.execute(
            insert(adventure_entry_assets).values(
                adventure_entry_id=fix.adv_entry_id,
                asset_id=rt_attach_asset.id,
                role="attachment",
                sort_order=3,
            )
        )
    snap_before = _snapshot_state(fix.engine, fix.room_id, fix.session_id, fix.notifier.notifications)
    with pytest.raises(StageSourceInvalidError):
        bridge.set_stage_image(
            fix.human_dm_actor,
            RuntimeEntryImageStageSource(
                runtime_entry_id=rt_entry.id,
                adventure_id=adv_id,
                asset_id=rt_attach_asset.id,
            ),
            expected_revision=1,
            idempotency_key="k-rt-attach-role",
        )
    snap_after = _snapshot_state(fix.engine, fix.room_id, fix.session_id, fix.notifier.notifications)
    assert snap_after == snap_before


def test_stage_bridge_dm_only_authority_matrix(tmp_path: Path) -> None:
    # 1. Human current DM succeeds
    fix1 = _build_active_fixture()
    bridge1, asset_service1, _ = _make_bridge(fix1, tmp_path / "f1")
    asset_dm1 = asset_service1.create(
        fix1.owner_context,
        room_id=fix1.room_id,
        kind="image",
        filename="dm1.png",
        mime_type="image/png",
        data=PNG_BYTES,
        visibility="dm_only",
    )
    stage1 = bridge1.set_stage_image(
        fix1.human_dm_actor,
        RoomAssetStageSource(asset_id=asset_dm1.id),
        expected_revision=0,
        idempotency_key="k-dm-human",
    )
    assert stage1.revision == 1

    # 2. AI current DM succeeds
    fix2 = _build_active_fixture()
    bridge2, asset_service2, _ = _make_bridge(fix2, tmp_path / "f2")
    asset_dm2 = asset_service2.create(
        fix2.owner_context,
        room_id=fix2.room_id,
        kind="image",
        filename="dm2.png",
        mime_type="image/png",
        data=PNG_BYTES,
        visibility="dm_only",
    )
    stage2 = bridge2.set_stage_image(
        fix2.ai_dm_actor,
        RoomAssetStageSource(asset_id=asset_dm2.id),
        expected_revision=0,
        idempotency_key="k-dm-ai",
    )
    assert stage2.revision == 1

    # 3. Human Player rejects
    fix3 = _build_active_fixture()
    bridge3, asset_service3, _ = _make_bridge(fix3, tmp_path / "f3")
    asset_dm3 = asset_service3.create(
        fix3.owner_context,
        room_id=fix3.room_id,
        kind="image",
        filename="dm3.png",
        mime_type="image/png",
        data=PNG_BYTES,
        visibility="dm_only",
    )
    snap_before = _snapshot_state(fix3.engine, fix3.room_id, fix3.session_id, fix3.notifier.notifications)
    with pytest.raises(TableEventActorUnauthorizedError):
        bridge3.set_stage_image(
            fix3.human_player_1_actor,
            RoomAssetStageSource(asset_id=asset_dm3.id),
            expected_revision=0,
            idempotency_key="k-player-h",
        )
    snap_after = _snapshot_state(fix3.engine, fix3.room_id, fix3.session_id, fix3.notifier.notifications)
    assert snap_after == snap_before

    # 4. AI Player rejects
    fix4 = _build_active_fixture()
    bridge4, asset_service4, _ = _make_bridge(fix4, tmp_path / "f4")
    asset_dm4 = asset_service4.create(
        fix4.owner_context,
        room_id=fix4.room_id,
        kind="image",
        filename="dm4.png",
        mime_type="image/png",
        data=PNG_BYTES,
        visibility="dm_only",
    )
    snap_before = _snapshot_state(fix4.engine, fix4.room_id, fix4.session_id, fix4.notifier.notifications)
    with pytest.raises(TableEventActorUnauthorizedError):
        bridge4.set_stage_image(
            fix4.ai_player_2_actor,
            RoomAssetStageSource(asset_id=asset_dm4.id),
            expected_revision=0,
            idempotency_key="k-player-ai",
        )
    snap_after = _snapshot_state(fix4.engine, fix4.room_id, fix4.session_id, fix4.notifier.notifications)
    assert snap_after == snap_before

    # 5. Inactive Session rejects
    fix5 = _build_active_fixture()
    bridge5, asset_service5, _ = _make_bridge(fix5, tmp_path / "f5")
    asset_dm5 = asset_service5.create(
        fix5.owner_context,
        room_id=fix5.room_id,
        kind="image",
        filename="dm5.png",
        mime_type="image/png",
        data=PNG_BYTES,
        visibility="dm_only",
    )
    inactive_actor = TableActorContext(
        actor_kind=fix5.human_dm_actor.actor_kind,
        room_id=fix5.human_dm_actor.room_id,
        campaign_id=fix5.human_dm_actor.campaign_id,
        session_id=fix5.inactive_session_id,
        seat_id=fix5.human_dm_actor.seat_id,
        controlled_seat_ids=fix5.human_dm_actor.controlled_seat_ids,
        role=fix5.human_dm_actor.role,
        is_current_dm=True,
        access_session_id=fix5.human_dm_actor.access_session_id,
    )
    snap_before = _snapshot_state(fix5.engine, fix5.room_id, fix5.inactive_session_id, fix5.notifier.notifications)
    with pytest.raises(TableEventSessionNotActiveError):
        bridge5.set_stage_image(
            inactive_actor,
            RoomAssetStageSource(asset_id=asset_dm5.id),
            expected_revision=0,
            idempotency_key="k-inactive",
        )
    snap_after = _snapshot_state(fix5.engine, fix5.room_id, fix5.inactive_session_id, fix5.notifier.notifications)
    assert snap_after == snap_before

    # 6. Revoked grant rejects
    fix6 = _build_active_fixture()
    bridge6, asset_service6, _ = _make_bridge(fix6, tmp_path / "f6")
    asset_dm6 = asset_service6.create(
        fix6.owner_context,
        room_id=fix6.room_id,
        kind="image",
        filename="dm6.png",
        mime_type="image/png",
        data=PNG_BYTES,
        visibility="dm_only",
    )
    revoked_actor, _ = setup_authority_failure_actor(fix6, "revoked_ai")
    snap_before = _snapshot_state(fix6.engine, fix6.room_id, fix6.session_id, fix6.notifier.notifications)
    with pytest.raises(TableEventActorUnauthorizedError):
        bridge6.set_stage_image(
            revoked_actor,
            RoomAssetStageSource(asset_id=asset_dm6.id),
            expected_revision=0,
            idempotency_key="k-revoked",
        )
    snap_after = _snapshot_state(fix6.engine, fix6.room_id, fix6.session_id, fix6.notifier.notifications)
    assert snap_after == snap_before

    # 7. Stale epoch rejects
    fix7 = _build_active_fixture()
    bridge7, asset_service7, _ = _make_bridge(fix7, tmp_path / "f7")
    asset_dm7 = asset_service7.create(
        fix7.owner_context,
        room_id=fix7.room_id,
        kind="image",
        filename="dm7.png",
        mime_type="image/png",
        data=PNG_BYTES,
        visibility="dm_only",
    )
    stale_actor, _ = setup_authority_failure_actor(fix7, "controller_epoch")
    snap_before = _snapshot_state(fix7.engine, fix7.room_id, fix7.session_id, fix7.notifier.notifications)
    with pytest.raises(TableEventActorUnauthorizedError):
        bridge7.set_stage_image(
            stale_actor,
            RoomAssetStageSource(asset_id=asset_dm7.id),
            expected_revision=0,
            idempotency_key="k-stale-epoch",
        )
    snap_after = _snapshot_state(fix7.engine, fix7.room_id, fix7.session_id, fix7.notifier.notifications)
    assert snap_after == snap_before


def test_stage_bridge_player_read_projection(fix: ActiveFixture, tmp_path: Path) -> None:
    bridge, asset_service, stage_service = _make_bridge(fix, tmp_path)
    asset_dm = asset_service.create(
        fix.owner_context,
        room_id=fix.room_id,
        kind="image",
        filename="secret_map.png",
        mime_type="image/png",
        data=PNG_BYTES,
        visibility="dm_only",
    )

    stage = bridge.set_stage_image(
        fix.human_dm_actor,
        RoomAssetStageSource(asset_id=asset_dm.id),
        expected_revision=0,
        idempotency_key="k-secret-stage",
    )

    # Player reads StageState
    player_stage = stage_service.get_stage(fix.human_player_1_actor)
    assert player_stage.session_id == fix.session_id
    assert player_stage.revision == 1
    assert player_stage.image_id == stage.image_id
    assert player_stage.image_id != asset_dm.id
    assert player_stage.image_media_type == "image/png"
    assert player_stage.image_filename == "secret_map.png"

    # Confirm no source asset_id or storage_key in model
    dumped = player_stage.model_dump()
    assert "asset_id" not in dumped
    assert "storage_key" not in dumped
    assert "source" not in dumped

    # Player reads image content
    img_content = stage_service.get_image(fix.human_player_1_actor, stage.image_id)
    assert img_content.id == stage.image_id
    assert img_content.media_type == "image/png"
    assert img_content.filename == "secret_map.png"
    assert img_content.data == PNG_BYTES
    content_dump = img_content.model_dump()
    assert "asset_id" not in content_dump
    assert "storage_key" not in content_dump


def test_stage_bridge_preserve_text_and_stale_revision(fix: ActiveFixture, tmp_path: Path) -> None:
    bridge, asset_service, stage_service = _make_bridge(fix, tmp_path)
    asset = asset_service.create(
        fix.owner_context,
        room_id=fix.room_id,
        kind="image",
        filename="text_test.png",
        mime_type="image/png",
        data=PNG_BYTES,
        visibility="room",
    )

    # First set initial text on stage
    initial_stage = stage_service.replace_stage(
        fix.human_dm_actor,
        StageUpdateRequest(expected_revision=0, text="The ancient tavern stands before you."),
    )
    assert initial_stage.revision == 1
    assert initial_stage.text == "The ancient tavern stands before you."
    assert initial_stage.image_id is None

    # Set stage image with expected_revision=1
    stage_with_img = bridge.set_stage_image(
        fix.human_dm_actor,
        RoomAssetStageSource(asset_id=asset.id),
        expected_revision=1,
        idempotency_key="k-preserve-text",
    )
    assert stage_with_img.revision == 2
    assert stage_with_img.text == "The ancient tavern stands before you."
    assert stage_with_img.image_id is not None

    # Now attempt with stale expected_revision=1 (current revision is 2)
    with fix.engine.connect() as conn:
        img_count_before = conn.scalar(select(func.count()).select_from(room_stage_images))
        event_count_before = conn.scalar(select(func.count()).select_from(session_events))

    notifications_before = len(fix.notifier.notifications)

    with pytest.raises(StageRevisionConflictError):
        bridge.set_stage_image(
            fix.human_dm_actor,
            RoomAssetStageSource(asset_id=asset.id),
            expected_revision=1,
            idempotency_key="k-stale-rev",
        )

    with fix.engine.connect() as conn:
        img_count_after = conn.scalar(select(func.count()).select_from(room_stage_images))
        event_count_after = conn.scalar(select(func.count()).select_from(session_events))

    assert img_count_after == img_count_before
    assert event_count_after == event_count_before
    assert len(fix.notifier.notifications) == notifications_before


def test_stage_bridge_idempotency_behavior(fix: ActiveFixture, tmp_path: Path) -> None:
    bridge, asset_service, _ = _make_bridge(fix, tmp_path)
    asset = asset_service.create(
        fix.owner_context,
        room_id=fix.room_id,
        kind="image",
        filename="idem.png",
        mime_type="image/png",
        data=PNG_BYTES,
        visibility="room",
    )

    initial_notifs = len(fix.notifier.notifications)
    stage1 = bridge.set_stage_image(
        fix.human_dm_actor,
        RoomAssetStageSource(asset_id=asset.id),
        expected_revision=0,
        idempotency_key="idem-key-stage",
    )
    assert stage1.revision == 1
    assert stage1.image_id is not None

    with fix.engine.connect() as conn:
        img_count1 = conn.scalar(select(func.count()).select_from(room_stage_images))
        event_count1 = conn.scalar(select(func.count()).select_from(session_events))

    notif_count1 = len(fix.notifier.notifications)
    assert notif_count1 == initial_notifs + 1
    assert fix.notifier.notifications[-1] == fix.session_id

    # Retry with identical key and args
    stage2 = bridge.set_stage_image(
        fix.human_dm_actor,
        RoomAssetStageSource(asset_id=asset.id),
        expected_revision=0,
        idempotency_key="idem-key-stage",
    )
    assert stage2.revision == stage1.revision
    assert stage2.image_id == stage1.image_id
    assert stage2.text == stage1.text

    with fix.engine.connect() as conn:
        img_count2 = conn.scalar(select(func.count()).select_from(room_stage_images))
        event_count2 = conn.scalar(select(func.count()).select_from(session_events))

    assert img_count2 == img_count1
    assert event_count2 == event_count1
    notif_count2 = len(fix.notifier.notifications)
    assert notif_count2 == notif_count1 + 1
    assert fix.notifier.notifications[-1] == fix.session_id

    # Retry with same key but changed source follows canonical P3 Stage behavior (returns existing)
    asset2 = asset_service.create(
        fix.owner_context,
        room_id=fix.room_id,
        kind="image",
        filename="idem2.png",
        mime_type="image/png",
        data=PNG_BYTES,
        visibility="room",
    )
    stage3 = bridge.set_stage_image(
        fix.human_dm_actor,
        RoomAssetStageSource(asset_id=asset2.id),
        expected_revision=0,
        idempotency_key="idem-key-stage",
    )
    assert stage3.image_id == stage1.image_id
    notif_count3 = len(fix.notifier.notifications)
    assert notif_count3 == notif_count2 + 1
    assert fix.notifier.notifications[-1] == fix.session_id


def test_stage_bridge_rest_endpoint_and_error_mapping(fix: ActiveFixture, tmp_path: Path) -> None:
    bridge, asset_service, _ = _make_bridge(fix, tmp_path)
    asset = asset_service.create(
        fix.owner_context,
        room_id=fix.room_id,
        kind="image",
        filename="rest.png",
        mime_type="image/png",
        data=PNG_BYTES,
        visibility="room",
    )

    client = TestClient(app)

    # 1. Success with Human current DM
    app.dependency_overrides[get_database_engine] = lambda: fix.engine
    app.dependency_overrides[get_campaign_stage_service] = lambda: bridge
    app.dependency_overrides[get_table_event_service] = lambda: fix.service.event_service
    app.dependency_overrides[get_room_access_context] = lambda: RoomAccessContext(
        room_id=fix.room_id,
        access_session_id=fix.human_dm_access_id,
        authority=RoomAccessAuthority.DM,
        display_name="Human DM",
    )

    url = f"/api/rooms/{fix.room_id}/campaigns/{fix.campaign_id}/sessions/{fix.session_id}/stage/image-source"
    body = {
        "source": {"kind": "room_asset", "asset_id": str(asset.id)},
        "expected_revision": 0,
        "idempotency_key": "k-rest-success",
    }
    resp = client.put(url, json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["revision"] == 1
    assert data["image_id"] is not None
    assert data["image_id"] != str(asset.id)
    assert data["image_media_type"] == "image/png"
    assert "asset_id" not in data
    assert "storage_key" not in data
    assert "source" not in data
    assert "adventure_id" not in data
    assert "adventure_entry_id" not in data
    assert "runtime_entry_id" not in data

    # 2. Denial with Player access context -> 403 table_actor_unauthorized, zero side effects
    app.dependency_overrides[get_room_access_context] = lambda: RoomAccessContext(
        room_id=fix.room_id,
        access_session_id=fix.human_player_1_actor.access_session_id,
        authority=RoomAccessAuthority.MEMBER,
        display_name="Human Player 1",
    )
    snap_before = _snapshot_state(fix.engine, fix.room_id, fix.session_id, fix.notifier.notifications)
    resp_player = client.put(url, json={
        "source": {"kind": "room_asset", "asset_id": str(asset.id)},
        "expected_revision": 1,
        "idempotency_key": "k-rest-player",
    })
    assert resp_player.status_code == 403, resp_player.text
    assert resp_player.json()["error"]["code"] == "table_actor_unauthorized"
    snap_after = _snapshot_state(fix.engine, fix.room_id, fix.session_id, fix.notifier.notifications)
    assert snap_after == snap_before

    # 3. Nonparticipant access context -> 404 session_not_found, zero side effects
    app.dependency_overrides[get_room_access_context] = lambda: RoomAccessContext(
        room_id=fix.room_id,
        access_session_id=uuid4(),
        authority=RoomAccessAuthority.MEMBER,
        display_name="Stranger",
    )
    snap_before = _snapshot_state(fix.engine, fix.room_id, fix.session_id, fix.notifier.notifications)
    resp_nonpart = client.put(url, json={
        "source": {"kind": "room_asset", "asset_id": str(asset.id)},
        "expected_revision": 1,
        "idempotency_key": "k-rest-nonpart",
    })
    assert resp_nonpart.status_code == 404, resp_nonpart.text
    assert resp_nonpart.json()["error"]["code"] == "session_not_found"
    snap_after = _snapshot_state(fix.engine, fix.room_id, fix.session_id, fix.notifier.notifications)
    assert snap_after == snap_before

    # Back to DM for error tests
    app.dependency_overrides[get_room_access_context] = lambda: RoomAccessContext(
        room_id=fix.room_id,
        access_session_id=fix.human_dm_access_id,
        authority=RoomAccessAuthority.DM,
        display_name="Human DM",
    )

    # 4. Source not found -> 404 stage_source_not_found, zero side effects
    snap_before = _snapshot_state(fix.engine, fix.room_id, fix.session_id, fix.notifier.notifications)
    resp_404 = client.put(url, json={
        "source": {"kind": "room_asset", "asset_id": str(uuid4())},
        "expected_revision": 1,
        "idempotency_key": "k-rest-404",
    })
    assert resp_404.status_code == 404, resp_404.text
    assert resp_404.json()["error"]["code"] == "stage_source_not_found"
    snap_after = _snapshot_state(fix.engine, fix.room_id, fix.session_id, fix.notifier.notifications)
    assert snap_after == snap_before

    # 5. Revision conflict -> 409 stage_revision_conflict, zero side effects
    snap_before = _snapshot_state(fix.engine, fix.room_id, fix.session_id, fix.notifier.notifications)
    resp_409 = client.put(url, json={
        "source": {"kind": "room_asset", "asset_id": str(asset.id)},
        "expected_revision": 99,
        "idempotency_key": "k-rest-409",
    })
    assert resp_409.status_code == 409, resp_409.text
    assert resp_409.json()["error"]["code"] == "stage_revision_conflict"
    snap_after = _snapshot_state(fix.engine, fix.room_id, fix.session_id, fix.notifier.notifications)
    assert snap_after == snap_before

    # 6. Unsupported asset kind (source_document) -> 422 invalid_stage_image, zero side effects
    doc_asset = asset_service.create(
        fix.owner_context,
        room_id=fix.room_id,
        kind="source_document",
        filename="notes.txt",
        mime_type="text/plain",
        data=DOC_BYTES,
        visibility="dm_only",
    )
    snap_before = _snapshot_state(fix.engine, fix.room_id, fix.session_id, fix.notifier.notifications)
    resp_422 = client.put(url, json={
        "source": {"kind": "room_asset", "asset_id": str(doc_asset.id)},
        "expected_revision": 1,
        "idempotency_key": "k-rest-422",
    })
    assert resp_422.status_code == 422, resp_422.text
    assert resp_422.json()["error"]["code"] == "invalid_stage_image"
    snap_after = _snapshot_state(fix.engine, fix.room_id, fix.session_id, fix.notifier.notifications)
    assert snap_after == snap_before

    app.dependency_overrides.clear()
