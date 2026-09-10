from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier, Lock
from uuid import uuid4

from app.domain.rooms.rolls import FormalRollInput, RollEngine, RollService
from app.domain.rooms.table_events import TableActorContext, TableActorKind
from app.persistence.rooms.exploration_subjects import StoredExplorationSubject
from app.persistence.rooms.p3c_rolls import (
    RollRequestNotPendingPersistenceError,
    StoredRollRequest,
    StoredRollResult,
)


class _Subjects:
    def __init__(self, subject: StoredExplorationSubject) -> None:
        self.subject = subject

    def resolve_subject(self, **_kwargs) -> StoredExplorationSubject:
        return self.subject


class _Events:
    notifier = None

    def require_actor_current(self, _actor: TableActorContext) -> None:
        return None


class _Modifier:
    def modifier_for(self, **_kwargs) -> int:
        return 3


class _CountingRng:
    def __init__(self) -> None:
        self.calls = 0
        self.lock = Lock()

    def randint(self, _low: int, _high: int) -> int:
        with self.lock:
            self.calls += 1
        return 11


class _SerializedRepository:
    """Model the repository critical section after both callers saw no result."""

    def __init__(self, request: StoredRollRequest) -> None:
        self.request = request
        self.result: StoredRollResult | None = None
        self.initial_reads = 0
        self.initial_lock = Lock()
        self.initial_barrier = Barrier(2)
        self.completion_lock = Lock()
        self.factory_calls = 0

    def get_request(self, **_kwargs) -> StoredRollRequest:
        return self.request

    def get_result_for_request(self, **_kwargs) -> StoredRollResult | None:
        with self.initial_lock:
            is_initial = self.initial_reads < 2
            if is_initial:
                self.initial_reads += 1
        if is_initial:
            self.initial_barrier.wait(timeout=5)
            return None
        return self.result

    def complete_request(self, *, result_factory, **_kwargs):
        with self.completion_lock:
            if self.result is not None:
                raise RollRequestNotPendingPersistenceError(str(self.request.id))
            computation = result_factory()
            self.factory_calls += 1
            now = datetime.now(timezone.utc)
            self.result = StoredRollResult(
                id=uuid4(),
                roll_request_id=self.request.id,
                session_id=self.request.session_id,
                acting_seat_id=self.request.target_seat_id,
                subject_seat_id=self.request.target_seat_id,
                subject_character_id=self.request.target_character_id,
                execution_mode="self",
                source=computation.source,
                formula=computation.formula,
                raw_dice=computation.raw_dice,
                kept_dice=computation.kept_dice,
                base_modifier=computation.base_modifier,
                flat_adjustment=computation.flat_adjustment,
                total=computation.total,
                visibility=self.request.visibility,
                created_at=now,
            )
            return self.result, None


def test_concurrent_formal_submit_consumes_rng_only_inside_winning_completion() -> None:
    now = datetime.now(timezone.utc)
    room_id = uuid4()
    campaign_id = uuid4()
    session_id = uuid4()
    seat_id = uuid4()
    character_id = uuid4()
    request = StoredRollRequest(
        id=uuid4(),
        session_id=session_id,
        roll_group_id=uuid4(),
        target_seat_id=seat_id,
        target_character_id=character_id,
        request_type="ability",
        ability_ref="str",
        skill_ref=None,
        dc=12,
        modifier_mode="normal",
        flat_adjustment=0,
        visibility="public",
        status="pending",
        requested_by_seat_id=uuid4(),
        created_at=now,
        resolved_at=None,
        version=1,
    )
    repository = _SerializedRepository(request)
    rng = _CountingRng()
    service = RollService(
        repository=repository,  # type: ignore[arg-type]
        subject_repository=_Subjects(
            StoredExplorationSubject(
                seat_id=seat_id,
                role="player",
                active_character_id=character_id,
            )
        ),  # type: ignore[arg-type]
        table_event_service=_Events(),  # type: ignore[arg-type]
        modifier_resolver=_Modifier(),
        engine=RollEngine(rng=rng),  # type: ignore[arg-type]
    )
    actor = TableActorContext(
        actor_kind=TableActorKind.HUMAN,
        room_id=room_id,
        campaign_id=campaign_id,
        session_id=session_id,
        seat_id=seat_id,
        controlled_seat_ids=(seat_id,),
        role="player",
        access_session_id=uuid4(),
    )

    def submit():
        return service.complete_formal(actor, FormalRollInput(roll_request_id=request.id))

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: submit(), range(2)))

    assert repository.factory_calls == 1
    assert rng.calls == 1
    assert results[0].id == results[1].id
    assert results[0].raw_dice == (11,)
    assert results[0].total == 14
