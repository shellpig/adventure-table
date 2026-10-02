"""P5-G G.4: concurrent stale races on Tactical state.

Three race groups, each with a real winner and a real loser:

1. Human (REST) vs AI Player (MCP) confirming the same movement with the
   same expected revisions: exactly one commits; the loser gets the stable
   machine code ``combat_movement_stale`` on both surfaces (REST HTTP 409,
   MCP structured error).
2. DM reposition vs a Player REST movement confirm on a stale revision: the
   DM correction wins; the Player confirm gets HTTP 409
   ``combat_movement_stale`` with zero side effects.
3. DM door runtime-state change vs a stale AoE propose: the door change
   advances the board runtime revision; the stale propose gets HTTP 409
   ``combat_board_stale`` with zero side effects (no combat action, no HP
   change, no new events).
"""

from __future__ import annotations

import asyncio
import contextlib
from uuid import UUID

from sqlalchemy import func, select, update

from app.api.dependencies import get_database_engine
from app.api.rooms.access import get_room_access_context
from app.api.rooms.dependencies import (
    get_combat_spell_service,
    get_movement_service,
    get_table_event_service,
)
from app.domain.combat.board import PlaceCombatantInput, UpdateDoorStateInput
from app.domain.combat.lifecycle import (
    ResolveInitiativeOrderInput,
    StartTacticalCombatInput,
)
from app.domain.combat.movement import MovementService, RepositionInput
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.mcp.tools import call_tool
from app.persistence.combat.tables import combat_actions, combat_entries
from app.persistence.rooms.table_runtime import session_events
from tests.p5a_tactical_helpers import (
    TacticalTable,
    insert_battle_map,
    setup_tactical_table,
)
from tests.test_p5d_aoe_tactical import (
    _add_monster,
    _character_entry_id,
    _enable_fireball_profile,
)
from tests.test_p5e_acceptance import _event_rows
from tests.test_p5e_e1b import _board, _combat, _position
from tests.test_p5f_f1b import _running_table
from tests.test_p5f_tactical_mcp import _facade, _player_token

FIREBALL_REF = "srd5.1:spell:fireball"


def _movement(table: TacticalTable) -> MovementService:
    return MovementService(
        board_repository=table.board.board_repository,
        board_service=table.board,
        combat_service=table.combat,
    )


@contextlib.contextmanager
def _rest_client(table: TacticalTable, *, movement=None, spells=None):
    """TestClient wired to one fixture table, acting as the Human player."""
    from fastapi.testclient import TestClient

    from app.main import app

    app.dependency_overrides[get_database_engine] = lambda: table.engine
    app.dependency_overrides[get_table_event_service] = lambda: table.events
    app.dependency_overrides[get_room_access_context] = lambda: RoomAccessContext(
        room_id=table.room_id,
        access_session_id=table.player_actor.access_session_id,
        authority=RoomAccessAuthority.MEMBER,
    )
    if movement is not None:
        app.dependency_overrides[get_movement_service] = lambda: movement
    if spells is not None:
        app.dependency_overrides[get_combat_spell_service] = lambda: spells
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _combat_base(table: TacticalTable) -> str:
    return (
        f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
        f"/sessions/{table.session_id}/combat"
    )


def _mcp_call(facade, token: str, name: str, arguments: dict) -> dict:
    auth = facade.ai_controller_service.authenticate(token)
    return asyncio.run(
        call_tool(facade, token=token, auth=auth, name=name, arguments=arguments)
    )


def _movement_events(table: TacticalTable) -> int:
    return len(_event_rows(table, "combat.movement_committed"))


def _g4_aoe_table() -> tuple[TacticalTable, UUID, UUID]:
    """Tactical AoE table on insert_battle_map (has the hidden door)."""
    table = setup_tactical_table()
    map_id = insert_battle_map(table)
    table.combat.start_tactical_combat(
        table.dm_actor, StartTacticalCombatInput(battle_map_id=map_id)
    )
    char_entry = _character_entry_id(table)
    goblin = _add_monster(table)
    table.board.place_position(
        table.dm_actor, char_entry, PlaceCombatantInput(anchor_x=1, anchor_y=1)
    )
    table.board.place_position(
        table.dm_actor, goblin, PlaceCombatantInput(anchor_x=5, anchor_y=5)
    )
    with table.engine.begin() as conn:
        for entry_id, total in ((char_entry, 20), (goblin, 10)):
            conn.execute(
                update(combat_entries)
                .where(combat_entries.c.id == entry_id)
                .values(initiative_total=total)
            )
    table.combat.resolve_initiative_order(
        table.dm_actor,
        ResolveInitiativeOrderInput(ordered_entry_ids=(char_entry, goblin)),
    )
    _enable_fireball_profile(table)
    return table, char_entry, goblin


def _action_count(table: TacticalTable) -> int:
    with table.engine.connect() as conn:
        return conn.execute(
            select(func.count()).select_from(combat_actions).where(
                combat_actions.c.combat_id == _combat(table).id
            )
        ).scalar_one()


def _session_event_count(table: TacticalTable) -> int:
    with table.engine.connect() as conn:
        return conn.execute(
            select(func.count()).select_from(session_events).where(
                session_events.c.session_id == table.session_id
            )
        ).scalar_one()


def _goblin_hp(table: TacticalTable, goblin: UUID) -> int:
    entry = table.combat.repository.get_entry(goblin)
    assert entry is not None
    instance = table.combat.monster_repository.get_instance(entry.monster_instance_id)
    assert instance is not None
    return int(instance.current_hp)


# ---------------------------------------------------------------------------
# 1. Human REST vs AI MCP: same subject, same path, same expected revisions
# ---------------------------------------------------------------------------


def test_p5g_g4_human_rest_vs_ai_mcp_movement_stale() -> None:
    table, char_entry, _monster_entry = _running_table()
    facade = _facade(table)
    movement = _movement(table)

    position = _position(table, char_entry)
    board_revision = _board(table).runtime_revision
    path_json = [{"x": 1, "y": 1}, {"x": 2, "y": 1}, {"x": 3, "y": 1}]
    events_before = _movement_events(table)

    with _rest_client(table, movement=movement) as client:
        base = _combat_base(table)
        # Human wins the race through the real REST route.
        rest_res = client.post(
            f"{base}/board/movement/confirm",
            json={
                "entry_id": str(char_entry),
                "path": path_json,
                "expected_position_revision": position.revision,
                "expected_board_revision": board_revision,
                "idempotency_key": "g4-rest-wins",
            },
        )
        assert rest_res.status_code == 200, rest_res.text
        assert rest_res.json()["outcome"] == "committed"

    # The AI handoff happens after the Human REST call: handing the seat to
    # the AI revokes the Human actor binding, so the REST leg must go first.
    ai_token = _player_token(table)

    # AI loses with the same stale revisions through the MCP tool.
    ai_result = _mcp_call(
        facade,
        ai_token,
        "combat_confirm_movement",
        {
            "entry_id": str(char_entry),
            "path": path_json,
            "expected_position_revision": position.revision,
            "expected_board_revision": board_revision,
            "idempotency_key": "g4-ai-loses",
        },
    )
    error = ai_result["structuredContent"]["error"]
    assert error["code"] == "combat_movement_stale"
    assert error["messages"]["en"]
    assert error["messages"]["zh-TW"]

    # Exactly one commit happened; the loser left no side effects.
    after = _position(table, char_entry)
    assert (after.anchor_x, after.anchor_y) == (3, 1)
    assert after.revision == position.revision + 1
    assert movement.movement_status(table.player_actor, char_entry).used_feet == 10
    assert _movement_events(table) == events_before + 1


# ---------------------------------------------------------------------------
# 2. DM reposition vs Player stale REST confirm
# ---------------------------------------------------------------------------


def test_p5g_g4_dm_reposition_vs_player_stale_confirm() -> None:
    table, char_entry, _monster_entry = _running_table()
    movement = _movement(table)

    position = _position(table, char_entry)
    board_revision = _board(table).runtime_revision
    path_json = [{"x": 1, "y": 1}, {"x": 2, "y": 1}, {"x": 3, "y": 1}]
    corrected_before = len(_event_rows(table, "combat.position_corrected"))
    committed_before = _movement_events(table)

    # DM correction wins first.
    repositioned = movement.reposition(
        table.dm_actor,
        char_entry,
        RepositionInput(
            entry_id=char_entry,
            anchor_x=2,
            anchor_y=2,
            reason="DM correction",
            expected_position_revision=position.revision,
            idempotency_key="g4-dm-reposition",
        ),
    )
    assert (repositioned.anchor_x, repositioned.anchor_y) == (2, 2)
    assert len(_event_rows(table, "combat.position_corrected")) == corrected_before + 1

    # Player confirms with the pre-reposition revisions through REST.
    with _rest_client(table, movement=movement) as client:
        res = client.post(
            f"{_combat_base(table)}/board/movement/confirm",
            json={
                "entry_id": str(char_entry),
                "path": path_json,
                "expected_position_revision": position.revision,
                "expected_board_revision": board_revision,
                "idempotency_key": "g4-player-loses",
            },
        )
    assert res.status_code == 409, res.text
    assert res.json()["error"]["code"] == "combat_movement_stale"

    # The loser changed nothing: DM position stands, no movement committed.
    after = _position(table, char_entry)
    assert (after.anchor_x, after.anchor_y) == (2, 2)
    assert movement.movement_status(table.player_actor, char_entry).used_feet == 0
    assert _movement_events(table) == committed_before


# ---------------------------------------------------------------------------
# 3. DM door runtime-state change vs stale AoE propose
# ---------------------------------------------------------------------------


def test_p5g_g4_dm_door_change_vs_stale_aoe_propose() -> None:
    table, char_entry, goblin = _g4_aoe_table()
    spells_service = _spells_for(table)

    # Player captures the board revision before the DM's change.
    board_revision = _board(table).runtime_revision

    # DM changes the hidden door's runtime state: the board runtime revision
    # advances underneath the player's proposal.
    door_id = next(
        d.door_id
        for d in table.board.get_board(table.dm_actor).doors
        if (d.x1, d.y1, d.x2, d.y2) == (5, 0, 6, 0)
    )
    table.board.update_door_state(
        table.dm_actor,
        door_id,
        UpdateDoorStateInput(
            state="open",
            revealed=False,
            expected_runtime_revision=board_revision,
            idempotency_key="g4-door-open",
        ),
    )
    assert _board(table).runtime_revision == board_revision + 1

    actions_before = _action_count(table)
    events_before = _session_event_count(table)
    hp_before = _goblin_hp(table, goblin)

    # The stale propose goes through the real REST route: 409, zero side effects.
    with _rest_client(table, spells=spells_service) as client:
        res = client.post(
            f"{_combat_base(table)}/spells/aoe/propose",
            json={
                "caster_entry_id": str(char_entry),
                "spell_ref": FIREBALL_REF,
                "slot_level": 3,
                "profile_id": "wizard",
                "proposed_target_ids": [str(goblin)],
                "template": {
                    "shape": "circle",
                    "size_feet": 20,
                    "origin_x": 5,
                    "origin_y": 5,
                },
                "board_revision": board_revision,
                "idempotency_key": "g4-aoe-loses",
            },
        )
    assert res.status_code == 409, res.text
    assert res.json()["error"]["code"] == "combat_board_stale"

    assert _action_count(table) == actions_before
    assert _session_event_count(table) == events_before
    assert _goblin_hp(table, goblin) == hp_before


def _spells_for(table: TacticalTable):
    from tests.test_p5d_aoe_tactical import _spells

    return _spells(table)
