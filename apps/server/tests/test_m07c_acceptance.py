"""M07-C conductor acceptance: real MCP journeys for map monster load.

An AI DM starts Tactical Combat with ``load_map_monsters`` through the MCP
tool layer; an AI Player then reads every MCP context surface and must never
see the hidden placement's identity, name, position or count. A bad batch must
leave the table untouched.
"""

from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import select, update

from app.persistence.combat.tables import combat_entries, monster_instances, monster_templates
from tests.p5a_tactical_helpers import TacticalTable
from tests.test_m07b_tactical_sources import _mcp
from tests.test_m07c_combat_load import (
    GOBLIN_KEY,
    _counts,
    _create_map,
    _event_cursor,
    _insert_custom_template,
    _placement,
    _put_placements,
    _table,
)
from tests.test_p5f_tactical_mcp import _dm_token, _player_token

HIDDEN_NAME = "Lurker In The Dark"

PLAYER_READS: tuple[tuple[str, dict], ...] = (
    ("combat_get_active", {}),
    ("get_combat_context", {}),
    ("combat_get_board", {}),
    ("get_pending_events", {}),
)


def _loaded_by_ai_dm() -> tuple[TacticalTable, str, UUID, UUID]:
    table, battle_maps = _table()
    map_id = _create_map(table, battle_maps)
    lurker = _insert_custom_template(table.engine, table.room_id, name=HIDDEN_NAME, size="Medium")
    _put_placements(table, battle_maps, map_id, [
        _placement(template_key=GOBLIN_KEY, anchor=(1, 1), visibility="public", sort_order=0),
        _placement(custom_template_id=lurker, anchor=(9, 9), visibility="hidden", sort_order=1),
    ])
    dm_token = _dm_token(table)
    started = _mcp(table, dm_token, "combat_start_tactical", {
        "battle_map_id": str(map_id), "load_map_monsters": True, "idempotency_key": "acceptance-load",
    })
    assert started["structuredContent"]["ok"] is True, started
    with table.engine.connect() as connection:
        hidden = connection.execute(
            select(combat_entries.c.id, combat_entries.c.monster_instance_id)
            .join(monster_instances, monster_instances.c.id == combat_entries.c.monster_instance_id)
            .where(monster_instances.c.visibility == "hidden")
        ).one()
    return table, dm_token, hidden.id, hidden.monster_instance_id


def _blob(result: dict) -> str:
    return json.dumps(result["structuredContent"], default=str, ensure_ascii=False)


def test_ai_player_mcp_reads_never_reveal_hidden_loaded_monster() -> None:
    table, dm_token, hidden_entry_id, hidden_instance_id = _loaded_by_ai_dm()
    player_token = _player_token(table)

    for name, arguments in PLAYER_READS:
        result = _mcp(table, player_token, name, arguments)
        assert result["structuredContent"]["ok"] is True, (name, result)
        blob = _blob(result)
        assert str(hidden_entry_id) not in blob, name
        assert str(hidden_instance_id) not in blob, name
        assert HIDDEN_NAME not in blob, name
        # The idempotency intent (incl. load_map_monsters) is DM bookkeeping.
        assert "start_intent" not in blob, name

    active = _mcp(table, player_token, "combat_get_active", {})["structuredContent"]["data"]["combat"]
    monsters = [entry for entry in active["entries"] if entry["subject_kind"] == "monster"]
    assert len(monsters) == 1
    board = _mcp(table, player_token, "combat_get_board", {})["structuredContent"]["data"]
    assert all(position["anchor_x"] != 9 for position in board["positions"])

    # The DM sees the hidden monster through the same tools.
    for name, arguments in PLAYER_READS[:3]:
        dm_blob = _blob(_mcp(table, dm_token, name, arguments))
        assert str(hidden_entry_id) in dm_blob, name


def test_ai_dm_bad_batch_after_template_growth_leaves_table_untouched() -> None:
    table, battle_maps = _table()
    map_id = _create_map(table, battle_maps)
    brute = _insert_custom_template(table.engine, table.room_id, name="Growing Brute", size="Medium")
    _put_placements(table, battle_maps, map_id, [
        _placement(template_key=GOBLIN_KEY, anchor=(2, 1), sort_order=0),
        _placement(custom_template_id=brute, anchor=(1, 1), visibility="hidden", sort_order=1),
    ])
    # The template grows after the placement was saved: Huge (3x3) at (1,1)
    # now overlaps the goblin at (2,1). The start must reject the whole batch.
    with table.engine.begin() as connection:
        rules = connection.execute(
            select(monster_templates.c.rules).where(monster_templates.c.id == brute)
        ).scalar_one()
        connection.execute(
            update(monster_templates)
            .where(monster_templates.c.id == brute)
            .values(rules={**rules, "size": "Huge"}, revision=2)
        )
    dm_token = _dm_token(table)
    before = _counts(table.engine)
    cursor = _event_cursor(table.engine, table.session_id)

    result = _mcp(table, dm_token, "combat_start_tactical", {
        "battle_map_id": str(map_id), "load_map_monsters": True,
    })
    error = result["structuredContent"]["error"]
    assert error["code"] == "map_monster_placement_invalid", error
    assert _counts(table.engine) == before
    assert _event_cursor(table.engine, table.session_id) == cursor

    # Loading only the map still works afterwards.
    only_map = _mcp(table, dm_token, "combat_start_tactical", {"battle_map_id": str(map_id)})
    assert only_map["structuredContent"]["ok"] is True
    assert _counts(table.engine)["instances"] == before["instances"]
