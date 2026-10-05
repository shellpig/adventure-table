"""M07-D D.1: integrated pre-M07 heads -> current heads migration on real PostgreSQL.

Per-hop evidence already exists for each M07 migration in isolation
(0041: ``test_m07a_migration_and_references.py::test_postgres_migration_0041``,
0042: ``test_m07b_postgres.py::test_m07b_0042_migrates_real_map_and_finished_board_rows``,
0043: ``test_m07c_postgres.py``). This module proves the whole
pre-M07 (web ``0040_p5g_terrain_normal``) -> current heads path in one run,
both empty and seeded, using real Alembic upgrades -- never
``metadata.create_all``. It also pins the web/character track boundary:
M07 never touched the character track, so the character head must be
``0015_character_state_revision`` before and after.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from alembic import command
import pytest
from sqlalchemy import create_engine, func, inspect, select, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from app.content import load_default_content_registry
from app.content.localization_files import load_content_localization_catalog
from app.content.registry import resolve_content_root
from app.domain.battle_maps.schemas import (
    BattleMapCreate,
    MonsterPlacementInput,
    MonsterPlacementsReplace,
)
from app.domain.battle_maps.service import BattleMapService
from app.domain.combat.lifecycle import StartTacticalCombatInput
from app.domain.monster_library.schemas import CreateCustomMonsterInput
from app.domain.monster_library.service import MonsterLibraryService
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.table_events import TableEventService
from app.persistence.battle_maps.repository import BattleMapRepository
from app.persistence.battle_maps.tables import battle_map_monster_placements, battle_maps
from app.persistence.combat.tables import (
    combat_entries,
    combats,
    monster_instances,
    monster_templates,
)
from app.persistence.combat.repository import MonsterRepository
from app.persistence.combat_boards.tables import combat_boards
from app.persistence.monster_library.repository import MonsterLibraryRepository
from app.persistence.room_assets.repository import RoomAssetRepository
from app.persistence.rooms.table_runtime import TableEventRepository
from tests.migration_support import migration_heads
from tests.p5a_tactical_helpers import TacticalTable, setup_tactical_table
from tests.test_p5a_postgres_migration import POSTGRES_URL, _config, _reset

pytestmark = [
    pytest.mark.xdist_group("postgres"),
    pytest.mark.skipif(not POSTGRES_URL, reason="P4_POSTGRES_URL is only supplied by the PostgreSQL job"),
]

PRE_M07_WEB = "0040_p5g_terrain_normal"
CHARACTER_HEAD = "0015_character_state_revision"
CURRENT_WEB = "0043_m07c_map_monster_placements"
GOBLIN_KEY = "srd5.1:monster:goblin"


def _versions(engine: Engine) -> list[str]:
    with engine.connect() as connection:
        return sorted(
            connection.execute(text("SELECT version_num FROM alembic_version")).scalars()
        )


def _table_names(engine: Engine) -> set[str]:
    with engine.connect() as connection:
        return set(inspect(connection).get_table_names())


def _columns(engine: Engine, table: str) -> set[str]:
    with engine.connect() as connection:
        return {col["name"] for col in inspect(connection).get_columns(table)}


def _dm_context(table: TacticalTable) -> RoomAccessContext:
    return RoomAccessContext(
        room_id=table.room_id,
        access_session_id=table.dm_actor.access_session_id,
        authority=RoomAccessAuthority.DM,
    )


def _services(table: TacticalTable, engine: Engine) -> tuple[BattleMapService, MonsterLibraryService]:
    registry = load_default_content_registry()
    localization = load_content_localization_catalog(registry, resolve_content_root())
    map_service = BattleMapService(
        BattleMapRepository(engine),
        RoomAssetRepository(engine),
        table.events,
        content_registry=registry,
    )
    library = MonsterLibraryService(
        engine,
        MonsterLibraryRepository(engine),
        MonsterRepository(engine),
        registry,
        localization,
        TableEventService(TableEventRepository(engine)),
    )
    return map_service, library


def test_pg_prem07_to_current_heads_empty() -> None:
    """Empty schema: pre-M07 heads upgrade cleanly to current heads.

    Pins the pre-M07 shape (campaign-bound templates, no placements table,
    character track at its base) and the post-upgrade shape (Room-bound
    templates, placements table, both tracks at their heads).
    """
    _reset()
    config = _config()
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        command.upgrade(config, PRE_M07_WEB)
        assert _versions(engine) == [PRE_M07_WEB]
        assert "battle_map_monster_placements" not in _table_names(engine)
        assert _columns(engine, "monster_templates") == {
            "id", "campaign_id", "name", "source_key", "rules",
            "created_at", "updated_at",
        }
        # M07 never touched the character track: its marker column is absent.
        assert "state_revision" not in _columns(engine, "character_states")

        command.upgrade(config, "heads")
        assert _versions(engine) == [CHARACTER_HEAD, CURRENT_WEB]
        assert migration_heads(config) == {
            "character": CHARACTER_HEAD,
            "web": CURRENT_WEB,
        }
        assert "battle_map_monster_placements" in _table_names(engine)
        template_cols = _columns(engine, "monster_templates")
        assert "room_id" in template_cols
        assert "campaign_id" not in template_cols
        assert "revision" in template_cols
        assert "archived_at" in template_cols
        assert "state_revision" in _columns(engine, "character_states")
    finally:
        engine.dispose()


def _seed_m07_world(
    table: TacticalTable, engine: Engine
) -> dict[str, object]:
    """Build a Room library + finished tactical Combat through the real services."""
    map_service, library = _services(table, engine)
    ctx = _dm_context(table)

    created_template = library.create_custom(
        ctx, table.room_id,
        CreateCustomMonsterInput(
            name="Seeded Brute", size="Large", armor_class=14, max_hp=76,
        ),
    )
    template_id = UUID(created_template.ref.removeprefix("custom:"))

    created_map = map_service.create(
        ctx, room_id=table.room_id,
        payload=BattleMapCreate(
            name="Seed Lair", source_kind="blank", width_cells=20, height_cells=15
        ),
    )
    map_service.replace_monster_placements(
        ctx, room_id=table.room_id, map_id=created_map.id,
        payload=MonsterPlacementsReplace(
            expected_revision=1,
            placements=[
                MonsterPlacementInput(
                    template_key=GOBLIN_KEY, anchor_x=1, anchor_y=1,
                    visibility="public", sort_order=0,
                ),
                MonsterPlacementInput(
                    custom_template_id=template_id, anchor_x=6, anchor_y=6,
                    visibility="hidden", sort_order=1,
                ),
            ],
        ),
    )

    started = table.combat.start_tactical_combat(
        table.dm_actor,
        StartTacticalCombatInput(
            battle_map_id=created_map.id, load_map_monsters=True,
            include_active_party=True, idempotency_key="seeded-migration",
        ),
    )
    # Wound one loaded instance so HP retention is proven, not just defaults.
    with engine.begin() as connection:
        instance_ids = connection.execute(
            select(monster_instances.c.id)
            .join(combat_entries, combat_entries.c.monster_instance_id == monster_instances.c.id)
            .where(combat_entries.c.combat_id == started.id)
        ).scalars().all()
        assert len(instance_ids) == 2
        connection.execute(
            update(monster_instances)
            .where(monster_instances.c.id == instance_ids[0])
            .values(current_hp=monster_instances.c.current_hp - 5)
        )
    table.combat.end_combat(table.dm_actor)

    with engine.connect() as connection:
        template_row = dict(
            connection.execute(
                select(monster_templates).where(monster_templates.c.id == template_id)
            ).mappings().one()
        )
        instance_rows = [
            dict(row)
            for row in connection.execute(
                select(monster_instances)
                .join(combat_entries, combat_entries.c.monster_instance_id == monster_instances.c.id)
                .where(combat_entries.c.combat_id == started.id)
            ).mappings().all()
        ]
        board_row = dict(
            connection.execute(
                select(combat_boards).where(combat_boards.c.combat_id == started.id)
            ).mappings().one()
        )
        map_row = dict(
            connection.execute(
                select(battle_maps).where(battle_maps.c.id == created_map.id)
            ).mappings().one()
        )
    return {
        "template": template_row,
        "instances": instance_rows,
        "board": board_row,
        "map": map_row,
        "combat_id": started.id,
        "room_id": table.room_id,
        "campaign_id": table.campaign_id,
    }


def _source_map_fk_ondelete(engine: Engine) -> str | None:
    with engine.connect() as connection:
        fk = next(
            fk for fk in inspect(connection).get_foreign_keys("combat_boards")
            if fk["constrained_columns"] == ["source_battle_map_id"]
        )
    options = fk.get("options") or {}
    return options.get("ondelete")


def test_pg_prem07_to_current_heads_seeded() -> None:
    """Seeded schema: legacy rows survive pre-M07 -> current heads with retention.

    Provenance: templates backfill Room from their Campaign, identity/source/
    rules survive; Monster Instance identity/rules snapshot/HP survive; the
    finished board keeps its source map id + revision; deletion reference
    protection becomes RESTRICT; placements (a post-M07 concept) are created
    legally only after the upgrade and persist across a reconnect.
    """
    _reset()
    config = _config()
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        command.upgrade(config, "heads")
        table = setup_tactical_table(engine)
        seed = _seed_m07_world(table, engine)
        template = seed["template"]
        assert isinstance(template, dict)
        template_id = template["id"]
        map_id = seed["map"]["id"]  # type: ignore[index]

        # Down to the pre-M07 shape with the real rows in place.
        # The character branch is untouched by the web downgrade.
        command.downgrade(config, PRE_M07_WEB)
        assert _versions(engine) == [CHARACTER_HEAD, PRE_M07_WEB]
        assert _columns(engine, "monster_templates") == {
            "id", "campaign_id", "name", "source_key", "rules",
            "created_at", "updated_at",
        }
        with engine.connect() as connection:
            legacy = dict(
                connection.execute(
                    text(
                        "SELECT id, campaign_id, name, source_key, rules"
                        " FROM monster_templates WHERE id = :id"
                    ),
                    {"id": template_id},
                ).mappings().one()
            )
        assert legacy["campaign_id"] == seed["campaign_id"]
        assert legacy["name"] == "Seeded Brute"
        assert _source_map_fk_ondelete(engine) == "SET NULL"
        assert "battle_map_monster_placements" not in _table_names(engine)

        # Forward: pre-M07 heads -> current heads.
        command.upgrade(config, "heads")
        assert _versions(engine) == [CHARACTER_HEAD, CURRENT_WEB]
        assert migration_heads(config) == {
            "character": CHARACTER_HEAD,
            "web": CURRENT_WEB,
        }

        with engine.connect() as connection:
            row = dict(
                connection.execute(
                    select(monster_templates).where(monster_templates.c.id == template_id)
                ).mappings().one()
            )
        # Campaign-bound template backfilled to its Campaign's Room.
        assert row["room_id"] == seed["room_id"]
        assert row["name"] == template["name"]
        assert row["source_key"] == template["source_key"]
        assert row["rules"] == template["rules"]
        assert row["revision"] == 1
        assert row["archived_at"] is None

        with engine.connect() as connection:
            instances = [
                dict(r)
                for r in connection.execute(
                    select(monster_instances)
                    .join(
                        combat_entries,
                        combat_entries.c.monster_instance_id == monster_instances.c.id,
                    )
                    .where(combat_entries.c.combat_id == seed["combat_id"])
                ).mappings().all()
            ]
        assert {r["id"] for r in instances} == {r["id"] for r in seed["instances"]}  # type: ignore[index]
        for before in seed["instances"]:  # type: ignore[index]
            after = next(r for r in instances if r["id"] == before["id"])
            assert after["rules_snapshot"] == before["rules_snapshot"]
            assert after["custom_template_id"] == before["custom_template_id"]
            assert after["current_hp"] == before["current_hp"]
            assert after["visibility"] == before["visibility"]

        with engine.connect() as connection:
            board = dict(
                connection.execute(
                    select(combat_boards).where(combat_boards.c.combat_id == seed["combat_id"])
                ).mappings().one()
            )
            combat_status = connection.scalar(
                select(combats.c.status).where(combats.c.id == seed["combat_id"])
            )
        assert combat_status == "ended"
        assert board["source_battle_map_id"] == map_id
        assert board["source_battle_map_revision"] == seed["map"]["revision"]  # type: ignore[index]

        # Deletion reference protection is RESTRICT on real rows.
        assert _source_map_fk_ondelete(engine) == "RESTRICT"
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM monster_templates WHERE id = :id"),
                    {"id": template_id},
                )
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM battle_maps WHERE id = :id"), {"id": map_id}
                )

        # Placements did not exist pre-M07; create them legally post-upgrade
        # and prove they persist across a fresh connection (restart).
        map_service, _library = _services(table, engine)
        reread = map_service.get(_dm_context(table), table.room_id, map_id)
        assert reread.revision == seed["map"]["revision"]  # type: ignore[index]
        map_service.replace_monster_placements(
            _dm_context(table), room_id=table.room_id, map_id=map_id,
            payload=MonsterPlacementsReplace(
                expected_revision=reread.revision,
                placements=[
                    MonsterPlacementInput(
                        template_key=GOBLIN_KEY, anchor_x=2, anchor_y=2,
                        visibility="public", sort_order=0,
                    ),
                ],
            ),
        )
        engine.dispose()

        fresh = create_engine(POSTGRES_URL)
        try:
            with fresh.connect() as connection:
                count = connection.scalar(
                    select(func.count()).select_from(battle_map_monster_placements)
                    .where(battle_map_monster_placements.c.battle_map_id == map_id)
                )
                assert count == 1
                saved = dict(
                    connection.execute(
                        select(battle_map_monster_placements).where(
                            battle_map_monster_placements.c.battle_map_id == map_id
                        )
                    ).mappings().one()
                )
            assert saved["template_key"] == GOBLIN_KEY
            assert (saved["anchor_x"], saved["anchor_y"]) == (2, 2)
            assert saved["visibility"] == "public"
        finally:
            fresh.dispose()
    finally:
        engine.dispose()
