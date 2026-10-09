"""M07-D D6 (D.4): Room monster library sort & filter.

Covers every backend bullet of the D.4 test contract: each sort field
asc/desc, missing-values-last, stable ties, size/type/cr_eq/cr_min/cr_max
alone and combined, composition with query/source/include_archived,
pagination correctness across custom+builtin after sort/filter, 422 cases
with zero side effects, walk_speed parsing, and unchanged Room authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Generator
from uuid import UUID, uuid4

from fastapi import Request
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, event, insert
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from app.api.dependencies import (
    get_content_localization,
    get_content_registry,
    get_database_engine,
)
from app.api.errors import APIError
from app.api.rooms.access import get_room_access_context
from app.api.rooms.dependencies import get_monster_library_service
from app.content import load_default_content_registry
from app.content.localization_files import load_content_localization_catalog
from app.content.registry import resolve_content_root
from app.db import metadata
from app.domain.monster_library.service import MonsterLibraryService
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.table_events import TableEventService
from app.main import app
from app.persistence.combat.repository import MonsterRepository
from app.persistence.monster_library.repository import MonsterLibraryRepository
from app.persistence.rooms.table_runtime import TableEventRepository
from app.persistence.rooms.tables import campaigns, rooms


def _engine() -> Engine:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    metadata.create_all(engine)
    return engine


@dataclass(frozen=True)
class SortFilterFixture:
    client: TestClient
    engine: Engine
    room_id: UUID
    token_owner: str
    token_dm: str
    token_member: str
    library_service: MonsterLibraryService


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def sort_filter_fixture() -> Generator[SortFilterFixture, None, None]:
    engine = _engine()
    registry = load_default_content_registry()
    content_root = resolve_content_root()
    localization = load_content_localization_catalog(registry, content_root)

    room_id = uuid4()
    campaign_id = uuid4()
    now = datetime.now(timezone.utc)

    with engine.begin() as conn:
        conn.execute(
            insert(rooms).values(
                id=room_id,
                code="SORTROOM",
                name="Sort Room",
                password_salt=b"salt",
                password_hash=b"pw",
                owner_key_hash=b"owner",
                dm_key_hash=b"dm",
                created_at=now,
                updated_at=now,
            )
        )
        conn.execute(
            insert(campaigns).values(
                id=campaign_id,
                room_id=room_id,
                name="Campaign 1",
                ruleset="dnd-5e-2014",
                status="active",
                created_at=now,
                updated_at=now,
            )
        )

    token_owner = "tok-owner"
    token_dm = "tok-dm"
    token_member = "tok-member"

    token_to_context = {
        token_owner: RoomAccessContext(
            room_id=room_id,
            access_session_id=uuid4(),
            authority=RoomAccessAuthority.OWNER,
            display_name="Owner",
        ),
        token_dm: RoomAccessContext(
            room_id=room_id,
            access_session_id=uuid4(),
            authority=RoomAccessAuthority.DM,
            display_name="DM",
        ),
        token_member: RoomAccessContext(
            room_id=room_id,
            access_session_id=uuid4(),
            authority=RoomAccessAuthority.MEMBER,
            display_name="Member",
        ),
    }

    def _override_access(request: Request) -> RoomAccessContext:
        auth_hdr = request.headers.get("authorization", "")
        _, _, token = auth_hdr.partition(" ")
        clean = token.strip()
        if clean in token_to_context:
            return token_to_context[clean]
        raise APIError(401, "room_access_required", "Room access required")

    monster_repo = MonsterRepository(engine)
    library_repo = MonsterLibraryRepository(engine)
    event_repo = TableEventRepository(engine)
    table_event_service = TableEventService(event_repo)

    library_service = MonsterLibraryService(
        engine=engine,
        repository=library_repo,
        monster_repository=monster_repo,
        content_registry=registry,
        localization=localization,
        table_event_service=table_event_service,
    )

    app.state.content_registry = registry
    app.state.content_localization = localization
    app.state.monster_library_service = library_service

    app.dependency_overrides[get_database_engine] = lambda: engine
    app.dependency_overrides[get_content_registry] = lambda: registry
    app.dependency_overrides[get_content_localization] = lambda: localization
    app.dependency_overrides[get_room_access_context] = _override_access
    app.dependency_overrides[get_monster_library_service] = lambda: library_service

    client = TestClient(app)
    try:
        yield SortFilterFixture(
            client=client,
            engine=engine,
            room_id=room_id,
            token_owner=token_owner,
            token_dm=token_dm,
            token_member=token_member,
            library_service=library_service,
        )
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def _create_custom(
    fix: SortFilterFixture,
    name: str,
    *,
    armor_class: int = 10,
    max_hp: int = 10,
    size: str = "medium",
    monster_type: str = "humanoid",
    challenge_rating: float = 0.0,
    speed: object = None,
) -> dict:
    payload: dict[str, object] = {
        "name": name,
        "armor_class": armor_class,
        "max_hp": max_hp,
        "size": size,
        "type": monster_type,
        "challenge_rating": challenge_rating,
    }
    if speed is not None:
        payload["speed"] = speed
    resp = fix.client.post(
        f"/api/rooms/{fix.room_id}/monster-library/custom",
        json=payload,
        headers=_auth(fix.token_owner),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _list(
    fix: SortFilterFixture,
    params: dict[str, object],
    token: str | None = None,
):
    return fix.client.get(
        f"/api/rooms/{fix.room_id}/monster-library",
        params=params,
        headers=_auth(token or fix.token_owner),
    )


def _custom_count(fix: SortFilterFixture) -> int:
    resp = _list(fix, {"source": "custom", "limit": 100})
    assert resp.status_code == 200
    return len(resp.json())


def test_sort_each_field_asc_and_desc(sort_filter_fixture: SortFilterFixture) -> None:
    fix = sort_filter_fixture
    alpha = _create_custom(
        fix, "SF Alpha", armor_class=12, max_hp=10, challenge_rating=1.0,
        speed={"walk": "30 ft."},
    )
    beta = _create_custom(
        fix, "SF Beta", armor_class=10, max_hp=30, challenge_rating=0.5,
        speed={"walk": "20 ft."},
    )
    gamma = _create_custom(
        fix, "SF Gamma", armor_class=15, max_hp=20, challenge_rating=5.0,
        speed={"walk": "40 ft."},
    )
    refs = {"SF Alpha": alpha["ref"], "SF Beta": beta["ref"], "SF Gamma": gamma["ref"]}

    expectations = {
        "armor_class": (["SF Beta", "SF Alpha", "SF Gamma"], ["SF Gamma", "SF Alpha", "SF Beta"]),
        "max_hp": (["SF Alpha", "SF Gamma", "SF Beta"], ["SF Beta", "SF Gamma", "SF Alpha"]),
        "challenge_rating": (["SF Beta", "SF Alpha", "SF Gamma"], ["SF Gamma", "SF Alpha", "SF Beta"]),
        "walk_speed": (["SF Beta", "SF Alpha", "SF Gamma"], ["SF Gamma", "SF Alpha", "SF Beta"]),
        "name": (["SF Alpha", "SF Beta", "SF Gamma"], ["SF Gamma", "SF Beta", "SF Alpha"]),
    }
    for field, (asc_names, desc_names) in expectations.items():
        resp = _list(fix, {"source": "custom", "sort": field, "order": "asc"})
        assert resp.status_code == 200, resp.text
        assert [item["name"] for item in resp.json()] == asc_names
        assert [item["ref"] for item in resp.json()] == [refs[name] for name in asc_names]
        resp = _list(fix, {"source": "custom", "sort": field, "order": "desc"})
        assert resp.status_code == 200, resp.text
        assert [item["name"] for item in resp.json()] == desc_names


def test_sort_missing_values_last_both_orders(sort_filter_fixture: SortFilterFixture) -> None:
    fix = sort_filter_fixture
    _create_custom(fix, "SF Plain", armor_class=11, max_hp=9, challenge_rating=2.0)
    # Template without challenge_rating in stored rules.
    fix.library_service.repository.create_custom_template(
        room_id=fix.room_id,
        name="SF NoCR",
        rules={
            "name": "SF NoCR",
            "size": "medium",
            "type": "beast",
            "alignment": "unaligned",
            "armor_class": 11,
            "max_hp": 5,
            "speed": {"walk": "30 ft."},
        },
        presentation_json={"names": {}, "name_is_custom": True},
    )
    # Template with no walk speed (fly only).
    _create_custom(fix, "SF NoWalk", armor_class=11, max_hp=9, challenge_rating=3.0,
                   speed={"fly": "60 ft."})

    for order in ("asc", "desc"):
        resp = _list(
            fix,
            {"source": "custom", "sort": "challenge_rating", "order": order, "limit": 100},
        )
        assert resp.status_code == 200, resp.text
        names = [item["name"] for item in resp.json()]
        assert names[-1] == "SF NoCR"
        assert set(names) == {"SF Plain", "SF NoCR", "SF NoWalk"}

    for order in ("asc", "desc"):
        resp = _list(
            fix,
            {"source": "custom", "sort": "walk_speed", "order": order, "limit": 100},
        )
        assert resp.status_code == 200, resp.text
        names = [item["name"] for item in resp.json()]
        assert names[-1] == "SF NoWalk"
        assert set(names) == {"SF Plain", "SF NoCR", "SF NoWalk"}


def test_sort_stable_ties(sort_filter_fixture: SortFilterFixture) -> None:
    fix = sort_filter_fixture
    _create_custom(fix, "SF Tie B", armor_class=10, max_hp=42)
    _create_custom(fix, "SF Tie A", armor_class=10, max_hp=42)
    first = _create_custom(fix, "SF Same", armor_class=10, max_hp=42)
    second = _create_custom(fix, "SF Same", armor_class=10, max_hp=42)

    resp = _list(fix, {"source": "custom", "sort": "max_hp", "order": "asc", "limit": 100})
    assert resp.status_code == 200, resp.text
    names = [item["name"] for item in resp.json()]
    # Same HP: alphabetical name order wins over creation order.
    assert names.index("SF Tie A") < names.index("SF Tie B")
    # Identical names: deterministic ref order, stable across requests.
    same_refs = [item["ref"] for item in resp.json() if item["name"] == "SF Same"]
    assert same_refs == sorted(same_refs)
    assert set(same_refs) == {first["ref"], second["ref"]}
    again = _list(fix, {"source": "custom", "sort": "max_hp", "order": "asc", "limit": 100})
    assert [item["ref"] for item in again.json()] == [item["ref"] for item in resp.json()]

    desc = _list(fix, {"source": "custom", "sort": "max_hp", "order": "desc", "limit": 100})
    assert desc.status_code == 200
    desc_names = [item["name"] for item in desc.json()]
    assert desc_names.index("SF Tie A") < desc_names.index("SF Tie B")


def test_filter_size_type_cr_eq_alone(sort_filter_fixture: SortFilterFixture) -> None:
    fix = sort_filter_fixture
    _create_custom(fix, "SF Big Dragon", size="Large", monster_type="dragon", challenge_rating=7.0)
    _create_custom(fix, "SF Small Dragon", size="Small", monster_type="dragon", challenge_rating=7.0)
    _create_custom(fix, "SF Big Ooze", size="Large", monster_type="ooze", challenge_rating=1.0)

    resp = _list(fix, {"source": "custom", "size": "large", "limit": 100})
    assert resp.status_code == 200, resp.text
    assert {item["name"] for item in resp.json()} == {"SF Big Dragon", "SF Big Ooze"}

    # Canonical size match is case-insensitive.
    resp = _list(fix, {"source": "custom", "size": "LARGE", "limit": 100})
    assert resp.status_code == 200, resp.text
    assert {item["name"] for item in resp.json()} == {"SF Big Dragon", "SF Big Ooze"}

    resp = _list(fix, {"type": "dragon", "limit": 100})
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert len(items) > 2  # built-in dragons join the custom ones
    assert all(item["type"] is not None and item["type"].casefold() == "dragon" for item in items)
    assert {"SF Big Dragon", "SF Small Dragon"} <= {item["name"] for item in items}

    resp = _list(fix, {"source": "custom", "cr_eq": 7.0, "limit": 100})
    assert resp.status_code == 200, resp.text
    assert {item["name"] for item in resp.json()} == {"SF Big Dragon", "SF Small Dragon"}

    resp = _list(fix, {"source": "custom", "cr_eq": 0.125, "limit": 100})
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


def test_filter_cr_min_max_range(sort_filter_fixture: SortFilterFixture) -> None:
    fix = sort_filter_fixture
    _create_custom(fix, "SF CR One", challenge_rating=1.0)
    _create_custom(fix, "SF CR Five", challenge_rating=5.0)
    _create_custom(fix, "SF CR Ten", challenge_rating=10.0)

    resp = _list(fix, {"source": "custom", "cr_min": 2, "cr_max": 8, "limit": 100})
    assert resp.status_code == 200, resp.text
    assert [item["name"] for item in resp.json()] == ["SF CR Five"]

    # Bounds are inclusive.
    resp = _list(fix, {"source": "custom", "cr_min": 5, "cr_max": 5, "limit": 100})
    assert resp.status_code == 200, resp.text
    assert [item["name"] for item in resp.json()] == ["SF CR Five"]

    resp = _list(fix, {"source": "custom", "cr_min": 5, "limit": 100})
    assert resp.status_code == 200, resp.text
    assert {item["name"] for item in resp.json()} == {"SF CR Five", "SF CR Ten"}

    resp = _list(fix, {"source": "custom", "cr_max": 1, "limit": 100})
    assert resp.status_code == 200, resp.text
    assert [item["name"] for item in resp.json()] == ["SF CR One"]

    # Fractional CR values filter exactly.
    _create_custom(fix, "SF CR Eighth", challenge_rating=0.125)
    resp = _list(fix, {"source": "custom", "cr_min": 0.125, "cr_max": 0.25, "limit": 100})
    assert resp.status_code == 200, resp.text
    assert [item["name"] for item in resp.json()] == ["SF CR Eighth"]


def test_filters_combine_with_query_source_archived(sort_filter_fixture: SortFilterFixture) -> None:
    fix = sort_filter_fixture
    keeper = _create_custom(
        fix, "SF Combine Drake", size="Large", monster_type="dragon", challenge_rating=12.0,
    )
    _create_custom(
        fix, "SF Combine Wyrmling", size="Large", monster_type="dragon", challenge_rating=3.0,
    )
    _create_custom(
        fix, "SF Combine Ooze", size="Large", monster_type="ooze", challenge_rating=12.0,
    )
    doomed = _create_custom(
        fix, "SF Combine Ghost", size="Large", monster_type="dragon", challenge_rating=12.0,
    )
    template_id = doomed["ref"].removeprefix("custom:")
    arch = fix.client.post(
        f"/api/rooms/{fix.room_id}/monster-library/custom/{template_id}/archive",
        json={"expected_revision": 1},
        headers=_auth(fix.token_owner),
    )
    assert arch.status_code == 200, arch.text

    base = {
        "source": "custom",
        "size": "Large",
        "type": "dragon",
        "cr_min": 10,
        "cr_max": 15,
        "query": "combine",
        "limit": 100,
    }
    resp = _list(fix, base)
    assert resp.status_code == 200, resp.text
    assert [item["name"] for item in resp.json()] == ["SF Combine Drake"]

    resp = _list(fix, {**base, "include_archived": True})
    assert resp.status_code == 200, resp.text
    assert {item["name"] for item in resp.json()} == {"SF Combine Drake", "SF Combine Ghost"}
    assert keeper["ref"] in {item["ref"] for item in resp.json()}


def test_sort_filter_pagination_across_sources(sort_filter_fixture: SortFilterFixture) -> None:
    fix = sort_filter_fixture
    for idx in range(5):
        _create_custom(fix, f"SF Page Drake {idx}", monster_type="dragon",
                       max_hp=100 + idx, challenge_rating=11.0)

    def _fetch_all(params: dict[str, object], page_size: int) -> list[dict]:
        collected: list[dict] = []
        offset = 0
        while True:
            resp = _list(fix, {**params, "limit": page_size, "offset": offset})
            assert resp.status_code == 200, resp.text
            page = resp.json()
            collected.extend(page)
            if len(page) < page_size:
                break
            offset += page_size
        return collected

    params: dict[str, object] = {"sort": "max_hp", "order": "desc"}
    by_threes = _fetch_all(params, 3)
    by_sevens = _fetch_all(params, 7)
    assert [item["ref"] for item in by_threes] == [item["ref"] for item in by_sevens]
    hp_values = [item["max_hp"] for item in by_threes]
    assert hp_values == sorted(hp_values, reverse=True)
    assert len(by_threes) > 7  # custom + built-in span several pages

    dragon_params: dict[str, object] = {
        "type": "dragon",
        "cr_min": 10,
        "cr_max": 15,
        "sort": "max_hp",
        "order": "desc",
    }
    dragon_paged = _fetch_all(dragon_params, 2)
    assert len(dragon_paged) >= 5
    assert all(
        item["type"] is not None
        and item["type"].casefold() == "dragon"
        and 10 <= item["challenge_rating"] <= 15
        for item in dragon_paged
    )
    dragon_hp = [item["max_hp"] for item in dragon_paged]
    assert dragon_hp == sorted(dragon_hp, reverse=True)

    # Query composes with sort across pages.
    query_params: dict[str, object] = {"query": "page drake", "sort": "max_hp", "order": "desc"}
    query_paged = _fetch_all(query_params, 2)
    assert [item["name"] for item in query_paged] == [f"SF Page Drake {idx}" for idx in (4, 3, 2, 1, 0)]


def test_invalid_filters_422_zero_side_effects(sort_filter_fixture: SortFilterFixture) -> None:
    fix = sort_filter_fixture
    _create_custom(fix, "SF Witness", armor_class=10, max_hp=10)
    before = _custom_count(fix)

    bad_param_sets = [
        {"sort": "bogus"},
        {"order": "sideways"},
        {"cr_eq": 5, "cr_min": 1},
        {"cr_eq": 5, "cr_max": 9},
        {"cr_min": 9, "cr_max": 1},
    ]
    for bad in bad_param_sets:
        resp = _list(fix, bad)
        assert resp.status_code == 422, bad
        assert resp.json()["error"]["code"] == "invalid_monster_library_filter", bad

    assert _custom_count(fix) == before


def test_walk_speed_parsing(sort_filter_fixture: SortFilterFixture) -> None:
    fix = sort_filter_fixture
    multi = _create_custom(fix, "SF Multi Speed", speed={"walk": "40 ft.", "fly": "80 ft."})
    plain = _create_custom(fix, "SF Plain Speed", speed="25 ft.")
    flyer = _create_custom(fix, "SF Fly Only", speed={"fly": "60 ft."})

    resp = _list(fix, {"source": "custom", "query": "SF", "limit": 100})
    assert resp.status_code == 200, resp.text
    by_name = {item["name"]: item for item in resp.json()}
    assert by_name["SF Multi Speed"]["walk_speed"] == 40
    assert by_name["SF Plain Speed"]["walk_speed"] == 25
    assert by_name["SF Fly Only"]["walk_speed"] is None
    assert multi["ref"] in {item["ref"] for item in resp.json()}
    assert plain["ref"] in {item["ref"] for item in resp.json()}
    assert flyer["ref"] in {item["ref"] for item in resp.json()}

    resp = _list(fix, {"source": "builtin", "query": "goblin", "limit": 10})
    assert resp.status_code == 200, resp.text
    goblin = next(item for item in resp.json() if item["ref"] == "srd5.1:monster:goblin")
    assert goblin["walk_speed"] == 30

    resp = _list(fix, {"source": "builtin", "query": "air elemental", "limit": 10})
    assert resp.status_code == 200, resp.text
    elemental = next(
        item for item in resp.json() if item["ref"] == "srd5.1:monster:air-elemental"
    )
    assert elemental["walk_speed"] is None


def test_member_and_outsider_still_rejected_with_new_params(
    sort_filter_fixture: SortFilterFixture,
) -> None:
    fix = sort_filter_fixture
    params = {"sort": "max_hp", "order": "desc", "type": "dragon", "cr_min": 10}
    resp = _list(fix, params, token=fix.token_member)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "monster_library_forbidden"

    resp = fix.client.get(
        f"/api/rooms/{fix.room_id}/monster-library",
        params=params,
        headers=_auth("tok-unknown"),
    )
    assert resp.status_code == 401


def test_default_list_shape_gains_walk_speed(sort_filter_fixture: SortFilterFixture) -> None:
    fix = sort_filter_fixture
    _create_custom(fix, "SF Shape", armor_class=10, max_hp=10)
    resp = _list(fix, {})
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert len(items) > 0
    for item in items:
        assert "walk_speed" in item
        assert item["walk_speed"] is None or isinstance(item["walk_speed"], int)
    names = [item["name"] for item in items]
    assert names == sorted(names, key=str.casefold)
