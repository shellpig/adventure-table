"""M07-D D1 (F08) PostgreSQL locking tests: template create vs archive, map freeze.

SQLite drops ``FOR UPDATE``, so lock-blocking behavior is proven here
against real PostgreSQL (``P4_POSTGRES_URL``; skip does not count as pass).
Each test migrates a scratch database to head (``xdist_group("postgres")``
serialises these with the other PG tests).
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from uuid import UUID, uuid4

from alembic import command
import pytest
from sqlalchemy import create_engine, func, select, update
from sqlalchemy.engine import Engine

from app.content import load_default_content_registry
from app.domain.battle_maps.schemas import (
    BattleMapArchive,
    BattleMapCreate,
    MonsterPlacementInput,
    MonsterPlacementsReplace,
)
from app.domain.battle_maps.service import BattleMapService
from app.domain.combat.lifecycle import StartTacticalCombatInput
from app.domain.combat.monster_instances import (
    CreateMonsterFromContentInput,
    MonsterInstanceService,
)
from app.domain.monster_library.errors import MonsterTemplateArchivedError
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.persistence.battle_maps.repository import BattleMapRepository
from app.persistence.battle_maps.tables import battle_maps as battle_maps_tbl
from app.persistence.combat.tables import monster_instances, monster_templates
from app.persistence.room_assets.repository import RoomAssetRepository
from tests.p5a_tactical_helpers import TacticalTable, setup_tactical_table
from tests.test_p5a_postgres_migration import POSTGRES_URL, _config, _reset

pytestmark = [
    pytest.mark.xdist_group("postgres"),
    pytest.mark.skipif(not POSTGRES_URL, reason="P4_POSTGRES_URL is only supplied by the P4 PostgreSQL job"),
]

GOBLIN_KEY = "srd5.1:monster:goblin"


def _pg_table() -> tuple[TacticalTable, BattleMapService, Engine]:
    _reset()
    config = _config()
    assert config.attributes["target_database_url"] == POSTGRES_URL
    command.upgrade(config, "heads")
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL, pool_size=10, max_overflow=10)
    table = setup_tactical_table(engine)
    battle_maps = BattleMapService(
        BattleMapRepository(engine),
        RoomAssetRepository(engine),
        table.events,
        content_registry=load_default_content_registry(),
    )
    return table, battle_maps, engine


def _dm_context(table: TacticalTable) -> RoomAccessContext:
    return RoomAccessContext(
        room_id=table.room_id,
        access_session_id=table.dm_actor.access_session_id,
        authority=RoomAccessAuthority.DM,
    )


def _insert_template(engine: Engine, room_id: UUID) -> UUID:
    template_id = uuid4()
    now = datetime.now(timezone.utc)
    with engine.begin() as connection:
        connection.execute(
            monster_templates.insert().values(
                id=template_id, room_id=room_id, name="Race Brute",
                source_key=None,
                rules={"size": "Medium", "armor_class": 11, "max_hp": 59,
                       "speed": {"walk": "40 ft."}},
                revision=1, archived_at=None,
                presentation_json={"names": {"en": "Race Brute"}, "name_is_custom": True},
                created_at=now, updated_at=now,
            )
        )
    return template_id


def _instances(table: TacticalTable) -> MonsterInstanceService:
    return MonsterInstanceService(
        monster_repository=table.combat.monster_repository,
        content_registry=table.registry,
        table_event_service=table.events,
    )


def test_pg_template_create_blocks_on_row_lock_then_sees_archive() -> None:
    """The single-create path holds the template row lock (F08).

    While another transaction holds the template row lock, the create must
    block (not slip a read past it); after that transaction archives and
    commits, the create must fail with the archived error and store nothing.
    Without the in-transaction lock the create would finish immediately and
    this test's "still blocked" assertion would fail.
    """
    table, _, engine = _pg_table()
    try:
        template_id = _insert_template(engine, table.room_id)
        holder = engine.connect()
        holder_tx = holder.begin()
        try:
            holder.execute(
                select(monster_templates.c.id)
                .where(monster_templates.c.id == template_id)
                .with_for_update()
            )
            outcome: dict = {}

            def create() -> None:
                try:
                    outcome["view"] = _instances(table).create_from_content(
                        table.dm_actor,
                        CreateMonsterFromContentInput(
                            content_key=f"custom:{template_id}"
                        ),
                    )
                except Exception as exc:  # noqa: BLE001
                    outcome["error"] = exc

            worker = threading.Thread(target=create)
            worker.start()
            worker.join(timeout=10)
            assert worker.is_alive(), "create must block on the held template row lock"
            holder.execute(
                update(monster_templates)
                .where(monster_templates.c.id == template_id)
                .values(archived_at=datetime.now(timezone.utc))
            )
            holder_tx.commit()
        finally:
            holder.close()
        worker.join(timeout=60)
        assert not worker.is_alive()
        assert isinstance(outcome.get("error"), MonsterTemplateArchivedError)
        with engine.connect() as connection:
            count = int(
                connection.scalar(
                    select(func.count()).select_from(monster_instances)
                ) or 0
            )
        assert count == 0
    finally:
        engine.dispose()


def test_pg_concurrent_create_vs_archive_has_legal_outcome() -> None:
    """A create racing an archive resolves to exactly one legal outcome."""
    table, _, engine = _pg_table()
    try:
        template_id = _insert_template(engine, table.room_id)
        barrier = threading.Barrier(2)
        outcome: dict = {}

        def create() -> None:
            try:
                barrier.wait(timeout=30)
                outcome["view"] = _instances(table).create_from_content(
                    table.dm_actor,
                    CreateMonsterFromContentInput(
                        content_key=f"custom:{template_id}"
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                outcome["error"] = exc

        def archive() -> None:
            try:
                barrier.wait(timeout=30)
                with engine.begin() as connection:
                    connection.execute(
                        update(monster_templates)
                        .where(monster_templates.c.id == template_id)
                        .values(archived_at=datetime.now(timezone.utc))
                    )
                outcome["archived"] = True
            except Exception as exc:  # noqa: BLE001
                outcome["archive_error"] = exc

        threads = [threading.Thread(target=create), threading.Thread(target=archive)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)
        assert "archive_error" not in outcome
        assert outcome.get("archived") is True
        with engine.connect() as connection:
            rows = connection.execute(
                select(monster_instances.c.custom_template_id).where(
                    monster_instances.c.custom_template_id == template_id
                )
            ).all()
        if "view" in outcome:
            # The create won the race before the archive committed: exactly
            # one instance from the then-live template.
            assert len(rows) == 1
        else:
            # The archive won: the create was rejected, nothing stored.
            assert isinstance(outcome.get("error"), MonsterTemplateArchivedError)
            assert rows == []
    finally:
        engine.dispose()


def test_pg_tactical_start_blocks_while_map_row_locked() -> None:
    """The board freezer locks the map row before reading (F08).

    While another transaction holds the map row lock, the tactical start
    must block; after release it freezes exactly the committed revision.
    """
    table, battle_maps, engine = _pg_table()
    try:
        created = battle_maps.create(
            _dm_context(table),
            room_id=table.room_id,
            payload=BattleMapCreate(
                name="Lock Map", source_kind="blank", width_cells=20, height_cells=15
            ),
        )
        battle_maps.replace_monster_placements(
            _dm_context(table),
            room_id=table.room_id,
            map_id=created.id,
            payload=MonsterPlacementsReplace(
                expected_revision=1,
                placements=[
                    MonsterPlacementInput(
                        template_key=GOBLIN_KEY, custom_template_id=None,
                        anchor_x=1, anchor_y=1, visibility="public", sort_order=0,
                    )
                ],
            ),
        )
        holder = engine.connect()
        holder_tx = holder.begin()
        try:
            holder.execute(
                select(battle_maps_tbl.c.id)
                .where(battle_maps_tbl.c.id == created.id)
                .with_for_update()
            )
            outcome: dict = {}

            def start() -> None:
                try:
                    outcome["view"] = table.combat.start_tactical_combat(
                        table.dm_actor,
                        StartTacticalCombatInput(
                            battle_map_id=created.id, load_map_monsters=True,
                            idempotency_key="pg-d1-map-lock",
                        ),
                    )
                except Exception as exc:  # noqa: BLE001
                    outcome["error"] = exc

            worker = threading.Thread(target=start)
            worker.start()
            worker.join(timeout=10)
            assert worker.is_alive(), "tactical start must block on the held map row lock"
            holder_tx.commit()
        finally:
            holder.close()
        worker.join(timeout=120)
        assert not worker.is_alive()
        assert "error" not in outcome, outcome.get("error")
        board = table.board.get_board(table.dm_actor)
        assert board.source_battle_map_id == created.id
        assert board.source_battle_map_revision == 2
    finally:
        engine.dispose()


def test_pg_archived_map_retry_after_end_returns_original() -> None:
    """F09 on PostgreSQL: end, archive, same-key retry returns the original."""
    table, battle_maps, engine = _pg_table()
    try:
        created = battle_maps.create(
            _dm_context(table),
            room_id=table.room_id,
            payload=BattleMapCreate(
                name="F09 Map", source_kind="blank", width_cells=20, height_cells=15
            ),
        )
        battle_maps.replace_monster_placements(
            _dm_context(table),
            room_id=table.room_id,
            map_id=created.id,
            payload=MonsterPlacementsReplace(
                expected_revision=1,
                placements=[
                    MonsterPlacementInput(
                        template_key=GOBLIN_KEY, custom_template_id=None,
                        anchor_x=1, anchor_y=1, visibility="public", sort_order=0,
                    )
                ],
            ),
        )
        first = table.combat.start_tactical_combat(
            table.dm_actor,
            StartTacticalCombatInput(
                battle_map_id=created.id, load_map_monsters=True,
                idempotency_key="pg-d1-f09",
            ),
        )
        table.combat.end_combat(table.dm_actor)
        battle_maps.archive(
            _dm_context(table), room_id=table.room_id, map_id=created.id,
            payload=BattleMapArchive(expected_revision=2),
        )
        retry = table.combat.start_tactical_combat(
            table.dm_actor,
            StartTacticalCombatInput(
                battle_map_id=created.id, load_map_monsters=True,
                idempotency_key="pg-d1-f09",
            ),
        )
        assert retry.id == first.id
        assert retry.status == "ended"
    finally:
        engine.dispose()
