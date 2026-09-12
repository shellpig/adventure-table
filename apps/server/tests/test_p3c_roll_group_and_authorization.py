from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool

from app.content import load_default_content_registry
from app.db import metadata
from app.domain.character.fixture import (
    build_p0_fighter_wizard_fixture,
    build_p0_fighter_wizard_state,
)
from app.domain.rooms.campaigns import (
    CampaignCreate,
    CampaignService,
    CampaignStatus,
    RosterAdd,
)
from app.domain.rooms.character_rolls import CharacterRollModifierResolver
from app.domain.rooms.rolls import (
    CheckReferenceInvalidError,
    FormalRollInput,
    RequestCheckInput,
    RollModifierMode,
    RollRequestNotFoundError,
    RollRequestType,
    RollService,
    RollVisibility,
)
from app.domain.rooms.schemas import CreateRoomRequest, EnterRoomRequest
from app.domain.rooms.seats import (
    ControllerKind,
    SeatControllerPatch,
    SeatCreate,
    SeatRole,
    SeatService,
)
from app.domain.rooms.service import RoomService
from app.domain.rooms.sessions import SessionService
from app.domain.rooms.table_events import (
    TableEventActorUnauthorizedError,
    TableEventService,
)
from app.persistence.characters import CharacterRepository
from app.persistence.rooms.campaigns import CampaignRepository
from app.persistence.rooms.exploration_subjects import ExplorationSubjectRepository
from app.persistence.rooms.p3c_rolls import RollRepository
from app.persistence.rooms.repository import RoomRepository
from app.persistence.rooms.seats import SeatRepository
from app.persistence.rooms.sessions import SessionRepository
from app.persistence.rooms.table_runtime import TableEventRepository
from app.persistence.rooms.workspace import RoomWorkspaceRepository


PERCEPTION = "srd5.1:skill:perception"


class Table:
    """One started Session with two independently controlled Player Seats."""

    def __init__(self, **fields) -> None:
        self.__dict__.update(fields)


def _engine():
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


def _setup(engine) -> Table:
    registry = load_default_content_registry()
    rooms = RoomService(RoomRepository(engine))
    owner = rooms.create_room(
        CreateRoomRequest(name="P3-C Roll Room", password="secret", display_name="Mira Player")
    )
    dm = rooms.enter_room(
        EnterRoomRequest(
            code=owner.room.code,
            password="secret",
            elevated_key=owner.dm_key,
            display_name="DM",
        ),
        remote_addr="127.0.0.2",
    )
    other = rooms.enter_room(
        EnterRoomRequest(
            code=owner.room.code,
            password="secret",
            display_name="Bran Player",
        ),
        remote_addr="127.0.0.3",
    )

    characters = CharacterRepository(engine, registry)
    workspace = RoomWorkspaceRepository(engine)
    campaigns = CampaignService(CampaignRepository(engine))
    campaign = campaigns.create_campaign(
        owner.room.id,
        CampaignCreate(name="Campaign", ruleset="dnd5e-2014"),
    )
    campaigns.set_status(owner.room.id, campaign.id, CampaignStatus.ACTIVE)
    campaigns.select_campaign(owner.room.id, campaign.id)

    seats = SeatService(SeatRepository(engine))
    dm_seat = seats.create_seat(
        owner.room.id,
        campaign.id,
        SeatCreate(role=SeatRole.DM, label="DM"),
    )
    seats.set_controller(
        owner.room.id,
        campaign.id,
        dm_seat.id,
        SeatControllerPatch(
            controller_kind=ControllerKind.HUMAN,
            controller_access_session_id=dm.access_session_id,
        ),
    )

    player_seats = {}
    player_characters = {}
    for label, access_session_id in (
        ("Mira", owner.access_session_id),
        ("Bran", other.access_session_id),
    ):
        build = build_p0_fighter_wizard_fixture()
        character = characters.create_character(
            name=label,
            build=build,
            state=build_p0_fighter_wizard_state(build),
        )
        workspace.attach_character(room_id=owner.room.id, character_id=character.id)
        campaigns.add_character(
            owner.room.id,
            campaign.id,
            RosterAdd(character_id=character.id),
        )
        seat = seats.create_seat(
            owner.room.id,
            campaign.id,
            SeatCreate(role=SeatRole.PLAYER, label=f"{label} Player"),
        )
        seats.set_controller(
            owner.room.id,
            campaign.id,
            seat.id,
            SeatControllerPatch(
                controller_kind=ControllerKind.HUMAN,
                controller_access_session_id=access_session_id,
            ),
        )
        seats.select_character(owner.room.id, campaign.id, seat.id, character.id)
        player_seats[label] = seat
        player_characters[label] = character

    dm_context = rooms.authenticate(owner.room.id, dm.access_token)
    mira_context = rooms.authenticate(owner.room.id, owner.access_token)
    bran_context = rooms.authenticate(owner.room.id, other.access_token)
    started = SessionService(SessionRepository(engine)).start_session(
        owner.room.id, campaign.id, dm_context
    )

    events = TableEventService(TableEventRepository(engine))
    modifier_resolver = CharacterRollModifierResolver(characters, registry)
    service = RollService(
        RollRepository(engine, events.repository),
        ExplorationSubjectRepository(engine),
        events,
        modifier_resolver,
        registry=registry,
    )

    def actor(context):
        return events.resolve_human_actor(
            room_id=owner.room.id,
            campaign_id=campaign.id,
            session_id=started.id,
            context=context,
        )

    return Table(
        service=service,
        events=events,
        modifier_resolver=modifier_resolver,
        mira_seat=player_seats["Mira"],
        bran_seat=player_seats["Bran"],
        mira_character=player_characters["Mira"],
        dm_actor=actor(dm_context),
        mira_actor=actor(mira_context),
        bran_actor=actor(bran_context),
    )


def test_group_check_tracks_each_seat_from_waiting_to_rolled() -> None:
    engine = _engine()
    try:
        table = _setup(engine)
        group_id, requests = table.service.request_check(
            table.dm_actor,
            RequestCheckInput(
                target_seat_ids=(table.mira_seat.id, table.bran_seat.id),
                request_type=RollRequestType.SKILL,
                skill_ref=PERCEPTION,
                dc=13,
                label="Party listens at the door",
            ),
        )

        assert len({request.roll_group_id for request in requests}) == 1
        assert requests[0].roll_group_id == group_id
        assert {request.target_seat_id for request in requests} == {
            table.mira_seat.id,
            table.bran_seat.id,
        }
        assert [request.status for request in requests] == ["pending", "pending"]

        mira_request = next(
            request for request in requests if request.target_seat_id == table.mira_seat.id
        )
        bran_request = next(
            request for request in requests if request.target_seat_id == table.bran_seat.id
        )

        # One Seat rolls for itself, the other is completed by current DM proxy.
        table.service.complete_formal(
            table.mira_actor,
            FormalRollInput(roll_request_id=mira_request.id),
        )
        after_first = {
            request.id: request.status
            for request in table.service.list_requests(table.dm_actor)
        }
        assert after_first[mira_request.id] == "resolved"
        assert after_first[bran_request.id] == "pending"

        table.service.complete_formal(
            table.dm_actor,
            FormalRollInput(roll_request_id=bran_request.id),
        )
        after_second = {
            request.id: request.status
            for request in table.service.list_requests(table.dm_actor)
        }
        assert set(after_second.values()) == {"resolved"}

        # The group is a projection of per-Seat truth only: nothing in it claims
        # the party succeeded or failed, that stays the DM's call.
        assert not any(
            hasattr(request, field)
            for request in requests
            for field in ("outcome", "success", "group_result")
        )
    finally:
        engine.dispose()


def test_current_dm_proxy_rolls_with_subject_character_rules_and_keeps_both_identities() -> None:
    engine = _engine()
    try:
        table = _setup(engine)
        _group_id, requests = table.service.request_check(
            table.dm_actor,
            RequestCheckInput(
                target_seat_ids=(table.mira_seat.id,),
                request_type=RollRequestType.SKILL,
                skill_ref=PERCEPTION,
                modifier_mode=RollModifierMode.ADVANTAGE,
                visibility=RollVisibility.ROLLER_AND_DM,
            ),
        )
        request = requests[0]

        result = table.service.complete_formal(
            table.dm_actor,
            FormalRollInput(roll_request_id=request.id),
        )

        expected_modifier = table.modifier_resolver.modifier_for(
            character_id=table.mira_character.id,
            request_type=RollRequestType.SKILL,
            ability_ref=None,
            skill_ref=PERCEPTION,
        )
        assert result.base_modifier == expected_modifier
        assert result.subject_character_id == table.mira_character.id
        assert result.subject_seat_id == table.mira_seat.id
        assert result.acting_seat_id == table.dm_actor.seat_id
        assert result.execution_mode == "dm_proxy"
        assert len(result.raw_dice) == 2
        assert result.kept_dice == (max(result.raw_dice),)
        assert result.total == result.kept_dice[0] + result.base_modifier
    finally:
        engine.dispose()


def test_third_party_player_cannot_complete_another_seats_request() -> None:
    engine = _engine()
    try:
        table = _setup(engine)
        _group_id, requests = table.service.request_check(
            table.dm_actor,
            RequestCheckInput(
                target_seat_ids=(table.mira_seat.id,),
                request_type=RollRequestType.SKILL,
                skill_ref=PERCEPTION,
            ),
        )
        request = requests[0]
        before = table.events.current_cursor(table.dm_actor)

        with pytest.raises(TableEventActorUnauthorizedError):
            table.service.complete_formal(
                table.bran_actor,
                FormalRollInput(roll_request_id=request.id),
            )

        assert table.events.current_cursor(table.dm_actor) == before
        still_pending = table.service.list_requests(table.dm_actor)
        assert [item.status for item in still_pending] == ["pending"]
    finally:
        engine.dispose()


def test_request_outside_this_session_is_never_resolvable() -> None:
    engine = _engine()
    try:
        table = _setup(engine)
        with pytest.raises(RollRequestNotFoundError):
            table.service.complete_formal(
                table.mira_actor,
                FormalRollInput(roll_request_id=uuid4()),
            )
    finally:
        engine.dispose()


def test_stale_actor_binding_cannot_submit_a_formal_roll() -> None:
    engine = _engine()
    try:
        table = _setup(engine)
        _group_id, requests = table.service.request_check(
            table.dm_actor,
            RequestCheckInput(
                target_seat_ids=(table.mira_seat.id,),
                request_type=RollRequestType.SKILL,
                skill_ref=PERCEPTION,
            ),
        )
        request = requests[0]
        stale = table.mira_actor.model_copy(update={"access_session_id": uuid4()})

        with pytest.raises(TableEventActorUnauthorizedError):
            table.service.complete_formal(
                stale,
                FormalRollInput(roll_request_id=request.id),
            )

        assert [
            item.status for item in table.service.list_requests(table.dm_actor)
        ] == ["pending"]
    finally:
        engine.dispose()


def test_request_check_accepts_a_bare_skill_name_and_normalises_to_stable_key() -> None:
    engine = _engine()
    try:
        table = _setup(engine)
        _group_id, requests = table.service.request_check(
            table.dm_actor,
            RequestCheckInput(
                target_seat_ids=(table.mira_seat.id,),
                request_type=RollRequestType.SKILL,
                skill_ref="perception",
            ),
        )
        # Stored ref is the stable key, so a server roll resolves the modifier.
        assert requests[0].skill_ref == "srd5.1:skill:perception"
        result = table.service.complete_formal(
            table.mira_actor,
            FormalRollInput(roll_request_id=requests[0].id),
        )
        assert result.total is not None
    finally:
        engine.dispose()


def test_request_check_rejects_an_unknown_skill_at_creation() -> None:
    engine = _engine()
    try:
        table = _setup(engine)
        with pytest.raises(CheckReferenceInvalidError):
            table.service.request_check(
                table.dm_actor,
                RequestCheckInput(
                    target_seat_ids=(table.mira_seat.id,),
                    request_type=RollRequestType.SKILL,
                    skill_ref="telepathy",
                ),
            )
    finally:
        engine.dispose()
