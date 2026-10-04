"""M07-D D1: tactical start intent (F03) and retry ordering (F09).

F03: ``include_active_party`` is part of the idempotency intent — same key
with a changed value is a 409, same value retries into the original Combat.
F09: same-key retry resolves the committed result before touching the map
(archive before/after combat end both return the original Combat; a
different intent is still a 409). The archive-before-end path was already
locked by ``test_retry_after_map_archived_returns_original_without_touching_map``;
this file adds the archive-after-end variant and the F03 intent cases.
"""

from __future__ import annotations

import pytest

from app.domain.battle_maps.schemas import BattleMapArchive
from app.domain.combat.lifecycle import (
    CombatIdempotencyConflictError,
    StartTacticalCombatInput,
    tactical_start_intent,
)
from tests.test_m07c_combat_load import (
    GOBLIN_KEY,
    _create_map,
    _dm_context,
    _placement,
    _put_placements,
    _start,
    _table,
)


def test_intent_includes_include_active_party_flag() -> None:
    from uuid import uuid4

    map_id = uuid4()
    with_party = tactical_start_intent(
        StartTacticalCombatInput(
            battle_map_id=map_id, load_map_monsters=True, include_active_party=True
        )
    )
    without_party = tactical_start_intent(
        StartTacticalCombatInput(
            battle_map_id=map_id, load_map_monsters=True, include_active_party=False
        )
    )
    assert with_party["include_active_party"] is True
    assert without_party["include_active_party"] is False
    assert with_party != without_party


def test_same_key_changed_party_flag_is_409() -> None:
    table, battle_maps = _table()
    map_id = _create_map(table, battle_maps)
    _put_placements(table, battle_maps, map_id, [
        _placement(template_key=GOBLIN_KEY, anchor=(1, 1)),
    ])
    first = _start(table, map_id, idempotency_key="d1-party-flag")
    assert first.id is not None
    with pytest.raises(CombatIdempotencyConflictError):
        table.combat.start_tactical_combat(
            table.dm_actor,
            StartTacticalCombatInput(
                battle_map_id=map_id,
                load_map_monsters=True,
                include_active_party=False,
                idempotency_key="d1-party-flag",
            ),
        )


def test_same_key_same_party_flag_retries_original() -> None:
    table, battle_maps = _table()
    map_id = _create_map(table, battle_maps)
    _put_placements(table, battle_maps, map_id, [
        _placement(template_key=GOBLIN_KEY, anchor=(1, 1)),
    ])
    first = _start(
        table, map_id, include_active_party=False, idempotency_key="d1-party-same"
    )
    assert [e.subject_kind for e in first.entries] == ["monster"]
    second = _start(
        table, map_id, include_active_party=False, idempotency_key="d1-party-same"
    )
    assert second.id == first.id


def test_retry_after_combat_end_and_map_archive_returns_original() -> None:
    table, battle_maps = _table()
    map_id = _create_map(table, battle_maps)
    _put_placements(table, battle_maps, map_id, [
        _placement(template_key=GOBLIN_KEY, anchor=(1, 1)),
    ])
    first = _start(table, map_id, idempotency_key="d1-end-archive")
    table.combat.end_combat(table.dm_actor)
    assert table.combat.repository.get_active(table.campaign_id) is None
    battle_maps.archive(
        _dm_context(table), room_id=table.room_id, map_id=map_id,
        payload=BattleMapArchive(expected_revision=2),
    )
    second = _start(table, map_id, idempotency_key="d1-end-archive")
    assert second.id == first.id
    assert second.status == "ended"


def test_retry_after_archive_different_intent_still_409() -> None:
    table, battle_maps = _table()
    map_id = _create_map(table, battle_maps)
    _put_placements(table, battle_maps, map_id, [
        _placement(template_key=GOBLIN_KEY, anchor=(1, 1)),
    ])
    first = _start(table, map_id, idempotency_key="d1-archive-409")
    assert first.id is not None
    battle_maps.archive(
        _dm_context(table), room_id=table.room_id, map_id=map_id,
        payload=BattleMapArchive(expected_revision=2),
    )
    # Same key but a different intent (party flag flipped) is a conflict, not
    # a replay — even though the map source is now archived.
    with pytest.raises(CombatIdempotencyConflictError):
        table.combat.start_tactical_combat(
            table.dm_actor,
            StartTacticalCombatInput(
                battle_map_id=map_id,
                load_map_monsters=True,
                include_active_party=False,
                idempotency_key="d1-archive-409",
            ),
        )
    # The committed result is still resolvable with the original intent.
    retry = _start(table, map_id, idempotency_key="d1-archive-409")
    assert retry.id == first.id
