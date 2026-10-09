"""M07-D D1 (F11): Session-scoped read-only libraries for the current DM.

A non-Owner Human on the current DM Seat can list/read the Room battle-map
and monster libraries from inside a Session (same DTOs and archived semantics
as the management routes). Player seats (whoever sits there), AI Players,
and cross-Room/Session callers are rejected. No authoring route exists.
"""

from __future__ import annotations

from urllib.parse import quote
from uuid import UUID

from fastapi.testclient import TestClient
import pytest

from app.api.rooms.access import get_room_access_context
from app.api.rooms.dependencies import (
    get_battle_map_service,
    get_monster_library_service,
    get_table_event_service,
)
from app.content import load_default_content_registry
from app.content.localization_files import load_content_localization_catalog
from app.content.registry import resolve_content_root
from app.domain.battle_maps.schemas import BattleMapArchive, BattleMapCreate
from app.domain.battle_maps.service import BattleMapService
from app.domain.monster_library.schemas import CreateCustomMonsterFromContentInput
from app.domain.monster_library.service import MonsterLibraryService
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.table_events import TableEventActorUnauthorizedError
from app.main import app
from app.persistence.battle_maps.repository import BattleMapRepository
from app.persistence.combat.repository import MonsterRepository
from app.persistence.monster_library.repository import MonsterLibraryRepository
from app.persistence.room_assets.repository import RoomAssetRepository
from tests.p5a_tactical_helpers import TacticalTable, setup_tactical_table
from tests.test_m07c_secrecy import _ai_player_actor

GOBLIN_KEY = "srd5.1:monster:goblin"


def _services(table: TacticalTable) -> tuple[BattleMapService, MonsterLibraryService]:
    registry = load_default_content_registry()
    battle_maps = BattleMapService(
        BattleMapRepository(table.engine),
        RoomAssetRepository(table.engine),
        table.events,
        content_registry=registry,
    )
    localization = load_content_localization_catalog(registry, resolve_content_root())
    library = MonsterLibraryService(
        table.engine,
        MonsterLibraryRepository(table.engine),
        MonsterRepository(table.engine),
        registry,
        localization,
        table.events,
    )
    return battle_maps, library


def _contexts(table: TacticalTable) -> dict[str, RoomAccessContext]:
    return {
        "dm": RoomAccessContext(
            room_id=table.room_id,
            access_session_id=table.dm_actor.access_session_id,
            authority=RoomAccessAuthority.DM,
        ),
        "player": RoomAccessContext(
            room_id=table.room_id,
            access_session_id=table.player_actor.access_session_id,
            authority=RoomAccessAuthority.OWNER,
        ),
    }


def _client(table: TacticalTable, who: str) -> TestClient:
    contexts = _contexts(table)
    battle_maps, library = _services(table)
    app.dependency_overrides[get_room_access_context] = lambda: contexts[who]
    app.dependency_overrides[get_table_event_service] = lambda: table.events
    app.dependency_overrides[get_battle_map_service] = lambda: battle_maps
    app.dependency_overrides[get_monster_library_service] = lambda: library
    return TestClient(app)


def _base(table: TacticalTable) -> str:
    return (
        f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
        f"/sessions/{table.session_id}/libraries"
    )


def _seed_map(table: TacticalTable, name: str = "DM Map") -> UUID:
    battle_maps, _ = _services(table)
    created = battle_maps.create(
        RoomAccessContext(
            room_id=table.room_id,
            access_session_id=table.dm_actor.access_session_id,
            authority=RoomAccessAuthority.DM,
        ),
        room_id=table.room_id,
        payload=BattleMapCreate(name=name, source_kind="blank", width_cells=12, height_cells=10),
    )
    return created.id


def _seed_custom(table: TacticalTable, content_key: str = GOBLIN_KEY) -> str:
    _, library = _services(table)
    detail = library.create_from_content(
        RoomAccessContext(
            room_id=table.room_id,
            access_session_id=table.dm_actor.access_session_id,
            authority=RoomAccessAuthority.OWNER,
        ),
        table.room_id,
        CreateCustomMonsterFromContentInput(content_key=content_key),
    )
    return detail.ref


# --- happy paths -----------------------------------------------------------------------


def test_current_dm_human_can_list_and_read_battle_maps() -> None:
    table = setup_tactical_table()
    map_id = _seed_map(table)
    client = _client(table, "dm")
    try:
        listing = client.get(f"{_base(table)}/battle-maps")
        assert listing.status_code == 200, listing.text
        assert str(map_id) in {item["id"] for item in listing.json()}
        single = client.get(f"{_base(table)}/battle-maps/{map_id}")
        assert single.status_code == 200, single.text
        assert single.json()["id"] == str(map_id)
        assert single.json()["name"] == "DM Map"
    finally:
        app.dependency_overrides.clear()


def test_current_dm_human_can_list_and_read_monster_library() -> None:
    table = setup_tactical_table()
    custom_ref = _seed_custom(table)
    client = _client(table, "dm")
    try:
        listing = client.get(f"{_base(table)}/monster-library", params={"query": "goblin"})
        assert listing.status_code == 200, listing.text
        refs = {item["ref"] for item in listing.json()}
        assert GOBLIN_KEY in refs
        assert custom_ref in refs
        # Same query/limit/offset/source semantics as the management route.
        queried = client.get(f"{_base(table)}/monster-library", params={"query": "goblin", "source": "custom"})
        assert queried.status_code == 200
        assert {item["ref"] for item in queried.json()} == {custom_ref}
        single = client.get(f"{_base(table)}/monster-library/{quote(custom_ref, safe='')}")
        assert single.status_code == 200, single.text
        assert single.json()["ref"] == custom_ref
        builtin = client.get(f"{_base(table)}/monster-library/{quote(GOBLIN_KEY, safe='')}")
        assert builtin.status_code == 200
        assert builtin.json()["source_kind"] == "builtin"
    finally:
        app.dependency_overrides.clear()


# --- rejections --------------------------------------------------------------------------


def test_player_seat_cannot_read_libraries() -> None:
    table = setup_tactical_table()
    _seed_map(table)
    client = _client(table, "player")
    try:
        for url in (
            f"{_base(table)}/battle-maps",
            f"{_base(table)}/monster-library",
        ):
            resp = client.get(url)
            assert resp.status_code == 403, (url, resp.text)
            assert resp.json()["error"]["code"] == "table_actor_unauthorized"
    finally:
        app.dependency_overrides.clear()


def test_same_person_on_player_seat_cannot_read_libraries() -> None:
    # The gate is seat-role based (actor.role == "dm" and is_current_dm), not
    # identity based: the product pins the DM Seat controller while its
    # Session is active, so "the same person on a Player Seat" resolves
    # through the identical non-DM path. Any current non-DM actor — whoever
    # they are — is rejected before any library row is touched.
    table = setup_tactical_table()
    battle_maps, library = _services(table)
    assert not table.player_actor.is_current_dm
    with pytest.raises(TableEventActorUnauthorizedError):
        library.list_for_actor(table.player_actor, table.room_id)
    with pytest.raises(TableEventActorUnauthorizedError):
        library.get_for_actor(table.player_actor, table.room_id, ref=GOBLIN_KEY)
    with pytest.raises(TableEventActorUnauthorizedError):
        battle_maps.list_for_actor(table.player_actor)
    from uuid import uuid4

    with pytest.raises(TableEventActorUnauthorizedError):
        battle_maps.get_for_actor(table.player_actor, uuid4())


def test_ai_player_cannot_use_session_libraries() -> None:
    table = setup_tactical_table()
    _, library = _services(table)
    ai_actor = _ai_player_actor(table)
    assert not ai_actor.is_current_dm
    with pytest.raises(TableEventActorUnauthorizedError):
        library.list_for_actor(ai_actor, table.room_id)
    with pytest.raises(TableEventActorUnauthorizedError):
        library.get_for_actor(ai_actor, table.room_id, ref=GOBLIN_KEY)


def test_cross_room_and_cross_session_are_404() -> None:
    from uuid import uuid4

    table = setup_tactical_table()
    client = _client(table, "dm")
    try:
        cross_room = client.get(
            f"/api/rooms/{uuid4()}/campaigns/{table.campaign_id}"
            f"/sessions/{table.session_id}/libraries/battle-maps"
        )
        assert cross_room.status_code == 404, cross_room.text
        cross_session = client.get(
            f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
            f"/sessions/{uuid4()}/libraries/battle-maps"
        )
        assert cross_session.status_code == 404, cross_session.text
    finally:
        app.dependency_overrides.clear()


def test_archived_lists_match_management_semantics() -> None:
    table = setup_tactical_table()
    battle_maps, _ = _services(table)
    map_id = _seed_map(table)
    dm_ctx = _contexts(table)["dm"]
    battle_maps.archive(
        dm_ctx, room_id=table.room_id, map_id=map_id,
        payload=BattleMapArchive(expected_revision=1),
    )
    client = _client(table, "dm")
    try:
        default = client.get(f"{_base(table)}/battle-maps")
        assert default.status_code == 200
        assert str(map_id) not in {item["id"] for item in default.json()}
        included = client.get(
            f"{_base(table)}/battle-maps", params={"include_archived": True}
        )
        assert included.status_code == 200
        assert str(map_id) in {item["id"] for item in included.json()}
        # Management route agrees on both views.
        assert {str(item.id) for item in battle_maps.list(dm_ctx, table.room_id)} == {
            item["id"] for item in default.json()
        }
        assert {str(item.id) for item in battle_maps.list(dm_ctx, table.room_id, include_archived=True)} == {
            item["id"] for item in included.json()
        }
        # Single archived map still reads (management parity).
        single = client.get(f"{_base(table)}/battle-maps/{map_id}")
        assert single.status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_no_authoring_routes_under_session_libraries() -> None:
    table = setup_tactical_table()
    client = _client(table, "dm")
    try:
        resp = client.post(f"{_base(table)}/battle-maps", json={})
        assert resp.status_code in (404, 405), resp.status_code
        resp = client.patch(f"{_base(table)}/battle-maps/{table.session_id}", json={})
        assert resp.status_code in (404, 405), resp.status_code
        resp = client.post(f"{_base(table)}/monster-library/custom", json={})
        assert resp.status_code in (404, 405), resp.status_code
        resp = client.delete(f"{_base(table)}/monster-library/custom/whatever")
        assert resp.status_code in (404, 405), resp.status_code
    finally:
        app.dependency_overrides.clear()
