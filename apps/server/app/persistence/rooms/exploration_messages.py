from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    insert,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine

from app.db import metadata
from app.persistence.rooms.table_runtime import (
    StoredTableActorBinding,
    StoredTableEvent,
    TableEventRepository,
    session_events,
)


recipient_type = JSON().with_variant(JSONB(), "postgresql")

session_messages = Table(
    "session_messages",
    metadata,
    Column("id", Uuid(), primary_key=True),
    Column(
        "session_id",
        Uuid(),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "event_id",
        Uuid(),
        ForeignKey("session_events.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "acting_seat_id",
        Uuid(),
        ForeignKey("campaign_seats.id", ondelete="RESTRICT"),
        nullable=True,
    ),
    Column(
        "subject_seat_id",
        Uuid(),
        ForeignKey("campaign_seats.id", ondelete="RESTRICT"),
        nullable=True,
    ),
    Column(
        "subject_character_id",
        Uuid(),
        ForeignKey("characters.id", ondelete="RESTRICT"),
        nullable=True,
    ),
    Column("execution_mode", String(16), nullable=False),
    Column("kind", String(24), nullable=False),
    Column("text", Text(), nullable=False),
    Column("visibility", String(24), nullable=False),
    Column(
        "recipient_seat_ids",
        recipient_type,
        nullable=False,
        default=list,
        server_default="[]",
    ),
    Column("source_command", String(16), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "kind IN ('dialogue', 'action', 'ooc', 'whisper_dm', 'narration')",
        name="ck_session_messages_kind",
    ),
    CheckConstraint(
        "execution_mode IN ('self', 'dm_proxy', 'system')",
        name="ck_session_messages_execution_mode",
    ),
    CheckConstraint(
        "visibility IN ('public', 'dm_only', 'actor_and_dm', 'seat_private')",
        name="ck_session_messages_visibility",
    ),
    CheckConstraint(
        "source_command IS NULL OR source_command IN ('search', 'check')",
        name="ck_session_messages_source_command",
    ),
    UniqueConstraint("event_id", name="uq_session_messages_event_id"),
)
Index("ix_session_messages_session_id", session_messages.c.session_id)


class ExplorationMessageRepository:
    """Write canonical Exploration messages and their transport event atomically."""

    def __init__(self, engine: Engine) -> None:
        self.event_repository = TableEventRepository(engine)

    def append_message(
        self,
        *,
        binding: StoredTableActorBinding,
        message_kind: str,
        text: str,
        acting_seat_id: UUID,
        subject_seat_id: UUID | None,
        subject_character_id: UUID | None,
        execution_mode: str,
        visibility: str,
        recipient_seat_ids: tuple[UUID, ...],
        source_command: str | None,
        idempotency_key: str | None,
    ) -> StoredTableEvent:
        message_id = uuid4()

        def persist_message(connection, event_id: UUID, _event_seq: int) -> None:
            connection.execute(
                insert(session_messages).values(
                    id=message_id,
                    session_id=binding.session_id,
                    event_id=event_id,
                    acting_seat_id=acting_seat_id,
                    subject_seat_id=subject_seat_id,
                    subject_character_id=subject_character_id,
                    execution_mode=execution_mode,
                    kind=message_kind,
                    text=text,
                    visibility=visibility,
                    recipient_seat_ids=[str(value) for value in recipient_seat_ids],
                    source_command=source_command,
                )
            )

        return self.event_repository.append(
            room_id=binding.room_id,
            campaign_id=binding.campaign_id,
            session_id=binding.session_id,
            kind=f"exploration.{message_kind}",
            acting_seat_id=acting_seat_id,
            subject_seat_id=subject_seat_id,
            subject_character_id=subject_character_id,
            execution_mode=execution_mode,
            visibility=visibility,
            recipient_seat_ids=recipient_seat_ids,
            payload_version=1,
            payload={
                "type": message_kind,
                "text": text,
                "source_command": source_command,
            },
            idempotency_key=idempotency_key,
            expected_actor_binding=binding,
            transaction_projection=persist_message,
        )


__all__ = ["ExplorationMessageRepository", "session_messages"]
