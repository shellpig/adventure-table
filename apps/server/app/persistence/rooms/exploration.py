from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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
    TableEventActorBindingStalePersistenceError,
    TableEventSessionNotActivePersistenceError,
    TableEventSessionNotFoundPersistenceError,
    session_events,
    session_table_runtime,
)
from app.persistence.rooms.tables import campaigns, room_access_sessions, sessions


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
    """P3-B canonical Stage persistence plus atomic Stage event emission."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @staticmethod
    def _stored_event(row: Any) -> StoredTableEvent:
        return StoredTableEvent(
            id=row["id"],
            session_id=row["session_id"],
            seq=int(row["seq"]),
            kind=row["kind"],
            acting_seat_id=row["acting_seat_id"],
            subject_seat_id=row["subject_seat_id"],
            subject_character_id=row["subject_character_id"],
            execution_mode=row["execution_mode"],
            visibility=row["visibility"],
            recipient_seat_ids=tuple(
                UUID(str(value)) for value in (row["recipient_seat_ids"] or [])
            ),
            payload_version=int(row["payload_version"]),
            payload=dict(row["payload"]),
            idempotency_key=row["idempotency_key"],
            created_at=row["created_at"],
        )

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
    def _stage_from_event(row: Any, session_id: UUID) -> StoredSessionStage:
        payload = dict(row["payload"])
        raw_image_id = payload.get("image_id")
        return StoredSessionStage(
            session_id=session_id,
            revision=int(payload["stage_revision"]),
            text=payload.get("text"),
            image_id=UUID(str(raw_image_id)) if raw_image_id is not None else None,
            image_media_type=payload.get("image_media_type"),
            image_filename=payload.get("image_filename"),
            updated_by_seat_id=row["acting_seat_id"],
        )

    def _session_scope_row(
        self,
        connection,
        *,
        room_id: UUID,
        campaign_id: UUID,
        session_id: UUID,
        for_update: bool = False,
    ):
        query = (
            select(
                sessions.c.id,
                sessions.c.status,
                sessions.c.dm_seat_id,
                sessions.c.dm_controller_kind,
                sessions.c.dm_controller_access_session_id,
                campaigns.c.room_id,
            )
            .select_from(sessions.join(campaigns, campaigns.c.id == sessions.c.campaign_id))
            .where(
                sessions.c.id == session_id,
                sessions.c.campaign_id == campaign_id,
                campaigns.c.room_id == room_id,
            )
        )
        if for_update:
            query = query.with_for_update()
        return connection.execute(query).mappings().one_or_none()

    def _require_current_dm(
        self,
        connection,
        *,
        binding: StoredTableActorBinding,
        session_row: Any,
    ) -> None:
        access = connection.execute(
            select(
                room_access_sessions.c.id,
                room_access_sessions.c.room_id,
                room_access_sessions.c.revoked_at,
            )
            .where(room_access_sessions.c.id == binding.access_session_id)
            .with_for_update()
        ).mappings().one_or_none()
        current = (
            binding.is_current_dm
            and binding.role == "dm"
            and binding.seat_id == session_row["dm_seat_id"]
            and binding.room_id == session_row["room_id"]
            and session_row["dm_controller_kind"] == "human"
            and session_row["dm_controller_access_session_id"] == binding.access_session_id
            and access is not None
            and access["room_id"] == binding.room_id
            and access["revoked_at"] is None
        )
        if not current:
            raise TableEventActorBindingStalePersistenceError(
                "Stage writer is no longer the current Session DM"
            )

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
        campaign_id = binding.campaign_id
        session_id = binding.session_id
        event_id = uuid4()

        with self.engine.begin() as connection:
            session_row = self._session_scope_row(
                connection,
                room_id=room_id,
                campaign_id=campaign_id,
                session_id=session_id,
                for_update=True,
            )
            if session_row is None:
                raise TableEventSessionNotFoundPersistenceError(str(session_id))
            self._require_current_dm(connection, binding=binding, session_row=session_row)
            if session_row["status"] != "active":
                raise TableEventSessionNotActivePersistenceError(str(session_id))

            if idempotency_key is not None:
                existing = connection.execute(
                    select(session_events).where(
                        session_events.c.session_id == session_id,
                        session_events.c.idempotency_key == idempotency_key,
                    )
                ).mappings().one_or_none()
                if existing is not None:
                    return (
                        self._stage_from_event(existing, session_id),
                        self._stored_event(existing),
                    )

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

            runtime_row = connection.execute(
                select(session_table_runtime)
                .where(session_table_runtime.c.session_id == session_id)
                .with_for_update()
            ).mappings().one_or_none()
            if runtime_row is None:
                next_seq = 1
                connection.execute(
                    insert(session_table_runtime).values(
                        session_id=session_id,
                        revision=1,
                        last_event_seq=1,
                    )
                )
            else:
                next_seq = int(runtime_row["last_event_seq"]) + 1
                connection.execute(
                    update(session_table_runtime)
                    .where(session_table_runtime.c.session_id == session_id)
                    .values(
                        revision=int(runtime_row["revision"]) + 1,
                        last_event_seq=next_seq,
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
                insert(session_events).values(
                    id=event_id,
                    session_id=session_id,
                    seq=next_seq,
                    kind="stage.updated",
                    acting_seat_id=binding.seat_id,
                    subject_seat_id=None,
                    subject_character_id=None,
                    execution_mode="self",
                    visibility="public",
                    recipient_seat_ids=[],
                    payload_version=1,
                    payload=payload,
                    idempotency_key=idempotency_key,
                )
            )

            if old_image_id is not None and old_image_id != next_image_id:
                connection.execute(
                    delete(room_stage_images).where(room_stage_images.c.id == old_image_id)
                )

            final_stage_row = connection.execute(
                select(session_stages).where(session_stages.c.session_id == session_id)
            ).mappings().one()
            event_row = connection.execute(
                select(session_events).where(session_events.c.id == event_id)
            ).mappings().one()

        return (
            self._stage(final_stage_row, image_row, session_id),
            self._stored_event(event_row),
        )


__all__ = [
    "ExplorationRepository",
    "StageImageNotFoundPersistenceError",
    "StageRevisionConflictPersistenceError",
    "StoredSessionStage",
    "StoredStageImage",
    "room_stage_images",
    "session_stages",
]
