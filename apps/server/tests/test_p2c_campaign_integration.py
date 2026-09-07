from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool

from app.api.errors import APIError
from app.api.rooms.dependencies import _HistoryGuardedCharacterRepository
from app.content import load_default_content_registry
from app.db import metadata
from app.domain.character.fixture import (
    build_p0_fighter_wizard_fixture,
    build_p0_fighter_wizard_state,
)
from app.domain.character.schemas import ResourceCounter
from app.domain.rooms.campaigns import (
    CampaignCreate,
    CampaignNotFoundError,
    CampaignService,
    CharacterNotInRoomError,
    RosterAdd,
    RosterStatus,
)
from app.domain.rooms.schemas import CreateRoomRequest
from app.domain.rooms.service import RoomService
from app.persistence.characters import CharacterRepository
from app.persistence.rooms.campaigns import CampaignRepository
from app.persistence.rooms.repository import RoomRepository
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


def test_real_campaign_rosters_share_one_character_state_and_preserve_history() -> None:
    engine = _engine()
    registry = load_default_content_registry()
    room_repository = RoomRepository(engine)
    room_service = RoomService(room_repository)
    room_a = room_service.create_room(CreateRoomRequest(name="Room A", password="secret-a"))
    room_b = room_service.create_room(CreateRoomRequest(name="Room B", password="secret-b"))
    workspace = RoomWorkspaceRepository(engine)
    character_repository = CharacterRepository(engine, registry)
    campaign_repository = CampaignRepository(engine)
    campaign_service = CampaignService(campaign_repository)
    build = build_p0_fighter_wizard_fixture()
    state = build_p0_fighter_wizard_state(build)

    try:
        mira = character_repository.create_character(name="Mira", build=build, state=state)
        other = character_repository.create_character(name="Other", build=build, state=state)
        workspace.attach_character(room_id=room_a.room.id, character_id=mira.id)
        workspace.attach_character(room_id=room_b.room.id, character_id=other.id)

        campaign_a = campaign_service.create_campaign(
            room_a.room.id,
            CampaignCreate(name="Campaign A", ruleset="dnd5e-2014"),
        )
        campaign_b = campaign_service.create_campaign(
            room_a.room.id,
            CampaignCreate(name="Campaign B", ruleset="dnd5e-2014"),
        )
        foreign_campaign = campaign_service.create_campaign(
            room_b.room.id,
            CampaignCreate(name="Foreign", ruleset="dnd5e-2014"),
        )

        with pytest.raises(CampaignNotFoundError):
            campaign_service.select_campaign(room_a.room.id, foreign_campaign.id)
        assert room_repository.get_room(room_a.room.id).active_campaign_id is None

        campaign_service.select_campaign(room_a.room.id, campaign_a.id)
        assert room_repository.get_room(room_a.room.id).active_campaign_id == campaign_a.id

        first = campaign_service.add_character(
            room_a.room.id,
            campaign_a.id,
            RosterAdd(character_id=mira.id),
        )
        duplicate = campaign_service.add_character(
            room_a.room.id,
            campaign_a.id,
            RosterAdd(character_id=mira.id),
        )
        second_campaign = campaign_service.add_character(
            room_a.room.id,
            campaign_b.id,
            RosterAdd(character_id=mira.id),
        )
        assert duplicate == first
        assert second_campaign.character_id == mira.id
        with pytest.raises(CharacterNotInRoomError):
            campaign_service.add_character(
                room_a.room.id,
                campaign_a.id,
                RosterAdd(character_id=other.id),
            )

        inventory = [
            entry.model_copy(update={"quantity": 1})
            if entry.entry_id == "inventory:healing-potion"
            else entry
            for entry in mira.state.inventory_state
        ]
        mutated_state = mira.state.model_copy(
            update={
                "current_hp": 41,
                "inventory_state": inventory,
                "prepared_spell_entry_ids": [
                    "wizard:magic-missile",
                    "wizard:shield",
                ],
                "resources": {
                    "wizard:arcane-recovery": ResourceCounter(used=1, remaining=0),
                },
            }
        )
        character_repository.save_state(mira.id, mutated_state)

        roster_a = campaign_service.list_roster(room_a.room.id, campaign_a.id)
        roster_b = campaign_service.list_roster(room_a.room.id, campaign_b.id)
        seen_from_a = character_repository.load_character(roster_a[0].character_id)
        seen_from_b = character_repository.load_character(roster_b[0].character_id)
        for seen in (seen_from_a, seen_from_b):
            assert seen.id == mira.id
            assert seen.state.current_hp == 41
            assert seen.state.inventory_state == inventory
            assert seen.state.prepared_spell_entry_ids == [
                "wizard:magic-missile",
                "wizard:shield",
            ]
            assert seen.state.resources["wizard:arcane-recovery"] == ResourceCounter(
                used=1,
                remaining=0,
            )

        retired = campaign_service.update_roster_status(
            room_a.room.id,
            campaign_a.id,
            mira.id,
            RosterStatus.RETIRED,
        )
        assert retired.status is RosterStatus.RETIRED
        assert (
            campaign_service.list_roster(room_a.room.id, campaign_a.id)[0].status
            is RosterStatus.RETIRED
        )

        character_repository.set_archived(mira.id, True)
        assert (
            campaign_service.list_roster(room_a.room.id, campaign_a.id)[0].character_id
            == mira.id
        )
        guarded = _HistoryGuardedCharacterRepository(character_repository, campaign_repository)
        with pytest.raises(APIError) as exc:
            guarded.delete_character(mira.id)
        assert exc.value.code == "character_history_referenced"

        disposable = campaign_service.create_campaign(
            room_a.room.id,
            CampaignCreate(name="Disposable Draft", ruleset="dnd5e-2014"),
        )
        campaign_service.delete_draft(room_a.room.id, disposable.id)
        with pytest.raises(CampaignNotFoundError):
            campaign_service.get_campaign(room_a.room.id, disposable.id)
    finally:
        engine.dispose()
