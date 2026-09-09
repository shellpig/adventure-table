from __future__ import annotations

import base64
import binascii
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.domain.rooms.schemas import StrictModel
from app.domain.rooms.table_events import (
    TableActorContext,
    TableActorKind,
    TableEventActorUnauthorizedError,
    TableEventService,
)
from app.persistence.rooms.exploration import (
    ExplorationRepository,
    StageImageNotFoundPersistenceError,
    StoredSessionStage,
    StoredStageImage,
)
from app.persistence.rooms.table_runtime import (
    StoredTableActorBinding,
    TableEventActorBindingStalePersistenceError,
)


MAX_STAGE_TEXT_LENGTH = 12_000
MAX_STAGE_IMAGE_BYTES = 8 * 1024 * 1024
SUPPORTED_STAGE_IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})


class StageImageUpload(StrictModel):
    media_type: Literal["image/png", "image/jpeg", "image/webp"]
    filename: str | None = Field(default=None, max_length=255)
    data_base64: str = Field(min_length=1)


class StageUpdateRequest(StrictModel):
    text: str | None = Field(default=None, max_length=MAX_STAGE_TEXT_LENGTH)
    image_id: UUID | None = None
    image: StageImageUpload | None = None
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)

    @model_validator(mode="after")
    def validate_image_source(self) -> StageUpdateRequest:
        if self.image_id is not None and self.image is not None:
            raise ValueError("image_id and image are mutually exclusive")
        if self.text is not None:
            normalized = self.text.strip()
            self.text = normalized or None
        return self


class StageState(StrictModel):
    session_id: UUID
    revision: int = Field(ge=0)
    text: str | None = None
    image_id: UUID | None = None
    image_media_type: str | None = None
    image_filename: str | None = None


class StageImageContent(StrictModel):
    id: UUID
    media_type: str
    filename: str | None = None
    data: bytes


class StageImageInvalidError(ValueError):
    pass


class ExplorationStageService:
    def __init__(
        self,
        repository: ExplorationRepository,
        table_event_service: TableEventService,
    ) -> None:
        self.repository = repository
        self.table_event_service = table_event_service

    @staticmethod
    def _binding(actor: TableActorContext) -> StoredTableActorBinding:
        if actor.actor_kind is not TableActorKind.HUMAN or actor.access_session_id is None:
            raise TableEventActorUnauthorizedError(
                "AI Stage actor resolver is not available until P3-D"
            )
        return StoredTableActorBinding(
            room_id=actor.room_id,
            campaign_id=actor.campaign_id,
            session_id=actor.session_id,
            seat_id=actor.seat_id,
            controlled_seat_ids=actor.controlled_seat_ids,
            role=actor.role,
            is_current_dm=actor.is_current_dm,
            access_session_id=actor.access_session_id,
        )

    @staticmethod
    def _present(stage: StoredSessionStage) -> StageState:
        return StageState(
            session_id=stage.session_id,
            revision=stage.revision,
            text=stage.text,
            image_id=stage.image_id,
            image_media_type=stage.image_media_type,
            image_filename=stage.image_filename,
        )

    @staticmethod
    def _decode_image(upload: StageImageUpload) -> tuple[str, str | None, bytes]:
        try:
            data = base64.b64decode(upload.data_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise StageImageInvalidError("Stage image is not valid base64") from exc
        if not data or len(data) > MAX_STAGE_IMAGE_BYTES:
            raise StageImageInvalidError(
                f"Stage image must be between 1 and {MAX_STAGE_IMAGE_BYTES} bytes"
            )
        signatures = {
            "image/png": lambda value: value.startswith(b"\x89PNG\r\n\x1a\n"),
            "image/jpeg": lambda value: value.startswith(b"\xff\xd8\xff"),
            "image/webp": lambda value: (
                len(value) >= 12
                and value.startswith(b"RIFF")
                and value[8:12] == b"WEBP"
            ),
        }
        if upload.media_type not in SUPPORTED_STAGE_IMAGE_TYPES or not signatures[upload.media_type](data):
            raise StageImageInvalidError("Stage image bytes do not match media_type")
        return upload.media_type, upload.filename, data

    def get_stage(self, actor: TableActorContext) -> StageState:
        self.table_event_service.require_actor_current(actor)
        return self._present(
            self.repository.load_stage(
                room_id=actor.room_id,
                campaign_id=actor.campaign_id,
                session_id=actor.session_id,
            )
        )

    def replace_stage(
        self,
        actor: TableActorContext,
        request: StageUpdateRequest,
    ) -> StageState:
        if not actor.is_current_dm:
            raise TableEventActorUnauthorizedError(
                "Only the current Session DM can update Main Stage"
            )
        new_image = self._decode_image(request.image) if request.image is not None else None
        try:
            stage, _event = self.repository.replace_stage(
                binding=self._binding(actor),
                text=request.text,
                retain_image_id=request.image_id,
                new_image=new_image,
                idempotency_key=(
                    f"p3b-stage:{request.idempotency_key}"
                    if request.idempotency_key is not None
                    else None
                ),
            )
        except TableEventActorBindingStalePersistenceError as exc:
            raise TableEventActorUnauthorizedError(str(exc)) from exc
        if self.table_event_service.notifier is not None:
            self.table_event_service.notifier.notify(actor.session_id)
        return self._present(stage)

    def get_image(self, actor: TableActorContext, image_id: UUID) -> StageImageContent:
        self.table_event_service.require_actor_current(actor)
        image: StoredStageImage = self.repository.load_image(
            room_id=actor.room_id,
            image_id=image_id,
        )
        return StageImageContent(
            id=image.id,
            media_type=image.media_type,
            filename=image.filename,
            data=image.data,
        )


__all__ = [
    "ExplorationStageService",
    "MAX_STAGE_IMAGE_BYTES",
    "MAX_STAGE_TEXT_LENGTH",
    "SUPPORTED_STAGE_IMAGE_TYPES",
    "StageImageContent",
    "StageImageInvalidError",
    "StageImageNotFoundPersistenceError",
    "StageImageUpload",
    "StageState",
    "StageUpdateRequest",
]
