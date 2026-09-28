"""P5-G G.6: secrecy matrix — every secret, every actor, every surface.

Actors: dm / human_player / ai_player.
Secrets: hidden token id + coords, hidden door id + runtime state, hidden
wall coords, enemy precise HP/AC, runtime secret ids.
Surfaces: REST board, Session Resume, Player event stream,
MCP combat_get_board, MCP get_session_context, hidden interruption
response/event, AoE preview, target check.

Each surface test asserts the DM sees the true value and both player kinds
see nothing: no hidden ids, no hidden coords, no hidden door state, no
enemy HP/AC fields, and — for ordering surfaces — no count/order side
channel.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select, update

from app.api.rooms.access import get_room_access_context
from app.api.rooms.dependencies import get_combat_board_service, get_table_event_service
from app.domain.combat.board import PlaceCombatantInput, UpdateDoorStateInput
from app.domain.combat.lifecycle import (
    ResolveInitiativeOrderInput,
    StartTacticalCombatInput,
)
from app.domain.combat.movement import (
    ConfirmMovementInput,
    MovementAnchorInput,
    MovementService,
)
from app.domain.combat.spell_service import AoeTemplateInput, PreviewAoeSpellInput
from app.domain.combat.target_check import TargetCheckInput, TargetCheckService
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.mcp.tools import call_tool
from app.persistence.combat.tables import combat_entries
from app.persistence.rooms.table_runtime import session_events
from tests.p5a_tactical_helpers import (
    TacticalTable,
    insert_battle_map,
    setup_tactical_table,
)
from tests.test_p5d_aoe_tactical import (
    FIREBALL_REF,
    _add_monster,
    _character_entry_id,
    _enable_fireball_profile,
)
from tests.test_p5f_tactical_mcp import _dm_token, _facade, _player_token


# ---------------------------------------------------------------------------
# Fixture: one rich tactical table with every secret class present
# ---------------------------------------------------------------------------


@dataclass
class SecrecyTable:
    table: TacticalTable
    char_entry: UUID
    goblin: UUID
    stalker: UUID
    hidden_door_id: UUID
    goblin_ac: int = 15
    goblin_max_hp: int = 7


def _secrecy_table() -> SecrecyTable:
    table = setup_tactical_table()
    map_id = insert_battle_map(table)
    table.combat.start_tactical_combat(
        table.dm_actor, StartTacticalCombatInput(battle_map_id=map_id)
    )
    char_entry = _character_entry_id(table)
    goblin = _add_monster(table)  # public, AC 15, max HP 7
    stalker = _add_monster(table, visibility="hidden")
    table.board.place_position(
        table.dm_actor, char_entry, PlaceCombatantInput(anchor_x=1, anchor_y=1)
    )
    table.board.place_position(
        table.dm_actor, goblin, PlaceCombatantInput(anchor_x=5, anchor_y=5)
    )
    table.board.place_position(
        table.dm_actor, stalker, PlaceCombatantInput(anchor_x=3, anchor_y=1)
    )
    with table.engine.begin() as conn:
        for entry_id, total in ((char_entry, 20), (goblin, 15), (stalker, 10)):
            conn.execute(
                update(combat_entries)
                .where(combat_entries.c.id == entry_id)
                .values(initiative_total=total)
            )
    table.combat.resolve_initiative_order(
        table.dm_actor,
        ResolveInitiativeOrderInput(ordered_entry_ids=(char_entry, goblin, stalker)),
    )
    _enable_fireball_profile(table)
    hidden_door_id = next(
        d.door_id
        for d in table.board.get_board(table.dm_actor).doors
        if (d.x1, d.y1, d.x2, d.y2) == (5, 0, 6, 0)
    )
    # DM changes the hidden door's runtime state but does not reveal it.
    table.board.update_door_state(
        table.dm_actor,
        hidden_door_id,
        UpdateDoorStateInput(
            state="open",
            revealed=False,
            expected_runtime_revision=table.board.get_board(
                table.dm_actor
            ).runtime_revision,
            idempotency_key="g6-door-open",
        ),
    )
    return SecrecyTable(
        table=table,
        char_entry=char_entry,
        goblin=goblin,
        stalker=stalker,
        hidden_door_id=hidden_door_id,
    )


def _movement(table: TacticalTable) -> MovementService:
    return MovementService(
        board_repository=table.board.board_repository,
        board_service=table.board,
        combat_service=table.combat,
    )


def _spells(table: TacticalTable):
    from tests.test_p5d_aoe_tactical import _spells

    return _spells(table)


def _resume_service(table: TacticalTable):
    """Real SessionResumeService wired over the fixture engine (no HTTP)."""
    from app.domain.rooms.campaigns import CampaignService
    from app.domain.rooms.exploration import ExplorationStageService
    from app.domain.rooms.seats import SeatService
    from app.domain.rooms.session_resume import SessionResumeService
    from app.domain.rooms.sessions import SessionService
    from app.persistence.rooms.campaigns import CampaignRepository
    from app.persistence.mcp.room_lifecycle import M04BSeatRepository, M04BSessionRepository
    from app.persistence.rooms.exploration import ExplorationRepository
    from app.persistence.rooms.repository import RoomRepository
    from app.persistence.rooms.session_live import SessionLiveRepository
    from app.persistence.rooms.session_resume import SessionResumeRepository

    engine = table.engine
    return SessionResumeService(
        session_service=SessionService(
            M04BSessionRepository(engine),
            SessionLiveRepository(engine),
            table.events,
        ),
        room_repository=RoomRepository(engine),
        campaign_service=CampaignService(CampaignRepository(engine)),
        seat_service=SeatService(M04BSeatRepository(engine)),
        character_repository=table.characters,
        summary_repository=SessionResumeRepository(engine),
        table_event_service=table.events,
        stage_service=ExplorationStageService(
            ExplorationRepository(engine), table.events
        ),
    )


def _target_check(table: TacticalTable) -> TargetCheckService:
    from app.domain.combat.attack_definitions import AttackDefinitionResolver

    return TargetCheckService(
        table_event_service=table.events,
        combat_service=table.combat,
        board_service=table.board,
        attack_definition_resolver=AttackDefinitionResolver(
            table.characters, table.combat.monster_repository, table.registry
        ),
        monster_repository=table.combat.monster_repository,
        registry=table.registry,
    )


@contextlib.contextmanager
def _rest_client_as(table: TacticalTable, actor, *, target_check=None):
    """TestClient acting as the given actor (DM or Human Player).

    Overrides the service-level dependencies directly (P5F pattern): the
    route dependencies call get_combat_service(request) as a plain function,
    which bypasses dependency_overrides for get_database_engine.
    """
    from fastapi.testclient import TestClient

    from app.api.rooms.access import get_room_access_context
    from app.api.rooms.dependencies import (
        get_combat_board_service,
        get_target_check_service,
    )
    from app.main import app

    authority = (
        RoomAccessAuthority.DM if actor.is_current_dm else RoomAccessAuthority.MEMBER
    )
    app.dependency_overrides[get_combat_board_service] = lambda: table.board
    app.dependency_overrides[get_table_event_service] = lambda: table.events
    app.dependency_overrides[get_room_access_context] = lambda: RoomAccessContext(
        room_id=table.room_id,
        access_session_id=actor.access_session_id,
        authority=authority,
    )
    if target_check is not None:
        app.dependency_overrides[get_target_check_service] = lambda: target_check
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _combat_base(table: TacticalTable) -> str:
    return (
        f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
        f"/sessions/{table.session_id}/combat"
    )


def _mcp_data(facade, token: str, name: str, arguments: dict) -> dict:
    auth = facade.ai_controller_service.authenticate(token)
    result = asyncio.run(
        call_tool(facade, token=token, auth=auth, name=name, arguments=arguments)
    )
    assert result["structuredContent"]["ok"] is True, result["structuredContent"]
    return result["structuredContent"]["data"]


def _wall_coords(board_json: dict) -> list[tuple[int, int, int, int]]:
    return [(w["x1"], w["y1"], w["x2"], w["y2"]) for w in board_json["walls"]]


def _position_ids(board_json: dict) -> set[str]:
    return {p["entry_id"] for p in board_json["positions"]}


# ---------------------------------------------------------------------------
# Surface: REST board (GET /combat/board)
# ---------------------------------------------------------------------------


def test_p5g_g6_surface_rest_board() -> None:
    fix = _secrecy_table()
    table = fix.table

    with _rest_client_as(table, table.player_actor) as client:
        res = client.get(f"{_combat_base(table)}/board")
    assert res.status_code == 200, res.text
    player_board = res.json()
    player_text = json.dumps(player_board)

    # DM truth via the service: hidden token, hidden wall, unrevealed door.
    dm_board = table.board.get_board(table.dm_actor).model_dump(mode="json")
    assert str(fix.stalker) in _position_ids(dm_board)
    assert (10, 10, 12, 10) in _wall_coords(dm_board)
    dm_door = next(d for d in dm_board["doors"] if d["door_id"] == str(fix.hidden_door_id))
    assert dm_door["state"] == "open"
    assert dm_door["revealed"] is False

    # Player sees none of it.
    assert _position_ids(player_board) == {str(fix.char_entry), str(fix.goblin)}
    assert str(fix.stalker) not in player_text
    assert str(fix.hidden_door_id) not in player_text
    assert player_board["doors"] == []
    player_walls = _wall_coords(player_board)
    assert player_walls == [(0, 0, 5, 0), (5, 0, 6, 0)]
    assert player_walls == sorted(player_walls)  # no ordering side channel
    # The projected door-wall carries no door identity or state.
    for wall in player_board["walls"]:
        assert "door_id" not in wall
        assert "state" not in wall
        assert wall.get("visibility") is None


# ---------------------------------------------------------------------------
# Surface: Session Resume (GET /sessions/active) and Player event stream
# ---------------------------------------------------------------------------


def test_p5g_g6_surface_session_resume() -> None:
    fix = _secrecy_table()
    table = fix.table
    resume_service = _resume_service(table)

    player_resume = resume_service.resume(
        table.room_id,
        table.campaign_id,
        caller_access_session_id=table.player_actor.access_session_id,
    )
    resume_text = player_resume.model_dump_json()
    assert str(fix.stalker) not in resume_text
    assert str(fix.hidden_door_id) not in resume_text
    assert '"armor_class"' not in resume_text
    assert '"current_hp"' not in resume_text
    assert '"max_hp"' not in resume_text

    # The DM resume carries the full truth.
    dm_resume = resume_service.resume(
        table.room_id,
        table.campaign_id,
        caller_access_session_id=table.dm_actor.access_session_id,
    )
    assert str(fix.stalker) in dm_resume.model_dump_json()


def test_p5g_g6_surface_player_event_stream() -> None:
    fix = _secrecy_table()
    table = fix.table

    page = table.events.list_after(table.player_actor, after_seq=0, limit=200)
    player_text = json.dumps(
        [(event.kind, event.payload) for event in page.events], default=str
    )
    assert str(fix.stalker) not in player_text
    assert str(fix.hidden_door_id) not in player_text


# ---------------------------------------------------------------------------
# Surface: MCP combat_get_board and get_session_context
# ---------------------------------------------------------------------------


def test_p5g_g6_surface_mcp_combat_get_board() -> None:
    fix = _secrecy_table()
    table = fix.table
    facade = _facade(table)

    ai_board = _mcp_data(facade, _player_token(table), "combat_get_board", {})
    ai_text = json.dumps(ai_board, default=str)
    assert str(fix.stalker) not in ai_text
    assert str(fix.hidden_door_id) not in ai_text
    assert _position_ids(ai_board) == {str(fix.char_entry), str(fix.goblin)}

    dm_board = _mcp_data(facade, _dm_token(table), "combat_get_board", {})
    assert str(fix.stalker) in json.dumps(dm_board, default=str)


def test_p5g_g6_surface_mcp_get_session_context() -> None:
    fix = _secrecy_table()
    table = fix.table
    facade = _facade(table)

    ai_context = _mcp_data(facade, _player_token(table), "get_session_context", {})
    ai_text = json.dumps(ai_context, default=str)
    assert str(fix.stalker) not in ai_text
    assert str(fix.hidden_door_id) not in ai_text

    # Enemy precise HP/AC: the player's own unit may carry stats, but the
    # public goblin's projection must not, and the stalker is absent.
    combatants = ai_context["combat"]["combat"]["combatants"]
    by_id = {c["entry_id"]: c for c in combatants}
    assert str(fix.stalker) not in by_id
    goblin_projection = by_id[str(fix.goblin)]["projection"]
    assert "armor_class" not in goblin_projection
    assert "max_hp" not in goblin_projection
    assert "current_hp" not in goblin_projection
    # The player's own character keeps its stats.
    char_projection = by_id[str(fix.char_entry)]["projection"]
    assert char_projection["armor_class"] == 18

    dm_context = _mcp_data(facade, _dm_token(table), "get_session_context", {})
    assert str(fix.stalker) in json.dumps(dm_context, default=str)


# ---------------------------------------------------------------------------
# Surface: hidden interruption response and event projection
# ---------------------------------------------------------------------------


def test_p5g_g6_surface_hidden_interruption() -> None:
    fix = _secrecy_table()
    table = fix.table
    movement = _movement(table)

    position = next(
        p
        for p in table.board.get_board(table.player_actor).positions
        if p.entry_id == fix.char_entry
    )
    board = table.board.get_board(table.player_actor)
    result = movement.confirm(
        table.player_actor,
        fix.char_entry,
        ConfirmMovementInput(
            entry_id=fix.char_entry,
            path=tuple(MovementAnchorInput(x=x, y=1) for x in (1, 2, 3, 4)),
            expected_position_revision=position.revision,
            expected_board_revision=board.runtime_revision,
            idempotency_key="g6-interrupt",
        ),
    )
    assert result.outcome == "interrupted"

    # The player-facing response carries no hidden identity or coordinates.
    response_text = json.dumps(result.model_dump(mode="json"), default=str)
    assert str(fix.stalker) not in response_text
    assert '"monster"' not in response_text

    # The DM-auditable raw event carries the full blocker truth.
    with table.engine.connect() as conn:
        row = (
            conn.execute(
                select(session_events.c.payload)
                .where(
                    session_events.c.session_id == table.session_id,
                    session_events.c.kind == "combat.movement_interrupted",
                )
                .order_by(session_events.c.seq.desc())
            )
            .mappings()
            .one()
        )
    raw_payload = dict(row["payload"])
    assert raw_payload["blocker_id"] == str(fix.stalker)
    assert raw_payload["blocker_type"] == "monster"
    assert raw_payload["step_index"] == 2

    # The player-projected event keeps only combat_id, entry_id, reason.
    page = table.events.list_after(table.player_actor, after_seq=0, limit=200)
    projected = next(
        event for event in page.events if event.kind == "combat.movement_interrupted"
    )
    assert set(projected.payload.keys()) == {"combat_id", "entry_id", "reason"}
    assert projected.payload["entry_id"] == str(fix.char_entry)


# ---------------------------------------------------------------------------
# Surface: AoE preview candidates and target check
# ---------------------------------------------------------------------------

# Origin (4,4): goblin (5,5) is 15 ft and stalker (3,1) is 15 ft away under
# the 5/10-alternating vertex distance, so both are inside the 20 ft circle;
# the char (1,1) is the caster.
G6_AOE_TEMPLATE_KWARGS = {"shape": "circle", "size_feet": 20, "origin_x": 4, "origin_y": 4}


def test_p5g_g6_surface_aoe_preview() -> None:
    fix = _secrecy_table()
    table = fix.table
    spells = _spells(table)
    template = AoeTemplateInput(**G6_AOE_TEMPLATE_KWARGS)

    def candidate_ids(actor) -> set[str]:
        preview = spells.preview_aoe(
            actor,
            PreviewAoeSpellInput(
                caster_entry_id=fix.char_entry,
                spell_ref=FIREBALL_REF,
                template=template,
            ),
        )
        return {str(c.entry_id) for c in preview.candidates}

    player_candidates = candidate_ids(table.player_actor)
    assert str(fix.stalker) not in player_candidates
    assert str(fix.goblin) in player_candidates

    dm_candidates = candidate_ids(table.dm_actor)
    assert str(fix.stalker) in dm_candidates
    assert str(fix.goblin) in dm_candidates


def test_p5g_g6_surface_target_check() -> None:
    fix = _secrecy_table()
    table = fix.table
    service = _target_check(table)

    # A player cannot target what they cannot see: not found, no leak.
    with _rest_client_as(table, table.player_actor, target_check=service) as client:
        res = client.post(
            f"{_combat_base(table)}/board/target-check",
            json={
                "source_entry_id": str(fix.char_entry),
                "target_entry_id": str(fix.stalker),
                "spell_ref": FIREBALL_REF,
            },
        )
    assert res.status_code == 404, res.text
    assert res.json()["error"]["code"] == "combat_target_not_found"
    assert str(fix.stalker) not in res.text

    # The DM can check the hidden target directly.
    dm_result = service.check_target(
        table.dm_actor,
        TargetCheckInput(
            source_entry_id=fix.char_entry,
            target_entry_id=fix.stalker,
            spell_ref=FIREBALL_REF,
        ),
    )
    assert dm_result.target_entry_id == fix.stalker


# ---------------------------------------------------------------------------
# DM truth: enemy precise HP/AC visible to the DM, never to players
# ---------------------------------------------------------------------------


def test_p5g_g6_dm_sees_enemy_hp_ac_players_do_not() -> None:
    fix = _secrecy_table()
    table = fix.table

    instance = table.combat.monster_repository.get_instance(
        next(
            e.monster_instance_id
            for e in table.combat.get_active_combat(table.dm_actor).entries
            if e.id == fix.goblin
        )
    )
    assert instance is not None
    assert instance.rules_snapshot.get("armor_class") == fix.goblin_ac
    assert instance.rules_snapshot.get("max_hp") == fix.goblin_max_hp

    with _rest_client_as(table, table.player_actor) as client:
        res = client.get(f"{_combat_base(table)}/board")
    player_text = json.dumps(res.json())
    assert '"armor_class"' not in player_text
    assert '"max_hp"' not in player_text
    assert '"current_hp"' not in player_text
