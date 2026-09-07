from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field, field_validator

from app.domain.rooms.schemas import StrictModel
from app.persistence.rooms.campaigns import (
    CampaignNotDraftPersistenceError,
    CampaignRepository,
    CampaignSessionHistoryPersistenceError,
    StoredCampaign,
    StoredRosterEntry,
)


class CampaignStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class RosterStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    RETIRED = "retired"
    DEAD = "dead"


class Campaign(StrictModel):
    id: UUID
    room_id: UUID
    name: str
    ruleset: str
    status: CampaignStatus
    created_at: datetime
    updated_at: datetime


class CampaignCreate(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    ruleset: str = Field(min_length=1, max_length=80)

    @field_validator("name", "ruleset")
    @classmethod
    def normalize_non_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value cannot be blank")
        return normalized


class CampaignStatusPatch(StrictModel):
    status: CampaignStatus


class RosterEntry(StrictModel):
    campaign_id: UUID
    character_id: UUID
    status: RosterStatus
    added_at: datetime
    updated_at: datetime


class RosterAdd(StrictModel):
    character_id: UUID
    status: RosterStatus = RosterStatus.ACTIVE


class RosterStatusPatch(StrictModel):
    status: RosterStatus


class CampaignNotFoundError(LookupError):
    pass


class CharacterNotInRoomError(LookupError):
    pass


class CampaignLifecycleError(RuntimeError):
    pass


def _campaign_view(stored: StoredCampaign) -> Campaign:
    return Campaign(
        id=stored.id,
        room_id=stored.room_id,
        name=stored.name,
        ruleset=stored.ruleset,
        status=CampaignStatus(stored.status),
        created_at=stored.created_at,
        updated_at=stored.updated_at,
    )


def _roster_view(stored: StoredRosterEntry) -> RosterEntry:
    return RosterEntry(
        campaign_id=stored.campaign_id,
        character_id=stored.character_id,
        status=RosterStatus(stored.status),
        added_at=stored.added_at,
        updated_at=stored.updated_at,
    )


class CampaignService:
    def __init__(self, repository: CampaignRepository) -> None:
        self.repository = repository

    def list_campaigns(self, room_id: UUID) -> list[Campaign]:
        return [_campaign_view(stored) for stored in self.repository.list_for_room(room_id)]

    def get_campaign(self, room_id: UUID, campaign_id: UUID) -> Campaign:
        stored = self.repository.get(campaign_id)
        if stored is None or stored.room_id != room_id:
            raise CampaignNotFoundError(str(campaign_id))
        return _campaign_view(stored)

    def create_campaign(self, room_id: UUID, payload: CampaignCreate) -> Campaign:
        return _campaign_view(
            self.repository.create(
                room_id=room_id,
                name=payload.name,
                ruleset=payload.ruleset,
                status=CampaignStatus.DRAFT.value,
            )
        )

    def set_status(
        self,
        room_id: UUID,
        campaign_id: UUID,
        status: CampaignStatus,
    ) -> Campaign:
        self.get_campaign(room_id, campaign_id)
        stored = self.repository.set_status(campaign_id, status.value)
        if stored is None:
            raise CampaignNotFoundError(str(campaign_id))
        if status is CampaignStatus.ARCHIVED:
            self.repository.clear_selection_if_campaign(campaign_id)
        return _campaign_view(stored)

    def select_campaign(self, room_id: UUID, campaign_id: UUID) -> Campaign:
        campaign = self.get_campaign(room_id, campaign_id)
        if campaign.status is CampaignStatus.ARCHIVED:
            raise CampaignLifecycleError("archived campaign cannot be selected")
        if not self.repository.select_active_campaign(
            room_id=room_id,
            campaign_id=campaign_id,
        ):
            raise CampaignNotFoundError(str(campaign_id))
        return campaign

    def clear_selection(self, room_id: UUID) -> None:
        if not self.repository.select_active_campaign(room_id=room_id, campaign_id=None):
            raise CampaignNotFoundError(str(room_id))

    def delete_draft(self, room_id: UUID, campaign_id: UUID) -> None:
        campaign = self.get_campaign(room_id, campaign_id)
        if campaign.status is not CampaignStatus.DRAFT:
            raise CampaignLifecycleError("only draft Campaigns can be hard deleted")
        try:
            deleted = self.repository.delete_draft_without_session_history(campaign_id)
        except CampaignSessionHistoryPersistenceError as exc:
            raise CampaignLifecycleError(
                "Campaign with Session history cannot be hard deleted"
            ) from exc
        except CampaignNotDraftPersistenceError as exc:
            raise CampaignLifecycleError("only draft Campaigns can be hard deleted") from exc
        if not deleted:
            raise CampaignNotFoundError(str(campaign_id))

    def list_roster(self, room_id: UUID, campaign_id: UUID) -> list[RosterEntry]:
        self.get_campaign(room_id, campaign_id)
        return [_roster_view(stored) for stored in self.repository.list_roster(campaign_id)]

    def add_character(
        self,
        room_id: UUID,
        campaign_id: UUID,
        payload: RosterAdd,
    ) -> RosterEntry:
        self.get_campaign(room_id, campaign_id)
        try:
            stored = self.repository.add_roster_entry_same_room(
                room_id=room_id,
                campaign_id=campaign_id,
                character_id=payload.character_id,
                status=payload.status.value,
            )
        except ValueError as exc:
            if str(exc) == "character_not_in_room":
                raise CharacterNotInRoomError(str(payload.character_id)) from exc
            raise
        if stored is None:
            raise CampaignNotFoundError(str(campaign_id))
        return _roster_view(stored)

    def update_roster_status(
        self,
        room_id: UUID,
        campaign_id: UUID,
        character_id: UUID,
        status: RosterStatus,
    ) -> RosterEntry:
        self.get_campaign(room_id, campaign_id)
        stored = self.repository.update_roster_status(
            campaign_id=campaign_id,
            character_id=character_id,
            status=status.value,
        )
        if stored is None:
            raise CharacterNotInRoomError(str(character_id))
        return _roster_view(stored)

    def remove_character(
        self,
        room_id: UUID,
        campaign_id: UUID,
        character_id: UUID,
    ) -> None:
        self.get_campaign(room_id, campaign_id)
        if not self.repository.remove_roster_entry(
            campaign_id=campaign_id,
            character_id=character_id,
        ):
            raise CharacterNotInRoomError(str(character_id))


__all__ = [
    "Campaign",
    "CampaignCreate",
    "CampaignLifecycleError",
    "CampaignNotFoundError",
    "CampaignService",
    "CampaignStatus",
    "CampaignStatusPatch",
    "CharacterNotInRoomError",
    "RosterAdd",
    "RosterEntry",
    "RosterStatus",
    "RosterStatusPatch",
]
