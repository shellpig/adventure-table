from __future__ import annotations

from datetime import datetime, timezone
from typing import cast
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.domain.adventures.schemas import (
    AdventureAlreadyAttachedError,
    AdventureNotFinalizedError,
    AdventureNotFoundError,
    AdventureStatus,
    AttachedAdventure,
    CampaignAdventureAttach,
    CampaignAdventureDetachBlockedError,
    CampaignAdventureLinkNotFoundError,
)
from app.domain.adventures.service import require_adventure_author
from app.domain.rooms.campaigns import CampaignNotFoundError
from app.domain.rooms.schemas import RoomAccessContext
from app.persistence.adventures.repository import (
    AdventureRepository,
    CampaignAdventureLinkRepository,
    StoredAdventureDefinition,
    StoredCampaignAdventureLink,
)
from app.persistence.campaign_runtime.repository import CampaignRuntimeRepository
from app.persistence.rooms.campaigns import CampaignRepository, StoredCampaign


def _attached_view(
    link: StoredCampaignAdventureLink, definition: StoredAdventureDefinition
) -> AttachedAdventure:
    return AttachedAdventure(
        campaign_id=link.campaign_id,
        adventure_id=link.adventure_id,
        sort_order=link.sort_order,
        attached_at=link.attached_at,
        name=definition.name,
        summary=definition.summary,
        status=cast(AdventureStatus, definition.status),
    )


class CampaignAdventureService:
    def __init__(
        self,
        link_repository: CampaignAdventureLinkRepository,
        adventure_repository: AdventureRepository,
        campaign_repository: CampaignRepository,
    ) -> None:
        self.link_repository = link_repository
        self.adventure_repository = adventure_repository
        self.campaign_repository = campaign_repository

    def _campaign_or_404(self, room_id: UUID, campaign_id: UUID) -> StoredCampaign:
        campaign = self.campaign_repository.get(campaign_id)
        if campaign is None or campaign.room_id != room_id:
            raise CampaignNotFoundError(f"Campaign {campaign_id} not found in room {room_id}")
        return campaign

    def attach(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        campaign_id: UUID,
        payload: CampaignAdventureAttach,
    ) -> AttachedAdventure:
        require_adventure_author(context, room_id)
        self._campaign_or_404(room_id, campaign_id)
        definition = self.adventure_repository.get_definition(room_id, payload.adventure_id)
        if definition is None:
            raise AdventureNotFoundError(
                f"Adventure {payload.adventure_id} not found in room {room_id}"
            )
        if definition.status != "finalized":
            raise AdventureNotFinalizedError(
                f"Cannot attach adventure in '{definition.status}' status; only finalized can be attached"
            )
        if self.link_repository.is_attached(campaign_id, payload.adventure_id):
            raise AdventureAlreadyAttachedError(
                f"Adventure {payload.adventure_id} is already attached to campaign {campaign_id}"
            )
        sort_order = self.link_repository.next_sort_order(campaign_id)
        now = datetime.now(timezone.utc)
        stored = StoredCampaignAdventureLink(
            campaign_id=campaign_id,
            adventure_id=payload.adventure_id,
            sort_order=sort_order,
            attached_at=now,
        )
        try:
            self.link_repository.attach(stored)
        except IntegrityError as exc:
            raise AdventureAlreadyAttachedError(
                f"Adventure {payload.adventure_id} is already attached to campaign {campaign_id}"
            ) from exc
        return _attached_view(stored, definition)

    def detach(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        campaign_id: UUID,
        adventure_id: UUID,
    ) -> None:
        require_adventure_author(context, room_id)
        with self.campaign_repository.engine.begin() as connection:
            campaign = self.campaign_repository.get_for_update_in_transaction(
                connection, campaign_id
            )
            if campaign is None or campaign.room_id != room_id:
                raise CampaignNotFoundError(
                    f"Campaign {campaign_id} not found in room {room_id}"
                )

            if not self.link_repository.is_attached_in_transaction(
                connection, campaign_id, adventure_id
            ):
                raise CampaignAdventureLinkNotFoundError(
                    f"Adventure {adventure_id} is not attached to campaign {campaign_id}"
                )

            if CampaignRuntimeRepository.has_active_overrides_for_adventure_in_transaction(
                connection, campaign_id, adventure_id
            ):
                raise CampaignAdventureDetachBlockedError(
                    campaign_id=campaign_id,
                    adventure_id=adventure_id,
                    reason="active overrides exist for this adventure",
                )

            if CampaignRuntimeRepository.has_current_adventure_scene_in_transaction(
                connection, campaign_id, adventure_id
            ):
                raise CampaignAdventureDetachBlockedError(
                    campaign_id=campaign_id,
                    adventure_id=adventure_id,
                    reason="current adventure scene points to this adventure",
                )

            deleted = self.link_repository.detach_in_transaction(
                connection, campaign_id, adventure_id
            )
            if not deleted:
                raise CampaignAdventureLinkNotFoundError(
                    f"Adventure {adventure_id} is not attached to campaign {campaign_id}"
                )

    def list(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        campaign_id: UUID,
    ) -> list[AttachedAdventure]:
        require_adventure_author(context, room_id)
        self._campaign_or_404(room_id, campaign_id)
        # attach() only links same-Room finalized Adventures and the FK is RESTRICT,
        # so every link resolves to a definition of this Room.
        definitions = {d.id: d for d in self.adventure_repository.list_definitions(room_id)}
        return [
            _attached_view(link, definitions[link.adventure_id])
            for link in self.link_repository.list_for_campaign(campaign_id)
        ]


__all__ = ["CampaignAdventureService"]
