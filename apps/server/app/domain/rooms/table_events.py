from __future__ import annotations

import asyncio
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

from pydantic import Field

from app.domain.rooms.schemas import RoomAccessContext, StrictModel
from app.persistence.rooms.table_runtime import (
    MAX_EVENT_SCAN_LIMIT,
    StoredTableActorBinding,
    StoredTableEvent,
    TableEventRepository,
    TableEventSessionNotActivePersistenceError,
    TableEventSessionNotFoundPersistenceError,
)


class TableActorKind(StrEnum):
    HUMAN = "human"
    AI = "ai"


class TableEventVisibility(StrEnum):
    PUBLIC = "public"
    DM_ONLY = "dm_only"
    ACTOR_AND_DM = "actor_and_dm"
    SEAT_PRIVATE = "seat_private"


class TableExecutionMode(StrEnum):
    SELF = "self"
    DM_PROXY = "dm_proxy"
    SYSTEM = "system"


class TableEventNotFoundError(LookupError):
    pass


class TableEventActorUnauthorizedError(PermissionError):
    pass


class TableEventSessionNotActiveError(RuntimeError):
    pass


class TableEventNotifier(Protocol):
    def notify(self, session_id: UUID) -> None: ...

    def register(self, session_id: UUID) -> object: ...

    async def wait(self, handle: object, timeout: float) -> bool: ...

    def unregister(self, handle: object) -> None: ...


class TableActorContext(StrictModel):
    actor_kind: TableActorKind
    room_id: UUID
    campaign_id: UUID
    session_id: UUID
    seat_id: UUID
    controlled_seat_ids: tuple[UUID, ...]
    role: str
    is_current_dm: bool = False
    access_session_id: UUID | None = None
    ai_controller_grant_id: UUID | None = None
    grant_generation: int | None = None


class TableRuntimeCursor(StrictModel):
    session_id: UUID
    revision: int = Field(ge=0)
    last_event_seq: int = Field(ge=0)


class TableEventAppend(StrictModel):
    kind: str = Field(
        min_length=1,
        max_length=80,
        pattern=r"^[a-z0-9][a-z0-9_.-]*$",
    )
    acting_seat_id: UUID | None = None
    subject_seat_id: UUID | None = None
    subject_character_id: UUID | None = None
    execution_mode: TableExecutionMode | None = None
    visibility: TableEventVisibility = TableEventVisibility.PUBLIC
    recipient_seat_ids: tuple[UUID, ...] = ()
    payload_version: int = Field(default=1, ge=1)
    payload: dict[str, Any]
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=160)


class TableEvent(StrictModel):
    id: UUID
    session_id: UUID
    seq: int = Field(gt=0)
    kind: str
    acting_seat_id: UUID | None = None
    subject_seat_id: UUID | None = None
    subject_character_id: UUID | None = None
    execution_mode: TableExecutionMode | None = None
    visibility: TableEventVisibility
    recipient_seat_ids: tuple[UUID, ...]
    payload_version: int = Field(gt=0)
    payload: dict[str, Any]
    created_at: datetime


class TableEventPage(StrictModel):
    session_id: UUID
    after_seq: int = Field(ge=0)
    cursor: int = Field(ge=0)
    current_seq: int = Field(ge=0)
    has_more: bool
    events: list[TableEvent]


class TableEventService:
    """Actor-neutral event application service.

    P3-A has only a Human HTTP resolver. The service itself consumes a typed
    TableActorContext so P3-D can add AI grant resolution without cloning event
    authorization or audience projection. Durable DB cursors are authoritative;
    the process-local notifier is only an optional low-latency wake hint.
    """

    def __init__(
        self,
        repository: TableEventRepository,
        notifier: TableEventNotifier | None = None,
    ) -> None:
        self.repository = repository
        self.notifier = notifier

    @staticmethod
    def _actor(binding: StoredTableActorBinding) -> TableActorContext:
        return TableActorContext(
            actor_kind=TableActorKind.HUMAN,
            room_id=binding.room_id,
            campaign_id=binding.campaign_id,
            session_id=binding.session_id,
            seat_id=binding.seat_id,
            controlled_seat_ids=binding.controlled_seat_ids,
            role=binding.role,
            is_current_dm=binding.is_current_dm,
            access_session_id=binding.access_session_id,
        )

    @staticmethod
    def _stored_binding(actor: TableActorContext) -> StoredTableActorBinding:
        if actor.actor_kind is not TableActorKind.HUMAN or actor.access_session_id is None:
            raise TableEventActorUnauthorizedError(
                "AI event actor resolver is not available until P3-D"
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

    def resolve_human_actor(
        self,
        *,
        room_id: UUID,
        campaign_id: UUID,
        session_id: UUID,
        context: RoomAccessContext,
    ) -> TableActorContext:
        if context.room_id != room_id:
            raise TableEventNotFoundError(str(session_id))
        binding = self.repository.resolve_human_actor(
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            access_session_id=context.access_session_id,
        )
        if binding is None:
            raise TableEventNotFoundError(str(session_id))
        return self._actor(binding)

    def require_actor_current(self, actor: TableActorContext) -> None:
        binding = self._stored_binding(actor)
        if not self.repository.actor_binding_is_current(binding):
            raise TableEventActorUnauthorizedError("Table actor binding is no longer current")

    @staticmethod
    def _present(stored: StoredTableEvent) -> TableEvent:
        return TableEvent(
            id=stored.id,
            session_id=stored.session_id,
            seq=stored.seq,
            kind=stored.kind,
            acting_seat_id=stored.acting_seat_id,
            subject_seat_id=stored.subject_seat_id,
            subject_character_id=stored.subject_character_id,
            execution_mode=(
                TableExecutionMode(stored.execution_mode)
                if stored.execution_mode is not None
                else None
            ),
            visibility=TableEventVisibility(stored.visibility),
            recipient_seat_ids=stored.recipient_seat_ids,
            payload_version=stored.payload_version,
            payload=stored.payload,
            created_at=stored.created_at,
        )

    @staticmethod
    def _visible(actor: TableActorContext, stored: StoredTableEvent) -> bool:
        visibility = TableEventVisibility(stored.visibility)
        if visibility is TableEventVisibility.PUBLIC:
            return True
        if actor.is_current_dm:
            return True

        controlled = set(actor.controlled_seat_ids)
        if visibility is TableEventVisibility.DM_ONLY:
            return False
        if visibility is TableEventVisibility.ACTOR_AND_DM:
            related = {
                seat_id
                for seat_id in (stored.acting_seat_id, stored.subject_seat_id)
                if seat_id is not None
            }
            return bool(controlled.intersection(related))
        if visibility is TableEventVisibility.SEAT_PRIVATE:
            return bool(controlled.intersection(stored.recipient_seat_ids))
        return False

    def current_cursor(self, actor: TableActorContext) -> TableRuntimeCursor:
        self.require_actor_current(actor)
        try:
            runtime = self.repository.current_runtime(
                room_id=actor.room_id,
                campaign_id=actor.campaign_id,
                session_id=actor.session_id,
            )
        except TableEventSessionNotFoundPersistenceError as exc:
            raise TableEventNotFoundError(str(actor.session_id)) from exc
        return TableRuntimeCursor(
            session_id=runtime.session_id,
            revision=runtime.revision,
            last_event_seq=runtime.last_event_seq,
        )

    def list_after(
        self,
        actor: TableActorContext,
        *,
        after_seq: int,
        limit: int,
    ) -> TableEventPage:
        self.require_actor_current(actor)
        bounded_after = max(0, int(after_seq))
        bounded_limit = max(1, min(int(limit), MAX_EVENT_SCAN_LIMIT))
        try:
            raw = self.repository.list_after(
                room_id=actor.room_id,
                campaign_id=actor.campaign_id,
                session_id=actor.session_id,
                after_seq=bounded_after,
                scan_limit=bounded_limit,
            )
            runtime = self.repository.current_runtime(
                room_id=actor.room_id,
                campaign_id=actor.campaign_id,
                session_id=actor.session_id,
            )
        except TableEventSessionNotFoundPersistenceError as exc:
            raise TableEventNotFoundError(str(actor.session_id)) from exc

        # Advance over the bounded raw window, including events this caller may
        # not see, so a private event cannot make an unauthorized client spin on
        # the same cursor forever or infer hidden-event details from a flag.
        cursor = raw[-1].seq if raw else bounded_after
        visible = [
            self._present(stored)
            for stored in raw
            if self._visible(actor, stored)
        ]
        return TableEventPage(
            session_id=actor.session_id,
            after_seq=bounded_after,
            cursor=cursor,
            current_seq=runtime.last_event_seq,
            has_more=cursor < runtime.last_event_seq,
            events=visible,
        )

    async def wait_after(
        self,
        actor: TableActorContext,
        *,
        after_seq: int,
        limit: int,
        timeout: float,
    ) -> TableEventPage:
        """Wait without occupying a DB connection/transaction or worker thread.

        Only the short authorization/query calls are sent to a worker thread.
        The idle period awaits an asyncio primitive in this request task. A DB
        recheck immediately after registration closes the lost-wakeup window; a
        final DB recheck after wake/timeout makes the durable cursor canonical.
        """

        bounded_after = max(0, int(after_seq))
        bounded_timeout = max(0.0, min(float(timeout), 60.0))

        first = await asyncio.to_thread(
            self.list_after,
            actor,
            after_seq=bounded_after,
            limit=limit,
        )
        if first.cursor > bounded_after:
            return first

        if self.notifier is None:
            if bounded_timeout > 0:
                await asyncio.sleep(bounded_timeout)
            return await asyncio.to_thread(
                self.list_after,
                actor,
                after_seq=bounded_after,
                limit=limit,
            )

        handle = self.notifier.register(actor.session_id)
        try:
            # Registration happens before this second DB read, therefore an
            # event committed between the initial read and registration is
            # observed here even if no process-local notify reaches this worker.
            second = await asyncio.to_thread(
                self.list_after,
                actor,
                after_seq=bounded_after,
                limit=limit,
            )
            if second.cursor > bounded_after:
                return second

            await self.notifier.wait(handle, bounded_timeout)
            return await asyncio.to_thread(
                self.list_after,
                actor,
                after_seq=bounded_after,
                limit=limit,
            )
        finally:
            self.notifier.unregister(handle)

    def append_event(
        self,
        actor: TableActorContext,
        request: TableEventAppend,
    ) -> TableEvent:
        self.require_actor_current(actor)
        if request.execution_mode is TableExecutionMode.SYSTEM:
            raise TableEventActorUnauthorizedError(
                "Human/AI actor requests cannot claim system execution mode"
            )

        dump = request.model_dump(mode="json")
        try:
            stored = self.repository.append(
                room_id=actor.room_id,
                campaign_id=actor.campaign_id,
                session_id=actor.session_id,
                kind=request.kind,
                acting_seat_id=request.acting_seat_id or actor.seat_id,
                subject_seat_id=request.subject_seat_id,
                subject_character_id=request.subject_character_id,
                execution_mode=(
                    request.execution_mode.value
                    if request.execution_mode is not None
                    else TableExecutionMode.SELF.value
                ),
                visibility=request.visibility.value,
                recipient_seat_ids=request.recipient_seat_ids,
                payload_version=request.payload_version,
                payload=dict(dump["payload"]),
                idempotency_key=request.idempotency_key,
            )
        except TableEventSessionNotFoundPersistenceError as exc:
            raise TableEventNotFoundError(str(actor.session_id)) from exc
        except TableEventSessionNotActivePersistenceError as exc:
            raise TableEventSessionNotActiveError(str(actor.session_id)) from exc

        if self.notifier is not None:
            self.notifier.notify(actor.session_id)
        return self._present(stored)


__all__ = [
    "TableActorContext",
    "TableActorKind",
    "TableEvent",
    "TableEventActorUnauthorizedError",
    "TableEventAppend",
    "TableEventNotFoundError",
    "TableEventPage",
    "TableEventService",
    "TableEventSessionNotActiveError",
    "TableEventVisibility",
    "TableExecutionMode",
    "TableRuntimeCursor",
]
