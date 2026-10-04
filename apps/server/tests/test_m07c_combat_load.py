"""M07-C C2: atomic Tactical monster load, name snapshots, idempotency intent.

Domain-level tests over ``setup_tactical_table()`` (in-memory SQLite) plus a
few REST route tests. PostgreSQL race tests live in
``tests/test_m07c_postgres.py``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Engine

from app.content import load_default_content_registry
from app.content.localization_files import load_content_localization_catalog
from app.domain.battle_maps.schemas import (
    BattleMapArchive,
    BattleMapCreate,
    MapMonsterPlacementInvalidError,
    MonsterPlacementReferenceNotFoundError,
    MonsterPlacementsReplace,
    MonsterPlacementInput,
)
from app.domain.battle_maps.service import BattleMapService
from app.domain.combat.lifecycle import (
    CombatIdempotencyConflictError,
    CombatPlacementIncompleteError,
    ResolveInitiativeOrderInput,
    StartTacticalCombatInput,
    tactical_start_intent,
)
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.table_events import TableEventActorUnauthorizedError
from app.paths import resolve_content_root
from app.persistence.battle_maps.repository import BattleMapRepository
from app.persistence.battle_maps.tables import battle_map_monster_placements
from app.persistence.rooms.table_runtime import TableEventSessionNotActivePersistenceError
from app.persistence.combat.tables import (
    combat_entries,
    combats,
    monster_instances,
    monster_templates,
)
from app.persistence.combat_boards.tables import combat_boards, combat_positions
from app.persistence.room_assets.repository import RoomAssetRepository
from app.persistence.rooms.table_runtime import session_events
from tests.p5a_tactical_helpers import TacticalTable, setup_tactical_table

GOBLIN_KEY = "srd5.1:monster:goblin"  # Small -> 1x1
OGRE_KEY = "srd5.1:monster:ogre"  # Large -> 2x2


def _table() -> tuple[TacticalTable, BattleMapService]:
    table = setup_tactical_table()
    battle_maps = BattleMapService(
        BattleMapRepository(table.engine),
        RoomAssetRepository(table.engine),
        table.events,
        content_registry=load_default_content_registry(),
    )
    return table, battle_maps


def _dm_context(table: TacticalTable) -> RoomAccessContext:
    return RoomAccessContext(
        room_id=table.room_id,
        access_session_id=table.dm_actor.access_session_id,
        authority=RoomAccessAuthority.DM,
    )


def _insert_custom_template(
    engine: Engine,
    room_id: UUID,
    *,
    name: str = "Ogre Brute",
    size: str = "Large",
    max_hp: int = 59,
    archived: bool = False,
    presentation: dict | None = None,
) -> UUID:
    template_id = uuid4()
    now = datetime.now(timezone.utc)
    rules = {
        "size": size,
        "armor_class": 11,
        "max_hp": max_hp,
        "speed": {"walk": "40 ft."},
        "ability_scores": {"dexterity": 8},
    }
    with engine.begin() as connection:
        connection.execute(
            insert(monster_templates).values(
                id=template_id,
                room_id=room_id,
                name=name,
                source_key=None,
                rules=rules,
                revision=1,
                archived_at=now if archived else None,
                presentation_json=presentation if presentation is not None else {},
                created_at=now,
                updated_at=now,
            )
        )
    return template_id


def _create_map(
    table: TacticalTable,
    battle_maps: BattleMapService,
    *,
    width: int = 20,
    height: int = 15,
) -> UUID:
    created = battle_maps.create(
        _dm_context(table),
        room_id=table.room_id,
        payload=BattleMapCreate(
            name="Load Map", source_kind="blank",
            width_cells=width, height_cells=height,
        ),
    )
    return created.id


def _put_placements(
    table: TacticalTable,
    battle_maps: BattleMapService,
    map_id: UUID,
    placements: list[MonsterPlacementInput],
    *,
    expected_revision: int = 1,
):
    return battle_maps.replace_monster_placements(
        _dm_context(table),
        room_id=table.room_id,
        map_id=map_id,
        payload=MonsterPlacementsReplace(
            expected_revision=expected_revision, placements=placements
        ),
    )


def _placement(
    *,
    template_key: str | None = None,
    custom_template_id: UUID | None = None,
    anchor: tuple[int, int] = (1, 1),
    visibility: str = "public",
    sort_order: int = 0,
) -> MonsterPlacementInput:
    return MonsterPlacementInput(
        template_key=template_key,
        custom_template_id=custom_template_id,
        anchor_x=anchor[0],
        anchor_y=anchor[1],
        visibility=visibility,
        sort_order=sort_order,
    )


def _counts(engine: Engine) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            "instances": connection.scalar(select(func.count()).select_from(monster_instances)),
            "combats": connection.scalar(select(func.count()).select_from(combats)),
            "entries": connection.scalar(select(func.count()).select_from(combat_entries)),
            "boards": connection.scalar(select(func.count()).select_from(combat_boards)),
            "positions": connection.scalar(select(func.count()).select_from(combat_positions)),
            "events": connection.scalar(select(func.count()).select_from(session_events)),
        }


def _event_cursor(engine: Engine, session_id: UUID) -> int:
    with engine.connect() as connection:
        return connection.scalar(
            select(func.max(session_events.c.seq)).where(
                session_events.c.session_id == session_id
            )
        ) or 0


def _start(
    table: TacticalTable,
    map_id: UUID,
    *,
    load_map_monsters: bool = True,
    idempotency_key: str | None = None,
    include_active_party: bool = True,
):
    return table.combat.start_tactical_combat(
        table.dm_actor,
        StartTacticalCombatInput(
            battle_map_id=map_id,
            load_map_monsters=load_map_monsters,
            include_active_party=include_active_party,
            idempotency_key=idempotency_key,
        ),
    )


def _monster_entries(table: TacticalTable, combat_id: UUID) -> list:
    with table.engine.connect() as connection:
        rows = connection.execute(
            select(combat_entries).where(combat_entries.c.combat_id == combat_id)
        ).mappings().all()
    return [dict(row) for row in rows if row["subject_kind"] == "monster"]


def _instance(table: TacticalTable, instance_id: UUID) -> dict:
    with table.engine.connect() as connection:
        row = connection.execute(
            select(monster_instances).where(monster_instances.c.id == instance_id)
        ).mappings().one()
    return dict(row)


# --- C.2 happy path ------------------------------------------------------------


def test_load_map_monsters_happy_path() -> None:
    table, battle_maps = _table()
    map_id = _create_map(table, battle_maps)
    custom_id = _insert_custom_template(table.engine, table.room_id)
    _put_placements(table, battle_maps, map_id, [
        _placement(template_key=GOBLIN_KEY, anchor=(1, 1), visibility="public", sort_order=0),
        _placement(custom_template_id=custom_id, anchor=(5, 5), visibility="hidden", sort_order=1),
    ])

    view = _start(table, map_id)

    assert view.mode == "tactical"
    monsters = _monster_entries(table, view.id)
    assert len(monsters) == 2
    # Party character still auto-included.
    assert any(e.subject_kind == "character" for e in
               table.combat.repository.list_entries(view.id))
    by_visibility = {m["monster_instance_id"]: m for m in monsters}
    instances = {iid: _instance(table, iid) for iid in by_visibility}
    vis = sorted(inst["visibility"] for inst in instances.values())
    assert vis == ["hidden", "public"]
    # Each monster got its own board position at the placement anchor.
    with table.engine.connect() as connection:
        positions = connection.execute(
            select(combat_positions).where(combat_positions.c.combat_id == view.id)
        ).mappings().all()
    assert len(positions) == 2
    anchors = sorted((p["anchor_x"], p["anchor_y"]) for p in positions)
    assert anchors == [(1, 1), (5, 5)]
    # Ogre is Large -> 2x2 footprint recorded.
    footprints = sorted((p["footprint_width"], p["footprint_height"]) for p in positions)
    assert footprints == [(1, 1), (2, 2)]
    # Board froze the map revision.
    board = table.board.get_board(table.dm_actor)
    assert board.source_battle_map_id == map_id
    assert board.source_battle_map_revision == 2


def test_load_empty_placements_starts_normally() -> None:
    table, battle_maps = _table()
    map_id = _create_map(table, battle_maps)
    view = _start(table, map_id)
    assert view.mode == "tactical"
    assert _monster_entries(table, view.id) == []


def test_load_flag_rejected_without_battle_map_source() -> None:
    with pytest.raises(Exception):
        StartTacticalCombatInput(
            blank_width_cells=10, blank_height_cells=10, load_map_monsters=True
        )
    with pytest.raises(Exception):
        StartTacticalCombatInput(
            temporary_map={
                "width_cells": 10, "height_cells": 10,
                "walls": [], "doors": [], "terrain": [], "drawings": [],
            },
            load_map_monsters=True,
        )


def test_start_intent_captures_source_flag_and_geometry() -> None:
    map_id = uuid4()
    intent = tactical_start_intent(
        StartTacticalCombatInput(battle_map_id=map_id, load_map_monsters=True)
    )
    assert intent == {
        "map_source": "battle_map",
        "battle_map_id": str(map_id),
        # M07-D D1 (F03): party inclusion is part of the idempotency intent.
        "include_active_party": True,
        "load_map_monsters": True,
        "temporary_geometry_digest": None,
        "blank_dimensions": None,
    }
    blank_intent = tactical_start_intent(
        StartTacticalCombatInput(blank_width_cells=8, blank_height_cells=6)
    )
    assert blank_intent["map_source"] == "blank"
    assert blank_intent["blank_dimensions"] == [8, 6]
    assert blank_intent["load_map_monsters"] is False


# --- C.2 latest template, whole-batch rejection --------------------------------


def test_load_uses_latest_template_size_not_placement_time_size() -> None:
    table, battle_maps = _table()
    map_id = _create_map(table, battle_maps)
    custom_id = _insert_custom_template(table.engine, table.room_id, size="Medium")
    # Two Medium (1x1) placements side by side: legal at edit time.
    _put_placements(table, battle_maps, map_id, [
        _placement(custom_template_id=custom_id, anchor=(3, 3), sort_order=0),
        _placement(template_key=GOBLIN_KEY, anchor=(4, 3), sort_order=1),
    ])
    # Template grows to Large after the placements were saved.
    with table.engine.begin() as connection:
        connection.execute(
            update(monster_templates)
            .where(monster_templates.c.id == custom_id)
            .values(rules={"size": "Large", "armor_class": 11, "max_hp": 59,
                           "speed": {"walk": "40 ft."}})
        )
    before = _counts(table.engine)
    cursor = _event_cursor(table.engine, table.session_id)
    with pytest.raises(MapMonsterPlacementInvalidError) as exc_info:
        _start(table, map_id)
    codes = sorted(problem.code for problem in exc_info.value.problems)
    assert codes == ["overlapping_placement", "overlapping_placement"]
    # Zero side effects: nothing created, cursor unmoved.
    assert _counts(table.engine) == before
    assert _event_cursor(table.engine, table.session_id) == cursor


def test_one_bad_placement_rolls_back_entire_start() -> None:
    table, battle_maps = _table()
    map_id = _create_map(table, battle_maps, width=10, height=8)
    custom_id = _insert_custom_template(table.engine, table.room_id)
    # Large (2x2) at (8,6) is legal on a 10x8 map at edit time.
    _put_placements(table, battle_maps, map_id, [
        _placement(template_key=GOBLIN_KEY, anchor=(1, 1), sort_order=0),
        _placement(custom_template_id=custom_id, anchor=(8, 6), sort_order=1),
    ])
    # Grow the template to Gargantuan after the save: the second placement
    # goes out of bounds at load time.
    with table.engine.begin() as connection:
        connection.execute(
            update(monster_templates)
            .where(monster_templates.c.id == custom_id)
            .values(rules={"size": "Gargantuan", "armor_class": 11, "max_hp": 59,
                           "speed": {"walk": "40 ft."}})
        )
    before = _counts(table.engine)
    cursor = _event_cursor(table.engine, table.session_id)
    with pytest.raises(MapMonsterPlacementInvalidError):
        _start(table, map_id)
    after = _counts(table.engine)
    assert after == before
    assert _event_cursor(table.engine, table.session_id) == cursor
    # The library map itself is untouched.
    with table.engine.connect() as connection:
        revision = connection.scalar(
            select(battle_map_monster_placements.c.id).where(
                battle_map_monster_placements.c.battle_map_id == map_id
            )
        )
    assert revision is not None


def test_archived_template_loads_from_saved_config() -> None:
    table, battle_maps = _table()
    map_id = _create_map(table, battle_maps)
    custom_id = _insert_custom_template(table.engine, table.room_id)
    _put_placements(table, battle_maps, map_id, [
        _placement(custom_template_id=custom_id, anchor=(2, 2)),
    ])
    # Archive after the placement was saved: load must still work.
    with table.engine.begin() as connection:
        connection.execute(
            update(monster_templates)
            .where(monster_templates.c.id == custom_id)
            .values(archived_at=datetime.now(timezone.utc))
        )
    view = _start(table, map_id)
    monsters = _monster_entries(table, view.id)
    assert len(monsters) == 1
    instance = _instance(table, monsters[0]["monster_instance_id"])
    assert instance["custom_template_id"] == custom_id


def test_dangling_builtin_template_reference_is_404() -> None:
    table, battle_maps = _table()
    map_id = _create_map(table, battle_maps)
    # Bypass the PUT validator (which would reject the unknown key) to simulate
    # a builtin entry that vanished from the content packs.
    with table.engine.begin() as connection:
        connection.execute(
            insert(battle_map_monster_placements).values(
                id=uuid4(), battle_map_id=map_id,
                template_key="srd5.1:monster:does-not-exist",
                custom_template_id=None, anchor_x=1, anchor_y=1,
                visibility="public", sort_order=0,
            )
        )
    before = _counts(table.engine)
    with pytest.raises(MonsterPlacementReferenceNotFoundError):
        _start(table, map_id)
    assert _counts(table.engine) == before


# --- C.2 idempotency -------------------------------------------------------------


def test_idempotent_retry_same_intent_returns_original_combat() -> None:
    table, battle_maps = _table()
    map_id = _create_map(table, battle_maps)
    _put_placements(table, battle_maps, map_id, [
        _placement(template_key=GOBLIN_KEY, anchor=(1, 1)),
    ])
    first = _start(table, map_id, idempotency_key="load-key-1")
    before = _counts(table.engine)
    second = _start(table, map_id, idempotency_key="load-key-1")
    assert second.id == first.id
    assert _counts(table.engine) == before
    assert len(_monster_entries(table, first.id)) == 1


def test_idempotent_retry_after_template_edit_does_not_respawn() -> None:
    table, battle_maps = _table()
    map_id = _create_map(table, battle_maps)
    _put_placements(table, battle_maps, map_id, [
        _placement(template_key=GOBLIN_KEY, anchor=(1, 1)),
    ])
    first = _start(table, map_id, idempotency_key="load-key-2")
    original_instance_ids = {
        m["monster_instance_id"] for m in _monster_entries(table, first.id)
    }
    # Edit the builtin-derived custom template after the start.
    custom_id = _insert_custom_template(table.engine, table.room_id, name="Renamed")
    _put_placements(
        table, battle_maps, map_id,
        [_placement(template_key=GOBLIN_KEY, anchor=(1, 1)),
         _placement(custom_template_id=custom_id, anchor=(6, 6))],
        expected_revision=2,
    )
    second = _start(table, map_id, idempotency_key="load-key-2")
    assert second.id == first.id
    assert {
        m["monster_instance_id"] for m in _monster_entries(table, first.id)
    } == original_instance_ids


def test_idempotent_retry_different_intent_is_409() -> None:
    table, battle_maps = _table()
    map_id = _create_map(table, battle_maps)
    other_map_id = _create_map(table, battle_maps)
    _put_placements(table, battle_maps, map_id, [
        _placement(template_key=GOBLIN_KEY, anchor=(1, 1)),
    ])
    first = _start(table, map_id, idempotency_key="load-key-3")
    before = _counts(table.engine)
    # Same key, load flag flipped.
    with pytest.raises(CombatIdempotencyConflictError):
        table.combat.start_tactical_combat(
            table.dm_actor,
            StartTacticalCombatInput(
                battle_map_id=map_id, load_map_monsters=False,
                idempotency_key="load-key-3",
            ),
        )
    # Same key, different map source.
    with pytest.raises(CombatIdempotencyConflictError):
        table.combat.start_tactical_combat(
            table.dm_actor,
            StartTacticalCombatInput(
                battle_map_id=other_map_id, load_map_monsters=True,
                idempotency_key="load-key-3",
            ),
        )
    # Nothing new was created by the conflicts.
    assert _counts(table.engine) == before
    assert table.combat.repository.get_active(table.campaign_id).id == first.id


def test_retry_after_combat_end_returns_original_result() -> None:
    table, battle_maps = _table()
    map_id = _create_map(table, battle_maps)
    _put_placements(table, battle_maps, map_id, [
        _placement(template_key=GOBLIN_KEY, anchor=(1, 1)),
    ])
    first = _start(table, map_id, idempotency_key="load-key-4")
    table.combat.end_combat(table.dm_actor)
    assert table.combat.repository.get_active(table.campaign_id) is None
    second = _start(table, map_id, idempotency_key="load-key-4")
    assert second.id == first.id
    assert second.status == "ended"


def test_retry_after_map_archived_returns_original_without_touching_map() -> None:
    table, battle_maps = _table()
    map_id = _create_map(table, battle_maps)
    _put_placements(table, battle_maps, map_id, [
        _placement(template_key=GOBLIN_KEY, anchor=(1, 1)),
    ])
    first = _start(table, map_id, idempotency_key="load-key-6")
    # Archive the map after the start; the retry must resolve from the stored
    # event and never read the map (the old eager freeze would raise
    # BattleMapArchivedError here).
    battle_maps.archive(
        _dm_context(table), room_id=table.room_id, map_id=map_id,
        payload=BattleMapArchive(expected_revision=2),
    )
    before = _counts(table.engine)
    second = _start(table, map_id, idempotency_key="load-key-6")
    assert second.id == first.id
    assert _counts(table.engine) == before


def test_new_key_cannot_start_in_ended_session() -> None:
    table, battle_maps = _table()
    map_id = _create_map(table, battle_maps)
    _put_placements(table, battle_maps, map_id, [
        _placement(template_key=GOBLIN_KEY, anchor=(1, 1)),
    ])
    first = _start(table, map_id, idempotency_key="load-key-5")
    # End the combat and the session.
    table.combat.end_combat(table.dm_actor)
    from app.domain.rooms.sessions import SessionService
    from app.persistence.rooms.session_live import SessionLiveRepository
    from app.persistence.rooms.sessions import SessionRepository

    sessions = SessionService(
        SessionRepository(table.engine),
        SessionLiveRepository(table.engine),
        event_service=table.events,
    )
    sessions.end_session(
        table.room_id, table.campaign_id, table.session_id, _dm_context(table)
    )
    before = _counts(table.engine)
    # The session gate lives inside the event transaction, after the
    # idempotency replay; the map is never touched for this rejected start.
    with pytest.raises(TableEventSessionNotActivePersistenceError):
        _start(table, map_id, idempotency_key="brand-new-key")
    assert _counts(table.engine) == before
    assert first.id is not None


def test_player_cannot_start_tactical_with_load_flag() -> None:
    table, battle_maps = _table()
    map_id = _create_map(table, battle_maps)
    _put_placements(table, battle_maps, map_id, [
        _placement(template_key=GOBLIN_KEY, anchor=(1, 1)),
    ])
    before = _counts(table.engine)
    with pytest.raises(TableEventActorUnauthorizedError):
        table.combat.start_tactical_combat(
            table.player_actor,
            StartTacticalCombatInput(
                battle_map_id=map_id, load_map_monsters=True,
                idempotency_key="player-key",
            ),
        )
    assert _counts(table.engine) == before


# --- C.2 name snapshots ------------------------------------------------------------


def test_rules_snapshot_carries_presentation_and_provenance() -> None:
    table, battle_maps = _table()
    map_id = _create_map(table, battle_maps)
    custom_id = _insert_custom_template(
        table.engine, table.room_id, name="Brute",
        presentation={"names": {"en": "Brute", "zh-TW": "蠻兵"}, "name_is_custom": True},
    )
    _put_placements(table, battle_maps, map_id, [
        _placement(template_key=GOBLIN_KEY, anchor=(1, 1), sort_order=0),
        _placement(custom_template_id=custom_id, anchor=(5, 5), sort_order=1),
    ])
    table.combat.content_localization = load_content_localization_catalog(
        load_default_content_registry(), resolve_content_root()
    )
    view = _start(table, map_id)
    monsters = _monster_entries(table, view.id)
    assert len(monsters) == 2
    by_key = {}
    for monster in monsters:
        inst = _instance(table, monster["monster_instance_id"])
        by_key[inst["template_key"] or str(inst["custom_template_id"])] = inst
    goblin = by_key[GOBLIN_KEY]
    assert goblin["rules_snapshot"]["presentation"] == {
        "names": {"en": "Goblin", "zh-TW": "地精"},
        "name_is_custom": False,
    }
    assert goblin["rules_snapshot"]["provenance"] == {"template_key": GOBLIN_KEY}
    assert goblin["name"] == "Goblin"
    brute = by_key[str(custom_id)]
    assert brute["rules_snapshot"]["presentation"] == {
        "names": {"en": "Brute", "zh-TW": "蠻兵"},
        "name_is_custom": True,
    }
    assert brute["rules_snapshot"]["provenance"] == {
        "custom_template_id": str(custom_id),
        "template_revision": 1,
    }
    assert brute["name"] == "Brute"


def test_snapshot_frozen_against_later_template_edits() -> None:
    table, battle_maps = _table()
    map_id = _create_map(table, battle_maps)
    custom_id = _insert_custom_template(table.engine, table.room_id, name="Brute")
    _put_placements(table, battle_maps, map_id, [
        _placement(custom_template_id=custom_id, anchor=(2, 2)),
    ])
    view = _start(table, map_id)
    monsters = _monster_entries(table, view.id)
    instance_id = monsters[0]["monster_instance_id"]
    before = _instance(table, instance_id)["rules_snapshot"]
    # Rename the template and bump its revision afterwards.
    with table.engine.begin() as connection:
        connection.execute(
            update(monster_templates)
            .where(monster_templates.c.id == custom_id)
            .values(
                name="Brute Renamed",
                revision=2,
                presentation_json={"names": {"en": "Brute Renamed"}, "name_is_custom": True},
                rules={"size": "Large", "armor_class": 13, "max_hp": 99,
                       "speed": {"walk": "40 ft."}},
            )
        )
    after = _instance(table, instance_id)["rules_snapshot"]
    assert after == before
    assert after["presentation"]["names"] == {"en": "Brute"}
    assert after["provenance"]["template_revision"] == 1


def test_party_initiative_gate_still_applies_with_loaded_monsters() -> None:
    table, battle_maps = _table()
    map_id = _create_map(table, battle_maps)
    _put_placements(table, battle_maps, map_id, [
        _placement(template_key=GOBLIN_KEY, anchor=(1, 1)),
    ])
    view = _start(table, map_id)
    # Loaded monsters are pre-placed, but the party character is not: the
    # existing initiative gate must still refuse to order.
    entries = table.combat.repository.list_entries(view.id)
    with pytest.raises(CombatPlacementIncompleteError):
        table.combat.resolve_initiative_order(
            table.dm_actor,
            ResolveInitiativeOrderInput(
                ordered_entry_ids=tuple(e.id for e in entries),
            ),
        )


# --- C.2 AI grant revocation -----------------------------------------------------


def _ai_dm_actor(table: TacticalTable):
    """Seat the AI as DM via a grant (mirrors test_p5f_tactical_mcp._dm_token)."""
    from datetime import UTC

    from sqlalchemy import insert as sa_insert
    from sqlalchemy import update as sa_update

    from app.domain.rooms.ai_controller_tokens import mint_ai_controller_token
    from app.persistence.rooms.tables import ai_controller_grants, campaign_seats, sessions

    minted = mint_ai_controller_token()
    now = datetime.now(UTC)
    with table.engine.begin() as conn:
        conn.execute(
            sa_insert(ai_controller_grants).values(
                id=minted.grant_id, room_id=table.room_id, campaign_id=table.campaign_id,
                seat_id=table.dm_actor.seat_id, role="dm", session_id=table.session_id,
                secret_hash=minted.secret_hash, secret_prefix=minted.display_hint,
                generation=1, status="active", pre_session_expires_at=None,
                handoff_return_access_session_id=None, temporary_instruction=None,
                created_at=now, bound_at=now, revoked_at=None, last_seen_at=None,
            )
        )
        conn.execute(
            sa_update(campaign_seats)
            .where(campaign_seats.c.id == table.dm_actor.seat_id)
            .values(
                controller_kind="ai", ai_controller_grant_id=minted.grant_id,
                controller_epoch=1, controller_access_session_id=None, updated_at=now,
            )
        )
        conn.execute(
            sa_update(sessions)
            .where(sessions.c.id == table.session_id)
            .values(
                dm_controller_kind="ai", dm_controller_ai_grant_id=minted.grant_id,
                dm_controller_generation=1, dm_controller_access_session_id=None,
            )
        )
    actor = table.events.resolve_ai_actor(
        room_id=table.room_id, campaign_id=table.campaign_id, session_id=table.session_id,
        grant_id=minted.grant_id, generation=1,
    )
    return actor, minted.grant_id


def _revoke_grant(table: TacticalTable, grant_id) -> None:
    from app.persistence.rooms.ai_controllers import AIControllerGrantRepository

    repo = AIControllerGrantRepository(table.engine)
    with table.engine.begin() as connection:
        repo.revoke_session_grants_in_transaction(connection, session_id=table.session_id)


def test_ai_grant_revoked_old_key_is_rejected_with_zero_side_effects() -> None:
    table, battle_maps = _table()
    map_id = _create_map(table, battle_maps)
    _put_placements(table, battle_maps, map_id, [
        _placement(template_key=GOBLIN_KEY, anchor=(1, 1)),
    ])
    ai_dm, grant_id = _ai_dm_actor(table)
    assert ai_dm.is_current_dm
    first = table.combat.start_tactical_combat(
        ai_dm,
        StartTacticalCombatInput(
            battle_map_id=map_id, load_map_monsters=True,
            idempotency_key="ai-dm-key-1",
        ),
    )
    before = _counts(table.engine)
    cursor = _event_cursor(table.engine, table.session_id)
    # Revoke the AI DM grant: the old key must now be rejected even though the
    # combat.started event exists.
    _revoke_grant(table, grant_id)
    with pytest.raises(TableEventActorUnauthorizedError):
        table.combat.start_tactical_combat(
            ai_dm,
            StartTacticalCombatInput(
                battle_map_id=map_id, load_map_monsters=True,
                idempotency_key="ai-dm-key-1",
            ),
        )
    assert _counts(table.engine) == before
    assert _event_cursor(table.engine, table.session_id) == cursor
    assert table.combat.repository.get_active(table.campaign_id).id == first.id


# --- C.2 session end / abandon then retry ----------------------------------------


def _session_service(table: TacticalTable):
    from app.domain.rooms.sessions import SessionService
    from app.persistence.rooms.session_live import SessionLiveRepository
    from app.persistence.rooms.sessions import SessionRepository

    return SessionService(
        SessionRepository(table.engine),
        SessionLiveRepository(table.engine),
        event_service=table.events,
    )


def test_retry_after_session_end_returns_original_combat() -> None:
    table, battle_maps = _table()
    map_id = _create_map(table, battle_maps)
    custom_id = _insert_custom_template(table.engine, table.room_id, name="Brute")
    _put_placements(table, battle_maps, map_id, [
        _placement(template_key=GOBLIN_KEY, anchor=(1, 1)),
        _placement(custom_template_id=custom_id, anchor=(5, 5)),
    ])
    first = _start(table, map_id, idempotency_key="load-key-end")
    instances_before = {m["monster_instance_id"] for m in _monster_entries(table, first.id)}
    assert len(instances_before) == 2
    # End the session (combat stays active).
    _session_service(table).end_session(
        table.room_id, table.campaign_id, table.session_id, _dm_context(table)
    )
    before = _counts(table.engine)
    # The DM binding is still current; the retry resolves from the stored event
    # before the session gate.
    second = _start(table, map_id, idempotency_key="load-key-end")
    assert second.id == first.id
    assert _counts(table.engine) == before
    assert {m["monster_instance_id"] for m in _monster_entries(table, first.id)} == instances_before
    # Editing the template after the session ended does not respawn anything.
    with table.engine.begin() as connection:
        connection.execute(
            update(monster_templates)
            .where(monster_templates.c.id == custom_id)
            .values(name="Brute Renamed", revision=2)
        )
    third = _start(table, map_id, idempotency_key="load-key-end")
    assert third.id == first.id
    assert {m["monster_instance_id"] for m in _monster_entries(table, first.id)} == instances_before


def test_retry_after_session_abandon_returns_original_combat() -> None:
    table, battle_maps = _table()
    map_id = _create_map(table, battle_maps)
    _put_placements(table, battle_maps, map_id, [
        _placement(template_key=GOBLIN_KEY, anchor=(1, 1)),
    ])
    first = _start(table, map_id, idempotency_key="load-key-abandon")
    instances_before = {m["monster_instance_id"] for m in _monster_entries(table, first.id)}
    _session_service(table).abandon_session(
        table.room_id, table.campaign_id, table.session_id, _dm_context(table)
    )
    before = _counts(table.engine)
    second = _start(table, map_id, idempotency_key="load-key-abandon")
    assert second.id == first.id
    assert _counts(table.engine) == before
    assert {m["monster_instance_id"] for m in _monster_entries(table, first.id)} == instances_before


# --- C.2 snapshot frozen against spellcasting edits -------------------------------


def test_snapshot_frozen_against_spellcasting_edit() -> None:
    table, battle_maps = _table()
    map_id = _create_map(table, battle_maps)
    custom_id = _insert_custom_template(table.engine, table.room_id, name="Shaman")
    _put_placements(table, battle_maps, map_id, [
        _placement(custom_template_id=custom_id, anchor=(2, 2)),
    ])
    view = _start(table, map_id)
    monsters = _monster_entries(table, view.id)
    instance_id = monsters[0]["monster_instance_id"]
    before = _instance(table, instance_id)["rules_snapshot"]
    assert "spellcasting" not in before.get("rules", {})
    # Add spellcasting to the template afterwards.
    with table.engine.begin() as connection:
        connection.execute(
            update(monster_templates)
            .where(monster_templates.c.id == custom_id)
            .values(
                revision=2,
                rules={"size": "Large", "armor_class": 11, "max_hp": 59,
                       "speed": {"walk": "40 ft."},
                       "spellcasting": {"ability": "wisdom", "save_dc": 13}},
            )
        )
    after = _instance(table, instance_id)["rules_snapshot"]
    assert after == before
    assert "spellcasting" not in after.get("rules", {})
    assert after["presentation"]["names"] == {"en": "Shaman"}
