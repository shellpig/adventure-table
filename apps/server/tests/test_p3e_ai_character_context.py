from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.domain.rooms.ai_tools import AIToolApplicationService
from app.domain.rooms.table_events import TableActorContext, TableActorKind
from app.domain.rooms.workspace import (
    RoomCharacterWorkspaceService,
    RoomWorkspaceScopeError,
)


class _Controller:
    def __init__(self, actor: TableActorContext) -> None:
        self.actor = actor

    def resolve_actor(self, token: str, *, touch: bool = True) -> TableActorContext:
        assert token == "ai-token"
        assert touch is True
        return self.actor


class _SessionService:
    def __init__(self, participants: list[SimpleNamespace]) -> None:
        self.participants = participants

    def get_session(self, room_id: UUID, campaign_id: UUID, session_id: UUID):
        return SimpleNamespace(participants=self.participants)


class _Character:
    def __init__(self, character_id: UUID) -> None:
        self.character_id = character_id

    def model_dump(self, *, mode: str):
        assert mode == "json"
        return {"id": str(self.character_id), "name": "Scoped Hero"}


class _Workspace:
    """Intentionally exposes no persistence repository attributes."""

    def __init__(self, character_id: UUID) -> None:
        self.character = _Character(character_id)
        self.calls: list[tuple[UUID, UUID]] = []

    def get_character(self, room_id: UUID, character_id: UUID):
        self.calls.append((room_id, character_id))
        return self.character


def _facade(
    actor: TableActorContext,
    participants: list[SimpleNamespace],
    workspace: _Workspace,
) -> AIToolApplicationService:
    return AIToolApplicationService(
        ai_controller_service=_Controller(actor),  # type: ignore[arg-type]
        session_service=_SessionService(participants),  # type: ignore[arg-type]
        stage_service=None,  # type: ignore[arg-type]
        action_service=None,  # type: ignore[arg-type]
        roll_service=None,  # type: ignore[arg-type]
        state_service=None,  # type: ignore[arg-type]
        pending_action_service=None,  # type: ignore[arg-type]
        event_service=None,  # type: ignore[arg-type]
        workspace_service=workspace,  # type: ignore[arg-type]
    )


def test_ai_player_character_context_uses_only_scoped_workspace_read() -> None:
    room_id, campaign_id, session_id = uuid4(), uuid4(), uuid4()
    own_seat_id, other_seat_id = uuid4(), uuid4()
    own_character_id, other_character_id = uuid4(), uuid4()
    actor = TableActorContext(
        actor_kind=TableActorKind.AI,
        room_id=room_id,
        campaign_id=campaign_id,
        session_id=session_id,
        seat_id=own_seat_id,
        controlled_seat_ids=(own_seat_id,),
        role="player",
        ai_controller_grant_id=uuid4(),
        grant_generation=3,
    )
    workspace = _Workspace(own_character_id)
    facade = _facade(
        actor,
        [
            SimpleNamespace(
                seat_id=other_seat_id,
                active_character_id=other_character_id,
            ),
            SimpleNamespace(
                seat_id=own_seat_id,
                active_character_id=own_character_id,
            ),
        ],
        workspace,
    )

    result = facade.get_character_context("ai-token")

    assert result == {"id": str(own_character_id), "name": "Scoped Hero"}
    assert workspace.calls == [(room_id, own_character_id)]


def test_workspace_scoped_character_read_checks_room_before_repository_load() -> None:
    room_id, wrong_room_id, character_id = uuid4(), uuid4(), uuid4()
    loaded: list[UUID] = []

    workspace = object.__new__(RoomCharacterWorkspaceService)
    workspace.workspace_repository = SimpleNamespace(
        character_room_id=lambda candidate: room_id if candidate == character_id else None
    )
    workspace.character_repository = SimpleNamespace(
        load_character=lambda candidate: loaded.append(candidate) or _Character(candidate)
    )

    character = workspace.get_character(room_id, character_id)
    assert character.character_id == character_id
    assert loaded == [character_id]

    with pytest.raises(RoomWorkspaceScopeError):
        workspace.get_character(wrong_room_id, character_id)
    assert loaded == [character_id]
