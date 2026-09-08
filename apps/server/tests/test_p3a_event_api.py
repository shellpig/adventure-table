from __future__ import annotations

import inspect
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest

from app.api.rooms.access import get_room_access_context
from app.api.rooms.dependencies import get_table_event_service
from app.api.rooms.table_events import wait_table_events
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.table_events import (
    TableActorContext,
    TableActorKind,
    TableEventNotFoundError,
    TableEventPage,
    TableRuntimeCursor,
)
from app.main import app


class _ApiTableEventService:
    def __init__(self, room_id: UUID, campaign_id: UUID, session_id: UUID) -> None:
        self.room_id = room_id
        self.campaign_id = campaign_id
        self.session_id = session_id
        self.actor = TableActorContext(
            actor_kind=TableActorKind.HUMAN,
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            seat_id=uuid4(),
            controlled_seat_ids=(),
            role="dm",
            is_current_dm=True,
            access_session_id=uuid4(),
        )
        self.resolve_error: Exception | None = None
        self.wait_called = False

    def resolve_human_actor(self, *, room_id, campaign_id, session_id, context):
        assert room_id == self.room_id
        assert campaign_id == self.campaign_id
        assert session_id == self.session_id
        if self.resolve_error is not None:
            raise self.resolve_error
        return self.actor.model_copy(update={"access_session_id": context.access_session_id})

    def current_cursor(self, actor):
        assert actor.session_id == self.session_id
        return TableRuntimeCursor(
            session_id=self.session_id,
            revision=7,
            last_event_seq=12,
        )

    def list_after(self, actor, *, after_seq: int, limit: int):
        assert actor.session_id == self.session_id
        assert limit <= 200
        return TableEventPage(
            session_id=self.session_id,
            after_seq=after_seq,
            cursor=after_seq,
            current_seq=12,
            has_more=after_seq < 12,
            events=[],
        )

    async def wait_after(self, actor, *, after_seq: int, limit: int, timeout: float):
        assert actor.session_id == self.session_id
        assert timeout >= 0
        self.wait_called = True
        return self.list_after(actor, after_seq=after_seq, limit=limit)


@pytest.fixture
def table_event_api_fixture():
    room_id = uuid4()
    campaign_id = uuid4()
    session_id = uuid4()
    context = RoomAccessContext(
        room_id=room_id,
        access_session_id=uuid4(),
        authority=RoomAccessAuthority.DM,
    )
    service = _ApiTableEventService(room_id, campaign_id, session_id)
    app.dependency_overrides[get_room_access_context] = lambda: context
    app.dependency_overrides[get_table_event_service] = lambda: service
    client = TestClient(app)
    try:
        yield room_id, campaign_id, session_id, service, client
    finally:
        app.dependency_overrides.pop(get_room_access_context, None)
        app.dependency_overrides.pop(get_table_event_service, None)


def test_wait_http_endpoint_is_async_and_event_routes_use_bounded_cursor_contract(
    table_event_api_fixture,
) -> None:
    assert inspect.iscoroutinefunction(wait_table_events)
    room_id, campaign_id, session_id, service, client = table_event_api_fixture
    prefix = f"/api/rooms/{room_id}/campaigns/{campaign_id}/sessions/{session_id}"

    runtime = client.get(f"{prefix}/runtime")
    assert runtime.status_code == 200
    assert runtime.json()["revision"] == 7
    assert runtime.json()["last_event_seq"] == 12

    page = client.get(f"{prefix}/events?after=4&limit=5")
    assert page.status_code == 200
    assert page.json()["after_seq"] == 4
    assert page.json()["cursor"] == 4
    assert page.json()["current_seq"] == 12

    waited = client.get(f"{prefix}/events/wait?after=4&limit=5&timeout=0")
    assert waited.status_code == 200
    assert service.wait_called is True


def test_event_http_validation_and_scope_errors_do_not_expose_hidden_session(
    table_event_api_fixture,
) -> None:
    room_id, campaign_id, session_id, service, client = table_event_api_fixture
    prefix = f"/api/rooms/{room_id}/campaigns/{campaign_id}/sessions/{session_id}"

    assert client.get(f"{prefix}/events?after=-1").status_code == 422
    assert client.get(f"{prefix}/events?limit=201").status_code == 422
    assert client.get(f"{prefix}/events/wait?timeout=61").status_code == 422

    service.resolve_error = TableEventNotFoundError(str(session_id))
    response = client.get(f"{prefix}/events")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "session_not_found"
