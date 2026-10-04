"""M07-B PostgreSQL: 0042 migration on real rows and tactical start vs map delete race."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from alembic import command
import pytest
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from app.domain.battle_maps.schemas import BattleMapNotFoundError, BattleMapReferencedError
from app.domain.battle_maps.service import BattleMapService
from app.domain.combat.lifecycle import StartTacticalCombatInput
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.persistence.battle_maps.repository import BattleMapRepository
from app.persistence.battle_maps.tables import battle_maps
from app.persistence.combat.tables import combats
from app.persistence.combat_boards.tables import combat_boards
from app.persistence.room_assets.repository import RoomAssetRepository
from tests.p5a_tactical_helpers import TacticalTable, insert_battle_map, setup_tactical_table
from tests.test_p5a_postgres_migration import POSTGRES_URL, _config, _reset

pytestmark = [
    pytest.mark.xdist_group("postgres"),
    pytest.mark.skipif(not POSTGRES_URL, reason="P4_POSTGRES_URL is only supplied by the PostgreSQL job"),
]


def _source_map_fk(engine: Engine) -> dict[str, object]:
    with engine.connect() as connection:
        return next(
            fk for fk in inspect(connection).get_foreign_keys("combat_boards")
            if fk["constrained_columns"] == ["source_battle_map_id"]
        )


def _owner_context(table: TacticalTable) -> RoomAccessContext:
    return RoomAccessContext(
        room_id=table.room_id, access_session_id=uuid4(), authority=RoomAccessAuthority.OWNER,
    )


def test_m07b_0042_migrates_real_map_and_finished_board_rows() -> None:
    _reset()
    config = _config()
    command.upgrade(config, "heads")
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        table = setup_tactical_table(engine)
        map_id = insert_battle_map(table)
        combat = table.combat.start_tactical_combat(
            table.dm_actor, StartTacticalCombatInput(battle_map_id=map_id)
        )
        table.combat.end_combat(table.dm_actor)
        engine.dispose()

        # Back to the pre-M07-B schema with the real rows in place, then forward.
        command.downgrade(config, "0041_m07a_room_monster_templates")
        assert _source_map_fk(engine)["options"] == {"ondelete": "SET NULL"}
        command.upgrade(config, "0042_m07b_battle_map_lifecycle")

        assert _source_map_fk(engine)["options"] == {"ondelete": "RESTRICT"}
        with engine.connect() as connection:
            stored = connection.execute(
                select(battle_maps.c.revision, battle_maps.c.archived_at).where(battle_maps.c.id == map_id)
            ).one()
            assert (stored.revision, stored.archived_at) == (3, None)
            board = connection.execute(
                select(combat_boards.c.source_battle_map_id, combat_boards.c.source_battle_map_revision)
                .where(combat_boards.c.combat_id == combat.id)
            ).one()
            assert (board.source_battle_map_id, board.source_battle_map_revision) == (map_id, 3)
            assert connection.scalar(select(combats.c.status).where(combats.c.id == combat.id)) == "ended"
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(battle_maps.delete().where(battle_maps.c.id == map_id))
    finally:
        engine.dispose()


def test_m07b_tactical_start_vs_map_delete_race_leaves_no_dangling_reference() -> None:
    _reset()
    command.upgrade(_config(), "heads")
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        table = setup_tactical_table(engine)
        map_id = insert_battle_map(table)
        maps = BattleMapService(BattleMapRepository(engine), RoomAssetRepository(engine), table.events)
        barrier = Barrier(2)
        outcomes: dict[str, Exception | None] = {}

        def start() -> None:
            barrier.wait(timeout=10)
            try:
                table.combat.start_tactical_combat(table.dm_actor, StartTacticalCombatInput(battle_map_id=map_id))
                outcomes["start"] = None
            except BattleMapNotFoundError as exc:
                outcomes["start"] = exc

        def delete() -> None:
            barrier.wait(timeout=10)
            try:
                maps.delete(_owner_context(table), table.room_id, map_id, expected_revision=3)
                outcomes["delete"] = None
            except BattleMapReferencedError as exc:
                outcomes["delete"] = exc

        with ThreadPoolExecutor(max_workers=2) as pool:
            for future in [pool.submit(start), pool.submit(delete)]:
                future.result(timeout=30)

        with engine.connect() as connection:
            map_rows = connection.scalar(select(func.count()).select_from(battle_maps).where(battle_maps.c.id == map_id))
            board_refs = connection.scalar(
                select(func.count()).select_from(combat_boards).where(combat_boards.c.source_battle_map_id == map_id)
            )
            combat_count = connection.scalar(
                select(func.count()).select_from(combats).where(combats.c.campaign_id == table.campaign_id)
            )
        if outcomes["start"] is None:
            assert isinstance(outcomes["delete"], BattleMapReferencedError)
            assert (map_rows, board_refs, combat_count) == (1, 1, 1)
        else:
            assert outcomes["delete"] is None
            assert (map_rows, board_refs, combat_count) == (0, 0, 0)
    finally:
        engine.dispose()
