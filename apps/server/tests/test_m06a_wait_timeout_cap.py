from __future__ import annotations

import asyncio
from collections.abc import Generator
from uuid import UUID, uuid4

from annotated_types import Le
from fastapi.testclient import TestClient
import pytest

from app.api.rooms.access import get_room_access_context
from app.api.rooms.dependencies import get_table_event_service
from app.domain.rooms import ai_guidance
from app.domain.rooms.ai_guidance import render_briefing
from app.domain.rooms.ai_tool_contract import WAIT_EVENT_MAX_TIMEOUT_SECONDS
from app.domain.rooms.ai_tools import AIToolApplicationService, WaitEventsInput
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.table_events import (
    TableActorContext,
    TableActorKind,
    TableEventNotifier,
    TableEventPage,
    TableEventService,
)
from app.main import app
from app.mcp.guide import render_guide


class _FakeNotifier:
    def __init__(self) -> None:
        self.recorded_timeouts: list[float] = []

    def notify(self, session_id: UUID) -> None:
        del session_id

    def register(self, session_id: UUID) -> object:
        del session_id
        return object()

    async def wait(self, handle: object, timeout: float) -> bool:
        del handle
        self.recorded_timeouts.append(timeout)
        return False

    def unregister(self, handle: object) -> None:
        del handle


class _TestTableEventService(TableEventService):
    def __init__(self, notifier: TableEventNotifier) -> None:
        super().__init__(repository=None, notifier=notifier)  # type: ignore[arg-type]

    def list_after(
        self,
        actor: TableActorContext,
        *,
        after_seq: int,
        limit: int,
        suppress_own: bool = False,
    ) -> TableEventPage:
        del limit, suppress_own
        return TableEventPage(
            session_id=actor.session_id,
            after_seq=after_seq,
            cursor=after_seq,
            current_seq=after_seq,
            has_more=False,
            events=[],
        )

    def resolve_human_actor(
        self,
        *,
        room_id: UUID,
        campaign_id: UUID,
        session_id: UUID,
        context: RoomAccessContext,
    ) -> TableActorContext:
        seat_id = uuid4()
        return TableActorContext(
            actor_kind=TableActorKind.HUMAN,
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            seat_id=seat_id,
            controlled_seat_ids=(seat_id,),
            role="player",
            access_session_id=context.access_session_id,
        )


class _StaticAIControllerService:
    def __init__(self, actor: TableActorContext) -> None:
        self.actor = actor

    def resolve_actor(self, token: str, *, touch: bool = True) -> TableActorContext:
        del token, touch
        return self.actor


def _make_ai_actor() -> TableActorContext:
    seat_id = uuid4()
    return TableActorContext(
        actor_kind=TableActorKind.AI,
        room_id=uuid4(),
        campaign_id=uuid4(),
        session_id=uuid4(),
        seat_id=seat_id,
        controlled_seat_ids=(seat_id,),
        role="player",
        is_current_dm=False,
        access_session_id=None,
        ai_controller_grant_id=uuid4(),
        grant_generation=1,
    )


def _make_human_actor() -> TableActorContext:
    seat_id = uuid4()
    return TableActorContext(
        actor_kind=TableActorKind.HUMAN,
        room_id=uuid4(),
        campaign_id=uuid4(),
        session_id=uuid4(),
        seat_id=seat_id,
        controlled_seat_ids=(seat_id,),
        role="player",
        is_current_dm=False,
        access_session_id=uuid4(),
    )


def _build_ai_tool_service(
    controller_service: _StaticAIControllerService,
    event_service: TableEventService,
) -> AIToolApplicationService:
    return AIToolApplicationService(
        ai_controller_service=controller_service,  # type: ignore[arg-type]
        session_service=None,  # type: ignore[arg-type]
        stage_service=None,  # type: ignore[arg-type]
        action_service=None,  # type: ignore[arg-type]
        roll_service=None,  # type: ignore[arg-type]
        state_service=None,  # type: ignore[arg-type]
        pending_action_service=None,  # type: ignore[arg-type]
        event_service=event_service,
        workspace_service=None,  # type: ignore[arg-type]
    )


@pytest.fixture
def human_route_client() -> Generator[tuple[UUID, UUID, UUID, _FakeNotifier, TestClient], None, None]:
    room_id = uuid4()
    campaign_id = uuid4()
    session_id = uuid4()
    notifier = _FakeNotifier()
    service = _TestTableEventService(notifier)
    app.dependency_overrides[get_room_access_context] = lambda: RoomAccessContext(
        room_id=room_id,
        access_session_id=uuid4(),
        authority=RoomAccessAuthority.MEMBER,
    )
    app.dependency_overrides[get_table_event_service] = lambda: service
    client = TestClient(app)
    try:
        yield room_id, campaign_id, session_id, notifier, client
    finally:
        app.dependency_overrides.pop(get_room_access_context, None)
        app.dependency_overrides.pop(get_table_event_service, None)


def test_mcp_wait_for_event_passes_full_timeout_to_notifier() -> None:
    notifier = _FakeNotifier()
    event_service = _TestTableEventService(notifier)
    actor = _make_ai_actor()
    controller_service = _StaticAIControllerService(actor)
    facade = _build_ai_tool_service(controller_service, event_service)

    result = asyncio.run(
        facade.wait_for_event("fake-token", WaitEventsInput(timeout=120))
    )
    assert result["events"] == []
    # Default wait suppresses own echoes (M06-B), whose loop passes the time left before the deadline.
    assert notifier.recorded_timeouts == [pytest.approx(120.0, abs=1.0)]


def test_mcp_wait_for_event_passes_shorter_timeout_unchanged() -> None:
    notifier = _FakeNotifier()
    event_service = _TestTableEventService(notifier)
    actor = _make_ai_actor()
    controller_service = _StaticAIControllerService(actor)
    facade = _build_ai_tool_service(controller_service, event_service)

    result = asyncio.run(
        facade.wait_for_event("fake-token", WaitEventsInput(timeout=90))
    )
    assert result["events"] == []
    assert notifier.recorded_timeouts == [pytest.approx(90.0, abs=1.0)]


def test_wait_after_default_cap_is_sixty() -> None:
    notifier = _FakeNotifier()
    event_service = _TestTableEventService(notifier)
    actor = _make_human_actor()

    result = asyncio.run(
        event_service.wait_after(actor, after_seq=0, limit=50, timeout=120.0)
    )
    assert result.events == []
    assert notifier.recorded_timeouts == [60.0]


def test_wait_cap_single_source() -> None:
    timeout_field = WaitEventsInput.model_fields["timeout"]
    le_constraint = next(item.le for item in timeout_field.metadata if isinstance(item, Le))
    assert le_constraint == WAIT_EVENT_MAX_TIMEOUT_SECONDS
    assert ai_guidance.WAIT_TIMEOUT_SECONDS == int(WAIT_EVENT_MAX_TIMEOUT_SECONDS)

    actor = _make_ai_actor()
    controller_service = _StaticAIControllerService(actor)
    notifier = _FakeNotifier()
    event_service = _TestTableEventService(notifier)

    recorded_kwargs: dict[str, float] = {}

    async def spy_wait_after(
        actor_arg: TableActorContext,
        *,
        after_seq: int,
        limit: int,
        timeout: float,
        max_timeout: float = 60.0,
        suppress_own: bool = False,
    ) -> TableEventPage:
        del actor_arg, after_seq, limit, timeout, suppress_own
        recorded_kwargs["max_timeout"] = max_timeout
        return TableEventPage(
            session_id=actor.session_id,
            after_seq=0,
            cursor=0,
            current_seq=0,
            has_more=False,
            events=[],
        )

    event_service.wait_after = spy_wait_after  # type: ignore[method-assign]
    facade = _build_ai_tool_service(controller_service, event_service)

    asyncio.run(
        facade.wait_for_event("fake-token", WaitEventsInput(timeout=30))
    )
    assert recorded_kwargs.get("max_timeout") == WAIT_EVENT_MAX_TIMEOUT_SECONDS


def test_guide_and_briefing_show_cap_seconds() -> None:
    expected_seconds = str(int(WAIT_EVENT_MAX_TIMEOUT_SECONDS))

    for locale in ("en", "zh-TW"):
        guide = render_guide(locale)
        assert expected_seconds in guide

    for role in ("dm", "player"):
        briefing = render_briefing(role=role, mode="active_session")
        assert expected_seconds in briefing


def test_human_events_wait_uses_sixty_second_cap(
    human_route_client: tuple[UUID, UUID, UUID, _FakeNotifier, TestClient],
) -> None:
    room_id, campaign_id, session_id, notifier, client = human_route_client
    url = f"/api/rooms/{room_id}/campaigns/{campaign_id}/sessions/{session_id}/events/wait?timeout=60"
    response = client.get(url)
    assert response.status_code == 200
    assert notifier.recorded_timeouts == [60.0]


def test_human_events_wait_rejects_timeout_above_sixty(
    human_route_client: tuple[UUID, UUID, UUID, _FakeNotifier, TestClient],
) -> None:
    room_id, campaign_id, session_id, _notifier, client = human_route_client
    url = f"/api/rooms/{room_id}/campaigns/{campaign_id}/sessions/{session_id}/events/wait?timeout=61"
    response = client.get(url)
    assert response.status_code == 422
