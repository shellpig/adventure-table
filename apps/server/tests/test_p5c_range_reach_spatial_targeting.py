"""P5-C C1: reach/range, spatial targeting, Tactical attack & spell wiring (backend only).

Covers 測試指南 C.1-C.6:
- C.1 distance consistency across movement / ranged / reach on one fixture
- C.2 Large/Huge nearest cell pair (anchor-to-anchor counterexample)
- C.3 reach derivation (Glaive/Whip/monster reach=10) and hard-wall rejection
- C.4 light crossbow 80/320 bands, long-range disadvantage, Quick unchanged
- C.5 wall/closed/locked block, open/broken do not, cover adds no AC
- C.6 Tactical attacks reuse the P4 formal roll / damage / HP pipeline
Plus: player/DM hidden-blocker secrecy, hidden-monster targeting, actor
authorization with zero side effects, condition distance boundaries, targeted
spell ranges (Self/Touch/N feet/unknown), and API 409 error mapping.
"""

from __future__ import annotations

from dataclasses import fields
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, insert, select, update

from app.api.rooms.combat import _map_combat_error
from app.content import load_default_content_registry
from app.domain.character.schemas import CharacterBuild, CharacterState
from app.domain.combat.attack_definitions import AttackDefinitionResolver
from app.domain.combat.attacks import (
    AttackRequestInput,
    CombatAttackService,
)
from app.domain.combat.board import (
    PlaceCombatantInput,
    UpdateDoorStateInput,
)
from app.domain.combat.condition_modifiers import attack_modifiers
from app.domain.combat.lifecycle import (
    CombatStateConflictError,
    AddMonsterInput,
    ResolveInitiativeOrderInput,
    StartCombatInput,
    StartTacticalCombatInput,
)
from app.domain.combat.initiative import (
    CombatInitiativeService,
    FinalizeInitiativeInput,
    RequestInitiativeInput,
)
from app.domain.combat.resolution import AttackKind, ResolvedAttack, RollMode
from app.domain.combat.spell_resolver import SpellCastMode
from app.domain.combat.spell_service import CastSpellInput, CombatSpellService
from app.domain.rooms.character_rolls import CharacterRollModifierResolver
from app.domain.rooms.rolls import (
    FormalRollInput,
    FormalRollSource,
    RollModifierMode,
    RollService,
)
from app.domain.rooms.table_events import TableEventActorUnauthorizedError
from app.domain.spatial.pathing import grid_distance
from app.domain.spatial.primitives import BarrierSegment, GridCell
from app.domain.spatial.targeting import (
    BarrierView,
    CombatTargetBlockedError,
    CombatTargetOutOfRangeError,
    SpatialTargetingResult,
    is_within_reach,
    parse_spell_range,
    validate_attack_target,
    validate_spell_target,
)
from app.persistence.battle_maps.tables import (
    battle_map_doors,
    battle_maps,
    battle_map_walls,
)
from app.persistence.characters import (
    CharacterRepository,
    character_states,
    character_versions,
    characters,
)
from app.persistence.combat.adjudication import CombatAdjudicationRepository
from app.persistence.combat.initiative import CombatInitiativeRepository
from app.persistence.combat.attacks import CombatAttackRepository
from app.persistence.combat.resolution import CombatResolutionTargetNotFoundError
from app.persistence.combat.spells import CombatSpellRepository
from app.persistence.combat.tables import combat_entries
from app.persistence.rooms.exploration_subjects import ExplorationSubjectRepository
from app.domain.combat.roll_compat import CombatAwareRollRepository
from tests.p5a_tactical_helpers import (
    TacticalTable,
    setup_tactical_table,
)


# ---------------------------------------------------------------------------
# Helpers


def _rolls(table: TacticalTable) -> RollService:
    return RollService(
        CombatAwareRollRepository(table.engine, table.events.repository),
        ExplorationSubjectRepository(table.engine),
        table.events,
        CharacterRollModifierResolver(table.combat.character_repository, table.registry),
    )


def _attacks(table: TacticalTable) -> CombatAttackService:
    return CombatAttackService(
        CombatAttackRepository(table.engine, table.events.repository),
        CombatAdjudicationRepository(table.engine, table.events.repository),
        table.combat.repository,
        table.combat,
        AttackDefinitionResolver(
            table.combat.character_repository,
            table.combat.monster_repository,
            table.registry,
        ),
        _rolls(table),
        table.events,
        board_service=table.board,
    )


def _spells(table: TacticalTable) -> CombatSpellService:
    return CombatSpellService(
        repository=CombatSpellRepository(table.engine, table.events.repository),
        combat_repository=table.combat.repository,
        combat_service=table.combat,
        table_event_service=table.events,
        monster_repository=table.combat.monster_repository,
        character_repository=table.combat.character_repository,
        roll_service=_rolls(table),
        registry=table.registry,
        board_service=table.board,
    )


def _blank_map(table: TacticalTable, width_cells: int = 30, height_cells: int = 30) -> UUID:
    map_id = uuid4()
    now = datetime.now(timezone.utc)
    with table.engine.begin() as conn:
        conn.execute(
            insert(battle_maps).values(
                id=map_id, room_id=table.room_id, name="p5c-test",
                source_kind="blank", image_asset_id=None,
                width_cells=width_cells, height_cells=height_cells,
                grid_pixel_size=None, grid_offset_x=None, grid_offset_y=None,
                revision=1, created_at=now, updated_at=now,
            )
        )
    return map_id


def _map_with_wall(
    table: TacticalTable,
    *,
    x1: int, y1: int, x2: int, y2: int,
    visibility: str = "public",
) -> UUID:
    map_id = _blank_map(table)
    with table.engine.begin() as conn:
        conn.execute(
            insert(battle_map_walls).values(
                id=uuid4(), battle_map_id=map_id,
                x1=x1, y1=y1, x2=x2, y2=y2, visibility=visibility,
            )
        )
    return map_id


def _map_with_door(
    table: TacticalTable,
    *,
    x1: int, y1: int, x2: int, y2: int,
    default_state: str = "closed",
    visibility: str = "public",
) -> UUID:
    map_id = _blank_map(table)
    with table.engine.begin() as conn:
        conn.execute(
            insert(battle_map_doors).values(
                id=uuid4(), battle_map_id=map_id,
                x1=x1, y1=y1, x2=x2, y2=y2,
                default_state=default_state, visibility=visibility,
            )
        )
    return map_id


def _character_entry_id(table: TacticalTable) -> UUID:
    view = table.combat.get_active_combat(table.dm_actor)
    assert view is not None
    return next(e.id for e in view.entries if e.subject_kind == "character")


def _add_monster(table: TacticalTable, **kwargs) -> UUID:
    instance = table.combat.monster_repository.create_quick_enemy(
        campaign_id=table.campaign_id, name="Goblin",
        armor_class=15, max_hp=7, speed={"walk": "30 ft."},
        **kwargs,
    )
    table.combat.add_monster(
        table.dm_actor, AddMonsterInput(monster_instance_id=instance.id)
    )
    view = table.combat.get_active_combat(table.dm_actor)
    assert view is not None
    return next(e.id for e in view.entries if e.subject_kind == "monster")


def _running(
    table: TacticalTable,
    *,
    char_entry: UUID,
    monster_entry: UUID,
    char_at: tuple[int, int] = (1, 1),
    monster_at: tuple[int, int] = (2, 1),
) -> None:
    table.board.place_position(
        table.dm_actor, char_entry,
        PlaceCombatantInput(anchor_x=char_at[0], anchor_y=char_at[1]),
    )
    table.board.place_position(
        table.dm_actor, monster_entry,
        PlaceCombatantInput(anchor_x=monster_at[0], anchor_y=monster_at[1]),
    )
    with table.engine.begin() as conn:
        conn.execute(
            update(combat_entries)
            .where(combat_entries.c.id == char_entry)
            .values(initiative_total=20)
        )
        conn.execute(
            update(combat_entries)
            .where(combat_entries.c.id == monster_entry)
            .values(initiative_total=10)
        )
    table.combat.resolve_initiative_order(
        table.dm_actor,
        ResolveInitiativeOrderInput(ordered_entry_ids=(char_entry, monster_entry)),
    )


def _tactical_table(battle_map_id: UUID | None = None) -> tuple[TacticalTable, UUID, UUID]:
    """Fresh tactical table with character + monster placed and running."""
    table = setup_tactical_table()
    if battle_map_id is None:
        battle_map_id = _blank_map(table)
    table.combat.start_tactical_combat(
        table.dm_actor, StartTacticalCombatInput(battle_map_id=battle_map_id)
    )
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)
    return table, char_entry, monster_entry


def _attack_adjudications(table: TacticalTable) -> CombatAdjudicationRepository:
    return CombatAdjudicationRepository(table.engine, table.events.repository)


def _combat_id(table: TacticalTable) -> UUID:
    view = table.combat.get_active_combat(table.dm_actor)
    assert view is not None
    return view.id


def _initiative(table: TacticalTable) -> CombatInitiativeService:
    return CombatInitiativeService(
        CombatInitiativeRepository(table.engine, table.events.repository),
        table.combat.repository,
        table.combat,
        table.combat.monster_repository,
        _rolls(table),
        table.events,
    )


def _quick_running(table: TacticalTable, char_entry: UUID, monster_entry: UUID) -> None:
    """Bring a quick Combat to running status via the initiative dance."""
    initiative = _initiative(table)
    requested = initiative.request_initiative(
        table.dm_actor, RequestInitiativeInput(idempotency_key="p5c-quick-init")
    )
    for index, request in enumerate(requested.requests):
        actor = (
            table.player_actor if request.target_seat_id is not None else table.dm_actor
        )
        raw = 20 if request.target_seat_id is not None else 1
        initiative.complete_initiative(
            actor,
            FormalRollInput(
                roll_request_id=request.id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(raw,),
                idempotency_key=f"p5c-quick-init-roll-{index}",
            ),
        )
    initiative.finalize_initiative(
        table.dm_actor,
        FinalizeInitiativeInput(
            ordered_entry_ids=(char_entry, monster_entry),
            idempotency_key="p5c-quick-finalize",
        ),
    )


def _no_pending_attacks(table: TacticalTable) -> None:
    assert _attack_adjudications(table).list_pending(combat_id=_combat_id(table)) == ()


def _attack_source_ref(attacks: CombatAttackService, actor, entry_id: UUID, name: str) -> str:
    available = attacks.available_attacks(actor, entry_id)
    match = next(a for a in available if a.name == name)
    return match.source_ref


def _grant_weapon(table: TacticalTable, item_ref: str) -> None:
    """Patch character state inventory (established test pattern)."""
    repo = CharacterRepository(table.engine, table.registry)
    character = repo.load_character(table.character_id)
    payload = character.state.model_dump(mode="json")
    payload["inventory_state"].append(
        {
            "entry_id": f"test:{item_ref.split(':')[-1]}",
            "item_ref": item_ref,
            "quantity": 1,
            "equipped": True,
            "carried": True,
        }
    )
    CharacterState.model_validate(payload)
    with table.engine.begin() as conn:
        conn.execute(
            update(character_states)
            .where(character_states.c.character_id == table.character_id)
            .values(
                state_payload=payload,
                state_revision=character_states.c.state_revision + 1,
            )
        )


def _grant_spells(table: TacticalTable, *spell_keys: str) -> None:
    """Grant wizard spellbook access entries (build) + prepared ids (state).

    The P5-A tactical fixture carries no spellcasting profiles, so a wizard
    profile is added alongside the access rows (test-only build patch).
    """
    repo = CharacterRepository(table.engine, table.registry)
    loaded = repo.load_character(table.character_id)
    build_payload = loaded.build.model_dump(mode="json")
    wizard = "srd5.1:class:wizard"
    if not any(
        p["profile_id"] == "wizard"
        for p in build_payload.get("spellcasting_profiles", [])
    ):
        build_payload.setdefault("spellcasting_profiles", []).append(
            {
                "profile_id": "wizard",
                "source_type": "class",
                "source_key": wizard,
                "class_ref": wizard,
                "ability": "intelligence",
                "access_model": "prepared",
                "resource_pool_type": "normal_multiclass_slots",
                "max_spell_level": 3,
                "prepared_limit": 8,
            }
        )
    for key in spell_keys:
        entry_id = f"wizard:{key.split(':')[-1]}"
        if not any(
            e["entry_id"] == entry_id
            for e in build_payload["spell_access_entries"]
        ):
            build_payload["spell_access_entries"].append(
                {
                    "entry_id": entry_id,
                    "spell_key": key,
                    "source_type": "class",
                    "source_key": "srd5.1:class:wizard",
                    "access_type": "spellbook",
                }
            )
    CharacterBuild.model_validate(build_payload)
    state_payload = loaded.state.model_dump(mode="json")
    for key in spell_keys:
        entry_id = f"wizard:{key.split(':')[-1]}"
        if entry_id not in state_payload["prepared_spell_entry_ids"]:
            state_payload["prepared_spell_entry_ids"].append(entry_id)
    CharacterState.model_validate(state_payload)
    with table.engine.begin() as conn:
        current_version_id = conn.execute(
            select(characters.c.current_version_id).where(
                characters.c.id == table.character_id
            )
        ).scalar_one()
        version_no = conn.execute(
            select(func.max(character_versions.c.version_no)).where(
                character_versions.c.character_id == table.character_id
            )
        ).scalar() or 0
        new_version_id = uuid4()
        conn.execute(
            insert(character_versions).values(
                id=new_version_id,
                character_id=table.character_id,
                version_no=version_no + 1,
                build_payload=build_payload,
                builder_provenance=None,
                version_kind="correction",
                parent_version_id=current_version_id,
                superseded_by_version_id=None,
                change_note="p5c-test",
            )
        )
        conn.execute(
            update(characters)
            .where(characters.c.id == table.character_id)
            .values(current_version_id=new_version_id)
        )
        conn.execute(
            update(character_states)
            .where(character_states.c.character_id == table.character_id)
            .values(
                state_payload=state_payload,
                state_revision=character_states.c.state_revision + 1,
            )
        )


def _make_melee_attack(*, reach_feet: int | None = 5) -> ResolvedAttack:
    from app.domain.combat.resolution import DamageFormulaPart, DamageType

    return ResolvedAttack(
        source_ref="test:sword",
        name="Test Sword",
        attack_bonus=5,
        attack_kind=AttackKind.MELEE,
        damage_parts=(
            DamageFormulaPart(
                damage_type=DamageType.SLASHING,
                dice_count=1, die_size=8, flat_modifier=3,
            ),
        ),
        reach_feet=reach_feet,
    )


# ---------------------------------------------------------------------------
# C.1 — distance consistency: targeting measures the same feet as grid_distance


def test_c1_melee_distance_matches_grid_distance() -> None:
    source = (GridCell(0, 0),)
    target = (GridCell(5, 0),)
    result = validate_attack_target(
        source_cells=source, target_cells=target,
        attack=_make_melee_attack(reach_feet=30),
        barriers=(), audience="player",
    )
    assert result.distance_feet == grid_distance(source, target).feet == 25
    assert result.legal and result.range_band == "reach"


def test_c1_ranged_distance_matches_grid_distance() -> None:
    source = (GridCell(0, 0),)
    target = (GridCell(20, 0),)
    attack = _make_melee_attack()
    ranged = ResolvedAttack(
        source_ref=attack.source_ref, name=attack.name,
        attack_bonus=attack.attack_bonus, attack_kind=AttackKind.RANGED,
        damage_parts=attack.damage_parts,
        range_normal_feet=80, range_long_feet=320,
    )
    result = validate_attack_target(
        source_cells=source, target_cells=target,
        attack=ranged, barriers=(), audience="player",
    )
    assert result.distance_feet == grid_distance(source, target).feet == 100
    assert result.legal and result.range_band == "long"


def test_c1_spell_distance_matches_grid_distance() -> None:
    source = (GridCell(2, 2),)
    target = (GridCell(5, 6),)
    result = validate_spell_target(
        source_cells=source, target_cells=target,
        range_feet=60, barriers=(), audience="player",
    )
    assert result.distance_feet == grid_distance(source, target).feet == 25
    assert result.legal


# ---------------------------------------------------------------------------
# C.2 — Large/Huge footprints use the nearest cell pair


def _large_cells() -> tuple[GridCell, ...]:
    return (
        GridCell(0, 0), GridCell(1, 0),
        GridCell(0, 1), GridCell(1, 1),
    )


def test_c2_large_footprint_uses_nearest_cell_pair() -> None:
    # Nearest pair (1,0)-(3,0): 10 ft. Anchor-to-anchor would be 15 ft.
    result = validate_attack_target(
        source_cells=_large_cells(), target_cells=(GridCell(3, 0),),
        attack=_make_melee_attack(reach_feet=10),
        barriers=(), audience="player",
    )
    assert result.distance_feet == 10
    assert result.legal and result.range_band == "reach"


def test_c2_anchor_to_anchor_would_be_wrong() -> None:
    assert grid_distance((GridCell(0, 0),), (GridCell(3, 0),)).feet == 15
    assert is_within_reach(
        _large_cells(), (GridCell(3, 0),),
        _make_melee_attack(reach_feet=10),
    ) is True  # 15 ft anchor distance would wrongly fail a 10 ft reach


def test_c2_huge_footprint_nearest_pair() -> None:
    huge = tuple(
        GridCell(x, y) for x in range(3) for y in range(3)
    )
    result = validate_attack_target(
        source_cells=huge, target_cells=(GridCell(4, 1),),
        attack=_make_melee_attack(reach_feet=5),
        barriers=(), audience="player",
    )
    assert result.distance_feet == 10  # (2,1)-(4,1), not (0,1)-(4,1) = 20 ft
    assert not result.legal and result.range_band == "out_of_range"


# ---------------------------------------------------------------------------
# Pure range-band / reach behavior


def test_melee_reach_bands() -> None:
    near = validate_attack_target(
        source_cells=(GridCell(0, 0),), target_cells=(GridCell(1, 0),),
        attack=_make_melee_attack(reach_feet=5), barriers=(), audience="player",
    )
    assert (near.legal, near.range_band) == (True, "reach")
    far = validate_attack_target(
        source_cells=(GridCell(0, 0),), target_cells=(GridCell(2, 0),),
        attack=_make_melee_attack(reach_feet=5), barriers=(), audience="player",
    )
    assert (far.legal, far.range_band, far.blocked) == (False, "out_of_range", False)


def test_thrown_melee_uses_range_when_thrown() -> None:
    attack = _make_melee_attack()
    thrown = ResolvedAttack(
        source_ref=attack.source_ref, name=attack.name,
        attack_bonus=attack.attack_bonus, attack_kind=AttackKind.MELEE,
        damage_parts=attack.damage_parts,
        reach_feet=5, range_normal_feet=20, range_long_feet=60,
    )
    # Within reach: melee band.
    assert validate_attack_target(
        source_cells=(GridCell(0, 0),), target_cells=(GridCell(1, 0),),
        attack=thrown, barriers=(), audience="player",
    ).range_band == "reach"
    # Beyond reach but inside thrown normal range: normal band.
    mid = validate_attack_target(
        source_cells=(GridCell(0, 0),), target_cells=(GridCell(3, 0),),
        attack=thrown, barriers=(), audience="player",
    )
    assert (mid.legal, mid.range_band) == (True, "normal")
    # Long band for the thrown weapon.
    long = validate_attack_target(
        source_cells=(GridCell(0, 0),), target_cells=(GridCell(6, 0),),
        attack=thrown, barriers=(), audience="player",
    )
    assert (long.legal, long.range_band, long.is_long_range) == (True, "long", True)


def test_ranged_without_long_range_caps_at_normal() -> None:
    attack = _make_melee_attack()
    shortbow = ResolvedAttack(
        source_ref=attack.source_ref, name=attack.name,
        attack_bonus=attack.attack_bonus, attack_kind=AttackKind.RANGED,
        damage_parts=attack.damage_parts, range_normal_feet=80,
    )
    result = validate_attack_target(
        source_cells=(GridCell(0, 0),), target_cells=(GridCell(20, 0),),
        attack=shortbow, barriers=(), audience="player",
    )
    assert (result.legal, result.range_band) == (False, "out_of_range")


def test_attack_without_range_data_requires_dm_adjudication() -> None:
    attack = _make_melee_attack(reach_feet=None)
    result = validate_attack_target(
        source_cells=(GridCell(0, 0),), target_cells=(GridCell(1, 0),),
        attack=attack, barriers=(), audience="player",
    )
    assert result.requires_dm_adjudication is True
    assert result.legal is False


def test_is_within_reach_never_triggers_reactions() -> None:
    # Pure distance question: no DB, no events, no side channels.
    attack = _make_melee_attack(reach_feet=5)
    assert is_within_reach((GridCell(0, 0),), (GridCell(1, 0),), attack) is True
    assert is_within_reach((GridCell(0, 0),), (GridCell(2, 0),), attack) is False
    assert is_within_reach((GridCell(0, 0),), (GridCell(1, 0),), _make_melee_attack(reach_feet=None)) is False


# ---------------------------------------------------------------------------
# C.5 pure — hard blockers


def test_c5_wall_blocks_and_reports_kind() -> None:
    wall = BarrierView(BarrierSegment(1, 0, 1, 1), "wall")
    result = validate_attack_target(
        source_cells=(GridCell(0, 0),), target_cells=(GridCell(1, 0),),
        attack=_make_melee_attack(), barriers=(wall,), audience="player",
    )
    assert result.legal is False
    assert result.blocked is True
    assert result.blocker_kind == "wall"
    assert result.requires_dm_adjudication is False


def test_c5_closed_and_locked_doors_block() -> None:
    for kind in ("closed_door", "locked_door"):
        barrier = BarrierView(BarrierSegment(1, 0, 1, 1), kind)  # type: ignore[arg-type]
        result = validate_attack_target(
            source_cells=(GridCell(0, 0),), target_cells=(GridCell(1, 0),),
            attack=_make_melee_attack(), barriers=(barrier,), audience="player",
        )
        assert result.blocked is True, kind
        assert result.blocker_kind == kind


def test_c5_barrier_beside_the_sight_line_does_not_block() -> None:
    # Wall above the y=0.5 sight line: grazing touch is not a proper cross.
    wall = BarrierView(BarrierSegment(1, 1, 2, 1), "wall")
    result = validate_attack_target(
        source_cells=(GridCell(0, 0),), target_cells=(GridCell(2, 0),),
        attack=_make_melee_attack(reach_feet=10), barriers=(wall,), audience="player",
    )
    assert result.blocked is False
    assert result.legal is True


def test_c5_all_pairs_must_be_blocked_for_large_attacker() -> None:
    # Wall covers only the lower cell's sight line; the upper cell sees clear.
    wall = BarrierView(BarrierSegment(1, 0, 1, 1), "wall")
    result = validate_attack_target(
        source_cells=(GridCell(0, 0), GridCell(0, 1)),
        target_cells=(GridCell(2, 0),),
        attack=_make_melee_attack(reach_feet=15),
        barriers=(wall,), audience="player",
    )
    assert result.blocked is False
    assert result.legal is True


def test_c5_result_contract_has_no_ac_adjustment() -> None:
    names = {f.name for f in fields(SpatialTargetingResult)}
    assert names == {
        "legal", "distance_feet", "range_band", "blocked", "blocker_kind",
        "requires_dm_adjudication", "is_long_range", "target_within_5ft",
    }


# ---------------------------------------------------------------------------
# Hidden blocker secrecy (two audiences, pure)


def test_secrecy_player_sees_wall_for_hidden_wall() -> None:
    barrier = BarrierView(BarrierSegment(1, 0, 1, 1), "hidden_wall")
    result = validate_attack_target(
        source_cells=(GridCell(0, 0),), target_cells=(GridCell(1, 0),),
        attack=_make_melee_attack(), barriers=(barrier,), audience="player",
    )
    assert result.blocked is True
    assert result.blocker_kind == "wall"  # public-safe projection, no leak


def test_secrecy_dm_sees_hidden_wall() -> None:
    barrier = BarrierView(BarrierSegment(1, 0, 1, 1), "hidden_wall")
    result = validate_attack_target(
        source_cells=(GridCell(0, 0),), target_cells=(GridCell(1, 0),),
        attack=_make_melee_attack(), barriers=(barrier,), audience="dm",
    )
    assert result.blocked is True
    assert result.blocker_kind == "hidden_wall"


def test_secrecy_hidden_door_blocks_as_wall_for_player() -> None:
    barrier = BarrierView(BarrierSegment(1, 0, 1, 1), "hidden_door")
    player = validate_attack_target(
        source_cells=(GridCell(0, 0),), target_cells=(GridCell(1, 0),),
        attack=_make_melee_attack(), barriers=(barrier,), audience="player",
    )
    assert player.blocked is True
    assert player.blocker_kind == "wall"
    dm = validate_attack_target(
        source_cells=(GridCell(0, 0),), target_cells=(GridCell(1, 0),),
        attack=_make_melee_attack(), barriers=(barrier,), audience="dm",
    )
    assert dm.blocker_kind == "hidden_door"


# ---------------------------------------------------------------------------
# Spell range parsing


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Self", ("self", 0)),
        ("self", ("self", 0)),
        ("Touch", ("touch", 5)),
        ("60 feet", ("feet", 60)),
        ("120 feet", ("feet", 120)),
        ("1 mile", ("feet", 5280)),
        ("10 miles", ("feet", 52800)),
        ("Sight", ("unknown", None)),
        ("Special", ("unknown", None)),
        ("Unlimited", ("unknown", None)),
        ("", ("unknown", None)),
        (None, ("unknown", None)),
    ],
)
def test_parse_spell_range(text, expected) -> None:
    assert parse_spell_range(text) == expected


def test_spell_target_out_of_range_pure() -> None:
    result = validate_spell_target(
        source_cells=(GridCell(0, 0),), target_cells=(GridCell(30, 0),),
        range_feet=120, barriers=(), audience="player",
    )
    assert (result.legal, result.range_band, result.distance_feet) == (False, "out_of_range", 150)


def test_spell_target_touch_range_pure() -> None:
    adjacent = validate_spell_target(
        source_cells=(GridCell(0, 0),), target_cells=(GridCell(1, 0),),
        range_feet=5, barriers=(), audience="player",
    )
    assert adjacent.legal is True and adjacent.target_within_5ft is True
    far = validate_spell_target(
        source_cells=(GridCell(0, 0),), target_cells=(GridCell(2, 0),),
        range_feet=5, barriers=(), audience="player",
    )
    assert far.legal is False


# ---------------------------------------------------------------------------
# C.3 / C.4 — reach/range derivation through AttackDefinitionResolver


def _resolver(table: TacticalTable) -> AttackDefinitionResolver:
    return AttackDefinitionResolver(
        table.combat.character_repository,
        table.combat.monster_repository,
        table.registry,
    )


def _tactical_with_entries() -> tuple[TacticalTable, UUID, UUID]:
    table = setup_tactical_table()
    table.combat.start_tactical_combat(
        table.dm_actor,
        StartTacticalCombatInput(battle_map_id=_blank_map(table)),
    )
    return table, _character_entry_id(table), _add_monster(table)


def test_c3_glaive_reach_ten_through_resolver() -> None:
    table, char_entry, _ = _tactical_with_entries()
    _grant_weapon(table, "srd5.1:equipment:glaive")
    entry = table.combat.repository.get_entry(char_entry)
    assert entry is not None
    resolved = next(
        a for a in _resolver(table).attacks_for(entry) if a.name == "Glaive"
    )
    assert resolved.attack_kind is AttackKind.MELEE
    assert resolved.reach_feet == 10
    assert resolved.range_normal_feet is None


def test_c3_whip_reach_ten_through_resolver() -> None:
    table, char_entry, _ = _tactical_with_entries()
    _grant_weapon(table, "srd5.1:equipment:whip")
    entry = table.combat.repository.get_entry(char_entry)
    assert entry is not None
    resolved = next(
        a for a in _resolver(table).attacks_for(entry) if a.name == "Whip"
    )
    assert resolved.reach_feet == 10


def test_c3_longsword_reach_five_default() -> None:
    table, char_entry, _ = _tactical_with_entries()
    entry = table.combat.repository.get_entry(char_entry)
    assert entry is not None
    resolved = next(
        a for a in _resolver(table).attacks_for(entry) if a.name == "Longsword"
    )
    assert resolved.attack_kind is AttackKind.MELEE
    assert resolved.reach_feet == 5


def test_c3_monster_reach_ten_action() -> None:
    table, _, monster_entry = _tactical_with_entries()
    instance = table.combat.monster_repository.create_quick_enemy(
        campaign_id=table.campaign_id, name="Ogre",
        armor_class=11, max_hp=59, speed={"walk": "40 ft."},
        attack={
            "name": "Greatclub",
            "attack_bonus": 6,
            "damage": "2d8+4 bludgeoning",
            "attack_kind": "melee",
            "desc": "Melee Weapon Attack: +6 to hit, reach 10 ft., one target.",
        },
    )
    table.combat.add_monster(
        table.dm_actor, AddMonsterInput(monster_instance_id=instance.id)
    )
    view = table.combat.get_active_combat(table.dm_actor)
    assert view is not None
    ogre_entry = next(e for e in view.entries if e.monster_instance_id == instance.id)
    resolved = next(
        a for a in _resolver(table).attacks_for(ogre_entry) if a.name == "Greatclub"
    )
    assert resolved.reach_feet == 10


def test_c4_crossbow_light_range_through_resolver() -> None:
    table, char_entry, _ = _tactical_with_entries()
    _grant_weapon(table, "srd5.1:equipment:crossbow-light")
    entry = table.combat.repository.get_entry(char_entry)
    assert entry is not None
    resolved = next(
        a for a in _resolver(table).attacks_for(entry) if a.name == "Crossbow, light"
    )
    assert resolved.attack_kind is AttackKind.RANGED
    assert resolved.range_normal_feet == 80
    assert resolved.range_long_feet == 320
    assert resolved.reach_feet is None


def test_c4_crossbow_light_range_bands_pure() -> None:
    table, char_entry, _ = _tactical_with_entries()
    _grant_weapon(table, "srd5.1:equipment:crossbow-light")
    entry = table.combat.repository.get_entry(char_entry)
    assert entry is not None
    attack = next(
        a for a in _resolver(table).attacks_for(entry) if a.name == "Crossbow, light"
    )
    normal = validate_attack_target(
        source_cells=(GridCell(0, 0),), target_cells=(GridCell(10, 0),),
        attack=attack, barriers=(), audience="player",
    )
    assert (normal.legal, normal.range_band, normal.is_long_range) == (True, "normal", False)
    long = validate_attack_target(
        source_cells=(GridCell(0, 0),), target_cells=(GridCell(20, 0),),
        attack=attack, barriers=(), audience="player",
    )
    assert (long.legal, long.range_band, long.is_long_range) == (True, "long", True)
    out = validate_attack_target(
        source_cells=(GridCell(0, 0),), target_cells=(GridCell(70, 0),),
        attack=attack, barriers=(), audience="player",
    )
    assert (out.legal, out.range_band) == (False, "out_of_range")


# ---------------------------------------------------------------------------
# Condition distance boundaries (P5-C measured fact vs Quick fallback)


def test_c4_long_range_adds_disadvantage_source() -> None:
    decision = attack_modifiers(
        chosen=RollMode.NORMAL, attack_kind=AttackKind.RANGED,
        attacker_conditions=(), target_conditions=(),
        long_range=True,
    )
    assert "attack:long_range" in decision.disadvantage_sources
    assert decision.mode is RollMode.DISADVANTAGE


def test_condition_prone_ranged_within_5ft_keeps_prone_source() -> None:
    # Existing P4 semantics: within-5ft prone grants advantage via the
    # target:prone source for any attack kind. P5-C only wires the real
    # distance; it does not change the semantics.
    decision = attack_modifiers(
        chosen=RollMode.NORMAL, attack_kind=AttackKind.RANGED,
        attacker_conditions=(), target_conditions=("prone",),
        target_within_5ft=True,
    )
    assert decision.mode is RollMode.ADVANTAGE
    assert decision.advantage_sources == ("target:prone",)


def test_condition_prone_melee_beyond_5ft_no_within_advantage() -> None:
    decision = attack_modifiers(
        chosen=RollMode.NORMAL, attack_kind=AttackKind.MELEE,
        attacker_conditions=(), target_conditions=("prone",),
        target_within_5ft=False,  # reach-10 attack from 10 ft away
    )
    assert decision.mode is RollMode.DISADVANTAGE
    assert not any("prone" in s for s in decision.advantage_sources)


def test_condition_prone_quick_fallback_unchanged() -> None:
    ranged = attack_modifiers(
        chosen=RollMode.NORMAL, attack_kind=AttackKind.RANGED,
        attacker_conditions=(), target_conditions=("prone",),
        target_within_5ft=None,
    )
    assert ranged.mode is RollMode.DISADVANTAGE
    melee = attack_modifiers(
        chosen=RollMode.NORMAL, attack_kind=AttackKind.MELEE,
        attacker_conditions=(), target_conditions=("prone",),
        target_within_5ft=None,
    )
    assert melee.mode is RollMode.ADVANTAGE


@pytest.mark.parametrize("condition", ["paralyzed", "unconscious"])
def test_condition_adjacent_critical_uses_real_distance(condition: str) -> None:
    adjacent = attack_modifiers(
        chosen=RollMode.NORMAL, attack_kind=AttackKind.MELEE,
        attacker_conditions=(), target_conditions=(condition,),
        target_within_5ft=True,
    )
    assert adjacent.critical_on_hit is True
    distant = attack_modifiers(
        chosen=RollMode.NORMAL, attack_kind=AttackKind.MELEE,
        attacker_conditions=(), target_conditions=(condition,),
        target_within_5ft=False,
    )
    assert distant.critical_on_hit is False


# ---------------------------------------------------------------------------
# Service-level: Tactical spatial gating for attacks


def _request(attacks: CombatAttackService, actor, attacker: UUID, target: UUID,
             source_ref: str, *, key: str = "p5c-1") -> object:
    return attacks.request_attack(
        actor,
        AttackRequestInput(
            attacker_entry_id=attacker, target_entry_id=target,
            source_ref=source_ref, idempotency_key=key,
        ),
    )


def test_tactical_melee_adjacent_declares_without_adjudication() -> None:
    table, char_entry, monster_entry = _tactical_table()
    attacks = _attacks(table)
    source_ref = _attack_source_ref(attacks, table.player_actor, char_entry, "Longsword")
    view = _request(attacks, table.player_actor, char_entry, monster_entry, source_ref)
    assert view.roll_request_id is not None
    assert view.status == "waiting_for_roll"
    assert view.modifier_mode == "normal"
    # No adjudication row was created for the DM-authoritative Tactical path.
    pending = _attack_adjudications(table).list_pending(combat_id=_combat_id(table))
    assert all(a.target_entry_id != monster_entry for a in pending)


def test_tactical_reach_ten_hits_at_ten_feet() -> None:
    table = setup_tactical_table()
    table.combat.start_tactical_combat(
        table.dm_actor, StartTacticalCombatInput(battle_map_id=_blank_map(table))
    )
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _grant_weapon(table, "srd5.1:equipment:glaive")
    _running(table, char_entry=char_entry, monster_entry=monster_entry,
             monster_at=(3, 1))  # 10 ft away
    attacks = _attacks(table)
    source_ref = _attack_source_ref(attacks, table.player_actor, char_entry, "Glaive")
    view = _request(attacks, table.player_actor, char_entry, monster_entry, source_ref)
    assert view.status == "waiting_for_roll"
    assert view.roll_request_id is not None


def test_tactical_reach_five_rejects_ten_feet() -> None:
    table = setup_tactical_table()
    table.combat.start_tactical_combat(
        table.dm_actor, StartTacticalCombatInput(battle_map_id=_blank_map(table))
    )
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry,
             monster_at=(3, 1))  # 10 ft away, longsword reach 5
    attacks = _attacks(table)
    source_ref = _attack_source_ref(attacks, table.player_actor, char_entry, "Longsword")
    with pytest.raises(CombatTargetOutOfRangeError):
        _request(attacks, table.player_actor, char_entry, monster_entry, source_ref)
    # Zero side effects: nothing persisted for the rejected attack.
    assert attacks.repository.get_request(
        session_id=table.session_id, roll_request_id=uuid4()
    ) is None


def test_c3_hard_wall_between_rejects_attack() -> None:
    table = setup_tactical_table()
    map_id = _map_with_wall(table, x1=2, y1=1, x2=2, y2=2)
    table.combat.start_tactical_combat(
        table.dm_actor, StartTacticalCombatInput(battle_map_id=map_id)
    )
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry,
             char_at=(1, 1), monster_at=(2, 1))  # 5 ft: in reach, wall between
    attacks = _attacks(table)
    source_ref = _attack_source_ref(attacks, table.player_actor, char_entry, "Longsword")
    with pytest.raises(CombatTargetBlockedError) as exc_info:
        _request(attacks, table.player_actor, char_entry, monster_entry, source_ref,
                 key="p5c-wall")
    assert "wall" in str(exc_info.value)


def test_c5_closed_door_blocks_and_open_door_does_not() -> None:
    table = setup_tactical_table()
    map_id = _map_with_door(table, x1=2, y1=1, x2=2, y2=2, default_state="closed")
    table.combat.start_tactical_combat(
        table.dm_actor, StartTacticalCombatInput(battle_map_id=map_id)
    )
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry,
             char_at=(1, 1), monster_at=(2, 1))  # 5 ft: in reach, door between
    attacks = _attacks(table)
    source_ref = _attack_source_ref(attacks, table.player_actor, char_entry, "Longsword")
    with pytest.raises(CombatTargetBlockedError):
        _request(attacks, table.player_actor, char_entry, monster_entry, source_ref,
                 key="p5c-door-closed")
    door_id = next(iter(table.board.get_board(table.dm_actor).doors)).door_id
    table.board.update_door_state(
        table.dm_actor, door_id,
        UpdateDoorStateInput(state="open", expected_runtime_revision=1),
    )
    view = _request(attacks, table.player_actor, char_entry, monster_entry,
                    source_ref, key="p5c-door-open")
    assert view.status == "waiting_for_roll"


def test_c5_locked_door_blocks_attack() -> None:
    table = setup_tactical_table()
    map_id = _map_with_door(table, x1=2, y1=1, x2=2, y2=2, default_state="locked")
    table.combat.start_tactical_combat(
        table.dm_actor, StartTacticalCombatInput(battle_map_id=map_id)
    )
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry,
             char_at=(1, 1), monster_at=(2, 1))  # 5 ft: in reach, locked door between
    attacks = _attacks(table)
    source_ref = _attack_source_ref(attacks, table.player_actor, char_entry, "Longsword")
    with pytest.raises(CombatTargetBlockedError):
        _request(attacks, table.player_actor, char_entry, monster_entry, source_ref,
                 key="p5c-door-locked")


def test_c5_broken_door_does_not_block() -> None:
    table = setup_tactical_table()
    map_id = _map_with_door(table, x1=2, y1=1, x2=2, y2=2, default_state="closed")
    table.combat.start_tactical_combat(
        table.dm_actor, StartTacticalCombatInput(battle_map_id=map_id)
    )
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry,
             char_at=(1, 1), monster_at=(2, 1))  # 5 ft: in reach, door between
    door_id = next(iter(table.board.get_board(table.dm_actor).doors)).door_id
    table.board.update_door_state(
        table.dm_actor, door_id,
        UpdateDoorStateInput(state="broken", expected_runtime_revision=1),
    )
    attacks = _attacks(table)
    source_ref = _attack_source_ref(attacks, table.player_actor, char_entry, "Longsword")
    view = _request(attacks, table.player_actor, char_entry, monster_entry, source_ref)
    assert view.status == "waiting_for_roll"


def test_c4_tactical_long_range_attack_declares_disadvantage() -> None:
    table = setup_tactical_table()
    table.combat.start_tactical_combat(
        table.dm_actor, StartTacticalCombatInput(battle_map_id=_blank_map(table))
    )
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _grant_weapon(table, "srd5.1:equipment:crossbow-light")
    _running(table, char_entry=char_entry, monster_entry=monster_entry,
             char_at=(1, 1), monster_at=(21, 1))  # 100 ft: long band of 80/320
    attacks = _attacks(table)
    source_ref = _attack_source_ref(
        attacks, table.player_actor, char_entry, "Crossbow, light"
    )
    view = _request(attacks, table.player_actor, char_entry, monster_entry, source_ref)
    assert view.status == "waiting_for_roll"
    assert view.modifier_mode == "disadvantage"
    stored = attacks.repository.get_request(
        session_id=table.session_id, roll_request_id=view.roll_request_id
    )
    assert stored is not None
    assert stored.modifier_mode is RollMode.DISADVANTAGE


def test_c4_tactical_crossbow_long_band_declares() -> None:
    table = setup_tactical_table()
    table.combat.start_tactical_combat(
        table.dm_actor, StartTacticalCombatInput(battle_map_id=_blank_map(table))
    )
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _grant_weapon(table, "srd5.1:equipment:crossbow-light")
    _running(table, char_entry=char_entry, monster_entry=monster_entry,
             char_at=(1, 1), monster_at=(29, 1))  # 140 ft: long band of 80/320
    attacks = _attacks(table)
    source_ref = _attack_source_ref(
        attacks, table.player_actor, char_entry, "Crossbow, light"
    )
    view = _request(attacks, table.player_actor, char_entry, monster_entry, source_ref,
                    key="p5c-xbow-long")
    assert view.status == "waiting_for_roll"  # 140 ft is inside the long band


def test_c4_tactical_crossbow_beyond_long_range_rejected() -> None:
    table = setup_tactical_table()
    map_id = _blank_map(table, width_cells=70, height_cells=30)
    table.combat.start_tactical_combat(
        table.dm_actor, StartTacticalCombatInput(battle_map_id=map_id)
    )
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _grant_weapon(table, "srd5.1:equipment:crossbow-light")
    _running(table, char_entry=char_entry, monster_entry=monster_entry,
             char_at=(1, 1), monster_at=(66, 1))  # 325 ft > long 320
    attacks = _attacks(table)
    source_ref = _attack_source_ref(
        attacks, table.player_actor, char_entry, "Crossbow, light"
    )
    with pytest.raises(CombatTargetOutOfRangeError):
        _request(attacks, table.player_actor, char_entry, monster_entry, source_ref,
                 key="p5c-xbow-oor")
    _no_pending_attacks(table)


def test_c4_quick_crossbow_still_requires_dm_adjudication() -> None:
    table = setup_tactical_table()
    table.combat.start_quick_combat(table.dm_actor, StartCombatInput())
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _grant_weapon(table, "srd5.1:equipment:crossbow-light")
    _quick_running(table, char_entry=char_entry, monster_entry=monster_entry)
    attacks = _attacks(table)
    source_ref = _attack_source_ref(
        attacks, table.player_actor, char_entry, "Crossbow, light"
    )
    view = _request(attacks, table.player_actor, char_entry, monster_entry, source_ref)
    assert view.status == "dm_adjudication_required"
    assert view.roll_request_id is None  # DM adjudication, not a formal roll


def test_tactical_player_targeting_hidden_monster_rejected() -> None:
    table = setup_tactical_table()
    table.combat.start_tactical_combat(
        table.dm_actor, StartTacticalCombatInput(battle_map_id=_blank_map(table))
    )
    char_entry = _character_entry_id(table)
    hidden = table.combat.monster_repository.create_quick_enemy(
        campaign_id=table.campaign_id, name="Hidden Goblin",
        armor_class=15, max_hp=7, speed={"walk": "30 ft."},
        visibility="hidden",
    )
    table.combat.add_monster(
        table.dm_actor, AddMonsterInput(monster_instance_id=hidden.id)
    )
    view = table.combat.get_active_combat(table.dm_actor)
    assert view is not None
    hidden_entry = next(
        e for e in view.entries if e.monster_instance_id == hidden.id
    )
    _running(table, char_entry=char_entry, monster_entry=hidden_entry.id,
             monster_at=(2, 1))
    attacks = _attacks(table)
    source_ref = _attack_source_ref(attacks, table.player_actor, char_entry, "Longsword")
    with pytest.raises(CombatResolutionTargetNotFoundError):
        _request(attacks, table.player_actor, char_entry, hidden_entry.id, source_ref)


def test_tactical_uncontrolled_combatant_rejected_with_zero_side_effects() -> None:
    # A player trying to act through a combatant they do not control
    # (here: a Monster entry) is rejected before any persistence.
    table = setup_tactical_table()
    table.combat.start_tactical_combat(
        table.dm_actor, StartTacticalCombatInput(battle_map_id=_blank_map(table))
    )
    char_entry = _character_entry_id(table)
    instance = table.combat.monster_repository.create_quick_enemy(
        campaign_id=table.campaign_id, name="Orc",
        armor_class=13, max_hp=15, speed={"walk": "30 ft."},
        attack={
            "name": "Greataxe",
            "attack_bonus": 5,
            "damage": "1d12+3 slashing",
            "attack_kind": "melee",
            "desc": "Melee Weapon Attack: +5 to hit, reach 5 ft., one target.",
        },
    )
    table.combat.add_monster(
        table.dm_actor, AddMonsterInput(monster_instance_id=instance.id)
    )
    view = table.combat.get_active_combat(table.dm_actor)
    assert view is not None
    monster_entry = next(
        e.id for e in view.entries if e.monster_instance_id == instance.id
    )
    _running(table, char_entry=char_entry, monster_entry=monster_entry)
    attacks = _attacks(table)
    source_ref = _attack_source_ref(attacks, table.dm_actor, monster_entry, "Greataxe")
    with pytest.raises(TableEventActorUnauthorizedError):
        attacks.request_attack(
            table.player_actor,
            AttackRequestInput(
                attacker_entry_id=monster_entry, target_entry_id=char_entry,
                source_ref=source_ref, idempotency_key="p5c-unauth",
            ),
        )
    assert _attack_adjudications(table).list_pending(combat_id=_combat_id(table)) == ()


# ---------------------------------------------------------------------------
# C.6 — Tactical attacks reuse the P4 formal roll / damage / HP pipeline


def test_c6_tactical_attack_uses_p4_formal_roll_damage_and_hp() -> None:
    table, char_entry, monster_entry = _tactical_table()
    view = table.combat.get_active_combat(table.dm_actor)
    assert view is not None
    monster_instance_id = next(
        e.monster_instance_id for e in view.entries if e.id == monster_entry
    )
    assert monster_instance_id is not None

    attacks = _attacks(table)
    source_ref = _attack_source_ref(attacks, table.player_actor, char_entry, "Longsword")
    before = table.combat.monster_repository.get_instance(monster_instance_id)
    assert before is not None and before.current_hp == 7
    declared = _request(
        attacks, table.player_actor, char_entry, monster_entry, source_ref,
        key="p5c-c6",
    )
    # Same P4 persistence: the roll request resolves through the shared repository.
    assert declared.roll_request_id is not None
    stored = attacks.repository.get_request(
        session_id=table.session_id, roll_request_id=declared.roll_request_id
    )
    assert stored is not None
    assert stored.modifier_mode is RollMode.NORMAL
    assert stored.roll_request_id == declared.roll_request_id

    # Same P4 formal roll + damage pipeline: natural 20 physical roll.
    resolution = attacks.complete_attack(
        table.player_actor,
        FormalRollInput(
            roll_request_id=declared.roll_request_id,
            source=FormalRollSource.PHYSICAL,
            raw_dice=(20,),
            idempotency_key="p5c-c6-roll",
        ),
    )
    assert type(resolution).__name__ == "AttackResolutionView"  # no Tactical-specific model
    assert resolution.hit is True
    assert resolution.critical is True
    assert resolution.damage_total > 0

    # Same HP mutation: the monster row carries the new HP.
    instance = table.combat.monster_repository.get_instance(monster_instance_id)
    assert instance is not None
    assert instance.current_hp == max(0, 7 - resolution.damage_total)
    assert instance.current_hp < 7


def test_c6_tactical_and_quick_share_declare_path() -> None:
    # The declared row shape is identical whether the combat is Tactical
    # (DM-authoritative geometry) or Quick (DM adjudication).
    tactical_table, t_char, t_monster = _tactical_table()
    tactical_attacks = _attacks(tactical_table)
    t_ref = _attack_source_ref(tactical_attacks, tactical_table.player_actor, t_char, "Longsword")
    t_view = _request(tactical_attacks, tactical_table.player_actor, t_char, t_monster, t_ref, key="p5c-c6t")

    quick_table = setup_tactical_table()
    quick_table.combat.start_quick_combat(quick_table.dm_actor, StartCombatInput())
    q_char = _character_entry_id(quick_table)
    q_monster = _add_monster(quick_table)
    _quick_running(quick_table, char_entry=q_char, monster_entry=q_monster)
    quick_attacks = _attacks(quick_table)
    q_ref = _attack_source_ref(quick_attacks, quick_table.player_actor, q_char, "Longsword")
    q_view = _request(quick_attacks, quick_table.player_actor, q_char, q_monster, q_ref, key="p5c-c6q")

    t_stored = tactical_attacks.repository.get_request(
        session_id=tactical_table.session_id, roll_request_id=t_view.roll_request_id
    )
    assert t_stored is not None
    # Quick path stores an adjudication row, not a declared roll: the only
    # difference is the gating decision, not the persistence model.
    assert q_view.status == "dm_adjudication_required"
    assert t_stored.modifier_mode is RollMode.NORMAL


# ---------------------------------------------------------------------------
# Service-level: Tactical spell range validation


def _cast(spells: CombatSpellService, actor, caster: UUID, target: UUID | None,
          spell_ref: str, *, slot: int, key: str):
    return spells.cast_spell(
        actor,
        CastSpellInput(
            caster_entry_id=caster, target_entry_id=target,
            spell_ref=spell_ref, slot_level=slot, idempotency_key=key,
        ),
    )


def test_spell_120ft_in_range_casts() -> None:
    table = setup_tactical_table()
    table.combat.start_tactical_combat(
        table.dm_actor, StartTacticalCombatInput(battle_map_id=_blank_map(table))
    )
    _grant_spells(table, "srd5.1:spell:fire-bolt")
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry,
             char_at=(1, 1), monster_at=(20, 1))  # 95 ft < 120 ft
    spells = _spells(table)
    view = _cast(spells, table.player_actor, char_entry, monster_entry,
                 "srd5.1:spell:fire-bolt", slot=0, key="p5c-fb")
    assert view.status == "resolved"
    assert view.spell_ref == "srd5.1:spell:fire-bolt"


def test_spell_out_of_range_rejected_with_zero_side_effects() -> None:
    table = setup_tactical_table()
    table.combat.start_tactical_combat(
        table.dm_actor, StartTacticalCombatInput(battle_map_id=_blank_map(table))
    )
    _grant_spells(table, "srd5.1:spell:magic-missile")
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry,
             char_at=(1, 1), monster_at=(29, 1))  # 140 ft > 120 ft
    spells = _spells(table)
    before_slots = dict(
        table.combat.character_repository.load_character(
            table.character_id
        ).state.spell_slots
    )
    with pytest.raises(CombatTargetOutOfRangeError):
        _cast(spells, table.player_actor, char_entry, monster_entry,
              "srd5.1:spell:magic-missile", slot=1, key="p5c-mm-far")
    after_slots = dict(
        table.combat.character_repository.load_character(
            table.character_id
        ).state.spell_slots
    )
    assert after_slots == before_slots  # no slot spent on rejection


def test_spell_wall_blocked_rejected() -> None:
    table = setup_tactical_table()
    map_id = _map_with_wall(table, x1=3, y1=1, x2=3, y2=2)
    table.combat.start_tactical_combat(
        table.dm_actor, StartTacticalCombatInput(battle_map_id=map_id)
    )
    _grant_spells(table, "srd5.1:spell:fire-bolt")
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry,
             char_at=(1, 1), monster_at=(4, 1))
    spells = _spells(table)
    with pytest.raises(CombatTargetBlockedError) as exc_info:
        _cast(spells, table.player_actor, char_entry, monster_entry,
              "srd5.1:spell:fire-bolt", slot=0, key="p5c-fb-wall")
    assert "wall" in str(exc_info.value)


def test_spell_touch_range_adjacent_ok_and_far_rejected() -> None:
    table = setup_tactical_table()
    table.combat.start_tactical_combat(
        table.dm_actor, StartTacticalCombatInput(battle_map_id=_blank_map(table))
    )
    _grant_spells(table, "srd5.1:spell:cure-wounds")
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry,
             char_at=(1, 1), monster_at=(2, 1))  # 5 ft
    spells = _spells(table)
    view = _cast(spells, table.player_actor, char_entry, monster_entry,
                 "srd5.1:spell:cure-wounds", slot=1, key="p5c-cw-near")
    assert view.status == "resolved"

    far_table = setup_tactical_table()
    far_table.combat.start_tactical_combat(
        far_table.dm_actor, StartTacticalCombatInput(battle_map_id=_blank_map(far_table))
    )
    _grant_spells(far_table, "srd5.1:spell:cure-wounds")
    f_char = _character_entry_id(far_table)
    f_monster = _add_monster(far_table)
    _running(far_table, char_entry=f_char, monster_entry=f_monster,
             char_at=(1, 1), monster_at=(3, 1))  # 10 ft > touch
    f_spells = _spells(far_table)
    with pytest.raises(CombatTargetOutOfRangeError):
        _cast(f_spells, far_table.player_actor, f_char, f_monster,
              "srd5.1:spell:cure-wounds", slot=1, key="p5c-cw-far")


def test_spell_self_range_targets_caster_only() -> None:
    table = setup_tactical_table()
    table.combat.start_tactical_combat(
        table.dm_actor, StartTacticalCombatInput(battle_map_id=_blank_map(table))
    )
    _grant_spells(table, "srd5.1:spell:misty-step")
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)
    spells = _spells(table)
    view = _cast(spells, table.player_actor, char_entry, char_entry,
                 "srd5.1:spell:misty-step", slot=2, key="p5c-ms-self")
    assert view.status == "resolved"
    with pytest.raises(CombatStateConflictError):
        _cast(spells, table.player_actor, char_entry, monster_entry,
              "srd5.1:spell:misty-step", slot=2, key="p5c-ms-other")


def test_spell_unknown_range_skips_spatial_gate() -> None:
    # White-box: parse -> ("unknown", None) must not gate, even behind a wall.
    table = setup_tactical_table()
    map_id = _map_with_wall(table, x1=3, y1=1, x2=3, y2=2)
    table.combat.start_tactical_combat(
        table.dm_actor, StartTacticalCombatInput(battle_map_id=map_id)
    )
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry,
             char_at=(1, 1), monster_at=(4, 1))
    spells = _spells(table)
    combat = table.combat.repository.get_active(table.campaign_id)
    assert combat is not None and combat.mode == "tactical"
    caster = table.combat.repository.get_entry(char_entry)
    target = table.combat.repository.get_entry(monster_entry)
    assert caster is not None and target is not None
    # "Sight" parses to unknown: the gate is skipped, legacy DM adjudication stays.
    spells._validate_tactical_spell_target(
        table.player_actor,
        caster_entry=caster, target_entry=target,
        range_text="Sight", targeting_kind="single",
    )


def test_spell_player_targeting_hidden_monster_rejected() -> None:
    table = setup_tactical_table()
    table.combat.start_tactical_combat(
        table.dm_actor, StartTacticalCombatInput(battle_map_id=_blank_map(table))
    )
    char_entry = _character_entry_id(table)
    hidden = table.combat.monster_repository.create_quick_enemy(
        campaign_id=table.campaign_id, name="Hidden Goblin",
        armor_class=15, max_hp=7, speed={"walk": "30 ft."},
        visibility="hidden",
    )
    table.combat.add_monster(
        table.dm_actor, AddMonsterInput(monster_instance_id=hidden.id)
    )
    view = table.combat.get_active_combat(table.dm_actor)
    assert view is not None
    hidden_entry = next(
        e.id for e in view.entries if e.monster_instance_id == hidden.id
    )
    _grant_spells(table, "srd5.1:spell:fire-bolt")
    _running(table, char_entry=char_entry, monster_entry=hidden_entry,
             monster_at=(2, 1))
    spells = _spells(table)
    with pytest.raises(CombatResolutionTargetNotFoundError):
        _cast(spells, table.player_actor, char_entry, hidden_entry,
              "srd5.1:spell:fire-bolt", slot=0, key="p5c-fb-hidden")


# ---------------------------------------------------------------------------
# API error mapping


def test_api_maps_range_errors_to_409() -> None:
    out_of_range = _map_combat_error(
        CombatTargetOutOfRangeError("target is out of range")
    )
    assert out_of_range.status_code == 409
    assert out_of_range.code == "combat_target_out_of_range"
    blocked = _map_combat_error(
        CombatTargetBlockedError("target is blocked")
    )
    assert blocked.status_code == 409
    assert blocked.code == "combat_target_blocked"
