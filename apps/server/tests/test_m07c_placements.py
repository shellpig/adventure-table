"""M07-C C1: map monster placements over the Human REST routes and service."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Engine

from app.api.rooms.dependencies import get_battle_map_service
from app.content.registry import load_default_content_registry
from app.domain.battle_maps.placements import (
    PlacementValidationEntry,
    resolve_placement_size,
    validate_monster_placements,
)
from app.domain.battle_maps.projector import project_battle_map
from app.domain.battle_maps.schemas import (
    BattleMapCreate,
    MonsterPlacementInput,
    MonsterPlacementsReplace,
)
from app.domain.battle_maps.service import BattleMapService
from app.domain.combat.resolution import SizeCategory
from app.domain.monster_library.errors import MonsterTemplateReferencedError
from app.domain.monster_library.service import MonsterLibraryService
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.table_events import TableEventService
from app.domain.spatial.primitives import BarrierSegment, GridCell
from app.main import app
from app.persistence.battle_maps.repository import BattleMapRepository
from app.persistence.battle_maps.tables import battle_map_monster_placements
from app.persistence.characters import characters
from app.persistence.combat.repository import MonsterRepository
from app.persistence.combat.tables import monster_instances, monster_templates
from app.persistence.monster_library.repository import MonsterLibraryRepository
from app.persistence.room_assets.repository import RoomAssetRepository
from app.persistence.rooms.table_runtime import TableEventRepository
from app.persistence.rooms.tables import campaign_seats
from tests.p5a_tactical_helpers import setup_tactical_table
from tests.test_m07a_authorization_and_mcp import AuthFixture, auth_fixture  # noqa: F401
from tests.test_p5a_battle_maps import (  # noqa: F401
    BattleMapFixture,
    _auth,
    _blank_payload,
    _create_map,
    _error_code,
    bm_fixture,
)

GOBLIN_KEY = "srd5.1:monster:goblin"  # Small -> 1x1 footprint
OGRE_KEY = "srd5.1:monster:ogre"  # Large -> 2x2 footprint


def _maps_url(room_id: UUID, suffix: str = "") -> str:
    return f"/api/rooms/{room_id}/battle-maps{suffix}"


def _put_placements(fx: BattleMapFixture, token: str, room_id: UUID, map_id: UUID, payload: dict):
    return fx.client.put(
        _maps_url(room_id, f"/{map_id}/monster-placements"),
        json=payload,
        headers=_auth(token),
    )


def _placement_payload(
    *,
    placement_id: UUID | None = None,
    template_key: str | None = None,
    custom_template_id: UUID | None = None,
    anchor: tuple[int, int] = (1, 1),
    visibility: str = "public",
    sort_order: int = 0,
) -> dict:
    payload: dict = {
        "anchor_x": anchor[0],
        "anchor_y": anchor[1],
        "visibility": visibility,
        "sort_order": sort_order,
    }
    if placement_id is not None:
        payload["id"] = str(placement_id)
    if template_key is not None:
        payload["template_key"] = template_key
    if custom_template_id is not None:
        payload["custom_template_id"] = str(custom_template_id)
    return payload


def _insert_custom_template(
    engine: Engine,
    room_id: UUID,
    *,
    name: str = "Ogre Brute",
    size: str = "Large",
    archived: bool = False,
) -> UUID:
    template_id = uuid4()
    now = datetime.now(timezone.utc)
    with engine.begin() as connection:
        connection.execute(
            insert(monster_templates).values(
                id=template_id,
                room_id=room_id,
                name=name,
                source_key=None,
                rules={"size": size, "armor_class": 11, "max_hp": 59},
                revision=1,
                archived_at=now if archived else None,
                presentation_json={},
                created_at=now,
                updated_at=now,
            )
        )
    return template_id


def _archive_template(engine: Engine, template_id: UUID) -> None:
    with engine.begin() as connection:
        connection.execute(
            update(monster_templates)
            .where(monster_templates.c.id == template_id)
            .values(archived_at=datetime.now(timezone.utc))
        )


def _placement_snapshot(engine: Engine, map_id: UUID) -> list[tuple]:
    with engine.connect() as connection:
        rows = connection.execute(
            select(battle_map_monster_placements)
            .where(battle_map_monster_placements.c.battle_map_id == map_id)
            .order_by(
                battle_map_monster_placements.c.sort_order,
                battle_map_monster_placements.c.id,
            )
        ).mappings().all()
    return [
        (
            str(row["id"]),
            row["template_key"],
            str(row["custom_template_id"]) if row["custom_template_id"] else None,
            row["anchor_x"],
            row["anchor_y"],
            row["visibility"],
            row["sort_order"],
        )
        for row in rows
    ]


def _map_state(fx: BattleMapFixture, token: str, room_id: UUID, map_id: UUID) -> tuple[int, list[tuple]]:
    body = fx.client.get(_maps_url(room_id, f"/{map_id}"), headers=_auth(token)).json()
    return body["revision"], _placement_snapshot(fx.engine, map_id)


def _table_counts(engine: Engine) -> tuple[int, int, int]:
    with engine.connect() as connection:
        return (
            int(connection.scalar(select(func.count()).select_from(monster_instances)) or 0),
            int(connection.scalar(select(func.count()).select_from(characters)) or 0),
            int(connection.scalar(select(func.count()).select_from(battle_map_monster_placements)) or 0),
        )


def _create_map_with_geometry(fx: BattleMapFixture) -> dict:
    """12x10 map with a vertical wall, a blocked cell and a closed door."""
    created = _create_map(fx, fx.token_owner_a, fx.room_a_id, {
        "name": "Lair", "source_kind": "blank", "width_cells": 12, "height_cells": 10,
    })
    assert created.status_code == 201
    map_id = created.json()["id"]
    put = fx.client.put(
        _maps_url(fx.room_a_id, f"/{map_id}/objects"),
        json={
            "expected_revision": 1,
            "walls": [{"x1": 5, "y1": 2, "x2": 5, "y2": 6, "visibility": "public"}],
            "doors": [{"x1": 4, "y1": 5, "x2": 5, "y2": 5,
                       "default_state": "closed", "visibility": "public"}],
            "terrain": [{"x": 8, "y": 8, "terrain_kind": "blocked"}],
            "drawings": [],
        },
        headers=_auth(fx.token_owner_a),
    )
    assert put.status_code == 200
    return put.json()


def _problems(response) -> list[dict]:
    return response.json()["error"]["params"]["problems"]


# --- happy path -------------------------------------------------------------


def test_put_replaces_whole_set_and_bumps_revision(bm_fixture: BattleMapFixture) -> None:
    fx = bm_fixture
    created = _create_map(fx, fx.token_owner_a, fx.room_a_id, _blank_payload()).json()
    custom_id = _insert_custom_template(fx.engine, fx.room_a_id)

    first = _put_placements(fx, fx.token_owner_a, fx.room_a_id, created["id"], {
        "expected_revision": 1,
        "placements": [
            _placement_payload(template_key=GOBLIN_KEY, anchor=(1, 1), visibility="hidden"),
            _placement_payload(custom_template_id=custom_id, anchor=(4, 4), sort_order=1),
        ],
    })
    assert first.status_code == 200
    body = first.json()
    assert body["revision"] == 2
    assert [(p["template_key"], p["custom_template_id"], p["anchor_x"], p["anchor_y"], p["visibility"], p["sort_order"])
            for p in body["monster_placements"]] == [
        (GOBLIN_KEY, None, 1, 1, "hidden", 0),
        (None, str(custom_id), 4, 4, "public", 1),
    ]
    first_ids = {p["id"] for p in body["monster_placements"]}

    # A second PUT replaces the whole set; the old rows are gone.
    second = _put_placements(fx, fx.token_dm_a, fx.room_a_id, created["id"], {
        "expected_revision": 2,
        "placements": [_placement_payload(template_key=OGRE_KEY, anchor=(2, 2))],
    })
    assert second.status_code == 200
    assert second.json()["revision"] == 3
    assert [p["template_key"] for p in second.json()["monster_placements"]] == [OGRE_KEY]
    assert {p["id"] for p in second.json()["monster_placements"]}.isdisjoint(first_ids)
    assert _placement_snapshot(fx.engine, UUID(created["id"])) == [
        (second.json()["monster_placements"][0]["id"], OGRE_KEY, None, 2, 2, "public", 0)
    ]


def test_put_empty_placements_is_legal(bm_fixture: BattleMapFixture) -> None:
    fx = bm_fixture
    created = _create_map(fx, fx.token_owner_a, fx.room_a_id, _blank_payload()).json()
    response = _put_placements(fx, fx.token_owner_a, fx.room_a_id, created["id"], {
        "expected_revision": 1, "placements": [],
    })
    assert response.status_code == 200
    assert response.json()["revision"] == 2
    assert response.json()["monster_placements"] == []


def test_put_stale_revision_rejected_with_zero_side_effects(bm_fixture: BattleMapFixture) -> None:
    fx = bm_fixture
    created = _create_map(fx, fx.token_owner_a, fx.room_a_id, _blank_payload()).json()
    ok = _put_placements(fx, fx.token_owner_a, fx.room_a_id, created["id"], {
        "expected_revision": 1,
        "placements": [_placement_payload(template_key=GOBLIN_KEY)],
    })
    assert ok.status_code == 200
    before = _map_state(fx, fx.token_owner_a, fx.room_a_id, UUID(created["id"]))

    stale = _put_placements(fx, fx.token_owner_a, fx.room_a_id, created["id"], {
        "expected_revision": 1,
        "placements": [_placement_payload(template_key=OGRE_KEY)],
    })
    assert stale.status_code == 409
    assert _error_code(stale) == "battle_map_revision_conflict"
    assert _map_state(fx, fx.token_owner_a, fx.room_a_id, UUID(created["id"])) == before


# --- actors that must not operate -------------------------------------------


def test_member_and_other_room_owner_cannot_put_or_read(bm_fixture: BattleMapFixture) -> None:
    fx = bm_fixture
    created = _create_map(fx, fx.token_owner_a, fx.room_a_id, _blank_payload()).json()
    ok = _put_placements(fx, fx.token_owner_a, fx.room_a_id, created["id"], {
        "expected_revision": 1,
        "placements": [_placement_payload(template_key=GOBLIN_KEY)],
    })
    assert ok.status_code == 200
    before = _map_state(fx, fx.token_owner_a, fx.room_a_id, UUID(created["id"]))

    payload = {"expected_revision": 2, "placements": [_placement_payload(template_key=OGRE_KEY)]}
    for token in (fx.token_member_a, fx.token_owner_b):
        put = _put_placements(fx, token, fx.room_a_id, created["id"], payload)
        assert put.status_code == 404
        assert _error_code(put) == "battle_map_not_found"
        # Reading the management DTO (which carries placements) is also denied.
        got = fx.client.get(_maps_url(fx.room_a_id, f"/{created['id']}"), headers=_auth(token))
        assert got.status_code == 404
    assert _map_state(fx, fx.token_owner_a, fx.room_a_id, UUID(created["id"])) == before


def test_dm_seat_controller_without_room_authority_cannot_put(auth_fixture: AuthFixture) -> None:
    fix = auth_fixture
    service = BattleMapService(
        BattleMapRepository(fix.engine), RoomAssetRepository(fix.engine),
        TableEventService(TableEventRepository(fix.engine)),
        content_registry=load_default_content_registry(),
    )
    app.dependency_overrides[get_battle_map_service] = lambda: service

    created = fix.client.post(
        f"/api/rooms/{fix.room_id}/battle-maps", json=_blank_payload("Seat map"),
        headers=_auth(fix.owner_token),
    )
    assert created.status_code == 201
    map_id = created.json()["id"]

    # A Member controlling the DM Seat still has no Room DM authority.
    with fix.engine.begin() as connection:
        connection.execute(
            update(campaign_seats)
            .where(campaign_seats.c.id == fix.dm_seat_id)
            .values(controller_access_session_id=fix.member_context.access_session_id)
        )
    put = fix.client.put(
        f"/api/rooms/{fix.room_id}/battle-maps/{map_id}/monster-placements",
        json={"expected_revision": 1,
              "placements": [_placement_payload(template_key=GOBLIN_KEY)]},
        headers=_auth(fix.member_token),
    )
    assert put.status_code == 404
    assert _error_code(put) == "battle_map_not_found"
    with fix.engine.connect() as connection:
        assert connection.scalar(
            select(func.count()).select_from(battle_map_monster_placements)
        ) == 0


# --- source rules ------------------------------------------------------------


def test_missing_builtin_key_is_404(bm_fixture: BattleMapFixture) -> None:
    fx = bm_fixture
    created = _create_map(fx, fx.token_owner_a, fx.room_a_id, _blank_payload()).json()
    before = _map_state(fx, fx.token_owner_a, fx.room_a_id, UUID(created["id"]))
    response = _put_placements(fx, fx.token_owner_a, fx.room_a_id, created["id"], {
        "expected_revision": 1,
        "placements": [_placement_payload(template_key="srd5.1:monster:nope")],
    })
    assert response.status_code == 404
    assert _error_code(response) == "monster_placement_reference_not_found"
    assert _map_state(fx, fx.token_owner_a, fx.room_a_id, UUID(created["id"])) == before


def test_missing_or_cross_room_custom_template_is_404(bm_fixture: BattleMapFixture) -> None:
    fx = bm_fixture
    created = _create_map(fx, fx.token_owner_a, fx.room_a_id, _blank_payload()).json()
    foreign = _insert_custom_template(fx.engine, fx.room_b_id, name="Foreign Brute")
    before = _map_state(fx, fx.token_owner_a, fx.room_a_id, UUID(created["id"]))
    for custom_id in (uuid4(), foreign):
        response = _put_placements(fx, fx.token_owner_a, fx.room_a_id, created["id"], {
            "expected_revision": 1,
            "placements": [_placement_payload(custom_template_id=custom_id)],
        })
        assert response.status_code == 404
        assert _error_code(response) == "monster_placement_reference_not_found"
    assert _map_state(fx, fx.token_owner_a, fx.room_a_id, UUID(created["id"])) == before


def test_both_or_neither_source_is_422(bm_fixture: BattleMapFixture) -> None:
    fx = bm_fixture
    created = _create_map(fx, fx.token_owner_a, fx.room_a_id, _blank_payload()).json()
    custom_id = _insert_custom_template(fx.engine, fx.room_a_id)
    for placements in (
        [_placement_payload(template_key=GOBLIN_KEY, custom_template_id=custom_id)],
        [_placement_payload()],
    ):
        response = _put_placements(fx, fx.token_owner_a, fx.room_a_id, created["id"], {
            "expected_revision": 1, "placements": placements,
        })
        assert response.status_code == 422
    assert _map_state(fx, fx.token_owner_a, fx.room_a_id, UUID(created["id"]))[0] == 1


def test_duplicate_placement_ids_is_422(bm_fixture: BattleMapFixture) -> None:
    fx = bm_fixture
    created = _create_map(fx, fx.token_owner_a, fx.room_a_id, _blank_payload()).json()
    shared = uuid4()
    response = _put_placements(fx, fx.token_owner_a, fx.room_a_id, created["id"], {
        "expected_revision": 1,
        "placements": [
            _placement_payload(placement_id=shared, template_key=GOBLIN_KEY),
            _placement_payload(placement_id=shared, template_key=OGRE_KEY, anchor=(5, 5)),
        ],
    })
    assert response.status_code == 422
    assert _error_code(response) == "monster_placement_invalid_source"
    assert _map_state(fx, fx.token_owner_a, fx.room_a_id, UUID(created["id"]))[0] == 1


# --- archived template rules --------------------------------------------------


def test_newly_archived_custom_template_rejected_with_problems(bm_fixture: BattleMapFixture) -> None:
    fx = bm_fixture
    created = _create_map(fx, fx.token_owner_a, fx.room_a_id, _blank_payload()).json()
    custom_id = _insert_custom_template(fx.engine, fx.room_a_id, archived=True)
    before = _map_state(fx, fx.token_owner_a, fx.room_a_id, UUID(created["id"]))
    goblin_id, archived_placement_id = uuid4(), uuid4()

    response = _put_placements(fx, fx.token_owner_a, fx.room_a_id, created["id"], {
        "expected_revision": 1,
        "placements": [
            _placement_payload(placement_id=goblin_id, template_key=GOBLIN_KEY),
            _placement_payload(placement_id=archived_placement_id, custom_template_id=custom_id, anchor=(4, 4)),
        ],
    })
    assert response.status_code == 409
    assert _error_code(response) == "map_monster_placement_invalid"
    problems = _problems(response)
    assert problems == [{"placement_id": str(archived_placement_id), "code": "template_archived"}]
    assert _map_state(fx, fx.token_owner_a, fx.room_a_id, UUID(created["id"])) == before


def test_unchanged_archived_reference_resend_succeeds(bm_fixture: BattleMapFixture) -> None:
    fx = bm_fixture
    created = _create_map(fx, fx.token_owner_a, fx.room_a_id, _blank_payload()).json()
    custom_id = _insert_custom_template(fx.engine, fx.room_a_id)
    first = _put_placements(fx, fx.token_owner_a, fx.room_a_id, created["id"], {
        "expected_revision": 1,
        "placements": [_placement_payload(custom_template_id=custom_id)],
    })
    assert first.status_code == 200
    saved = first.json()["monster_placements"]

    _archive_template(fx.engine, custom_id)
    # Resending the same saved set must not fail because of the archive.
    resend = _put_placements(fx, fx.token_owner_a, fx.room_a_id, created["id"], {
        "expected_revision": 2,
        "placements": [
            _placement_payload(
                placement_id=UUID(saved[0]["id"]), custom_template_id=custom_id,
                anchor=(saved[0]["anchor_x"], saved[0]["anchor_y"]),
            )
        ],
    })
    assert resend.status_code == 200
    assert resend.json()["revision"] == 3


def test_changed_to_archived_template_is_rejected(bm_fixture: BattleMapFixture) -> None:
    fx = bm_fixture
    created = _create_map(fx, fx.token_owner_a, fx.room_a_id, _blank_payload()).json()
    kept_id = _insert_custom_template(fx.engine, fx.room_a_id, name="Kept")
    archived_id = _insert_custom_template(fx.engine, fx.room_a_id, name="Archived")
    first = _put_placements(fx, fx.token_owner_a, fx.room_a_id, created["id"], {
        "expected_revision": 1,
        "placements": [_placement_payload(custom_template_id=kept_id)],
    })
    assert first.status_code == 200
    _archive_template(fx.engine, archived_id)

    # Swapping in the archived template is a *new* reference: rejected.
    response = _put_placements(fx, fx.token_owner_a, fx.room_a_id, created["id"], {
        "expected_revision": 2,
        "placements": [_placement_payload(custom_template_id=archived_id)],
    })
    assert response.status_code == 409
    assert _error_code(response) == "map_monster_placement_invalid"
    assert [p["code"] for p in _problems(response)] == ["template_archived"]
    revision, snapshot = _map_state(fx, fx.token_owner_a, fx.room_a_id, UUID(created["id"]))
    assert revision == 2
    assert [row[2] for row in snapshot] == [str(kept_id)]


# --- geometry validation ------------------------------------------------------


def test_geometry_problems_all_reported_not_first_only(bm_fixture: BattleMapFixture) -> None:
    fx = bm_fixture
    created = _create_map_with_geometry(fx)
    map_id = UUID(created["id"])
    before = _map_state(fx, fx.token_owner_a, fx.room_a_id, map_id)

    out_id, blocked_id, wall_id, first_overlap_id, second_overlap_id = (uuid4() for _ in range(5))
    response = _put_placements(fx, fx.token_owner_a, fx.room_a_id, map_id, {
        # objects PUT bumped the revision to 2.
        "expected_revision": 2,
        "placements": [
            # Large ogre at (11, 9): cells x=11..12 exceed the 12-wide map.
            _placement_payload(placement_id=out_id, template_key=OGRE_KEY, anchor=(11, 9)),
            # Goblin on the blocked cell (8, 8).
            _placement_payload(placement_id=blocked_id, template_key=GOBLIN_KEY, anchor=(8, 8)),
            # Large ogre at (4, 3): the x=5 wall cuts its footprint interior.
            _placement_payload(placement_id=wall_id, template_key=OGRE_KEY, anchor=(4, 3)),
            # Two goblins on the same cell.
            _placement_payload(placement_id=first_overlap_id, template_key=GOBLIN_KEY, anchor=(1, 1)),
            _placement_payload(placement_id=second_overlap_id, template_key=GOBLIN_KEY, anchor=(1, 1)),
        ],
    })
    assert response.status_code == 409
    assert _error_code(response) == "map_monster_placement_invalid"
    problems = _problems(response)
    by_id: dict[str, list[str]] = {}
    for problem in problems:
        by_id.setdefault(problem["placement_id"], []).append(problem["code"])
    assert by_id == {
        str(out_id): ["out_of_bounds"],
        str(blocked_id): ["blocked_terrain"],
        str(wall_id): ["wall_or_door_blocked"],
        str(first_overlap_id): ["overlapping_placement"],
        str(second_overlap_id): ["overlapping_placement"],
    }
    # The whole batch is rejected: revision, placements and objects unchanged.
    assert _map_state(fx, fx.token_owner_a, fx.room_a_id, map_id) == before
    reread = fx.client.get(_maps_url(fx.room_a_id, f"/{map_id}"), headers=_auth(fx.token_owner_a)).json()
    assert len(reread["walls"]) == 1 and len(reread["terrain"]) == 1


def test_closed_door_blocks_but_open_door_does_not(bm_fixture: BattleMapFixture) -> None:
    fx = bm_fixture
    created = _create_map_with_geometry(fx)
    map_id = UUID(created["id"])
    # The closed door at (4,5)-(5,5) cuts a Large footprint anchored at (4, 4).
    closed = _put_placements(fx, fx.token_owner_a, fx.room_a_id, map_id, {
        "expected_revision": 2,
        "placements": [_placement_payload(template_key=OGRE_KEY, anchor=(4, 4))],
    })
    assert closed.status_code == 409
    assert [p["code"] for p in _problems(closed)] == ["wall_or_door_blocked"]

    # Swap the door to open: the same placement is now legal.
    opened = fx.client.put(
        _maps_url(fx.room_a_id, f"/{map_id}/objects"),
        json={
            "expected_revision": 2,
            "walls": [{"x1": 5, "y1": 2, "x2": 5, "y2": 6, "visibility": "public"}],
            "doors": [{"x1": 4, "y1": 5, "x2": 5, "y2": 5,
                       "default_state": "open", "visibility": "public"}],
            "terrain": [{"x": 8, "y": 8, "terrain_kind": "blocked"}],
            "drawings": [],
        },
        headers=_auth(fx.token_owner_a),
    )
    assert opened.status_code == 200
    # Move the wall away too so only the door state differs meaningfully.
    retry = _put_placements(fx, fx.token_owner_a, fx.room_a_id, map_id, {
        "expected_revision": 3,
        "placements": [_placement_payload(template_key=OGRE_KEY, anchor=(6, 4))],
    })
    assert retry.status_code == 200


# --- lifecycle wiring --------------------------------------------------------


def test_objects_put_does_not_clear_placements(bm_fixture: BattleMapFixture) -> None:
    fx = bm_fixture
    created = _create_map(fx, fx.token_owner_a, fx.room_a_id, _blank_payload()).json()
    put = _put_placements(fx, fx.token_owner_a, fx.room_a_id, created["id"], {
        "expected_revision": 1,
        "placements": [_placement_payload(template_key=GOBLIN_KEY, anchor=(1, 1))],
    })
    assert put.status_code == 200

    objects = fx.client.put(
        _maps_url(fx.room_a_id, f"/{created['id']}/objects"),
        json={"expected_revision": 2,
              "walls": [{"x1": 0, "y1": 0, "x2": 3, "y2": 0, "visibility": "public"}],
              "doors": [], "terrain": [], "drawings": []},
        headers=_auth(fx.token_owner_a),
    )
    assert objects.status_code == 200
    body = objects.json()
    assert body["revision"] == 3
    assert len(body["monster_placements"]) == 1
    assert body["monster_placements"][0]["template_key"] == GOBLIN_KEY


def test_conflicting_geometry_change_rejected_with_zero_side_effects(bm_fixture: BattleMapFixture) -> None:
    fx = bm_fixture
    created = _create_map(fx, fx.token_owner_a, fx.room_a_id, {
        "name": "Lair", "source_kind": "blank", "width_cells": 12, "height_cells": 10,
    }).json()
    map_id = UUID(created["id"])
    put = _put_placements(fx, fx.token_owner_a, fx.room_a_id, map_id, {
        "expected_revision": 1,
        "placements": [_placement_payload(template_key=OGRE_KEY, anchor=(4, 4))],
    })
    assert put.status_code == 200
    before = _map_state(fx, fx.token_owner_a, fx.room_a_id, map_id)

    # A wall through the ogre's footprint interior rejects the whole objects PUT.
    conflict = fx.client.put(
        _maps_url(fx.room_a_id, f"/{map_id}/objects"),
        json={"expected_revision": 2,
              "walls": [{"x1": 5, "y1": 2, "x2": 5, "y2": 8, "visibility": "public"}],
              "doors": [], "terrain": [], "drawings": []},
        headers=_auth(fx.token_owner_a),
    )
    assert conflict.status_code == 409
    assert _error_code(conflict) == "map_monster_placement_invalid"
    assert [p["code"] for p in _problems(conflict)] == ["wall_or_door_blocked"]
    assert _map_state(fx, fx.token_owner_a, fx.room_a_id, map_id) == before
    reread = fx.client.get(_maps_url(fx.room_a_id, f"/{map_id}"), headers=_auth(fx.token_owner_a)).json()
    assert reread["walls"] == []


def test_patch_shrink_conflicting_with_placements_rejected(bm_fixture: BattleMapFixture) -> None:
    fx = bm_fixture
    created = _create_map(fx, fx.token_owner_a, fx.room_a_id, {
        "name": "Lair", "source_kind": "blank", "width_cells": 12, "height_cells": 10,
    }).json()
    map_id = UUID(created["id"])
    put = _put_placements(fx, fx.token_owner_a, fx.room_a_id, map_id, {
        "expected_revision": 1,
        "placements": [_placement_payload(template_key=OGRE_KEY, anchor=(10, 8))],
    })
    assert put.status_code == 200
    before = _map_state(fx, fx.token_owner_a, fx.room_a_id, map_id)

    shrink = fx.client.patch(
        _maps_url(fx.room_a_id, f"/{map_id}"),
        json={"expected_revision": 2, "width_cells": 11},
        headers=_auth(fx.token_owner_a),
    )
    assert shrink.status_code == 409
    assert _error_code(shrink) == "map_monster_placement_invalid"
    assert [p["code"] for p in _problems(shrink)] == ["out_of_bounds"]
    assert _map_state(fx, fx.token_owner_a, fx.room_a_id, map_id) == before

    # A shrink that does not touch any placement still works; use a name change
    # to prove patch never clears placements.
    ok = fx.client.patch(
        _maps_url(fx.room_a_id, f"/{map_id}"),
        json={"expected_revision": 2, "name": "Lair Renamed"},
        headers=_auth(fx.token_owner_a),
    )
    assert ok.status_code == 200
    assert ok.json()["revision"] == 3
    assert len(ok.json()["monster_placements"]) == 1


def test_copy_copies_placements_with_new_ids(bm_fixture: BattleMapFixture) -> None:
    fx = bm_fixture
    created = _create_map(fx, fx.token_owner_a, fx.room_a_id, _blank_payload()).json()
    custom_id = _insert_custom_template(fx.engine, fx.room_a_id)
    put = _put_placements(fx, fx.token_owner_a, fx.room_a_id, created["id"], {
        "expected_revision": 1,
        "placements": [
            _placement_payload(template_key=GOBLIN_KEY, anchor=(1, 1), visibility="hidden"),
            _placement_payload(custom_template_id=custom_id, anchor=(4, 4), sort_order=1),
        ],
    })
    assert put.status_code == 200
    source_ids = {p["id"] for p in put.json()["monster_placements"]}
    _archive_template(fx.engine, custom_id)

    copied = fx.client.post(
        _maps_url(fx.room_a_id, f"/{created['id']}/copy"),
        json={"expected_revision": 2},
        headers=_auth(fx.token_owner_a),
    )
    assert copied.status_code == 201
    body = copied.json()
    assert body["revision"] == 1
    copied_ids = {p["id"] for p in body["monster_placements"]}
    assert copied_ids.isdisjoint(source_ids)
    # References are preserved, including the archived one.
    assert [(p["template_key"], p["custom_template_id"], p["anchor_x"], p["anchor_y"],
             p["visibility"], p["sort_order"]) for p in body["monster_placements"]] == [
        (GOBLIN_KEY, None, 1, 1, "hidden", 0),
        (None, str(custom_id), 4, 4, "public", 1),
    ]
    # The source map is untouched.
    assert _map_state(fx, fx.token_owner_a, fx.room_a_id, UUID(created["id"]))[0] == 2


def test_editing_placements_creates_no_instances_or_character_changes(bm_fixture: BattleMapFixture) -> None:
    fx = bm_fixture
    created = _create_map(fx, fx.token_owner_a, fx.room_a_id, _blank_payload()).json()
    custom_id = _insert_custom_template(fx.engine, fx.room_a_id)
    before = _table_counts(fx.engine)

    for revision, placements in (
        (1, [_placement_payload(template_key=GOBLIN_KEY),
             _placement_payload(custom_template_id=custom_id, anchor=(4, 4))]),
        (2, [_placement_payload(template_key=OGRE_KEY, anchor=(2, 2))]),
        (3, []),
    ):
        response = _put_placements(fx, fx.token_owner_a, fx.room_a_id, created["id"], {
            "expected_revision": revision, "placements": placements,
        })
        assert response.status_code == 200

    instances, characters, _ = _table_counts(fx.engine)
    assert (instances, characters) == (before[0], before[1])


def test_delete_custom_template_with_placement_ref_is_409_not_500(bm_fixture: BattleMapFixture) -> None:
    fx = bm_fixture
    created = _create_map(fx, fx.token_owner_a, fx.room_a_id, _blank_payload()).json()
    custom_id = _insert_custom_template(fx.engine, fx.room_a_id)
    put = _put_placements(fx, fx.token_owner_a, fx.room_a_id, created["id"], {
        "expected_revision": 1,
        "placements": [_placement_payload(custom_template_id=custom_id)],
    })
    assert put.status_code == 200

    library = MonsterLibraryService(
        engine=fx.engine,
        repository=MonsterLibraryRepository(fx.engine),
        monster_repository=MonsterRepository(fx.engine),
        content_registry=load_default_content_registry(),
        localization=None,
        table_event_service=TableEventService(TableEventRepository(fx.engine)),
    )
    context = RoomAccessContext(
        room_id=fx.room_a_id, access_session_id=uuid4(),
        authority=RoomAccessAuthority.OWNER,
    )
    with pytest.raises(MonsterTemplateReferencedError):
        library.delete_custom(context, fx.room_a_id, custom_id, expected_revision=1)
    # The placement (and the template) survive the refused delete.
    assert _placement_snapshot(fx.engine, UUID(created["id"])) != []


# --- management DTO reads -----------------------------------------------------


def test_ai_dm_get_for_actor_includes_placements() -> None:
    table = setup_tactical_table()
    maps = BattleMapService(
        table.battle_maps, RoomAssetRepository(table.engine), table.events,
        content_registry=load_default_content_registry(),
    )
    owner = RoomAccessContext(
        room_id=table.room_id, access_session_id=uuid4(),
        authority=RoomAccessAuthority.OWNER,
    )
    created = maps.create(
        owner, room_id=table.room_id,
        payload=BattleMapCreate(name="Lair", source_kind="blank",
                               width_cells=10, height_cells=10),
    )
    replaced = maps.replace_monster_placements(
        owner, room_id=table.room_id, map_id=created.id,
        payload=MonsterPlacementsReplace(
            expected_revision=1,
            placements=[MonsterPlacementInput(
                template_key=GOBLIN_KEY, anchor_x=1, anchor_y=1,
                visibility="hidden",
            )],
        ),
    )
    assert len(replaced.monster_placements) == 1

    for_actor = maps.get_for_actor(table.dm_actor, created.id)
    assert [(p.template_key, p.visibility) for p in for_actor.monster_placements] == [
        (GOBLIN_KEY, "hidden")
    ]


def test_player_projection_never_carries_placements() -> None:
    table = setup_tactical_table()
    maps = BattleMapService(
        table.battle_maps, RoomAssetRepository(table.engine), table.events,
        content_registry=load_default_content_registry(),
    )
    owner = RoomAccessContext(
        room_id=table.room_id, access_session_id=uuid4(),
        authority=RoomAccessAuthority.OWNER,
    )
    created = maps.create(
        owner, room_id=table.room_id,
        payload=BattleMapCreate(name="Lair", source_kind="blank",
                               width_cells=10, height_cells=10),
    )
    with_placements = maps.replace_monster_placements(
        owner, room_id=table.room_id, map_id=created.id,
        payload=MonsterPlacementsReplace(
            expected_revision=1,
            placements=[MonsterPlacementInput(template_key=GOBLIN_KEY, anchor_x=1, anchor_y=1)],
        ),
    )
    assert len(with_placements.monster_placements) == 1
    projected = project_battle_map(with_placements, audience="player")
    assert "monster_placements" not in projected.model_dump()
    assert "monster_placements" not in projected.model_dump_json()


# --- pure validator unit tests -------------------------------------------------


def _entry(placement_id: UUID, size: SizeCategory, x: int, y: int) -> PlacementValidationEntry:
    return PlacementValidationEntry(placement_id=placement_id, size=size, anchor_x=x, anchor_y=y)


def test_validator_reports_every_problem_code() -> None:
    ids = [uuid4() for _ in range(6)]
    barriers = (
        BarrierSegment(x1=5, y1=2, x2=5, y2=6),  # wall cutting x=5
        BarrierSegment(x1=0, y1=7, x2=1, y2=7),  # closed door on y=7
    )
    blocked = frozenset({GridCell(x=8, y=8)})
    problems = validate_monster_placements(
        [
            _entry(ids[0], SizeCategory.LARGE, 11, 9),  # out of the 12x10 map
            _entry(ids[1], SizeCategory.SMALL, 8, 8),  # blocked cell
            _entry(ids[2], SizeCategory.LARGE, 4, 3),  # wall through interior
            _entry(ids[3], SizeCategory.LARGE, 0, 6),  # closed door through interior
            _entry(ids[4], SizeCategory.SMALL, 2, 2),  # overlap pair
            _entry(ids[5], SizeCategory.SMALL, 2, 2),  # overlap pair
        ],
        width_cells=12, height_cells=10,
        barriers=barriers, blocked_cells=blocked,
    )
    by_id: dict[UUID, list[str]] = {}
    for problem in problems:
        by_id.setdefault(problem.placement_id, []).append(problem.code)
    assert by_id == {
        ids[0]: ["out_of_bounds"],
        ids[1]: ["blocked_terrain"],
        ids[2]: ["wall_or_door_blocked"],
        ids[3]: ["wall_or_door_blocked"],
        ids[4]: ["overlapping_placement"],
        ids[5]: ["overlapping_placement"],
    }


def test_validator_clean_batch_and_boundary_wall() -> None:
    first, second = uuid4(), uuid4()
    problems = validate_monster_placements(
        [
            # A wall on the footprint *boundary* is fine.
            _entry(first, SizeCategory.LARGE, 3, 3),
            _entry(second, SizeCategory.SMALL, 8, 1),
        ],
        width_cells=12, height_cells=10,
        barriers=(BarrierSegment(x1=3, y1=0, x2=3, y2=10),),
        blocked_cells=frozenset(),
    )
    assert problems == []


def test_resolve_placement_size_follows_sizes_conventions() -> None:
    assert resolve_placement_size(None) == SizeCategory.MEDIUM
    assert resolve_placement_size("") == SizeCategory.MEDIUM
    assert resolve_placement_size("   ") == SizeCategory.MEDIUM
    assert resolve_placement_size("Large") == SizeCategory.LARGE
    assert resolve_placement_size("small") == SizeCategory.SMALL
    # Present but unparseable: the caller reports an invalid_size problem.
    assert resolve_placement_size("colossal-plus") is None
    assert resolve_placement_size(42) is None
