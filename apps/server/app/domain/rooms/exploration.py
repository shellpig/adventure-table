from __future__ import annotations

import base64
import binascii
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.domain.rooms.schemas import StrictModel
from app.domain.rooms.table_events import (
    TableActorContext,
    TableActorKind,
    TableEvent,
    TableEventActorUnauthorizedError,
    TableEventAppend,
    TableEventNotFoundError,
    TableEventService,
    TableEventSessionNotActiveError,
    TableEventVisibility,
    TableExecutionMode,
)
from app.persistence.rooms.exploration import (
    ExplorationRepository,
    StageImageNotFoundPersistenceError,
    StoredSessionStage,
    StoredStageImage,
)
from app.persistence.rooms.exploration_subjects import (
    ExplorationSubjectRepository,
    StoredExplorationSubject,
)
from app.persistence.rooms.table_runtime import (
    StoredTableActorBinding,
    TableEventActorBindingStalePersistenceError,
    TableEventSessionNotActivePersistenceError,
    TableEventSessionNotFoundPersistenceError,
)


MAX_STAGE_TEXT_LENGTH = 12_000
MAX_STAGE_IMAGE_BYTES = 8 * 1024 * 1024
MAX_STAGE_IMAGE_BASE64_LENGTH = ((MAX_STAGE_IMAGE_BYTES + 2) // 3) * 4 + 16
MAX_EXPLORATION_TEXT_LENGTH = 8_000
SUPPORTED_STAGE_IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})


class StageImageUpload(StrictModel):
    media_type: Literal["image/png", "image/jpeg", "image/webp"]
    filename: str | None = Field(default=None, max_length=255)
    data_base64: str = Field(min_length=1, max_length=MAX_STAGE_IMAGE_BASE64_LENGTH)


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


class ExplorationInputKind(StrEnum):
    DIALOGUE = "dialogue"
    ACTION = "action"
    OOC = "ooc"
    WHISPER_DM = "whisper_dm"
    NARRATION = "narration"


class ExplorationInputRequest(StrictModel):
    kind: ExplorationInputKind
    text: str = Field(min_length=1, max_length=MAX_EXPLORATION_TEXT_LENGTH)
    subject_seat_id: UUID | None = None
    source_command: Literal["search"] | None = None
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)

    @model_validator(mode="after")
    def validate_shape(self) -> ExplorationInputRequest:
        self.text = self.text.strip()
        if not self.text:
            raise ValueError("exploration text cannot be blank")
        subject_required = self.kind in {
            ExplorationInputKind.DIALOGUE,
            ExplorationInputKind.ACTION,
        }
        if subject_required and self.subject_seat_id is None:
            raise ValueError("dialogue/action requires subject_seat_id")
        if not subject_required and self.subject_seat_id is not None:
            raise ValueError("subject_seat_id is only valid for dialogue/action")
        if self.source_command is not None and self.kind is not ExplorationInputKind.ACTION:
            raise ValueError("source_command is only valid for action")
        return self


class ExplorationSubjectNotFoundError(LookupError):
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
        try:
            stored = self.repository.load_stage(
                room_id=actor.room_id,
                campaign_id=actor.campaign_id,
                session_id=actor.session_id,
            )
        except TableEventSessionNotFoundPersistenceError as exc:
            raise TableEventNotFoundError(str(actor.session_id)) from exc
        return self._present(stored)

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
        except TableEventSessionNotFoundPersistenceError as exc:
            raise TableEventNotFoundError(str(actor.session_id)) from exc
        except TableEventSessionNotActivePersistenceError as exc:
            raise TableEventSessionNotActiveError(str(actor.session_id)) from exc
        if self.table_event_service.notifier is not None:
            self.table_event_service.notifier.notify(actor.session_id)
        return self._present(stage)

    def get_image(self, actor: TableActorContext, image_id: UUID) -> StageImageContent:
        stage = self.get_stage(actor)
        if stage.image_id != image_id:
            raise StageImageNotFoundPersistenceError(str(image_id))
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


class ExplorationActionService:
    """Typed Human table input service; P3-D can supply AI TableActorContext unchanged."""

    def __init__(
        self,
        subject_repository: ExplorationSubjectRepository,
        table_event_service: TableEventService,
    ) -> None:
        self.subject_repository = subject_repository
        self.table_event_service = table_event_service

    def _subject(self, actor: TableActorContext, seat_id: UUID) -> StoredExplorationSubject:
        subject = self.subject_repository.resolve_subject(
            room_id=actor.room_id,
            campaign_id=actor.campaign_id,
            session_id=actor.session_id,
            seat_id=seat_id,
        )
        if subject is None or subject.role != "player" or subject.active_character_id is None:
            raise ExplorationSubjectNotFoundError(str(seat_id))
        return subject

    def send(self, actor: TableActorContext, request: ExplorationInputRequest) -> TableEvent:
        self.table_event_service.require_actor_current(actor)
        subject: StoredExplorationSubject | None = None
        execution_mode = TableExecutionMode.SELF
        acting_seat_id = actor.seat_id

        if request.subject_seat_id is not None:
            subject = self._subject(actor, request.subject_seat_id)
            if subject.seat_id in actor.controlled_seat_ids:
                acting_seat_id = subject.seat_id
            elif actor.is_current_dm:
                execution_mode = TableExecutionMode.DM_PROXY
            else:
                raise TableEventActorUnauthorizedError(
                    "Actor does not control the selected Player Seat"
                )

        if request.kind is ExplorationInputKind.NARRATION and not actor.is_current_dm:
            raise TableEventActorUnauthorizedError(
                "Only the current Session DM can send Narration"
            )

        visibility = TableEventVisibility.PUBLIC
        recipient_seat_ids: tuple[UUID, ...] = ()
        if request.kind is ExplorationInputKind.WHISPER_DM:
            visibility = TableEventVisibility.SEAT_PRIVATE
            recipient_seat_ids = (actor.seat_id,)

        payload = {
            "type": request.kind.value,
            "text": request.text,
            "source_command": request.source_command,
        }
        return self.table_event_service.append_event(
            actor,
            TableEventAppend(
                kind=f"exploration.{request.kind.value}",
                acting_seat_id=acting_seat_id,
                subject_seat_id=subject.seat_id if subject is not None else None,
                subject_character_id=(
                    subject.active_character_id if subject is not None else None
                ),
                execution_mode=execution_mode,
                visibility=visibility,
                recipient_seat_ids=recipient_seat_ids,
                payload=payload,
                idempotency_key=(
                    f"p3b-input:{request.idempotency_key}"
                    if request.idempotency_key is not None
                    else None
                ),
            ),
        )


__all__ = [
    "ExplorationActionService",
    "ExplorationInputKind",
    "ExplorationInputRequest",
    "ExplorationStageService",
    "ExplorationSubjectNotFoundError",
    "MAX_EXPLORATION_TEXT_LENGTH",
    "MAX_STAGE_IMAGE_BASE64_LENGTH",
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
