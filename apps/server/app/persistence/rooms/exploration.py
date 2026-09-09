from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Table,
    Text,
    Uuid,
    delete,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Engine

from app.db import metadata
from app.persistence.rooms.table_runtime import (
    StoredTableActorBinding,
    StoredTableEvent,
    TableEventRepository,
    TableEventSessionNotFoundPersistenceError,
    session_events,
)
from app.persistence.rooms.tables import campaigns, sessions


room_stage_images = Table(
    "room_stage_images",
    metadata,
    Column("id", Uuid(), primary_key=True),
    Column("room_id", Uuid(), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False),
    Column("media_type", String(40), nullable=False),
    Column("filename", String(255), nullable=True),
    Column("sha256", String(64), nullable=False),
    Column("data", LargeBinary(), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
Index("ix_room_stage_images_room_id", room_stage_images.c.room_id)

session_stages = Table(
    "session_stages",
    metadata,
    Column(
        "session_id",
        Uuid(),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("revision", BigInteger, nullable=False, server_default="0"),
    Column("text", Text(), nullable=True),
    Column(
        "image_id",
        Uuid(),
        ForeignKey("room_stage_images.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column(
        "updated_by_seat_id",
        Uuid(),
        ForeignKey("campaign_seats.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("revision >= 0", name="ck_session_stages_revision_nonnegative"),
)
Index("ix_session_stages_image_id", session_stages.c.image_id)


class StageImageNotFoundPersistenceError(LookupError):
    pass


class StageRevisionConflictPersistenceError(RuntimeError):
    def __init__(self, expected_revision: int, current_revision: int) -> None:
        super().__init__(
            f"Stage revision conflict: expected {expected_revision}, current {current_revision}"
        )
        self.expected_revision = expected_revision
        self.current_revision = current_revision


@dataclass(frozen=True)
class StoredStageImage:
    id: UUID
    room_id: UUID
    media_type: str
    filename: str | None
    sha256: str
    data: bytes


@dataclass(frozen=True)
class StoredSessionStage:
    session_id: UUID
    revision: int
    text: str | None
    image_id: UUID | None
    image_media_type: str | None
    image_filename: str | None
    updated_by_seat_id: UUID | None


class ExplorationRepository:
    """P3-B Stage projection persisted through the canonical P3 event allocator."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.event_repository = TableEventRepository(engine)

    @staticmethod
    def _stage(row: Any | None, image_row: Any | None, session_id: UUID) -> StoredSessionStage:
        if row is None:
            return StoredSessionStage(
                session_id=session_id,
                revision=0,
                text=None,
                image_id=None,
                image_media_type=None,
                image_filename=None,
                updated_by_seat_id=None,
            )
        return StoredSessionStage(
            session_id=session_id,
            revision=int(row["revision"]),
            text=row["text"],
            image_id=row["image_id"],
            image_media_type=image_row["media_type"] if image_row is not None else None,
            image_filename=image_row["filename"] if image_row is not None else None,
            updated_by_seat_id=row["updated_by_seat_id"],
        )

    @staticmethod
    def _stage_from_event(event: StoredTableEvent) -> StoredSessionStage:
        payload = dict(event.payload)
        raw_image_id = payload.get("image_id")
        return StoredSessionStage(
            session_id=event.session_id,
            revision=int(payload["stage_revision"]),
            text=payload.get("text"),
            image_id=UUID(str(raw_image_id)) if raw_image_id is not None else None,
            image_media_type=payload.get("image_media_type"),
            image_filename=payload.get("image_filename"),
            updated_by_seat_id=event.acting_seat_id,
        )

    def _session_scope_row(
        self,
        connection,
        *,
        room_id: UUID,
        campaign_id: UUID,
        session_id: UUID,
    ):
        return connection.execute(
            select(
                sessions.c.id,
                campaigns.c.room_id,
            )
            .select_from(sessions.join(campaigns, campaigns.c.id == sessions.c.campaign_id))
            .where(
                sessions.c.id == session_id,
                sessions.c.campaign_id == campaign_id,
                campaigns.c.room_id == room_id,
            )
        ).mappings().one_or_none()

    def _image_row(self, connection, *, room_id: UUID, image_id: UUID | None):
        if image_id is None:
            return None
        return connection.execute(
            select(room_stage_images).where(
                room_stage_images.c.id == image_id,
                room_stage_images.c.room_id == room_id,
            )
        ).mappings().one_or_none()

    def load_stage(
        self,
        *,
        room_id: UUID,
        campaign_id: UUID,
        session_id: UUID,
    ) -> StoredSessionStage:
        with self.engine.connect() as connection:
            session_row = self._session_scope_row(
                connection,
                room_id=room_id,
                campaign_id=campaign_id,
                session_id=session_id,
            )
            if session_row is None:
                raise TableEventSessionNotFoundPersistenceError(str(session_id))
            row = connection.execute(
                select(session_stages).where(session_stages.c.session_id == session_id)
            ).mappings().one_or_none()
            image_row = self._image_row(
                connection,
                room_id=room_id,
                image_id=row["image_id"] if row is not None else None,
            )
        return self._stage(row, image_row, session_id)

    def load_image(self, *, room_id: UUID, image_id: UUID) -> StoredStageImage:
        with self.engine.connect() as connection:
            row = self._image_row(connection, room_id=room_id, image_id=image_id)
        if row is None:
            raise StageImageNotFoundPersistenceError(str(image_id))
        return StoredStageImage(
            id=row["id"],
            room_id=row["room_id"],
            media_type=row["media_type"],
            filename=row["filename"],
            sha256=row["sha256"],
            data=bytes(row["data"]),
        )

    def replace_stage(
        self,
        *,
        binding: StoredTableActorBinding,
        expected_revision: int,
        text: str | None,
        retain_image_id: UUID | None,
        new_image: tuple[str, str | None, bytes] | None,
        idempotency_key: str | None,
    ) -> tuple[StoredSessionStage, StoredTableEvent]:
        room_id = binding.room_id
        session_id = binding.session_id
        projected_stage: list[StoredSessionStage] = []

        def persist_stage(connection, event_id: UUID, _event_seq: int) -> None:
            stage_row = connection.execute(
                select(session_stages)
                .where(session_stages.c.session_id == session_id)
                .with_for_update()
            ).mappings().one_or_none()
            current_revision = int(stage_row["revision"]) if stage_row is not None else 0
            if current_revision != expected_revision:
                raise StageRevisionConflictPersistenceError(
                    expected_revision=expected_revision,
                    current_revision=current_revision,
                )
            old_image_id = stage_row["image_id"] if stage_row is not None else None

            if new_image is not None:
                media_type, filename, image_data = new_image
                next_image_id = uuid4()
                connection.execute(
                    insert(room_stage_images).values(
                        id=next_image_id,
                        room_id=room_id,
                        media_type=media_type,
                        filename=filename,
                        sha256=sha256(image_data).hexdigest(),
                        data=image_data,
                    )
                )
                image_row = self._image_row(
                    connection,
                    room_id=room_id,
                    image_id=next_image_id,
                )
            elif retain_image_id is not None:
                if retain_image_id != old_image_id:
                    raise StageImageNotFoundPersistenceError(str(retain_image_id))
                image_row = self._image_row(
                    connection,
                    room_id=room_id,
                    image_id=retain_image_id,
                )
                if image_row is None:
                    raise StageImageNotFoundPersistenceError(str(retain_image_id))
                next_image_id = retain_image_id
            else:
                next_image_id = None
                image_row = None

            next_stage_revision = current_revision + 1
            if stage_row is None:
                connection.execute(
                    insert(session_stages).values(
                        session_id=session_id,
                        revision=next_stage_revision,
                        text=text,
                        image_id=next_image_id,
                        updated_by_seat_id=binding.seat_id,
                    )
                )
            else:
                connection.execute(
                    update(session_stages)
                    .where(session_stages.c.session_id == session_id)
                    .values(
                        revision=next_stage_revision,
                        text=text,
                        image_id=next_image_id,
                        updated_by_seat_id=binding.seat_id,
                        updated_at=func.now(),
                    )
                )

            payload = {
                "stage_revision": next_stage_revision,
                "text": text,
                "image_id": str(next_image_id) if next_image_id is not None else None,
                "image_media_type": image_row["media_type"] if image_row is not None else None,
                "image_filename": image_row["filename"] if image_row is not None else None,
                "updated_by_seat_id": str(binding.seat_id),
            }
            connection.execute(
                update(session_events)
                .where(session_events.c.id == event_id)
                .values(payload=payload)
            )

            if old_image_id is not None and old_image_id != next_image_id:
                connection.execute(
                    delete(room_stage_images).where(room_stage_images.c.id == old_image_id)
                )

            final_stage_row = connection.execute(
                select(session_stages).where(session_stages.c.session_id == session_id)
            ).mappings().one()
            projected_stage.append(self._stage(final_stage_row, image_row, session_id))

        stored_event = self.event_repository.append(
            room_id=binding.room_id,
            campaign_id=binding.campaign_id,
            session_id=session_id,
            kind="stage.updated",
            acting_seat_id=binding.seat_id,
            subject_seat_id=None,
            subject_character_id=None,
            execution_mode="self",
            visibility="public",
            recipient_seat_ids=(),
            payload_version=1,
            payload={},
            idempotency_key=idempotency_key,
            expected_actor_binding=binding,
            transaction_projection=persist_stage,
        )
        if projected_stage:
            return projected_stage[0], stored_event
        return self._stage_from_event(stored_event), stored_event


__all__ = [
    "ExplorationRepository",
    "StageImageNotFoundPersistenceError",
    "StageRevisionConflictPersistenceError",
    "StoredSessionStage",
    "StoredStageImage",
    "room_stage_images",
    "session_stages",
]
