from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.domain.character.fixture import build_p0_fighter_wizard_fixture, build_p0_fighter_wizard_state
from app.domain.character.schemas import PersistedCharacter
from app.domain.rooms.table_character_state import (
    TableCharacterStatePatch,
    TableCharacterStateService,
)
from app.domain.rooms.table_events import (
    TableActorContext,
    TableActorKind,
    TableEventActorUnauthorizedError,
)


def _actor(*, seat_id, controlled=(), is_dm=False) -> TableActorContext:
    return TableActorContext(
        actor_kind=TableActorKind.HUMAN,
        room_id=uuid4(),
        campaign_id=uuid4(),
        session_id=uuid4(),
        seat_id=seat_id,
        controlled_seat_ids=tuple(controlled),
        role="dm" if is_dm else "player",
        is_current_dm=is_dm,
        access_session_id=uuid4(),
    )


def _character(character_id) -> PersistedCharacter:
    build = build_p0_fighter_wizard_fixture()
    return PersistedCharacter(
        id=character_id,
        name="Mira",
        ruleset=build.ruleset,
        current_version_id=uuid4(),
        version_no=1,
        build=build,
        state=build_p0_fighter_wizard_state(build),
        archived_at=None,
    )


class _Events:
    notifier = None

    def require_actor_current(self, actor):
        self.actor = actor


class _Subjects:
    def __init__(self, *, seat_id, character_id):
        self.seat_id = seat_id
        self.character_id = character_id

    def resolve_subject(self, **_kwargs):
        return SimpleNamespace(
            seat_id=self.seat_id,
            role="player",
            active_character_id=self.character_id,
        )


class _Repository:
    def __init__(self, character_id):
        self.character_id = character_id
        self.calls = []

    def apply_patch(self, **kwargs):
        self.calls.append(kwargs)
        return _character(self.character_id)


def test_table_state_patch_requires_a_real_canonical_change() -> None:
    with pytest.raises(ValueError):
        TableCharacterStatePatch()
    with pytest.raises(ValueError):
        TableCharacterStatePatch(current_hp=None)

    patch = TableCharacterStatePatch(current_hp=7, temporary_hp=3)
    assert patch.state_changes() == {"current_hp": 7, "temporary_hp": 3}


def test_controlled_player_state_write_uses_self_execution_identity() -> None:
    player_seat = uuid4()
    character_id = uuid4()
    actor = _actor(seat_id=player_seat, controlled=(player_seat,))
    repository = _Repository(character_id)
    events = _Events()
    service = TableCharacterStateService(
        repository,
        _Subjects(seat_id=player_seat, character_id=character_id),
        events,
    )

    updated = service.apply_patch(
        actor,
        subject_seat_id=player_seat,
        patch=TableCharacterStatePatch(current_hp=5),
    )

    assert updated.id == character_id
    assert events.actor == actor
    call = repository.calls[0]
    assert call["acting_seat_id"] == player_seat
    assert call["subject_seat_id"] == player_seat
    assert call["subject_character_id"] == character_id
    assert call["execution_mode"] == "self"


def test_current_dm_proxy_preserves_acting_and_subject_identity() -> None:
    dm_seat = uuid4()
    player_seat = uuid4()
    character_id = uuid4()
    actor = _actor(seat_id=dm_seat, controlled=(dm_seat,), is_dm=True)
    repository = _Repository(character_id)
    service = TableCharacterStateService(
        repository,
        _Subjects(seat_id=player_seat, character_id=character_id),
        _Events(),
    )

    service.apply_patch(
        actor,
        subject_seat_id=player_seat,
        patch=TableCharacterStatePatch(temporary_hp=4),
    )

    call = repository.calls[0]
    assert call["acting_seat_id"] == dm_seat
    assert call["subject_seat_id"] == player_seat
    assert call["subject_character_id"] == character_id
    assert call["execution_mode"] == "dm_proxy"


def test_unrelated_player_cannot_write_another_seats_state() -> None:
    caller_seat = uuid4()
    target_seat = uuid4()
    character_id = uuid4()
    repository = _Repository(character_id)
    service = TableCharacterStateService(
        repository,
        _Subjects(seat_id=target_seat, character_id=character_id),
        _Events(),
    )

    with pytest.raises(TableEventActorUnauthorizedError):
        service.apply_patch(
            _actor(seat_id=caller_seat, controlled=(caller_seat,)),
            subject_seat_id=target_seat,
            patch=TableCharacterStatePatch(current_hp=1),
        )

    assert repository.calls == []
