from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.api.errors import APIError
from app.api.rooms.campaigns import _require_owner, _require_roster_authority, router
from app.api.rooms.dependencies import _HistoryGuardedCharacterRepository
from app.domain.rooms.campaigns import (
    CampaignCreate,
    CampaignLifecycleError,
    CampaignService,
    CampaignStatus,
    CharacterNotInRoomError,
    RosterAdd,
    RosterStatus,
)
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.persistence.rooms.campaigns import StoredCampaign, StoredRosterEntry


def _context(authority: RoomAccessAuthority) -> RoomAccessContext:
    return RoomAccessContext(
        room_id=uuid4(),
        access_session_id=uuid4(),
        authority=authority,
    )


@pytest.mark.parametrize("authority", [RoomAccessAuthority.MEMBER, RoomAccessAuthority.DM])
def test_campaign_lifecycle_is_owner_only(authority: RoomAccessAuthority) -> None:
    with pytest.raises(APIError) as exc:
        _require_owner(_context(authority))
    assert exc.value.status_code == 403
    assert exc.value.code == "room_owner_required"
    _require_owner(_context(RoomAccessAuthority.OWNER))


def test_roster_management_allows_owner_and_dm_but_not_member() -> None:
    with pytest.raises(APIError) as exc:
        _require_roster_authority(_context(RoomAccessAuthority.MEMBER))
    assert exc.value.code == "roster_authority_required"
    _require_roster_authority(_context(RoomAccessAuthority.DM))
    _require_roster_authority(_context(RoomAccessAuthority.OWNER))


def test_campaign_router_exposes_only_p2c_surfaces() -> None:
    methods_by_path: dict[str, set[str]] = {}
    for route in router.routes:
        methods_by_path.setdefault(route.path, set()).update(route.methods or ())

    assert "POST" in methods_by_path["/api/rooms/{room_id}/campaigns"]
    assert "POST" in methods_by_path["/api/rooms/{room_id}/campaigns/{campaign_id}/select"]
    assert "POST" in methods_by_path["/api/rooms/{room_id}/campaigns/{campaign_id}/roster"]
    roster_character_path = (
        "/api/rooms/{room_id}/campaigns/{campaign_id}/roster/{character_id}"
    )
    assert {"PATCH", "DELETE"} <= methods_by_path[roster_character_path]
    assert not any(
        "/sessions" in path or "/lobby" in path or "/seats" in path
        for path in methods_by_path
    )


class _FakeCampaignRepository:
    def __init__(self, *, character_room_id=None) -> None:
        self.character_room_id = character_room_id
        self.campaign = None
        self.selected = None
        self.roster = {}
        self.clear_calls = []

    def create(self, *, room_id, name, ruleset, status):
        now = datetime.now(timezone.utc)
        self.campaign = StoredCampaign(
            id=uuid4(), room_id=room_id, name=name, ruleset=ruleset,
            status=status, created_at=now, updated_at=now,
        )
        return self.campaign

    def get(self, campaign_id):
        if self.campaign is None or self.campaign.id != campaign_id:
            return None
        return self.campaign

    def list_for_room(self, room_id):
        return (self.campaign,) if self.campaign is not None and self.campaign.room_id == room_id else ()

    def set_status(self, campaign_id, status):
        if self.campaign is None or self.campaign.id != campaign_id:
            return None
        self.campaign = StoredCampaign(
            **{**self.campaign.__dict__, "status": status, "updated_at": datetime.now(timezone.utc)}
        )
        return self.campaign

    def clear_selection_if_campaign(self, campaign_id):
        self.clear_calls.append(campaign_id)
        if self.selected == campaign_id:
            self.selected = None

    def select_active_campaign(self, *, room_id, campaign_id):
        if campaign_id is None:
            self.selected = None
            return True
        if self.campaign is not None and self.campaign.room_id == room_id:
            self.selected = campaign_id
            return True
        return False

    def delete(self, campaign_id):
        if self.campaign is None or self.campaign.id != campaign_id:
            return False
        self.campaign = None
        return True

    def list_roster(self, campaign_id):
        return tuple(self.roster.values())

    def add_roster_entry_same_room(self, *, room_id, campaign_id, character_id, status):
        if self.character_room_id != room_id:
            raise ValueError("character_not_in_room")
        key = (campaign_id, character_id)
        if key not in self.roster:
            now = datetime.now(timezone.utc)
            self.roster[key] = StoredRosterEntry(
                campaign_id=campaign_id,
                character_id=character_id,
                status=status,
                added_at=now,
                updated_at=now,
            )
        return self.roster[key]

    def update_roster_status(self, *, campaign_id, character_id, status):
        key = (campaign_id, character_id)
        old = self.roster.get(key)
        if old is None:
            return None
        updated = StoredRosterEntry(
            **{**old.__dict__, "status": status, "updated_at": datetime.now(timezone.utc)}
        )
        self.roster[key] = updated
        return updated

    def remove_roster_entry(self, *, campaign_id, character_id):
        return self.roster.pop((campaign_id, character_id), None) is not None


def test_campaign_service_separates_status_from_room_selection() -> None:
    room_id = uuid4()
    repo = _FakeCampaignRepository()
    service = CampaignService(repo)
    campaign = service.create_campaign(
        room_id,
        CampaignCreate(name="  Saltmarsh  ", ruleset=" dnd5e-2014 "),
    )
    assert campaign.name == "Saltmarsh"
    assert campaign.ruleset == "dnd5e-2014"
    assert campaign.status is CampaignStatus.DRAFT

    service.select_campaign(room_id, campaign.id)
    assert repo.selected == campaign.id
    active = service.set_status(room_id, campaign.id, CampaignStatus.ACTIVE)
    assert active.status is CampaignStatus.ACTIVE
    assert repo.selected == campaign.id

    archived = service.set_status(room_id, campaign.id, CampaignStatus.ARCHIVED)
    assert archived.status is CampaignStatus.ARCHIVED
    assert repo.selected is None


def test_same_room_roster_is_idempotent_and_status_is_roster_only() -> None:
    room_id = uuid4()
    character_id = uuid4()
    repo = _FakeCampaignRepository(character_room_id=room_id)
    service = CampaignService(repo)
    campaign = service.create_campaign(room_id, CampaignCreate(name="A", ruleset="dnd5e-2014"))

    first = service.add_character(room_id, campaign.id, RosterAdd(character_id=character_id))
    second = service.add_character(room_id, campaign.id, RosterAdd(character_id=character_id))
    assert first == second
    assert len(repo.roster) == 1

    dead = service.update_roster_status(
        room_id, campaign.id, character_id, RosterStatus.DEAD
    )
    assert dead.status is RosterStatus.DEAD
    active = service.update_roster_status(
        room_id, campaign.id, character_id, RosterStatus.ACTIVE
    )
    assert active.status is RosterStatus.ACTIVE


def test_cross_room_character_cannot_enter_roster() -> None:
    room_id = uuid4()
    repo = _FakeCampaignRepository(character_room_id=uuid4())
    service = CampaignService(repo)
    campaign = service.create_campaign(room_id, CampaignCreate(name="A", ruleset="dnd5e-2014"))
    with pytest.raises(CharacterNotInRoomError):
        service.add_character(room_id, campaign.id, RosterAdd(character_id=uuid4()))


def test_archived_campaign_cannot_be_selected_and_non_draft_cannot_hard_delete() -> None:
    room_id = uuid4()
    repo = _FakeCampaignRepository()
    service = CampaignService(repo)
    campaign = service.create_campaign(room_id, CampaignCreate(name="A", ruleset="dnd5e-2014"))
    service.set_status(room_id, campaign.id, CampaignStatus.ARCHIVED)
    with pytest.raises(CampaignLifecycleError):
        service.select_campaign(room_id, campaign.id)
    with pytest.raises(CampaignLifecycleError):
        service.delete_draft(room_id, campaign.id)


class _Delegate:
    registry = object()

    def __init__(self) -> None:
        self.deleted = []

    def delete_character(self, character_id) -> None:
        self.deleted.append(character_id)


class _History:
    def __init__(self, referenced: bool) -> None:
        self.referenced = referenced

    def character_is_referenced(self, character_id) -> bool:
        return self.referenced

    def character_is_history_referenced(self, character_id) -> bool:
        return self.referenced


def test_web_character_delete_history_guard_blocks_roster_reference() -> None:
    character_id = uuid4()
    delegate = _Delegate()
    guarded = _HistoryGuardedCharacterRepository(
        delegate,
        _History(True),
        _History(False),
    )
    with pytest.raises(APIError) as exc:
        guarded.delete_character(character_id)
    assert exc.value.status_code == 409
    assert exc.value.code == "character_history_referenced"
    assert delegate.deleted == []

    unreferenced = _HistoryGuardedCharacterRepository(
        delegate,
        _History(False),
        _History(False),
    )
    unreferenced.delete_character(character_id)
    assert delegate.deleted == [character_id]
