from __future__ import annotations

import base64
from typing import Annotated, Literal, cast
from uuid import UUID

from pydantic import Field

from app.domain.room_assets.schemas import RoomAssetNotFoundError
from app.domain.room_assets.service import RoomAssetService
from app.domain.rooms.exploration import (
    SUPPORTED_STAGE_IMAGE_TYPES,
    ExplorationStageService,
    StageImageUpload,
    StageState,
    StageUpdateRequest,
)
from app.domain.rooms.schemas import StrictModel
from app.domain.rooms.table_events import (
    TableActorContext,
    TableEventActorUnauthorizedError,
    TableEventNotFoundError,
    TableEventService,
    TableEventSessionNotActiveError,
)
from app.persistence.adventures.repository import (
    AdventureRepository,
    CampaignAdventureLinkRepository,
)
from app.persistence.campaign_runtime.repository import CampaignRuntimeRepository
from app.persistence.rooms.table_runtime import (
    TableEventActorBindingStalePersistenceError,
    TableEventSessionNotActivePersistenceError,
    TableEventSessionNotFoundPersistenceError,
)


class CampaignStageError(Exception):
    """Base exception for campaign stage bridge errors."""


class StageSourceNotFoundError(CampaignStageError, LookupError):
    """Raised when the specified stage image source cannot be found or is not attached."""


class StageSourceInvalidError(CampaignStageError, ValueError):
    """Raised when the stage image source kind or format is invalid."""


class RoomAssetStageSource(StrictModel):
    kind: Literal["room_asset"] = "room_asset"
    asset_id: UUID


class AdventureEntryAssetStageSource(StrictModel):
    kind: Literal["adventure_entry_asset"] = "adventure_entry_asset"
    adventure_id: UUID
    adventure_entry_id: UUID
    asset_id: UUID


class RuntimeEntryImageStageSource(StrictModel):
    kind: Literal["runtime_entry_image"] = "runtime_entry_image"
    runtime_entry_id: UUID
    adventure_id: UUID
    asset_id: UUID


StageImageSource = Annotated[
    RoomAssetStageSource | AdventureEntryAssetStageSource | RuntimeEntryImageStageSource,
    Field(discriminator="kind"),
]


class CampaignStageBridgeService:
    def __init__(
        self,
        *,
        room_asset_service: RoomAssetService,
        adventure_repository: AdventureRepository,
        campaign_adventure_link_repository: CampaignAdventureLinkRepository,
        campaign_runtime_repository: CampaignRuntimeRepository,
        stage_service: ExplorationStageService,
        table_event_service: TableEventService,
    ) -> None:
        self.room_asset_service = room_asset_service
        self.adventure_repository = adventure_repository
        self.link_repository = campaign_adventure_link_repository
        self.campaign_runtime_repository = campaign_runtime_repository
        self.stage_service = stage_service
        self.table_event_service = table_event_service

    def _require_active_dm_authority(self, actor: TableActorContext) -> None:
        if not actor.is_current_dm:
            raise TableEventActorUnauthorizedError(
                "Only the current Session DM can update Main Stage"
            )
        try:
            binding = TableEventService._stored_binding(actor)
        except TableEventActorUnauthorizedError:
            raise
        with self.table_event_service.repository.engine.connect() as connection:
            try:
                self.table_event_service.repository.require_active_actor_in_transaction(
                    connection, binding
                )
            except TableEventSessionNotFoundPersistenceError as exc:
                raise TableEventNotFoundError(str(actor.session_id)) from exc
            except TableEventSessionNotActivePersistenceError as exc:
                raise TableEventSessionNotActiveError(str(actor.session_id)) from exc
            except TableEventActorBindingStalePersistenceError as exc:
                raise TableEventActorUnauthorizedError(str(exc)) from exc

    def set_stage_image(
        self,
        actor: TableActorContext,
        source: StageImageSource,
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> StageState:
        self._require_active_dm_authority(actor)

        target_asset_id: UUID
        if isinstance(source, RoomAssetStageSource):
            target_asset_id = source.asset_id
        elif isinstance(source, AdventureEntryAssetStageSource):
            if not self.link_repository.is_attached(actor.campaign_id, source.adventure_id):
                raise StageSourceNotFoundError(
                    f"Adventure {source.adventure_id} is not attached to campaign {actor.campaign_id}"
                )
            adv_def = self.adventure_repository.get_definition(actor.room_id, source.adventure_id)
            if adv_def is None:
                raise StageSourceNotFoundError(
                    f"Adventure {source.adventure_id} not found in room {actor.room_id}"
                )
            adv_entry = self.adventure_repository.get_entry(
                source.adventure_id, source.adventure_entry_id
            )
            if adv_entry is None:
                raise StageSourceNotFoundError(
                    f"Adventure entry {source.adventure_entry_id} not found in adventure {source.adventure_id}"
                )
            entry_assets = self.adventure_repository.list_entry_assets(source.adventure_id)
            matching_links = [
                ea
                for ea in entry_assets
                if ea.adventure_entry_id == source.adventure_entry_id and ea.asset_id == source.asset_id
            ]
            if not matching_links:
                raise StageSourceNotFoundError(
                    f"Asset {source.asset_id} is not linked to adventure entry {source.adventure_entry_id}"
                )
            if not any(ea.role in ("image", "map") for ea in matching_links):
                raise StageSourceInvalidError(
                    f"Asset {source.asset_id} linked to adventure entry {source.adventure_entry_id} has non-image/map role(s): {[ea.role for ea in matching_links]}"
                )
            target_asset_id = source.asset_id
        elif isinstance(source, RuntimeEntryImageStageSource):
            entry_agg = self.campaign_runtime_repository.get_entry(
                actor.campaign_id, source.runtime_entry_id, include_archived=False
            )
            if entry_agg is None:
                raise StageSourceNotFoundError(
                    f"Runtime entry {source.runtime_entry_id} not found in campaign {actor.campaign_id}"
                )
            runtime_entry = entry_agg.entry
            if runtime_entry.source_adventure_entry_id is None:
                raise StageSourceNotFoundError(
                    f"Runtime entry {source.runtime_entry_id} has no source adventure entry"
                )
            if not self.link_repository.is_attached(actor.campaign_id, source.adventure_id):
                raise StageSourceNotFoundError(
                    f"Adventure {source.adventure_id} is not attached to campaign {actor.campaign_id}"
                )
            adv_def = self.adventure_repository.get_definition(actor.room_id, source.adventure_id)
            if adv_def is None:
                raise StageSourceNotFoundError(
                    f"Adventure {source.adventure_id} not found in room {actor.room_id}"
                )
            adv_entry = self.adventure_repository.get_entry(
                source.adventure_id, runtime_entry.source_adventure_entry_id
            )
            if adv_entry is None:
                raise StageSourceNotFoundError(
                    f"Source adventure entry {runtime_entry.source_adventure_entry_id} not found in adventure {source.adventure_id}"
                )
            entry_assets = self.adventure_repository.list_entry_assets(source.adventure_id)
            matching_links = [
                ea
                for ea in entry_assets
                if ea.adventure_entry_id == adv_entry.id and ea.asset_id == source.asset_id
            ]
            if not matching_links:
                raise StageSourceNotFoundError(
                    f"Asset {source.asset_id} is not linked to source entry {adv_entry.id}"
                )
            if not any(ea.role in ("image", "map") for ea in matching_links):
                raise StageSourceInvalidError(
                    f"Asset {source.asset_id} linked to source entry {adv_entry.id} has non-image/map role(s): {[ea.role for ea in matching_links]}"
                )
            target_asset_id = source.asset_id
        else:
            raise StageSourceInvalidError(
                f"Unsupported stage image source: {type(source).__name__}"
            )

        try:
            asset_view, handle = self.room_asset_service.open_content_for_table_actor(
                actor,
                self.table_event_service,
                room_id=actor.room_id,
                asset_id=target_asset_id,
            )
        except RoomAssetNotFoundError as exc:
            raise StageSourceNotFoundError(f"Room asset {target_asset_id} not found") from exc

        with handle:
            if (
                asset_view.kind != "image"
                or asset_view.mime_type not in SUPPORTED_STAGE_IMAGE_TYPES
            ):
                raise StageSourceInvalidError(
                    f"Asset {target_asset_id} is not a supported image ({asset_view.mime_type})"
                )
            data = handle.read()

        current_stage = self.stage_service.get_stage(actor)

        data_base64 = base64.b64encode(data).decode("ascii")
        media_type = cast(
            Literal["image/png", "image/jpeg", "image/webp"], asset_view.mime_type
        )
        upload = StageImageUpload(
            media_type=media_type,
            filename=asset_view.original_filename,
            data_base64=data_base64,
        )
        update_request = StageUpdateRequest(
            expected_revision=expected_revision,
            text=current_stage.text,
            image=upload,
            idempotency_key=idempotency_key,
        )
        return self.stage_service.replace_stage(actor, update_request)


__all__ = [
    "AdventureEntryAssetStageSource",
    "CampaignStageBridgeService",
    "CampaignStageError",
    "RoomAssetStageSource",
    "RuntimeEntryImageStageSource",
    "StageImageSource",
    "StageSourceInvalidError",
    "StageSourceNotFoundError",
]
