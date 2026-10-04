"""M07-D D1 (F08): single-transaction reads and writes (SQLite-observable parts).

The row-lock blocking behavior needs PostgreSQL (SQLite drops FOR UPDATE)
and lives in ``tests/test_m07d_postgres_race.py``. Here: the in-transaction
APIs honor the caller's transaction (rollback removes everything), custom
template creation rejects archived/cross-room templates with zero side
effects, and the frozen board matches one consistent map revision.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, insert, select, update

from app.domain.combat.monster_instances import (
    CreateMonsterFromContentInput,
    MonsterInstanceService,
)
from app.domain.monster_library.errors import (
    MonsterTemplateArchivedError,
    MonsterTemplateNotFoundError,
)
from app.persistence.battle_maps.tables import battle_maps as battle_maps_tbl
from app.persistence.combat.repository import MonsterRepository
from app.persistence.combat.tables import monster_instances, monster_templates
from tests.p5a_tactical_helpers import TacticalTable, setup_tactical_table
from tests.test_m07c_combat_load import (
    GOBLIN_KEY,
    _create_map,
    _insert_custom_template,
    _placement,
    _put_placements,
    _start,
    _table,
)


def _instances(table: TacticalTable) -> MonsterInstanceService:
    return MonsterInstanceService(
        monster_repository=table.combat.monster_repository,
        content_registry=table.registry,
        table_event_service=table.events,
    )


def _instance_count(table: TacticalTable) -> int:
    with table.engine.connect() as connection:
        return int(
            connection.scalar(select(func.count()).select_from(monster_instances)) or 0
        )


def test_in_transaction_create_honors_caller_rollback() -> None:
    table = setup_tactical_table()
    template_id = _insert_custom_template(table.engine, table.room_id, name="Rollback Brute")
    repo: MonsterRepository = table.combat.monster_repository
    before = _instance_count(table)
    with table.engine.connect() as connection:
        transaction = connection.begin()
        try:
            repo.create_instance_from_template_in_transaction(
                connection,
                template_id,
                campaign_id=table.campaign_id,
                room_id=table.room_id,
            )
        finally:
            transaction.rollback()
    # The method performed no internal commit: the rollback removed the row.
    assert _instance_count(table) == before


def test_custom_create_rejects_archived_template_with_zero_side_effects() -> None:
    table = setup_tactical_table()
    template_id = _insert_custom_template(table.engine, table.room_id, name="Doomed")
    with table.engine.begin() as connection:
        connection.execute(
            update(monster_templates)
            .where(monster_templates.c.id == template_id)
            .values(archived_at=datetime.now(timezone.utc))
        )
    before = _instance_count(table)
    with pytest.raises(MonsterTemplateArchivedError):
        _instances(table).create_from_content(
            table.dm_actor,
            CreateMonsterFromContentInput(content_key=f"custom:{template_id}"),
        )
    assert _instance_count(table) == before


def test_custom_create_rejects_cross_room_template() -> None:
    table = setup_tactical_table()
    foreign_room_id = uuid4()
    foreign_id = uuid4()
    now = datetime.now(timezone.utc)
    from app.persistence.rooms.tables import rooms as rooms_tbl

    with table.engine.begin() as connection:
        connection.execute(
            insert(rooms_tbl).values(
                id=foreign_room_id, code="FOREIGN", name="Foreign Room",
                password_salt=b"s", password_hash=b"p",
                owner_key_hash=b"o", dm_key_hash=b"d",
                created_at=now, updated_at=now,
            )
        )
        connection.execute(
            insert(monster_templates).values(
                id=foreign_id, room_id=foreign_room_id, name="Foreign",
                source_key=None,
                rules={"size": "Medium", "armor_class": 10, "max_hp": 10,
                       "speed": {"walk": "30 ft."}},
                revision=1, archived_at=None,
                presentation_json={"names": {"en": "Foreign"}, "name_is_custom": True},
                created_at=now, updated_at=now,
            )
        )
    with pytest.raises(MonsterTemplateNotFoundError):
        _instances(table).create_from_content(
            table.dm_actor,
            CreateMonsterFromContentInput(content_key=f"custom:{foreign_id}"),
        )
    assert _instance_count(table) == 0


def test_custom_create_rejects_malformed_ref() -> None:
    table = setup_tactical_table()
    from app.domain.monster_library.errors import InvalidMonsterTemplateRefError

    with pytest.raises(InvalidMonsterTemplateRefError):
        _instances(table).create_from_content(
            table.dm_actor,
            CreateMonsterFromContentInput(content_key="custom:not-a-uuid"),
        )


def test_custom_create_uses_latest_template_revision() -> None:
    table = setup_tactical_table()
    template_id = _insert_custom_template(table.engine, table.room_id, name="Old Name")
    with table.engine.begin() as connection:
        connection.execute(
            update(monster_templates)
            .where(monster_templates.c.id == template_id)
            .values(name="New Name", revision=2)
        )
    view = _instances(table).create_from_content(
        table.dm_actor,
        CreateMonsterFromContentInput(content_key=f"custom:{template_id}"),
    )
    assert view.name == "New Name"
    assert view.rules_snapshot["provenance"] == {"template_revision": 2}


def test_frozen_board_matches_single_map_revision() -> None:
    table, battle_maps = _table()
    map_id = _create_map(table, battle_maps)
    _put_placements(table, battle_maps, map_id, [
        _placement(template_key=GOBLIN_KEY, anchor=(1, 1), visibility="public", sort_order=0),
    ])
    view = _start(table, map_id)
    board = table.board.get_board(table.dm_actor)
    assert board.source_battle_map_id == map_id
    with table.engine.connect() as connection:
        revision = connection.scalar(
            select(battle_maps_tbl.c.revision).where(
                battle_maps_tbl.c.id == map_id
            )
        )
    assert board.source_battle_map_revision == revision
    assert (board.width_cells, board.height_cells) == (20, 15)
