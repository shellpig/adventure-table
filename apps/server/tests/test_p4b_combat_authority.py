from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.domain.combat.lifecycle import CombatService
from app.domain.rooms.table_events import (
    TableActorContext,
    TableActorKind,
    TableEventActorUnauthorizedError,
)


class _Repository:
    def __init__(self, seat_id):
        self.seat_id = seat_id

    def controlling_seat_for_character(self, **_kwargs):
        return self.seat_id


class _Events:
    def require_actor_current(self, _actor):
        return None


def _actor(*, dm: bool) -> TableActorContext:
    seat_id = uuid4()
    return TableActorContext(
        actor_kind=TableActorKind.HUMAN,
        room_id=uuid4(),
        campaign_id=uuid4(),
        session_id=uuid4(),
        seat_id=seat_id,
        controlled_seat_ids=(seat_id,),
        role="dm" if dm else "player",
        is_current_dm=dm,
        access_session_id=uuid4(),
    )


def _service(subject_seat_id):
    return CombatService(_Repository(subject_seat_id), _Events(), None, None)


def test_current_dm_can_explicitly_proxy_character_absent_from_new_session() -> None:
    actor = _actor(dm=True)
    entry = SimpleNamespace(subject_kind="character", character_id=uuid4())

    subject_seat_id, execution_mode = _service(None)._authorize_entry(actor, entry)

    assert subject_seat_id is None
    assert execution_mode == "dm_proxy"


def test_absent_character_is_not_rebound_to_unrelated_player_controller() -> None:
    actor = _actor(dm=False)
    entry = SimpleNamespace(subject_kind="character", character_id=uuid4())

    with pytest.raises(TableEventActorUnauthorizedError):
        _service(None)._authorize_entry(actor, entry)


def test_current_dm_proxy_for_present_character_keeps_subject_seat_identity() -> None:
    actor = _actor(dm=True)
    subject_seat_id = uuid4()
    entry = SimpleNamespace(subject_kind="character", character_id=uuid4())

    resolved_seat_id, execution_mode = _service(subject_seat_id)._authorize_entry(actor, entry)

    assert resolved_seat_id == subject_seat_id
    assert execution_mode == "dm_proxy"
