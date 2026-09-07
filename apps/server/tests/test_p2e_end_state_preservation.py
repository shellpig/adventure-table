from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool

from app.content import load_default_content_registry
from app.db import metadata
from app.domain.character.fixture import build_p0_fighter_wizard_fixture, build_p0_fighter_wizard_state
from app.domain.character.schemas import (
    ConditionState,
    PreparedSpellSelection,
    ResourceCounter,
    SpellcastingProfile,
)
from app.domain.rooms.campaigns import CampaignCreate, CampaignService, CampaignStatus, RosterAdd
from app.domain.rooms.schemas import CreateRoomRequest, EnterRoomRequest
from app.domain.rooms.seats import ControllerKind, SeatControllerPatch, SeatCreate, SeatRole, SeatService
from app.domain.rooms.service import RoomService
from app.domain.rooms.sessions import SessionService, SessionStatus
from app.persistence.characters import CharacterRepository
from app.persistence.rooms.campaigns import CampaignRepository
from app.persistence.rooms.repository import RoomRepository
from app.persistence.rooms.seats import SeatRepository
from app.persistence.rooms.sessions import SessionRepository
from app.persistence.rooms.workspace import RoomWorkspaceRepository


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


def test_end_session_preserves_exact_rich_character_state_and_history() -> None:
    engine = _engine()
    try:
        registry = load_default_content_registry()
        rooms = RoomService(RoomRepository(engine))
        owner = rooms.create_room(
            CreateRoomRequest(name="P2-E rich state", password="secret", display_name="Owner")
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

        base_build = build_p0_fighter_wizard_fixture()
        wizard_ref = "srd5.1:class:wizard"
        wizard_profile_id = "class:srd5.1:class:wizard"
        build = base_build.model_copy(
            update={
                "spellcasting_profiles": (
                    SpellcastingProfile(
                        profile_id=wizard_profile_id,
                        source_type="class",
                        source_key=wizard_ref,
                        class_ref=wizard_ref,
                        ability="intelligence",
                        access_model="spellbook",
                        resource_pool_type="normal_multiclass_slots",
                        max_spell_level=3,
                        prepared_limit=8,
                    ),
                )
            }
        )
        characters = CharacterRepository(engine, registry)
        mira = characters.create_character(
            name="Mira",
            build=build,
            state=build_p0_fighter_wizard_state(build),
        )
        RoomWorkspaceRepository(engine).attach_character(
            room_id=owner.room.id,
            character_id=mira.id,
        )

        campaigns = CampaignService(CampaignRepository(engine))
        campaign = campaigns.create_campaign(
            owner.room.id,
            CampaignCreate(name="Campaign", ruleset="dnd5e-2014"),
        )
        campaigns.set_status(owner.room.id, campaign.id, CampaignStatus.ACTIVE)
        campaigns.select_campaign(owner.room.id, campaign.id)
        campaigns.add_character(
            owner.room.id,
            campaign.id,
            RosterAdd(character_id=mira.id),
        )

        seats = SeatService(SeatRepository(engine))
        dm_seat = seats.create_seat(owner.room.id, campaign.id, SeatCreate(role=SeatRole.DM))
        seats.set_controller(
            owner.room.id,
            campaign.id,
            dm_seat.id,
            SeatControllerPatch(
                controller_kind=ControllerKind.HUMAN,
                controller_access_session_id=dm.access_session_id,
            ),
        )
        player_seat = seats.create_seat(
            owner.room.id,
            campaign.id,
            SeatCreate(role=SeatRole.PLAYER, label="Mira"),
        )
        seats.select_character(owner.room.id, campaign.id, player_seat.id, mira.id)

        sessions = SessionService(SessionRepository(engine))
        dm_context = rooms.authenticate(owner.room.id, dm.access_token)
        started = sessions.start_session(owner.room.id, campaign.id, dm_context)
        assert sessions.repository.lease_for_character(mira.id) is not None

        # Make a non-trivial, fully valid live-state mutation while the Session is active.
        # This fixture is not an Artificer, so active_infusions / feature_modes /
        # spell_storing_item intentionally remain their valid non-applicable values.
        current = characters.load_character(mira.id)
        inventory = [
            entry.model_copy(update={"quantity": 1})
            if entry.entry_id == "inventory:healing-potion"
            else entry
            for entry in current.state.inventory_state
        ]
        rich_state = current.state.model_copy(
            update={
                "current_hp": 41,
                "temporary_hp": 7,
                "conditions": [
                    ConditionState(
                        condition_ref="srd5.1:condition:poisoned",
                        note="P2-E preservation fixture",
                    )
                ],
                "prepared_spell_entry_ids": [],
                "prepared_spells": [
                    PreparedSpellSelection(
                        spell_key="srd5.1:spell:shield",
                        source_profile_id=wizard_profile_id,
                        source_access_entry_id="wizard:shield",
                    ),
                    PreparedSpellSelection(
                        spell_key="srd5.1:spell:detect-magic",
                        source_profile_id=wizard_profile_id,
                        source_access_entry_id="wizard:detect-magic",
                    ),
                ],
                "spell_slots": {
                    1: ResourceCounter(used=2, remaining=2),
                    2: ResourceCounter(used=1, remaining=2),
                    3: ResourceCounter(used=2, remaining=0),
                },
                "resources": {
                    "wizard:arcane-recovery": ResourceCounter(used=1, remaining=0),
                },
                "hit_dice_state": {"d10": 3, "d6": 2},
                "inventory_state": inventory,
            }
        )
        updated = characters.save_state(
            mira.id,
            rich_state,
            expected_current_version_id=current.current_version_id,
        )
        state_immediately_before_end = updated.state.model_dump(mode="json")

        # Guard against a vacuous equality test: every rich P2 field applicable to
        # this Fighter/Wizard fixture is populated and changed before End.
        assert state_immediately_before_end["current_hp"] == 41
        assert state_immediately_before_end["temporary_hp"] == 7
        assert state_immediately_before_end["conditions"]
        assert state_immediately_before_end["prepared_spells"]
        assert state_immediately_before_end["spell_slots"]
        assert state_immediately_before_end["resources"]
        assert state_immediately_before_end["hit_dice_state"] == {"d10": 3, "d6": 2}
        assert state_immediately_before_end["inventory_state"]

        ended = sessions.end_session(
            owner.room.id,
            campaign.id,
            started.id,
            dm_context,
        )
        assert ended.status is SessionStatus.ENDED

        state_after_end = characters.load_character(mira.id).state.model_dump(mode="json")
        assert state_after_end == state_immediately_before_end
        assert sessions.repository.lease_for_character(mira.id) is None

        participants = sessions.repository.list_participants(started.id)
        mira_participant = next(
            participant for participant in participants if participant.active_character_id == mira.id
        )
        assert mira_participant.seat_id == player_seat.id
        assert SeatRepository(engine).get(player_seat.id) is not None
        assert sessions.repository.get(started.id).status == "ended"
    finally:
        engine.dispose()
