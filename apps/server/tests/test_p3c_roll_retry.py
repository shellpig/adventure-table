from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.domain.rooms.rolls import FormalRollInput, RollEngine, RollService
from app.domain.rooms.table_events import TableActorContext, TableActorKind
from app.persistence.rooms.exploration_subjects import StoredExplorationSubject
from app.persistence.rooms.p3c_rolls import StoredRollRequest, StoredRollResult


class StaticSubjectRepository:
    def __init__(self, subject: StoredExplorationSubject) -> None:
        self.subject = subject

    def resolve_subject(self, **_kwargs) -> StoredExplorationSubject:
        return self.subject


class ResolvedRollRepository:
    def __init__(
        self,
        request: StoredRollRequest,
        result: StoredRollResult,
    ) -> None:
        self.request = request
        self.result = result
        self.complete_calls = 0

    def get_request(self, **_kwargs) -> StoredRollRequest:
        return self.request

    def get_result_for_request(self, **_kwargs) -> StoredRollResult:
        return self.result

    def complete_request(self, **_kwargs):
        self.complete_calls += 1
        raise AssertionError("resolved retry must not attempt persistence completion")


class CurrentActorTableEvents:
    notifier = None

    def require_actor_current(self, _actor: TableActorContext) -> None:
        return None


class CountingModifierResolver:
    def __init__(self) -> None:
        self.calls = 0

    def modifier_for(self, **_kwargs) -> int:
        self.calls += 1
        return 3


class FailRng:
    def __init__(self) -> None:
        self.calls = 0

    def randint(self, _low: int, _high: int) -> int:
        self.calls += 1
        raise AssertionError("resolved retry must not generate new dice")


def test_resolved_formal_retry_returns_canonical_result_without_new_rng() -> None:
    now = datetime.now(timezone.utc)
    room_id = uuid4()
    campaign_id = uuid4()
    session_id = uuid4()
    seat_id = uuid4()
    character_id = uuid4()
    request_id = uuid4()
    result_id = uuid4()

    request = StoredRollRequest(
        id=request_id,
        session_id=session_id,
        roll_group_id=uuid4(),
        target_seat_id=seat_id,
        target_character_id=character_id,
        request_type="ability",
        ability_ref="str",
        skill_ref=None,
        dc=15,
        modifier_mode="normal",
        flat_adjustment=0,
        visibility="public",
        status="resolved",
        requested_by_seat_id=uuid4(),
        created_at=now,
        resolved_at=now,
        version=2,
    )
    canonical = StoredRollResult(
        id=result_id,
        roll_request_id=request_id,
        session_id=session_id,
        acting_seat_id=seat_id,
        subject_seat_id=seat_id,
        subject_character_id=character_id,
        execution_mode="self",
        source="server",
        formula="1d20+3",
        raw_dice=(17,),
        kept_dice=(17,),
        base_modifier=3,
        flat_adjustment=0,
        total=20,
        visibility="public",
        created_at=now,
    )
    repository = ResolvedRollRepository(request, canonical)
    modifier_resolver = CountingModifierResolver()
    rng = FailRng()
    service = RollService(
        repository=repository,  # type: ignore[arg-type]
        subject_repository=StaticSubjectRepository(
            StoredExplorationSubject(
                seat_id=seat_id,
                role="player",
                active_character_id=character_id,
            )
        ),  # type: ignore[arg-type]
        table_event_service=CurrentActorTableEvents(),  # type: ignore[arg-type]
        modifier_resolver=modifier_resolver,
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

    result = service.complete_formal(
        actor,
        FormalRollInput(roll_request_id=request_id),
    )

    assert result.id == result_id
    assert result.total == 20
    assert result.raw_dice == (17,)
    assert repository.complete_calls == 0
    assert modifier_resolver.calls == 0
    assert rng.calls == 0
