from __future__ import annotations

import base64
from datetime import timedelta
import os
from pathlib import Path
from uuid import UUID

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Engine

from app.content import load_default_content_registry
from app.domain.character.fixture import build_p0_fighter_wizard_fixture, build_p0_fighter_wizard_state
from app.domain.rooms.ai_controllers import (
    AIControllerHandoffError,
    AIControllerService,
    AIControllerUnauthorizedError,
    AIHandoffRequest,
)
from app.domain.rooms.campaigns import CampaignCreate, CampaignService, CampaignStatus, RosterAdd
from app.domain.rooms.character_rolls import CharacterRollModifierResolver
from app.domain.rooms.exploration import (
    ExplorationActionService,
    ExplorationInputKind,
    ExplorationInputRequest,
    ExplorationStageService,
    StageImageUpload,
    StageUpdateRequest,
)
from app.domain.rooms.pending_actions import (
    PendingActionCreateInput,
    PendingActionService,
    PendingActionStatus,
    PendingActionTransitionInput,
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
from app.domain.rooms.sessions import SessionService
from app.domain.rooms.table_events import (
    TableEventAppend,
    TableEventService,
    TableEventVisibility,
)
from app.persistence.characters import CharacterRepository
from app.persistence.rooms.ai_controllers import AIControllerGrantRepository
from app.persistence.rooms.campaigns import CampaignRepository
from app.persistence.rooms.exploration import ExplorationRepository
from app.persistence.rooms.exploration_messages import ExplorationMessageRepository, session_messages
from app.persistence.rooms.exploration_subjects import ExplorationSubjectRepository
from app.persistence.rooms.p3c_pending import PendingActionRepository
from app.persistence.rooms.p3c_rolls import RollRepository
from app.persistence.rooms.p3c_runtime import roll_results
from app.persistence.rooms.repository import RoomRepository
from app.persistence.rooms.seats import SeatRepository
from app.persistence.rooms.sessions import SessionRepository
from app.persistence.rooms.table_runtime import TableEventRepository
from app.persistence.rooms.tables import campaign_seats
from app.persistence.rooms.workspace import RoomWorkspaceRepository


POSTGRES_URL = os.environ.get("P3_POSTGRES_URL")
pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="P3_POSTGRES_URL is only supplied by the P3 Non-E2E PostgreSQL job",
)
SERVER_ROOT = Path(__file__).resolve().parents[1]
PRE_SESSION_TTL = timedelta(minutes=30)


def _alembic_config() -> Config:
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SERVER_ROOT / "alembic"))
    assert POSTGRES_URL is not None
    config.set_main_option("sqlalchemy.url", POSTGRES_URL)
    config.attributes["target_database_url"] = POSTGRES_URL
    return config


@pytest.fixture()
def migrated_postgres_url() -> str:
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    engine.dispose()
    command.upgrade(_alembic_config(), "heads")
    return POSTGRES_URL


class _Services:
    """One process-local service graph; rebuilt from scratch to model a restart."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.registry = load_default_content_registry()
        self.rooms = RoomService(RoomRepository(engine))
        self.characters = CharacterRepository(engine, self.registry)
        self.workspace = RoomWorkspaceRepository(engine)
        self.campaigns = CampaignService(CampaignRepository(engine))
        self.seats = SeatService(SeatRepository(engine))
        self.events = TableEventService(TableEventRepository(engine))
        self.sessions = SessionService(SessionRepository(engine), event_service=self.events)
        self.stage = ExplorationStageService(ExplorationRepository(engine), self.events)
        self.actions = ExplorationActionService(
            ExplorationSubjectRepository(engine),
            ExplorationMessageRepository(engine),
            self.events,
        )
        roll_repository = RollRepository(engine, self.events.repository)
        self.rolls = RollService(
            roll_repository,
            ExplorationSubjectRepository(engine),
            self.events,
            CharacterRollModifierResolver(self.characters, self.registry),
        )
        self.pending = PendingActionService(
            PendingActionRepository(engine, self.events.repository),
            ExplorationSubjectRepository(engine),
            self.events,
            roll_repository,
        )
        self.grants = AIControllerGrantRepository(engine)
        self.controllers = AIControllerService(self.grants, self.events)

    def human(self, ids: dict, context):
        return self.events.resolve_human_actor(
            room_id=ids["room_id"],
            campaign_id=ids["campaign_id"],
            session_id=ids["session_id"],
            context=context,
        )

    def seat_epoch(self, seat_id: UUID) -> int:
        with self.engine.connect() as connection:
            return int(
                connection.scalar(
                    select(campaign_seats.c.controller_epoch).where(campaign_seats.c.id == seat_id)
                )
            )


def _png_upload() -> StageImageUpload:
    return StageImageUpload(
        media_type="image/png",
        filename="crypt.png",
        data_base64=base64.b64encode(b"\x89PNG\r\n\x1a\nP3F").decode("ascii"),
    )


def _build_dataset(s: _Services) -> dict:
    """Persist the Journey 8 dataset through the real service graph."""
    owner = s.rooms.create_room(CreateRoomRequest(name="P3-F Restart", password="secret"))
    dm = s.rooms.enter_room(
        EnterRoomRequest(code=owner.room.code, password="secret", elevated_key=owner.dm_key),
        remote_addr="127.0.0.2",
    )
    mira_player = s.rooms.enter_room(
        EnterRoomRequest(code=owner.room.code, password="secret", display_name="Mira Player"),
        remote_addr="127.0.0.3",
    )
    luna_player = s.rooms.enter_room(
        EnterRoomRequest(code=owner.room.code, password="secret", display_name="Luna Player"),
        remote_addr="127.0.0.4",
    )
    build = build_p0_fighter_wizard_fixture()
    mira = s.characters.create_character(
        name="Mira", build=build, state=build_p0_fighter_wizard_state(build),
    )
    luna = s.characters.create_character(
        name="Luna", build=build, state=build_p0_fighter_wizard_state(build),
    )
    for character in (mira, luna):
        s.workspace.attach_character(room_id=owner.room.id, character_id=character.id)
    campaign = s.campaigns.create_campaign(
        owner.room.id, CampaignCreate(name="Campaign", ruleset="dnd5e-2014"),
    )
    s.campaigns.set_status(owner.room.id, campaign.id, CampaignStatus.ACTIVE)
    s.campaigns.select_campaign(owner.room.id, campaign.id)
    for character in (mira, luna):
        s.campaigns.add_character(owner.room.id, campaign.id, RosterAdd(character_id=character.id))

    dm_seat = s.seats.create_seat(owner.room.id, campaign.id, SeatCreate(role=SeatRole.DM))
    s.seats.set_controller(
        owner.room.id, campaign.id, dm_seat.id,
        SeatControllerPatch(
            controller_kind=ControllerKind.HUMAN,
            controller_access_session_id=dm.access_session_id,
        ),
    )
    mira_seat = s.seats.create_seat(owner.room.id, campaign.id, SeatCreate(role=SeatRole.PLAYER))
    s.seats.set_controller(
        owner.room.id, campaign.id, mira_seat.id,
        SeatControllerPatch(
            controller_kind=ControllerKind.HUMAN,
            controller_access_session_id=mira_player.access_session_id,
        ),
    )
    s.seats.select_character(owner.room.id, campaign.id, mira_seat.id, mira.id)
    luna_seat = s.seats.create_seat(owner.room.id, campaign.id, SeatCreate(role=SeatRole.PLAYER))
    s.seats.set_controller(
        owner.room.id, campaign.id, luna_seat.id,
        SeatControllerPatch(
            controller_kind=ControllerKind.HUMAN,
            controller_access_session_id=luna_player.access_session_id,
        ),
    )
    s.seats.select_character(owner.room.id, campaign.id, luna_seat.id, luna.id)

    dm_context = s.rooms.authenticate(owner.room.id, dm.access_token)
    mira_context = s.rooms.authenticate(owner.room.id, mira_player.access_token)
    luna_context = s.rooms.authenticate(owner.room.id, luna_player.access_token)

    # Ended historical Session with a message and a resolved roll.
    history = s.sessions.start_session(owner.room.id, campaign.id, dm_context)
    history_ids = {"room_id": owner.room.id, "campaign_id": campaign.id, "session_id": history.id}
    s.actions.send(
        s.human(history_ids, mira_context),
        ExplorationInputRequest(
            kind=ExplorationInputKind.ACTION, text="Last week we opened the gate.",
            subject_seat_id=mira_seat.id,
        ),
    )
    _group, (old_request,) = s.rolls.request_check(
        s.human(history_ids, dm_context),
        RequestCheckInput(
            target_seat_ids=(mira_seat.id,), request_type=RollRequestType.OTHER,
            dc=10, label="Old gate", idempotency_key="p3f-rs-old-check",
        ),
    )
    s.rolls.complete_formal(
        s.human(history_ids, mira_context),
        FormalRollInput(roll_request_id=old_request.id, idempotency_key="p3f-rs-old-roll"),
    )
    s.sessions.end_session(owner.room.id, campaign.id, history.id, dm_context)

    # Active Session.
    started = s.sessions.start_session(owner.room.id, campaign.id, dm_context)
    ids = {
        "room_id": owner.room.id,
        "campaign_id": campaign.id,
        "session_id": started.id,
        "history_session_id": history.id,
        "dm_seat_id": dm_seat.id,
        "mira_seat_id": mira_seat.id,
        "luna_seat_id": luna_seat.id,
        "luna_character_id": luna.id,
        "dm_token": dm.access_token,
        "mira_token": mira_player.access_token,
        "luna_token": luna_player.access_token,
        "luna_access_session_id": luna_player.access_session_id,
    }
    dm_actor = s.human(ids, dm_context)
    mira_actor = s.human(ids, mira_context)

    stage = s.stage.replace_stage(
        dm_actor,
        StageUpdateRequest(
            expected_revision=0, text="A flooded crypt", image=_png_upload(),
            idempotency_key="p3f-rs-stage",
        ),
    )
    ids["stage_image_id"] = stage.image_id
    ids["stage_revision"] = stage.revision

    s.actions.send(
        mira_actor,
        ExplorationInputRequest(
            kind=ExplorationInputKind.ACTION, text="I wade toward the sarcophagus.",
            subject_seat_id=mira_seat.id,
        ),
    )
    s.actions.send(
        mira_actor,
        ExplorationInputRequest(kind=ExplorationInputKind.WHISPER_DM, text="I hid the amulet."),
    )
    s.events.append_event(
        dm_actor,
        TableEventAppend(
            kind="diagnostic.dm_note", visibility=TableEventVisibility.DM_ONLY,
            payload={"note": "the amulet is cursed"}, idempotency_key="p3f-rs-dm-note",
        ),
    )

    # One resolved and one pending RollRequest, plus a PendingAction bound to a roll.
    _group, (resolved_request,) = s.rolls.request_check(
        dm_actor,
        RequestCheckInput(
            target_seat_ids=(mira_seat.id,), request_type=RollRequestType.OTHER,
            dc=13, label="Mira notices", idempotency_key="p3f-rs-resolved-check",
        ),
    )
    resolved = s.rolls.complete_formal(
        mira_actor,
        FormalRollInput(roll_request_id=resolved_request.id, idempotency_key="p3f-rs-resolved-roll"),
    )
    _group, (pending_request,) = s.rolls.request_check(
        dm_actor,
        RequestCheckInput(
            target_seat_ids=(luna_seat.id,), request_type=RollRequestType.OTHER,
            dc=15, visibility=RollVisibility.ROLLER_AND_DM, label="Luna listens",
            idempotency_key="p3f-rs-pending-check",
        ),
    )
    pending_action = s.pending.create(
        mira_actor,
        PendingActionCreateInput(
            subject_seat_id=mira_seat.id, text="inspect the sarcophagus lid",
            idempotency_key="p3f-rs-pending-action",
        ),
    )
    _group, (bound_request,) = s.rolls.request_check(
        dm_actor,
        RequestCheckInput(
            target_seat_ids=(mira_seat.id,), request_type=RollRequestType.OTHER,
            dc=14, label="Lid inspection", idempotency_key="p3f-rs-bound-check",
        ),
    )
    waiting = s.pending.transition(
        dm_actor,
        pending_action.id,
        PendingActionTransitionInput(
            expected_version=pending_action.version,
            to_status=PendingActionStatus.WAITING_FOR_ROLL,
            roll_request_id=bound_request.id,
            idempotency_key="p3f-rs-pending-bind",
        ),
    )
    assert waiting.status is PendingActionStatus.WAITING_FOR_ROLL

    # Luna Player hands off to AI with a Temporary Instruction.
    grant = s.controllers.let_ai_control_player(
        room_id=owner.room.id, campaign_id=campaign.id, session_id=started.id,
        seat_id=luna_seat.id, context=luna_context,
        request=AIHandoffRequest(temporary_instruction="Stay near Mira and avoid combat."),
    )
    ai_auth = s.controllers.authenticate(grant.token)

    # Unbound pre-session AI DM grant lives in a second Room with no active Session.
    owner2 = s.rooms.create_room(CreateRoomRequest(name="P3-F Pre-session", password="secret"))
    campaign2 = s.campaigns.create_campaign(
        owner2.room.id, CampaignCreate(name="Campaign 2", ruleset="dnd5e-2014"),
    )
    s.campaigns.set_status(owner2.room.id, campaign2.id, CampaignStatus.ACTIVE)
    s.campaigns.select_campaign(owner2.room.id, campaign2.id)
    dm_seat2 = s.seats.create_seat(owner2.room.id, campaign2.id, SeatCreate(role=SeatRole.DM))
    pre_session = s.controllers.configure_pre_session_ai_dm(
        room_id=owner2.room.id, campaign_id=campaign2.id, seat_id=dm_seat2.id, ttl=PRE_SESSION_TTL,
    )

    dm_history = s.events.list_after(dm_actor, after_seq=0, limit=100)
    ids.update(
        {
            "cursor": dm_history.cursor,
            "dm_kinds": [item.kind for item in dm_history.events],
            "resolved_request_id": resolved_request.id,
            "resolved_result_id": resolved.id,
            "resolved_total": resolved.total,
            "pending_request_id": pending_request.id,
            "bound_request_id": bound_request.id,
            "pending_action_id": pending_action.id,
            "pending_action_version": waiting.version,
            "ai_token": grant.token,
            "ai_grant_id": grant.grant_id,
            "ai_generation": grant.generation,
            "luna_epoch": s.seat_epoch(luna_seat.id),
            "ai_auth": ai_auth,
            "pre_session_token": pre_session.token,
            "pre_session_grant_id": pre_session.grant_id,
            "pre_session_expires_at": pre_session.expires_at,
            "room2_id": owner2.room.id,
        }
    )
    return ids


def test_p3_runtime_recovers_from_canonical_postgres_after_process_restart(
    migrated_postgres_url: str,
) -> None:
    first = _Services(create_engine(migrated_postgres_url))
    try:
        ids = _build_dataset(first)
    finally:
        # Model a full process restart: no engine, pool, notifier, or service
        # object survives; everything below is rebuilt from PostgreSQL only.
        first.engine.dispose()
        del first

    s = _Services(create_engine(migrated_postgres_url))
    try:
        dm_context = s.rooms.authenticate(ids["room_id"], ids["dm_token"])
        mira_context = s.rooms.authenticate(ids["room_id"], ids["mira_token"])
        luna_context = s.rooms.authenticate(ids["room_id"], ids["luna_token"])
        dm = s.human(ids, dm_context)
        mira = s.human(ids, mira_context)

        # Cursor continues; nothing was reset or replayed.
        dm_history = s.events.list_after(dm, after_seq=0, limit=100)
        assert dm_history.cursor == ids["cursor"]
        assert [item.kind for item in dm_history.events] == ids["dm_kinds"]
        assert s.events.list_after(dm, after_seq=ids["cursor"], limit=100).events == []

        # Stage text + image survive and remain readable.
        stage = s.stage.get_stage(dm)
        assert stage.text == "A flooded crypt"
        assert stage.revision == ids["stage_revision"]
        assert stage.image_id == ids["stage_image_id"]
        image = s.stage.get_image(mira, ids["stage_image_id"])
        assert image.media_type == "image/png"
        assert base64.b64encode(image.data).decode("ascii") == _png_upload().data_base64

        # Visibility is still enforced from canonical rows.
        mira_kinds = [item.kind for item in s.events.list_after(mira, after_seq=0, limit=100).events]
        assert "exploration.whisper_dm" in mira_kinds
        assert "diagnostic.dm_note" not in mira_kinds
        assert "diagnostic.dm_note" in ids["dm_kinds"]

        # Resolved stays resolved with the same result; pending stays pending.
        requests = {item.id: item for item in s.rolls.list_requests(dm)}
        assert requests[ids["resolved_request_id"]].status == "resolved"
        assert requests[ids["pending_request_id"]].status == "pending"
        assert requests[ids["bound_request_id"]].status == "pending"
        # A second completion returns the canonical result instead of re-rolling.
        again = s.rolls.complete_formal(
            mira,
            FormalRollInput(
                roll_request_id=ids["resolved_request_id"],
                idempotency_key="p3f-rs-resolved-roll-again",
            ),
        )
        assert again.id == ids["resolved_result_id"]
        assert again.total == ids["resolved_total"]
        with s.engine.connect() as connection:
            results = connection.execute(
                select(roll_results.c.id, roll_results.c.total).where(
                    roll_results.c.roll_request_id == ids["resolved_request_id"]
                )
            ).all()
        assert [(row.id, row.total) for row in results] == [
            (ids["resolved_result_id"], ids["resolved_total"])
        ]

        # PendingAction still waits for its bound roll.
        pending = {item.id: item for item in s.pending.list(dm)}[ids["pending_action_id"]]
        assert pending.status is PendingActionStatus.WAITING_FOR_ROLL
        assert pending.roll_request_id == ids["bound_request_id"]
        assert pending.version == ids["pending_action_version"]

        # Human Seat epoch and AI grant generation / session binding / instruction
        # are rebuilt from Seat current grant id + controller_epoch, not memory.
        assert s.seat_epoch(ids["luna_seat_id"]) == ids["luna_epoch"] == ids["ai_generation"]
        auth = s.controllers.authenticate(ids["ai_token"])
        assert auth == ids["ai_auth"]
        assert auth.session_id == ids["session_id"]
        assert auth.temporary_instruction == "Stay near Mira and avoid combat."
        ai = s.controllers.resolve_actor(ids["ai_token"])
        s.events.require_actor_current(ai)
        ai_kinds = [item.kind for item in s.events.list_after(ai, after_seq=0, limit=100).events]
        assert "exploration.whisper_dm" not in ai_kinds
        assert "diagnostic.dm_note" not in ai_kinds
        assert "roll.requested" in ai_kinds
        stored_grant = s.grants.get(ids["ai_grant_id"])
        assert stored_grant is not None
        assert stored_grant.handoff_return_access_session_id == ids["luna_access_session_id"]

        # Handoff return identity is still the exact origin access session.
        with pytest.raises((AIControllerHandoffError, AIControllerUnauthorizedError)):
            s.controllers.take_back_player(
                room_id=ids["room_id"], campaign_id=ids["campaign_id"],
                session_id=ids["session_id"], seat_id=ids["luna_seat_id"], context=mira_context,
            )
        assert s.controllers.authenticate(ids["ai_token"]).generation == ids["ai_generation"]
        s.controllers.take_back_player(
            room_id=ids["room_id"], campaign_id=ids["campaign_id"],
            session_id=ids["session_id"], seat_id=ids["luna_seat_id"], context=luna_context,
        )
        assert s.seat_epoch(ids["luna_seat_id"]) == ids["luna_epoch"] + 1
        with pytest.raises(AIControllerUnauthorizedError):
            s.controllers.authenticate(ids["ai_token"])
        luna = s.human(ids, luna_context)
        assert luna.controlled_seat_ids == (ids["luna_seat_id"],)

        # Unbound pre-session TTL comes from the persisted timestamp only.
        pre_session = s.grants.get(ids["pre_session_grant_id"])
        assert pre_session is not None
        assert pre_session.session_id is None
        assert pre_session.pre_session_expires_at == ids["pre_session_expires_at"]
        pre_auth = s.controllers.authenticate(ids["pre_session_token"])
        assert pre_auth.session_id is None
        assert pre_auth.room_id == ids["room2_id"]
        with pytest.raises(AIControllerUnauthorizedError):
            s.controllers.actor_from_auth(pre_auth)

        # Ended historical Session keeps its messages and rolls.
        history = s.sessions.repository.get(ids["history_session_id"])
        assert history is not None
        assert history.status == "ended"
        with s.engine.connect() as connection:
            message_count = connection.scalar(
                select(func.count()).select_from(session_messages).where(
                    session_messages.c.session_id == ids["history_session_id"]
                )
            )
            result_count = connection.scalar(
                select(func.count()).select_from(roll_results).where(
                    roll_results.c.session_id == ids["history_session_id"]
                )
            )
        assert message_count == 1
        assert result_count == 1
    finally:
        s.engine.dispose()
