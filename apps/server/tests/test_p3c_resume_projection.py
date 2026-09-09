from __future__ import annotations

from uuid import uuid4

from app.domain.rooms.pending_actions import PendingActionStatus, PendingActionView
from app.domain.rooms.rolls import (
    RollModifierMode,
    RollRequestType,
    RollRequestView,
    RollVisibility,
)
from app.domain.rooms.session_resume import SessionResumeService
from app.domain.rooms.table_events import (
    TableActorContext,
    TableActorKind,
    TableEventNotFoundError,
    TableEventPage,
    TableRuntimeCursor,
)
from app.domain.rooms.exploration import StageState


def _service(*, events, stage=None, rolls=None, pending=None) -> SessionResumeService:
    return SessionResumeService(
        session_service=None,  # type: ignore[arg-type]
        room_repository=None,  # type: ignore[arg-type]
        campaign_service=None,  # type: ignore[arg-type]
        seat_service=None,  # type: ignore[arg-type]
        character_repository=None,
        table_event_service=events,
        stage_service=stage,
        roll_service=rolls,
        pending_action_service=pending,
    )


def test_p3c_resume_projects_canonical_roll_and_pending_truth_for_actor() -> None:
    room_id = uuid4()
    campaign_id = uuid4()
    session_id = uuid4()
    access_session_id = uuid4()
    dm_seat_id = uuid4()
    target_seat_id = uuid4()
    character_id = uuid4()
    request_id = uuid4()
    action_id = uuid4()
    actor = TableActorContext(
        actor_kind=TableActorKind.HUMAN,
        room_id=room_id,
        campaign_id=campaign_id,
        session_id=session_id,
        seat_id=dm_seat_id,
        controlled_seat_ids=(),
        role="dm",
        is_current_dm=True,
        access_session_id=access_session_id,
    )

    class _Events:
        def resolve_human_actor(self, **_kwargs):
            return actor

        def current_cursor(self, resolved_actor):
            assert resolved_actor == actor
            return TableRuntimeCursor(session_id=session_id, revision=7, last_event_seq=11)

        def list_after(self, resolved_actor, *, after_seq, limit):
            assert resolved_actor == actor
            assert after_seq == 0
            assert limit == 50
            return TableEventPage(
                session_id=session_id,
                after_seq=after_seq,
                cursor=11,
                current_seq=11,
                has_more=False,
                events=[],
            )

    class _Stage:
        def get_stage(self, resolved_actor):
            assert resolved_actor == actor
            return StageState(session_id=session_id, revision=2, text="Hall")

    roll = RollRequestView(
        id=request_id,
        session_id=session_id,
        roll_group_id=uuid4(),
        target_seat_id=target_seat_id,
        target_character_id=character_id,
        request_type=RollRequestType.SKILL,
        ability_ref="dex",
        skill_ref="stealth",
        dc=15,
        modifier_mode=RollModifierMode.ADVANTAGE,
        flat_adjustment=1,
        visibility=RollVisibility.ROLLER_AND_DM,
        status="pending",
        requested_by_seat_id=dm_seat_id,
        version=1,
    )

    class _Rolls:
        def list_requests(self, resolved_actor):
            assert resolved_actor == actor
            return (roll,)

    pending_action = PendingActionView(
        id=action_id,
        session_id=session_id,
        acting_seat_id=target_seat_id,
        subject_seat_id=target_seat_id,
        subject_character_id=character_id,
        execution_mode="self",
        text="Sneak past the guard",
        intent_payload={"kind": "check"},
        status=PendingActionStatus.WAITING_FOR_ROLL,
        roll_request_id=request_id,
        version=2,
    )

    class _Pending:
        def list(self, resolved_actor):
            assert resolved_actor == actor
            return (pending_action,)

    runtime, recent, stage, roll_requests, pending_actions = _service(
        events=_Events(),
        stage=_Stage(),
        rolls=_Rolls(),
        pending=_Pending(),
    )._table_projection(
        room_id=room_id,
        campaign_id=campaign_id,
        session_id=session_id,
        caller_access_session_id=access_session_id,
    )

    assert runtime is not None and runtime.last_event_seq == 11
    assert recent is not None and recent.cursor == 11
    assert stage is not None and stage.text == "Hall"
    assert roll_requests == [roll]
    assert pending_actions == [pending_action]


def test_p3c_resume_fails_closed_for_nonparticipant_projection() -> None:
    class _Events:
        def resolve_human_actor(self, **_kwargs):
            raise TableEventNotFoundError("not a Session participant")

    projected = _service(events=_Events())._table_projection(
        room_id=uuid4(),
        campaign_id=uuid4(),
        session_id=uuid4(),
        caller_access_session_id=uuid4(),
    )

    assert projected == (None, None, None, [], [])
