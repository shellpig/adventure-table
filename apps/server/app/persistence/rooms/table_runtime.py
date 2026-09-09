from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
    Uuid,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine

from app.db import metadata
from app.persistence.rooms.tables import (
    campaigns,
    room_access_sessions,
    session_participants,
    sessions,
)


json_payload_type = JSON().with_variant(JSONB(), "postgresql")
MAX_EVENT_SCAN_LIMIT = 200


session_table_runtime = Table(
    "session_table_runtime",
    metadata,
    Column(
        "session_id",
        Uuid(),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("revision", BigInteger, nullable=False, server_default="0"),
    Column("last_event_seq", BigInteger, nullable=False, server_default="0"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "revision >= 0",
        name="ck_session_table_runtime_revision_nonnegative",
    ),
    CheckConstraint(
        "last_event_seq >= 0",
        name="ck_session_table_runtime_last_event_seq_nonnegative",
    ),
)

session_events = Table(
    "session_events",
    metadata,
    Column("id", Uuid(), primary_key=True),
    Column(
        "session_id",
        Uuid(),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("seq", BigInteger, nullable=False),
    Column("kind", String(80), nullable=False),
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
    Column("execution_mode", String(16), nullable=True),
    Column("visibility", String(24), nullable=False),
    Column(
        "recipient_seat_ids",
        json_payload_type,
        nullable=False,
        default=list,
        server_default="[]",
    ),
    Column("payload_version", Integer, nullable=False, server_default="1"),
    Column("payload", json_payload_type, nullable=False),
    Column("idempotency_key", String(160), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("seq > 0", name="ck_session_events_seq_positive"),
    CheckConstraint(
        "payload_version > 0",
        name="ck_session_events_payload_version_positive",
    ),
    CheckConstraint(
        "visibility IN ('public', 'dm_only', 'actor_and_dm', 'seat_private')",
        name="ck_session_events_visibility",
    ),
    CheckConstraint(
        "execution_mode IS NULL OR execution_mode IN ('self', 'dm_proxy', 'system')",
        name="ck_session_events_execution_mode",
    ),
    UniqueConstraint("session_id", "seq", name="uq_session_events_session_seq"),
    UniqueConstraint(
        "session_id",
        "idempotency_key",
        name="uq_session_events_session_idempotency",
    ),
)
Index("ix_session_events_session_seq", session_events.c.session_id, session_events.c.seq)


class TableEventSessionNotFoundPersistenceError(LookupError):
    pass


class TableEventSessionNotActivePersistenceError(RuntimeError):
    pass


class TableEventActorBindingStalePersistenceError(PermissionError):
    pass


@dataclass(frozen=True)
class StoredTableRuntime:
    session_id: UUID
    revision: int
    last_event_seq: int


@dataclass(frozen=True)
class StoredTableActorBinding:
    room_id: UUID
    campaign_id: UUID
    session_id: UUID
    seat_id: UUID
    controlled_seat_ids: tuple[UUID, ...]
    role: str
    is_current_dm: bool
    access_session_id: UUID


@dataclass(frozen=True)
class StoredTableEvent:
    id: UUID
    session_id: UUID
    seq: int
    kind: str
    acting_seat_id: UUID | None
    subject_seat_id: UUID | None
    subject_character_id: UUID | None
    execution_mode: str | None
    visibility: str
    recipient_seat_ids: tuple[UUID, ...]
    payload_version: int
    payload: dict[str, Any]
    idempotency_key: str | None
    created_at: datetime


TableEventTransactionProjection = Callable[[Any, UUID, int], None]


class TableEventRepository:
    """P3 durable cursor/event persistence.

    All append allocation for one Session is serialized by a row lock on the
    canonical P2 Session row. The implementation never derives a sequence from
    MAX(seq), so concurrent writers cannot allocate the same sequence.
    """

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @staticmethod
    def _event(row) -> StoredTableEvent:
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
                sessions.c.campaign_id,
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

    def _human_actor_from_connection(
        self,
        connection,
        *,
        room_id: UUID,
        campaign_id: UUID,
        session_id: UUID,
        access_session_id: UUID,
        session_row=None,
        lock_access: bool = False,
    ) -> StoredTableActorBinding | None:
        if session_row is None:
            session_row = self._session_scope_row(
                connection,
                room_id=room_id,
                campaign_id=campaign_id,
                session_id=session_id,
            )
        if session_row is None:
            return None

        access_query = select(
            room_access_sessions.c.id,
            room_access_sessions.c.room_id,
            room_access_sessions.c.revoked_at,
        ).where(room_access_sessions.c.id == access_session_id)
        if lock_access:
            access_query = access_query.with_for_update()
        access = connection.execute(access_query).mappings().one_or_none()
        if (
            access is None
            or access["room_id"] != room_id
            or access["revoked_at"] is not None
        ):
            return None

        participant_rows = connection.execute(
            select(
                session_participants.c.seat_id,
                session_participants.c.role_snapshot,
                session_participants.c.controller_kind_at_join,
                session_participants.c.controller_access_session_id_at_join,
                session_participants.c.joined_at,
                session_participants.c.id,
            )
            .where(
                session_participants.c.session_id == session_id,
                session_participants.c.left_at.is_(None),
            )
            .order_by(session_participants.c.joined_at, session_participants.c.id)
        ).mappings().all()

        controlled = tuple(
            row["seat_id"]
            for row in participant_rows
            if row["controller_kind_at_join"] == "human"
            and row["controller_access_session_id_at_join"] == access_session_id
        )
        is_current_dm = (
            session_row["dm_controller_kind"] == "human"
            and session_row["dm_controller_access_session_id"] == access_session_id
        )
        if is_current_dm:
            seat_id = session_row["dm_seat_id"]
            if seat_id not in controlled:
                controlled = (seat_id, *controlled)
            return StoredTableActorBinding(
                room_id=room_id,
                campaign_id=campaign_id,
                session_id=session_id,
                seat_id=seat_id,
                controlled_seat_ids=controlled,
                role="dm",
                is_current_dm=True,
                access_session_id=access_session_id,
            )
        if not controlled:
            return None

        role_by_seat = {
            row["seat_id"]: row["role_snapshot"]
            for row in participant_rows
            if row["seat_id"] in controlled
        }
        preferred = next(
            (seat_id for seat_id in controlled if role_by_seat[seat_id] == "player"),
            controlled[0],
        )
        return StoredTableActorBinding(
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            seat_id=preferred,
            controlled_seat_ids=controlled,
            role=role_by_seat[preferred],
            is_current_dm=False,
            access_session_id=access_session_id,
        )

    def resolve_human_actor(
        self,
        *,
        room_id: UUID,
        campaign_id: UUID,
        session_id: UUID,
        access_session_id: UUID,
    ) -> StoredTableActorBinding | None:
        with self.engine.connect() as connection:
            return self._human_actor_from_connection(
                connection,
                room_id=room_id,
                campaign_id=campaign_id,
                session_id=session_id,
                access_session_id=access_session_id,
            )

    def actor_binding_is_current(self, binding: StoredTableActorBinding) -> bool:
        current = self.resolve_human_actor(
            room_id=binding.room_id,
            campaign_id=binding.campaign_id,
            session_id=binding.session_id,
            access_session_id=binding.access_session_id,
        )
        return current == binding

    def current_runtime(
        self,
        *,
        room_id: UUID,
        campaign_id: UUID,
        session_id: UUID,
    ) -> StoredTableRuntime:
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
                select(session_table_runtime).where(
                    session_table_runtime.c.session_id == session_id
                )
            ).mappings().one_or_none()
        if row is None:
            return StoredTableRuntime(
                session_id=session_id,
                revision=0,
                last_event_seq=0,
            )
        return StoredTableRuntime(
            session_id=row["session_id"],
            revision=int(row["revision"]),
            last_event_seq=int(row["last_event_seq"]),
        )

    def list_after(
        self,
        *,
        room_id: UUID,
        campaign_id: UUID,
        session_id: UUID,
        after_seq: int,
        scan_limit: int,
    ) -> tuple[StoredTableEvent, ...]:
        bounded_limit = max(1, min(int(scan_limit), MAX_EVENT_SCAN_LIMIT))
        with self.engine.connect() as connection:
            session_row = self._session_scope_row(
                connection,
                room_id=room_id,
                campaign_id=campaign_id,
                session_id=session_id,
            )
            if session_row is None:
                raise TableEventSessionNotFoundPersistenceError(str(session_id))
            rows = connection.execute(
                select(session_events)
                .where(
                    session_events.c.session_id == session_id,
                    session_events.c.seq > max(0, int(after_seq)),
                )
                .order_by(session_events.c.seq)
                .limit(bounded_limit)
            ).mappings().all()
        return tuple(self._event(row) for row in rows)

    def append(
        self,
        *,
        room_id: UUID,
        campaign_id: UUID,
        session_id: UUID,
        kind: str,
        acting_seat_id: UUID | None,
        subject_seat_id: UUID | None,
        subject_character_id: UUID | None,
        execution_mode: str | None,
        visibility: str,
        recipient_seat_ids: tuple[UUID, ...],
        payload_version: int,
        payload: dict[str, Any],
        idempotency_key: str | None,
        expected_actor_binding: StoredTableActorBinding | None = None,
        transaction_projection: TableEventTransactionProjection | None = None,
    ) -> StoredTableEvent:
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

            if expected_actor_binding is not None:
                current_actor = self._human_actor_from_connection(
                    connection,
                    room_id=room_id,
                    campaign_id=campaign_id,
                    session_id=session_id,
                    access_session_id=expected_actor_binding.access_session_id,
                    session_row=session_row,
                    lock_access=True,
                )
                if current_actor != expected_actor_binding:
                    raise TableEventActorBindingStalePersistenceError(
                        "Table actor binding is no longer current"
                    )

            if idempotency_key is not None:
                existing = connection.execute(
                    select(session_events).where(
                        session_events.c.session_id == session_id,
                        session_events.c.idempotency_key == idempotency_key,
                    )
                ).mappings().one_or_none()
                if existing is not None:
                    return self._event(existing)

            if session_row["status"] != "active":
                raise TableEventSessionNotActivePersistenceError(str(session_id))

            runtime = connection.execute(
                select(session_table_runtime)
                .where(session_table_runtime.c.session_id == session_id)
                .with_for_update()
            ).mappings().one_or_none()
            if runtime is None:
                next_seq = 1
                next_revision = 1
                connection.execute(
                    insert(session_table_runtime).values(
                        session_id=session_id,
                        revision=next_revision,
                        last_event_seq=next_seq,
                    )
                )
            else:
                next_seq = int(runtime["last_event_seq"]) + 1
                next_revision = int(runtime["revision"]) + 1
                connection.execute(
                    update(session_table_runtime)
                    .where(session_table_runtime.c.session_id == session_id)
                    .values(
                        revision=next_revision,
                        last_event_seq=next_seq,
                        updated_at=func.now(),
                    )
                )

            connection.execute(
                insert(session_events).values(
                    id=event_id,
                    session_id=session_id,
                    seq=next_seq,
                    kind=kind,
                    acting_seat_id=acting_seat_id,
                    subject_seat_id=subject_seat_id,
                    subject_character_id=subject_character_id,
                    execution_mode=execution_mode,
                    visibility=visibility,
                    recipient_seat_ids=[str(value) for value in recipient_seat_ids],
                    payload_version=payload_version,
                    payload=payload,
                    idempotency_key=idempotency_key,
                )
            )
            if transaction_projection is not None:
                transaction_projection(connection, event_id, next_seq)
            row = connection.execute(
                select(session_events).where(session_events.c.id == event_id)
            ).mappings().one()
        return self._event(row)


__all__ = [
    "MAX_EVENT_SCAN_LIMIT",
    "StoredTableActorBinding",
    "StoredTableEvent",
    "StoredTableRuntime",
    "TableEventActorBindingStalePersistenceError",
    "TableEventRepository",
    "TableEventSessionNotActivePersistenceError",
    "TableEventSessionNotFoundPersistenceError",
    "TableEventTransactionProjection",
    "session_events",
    "session_table_runtime",
]
