"""M07-C C3: Human/AI Player secrecy for map-loaded monsters.

All secrecy assertions run through the production ``hidden_combat_entry_ids``
wiring (mirrored by ``wire_tactical_services``): no mocked hidden-id sets.
"""

from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import select, update

from app.domain.combat.initiative import CombatInitiativeService
from app.domain.rooms.ai_controllers import AIControllerService, AIHandoffRequest
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.persistence.combat.tables import combat_entries, monster_instances
from app.persistence.rooms.ai_controllers import AIControllerGrantRepository
from tests.p5a_tactical_helpers import TacticalTable
from tests.test_m07c_combat_load import (
    GOBLIN_KEY,
    _create_map,
    _dm_context,
    _insert_custom_template,
    _placement,
    _put_placements,
    _start,
    _table,
)


def _loaded_table() -> tuple[TacticalTable, UUID, UUID, UUID]:
    """Start a tactical combat loading one public and one hidden monster.

    Returns ``(table, combat_id, public_entry_id, hidden_entry_id)``.
    """
    table, battle_maps = _table()
    map_id = _create_map(table, battle_maps)
    custom_id = _insert_custom_template(table.engine, table.room_id, name="Lurker")
    _put_placements(table, battle_maps, map_id, [
        _placement(template_key=GOBLIN_KEY, anchor=(1, 1), visibility="public", sort_order=0),
        _placement(custom_template_id=custom_id, anchor=(5, 5), visibility="hidden", sort_order=1),
    ])
    view = _start(table, map_id)
    by_visibility: dict[str, UUID] = {}
    with table.engine.connect() as connection:
        rows = connection.execute(
            select(combat_entries.c.id, monster_instances.c.visibility)
            .join(
                monster_instances,
                monster_instances.c.id == combat_entries.c.monster_instance_id,
            )
            .where(
                combat_entries.c.combat_id == view.id,
                combat_entries.c.subject_kind == "monster",
            )
        ).mappings().all()
    for row in rows:
        by_visibility[row["visibility"]] = row["id"]
    return table, view.id, by_visibility["public"], by_visibility["hidden"]


def _player_view(table: TacticalTable):
    view = table.combat.get_active_combat(table.player_actor)
    assert view is not None
    return view


def _ai_player_actor(table: TacticalTable):
    service = AIControllerService(AIControllerGrantRepository(table.engine), table.events)
    grant = service.let_ai_control_player(
        room_id=table.room_id, campaign_id=table.campaign_id, session_id=table.session_id,
        seat_id=table.player_actor.seat_id,
        context=RoomAccessContext(
            room_id=table.room_id,
            access_session_id=table.player_actor.access_session_id,
            authority=RoomAccessAuthority.MEMBER,
        ),
        request=AIHandoffRequest(),
    )
    return table.events.resolve_ai_actor(
        room_id=table.room_id, campaign_id=table.campaign_id, session_id=table.session_id,
        grant_id=grant.grant_id, generation=grant.generation,
    )


# --- C.3 views -----------------------------------------------------------------


def test_player_view_hides_hidden_and_densifies_turn_ordinals() -> None:
    table, combat_id, public_entry_id, hidden_entry_id = _loaded_table()
    view = _player_view(table)
    entry_ids = {e.id for e in view.entries}
    assert public_entry_id in entry_ids
    assert hidden_entry_id not in entry_ids
    # Turn ordinals are dense: no gap betrays the hidden combatant.
    ordinals = sorted(e.turn_order for e in view.entries if e.turn_order is not None)
    assert ordinals == list(range(len(ordinals)))
    # The DM still sees everything.
    dm_view = table.combat.get_active_combat(table.dm_actor)
    assert dm_view is not None
    assert {e.id for e in dm_view.entries} >= {public_entry_id, hidden_entry_id}


def test_player_board_hides_hidden_positions() -> None:
    table, combat_id, public_entry_id, hidden_entry_id = _loaded_table()
    board = table.board.get_board(table.player_actor)
    entry_ids = {p.entry_id for p in board.positions}
    assert public_entry_id in entry_ids
    assert hidden_entry_id not in entry_ids
    dm_board = table.board.get_board(table.dm_actor)
    assert {p.entry_id for p in dm_board.positions} >= {public_entry_id, hidden_entry_id}


def test_player_detail_omits_hidden_and_carries_name_presentation() -> None:
    table, combat_id, public_entry_id, hidden_entry_id = _loaded_table()
    detail = table.combat.get_active_combat_detail(table.player_actor)
    assert detail is not None
    assert hidden_entry_id not in {c.entry_id for c in detail.combatants}
    assert public_entry_id in {c.entry_id for c in detail.combatants}
    payload = json.dumps(detail.model_dump(), default=str)
    # No rules snapshot leaks through the player detail.
    assert "rules_snapshot" not in payload
    # The visible monster carries the name presentation subset but no stats.
    monster = next(c for c in detail.combatants if c.entry_id == public_entry_id)
    assert monster.projection["name_presentation"]["names"]["en"] == "Goblin"
    assert monster.projection["name_presentation"]["name_is_custom"] is False
    monster_blob = json.dumps(monster.projection, default=str)
    assert "armor_class" not in monster_blob
    assert "max_hp" not in monster_blob


def test_dm_detail_sees_hidden_with_full_snapshot() -> None:
    table, combat_id, public_entry_id, hidden_entry_id = _loaded_table()
    detail = table.combat.get_active_combat_detail(table.dm_actor)
    assert detail is not None
    assert {c.entry_id for c in detail.combatants} >= {public_entry_id, hidden_entry_id}
    hidden = next(c for c in detail.combatants if c.entry_id == hidden_entry_id)
    assert hidden.projection["visibility"] == "hidden"
    assert hidden.projection["name_presentation"]["names"] == {"en": "Lurker"}


def test_ai_player_sees_same_projection_as_human_player() -> None:
    table, combat_id, public_entry_id, hidden_entry_id = _loaded_table()
    ai_actor = _ai_player_actor(table)
    assert not ai_actor.is_current_dm
    view = table.combat.get_active_combat(ai_actor)
    assert view is not None
    entry_ids = {e.id for e in view.entries}
    assert public_entry_id in entry_ids
    assert hidden_entry_id not in entry_ids
    board = table.board.get_board(ai_actor)
    assert hidden_entry_id not in {p.entry_id for p in board.positions}


# --- C.3 initiative --------------------------------------------------------------


def _set_initiative_totals(table: TacticalTable, combat_id: UUID, totals: dict[UUID, int]) -> None:
    with table.engine.begin() as connection:
        for entry_id, total in totals.items():
            connection.execute(
                update(combat_entries)
                .where(combat_entries.c.id == entry_id)
                .values(initiative_total=total)
            )


def _initiative_service(table: TacticalTable) -> CombatInitiativeService:
    from app.persistence.combat.initiative import CombatInitiativeRepository

    return CombatInitiativeService(
        CombatInitiativeRepository(table.engine, table.events.repository),
        table.combat.repository,
        table.combat,
        table.combat.monster_repository,
        None,  # roll_service: not needed for suggested_order/tied_totals reads
        table.events,
    )


def test_player_suggested_order_excludes_hidden() -> None:
    table, combat_id, public_entry_id, hidden_entry_id = _loaded_table()
    view = table.combat.get_active_combat(table.dm_actor)
    assert view is not None
    character_entry_id = next(e.id for e in view.entries if e.subject_kind == "character")
    _set_initiative_totals(table, combat_id, {
        character_entry_id: 15, public_entry_id: 12, hidden_entry_id: 20,
    })
    service = _initiative_service(table)
    player_order = service.suggested_order(table.player_actor)
    assert hidden_entry_id not in player_order
    assert set(player_order) == {character_entry_id, public_entry_id}
    # The hidden monster would have sorted first; the player order shows no gap.
    assert player_order[0] == character_entry_id
    dm_order = service.suggested_order(table.dm_actor)
    assert dm_order[0] == hidden_entry_id


def test_player_tied_totals_exclude_hidden() -> None:
    table, combat_id, public_entry_id, hidden_entry_id = _loaded_table()
    view = table.combat.get_active_combat(table.dm_actor)
    assert view is not None
    character_entry_id = next(e.id for e in view.entries if e.subject_kind == "character")
    _set_initiative_totals(table, combat_id, {
        character_entry_id: 10, public_entry_id: 10, hidden_entry_id: 10,
    })
    # Distinct roll request ids so the tie is reported.
    with table.engine.begin() as connection:
        for entry_id, request_id in (
            (character_entry_id, UUID(int=1)),
            (public_entry_id, UUID(int=2)),
            (hidden_entry_id, UUID(int=3)),
        ):
            connection.execute(
                update(combat_entries)
                .where(combat_entries.c.id == entry_id)
                .values(initiative_roll_request_id=request_id)
            )
    service = _initiative_service(table)
    player_ties = service.tied_totals(table.player_actor)
    assert player_ties[10] is not None
    assert hidden_entry_id not in player_ties[10]
    assert set(player_ties[10]) == {character_entry_id, public_entry_id}
    dm_ties = service.tied_totals(table.dm_actor)
    assert set(dm_ties[10]) == {character_entry_id, public_entry_id, hidden_entry_id}


# --- C.3 events ------------------------------------------------------------------


def test_combat_started_event_redacts_hidden_for_player() -> None:
    table, combat_id, public_entry_id, hidden_entry_id = _loaded_table()
    page = table.events.list_after(table.player_actor, after_seq=0, limit=200)
    started = next(e for e in page.events if e.kind == "combat.started")
    payload = started.payload
    assert str(public_entry_id) in payload["entry_ids"]
    assert str(hidden_entry_id) not in payload["entry_ids"]
    blob = json.dumps(payload, default=str)
    assert "Lurker" not in blob
    # DM gets the full truth.
    dm_page = table.events.list_after(table.dm_actor, after_seq=0, limit=200)
    dm_started = next(e for e in dm_page.events if e.kind == "combat.started")
    assert str(hidden_entry_id) in dm_started.payload["entry_ids"]


def test_reveal_exposes_loaded_monster_to_player() -> None:
    from app.domain.combat.monster_instances import (
        MonsterInstancePatchInput,
        MonsterInstanceService,
    )

    table, combat_id, public_entry_id, hidden_entry_id = _loaded_table()
    assert hidden_entry_id not in {e.id for e in _player_view(table).entries}
    # DM reveals the hidden monster via the instance visibility update.
    with table.engine.connect() as connection:
        row = connection.execute(
            select(combat_entries.c.monster_instance_id).where(
                combat_entries.c.id == hidden_entry_id
            )
        ).mappings().one()
    service = MonsterInstanceService(
        monster_repository=table.combat.monster_repository,
        content_registry=table.registry,
        table_event_service=table.events,
    )
    service.update_instance(
        table.dm_actor,
        row["monster_instance_id"],
        MonsterInstancePatchInput(visibility="public"),
    )
    assert hidden_entry_id in {e.id for e in _player_view(table).entries}
    board = table.board.get_board(table.player_actor)
    assert hidden_entry_id in {p.entry_id for p in board.positions}
