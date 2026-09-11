from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool

from app.content import load_default_content_registry
from app.db import metadata
from app.domain.character.fixture import build_p0_fighter_wizard_fixture, build_p0_fighter_wizard_state
from app.domain.rooms.campaigns import CampaignCreate, CampaignService, CampaignStatus, RosterAdd
from app.domain.rooms.character_rolls import CharacterRollModifierResolver
from app.domain.rooms.exploration import (
    ExplorationActionService,
    ExplorationInputKind,
    ExplorationInputRequest,
    ExplorationStageService,
    StageUpdateRequest,
)
from app.domain.rooms.rolls import (
    FormalRollInput,
    RequestCheckInput,
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
from app.domain.rooms.sessions import SessionLateJoinRequest, SessionService
from app.domain.rooms.table_events import TableEventNotFoundError, TableEventService
from app.persistence.characters import CharacterRepository
from app.persistence.rooms.campaigns import CampaignRepository
from app.persistence.rooms.exploration import ExplorationRepository
from app.persistence.rooms.exploration_messages import ExplorationMessageRepository
from app.persistence.rooms.exploration_subjects import ExplorationSubjectRepository
from app.persistence.rooms.p3c_rolls import RollRepository
from app.persistence.rooms.repository import RoomRepository
from app.persistence.rooms.seats import SeatRepository
from app.persistence.rooms.sessions import SessionRepository
from app.persistence.rooms.table_runtime import TableEventRepository
from app.persistence.rooms.workspace import RoomWorkspaceRepository

import pytest


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


def _setup(engine):
    """Start a Session with DM + Mira; Luna's Seat exists but joins late."""
    registry = load_default_content_registry()
    rooms = RoomService(RoomRepository(engine))
    owner = rooms.create_room(CreateRoomRequest(name="P3-F Late Join", password="secret"))
    dm = rooms.enter_room(
        EnterRoomRequest(code=owner.room.code, password="secret", elevated_key=owner.dm_key),
        remote_addr="127.0.0.2",
    )
    mira_player = rooms.enter_room(
        EnterRoomRequest(code=owner.room.code, password="secret", display_name="Mira Player"),
        remote_addr="127.0.0.3",
    )
    luna_player = rooms.enter_room(
        EnterRoomRequest(code=owner.room.code, password="secret", display_name="Luna Player"),
        remote_addr="127.0.0.4",
    )

    build = build_p0_fighter_wizard_fixture()
    characters = CharacterRepository(engine, registry)
    workspace = RoomWorkspaceRepository(engine)
    mira = characters.create_character(
        name="Mira", build=build, state=build_p0_fighter_wizard_state(build),
    )
    luna = characters.create_character(
        name="Luna", build=build, state=build_p0_fighter_wizard_state(build),
    )
    for character in (mira, luna):
        workspace.attach_character(room_id=owner.room.id, character_id=character.id)

    campaigns = CampaignService(CampaignRepository(engine))
    campaign = campaigns.create_campaign(
        owner.room.id, CampaignCreate(name="Campaign", ruleset="dnd5e-2014"),
    )
    campaigns.set_status(owner.room.id, campaign.id, CampaignStatus.ACTIVE)
    campaigns.select_campaign(owner.room.id, campaign.id)
    for character in (mira, luna):
        campaigns.add_character(owner.room.id, campaign.id, RosterAdd(character_id=character.id))

    seats = SeatService(SeatRepository(engine))
    dm_seat = seats.create_seat(owner.room.id, campaign.id, SeatCreate(role=SeatRole.DM))
    seats.set_controller(
        owner.room.id, campaign.id, dm_seat.id,
        SeatControllerPatch(
            controller_kind=ControllerKind.HUMAN,
            controller_access_session_id=dm.access_session_id,
        ),
    )
    mira_seat = seats.create_seat(owner.room.id, campaign.id, SeatCreate(role=SeatRole.PLAYER))
    seats.set_controller(
        owner.room.id, campaign.id, mira_seat.id,
        SeatControllerPatch(
            controller_kind=ControllerKind.HUMAN,
            controller_access_session_id=mira_player.access_session_id,
        ),
    )
    seats.select_character(owner.room.id, campaign.id, mira_seat.id, mira.id)

    events = TableEventService(TableEventRepository(engine))
    sessions = SessionService(SessionRepository(engine), event_service=events)
    started = sessions.start_session(
        owner.room.id, campaign.id, rooms.authenticate(owner.room.id, dm.access_token),
    )

    # Luna's Seat is created after Start so it is not a participant yet.
    luna_seat = seats.create_seat(owner.room.id, campaign.id, SeatCreate(role=SeatRole.PLAYER))
    seats.set_controller(
        owner.room.id, campaign.id, luna_seat.id,
        SeatControllerPatch(
            controller_kind=ControllerKind.HUMAN,
            controller_access_session_id=luna_player.access_session_id,
        ),
    )
    seats.select_character(owner.room.id, campaign.id, luna_seat.id, luna.id)

    contexts = {
        "dm": rooms.authenticate(owner.room.id, dm.access_token),
        "mira": rooms.authenticate(owner.room.id, mira_player.access_token),
        "luna": rooms.authenticate(owner.room.id, luna_player.access_token),
    }
    services = {
        "events": events,
        "sessions": sessions,
        "stage": ExplorationStageService(ExplorationRepository(engine), events),
        "actions": ExplorationActionService(
            ExplorationSubjectRepository(engine),
            ExplorationMessageRepository(engine),
            events,
        ),
        "rolls": RollService(
            RollRepository(engine, events.repository),
            ExplorationSubjectRepository(engine),
            events,
            CharacterRollModifierResolver(characters, registry),
        ),
    }
    ids = {
        "room_id": owner.room.id,
        "campaign_id": campaign.id,
        "session_id": started.id,
        "mira_seat_id": mira_seat.id,
        "luna_seat_id": luna_seat.id,
        "luna_character_id": luna.id,
    }
    return services, contexts, ids


def _actor(services, contexts, ids, who):
    return services["events"].resolve_human_actor(
        room_id=ids["room_id"],
        campaign_id=ids["campaign_id"],
        session_id=ids["session_id"],
        context=contexts[who],
    )


def test_late_joiner_gets_stage_and_public_context_but_not_prior_private_events_and_can_complete_new_check() -> None:
    engine = _engine()
    try:
        services, contexts, ids = _setup(engine)
        events = services["events"]
        dm = _actor(services, contexts, ids, "dm")
        mira = _actor(services, contexts, ids, "mira")

        # Exploration history before Luna joins: Stage, public action,
        # Mira's private whisper, and a DM-only event.
        services["stage"].replace_stage(
            dm,
            StageUpdateRequest(expected_revision=0, text="A flooded crypt", idempotency_key="p3f-lj-stage"),
        )
        services["actions"].send(
            mira,
            ExplorationInputRequest(
                kind=ExplorationInputKind.ACTION,
                text="I wade toward the sarcophagus.",
                subject_seat_id=ids["mira_seat_id"],
            ),
        )
        whisper = services["actions"].send(
            mira,
            ExplorationInputRequest(kind=ExplorationInputKind.WHISPER_DM, text="I hid the amulet."),
        )
        assert whisper.visibility.value == "seat_private"
        _group, (secret_request,) = services["rolls"].request_check(
            dm,
            RequestCheckInput(
                target_seat_ids=(ids["mira_seat_id"],),
                request_type=RollRequestType.OTHER,
                dc=15,
                visibility=RollVisibility.DM_ONLY,
                label="Mira secret check",
                idempotency_key="p3f-lj-secret",
            ),
        )
        services["rolls"].complete_formal(
            mira,
            FormalRollInput(roll_request_id=secret_request.id, idempotency_key="p3f-lj-secret-roll"),
        )
        dm_history = events.list_after(dm, after_seq=0, limit=50)
        dm_kinds = [item.kind for item in dm_history.events]
        assert "exploration.whisper_dm" in dm_kinds
        assert "roll.resolved" in dm_kinds
        history_seq = dm_history.cursor

        # Before Late Join the Seat's controller is not a Session actor at all.
        with pytest.raises(TableEventNotFoundError):
            _actor(services, contexts, ids, "luna")

        joined = services["sessions"].late_join(
            ids["room_id"],
            ids["campaign_id"],
            ids["session_id"],
            SessionLateJoinRequest(seat_id=ids["luna_seat_id"]),
            contexts["dm"],
        )
        participant = next(p for p in joined.participants if p.seat_id == ids["luna_seat_id"])
        assert participant.active_character_id == ids["luna_character_id"]

        luna = _actor(services, contexts, ids, "luna")
        assert luna.controlled_seat_ids == (ids["luna_seat_id"],)

        # Current Stage is visible to the late joiner.
        assert services["stage"].get_stage(luna).text == "A flooded crypt"

        # Historical public context is projected; prior private / DM-only
        # payloads are not, even though the cursor covers the same seq range.
        luna_history = events.list_after(luna, after_seq=0, limit=50)
        assert luna_history.cursor == history_seq
        luna_kinds = [item.kind for item in luna_history.events]
        assert "stage.updated" in luna_kinds
        assert "exploration.action" in luna_kinds
        assert "exploration.whisper_dm" not in luna_kinds
        for item in luna_history.events:
            assert "I hid the amulet." not in str(item.payload)
            assert str(secret_request.id) not in str(item.payload)

        # New public and own events reach the late joiner.
        services["actions"].send(
            dm,
            ExplorationInputRequest(kind=ExplorationInputKind.NARRATION, text="Water drips from the vault."),
        )
        services["actions"].send(
            luna,
            ExplorationInputRequest(
                kind=ExplorationInputKind.DIALOGUE,
                text="Who else is down here?",
                subject_seat_id=ids["luna_seat_id"],
            ),
        )
        fresh = events.list_after(luna, after_seq=history_seq, limit=50)
        assert [item.kind for item in fresh.events] == [
            "exploration.narration",
            "exploration.dialogue",
        ]
        assert fresh.events[-1].acting_seat_id == ids["luna_seat_id"]

        # The late joiner can complete a new Request Check on its own Seat.
        _group, (request,) = services["rolls"].request_check(
            dm,
            RequestCheckInput(
                target_seat_ids=(ids["luna_seat_id"],),
                request_type=RollRequestType.ABILITY,
                ability_ref="srd5.1:ability:wis",
                dc=12,
                visibility=RollVisibility.PUBLIC,
                label="Luna listens",
                idempotency_key="p3f-lj-check",
            ),
        )
        assert [item.id for item in services["rolls"].list_requests(luna)] == [request.id]
        result = services["rolls"].complete_formal(
            luna,
            FormalRollInput(roll_request_id=request.id, idempotency_key="p3f-lj-roll"),
        )
        assert result.roll_request_id == request.id
        assert result.acting_seat_id == ids["luna_seat_id"]
        assert result.subject_character_id == ids["luna_character_id"]
        assert result.execution_mode == "self"
        resolved = {item.id: item for item in services["rolls"].list_requests(dm)}[request.id]
        assert resolved.status == "resolved"
        assert events.list_after(luna, after_seq=fresh.cursor, limit=50).events[-1].kind == "roll.resolved"
    finally:
        engine.dispose()
