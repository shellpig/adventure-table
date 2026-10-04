"""M07-D D1: hidden-Monster event secrecy (F01), warning parity (F02), rename flag (F15).

F01: a hidden Monster's entry/instance identity must not reach Human/AI
Players through any event (REST and MCP share ``TableEventService`` read
paths). Initiative ``roll.requested`` nests per-unit ``combat_entry_ids``,
``roll.resolved`` carries the flat list, and private bookkeeping updates
carry ``combat_entry_id``/``monster_instance_id``/``name``/``visibility``.
F02: ``no_hostile_combatants`` follows caller-visible entries.
F15: DM rename flips ``name_presentation.name_is_custom`` keeping the snapshot.
"""

from __future__ import annotations

import json
from uuid import UUID

from app.domain.combat.initiative import (
    CombatInitiativeService,
    RequestInitiativeInput,
)
from app.domain.combat.monster_instances import (
    CreateQuickEnemyInput,
    MonsterInstancePatchInput,
    MonsterInstanceService,
)
from app.domain.combat.roll_compat import CombatAwareRollRepository
from app.domain.rooms.character_rolls import CharacterRollModifierResolver
from app.domain.rooms.rolls import FormalRollInput, FormalRollSource, RollService
from app.persistence.combat.initiative import CombatInitiativeRepository
from app.persistence.rooms.exploration_subjects import ExplorationSubjectRepository
from tests.p5a_tactical_helpers import TacticalTable
from tests.test_m07c_combat_load import (
    GOBLIN_KEY,
    _create_map,
    _insert_custom_template,
    _placement,
    _put_placements,
    _start,
    _table,
)
from tests.test_m07c_secrecy import _ai_player_actor


def _loaded_table() -> tuple[TacticalTable, UUID, UUID, UUID, UUID]:
    """Tactical combat with one public + one hidden monster.

    Returns ``(table, combat_id, character_entry_id, public_entry_id,
    hidden_entry_id)``. The party character is placed so initiative can be
    requested through the production Tactical gate.
    """
    from app.domain.combat.board import PlaceCombatantInput

    table, battle_maps = _table()
    map_id = _create_map(table, battle_maps)
    custom_id = _insert_custom_template(table.engine, table.room_id, name="Lurker")
    _put_placements(table, battle_maps, map_id, [
        _placement(template_key=GOBLIN_KEY, anchor=(1, 1), visibility="public", sort_order=0),
        _placement(custom_template_id=custom_id, anchor=(5, 5), visibility="hidden", sort_order=1),
    ])
    view = _start(table, map_id)
    by_visibility: dict[str, UUID] = {}
    character_entry_id: UUID | None = None
    for entry in table.combat.repository.list_entries(view.id):
        if entry.subject_kind == "character":
            character_entry_id = entry.id
        elif entry.subject_kind == "monster":
            instance = table.combat.monster_repository.get_instance(entry.monster_instance_id)
            assert instance is not None
            by_visibility[instance.visibility] = entry.id
    assert character_entry_id is not None
    table.board.place_position(
        table.dm_actor,
        character_entry_id,
        PlaceCombatantInput(anchor_x=10, anchor_y=10),
    )
    return table, view.id, character_entry_id, by_visibility["public"], by_visibility["hidden"]


def _hidden_instance_id(table: TacticalTable, hidden_entry_id: UUID) -> UUID:
    entry = table.combat.repository.get_entry(hidden_entry_id)
    assert entry is not None and entry.monster_instance_id is not None
    return entry.monster_instance_id


def _initiative_service(table: TacticalTable) -> CombatInitiativeService:
    rolls = RollService(
        CombatAwareRollRepository(table.engine, table.events.repository),
        ExplorationSubjectRepository(table.engine),
        table.events,
        CharacterRollModifierResolver(table.characters, table.registry),
    )
    return CombatInitiativeService(
        CombatInitiativeRepository(table.engine, table.events.repository),
        table.combat.repository,
        table.combat,
        table.combat.monster_repository,
        rolls,
        table.events,
    )


def _player_events_blob(table: TacticalTable, actor) -> tuple[list, str]:
    page = table.events.list_after(actor, after_seq=0, limit=500)
    blob = json.dumps([event.payload for event in page.events], default=str)
    return page.events, blob


# --- F01: initiative roll.requested ------------------------------------------------


def test_initiative_requested_hides_hidden_units_from_player() -> None:
    table, combat_id, character_id, public_id, hidden_id = _loaded_table()
    hidden_instance_id = _hidden_instance_id(table, hidden_id)
    service = _initiative_service(table)
    service.request_initiative(table.dm_actor, RequestInitiativeInput())

    events, blob = _player_events_blob(table, table.player_actor)
    requested = next(e for e in events if e.kind == "roll.requested")
    payload = requested.payload
    assert str(public_id) in blob
    assert str(hidden_id) not in blob
    assert str(hidden_instance_id) not in blob
    assert "Lurker" not in blob
    # The hidden-only unit (and its roll request) is gone: no count leak.
    assert len(payload["roll_request_ids"]) == 2
    flat = [entry for group in payload["combat_entry_ids"] for entry in group]
    assert str(character_id) in flat
    assert len(payload["combat_entry_ids"]) == 2
    # DM keeps the full truth.
    dm_events, _ = _player_events_blob(table, table.dm_actor)
    dm_requested = next(e for e in dm_events if e.kind == "roll.requested")
    assert len(dm_requested.payload["roll_request_ids"]) == 3


def test_initiative_requested_hides_hidden_units_from_ai_player() -> None:
    table, combat_id, character_id, public_id, hidden_id = _loaded_table()
    service = _initiative_service(table)
    service.request_initiative(table.dm_actor, RequestInitiativeInput())
    ai_actor = _ai_player_actor(table)
    assert not ai_actor.is_current_dm
    events, blob = _player_events_blob(table, ai_actor)
    requested = next(e for e in events if e.kind == "roll.requested")
    assert str(hidden_id) not in blob
    assert len(requested.payload["roll_request_ids"]) == 2


def test_hidden_only_initiative_request_is_withheld_from_player() -> None:
    table, combat_id, character_id, public_id, hidden_id = _loaded_table()
    service = _initiative_service(table)
    # DM requests initiative for the hidden monster alone.
    service.request_initiative(table.dm_actor, RequestInitiativeInput(entry_ids=(hidden_id,)))
    events, blob = _player_events_blob(table, table.player_actor)
    assert all(e.kind != "roll.requested" for e in events)
    assert str(hidden_id) not in blob
    # DM still sees the request.
    dm_events, _ = _player_events_blob(table, table.dm_actor)
    assert any(e.kind == "roll.requested" for e in dm_events)


# --- F01: initiative roll.resolved -------------------------------------------------


def test_initiative_resolved_for_hidden_monster_is_withheld_from_player() -> None:
    table, combat_id, character_id, public_id, hidden_id = _loaded_table()
    service = _initiative_service(table)
    response = service.request_initiative(table.dm_actor, RequestInitiativeInput())
    hidden_request = next(
        request for request in response.requests
        if hidden_id in request.grouped_entry_ids
    )
    service.complete_initiative(
        table.dm_actor,
        FormalRollInput(roll_request_id=hidden_request.id, source=FormalRollSource.SERVER),
    )
    events, blob = _player_events_blob(table, table.player_actor)
    assert str(hidden_id) not in blob
    assert all(
        not (e.kind == "roll.resolved" and str(hidden_id) in json.dumps(e.payload, default=str))
        for e in events
    )
    dm_events, dm_blob = _player_events_blob(table, table.dm_actor)
    assert str(hidden_id) in dm_blob
    assert any(e.kind == "roll.resolved" for e in dm_events)


def test_initiative_resolved_for_visible_monster_stays_visible() -> None:
    table, combat_id, character_id, public_id, hidden_id = _loaded_table()
    service = _initiative_service(table)
    response = service.request_initiative(table.dm_actor, RequestInitiativeInput())
    public_request = next(
        request for request in response.requests
        if public_id in request.grouped_entry_ids
    )
    result = service.complete_initiative(
        table.dm_actor,
        FormalRollInput(roll_request_id=public_request.id, source=FormalRollSource.SERVER),
    )
    assert public_id in result.combat_entry_ids
    events, blob = _player_events_blob(table, table.player_actor)
    resolved = [e for e in events if e.kind == "roll.resolved"]
    assert resolved
    assert str(public_id) in json.dumps(resolved[0].payload, default=str)


# --- F01: private bookkeeping updates ----------------------------------------------


def test_hidden_bookkeeping_update_is_withheld_from_player_and_ai() -> None:
    table, combat_id, character_id, public_id, hidden_id = _loaded_table()
    hidden_instance_id = _hidden_instance_id(table, hidden_id)
    instances = MonsterInstanceService(
        monster_repository=table.combat.monster_repository,
        content_registry=table.registry,
        table_event_service=table.events,
    )
    instances.update_instance(
        table.dm_actor,
        hidden_instance_id,
        MonsterInstancePatchInput(position_note="lurking behind the pillar"),
    )
    # NOTE: the AI handoff below revokes the Human player's control, so the
    # Human read must happen first.
    events, blob = _player_events_blob(table, table.player_actor)
    assert str(hidden_instance_id) not in blob
    assert str(hidden_id) not in blob
    assert "lurking behind the pillar" not in blob
    assert all(e.kind != "combat.monster_instance_updated" for e in events)
    ai_events, ai_blob = _player_events_blob(table, _ai_player_actor(table))
    assert str(hidden_instance_id) not in ai_blob
    assert str(hidden_id) not in ai_blob
    assert "lurking behind the pillar" not in ai_blob
    assert all(e.kind != "combat.monster_instance_updated" for e in ai_events)
    # DM sees the bookkeeping event with full identity.
    dm_events, _ = _player_events_blob(table, table.dm_actor)
    updates = [e for e in dm_events if e.kind == "combat.monster_instance_updated"]
    assert updates
    assert updates[-1].payload["monster_instance_id"] == str(hidden_instance_id)


def test_public_bookkeeping_update_stays_visible_to_player() -> None:
    table, combat_id, character_id, public_id, hidden_id = _loaded_table()
    public_instance_id = _hidden_instance_id(table, public_id)
    instances = MonsterInstanceService(
        monster_repository=table.combat.monster_repository,
        content_registry=table.registry,
        table_event_service=table.events,
    )
    instances.update_instance(
        table.dm_actor,
        public_instance_id,
        MonsterInstancePatchInput(position_note="snarling in the open"),
    )
    events, blob = _player_events_blob(table, table.player_actor)
    updates = [e for e in events if e.kind == "combat.monster_instance_updated"]
    assert updates
    assert str(public_instance_id) in blob


def test_hidden_mid_combat_add_is_withheld_from_player() -> None:
    table, combat_id, character_id, public_id, hidden_id = _loaded_table()
    instances = MonsterInstanceService(
        monster_repository=table.combat.monster_repository,
        content_registry=table.registry,
        table_event_service=table.events,
    )
    lurker = instances.create_quick_enemy(
        table.dm_actor,
        CreateQuickEnemyInput(name="Sneak", armor_class=12, max_hp=9, visibility="hidden"),
    )
    from app.domain.combat.lifecycle import AddMonsterInput

    table.combat.add_monster(
        table.dm_actor, AddMonsterInput(monster_instance_id=lurker.id)
    )
    events, blob = _player_events_blob(table, table.player_actor)
    assert "Sneak" not in blob
    assert str(lurker.id) not in blob
    assert all(e.kind != "combat.entry_added" or "Sneak" not in json.dumps(e.payload, default=str) for e in events)
    dm_events, dm_blob = _player_events_blob(table, table.dm_actor)
    assert "Sneak" in dm_blob


# --- F01: Quick Combat hidden path (P4-B route) -------------------------------------


def test_quick_combat_hidden_initiative_stays_hidden_from_player() -> None:
    table, _battle_maps = _table()
    instances = MonsterInstanceService(
        monster_repository=table.combat.monster_repository,
        content_registry=table.registry,
        table_event_service=table.events,
    )
    from app.domain.combat.lifecycle import AddMonsterInput, StartCombatInput

    table.combat.start_quick_combat(
        table.dm_actor, StartCombatInput(include_active_party=True)
    )
    lurker = instances.create_quick_enemy(
        table.dm_actor,
        CreateQuickEnemyInput(name="QuickLurk", armor_class=12, max_hp=9, visibility="hidden"),
    )
    started = table.combat.add_monster(
        table.dm_actor, AddMonsterInput(monster_instance_id=lurker.id)
    )
    hidden_entry_id = next(e.id for e in started.entries if e.monster_instance_id == lurker.id)
    service = _initiative_service(table)
    service.request_initiative(table.dm_actor, RequestInitiativeInput())
    events, blob = _player_events_blob(table, table.player_actor)
    assert str(hidden_entry_id) not in blob
    assert str(lurker.id) not in blob
    assert "QuickLurk" not in blob


# --- F02: warning parity -------------------------------------------------------------


def test_no_hostile_warning_matches_caller_visibility() -> None:
    table, combat_id, character_id, public_id, hidden_id = _loaded_table()
    # Only-hidden-hostiles state is tested by hiding the public monster too.
    instances = MonsterInstanceService(
        monster_repository=table.combat.monster_repository,
        content_registry=table.registry,
        table_event_service=table.events,
    )
    public_instance_id = _hidden_instance_id(table, public_id)
    instances.update_instance(
        table.dm_actor,
        public_instance_id,
        MonsterInstancePatchInput(visibility="hidden"),
    )
    player_view = table.combat.get_active_combat(table.player_actor)
    assert player_view is not None
    # Player sees no hostiles at all: same warning as an empty battlefield.
    assert player_view.warnings == ("no_hostile_combatants",)
    ai_view = table.combat.get_active_combat(_ai_player_actor(table))
    assert ai_view is not None
    assert ai_view.warnings == ("no_hostile_combatants",)
    # DM follows the true state: hostiles exist, no warning.
    dm_view = table.combat.get_active_combat(table.dm_actor)
    assert dm_view is not None
    assert dm_view.warnings == ()


def test_warning_present_for_all_when_no_monsters() -> None:
    table, battle_maps = _table()
    map_id = _create_map(table, battle_maps)
    view = _start(table, map_id)
    assert view is not None
    for actor in (table.dm_actor, table.player_actor):
        seen = table.combat.get_active_combat(actor)
        assert seen is not None
        assert seen.warnings == ("no_hostile_combatants",)


# --- F15: rename flag -----------------------------------------------------------------


def test_dm_rename_sets_name_is_custom_keeping_names_snapshot() -> None:
    table, battle_maps = _table()
    map_id = _create_map(table, battle_maps)
    _put_placements(table, battle_maps, map_id, [
        _placement(template_key=GOBLIN_KEY, anchor=(1, 1), visibility="public", sort_order=0),
    ])
    view = _start(table, map_id)
    entry = next(e for e in table.combat.repository.list_entries(view.id) if e.subject_kind == "monster")
    assert entry.monster_instance_id is not None
    instances = MonsterInstanceService(
        monster_repository=table.combat.monster_repository,
        content_registry=table.registry,
        table_event_service=table.events,
    )
    renamed = instances.update_instance(
        table.dm_actor,
        entry.monster_instance_id,
        MonsterInstancePatchInput(name="Gobby the Renamed"),
    )
    assert renamed.name == "Gobby the Renamed"
    detail = table.combat.get_active_combat_detail(table.dm_actor)
    assert detail is not None
    combatant = next(c for c in detail.combatants if c.entry_id == entry.id)
    presentation = combatant.projection["name_presentation"]
    assert presentation["name_is_custom"] is True
    # The original locale names snapshot is kept for history.
    assert presentation["names"]["en"] == "Goblin"
    # The entry display name follows the rename.
    assert combatant.projection["name"] == "Gobby the Renamed"
    player_detail = table.combat.get_active_combat_detail(table.player_actor)
    assert player_detail is not None
    player_combatant = next(c for c in player_detail.combatants if c.entry_id == entry.id)
    assert player_combatant.projection["name_presentation"]["name_is_custom"] is True
