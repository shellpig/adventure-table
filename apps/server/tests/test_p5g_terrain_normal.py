"""P5-G: Normal terrain painted in the map editor (design: normal | difficult | blocked)."""

from __future__ import annotations

import os

import pytest
from alembic import command
from sqlalchemy import create_engine, insert, text

from app.domain.battle_maps.schemas import BattleMapObjectsReplace
from app.persistence.battle_maps.tables import battle_map_terrain
from p5a_tactical_helpers import insert_battle_map, setup_tactical_table
from test_p5b_movement import (
    _add_monster,
    _character_entry_id,
    _preview,
    _running,
    _start,
)

POSTGRES_URL = os.environ.get("P4_POSTGRES_URL")


def test_objects_replace_accepts_normal_terrain() -> None:
    objects = BattleMapObjectsReplace.model_validate({
        "expected_revision": 1,
        "terrain": [
            {"x": 1, "y": 1, "terrain_kind": "normal"},
            {"x": 2, "y": 1, "terrain_kind": "difficult"},
            {"x": 3, "y": 1, "terrain_kind": "blocked"},
        ],
    })
    assert [t.terrain_kind for t in objects.terrain] == ["normal", "difficult", "blocked"]


def test_normal_terrain_moves_like_an_unpainted_cell() -> None:
    table = setup_tactical_table()
    map_id = insert_battle_map(table)
    with table.engine.begin() as conn:
        conn.execute(insert(battle_map_terrain).values(
            battle_map_id=map_id, x=2, y=1, terrain_kind="normal",
        ))
    _start(table, battle_map_id=map_id)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)

    view = _preview(table, table.player_actor, char_entry, (1, 1), (2, 1))
    assert view.valid
    assert not view.steps[0].difficult
    assert view.steps[0].cost_feet == 5
    assert view.steps[0].warnings == ()


@pytest.mark.xdist_group("postgres")
@pytest.mark.skipif(not POSTGRES_URL, reason="P4_POSTGRES_URL is only supplied by the PostgreSQL job")
def test_postgres_0040_terrain_normal_migration_round_trip() -> None:
    from test_p5a_postgres_migration import _config, _reset

    _reset()
    config = _config()
    command.upgrade(config, "0040_p5g_terrain_normal")
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        with engine.connect() as conn:
            definition = conn.execute(text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'ck_battle_map_terrain_kind'"
            )).scalar_one()
        assert "'normal'" in definition
        command.downgrade(config, "0039_p5e_disengaged")
        with engine.connect() as conn:
            definition = conn.execute(text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'ck_battle_map_terrain_kind'"
            )).scalar_one()
        assert "'normal'" not in definition
        assert "'difficult'" in definition
    finally:
        engine.dispose()
