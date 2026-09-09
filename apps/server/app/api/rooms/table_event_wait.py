from __future__ import annotations

import asyncio
from dataclasses import dataclass
from threading import Lock
from uuid import UUID


@dataclass(frozen=True)
class TableEventWaitHandle:
    session_id: UUID
    loop: asyncio.AbstractEventLoop
    event: asyncio.Event


class ProcessLocalTableEventNotifier:
    """Best-effort wake hint for durable DB-backed event cursors.

    The notifier never owns event truth. It only wakes local waiters; every wait
    path rechecks the database after registration and again after wake/timeout.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._waiters: dict[UUID, set[TableEventWaitHandle]] = {}

    def register(self, session_id: UUID) -> TableEventWaitHandle:
        handle = TableEventWaitHandle(
            session_id=session_id,
            loop=asyncio.get_running_loop(),
            event=asyncio.Event(),
        )
        with self._lock:
            self._waiters.setdefault(session_id, set()).add(handle)
        return handle

    async def wait(self, handle: TableEventWaitHandle, timeout: float) -> bool:
        if handle.event.is_set():
            return True
        if timeout <= 0:
            return False
        try:
            await asyncio.wait_for(handle.event.wait(), timeout=timeout)
            return True
        except TimeoutError:
            return False

    def unregister(self, handle: TableEventWaitHandle) -> None:
        with self._lock:
            session_waiters = self._waiters.get(handle.session_id)
            if session_waiters is None:
                return
            session_waiters.discard(handle)
            if not session_waiters:
                self._waiters.pop(handle.session_id, None)

    def notify(self, session_id: UUID) -> None:
        with self._lock:
            waiters = tuple(self._waiters.get(session_id, ()))
        for handle in waiters:
            try:
                handle.loop.call_soon_threadsafe(handle.event.set)
            except RuntimeError:
                # A disconnected request may have closed its loop before the
                # synchronous writer finished notifying. DB cursor durability is
                # unaffected; cleanup removes the stale registration.
                continue

    def waiter_count(self, session_id: UUID | None = None) -> int:
        with self._lock:
            if session_id is not None:
                return len(self._waiters.get(session_id, ()))
            return sum(len(waiters) for waiters in self._waiters.values())


__all__ = ["ProcessLocalTableEventNotifier", "TableEventWaitHandle"]
