from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from uuid import uuid4

from sqlalchemy import create_engine, text

from app.api.rooms.table_event_wait import ProcessLocalTableEventNotifier
from app.domain.rooms.table_events import (
    TableActorContext,
    TableActorKind,
    TableEvent,
    TableEventPage,
    TableEventService,
    TableEventVisibility,
)


def _actor(session_id):
    seat_id = uuid4()
    return TableActorContext(
        actor_kind=TableActorKind.HUMAN,
        room_id=uuid4(),
        campaign_id=uuid4(),
        session_id=session_id,
        seat_id=seat_id,
        controlled_seat_ids=(seat_id,),
        role="player",
        access_session_id=uuid4(),
    )


class _DbBackedWaitService:
    wait_after = TableEventService.wait_after

    def __init__(self, engine, notifier, session_id) -> None:
        self.engine = engine
        self.notifier = notifier
        self.session_id = session_id
        self._lock = Lock()
        self._event: TableEvent | None = None
        self.list_calls = 0

    def publish(self, event: TableEvent) -> None:
        with self._lock:
            self._event = event

    def list_after(self, actor, *, after_seq: int, limit: int) -> TableEventPage:
        # One intentionally tiny DB query models the real service's sync
        # authorize/list operation. The connection is closed before returning.
        with self.engine.connect() as connection:
            assert connection.scalar(text("SELECT 1")) == 1
        with self._lock:
            self.list_calls += 1
            event = self._event
        events = [event] if event is not None and event.seq > after_seq else []
        current_seq = event.seq if event is not None else 0
        cursor = current_seq if current_seq > after_seq else after_seq
        return TableEventPage(
            session_id=actor.session_id,
            after_seq=after_seq,
            cursor=cursor,
            current_seq=current_seq,
            has_more=False,
            events=events[:limit],
        )


def _event(session_id, seq: int = 1) -> TableEvent:
    return TableEvent(
        id=uuid4(),
        session_id=session_id,
        seq=seq,
        kind="diagnostic.wake",
        acting_seat_id=None,
        subject_seat_id=None,
        subject_character_id=None,
        execution_mode=None,
        visibility=TableEventVisibility.PUBLIC,
        recipient_seat_ids=(),
        payload_version=1,
        payload={"seq": seq},
        created_at=datetime.now(timezone.utc),
    )


async def _wait_until(predicate, *, timeout: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("condition was not reached before timeout")
        await asyncio.sleep(0.005)


def test_wait_wakes_for_notify_and_final_db_recheck_is_canonical(tmp_path: Path) -> None:
    async def scenario() -> None:
        engine = create_engine(
            f"sqlite+pysqlite:///{tmp_path / 'wake.sqlite'}",
            connect_args={"check_same_thread": False},
            pool_size=1,
            max_overflow=0,
        )
        notifier = ProcessLocalTableEventNotifier()
        session_id = uuid4()
        actor = _actor(session_id)
        service = _DbBackedWaitService(engine, notifier, session_id)
        try:
            task = asyncio.create_task(
                service.wait_after(actor, after_seq=0, limit=10, timeout=1.0)
            )
            await _wait_until(lambda: notifier.waiter_count(session_id) == 1)
            service.publish(_event(session_id))
            notifier.notify(session_id)
            page = await asyncio.wait_for(task, timeout=1.0)
            assert [event.seq for event in page.events] == [1]
            assert page.cursor == 1
            assert notifier.waiter_count() == 0
            assert engine.pool.checkedout() == 0
        finally:
            engine.dispose()

    asyncio.run(scenario())


def test_wait_recovers_missed_process_local_notify_from_db_cursor(tmp_path: Path) -> None:
    async def scenario() -> None:
        engine = create_engine(
            f"sqlite+pysqlite:///{tmp_path / 'missed.sqlite'}",
            connect_args={"check_same_thread": False},
            pool_size=1,
            max_overflow=0,
        )
        notifier = ProcessLocalTableEventNotifier()
        session_id = uuid4()
        actor = _actor(session_id)
        service = _DbBackedWaitService(engine, notifier, session_id)
        try:
            task = asyncio.create_task(
                service.wait_after(actor, after_seq=0, limit=10, timeout=0.05)
            )
            await _wait_until(
                lambda: notifier.waiter_count(session_id) == 1 and service.list_calls >= 2
            )
            service.publish(_event(session_id))
            # Deliberately do not call notifier.notify(). The timeout path must
            # still re-read the durable cursor and deliver the new event.
            page = await asyncio.wait_for(task, timeout=1.0)
            assert [event.seq for event in page.events] == [1]
            assert service.list_calls >= 3
            assert notifier.waiter_count() == 0
            assert engine.pool.checkedout() == 0
        finally:
            engine.dispose()

    asyncio.run(scenario())


def test_many_idle_waiters_hold_no_db_connection_and_do_not_starve_db_request(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        engine = create_engine(
            f"sqlite+pysqlite:///{tmp_path / 'pool.sqlite'}",
            connect_args={"check_same_thread": False},
            pool_size=1,
            max_overflow=0,
            pool_timeout=0.2,
        )
        notifier = ProcessLocalTableEventNotifier()
        session_id = uuid4()
        actor = _actor(session_id)
        service = _DbBackedWaitService(engine, notifier, session_id)
        waiter_count = 24
        tasks = [
            asyncio.create_task(
                service.wait_after(actor, after_seq=0, limit=10, timeout=2.0)
            )
            for _ in range(waiter_count)
        ]
        try:
            await _wait_until(
                lambda: notifier.waiter_count(session_id) == waiter_count
                and service.list_calls >= waiter_count * 2
            )
            assert engine.pool.checkedout() == 0

            def ordinary_db_request() -> int:
                with engine.connect() as connection:
                    return int(connection.scalar(text("SELECT 7")))

            result = await asyncio.wait_for(
                asyncio.to_thread(ordinary_db_request),
                timeout=0.3,
            )
            assert result == 7
            assert engine.pool.checkedout() == 0
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.sleep(0)
            assert notifier.waiter_count() == 0
            assert engine.pool.checkedout() == 0
            engine.dispose()

    asyncio.run(scenario())


def test_wait_timeout_and_cancellation_cleanup_registration(tmp_path: Path) -> None:
    async def scenario() -> None:
        engine = create_engine(
            f"sqlite+pysqlite:///{tmp_path / 'cleanup.sqlite'}",
            connect_args={"check_same_thread": False},
            pool_size=1,
            max_overflow=0,
        )
        notifier = ProcessLocalTableEventNotifier()
        session_id = uuid4()
        actor = _actor(session_id)
        service = _DbBackedWaitService(engine, notifier, session_id)
        try:
            timeout_page = await service.wait_after(
                actor,
                after_seq=0,
                limit=10,
                timeout=0.01,
            )
            assert timeout_page.events == []
            assert notifier.waiter_count() == 0

            task = asyncio.create_task(
                service.wait_after(actor, after_seq=0, limit=10, timeout=10.0)
            )
            await _wait_until(
                lambda: notifier.waiter_count(session_id) == 1 and service.list_calls >= 4
            )
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            else:
                raise AssertionError("cancelled wait unexpectedly completed")
            await asyncio.sleep(0)
            assert notifier.waiter_count() == 0
            assert engine.pool.checkedout() == 0
        finally:
            engine.dispose()

    asyncio.run(scenario())
