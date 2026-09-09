from __future__ import annotations

import base64
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, insert, update
from sqlalchemy.pool import StaticPool

from app.db import metadata
from app.domain.rooms.exploration import (
    ExplorationStageService,
    StageImageInvalidError,
    StageImageUpload,
    StageRevisionConflictError,
    StageUpdateRequest,
)
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.table_events import TableEventActorUnauthorizedError, TableEventService
from app.persistence.rooms.exploration import (
    ExplorationRepository,
    StageImageNotFoundPersistenceError,
    room_stage_images,
)
from app.persistence.rooms.table_runtime import TableEventRepository
from app.persistence.rooms.tables import (
    campaign_seats,
    campaigns,
    room_access_sessions,
    rooms,
    session_participants,
    sessions,
)


def _engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata.create_all(engine)
    return engine


def _seed_session(engine):
    now = datetime.now(timezone.utc)
    room_id, campaign_id, session_id = uuid4(), uuid4(), uuid4()
    dm_access, player_access = uuid4(), uuid4()
    dm_seat, player_seat = uuid4(), uuid4()
    with engine.begin() as connection:
        connection.execute(
            insert(rooms).values(
                id=room_id,
                code="P3BSTAGE01",
                name="P3-B Stage",
                password_salt=b"s" * 32,
                password_hash=b"p" * 64,
                owner_key_hash=b"o" * 32,
                dm_key_hash=b"d" * 32,
                active_campaign_id=None,
                created_at=now,
                updated_at=now,
            )
        )
        for access_id, authority, token_byte in (
            (dm_access, "dm", b"d"),
            (player_access, "member", b"p"),
        ):
            connection.execute(
                insert(room_access_sessions).values(
                    id=access_id,
                    room_id=room_id,
                    authority=authority,
                    token_hash=token_byte * 32,
                    display_name=authority,
                    created_at=now,
                    last_seen_at=now,
                    revoked_at=None,
                )
            )
        connection.execute(
            insert(campaigns).values(
                id=campaign_id,
                room_id=room_id,
                name="Campaign",
                ruleset="dnd5e-2014",
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            update(rooms).where(rooms.c.id == room_id).values(active_campaign_id=campaign_id)
        )
        connection.execute(
            insert(campaign_seats),
            [
                {
                    "id": dm_seat,
                    "campaign_id": campaign_id,
                    "role": "dm",
                    "label": "DM",
                    "controller_kind": "human",
                    "controller_access_session_id": dm_access,
                    "selected_character_id": None,
                    "archived_at": None,
                    "created_at": now,
                    "updated_at": now,
                },
                {
                    "id": player_seat,
                    "campaign_id": campaign_id,
                    "role": "player",
                    "label": "Player",
                    "controller_kind": "human",
                    "controller_access_session_id": player_access,
                    "selected_character_id": None,
                    "archived_at": None,
                    "created_at": now,
                    "updated_at": now,
                },
            ],
        )
        connection.execute(
            insert(sessions).values(
                id=session_id,
                campaign_id=campaign_id,
                status="active",
                dm_seat_id=dm_seat,
                dm_controller_kind="human",
                dm_controller_access_session_id=dm_access,
                started_at=now,
                ended_at=None,
                created_at=now,
            )
        )
        connection.execute(
            insert(session_participants),
            [
                {
                    "id": uuid4(),
                    "session_id": session_id,
                    "seat_id": dm_seat,
                    "role_snapshot": "dm",
                    "controller_kind_at_join": "human",
                    "controller_access_session_id_at_join": dm_access,
                    "active_character_id": None,
                    "joined_at": now,
                    "left_at": None,
                },
                {
                    "id": uuid4(),
                    "session_id": session_id,
                    "seat_id": player_seat,
                    "role_snapshot": "player",
                    "controller_kind_at_join": "human",
                    "controller_access_session_id_at_join": player_access,
                    "active_character_id": None,
                    "joined_at": now,
                    "left_at": None,
                },
            ],
        )
    return room_id, campaign_id, session_id, dm_access, player_access


def _actor(
    service: TableEventService,
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    access_id: UUID,
    authority: str,
):
    return service.resolve_human_actor(
        room_id=room_id,
        campaign_id=campaign_id,
        session_id=session_id,
        context=RoomAccessContext(
            room_id=room_id,
            access_session_id=access_id,
            authority=RoomAccessAuthority(authority),
        ),
    )


def _png_upload() -> StageImageUpload:
    raw = b"\x89PNG\r\n\x1a\nP3B"
    return StageImageUpload(
        media_type="image/png",
        filename="stage.png",
        data_base64=base64.b64encode(raw).decode("ascii"),
    )


def test_stage_supports_all_four_modes_and_emits_ordered_public_events() -> None:
    engine = _engine()
    try:
        room_id, campaign_id, session_id, dm_access, player_access = _seed_session(engine)
        event_service = TableEventService(TableEventRepository(engine))
        service = ExplorationStageService(ExplorationRepository(engine), event_service)
        dm = _actor(event_service, room_id, campaign_id, session_id, dm_access, "dm")
        player = _actor(event_service, room_id, campaign_id, session_id, player_access, "member")

        assert service.get_stage(dm).revision == 0

        text_only = service.replace_stage(
            dm,
            StageUpdateRequest(expected_revision=0, text="A dark road"),
        )
        assert text_only.text == "A dark road"
        assert text_only.image_id is None

        combined = service.replace_stage(
            dm,
            StageUpdateRequest(expected_revision=1, text="Ruined gate", image=_png_upload()),
        )
        assert combined.text == "Ruined gate"
        assert combined.image_id is not None
        image_id = combined.image_id
        assert service.get_image(player, image_id).data.startswith(b"\x89PNG")

        image_only = service.replace_stage(
            dm,
            StageUpdateRequest(expected_revision=2, image_id=image_id),
        )
        assert image_only.text is None
        assert image_only.image_id == image_id

        cleared = service.replace_stage(dm, StageUpdateRequest(expected_revision=3))
        assert cleared.text is None
        assert cleared.image_id is None
        assert cleared.revision == 4
        with pytest.raises(StageImageNotFoundPersistenceError):
            service.get_image(dm, image_id)

        page = event_service.list_after(player, after_seq=0, limit=20)
        assert [event.kind for event in page.events] == ["stage.updated"] * 4
        assert [event.seq for event in page.events] == [1, 2, 3, 4]
        assert page.events[1].payload["text"] == "Ruined gate"
        assert page.events[3].payload["image_id"] is None
    finally:
        engine.dispose()


def test_only_current_dm_can_change_stage_and_stale_dm_is_rejected_in_transaction() -> None:
    engine = _engine()
    try:
        room_id, campaign_id, session_id, dm_access, player_access = _seed_session(engine)
        event_service = TableEventService(TableEventRepository(engine))
        service = ExplorationStageService(ExplorationRepository(engine), event_service)
        dm = _actor(event_service, room_id, campaign_id, session_id, dm_access, "dm")
        player = _actor(event_service, room_id, campaign_id, session_id, player_access, "member")

        with pytest.raises(TableEventActorUnauthorizedError):
            service.replace_stage(
                player,
                StageUpdateRequest(expected_revision=0, text="Nope"),
            )

        with engine.begin() as connection:
            connection.execute(
                update(room_access_sessions)
                .where(room_access_sessions.c.id == dm_access)
                .values(revoked_at=datetime.now(timezone.utc))
            )
        with pytest.raises(TableEventActorUnauthorizedError):
            service.replace_stage(
                dm,
                StageUpdateRequest(expected_revision=0, text="Stale"),
            )
    finally:
        engine.dispose()


def test_stage_image_rejects_invalid_content_and_retain_only_accepts_current_image() -> None:
    engine = _engine()
    try:
        room_id, campaign_id, session_id, dm_access, _player_access = _seed_session(engine)
        event_service = TableEventService(TableEventRepository(engine))
        service = ExplorationStageService(ExplorationRepository(engine), event_service)
        dm = _actor(event_service, room_id, campaign_id, session_id, dm_access, "dm")

        invalid = StageImageUpload(
            media_type="image/png",
            filename="fake.png",
            data_base64=base64.b64encode(b"not-a-png").decode("ascii"),
        )
        with pytest.raises(StageImageInvalidError):
            service.replace_stage(
                dm,
                StageUpdateRequest(expected_revision=0, image=invalid),
            )

        unrelated_image_id = uuid4()
        with engine.begin() as connection:
            connection.execute(
                insert(room_stage_images).values(
                    id=unrelated_image_id,
                    room_id=room_id,
                    media_type="image/png",
                    filename="other.png",
                    sha256="0" * 64,
                    data=b"\x89PNG\r\n\x1a\nOTHER",
                )
            )
        with pytest.raises(StageImageNotFoundPersistenceError):
            service.replace_stage(
                dm,
                StageUpdateRequest(expected_revision=0, image_id=unrelated_image_id),
            )
        with pytest.raises(StageImageNotFoundPersistenceError):
            service.get_image(dm, unrelated_image_id)
    finally:
        engine.dispose()


def test_stage_idempotent_replay_returns_original_result_after_later_updates() -> None:
    engine = _engine()
    try:
        room_id, campaign_id, session_id, dm_access, _player_access = _seed_session(engine)
        event_service = TableEventService(TableEventRepository(engine))
        service = ExplorationStageService(ExplorationRepository(engine), event_service)
        dm = _actor(event_service, room_id, campaign_id, session_id, dm_access, "dm")

        original = StageUpdateRequest(
            expected_revision=0,
            text="Stable",
            idempotency_key="same",
        )
        first = service.replace_stage(dm, original)
        later = service.replace_stage(
            dm,
            StageUpdateRequest(
                expected_revision=1,
                text="Later",
                idempotency_key="later",
            ),
        )
        with pytest.raises(StageRevisionConflictError):
            service.replace_stage(
                dm,
                StageUpdateRequest(expected_revision=0, text="Stale tab"),
            )
        replay = service.replace_stage(dm, original)

        assert first.revision == 1
        assert first.text == "Stable"
        assert later.revision == 2
        assert later.text == "Later"
        assert replay.revision == 1
        assert replay.text == "Stable"
        current = service.get_stage(dm)
        assert current.revision == 2
        assert current.text == "Later"
        assert event_service.current_cursor(dm).last_event_seq == 2
    finally:
        engine.dispose()
