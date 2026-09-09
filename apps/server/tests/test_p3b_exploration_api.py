from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest

from app.api.rooms.access import get_room_access_context
from app.api.rooms.dependencies import (
    get_exploration_action_service,
    get_exploration_stage_service,
    get_table_event_service,
)
from app.domain.rooms.exploration import StageImageContent, StageState
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.table_events import (
    TableActorContext,
    TableActorKind,
    TableEvent,
    TableEventVisibility,
    TableExecutionMode,
)
from app.main import app


class _EventService:
    def __init__(self, room_id: UUID, campaign_id: UUID, session_id: UUID) -> None:
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

    def resolve_human_actor(self, *, room_id, campaign_id, session_id, context):
        assert room_id == self.actor.room_id
        assert campaign_id == self.actor.campaign_id
        assert session_id == self.actor.session_id
        return self.actor.model_copy(update={"access_session_id": context.access_session_id})


class _StageService:
    def __init__(self, session_id: UUID) -> None:
        self.stage = StageState(session_id=session_id, revision=2, text="Gate")
        self.last_request = None

    def get_stage(self, actor):
        assert actor.session_id == self.stage.session_id
        return self.stage

    def replace_stage(self, actor, request):
        self.last_request = request
        self.stage = self.stage.model_copy(update={"revision": 3, "text": request.text})
        return self.stage

    def get_image(self, actor, image_id):
        return StageImageContent(
            id=image_id,
            media_type="image/png",
            filename='stage\r\nX-Injected: yes.png',
            data=b"\x89PNG\r\n\x1a\nP3B",
        )


class _ActionService:
    def __init__(self, session_id: UUID) -> None:
        self.session_id = session_id
        self.last_request = None

    def send(self, actor, request):
        self.last_request = request
        return TableEvent(
            id=uuid4(),
            session_id=self.session_id,
            seq=7,
            kind=f"exploration.{request.kind.value}",
            acting_seat_id=actor.seat_id,
            subject_seat_id=request.subject_seat_id,
            subject_character_id=None,
            execution_mode=TableExecutionMode.SELF,
            visibility=TableEventVisibility.PUBLIC,
            recipient_seat_ids=(),
            payload_version=1,
            payload={"text": request.text, "source_command": request.source_command},
            created_at=datetime.now(timezone.utc),
        )


@pytest.fixture
def exploration_api_fixture():
    room_id, campaign_id, session_id = uuid4(), uuid4(), uuid4()
    context = RoomAccessContext(
        room_id=room_id,
        access_session_id=uuid4(),
        authority=RoomAccessAuthority.DM,
    )
    events = _EventService(room_id, campaign_id, session_id)
    stage = _StageService(session_id)
    actions = _ActionService(session_id)
    app.dependency_overrides[get_room_access_context] = lambda: context
    app.dependency_overrides[get_table_event_service] = lambda: events
    app.dependency_overrides[get_exploration_stage_service] = lambda: stage
    app.dependency_overrides[get_exploration_action_service] = lambda: actions
    client = TestClient(app)
    try:
        yield room_id, campaign_id, session_id, stage, actions, client
    finally:
        for dependency in (
            get_room_access_context,
            get_table_event_service,
            get_exploration_stage_service,
            get_exploration_action_service,
        ):
            app.dependency_overrides.pop(dependency, None)


def test_stage_and_exploration_http_surface_share_session_actor_scope(exploration_api_fixture) -> None:
    room_id, campaign_id, session_id, stage, actions, client = exploration_api_fixture
    prefix = f"/api/rooms/{room_id}/campaigns/{campaign_id}/sessions/{session_id}"

    loaded = client.get(f"{prefix}/stage")
    assert loaded.status_code == 200
    assert loaded.json()["text"] == "Gate"

    replaced = client.put(
        f"{prefix}/stage",
        json={"expected_revision": 2, "text": "Bridge", "idempotency_key": "s1"},
    )
    assert replaced.status_code == 200
    assert replaced.json()["revision"] == 3
    assert stage.last_request.expected_revision == 2
    assert stage.last_request.idempotency_key == "s1"

    image_id = uuid4()
    image = client.get(f"{prefix}/stage/images/{image_id}")
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"
    assert image.headers["cache-control"] == "private, no-store"
    assert "content-disposition" not in image.headers
    assert "x-injected" not in image.headers
    assert image.content.startswith(b"\x89PNG")

    sent = client.post(f"{prefix}/exploration", json={
        "kind": "action",
        "subject_seat_id": str(uuid4()),
        "text": "Search the altar.",
        "source_command": "search",
        "idempotency_key": "a1",
    })
    assert sent.status_code == 200
    assert sent.json()["kind"] == "exploration.action"
    assert actions.last_request.source_command == "search"


def test_exploration_http_rejects_invalid_typed_shapes_before_service(exploration_api_fixture) -> None:
    room_id, campaign_id, session_id, _stage, actions, client = exploration_api_fixture
    prefix = f"/api/rooms/{room_id}/campaigns/{campaign_id}/sessions/{session_id}"

    missing_subject = client.post(f"{prefix}/exploration", json={
        "kind": "dialogue",
        "text": "Hello",
    })
    assert missing_subject.status_code == 422

    check_bypass = client.post(f"{prefix}/exploration", json={
        "kind": "ooc",
        "text": "Need a check",
        "source_command": "search",
    })
    assert check_bypass.status_code == 422
    assert actions.last_request is None
