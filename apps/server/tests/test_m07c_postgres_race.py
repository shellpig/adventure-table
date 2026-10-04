"""M07-C C2 PostgreSQL race tests: load vs edits, concurrent starts.

Each test migrates a scratch database to head (never dropping a shared schema
in parallel: ``xdist_group("postgres")`` serialises these).
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from uuid import UUID, uuid4

from alembic import command
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine

from app.content import load_default_content_registry
from app.domain.battle_maps.schemas import (
    BattleMapCreate,
    MapMonsterPlacementInvalidError,
    MonsterPlacementInput,
    MonsterPlacementsReplace,
)
from app.domain.battle_maps.service import BattleMapService
from app.domain.combat.lifecycle import (
    ActiveCombatExistsError,
    StartTacticalCombatInput,
)
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.persistence.battle_maps.repository import BattleMapRepository
from app.persistence.combat.tables import combat_entries, combats, monster_instances
from app.persistence.combat_boards.tables import combat_boards, combat_positions
from app.persistence.room_assets.repository import RoomAssetRepository
from app.persistence.rooms.table_runtime import session_events
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


def _create_map_with_goblin(table: TacticalTable, battle_maps: BattleMapService) -> UUID:
    created = battle_maps.create(
        _dm_context(table),
        room_id=table.room_id,
        payload=BattleMapCreate(
            name="Race Map", source_kind="blank", width_cells=20, height_cells=15
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
    return created.id


def _graph_counts(engine: Engine) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            name: int(connection.scalar(select(func.count()).select_from(tbl)) or 0)
            for name, tbl in (
                ("instances", monster_instances),
                ("combats", combats),
                ("entries", combat_entries),
                ("boards", combat_boards),
                ("positions", combat_positions),
                ("events", session_events),
            )
        }


def test_pg_concurrent_same_key_start_yields_one_combat() -> None:
    table, battle_maps, engine = _pg_table()
    try:
        map_id = _create_map_with_goblin(table, battle_maps)
        barrier = threading.Barrier(2)
        results: list = [None, None]
        errors: list = [None, None]

        def start(index: int) -> None:
            try:
                barrier.wait(timeout=30)
                results[index] = table.combat.start_tactical_combat(
                    table.dm_actor,
                    StartTacticalCombatInput(
                        battle_map_id=map_id, load_map_monsters=True,
                        idempotency_key="pg-race-same-key",
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                errors[index] = exc

        threads = [threading.Thread(target=start, args=(i,)) for i in (0, 1)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)
        assert errors == [None, None]
        assert results[0].id == results[1].id
        counts = _graph_counts(engine)
        assert counts["combats"] == 1
        assert counts["instances"] == 1
        assert counts["entries"] == 2  # party character + goblin
        assert counts["boards"] == 1
        assert counts["positions"] == 1
    finally:
        engine.dispose()


def test_pg_concurrent_different_keys_one_wins() -> None:
    table, battle_maps, engine = _pg_table()
    try:
        map_id = _create_map_with_goblin(table, battle_maps)
        barrier = threading.Barrier(2)
        results: list = [None, None]
        errors: list = [None, None]

        def start(index: int) -> None:
            try:
                barrier.wait(timeout=30)
                results[index] = table.combat.start_tactical_combat(
                    table.dm_actor,
                    StartTacticalCombatInput(
                        battle_map_id=map_id, load_map_monsters=True,
                        idempotency_key=f"pg-race-key-{index}",
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                errors[index] = exc

        threads = [threading.Thread(target=start, args=(i,)) for i in (0, 1)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)
        winners = [r for r in results if r is not None]
        losers = [e for e in errors if e is not None]
        assert len(winners) == 1
        assert len(losers) == 1
        assert isinstance(losers[0], ActiveCombatExistsError)
        counts = _graph_counts(engine)
        assert counts["combats"] == 1
        assert counts["instances"] == 1
    finally:
        engine.dispose()


def test_pg_load_vs_placement_edit_race_stays_atomic() -> None:
    """A placement edit racing the load resolves to exactly one config.

    The load locks the map row inside the event transaction; the PUT either
    commits fully before the lock (load sees 2 monsters) or after (load sees
    1). A mixed graph (2 instances but 1 placement row, or vice versa) would
    prove a torn read.
    """
    table, battle_maps, engine = _pg_table()
    try:
        map_id = _create_map_with_goblin(table, battle_maps)
        barrier = threading.Barrier(2)
        outcome: dict = {}

        def start_load() -> None:
            try:
                barrier.wait(timeout=30)
                view = table.combat.start_tactical_combat(
                    table.dm_actor,
                    StartTacticalCombatInput(
                        battle_map_id=map_id, load_map_monsters=True,
                        idempotency_key="pg-race-load",
                    ),
                )
                with engine.connect() as connection:
                    outcome["loaded_monsters"] = int(
                        connection.scalar(
                            select(func.count())
                            .select_from(combat_entries)
                            .where(
                                combat_entries.c.combat_id == view.id,
                                combat_entries.c.subject_kind == "monster",
                            )
                        )
                        or 0
                    )
            except Exception as exc:  # noqa: BLE001
                outcome["load_error"] = exc

        def edit_placements() -> None:
            try:
                barrier.wait(timeout=30)
                battle_maps.replace_monster_placements(
                    _dm_context(table),
                    room_id=table.room_id,
                    map_id=map_id,
                    payload=MonsterPlacementsReplace(
                        expected_revision=2,
                        placements=[
                            MonsterPlacementInput(
                                template_key=GOBLIN_KEY, custom_template_id=None,
                                anchor_x=1, anchor_y=1, visibility="public", sort_order=0,
                            ),
                            MonsterPlacementInput(
                                template_key=GOBLIN_KEY, custom_template_id=None,
                                anchor_x=4, anchor_y=4, visibility="public", sort_order=1,
                            ),
                        ],
                    ),
                )
                outcome["edit"] = "ok"
            except Exception as exc:  # noqa: BLE001
                outcome["edit_error"] = exc

        threads = [
            threading.Thread(target=start_load),
            threading.Thread(target=edit_placements),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)
        assert "load_error" not in outcome, outcome.get("load_error")
        # The edit may or may not have won the race; either way the loaded
        # graph is internally consistent.
        assert outcome["loaded_monsters"] in (1, 2)
        counts = _graph_counts(engine)
        assert counts["combats"] == 1
        assert counts["instances"] == outcome["loaded_monsters"]
        assert counts["positions"] == outcome["loaded_monsters"]
        assert counts["entries"] == outcome["loaded_monsters"] + 1
    finally:
        engine.dispose()


def test_pg_failed_load_rolls_back_with_cursor_unchanged() -> None:
    table, battle_maps, engine = _pg_table()
    try:
        map_id = _create_map_with_goblin(table, battle_maps)
        # Add a second placement, then shrink the map so it goes out of bounds.
        # (PUT-time geometry is 20x15; raw edit the map smaller afterwards.)
        battle_maps.replace_monster_placements(
            _dm_context(table),
            room_id=table.room_id,
            map_id=map_id,
            payload=MonsterPlacementsReplace(
                expected_revision=2,
                placements=[
                    MonsterPlacementInput(
                        template_key=GOBLIN_KEY, custom_template_id=None,
                        anchor_x=1, anchor_y=1, visibility="public", sort_order=0,
                    ),
                    MonsterPlacementInput(
                        template_key=GOBLIN_KEY, custom_template_id=None,
                        anchor_x=18, anchor_y=13, visibility="public", sort_order=1,
                    ),
                ],
            ),
        )
        from app.persistence.battle_maps.tables import battle_maps as battle_maps_tbl

        with engine.begin() as connection:
            connection.execute(
                battle_maps_tbl.update()
                .where(battle_maps_tbl.c.id == map_id)
                .values(width_cells=10, height_cells=8, revision=3)
            )
        before = _graph_counts(engine)
        with engine.connect() as connection:
            cursor_before = int(
                connection.scalar(
                    select(func.max(session_events.c.seq)).where(
                        session_events.c.session_id == table.session_id
                    )
                )
                or 0
            )
        with pytest.raises(MapMonsterPlacementInvalidError):
            table.combat.start_tactical_combat(
                table.dm_actor,
                StartTacticalCombatInput(
                    battle_map_id=map_id, load_map_monsters=True,
                    idempotency_key="pg-race-bad",
                ),
            )
        assert _graph_counts(engine) == before
        with engine.connect() as connection:
            cursor_after = int(
                connection.scalar(
                    select(func.max(session_events.c.seq)).where(
                        session_events.c.session_id == table.session_id
                    )
                )
                or 0
            )
        assert cursor_after == cursor_before
    finally:
        engine.dispose()


# --- C.2 load vs template mutation races (two connections) -----------------------


def _pg_table_with_custom_template() -> tuple:
    """Table + map with one custom-template placement; returns template id too."""
    from datetime import datetime, timezone

    from sqlalchemy import insert as sa_insert

    from app.persistence.combat.tables import monster_templates

    table, battle_maps, engine = _pg_table()
    template_id = uuid4()
    now = datetime.now(timezone.utc)
    with engine.begin() as connection:
        connection.execute(
            sa_insert(monster_templates).values(
                id=template_id,
                room_id=table.room_id,
                name="Race Brute",
                source_key=None,
                rules={"size": "Large", "armor_class": 11, "max_hp": 59,
                       "speed": {"walk": "40 ft."}},
                revision=1,
                archived_at=None,
                presentation_json={"names": {"en": "Race Brute"}, "name_is_custom": True},
                created_at=now,
                updated_at=now,
            )
        )
    created = battle_maps.create(
        _dm_context(table),
        room_id=table.room_id,
        payload=BattleMapCreate(
            name="Race Map 2", source_kind="blank", width_cells=20, height_cells=15
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
                    template_key=None, custom_template_id=template_id,
                    anchor_x=5, anchor_y=5, visibility="public", sort_order=0,
                )
            ],
        ),
    )
    return table, battle_maps, engine, created.id, template_id


def _assert_full_graph(engine: Engine, expected_monsters: int) -> None:
    counts = _graph_counts(engine)
    assert counts["combats"] == 1
    assert counts["instances"] == expected_monsters
    assert counts["positions"] == expected_monsters
    assert counts["entries"] == expected_monsters + 1  # + party character
    assert counts["boards"] == 1


def test_pg_load_vs_template_patch_two_connections() -> None:
    """Concurrent template patch vs load: the load sees one atomic snapshot."""
    table, battle_maps, engine_a, map_id, template_id = _pg_table_with_custom_template()
    engine_b = create_engine(POSTGRES_URL, pool_size=5, max_overflow=5)
    try:
        from app.persistence.combat.tables import monster_templates

        barrier = threading.Barrier(2)
        outcome: dict = {}

        def start_load() -> None:
            try:
                barrier.wait(timeout=30)
                view = table.combat.start_tactical_combat(
                    table.dm_actor,
                    StartTacticalCombatInput(
                        battle_map_id=map_id, load_map_monsters=True,
                        idempotency_key="pg-race-patch",
                    ),
                )
                with engine_a.connect() as connection:
                    name = connection.scalar(
                        select(monster_instances.c.name)
                        .join(
                            combat_entries,
                            combat_entries.c.monster_instance_id == monster_instances.c.id,
                        )
                        .where(combat_entries.c.combat_id == view.id)
                    )
                outcome["loaded_name"] = name
            except Exception as exc:  # noqa: BLE001
                outcome["load_error"] = exc

        def patch_template() -> None:
            try:
                barrier.wait(timeout=30)
                with engine_b.begin() as connection:
                    connection.execute(
                        monster_templates.update()
                        .where(monster_templates.c.id == template_id)
                        .values(name="Race Brute Patched", revision=2)
                    )
                outcome["patch"] = "ok"
            except Exception as exc:  # noqa: BLE001
                outcome["patch_error"] = exc

        threads = [threading.Thread(target=start_load), threading.Thread(target=patch_template)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)
        assert "load_error" not in outcome, outcome.get("load_error")
        assert "patch_error" not in outcome, outcome.get("patch_error")
        # Atomic: the snapshot carries exactly one of the two names.
        assert outcome["loaded_name"] in ("Race Brute", "Race Brute Patched")
        _assert_full_graph(engine_a, 1)
    finally:
        engine_b.dispose()
        engine_a.dispose()


def test_pg_load_vs_template_archive_two_connections() -> None:
    """Concurrent template archive vs load: archived-from-config still loads atomically."""
    table, battle_maps, engine_a, map_id, template_id = _pg_table_with_custom_template()
    engine_b = create_engine(POSTGRES_URL, pool_size=5, max_overflow=5)
    try:
        from datetime import datetime, timezone

        from app.persistence.combat.tables import monster_templates

        barrier = threading.Barrier(2)
        outcome: dict = {}

        def start_load() -> None:
            try:
                barrier.wait(timeout=30)
                table.combat.start_tactical_combat(
                    table.dm_actor,
                    StartTacticalCombatInput(
                        battle_map_id=map_id, load_map_monsters=True,
                        idempotency_key="pg-race-archive",
                    ),
                )
                outcome["load"] = "ok"
            except Exception as exc:  # noqa: BLE001
                outcome["load_error"] = exc

        def archive_template() -> None:
            try:
                barrier.wait(timeout=30)
                with engine_b.begin() as connection:
                    connection.execute(
                        monster_templates.update()
                        .where(monster_templates.c.id == template_id)
                        .values(archived_at=datetime.now(timezone.utc))
                    )
                outcome["archive"] = "ok"
            except Exception as exc:  # noqa: BLE001
                outcome["archive_error"] = exc

        threads = [threading.Thread(target=start_load), threading.Thread(target=archive_template)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)
        assert "load_error" not in outcome, outcome.get("load_error")
        assert "archive_error" not in outcome, outcome.get("archive_error")
        # No half batch either way.
        _assert_full_graph(engine_a, 1)
    finally:
        engine_b.dispose()
        engine_a.dispose()


def test_pg_load_vs_template_delete_two_connections() -> None:
    """Concurrent template delete vs load: the delete is rejected, the load is atomic."""
    table, battle_maps, engine_a, map_id, template_id = _pg_table_with_custom_template()
    engine_b = create_engine(POSTGRES_URL, pool_size=5, max_overflow=5)
    try:
        from app.persistence.combat.tables import monster_templates

        barrier = threading.Barrier(2)
        outcome: dict = {}

        def start_load() -> None:
            try:
                barrier.wait(timeout=30)
                table.combat.start_tactical_combat(
                    table.dm_actor,
                    StartTacticalCombatInput(
                        battle_map_id=map_id, load_map_monsters=True,
                        idempotency_key="pg-race-delete",
                    ),
                )
                outcome["load"] = "ok"
            except Exception as exc:  # noqa: BLE001
                outcome["load_error"] = exc

        def delete_template() -> None:
            # The placement references the template (FK RESTRICT), so the raw
            # delete must fail; it must not tear the concurrent load.
            from app.persistence.combat.tables import monster_templates as mt

            try:
                barrier.wait(timeout=30)
                with engine_b.begin() as connection:
                    connection.execute(
                        mt.delete().where(mt.c.id == template_id)
                    )
                outcome["delete"] = "ok"
            except Exception as exc:  # noqa: BLE001
                outcome["delete_error"] = exc

        threads = [threading.Thread(target=start_load), threading.Thread(target=delete_template)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)
        assert "load_error" not in outcome, outcome.get("load_error")
        # The delete cannot succeed while the placement references the template.
        assert "delete" not in outcome
        assert "delete_error" in outcome
        # The load graph is whole: no half batch of monsters.
        _assert_full_graph(engine_a, 1)
        with engine_a.connect() as connection:
            cursor = int(
                connection.scalar(
                    select(func.max(session_events.c.seq)).where(
                        session_events.c.session_id == table.session_id
                    )
                )
                or 0
            )
        assert cursor >= 1
    finally:
        engine_b.dispose()
        engine_a.dispose()
