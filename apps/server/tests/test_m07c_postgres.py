"""M07-C C1 PostgreSQL: 0043 migration up/down on real rows and constraints."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from alembic import command
import pytest
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from app.content.registry import load_default_content_registry
from app.domain.battle_maps.schemas import (
    BattleMapCreate,
    MapMonsterPlacementInvalidError,
    MonsterPlacementInput,
    MonsterPlacementsReplace,
)
from app.domain.battle_maps.service import BattleMapService
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.table_events import TableEventService
from app.persistence.battle_maps.repository import BattleMapRepository
from app.persistence.battle_maps.tables import battle_map_monster_placements
from app.persistence.room_assets.repository import RoomAssetRepository
from app.persistence.rooms.table_runtime import TableEventRepository
from tests.test_p5a_postgres_migration import POSTGRES_URL, _config, _reset

pytestmark = [
    pytest.mark.xdist_group("postgres"),
    pytest.mark.skipif(not POSTGRES_URL, reason="P4_POSTGRES_URL is only supplied by the PostgreSQL job"),
]

REVISION_0043 = "0043_m07c_map_monster_placements"
REVISION_0042 = "0042_m07b_battle_map_lifecycle"


def _seed_room_map_template(engine: Engine) -> tuple[object, object, object]:
    room_id, map_id, template_id = uuid4(), uuid4(), uuid4()
    now = datetime.now(timezone.utc)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO rooms (id, code, name, password_salt, password_hash,"
                " owner_key_hash, dm_key_hash, created_at, updated_at)"
                " VALUES (:id, 'M07C', 'Room', 's', 'h', 'o', 'd', :now, :now)"
            ),
            {"id": room_id, "now": now},
        )
        connection.execute(
            text(
                "INSERT INTO battle_maps (id, room_id, name, source_kind, width_cells,"
                " height_cells, revision, created_at, updated_at)"
                " VALUES (:id, :room_id, 'Lair', 'blank', 12, 10, 1, :now, :now)"
            ),
            {"id": map_id, "room_id": room_id, "now": now},
        )
        connection.execute(
            text(
                "INSERT INTO monster_templates (id, room_id, name, rules, revision,"
                " presentation_json, created_at, updated_at)"
                " VALUES (:id, :room_id, 'Brute', :rules, 1, '{}', :now, :now)"
            ),
            {
                "id": template_id,
                "room_id": room_id,
                "rules": '{"size": "Large"}',
                "now": now,
            },
        )
    return room_id, map_id, template_id


def _placement_count(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(
            connection.scalar(
                select(func.count()).select_from(battle_map_monster_placements)
            )
            or 0
        )


def test_m07c_0043_revision_id_fits_32_chars() -> None:
    assert len(REVISION_0043) <= 32


def test_m07c_0043_migrates_up_and_down_with_real_rows() -> None:
    _reset()
    config = _config()
    # The migration must run against the configured target database, never the
    # default alembic URL.
    assert config.attributes["target_database_url"] == POSTGRES_URL
    command.upgrade(config, "heads")
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        room_id, map_id, template_id = _seed_room_map_template(engine)
        placement_id = uuid4()
        with engine.begin() as connection:
            connection.execute(
                battle_map_monster_placements.insert().values(
                    id=placement_id,
                    battle_map_id=map_id,
                    template_key=None,
                    custom_template_id=template_id,
                    anchor_x=4,
                    anchor_y=4,
                    visibility="hidden",
                    sort_order=0,
                )
            )
        assert _placement_count(engine) == 1

        # Downgrade drops the placements table; the map and template survive.
        command.downgrade(config, REVISION_0042)
        assert "battle_map_monster_placements" not in inspect(engine).get_table_names()

        command.upgrade(config, REVISION_0043)
        assert "battle_map_monster_placements" in inspect(engine).get_table_names()
        assert _placement_count(engine) == 0

        # Exactly-one-source CHECK: both sources set is rejected by the DB.
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    battle_map_monster_placements.insert().values(
                        id=uuid4(),
                        battle_map_id=map_id,
                        template_key="srd5.1:monster:goblin",
                        custom_template_id=template_id,
                        anchor_x=1,
                        anchor_y=1,
                        visibility="public",
                        sort_order=0,
                    )
                )
        # ... and neither source set is rejected too.
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    battle_map_monster_placements.insert().values(
                        id=uuid4(),
                        battle_map_id=map_id,
                        template_key=None,
                        custom_template_id=None,
                        anchor_x=1,
                        anchor_y=1,
                        visibility="public",
                        sort_order=0,
                    )
                )
        # Visibility outside public|hidden is rejected.
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    battle_map_monster_placements.insert().values(
                        id=uuid4(),
                        battle_map_id=map_id,
                        template_key="srd5.1:monster:goblin",
                        custom_template_id=None,
                        anchor_x=1,
                        anchor_y=1,
                        visibility="dm_only",
                        sort_order=0,
                    )
                )
    finally:
        engine.dispose()


def test_m07c_0043_fk_restrict_and_cascade_on_real_rows() -> None:
    _reset()
    config = _config()
    command.upgrade(config, "heads")
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        room_id, map_id, template_id = _seed_room_map_template(engine)
        with engine.begin() as connection:
            connection.execute(
                battle_map_monster_placements.insert().values(
                    id=uuid4(),
                    battle_map_id=map_id,
                    template_key=None,
                    custom_template_id=template_id,
                    anchor_x=4,
                    anchor_y=4,
                    visibility="public",
                    sort_order=0,
                )
            )
        # RESTRICT: a referenced custom template cannot be deleted.
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM monster_templates WHERE id = :id"),
                    {"id": template_id},
                )
        # CASCADE: deleting the map removes its placements.
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM battle_maps WHERE id = :id"), {"id": map_id}
            )
        assert _placement_count(engine) == 0
    finally:
        engine.dispose()


def test_m07c_put_transaction_on_postgres() -> None:
    _reset()
    config = _config()
    command.upgrade(config, "heads")
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        room_id, _map_id, _template_id = _seed_room_map_template(engine)
        service = BattleMapService(
            BattleMapRepository(engine),
            RoomAssetRepository(engine),
            TableEventService(TableEventRepository(engine)),
            content_registry=load_default_content_registry(),
        )
        owner = RoomAccessContext(
            room_id=room_id, access_session_id=uuid4(),
            authority=RoomAccessAuthority.OWNER,
        )
        created = service.create(
            owner, room_id=room_id,
            payload=BattleMapCreate(
                name="Lair", source_kind="blank", width_cells=12, height_cells=10
            ),
        )
        replaced = service.replace_monster_placements(
            owner, room_id=room_id, map_id=created.id,
            payload=MonsterPlacementsReplace(
                expected_revision=1,
                placements=[
                    MonsterPlacementInput(
                        template_key="srd5.1:monster:ogre", anchor_x=4, anchor_y=4
                    ),
                    MonsterPlacementInput(
                        template_key="srd5.1:monster:goblin", anchor_x=1, anchor_y=1,
                        visibility="hidden",
                    ),
                ],
            ),
        )
        assert replaced.revision == 2
        assert len(replaced.monster_placements) == 2

        # A conflicting batch leaves the saved placements untouched.
        with pytest.raises(MapMonsterPlacementInvalidError):
            service.replace_monster_placements(
                owner, room_id=room_id, map_id=created.id,
                payload=MonsterPlacementsReplace(
                    expected_revision=2,
                    placements=[
                        MonsterPlacementInput(
                            template_key="srd5.1:monster:ogre", anchor_x=11, anchor_y=9
                        ),
                    ],
                ),
            )
        reread = service.get(owner, room_id, created.id)
        assert reread.revision == 2
        assert len(reread.monster_placements) == 2
    finally:
        engine.dispose()
