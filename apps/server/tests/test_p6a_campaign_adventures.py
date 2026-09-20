from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import inspect
from pathlib import Path
from typing import Generator
import typing
from uuid import UUID, uuid4

from fastapi import Request
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, event, func, insert, select
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_database_engine
from app.api.errors import APIError
from app.api.rooms.access import get_room_access_context
from app.domain.character.fixture import (
    build_p0_fighter_wizard_fixture,
    build_p0_fighter_wizard_state,
)
from app.content.registry import load_default_content_registry
from app.db import metadata
import app.domain.adventures.attachments
from app.domain.adventures.attachments import CampaignAdventureService
import app.domain.adventures.service
from app.domain.adventures.service import AdventureService
from app.domain.combat.lifecycle import CombatService, StartCombatInput
from app.domain.room_assets.service import RoomAssetService
from app.domain.rooms.campaigns import CampaignCreate, CampaignService, CampaignStatus, RosterAdd
from app.domain.rooms.character_rolls import CharacterRollModifierResolver
from app.domain.rooms.exploration import (
    ExplorationActionService,
    ExplorationInputKind,
    ExplorationInputRequest,
)
from app.domain.rooms.rolls import RequestCheckInput, RollRequestType, RollService
from app.domain.rooms.schemas import (
    CreateRoomRequest,
    EnterRoomRequest,
    RoomAccessAuthority,
    RoomAccessContext,
)
from app.domain.rooms.seats import (
    ControllerKind,
    SeatControllerPatch,
    SeatCreate,
    SeatRole,
    SeatService,
)
from app.domain.rooms.service import RoomService
from app.domain.rooms.sessions import SessionService
from app.domain.rooms.table_character_state import TableCharacterStateService
from app.domain.rooms.table_events import TableActorContext, TableEventService
from app.main import app as fastapi_app
import app.mcp.tools
from app.persistence.adventures.repository import (
    AdventureRepository,
    CampaignAdventureLinkRepository,
    StoredCampaignAdventureLink,
)
from app.persistence.adventures.tables import (
    adventure_definitions,
    adventure_entries,
    campaign_adventure_links,
)
from app.persistence.characters import CharacterRepository
from app.persistence.combat.lifecycle import CombatRepository
from app.persistence.combat.repository import MonsterRepository
from app.domain.combat.roll_compat import CombatAwareRollRepository
from app.persistence.room_assets.repository import RoomAssetRepository
from app.persistence.room_assets.storage import FilesystemAssetStorage
from app.persistence.rooms.campaigns import CampaignRepository
from app.persistence.rooms.exploration_messages import ExplorationMessageRepository
from app.persistence.rooms.exploration_subjects import ExplorationSubjectRepository
from app.persistence.rooms.repository import RoomRepository
from app.persistence.rooms.seats import SeatRepository
from app.persistence.rooms.sessions import SessionRepository
from app.persistence.rooms.table_runtime import TableEventRepository
from app.persistence.rooms.tables import campaigns, rooms
from app.persistence.rooms.workspace import RoomWorkspaceRepository


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
class CampaignAdventureApiFixture:
    client: TestClient
    engine: Engine
    room_a_id: UUID
    room_b_id: UUID
    campaign_a1_id: UUID
    campaign_b1_id: UUID
    token_owner_a: str
    token_dm_a: str
    token_member_a: str
    token_owner_b: str
    tmp_path: Path


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _finalized_adventure(
    client: TestClient,
    token: str,
    room_id: UUID,
    name: str,
) -> UUID:
    resp = client.post(
        f"/api/rooms/{room_id}/adventures",
        json={"name": name},
        headers=_auth(token),
    )
    assert resp.status_code == 201
    adv_id = UUID(resp.json()["id"])
    fin_resp = client.post(
        f"/api/rooms/{room_id}/adventures/{adv_id}/finalize",
        headers=_auth(token),
    )
    assert fin_resp.status_code == 200
    return adv_id


@pytest.fixture
def api_fixture(tmp_path: Path) -> Generator[CampaignAdventureApiFixture, None, None]:
    engine = _engine()
    storage = FilesystemAssetStorage(tmp_path)
    asset_repo = RoomAssetRepository(engine)
    room_asset_service = RoomAssetService(
        asset_repo,
        storage,
        max_image_bytes=20 * 1024 * 1024,
        max_source_document_bytes=20 * 1024 * 1024,
    )
    adv_repo = AdventureRepository(engine)
    adventure_service = AdventureService(adv_repo, asset_repo)
    link_repo = CampaignAdventureLinkRepository(engine)
    campaign_repo = CampaignRepository(engine)
    campaign_adventure_service = CampaignAdventureService(link_repo, adv_repo, campaign_repo)

    room_a_id = uuid4()
    room_b_id = uuid4()
    campaign_a1_id = uuid4()
    campaign_b1_id = uuid4()
    now = datetime.now(timezone.utc)

    with engine.begin() as conn:
        conn.execute(
            insert(rooms).values(
                [
                    {
                        "id": room_a_id,
                        "code": "ROOMA",
                        "name": "Room A",
                        "password_salt": b"salt",
                        "password_hash": b"pw",
                        "owner_key_hash": b"owner",
                        "dm_key_hash": b"dm",
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": room_b_id,
                        "code": "ROOMB",
                        "name": "Room B",
                        "password_salt": b"salt",
                        "password_hash": b"pw",
                        "owner_key_hash": b"owner",
                        "dm_key_hash": b"dm",
                        "created_at": now,
                        "updated_at": now,
                    },
                ]
            )
        )
        conn.execute(
            insert(campaigns).values(
                [
                    {
                        "id": campaign_a1_id,
                        "room_id": room_a_id,
                        "name": "Campaign A1",
                        "ruleset": "dnd5e-2014",
                        "status": "active",
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": campaign_b1_id,
                        "room_id": room_b_id,
                        "name": "Campaign B1",
                        "ruleset": "dnd5e-2014",
                        "status": "active",
                        "created_at": now,
                        "updated_at": now,
                    },
                ]
            )
        )

    token_owner_a = "token-owner-a"
    token_dm_a = "token-dm-a"
    token_member_a = "token-member-a"
    token_owner_b = "token-owner-b"

    token_to_context = {
        token_owner_a: RoomAccessContext(
            room_id=room_a_id,
            access_session_id=uuid4(),
            authority=RoomAccessAuthority.OWNER,
            display_name="Owner A",
        ),
        token_dm_a: RoomAccessContext(
            room_id=room_a_id,
            access_session_id=uuid4(),
            authority=RoomAccessAuthority.DM,
            display_name="DM A",
        ),
        token_member_a: RoomAccessContext(
            room_id=room_a_id,
            access_session_id=uuid4(),
            authority=RoomAccessAuthority.MEMBER,
            display_name="Member A",
        ),
        token_owner_b: RoomAccessContext(
            room_id=room_b_id,
            access_session_id=uuid4(),
            authority=RoomAccessAuthority.OWNER,
            display_name="Owner B",
        ),
    }

    def _override_access_context(request: Request) -> RoomAccessContext:
        auth = request.headers.get("authorization", "")
        _, _, token = auth.partition(" ")
        token_clean = token.strip()
        if token_clean in token_to_context:
            return token_to_context[token_clean]
        raise APIError(401, "room_access_required", "Room access token is required")

    fastapi_app.state.room_asset_service = room_asset_service
    fastapi_app.state.adventure_service = adventure_service
    fastapi_app.state.campaign_adventure_service = campaign_adventure_service
    fastapi_app.dependency_overrides[get_database_engine] = lambda: engine
    fastapi_app.dependency_overrides[get_room_access_context] = _override_access_context

    client = TestClient(fastapi_app)
    try:
        yield CampaignAdventureApiFixture(
            client=client,
            engine=engine,
            room_a_id=room_a_id,
            room_b_id=room_b_id,
            campaign_a1_id=campaign_a1_id,
            campaign_b1_id=campaign_b1_id,
            token_owner_a=token_owner_a,
            token_dm_a=token_dm_a,
            token_member_a=token_member_a,
            token_owner_b=token_owner_b,
            tmp_path=tmp_path,
        )
    finally:
        del fastapi_app.state.room_asset_service
        del fastapi_app.state.adventure_service
        del fastapi_app.state.campaign_adventure_service
        fastapi_app.dependency_overrides.pop(get_database_engine, None)
        fastapi_app.dependency_overrides.pop(get_room_access_context, None)


# ---------------------------------------------------------------------------
# Part 1: HTTP / API tests
# ---------------------------------------------------------------------------


def test_attach_two_adventures_and_list_in_order(
    api_fixture: CampaignAdventureApiFixture,
) -> None:
    auth_a = _auth(api_fixture.token_owner_a)
    adv_x_id = _finalized_adventure(
        api_fixture.client, api_fixture.token_owner_a, api_fixture.room_a_id, "Adventure X"
    )
    adv_y_id = _finalized_adventure(
        api_fixture.client, api_fixture.token_owner_a, api_fixture.room_a_id, "Adventure Y"
    )

    get_x_before = api_fixture.client.get(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv_x_id}",
        headers=auth_a,
    ).json()
    get_y_before = api_fixture.client.get(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv_y_id}",
        headers=auth_a,
    ).json()

    # Attach X then Y
    resp_x = api_fixture.client.post(
        f"/api/rooms/{api_fixture.room_a_id}/campaigns/{api_fixture.campaign_a1_id}/adventures",
        json={"adventure_id": str(adv_x_id)},
        headers=auth_a,
    )
    assert resp_x.status_code == 201

    resp_y = api_fixture.client.post(
        f"/api/rooms/{api_fixture.room_a_id}/campaigns/{api_fixture.campaign_a1_id}/adventures",
        json={"adventure_id": str(adv_y_id)},
        headers=auth_a,
    )
    assert resp_y.status_code == 201

    # List returns [X, Y] with sort_order 0, 1 and name/status projected; both share campaign_id
    list_resp = api_fixture.client.get(
        f"/api/rooms/{api_fixture.room_a_id}/campaigns/{api_fixture.campaign_a1_id}/adventures",
        headers=auth_a,
    )
    assert list_resp.status_code == 200
    items = list_resp.json()
    assert len(items) == 2
    assert items[0]["adventure_id"] == str(adv_x_id)
    assert items[0]["sort_order"] == 0
    assert items[0]["name"] == "Adventure X"
    assert items[0]["status"] == "finalized"
    assert items[0]["campaign_id"] == str(api_fixture.campaign_a1_id)

    assert items[1]["adventure_id"] == str(adv_y_id)
    assert items[1]["sort_order"] == 1
    assert items[1]["name"] == "Adventure Y"
    assert items[1]["status"] == "finalized"
    assert items[1]["campaign_id"] == str(api_fixture.campaign_a1_id)

    # GET Adventure definitions afterwards -> unchanged
    get_x_after = api_fixture.client.get(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv_x_id}",
        headers=auth_a,
    ).json()
    get_y_after = api_fixture.client.get(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv_y_id}",
        headers=auth_a,
    ).json()
    assert get_x_after["updated_at"] == get_x_before["updated_at"]
    assert get_x_after["status"] == "finalized"
    assert get_y_after["updated_at"] == get_y_before["updated_at"]
    assert get_y_after["status"] == "finalized"


def test_detach_leaves_the_other_attached(
    api_fixture: CampaignAdventureApiFixture,
) -> None:
    auth_a = _auth(api_fixture.token_owner_a)
    adv_x_id = _finalized_adventure(
        api_fixture.client, api_fixture.token_owner_a, api_fixture.room_a_id, "Adventure X"
    )
    adv_y_id = _finalized_adventure(
        api_fixture.client, api_fixture.token_owner_a, api_fixture.room_a_id, "Adventure Y"
    )

    api_fixture.client.post(
        f"/api/rooms/{api_fixture.room_a_id}/campaigns/{api_fixture.campaign_a1_id}/adventures",
        json={"adventure_id": str(adv_x_id)},
        headers=auth_a,
    )
    api_fixture.client.post(
        f"/api/rooms/{api_fixture.room_a_id}/campaigns/{api_fixture.campaign_a1_id}/adventures",
        json={"adventure_id": str(adv_y_id)},
        headers=auth_a,
    )

    # Detach X -> 204
    del_resp = api_fixture.client.delete(
        f"/api/rooms/{api_fixture.room_a_id}/campaigns/{api_fixture.campaign_a1_id}/adventures/{adv_x_id}",
        headers=auth_a,
    )
    assert del_resp.status_code == 204

    # List == [Y]
    list_resp = api_fixture.client.get(
        f"/api/rooms/{api_fixture.room_a_id}/campaigns/{api_fixture.campaign_a1_id}/adventures",
        headers=auth_a,
    )
    assert list_resp.status_code == 200
    items = list_resp.json()
    assert len(items) == 1
    assert items[0]["adventure_id"] == str(adv_y_id)

    # Detach X again -> 404 campaign_adventure_link_not_found
    del_again = api_fixture.client.delete(
        f"/api/rooms/{api_fixture.room_a_id}/campaigns/{api_fixture.campaign_a1_id}/adventures/{adv_x_id}",
        headers=auth_a,
    )
    assert del_again.status_code == 404
    assert del_again.json()["error"]["code"] == "campaign_adventure_link_not_found"

    # Adventure X definition still exists (GET 200)
    get_x = api_fixture.client.get(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv_x_id}",
        headers=auth_a,
    )
    assert get_x.status_code == 200


def test_duplicate_attach_is_409_with_zero_side_effects(
    api_fixture: CampaignAdventureApiFixture,
) -> None:
    auth_a = _auth(api_fixture.token_owner_a)
    adv_x_id = _finalized_adventure(
        api_fixture.client, api_fixture.token_owner_a, api_fixture.room_a_id, "Adventure X"
    )

    resp1 = api_fixture.client.post(
        f"/api/rooms/{api_fixture.room_a_id}/campaigns/{api_fixture.campaign_a1_id}/adventures",
        json={"adventure_id": str(adv_x_id)},
        headers=auth_a,
    )
    assert resp1.status_code == 201

    # Attach X twice -> 409 adventure_already_attached
    resp2 = api_fixture.client.post(
        f"/api/rooms/{api_fixture.room_a_id}/campaigns/{api_fixture.campaign_a1_id}/adventures",
        json={"adventure_id": str(adv_x_id)},
        headers=auth_a,
    )
    assert resp2.status_code == 409
    assert resp2.json()["error"]["code"] == "adventure_already_attached"

    # Link row count is unchanged and sort_order is unchanged
    with api_fixture.engine.connect() as conn:
        rows = conn.execute(
            select(campaign_adventure_links).where(
                campaign_adventure_links.c.campaign_id == api_fixture.campaign_a1_id
            )
        ).mappings().all()
        assert len(rows) == 1
        assert rows[0]["sort_order"] == 0


def test_draft_and_archived_adventures_cannot_attach(
    api_fixture: CampaignAdventureApiFixture,
) -> None:
    auth_a = _auth(api_fixture.token_owner_a)

    # Draft adventure
    draft_resp = api_fixture.client.post(
        f"/api/rooms/{api_fixture.room_a_id}/adventures",
        json={"name": "Draft Adv"},
        headers=auth_a,
    )
    assert draft_resp.status_code == 201
    draft_id = draft_resp.json()["id"]

    att_draft = api_fixture.client.post(
        f"/api/rooms/{api_fixture.room_a_id}/campaigns/{api_fixture.campaign_a1_id}/adventures",
        json={"adventure_id": draft_id},
        headers=auth_a,
    )
    assert att_draft.status_code == 409
    assert att_draft.json()["error"]["code"] == "adventure_not_finalized"

    # Create + finalize + archive another
    arch_id = _finalized_adventure(
        api_fixture.client, api_fixture.token_owner_a, api_fixture.room_a_id, "Archived Adv"
    )
    arch_resp = api_fixture.client.post(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{arch_id}/archive",
        headers=auth_a,
    )
    assert arch_resp.status_code == 200

    att_arch = api_fixture.client.post(
        f"/api/rooms/{api_fixture.room_a_id}/campaigns/{api_fixture.campaign_a1_id}/adventures",
        json={"adventure_id": str(arch_id)},
        headers=auth_a,
    )
    assert att_arch.status_code == 409
    assert att_arch.json()["error"]["code"] == "adventure_not_finalized"

    # Link row count is 0
    with api_fixture.engine.connect() as conn:
        count = conn.scalar(
            select(func.count())
            .select_from(campaign_adventure_links)
            .where(campaign_adventure_links.c.campaign_id == api_fixture.campaign_a1_id)
        )
        assert count == 0


def test_cross_room_adventure_and_campaign_are_404(
    api_fixture: CampaignAdventureApiFixture,
) -> None:
    adv_b_id = _finalized_adventure(
        api_fixture.client, api_fixture.token_owner_b, api_fixture.room_b_id, "Room B Adv"
    )

    # owner_a attaches an Adventure from room B to campaign A1 -> 404 adventure_not_found
    resp1 = api_fixture.client.post(
        f"/api/rooms/{api_fixture.room_a_id}/campaigns/{api_fixture.campaign_a1_id}/adventures",
        json={"adventure_id": str(adv_b_id)},
        headers=_auth(api_fixture.token_owner_a),
    )
    assert resp1.status_code == 404
    assert resp1.json()["error"]["code"] == "adventure_not_found"

    # owner_a targets campaign B1 through room A URL -> 404 campaign_not_found
    resp2 = api_fixture.client.post(
        f"/api/rooms/{api_fixture.room_a_id}/campaigns/{api_fixture.campaign_b1_id}/adventures",
        json={"adventure_id": str(adv_b_id)},
        headers=_auth(api_fixture.token_owner_a),
    )
    assert resp2.status_code == 404
    assert resp2.json()["error"]["code"] == "campaign_not_found"

    resp2_get = api_fixture.client.get(
        f"/api/rooms/{api_fixture.room_a_id}/campaigns/{api_fixture.campaign_b1_id}/adventures",
        headers=_auth(api_fixture.token_owner_a),
    )
    assert resp2_get.status_code == 404
    assert resp2_get.json()["error"]["code"] == "campaign_not_found"

    # owner_b with room_a URL -> 404
    resp3 = api_fixture.client.get(
        f"/api/rooms/{api_fixture.room_a_id}/campaigns/{api_fixture.campaign_a1_id}/adventures",
        headers=_auth(api_fixture.token_owner_b),
    )
    assert resp3.status_code == 404


def test_member_gets_404_on_attach_list_detach(
    api_fixture: CampaignAdventureApiFixture,
) -> None:
    adv_id = _finalized_adventure(
        api_fixture.client, api_fixture.token_owner_a, api_fixture.room_a_id, "Adv for Member"
    )
    member_auth = _auth(api_fixture.token_member_a)

    # POST -> 404 adventure_not_found
    resp_post = api_fixture.client.post(
        f"/api/rooms/{api_fixture.room_a_id}/campaigns/{api_fixture.campaign_a1_id}/adventures",
        json={"adventure_id": str(adv_id)},
        headers=member_auth,
    )
    assert resp_post.status_code == 404
    assert resp_post.json()["error"]["code"] == "adventure_not_found"

    # GET -> 404 adventure_not_found
    resp_get = api_fixture.client.get(
        f"/api/rooms/{api_fixture.room_a_id}/campaigns/{api_fixture.campaign_a1_id}/adventures",
        headers=member_auth,
    )
    assert resp_get.status_code == 404
    assert resp_get.json()["error"]["code"] == "adventure_not_found"

    # DELETE -> 404 adventure_not_found
    resp_del = api_fixture.client.delete(
        f"/api/rooms/{api_fixture.room_a_id}/campaigns/{api_fixture.campaign_a1_id}/adventures/{adv_id}",
        headers=member_auth,
    )
    assert resp_del.status_code == 404
    assert resp_del.json()["error"]["code"] == "adventure_not_found"

    # No rows written
    with api_fixture.engine.connect() as conn:
        count = conn.scalar(
            select(func.count()).select_from(campaign_adventure_links)
        )
        assert count == 0


def test_dm_can_attach_and_detach(
    api_fixture: CampaignAdventureApiFixture,
) -> None:
    adv_id = _finalized_adventure(
        api_fixture.client, api_fixture.token_owner_a, api_fixture.room_a_id, "Adv for DM"
    )
    dm_auth = _auth(api_fixture.token_dm_a)

    # dm_a POST 201
    resp_post = api_fixture.client.post(
        f"/api/rooms/{api_fixture.room_a_id}/campaigns/{api_fixture.campaign_a1_id}/adventures",
        json={"adventure_id": str(adv_id)},
        headers=dm_auth,
    )
    assert resp_post.status_code == 201

    # dm_a GET lists 1
    resp_get = api_fixture.client.get(
        f"/api/rooms/{api_fixture.room_a_id}/campaigns/{api_fixture.campaign_a1_id}/adventures",
        headers=dm_auth,
    )
    assert resp_get.status_code == 200
    assert len(resp_get.json()) == 1

    # dm_a DELETE 204
    resp_del = api_fixture.client.delete(
        f"/api/rooms/{api_fixture.room_a_id}/campaigns/{api_fixture.campaign_a1_id}/adventures/{adv_id}",
        headers=dm_auth,
    )
    assert resp_del.status_code == 204

    # List is now empty
    resp_after = api_fixture.client.get(
        f"/api/rooms/{api_fixture.room_a_id}/campaigns/{api_fixture.campaign_a1_id}/adventures",
        headers=dm_auth,
    )
    assert resp_after.status_code == 200
    assert resp_after.json() == []


# ---------------------------------------------------------------------------
# Part 2: Real services & regression tests (no TestClient)
# ---------------------------------------------------------------------------


def test_empty_campaign_still_starts_session_narrates_checks_and_fights() -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata.create_all(engine)
    registry = load_default_content_registry()

    rooms_service = RoomService(RoomRepository(engine))
    owner = rooms_service.create_room(
        CreateRoomRequest(name="Empty-Campaign", password="secret", display_name="Player")
    )
    dm = rooms_service.enter_room(
        EnterRoomRequest(
            code=owner.room.code,
            password="secret",
            elevated_key=owner.dm_key,
            display_name="DM",
        ),
        remote_addr="127.0.0.2",
    )

    characters = CharacterRepository(engine, registry)
    build = build_p0_fighter_wizard_fixture()
    character = characters.create_character(
        name="Mira",
        build=build,
        state=build_p0_fighter_wizard_state(build),
    )
    RoomWorkspaceRepository(engine).attach_character(
        room_id=owner.room.id,
        character_id=character.id,
    )

    campaigns_service = CampaignService(CampaignRepository(engine))
    campaign = campaigns_service.create_campaign(
        owner.room.id,
        CampaignCreate(name="Campaign", ruleset="dnd5e-2014"),
    )
    campaigns_service.set_status(owner.room.id, campaign.id, CampaignStatus.ACTIVE)
    campaigns_service.select_campaign(owner.room.id, campaign.id)
    campaigns_service.add_character(
        owner.room.id,
        campaign.id,
        RosterAdd(character_id=character.id),
    )

    seats_service = SeatService(SeatRepository(engine))
    dm_seat = seats_service.create_seat(
        owner.room.id, campaign.id, SeatCreate(role=SeatRole.DM, label="DM")
    )
    seats_service.set_controller(
        owner.room.id,
        campaign.id,
        dm_seat.id,
        SeatControllerPatch(
            controller_kind=ControllerKind.HUMAN,
            controller_access_session_id=dm.access_session_id,
        ),
    )
    player_seat = seats_service.create_seat(
        owner.room.id,
        campaign.id,
        SeatCreate(role=SeatRole.PLAYER, label="Player"),
    )
    seats_service.set_controller(
        owner.room.id,
        campaign.id,
        player_seat.id,
        SeatControllerPatch(
            controller_kind=ControllerKind.HUMAN,
            controller_access_session_id=owner.access_session_id,
        ),
    )
    seats_service.select_character(owner.room.id, campaign.id, player_seat.id, character.id)

    dm_context = rooms_service.authenticate(owner.room.id, dm.access_token)
    events_service = TableEventService(TableEventRepository(engine))
    sessions_service = SessionService(SessionRepository(engine), event_service=events_service)

    link_repo = CampaignAdventureLinkRepository(engine)
    # Assert Campaign has ZERO attached Adventures before
    assert link_repo.list_for_campaign(campaign.id) == ()

    # 1. SessionService.start_session succeeds
    started = sessions_service.start_session(owner.room.id, campaign.id, dm_context)
    assert started.id is not None

    dm_actor = events_service.resolve_human_actor(
        room_id=owner.room.id,
        campaign_id=campaign.id,
        session_id=started.id,
        context=dm_context,
    )

    # 2. ExplorationActionService.send narration succeeds
    exploration_service = ExplorationActionService(
        ExplorationSubjectRepository(engine),
        ExplorationMessageRepository(engine),
        events_service,
    )
    narration_event = exploration_service.send(
        dm_actor,
        ExplorationInputRequest(
            kind=ExplorationInputKind.NARRATION,
            text="The road is quiet.",
        ),
    )
    assert narration_event.kind == "exploration.narration"

    # 3. RollService.request_check returns one request
    roll_service = RollService(
        CombatAwareRollRepository(engine, events_service.repository),
        ExplorationSubjectRepository(engine),
        events_service,
        CharacterRollModifierResolver(characters, registry),
        registry=registry,
    )
    group_id, requests = roll_service.request_check(
        dm_actor,
        RequestCheckInput(
            target_seat_ids=(player_seat.id,),
            request_type=RollRequestType.SKILL,
            ability_ref="wis",
            skill_ref="perception",
            dc=10,
        ),
    )
    assert len(requests) == 1

    # 4. CombatService.start_quick_combat returns a CombatView
    combat_service = CombatService(
        CombatRepository(engine, events_service.repository),
        events_service,
        characters,
        MonsterRepository(engine),
        registry,
    )
    combat_view = combat_service.start_quick_combat(
        dm_actor,
        StartCombatInput(idempotency_key="empty-campaign"),
    )
    assert combat_view.id is not None

    # Assert Campaign has ZERO attached Adventures after
    assert link_repo.list_for_campaign(campaign.id) == ()


def test_adventure_domain_has_no_gameplay_actor_entry_point() -> None:
    for cls in (AdventureService, CampaignAdventureService):
        for name, method in inspect.getmembers(cls, predicate=inspect.isfunction):
            if name.startswith("_"):
                continue
            hints = typing.get_type_hints(method)
            sig = inspect.signature(method)
            params = [p for p in sig.parameters.values() if p.name != "self"]
            assert len(params) >= 1, f"{cls.__name__}.{name} has no parameters"
            assert (
                params[0].name == "context"
            ), f"{cls.__name__}.{name} first non-self parameter is '{params[0].name}', expected 'context'"
            assert (
                hints.get(params[0].name) is RoomAccessContext
            ), f"{cls.__name__}.{name} first parameter type is {hints.get(params[0].name)}, expected RoomAccessContext"
            for p in params:
                assert (
                    hints.get(p.name) is not TableActorContext
                ), f"{cls.__name__}.{name} parameter '{p.name}' is TableActorContext"

    assert "TableActorContext" not in inspect.getsource(app.domain.adventures.service)
    assert "TableActorContext" not in inspect.getsource(app.domain.adventures.attachments)
    for tool_def in app.mcp.tools._TOOL_DEFINITIONS:
        assert "adventure" not in tool_def.name.lower(), f"MCP tool {tool_def.name} contains 'adventure'"
