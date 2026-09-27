"""P5-D D1: Tactical AoE preview / propose / resolve (backend only).

Covers 測試指南 D.4-D.6:
- D.4 Tactical preview 是純計算（affected cells + candidates + board revision）；
  propose 必須帶 template + board_revision 且 server 用 board positions 重算
  candidates（忽略 client 送的 targets）；monster DM-adjudicated 路徑保留；
  template 必須符合 spell content 的 AoE shape/size
- D.5 board revision 過期 -> CombatBoardStaleError（transaction 內原子檢查，
  零副作用）；API 映射為 409 combat_board_stale
- D.6 DM confirm 可增刪 targets（Tactical 限定）；resolve 走 P4 管線且只能一次；
  player 看不到 hidden candidates（response + event projection）；幾何本身不
  因 hidden 而改變（affected_cells 仍含 hidden 所在格）
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, insert, select, update

from app.api.rooms.combat_spells import _map_error
from app.domain.character.schemas import (
    CharacterBuild,
    SpellcastingProfile,
    SpellResourcePool,
    SpellSlotCapacity,
)
from app.domain.combat.aoe_adjudication import confirm_aoe, propose_aoe
from app.domain.combat.board import CombatBoardStaleError, PlaceCombatantInput
from app.domain.combat.event_projection import project_combat_event_payload
from app.domain.combat.lifecycle import (
    AddMonsterInput,
    ResolveInitiativeOrderInput,
    StartTacticalCombatInput,
)
from app.domain.combat.movement import MovementService, RepositionInput
from app.domain.combat.spell_resolver import SaveDamageMode
from app.domain.combat.spell_service import (
    AoeTemplateInput,
    CombatSpellService,
    PreviewAoeSpellInput,
    ProposeAoeSpellInput,
    ResolveAoeSpellInput,
)
from app.domain.combat.resolution import DamageRollPart, DamageType
from app.persistence.combat.spells import CombatSpellRepository
from app.persistence.battle_maps.tables import battle_maps
from app.persistence.combat.tables import (
    combat_actions,
    combat_entries,
)
from app.persistence.rooms.table_runtime import session_events
from app.domain.combat.roll_compat import CombatAwareRollRepository
from tests.p5a_tactical_helpers import TacticalTable, setup_tactical_table
from app.domain.rooms.character_rolls import CharacterRollModifierResolver
from app.domain.rooms.rolls import RollService
from app.persistence.rooms.exploration_subjects import ExplorationSubjectRepository


def _character_entry_id(table: TacticalTable) -> UUID:
    view = table.combat.get_active_combat(table.dm_actor)
    assert view is not None
    return view.entries[0].id


def _add_monster(table: TacticalTable, *, visibility: str = "public") -> UUID:
    before = {
        e.id
        for e in table.combat.get_active_combat(table.dm_actor).entries  # type: ignore[union-attr]
    }
    instance = table.combat.monster_repository.create_quick_enemy(
        campaign_id=table.campaign_id,
        name="Goblin",
        armor_class=15,
        max_hp=7,
        speed={"walk": "30 ft."},
        visibility=visibility,
    )
    table.combat.add_monster(
        table.dm_actor, AddMonsterInput(monster_instance_id=instance.id)
    )
    view = table.combat.get_active_combat(table.dm_actor)
    assert view is not None
    new_entries = [e.id for e in view.entries if e.id not in before]
    assert len(new_entries) == 1
    return new_entries[0]


FIREBALL_REF = "srd5.1:spell:fireball"
FIREBALL_TEMPLATE = AoeTemplateInput(shape="circle", size_feet=20, origin_x=5, origin_y=5)


def _blank_map(table: TacticalTable, width_cells: int = 30, height_cells: int = 20) -> UUID:
    map_id = uuid4()
    now = datetime.now(timezone.utc)
    with table.engine.begin() as conn:
        conn.execute(
            insert(battle_maps).values(
                id=map_id,
                room_id=table.room_id,
                name="p5d-test",
                source_kind="blank",
                image_asset_id=None,
                width_cells=width_cells,
                height_cells=height_cells,
                grid_pixel_size=None,
                grid_offset_x=None,
                grid_offset_y=None,
                revision=1,
                created_at=now,
                updated_at=now,
            )
        )
    return map_id


def _enable_fireball_profile(table: TacticalTable) -> None:
    from app.persistence.characters import character_versions, characters

    with table.engine.begin() as connection:
        version_id = connection.scalar(
            select(characters.c.current_version_id).where(
                characters.c.id == table.character_id
            )
        )
        assert version_id is not None
        row = connection.execute(
            select(character_versions.c.build_payload).where(
                character_versions.c.id == version_id
            )
        ).mappings().one()
        build = CharacterBuild.model_validate(row["build_payload"])
        wizard = "srd5.1:class:wizard"
        profile = SpellcastingProfile(
            profile_id="wizard",
            source_type="class",
            source_key=wizard,
            class_ref=wizard,
            ability="intelligence",
            access_model="spellbook",
            resource_pool_type="normal_multiclass_slots",
            max_spell_level=3,
            prepared_limit=8,
        )
        pool = SpellResourcePool(
            pool_id="normal_multiclass",
            pool_type="normal_multiclass_slots",
            slots=(
                SpellSlotCapacity(level=1, capacity=4),
                SpellSlotCapacity(level=2, capacity=3),
                SpellSlotCapacity(level=3, capacity=2),
            ),
        )
        next_build = build.model_copy(
            update={
                "spellcasting_profiles": (profile,),
                "spell_resource_pools": (pool,),
            },
            deep=True,
        )
        connection.execute(
            update(character_versions)
            .where(character_versions.c.id == version_id)
            .values(build_payload=next_build.model_dump(mode="json"))
        )


def _tactical_aoe_table() -> tuple[TacticalTable, UUID, UUID, UUID]:
    """Tactical combat, running: char (1,1), goblin (5,5), hidden goblin (6,6)."""
    table = setup_tactical_table()
    table.combat.start_tactical_combat(
        table.dm_actor, StartTacticalCombatInput(battle_map_id=_blank_map(table))
    )
    char_entry = _character_entry_id(table)
    goblin = _add_monster(table, visibility="public")
    hidden = _add_monster(table, visibility="hidden")
    table.board.place_position(
        table.dm_actor, char_entry, PlaceCombatantInput(anchor_x=1, anchor_y=1)
    )
    table.board.place_position(
        table.dm_actor, goblin, PlaceCombatantInput(anchor_x=5, anchor_y=5)
    )
    table.board.place_position(
        table.dm_actor, hidden, PlaceCombatantInput(anchor_x=6, anchor_y=6)
    )
    with table.engine.begin() as conn:
        conn.execute(
            update(combat_entries)
            .where(combat_entries.c.id == char_entry)
            .values(initiative_total=20)
        )
        conn.execute(
            update(combat_entries)
            .where(combat_entries.c.id == goblin)
            .values(initiative_total=10)
        )
        conn.execute(
            update(combat_entries)
            .where(combat_entries.c.id == hidden)
            .values(initiative_total=5)
        )
    table.combat.resolve_initiative_order(
        table.dm_actor,
        ResolveInitiativeOrderInput(ordered_entry_ids=(char_entry, goblin, hidden)),
    )
    _enable_fireball_profile(table)
    return table, char_entry, goblin, hidden


def _spells(table: TacticalTable) -> CombatSpellService:
    return CombatSpellService(
        repository=CombatSpellRepository(table.engine, table.events.repository),
        combat_repository=table.combat.repository,
        combat_service=table.combat,
        table_event_service=table.events,
        monster_repository=table.combat.monster_repository,
        character_repository=table.combat.character_repository,
        roll_service=RollService(
            CombatAwareRollRepository(table.engine, table.events.repository),
            ExplorationSubjectRepository(table.engine),
            table.events,
            CharacterRollModifierResolver(
                table.combat.character_repository, table.registry
            ),
        ),
        registry=table.registry,
        board_service=table.board,
    )


def _board_revision(table: TacticalTable) -> int:
    return table.board.get_board(table.dm_actor).runtime_revision


def _movement(table: TacticalTable) -> MovementService:
    return MovementService(
        board_repository=table.board.board_repository,
        board_service=table.board,
        combat_service=table.combat,
    )


def _propose_input(
    caster_entry_id: UUID,
    goblin: UUID,
    *,
    template: AoeTemplateInput | None = FIREBALL_TEMPLATE,
    board_revision: int | None = None,
    proposed_target_ids: tuple[UUID, ...] | None = None,
    idempotency_key: str | None = None,
) -> ProposeAoeSpellInput:
    return ProposeAoeSpellInput(
        caster_entry_id=caster_entry_id,
        spell_ref=FIREBALL_REF,
        slot_level=3,
        profile_id="wizard",
        proposed_target_ids=(
            proposed_target_ids if proposed_target_ids is not None else (goblin,)
        ),
        idempotency_key=idempotency_key,
        template=template,
        board_revision=board_revision,
    )


def _action_count(table: TacticalTable) -> int:
    with table.engine.connect() as conn:
        return int(conn.scalar(select(func.count()).select_from(combat_actions)) or 0)


def _event_count(table: TacticalTable) -> int:
    with table.engine.connect() as conn:
        return int(conn.scalar(select(func.count()).select_from(session_events)) or 0)


def _action_payload(table: TacticalTable, action_id: UUID) -> dict:
    with table.engine.connect() as conn:
        row = conn.execute(
            select(combat_actions.c.payload).where(combat_actions.c.id == action_id)
        ).mappings().one()
        return dict(row["payload"] or {})


# ---------------------------------------------------------------------------
# D.4 Tactical preview / propose
# ---------------------------------------------------------------------------


def test_preview_returns_cells_candidates_and_revision() -> None:
    table, char_entry, goblin, _hidden = _tactical_aoe_table()
    service = _spells(table)
    preview = service.preview_aoe(
        table.player_actor,
        PreviewAoeSpellInput(
            caster_entry_id=char_entry,
            spell_ref=FIREBALL_REF,
            template=FIREBALL_TEMPLATE,
        ),
    )
    assert preview.board_revision == _board_revision(table)
    assert preview.affected_cells, "fireball must cover cells"
    assert all(
        0 <= cell.x < 30 and 0 <= cell.y < 20 for cell in preview.affected_cells
    )
    candidate_ids = {c.entry_id for c in preview.candidates}
    assert goblin in candidate_ids
    assert char_entry not in candidate_ids  # 35 ft away, outside the 20 ft circle


def test_preview_hides_hidden_candidates_from_player_but_not_dm() -> None:
    table, char_entry, _goblin, hidden = _tactical_aoe_table()
    service = _spells(table)
    player_view = service.preview_aoe(
        table.player_actor,
        PreviewAoeSpellInput(
            caster_entry_id=char_entry,
            spell_ref=FIREBALL_REF,
            template=FIREBALL_TEMPLATE,
        ),
    )
    assert hidden not in {c.entry_id for c in player_view.candidates}
    dm_view = service.preview_aoe(
        table.dm_actor,
        PreviewAoeSpellInput(
            caster_entry_id=char_entry,
            spell_ref=FIREBALL_REF,
            template=FIREBALL_TEMPLATE,
        ),
    )
    assert hidden in {c.entry_id for c in dm_view.candidates}
    # Geometry itself is not redacted: the hidden goblin's cell is still covered.
    assert any(cell.x == 6 and cell.y == 6 for cell in player_view.affected_cells)


def test_preview_rejects_shape_mismatch_with_spell() -> None:
    table, char_entry, _goblin, _hidden = _tactical_aoe_table()
    service = _spells(table)
    with pytest.raises(ValueError, match="does not match"):
        service.preview_aoe(
            table.player_actor,
            PreviewAoeSpellInput(
                caster_entry_id=char_entry,
                spell_ref=FIREBALL_REF,
                template=AoeTemplateInput(
                    shape="square", size_feet=20, origin_x=5, origin_y=5,
                    direction="se",
                ),
            ),
        )
    with pytest.raises(ValueError, match="does not match"):
        service.preview_aoe(
            table.player_actor,
            PreviewAoeSpellInput(
                caster_entry_id=char_entry,
                spell_ref=FIREBALL_REF,
                template=AoeTemplateInput(
                    shape="circle", size_feet=15, origin_x=5, origin_y=5
                ),
            ),
        )


def test_propose_recomputes_candidates_and_ignores_client_targets() -> None:
    table, char_entry, goblin, hidden = _tactical_aoe_table()
    service = _spells(table)
    revision = _board_revision(table)
    # Client claims only the caster is hit; the server must recompute.
    response = service.propose_aoe(
        table.player_actor,
        _propose_input(
            char_entry,
            goblin,
            board_revision=revision,
            proposed_target_ids=(char_entry,),
            idempotency_key="p5d-tactical-propose",
        ),
    )
    assert response.status == "dm_adjudication_required"
    stored = service.repository.get_aoe_action(
        session_id=table.session_id, action_id=response.action_id
    )
    assert stored is not None
    assert {UUID(v) for v in stored.adjudication.proposed_target_ids} == {goblin, hidden}
    # Player response hides the hidden goblin.
    assert set(response.proposed_target_ids) == {goblin}
    tactical = _action_payload(table, response.action_id)["tactical"]
    assert tactical["candidate_source"] == "geometry"
    assert tactical["board_revision"] == revision
    assert tactical["shape"] == {
        "kind": "circle",
        "size_feet": 20,
        "origin": [5, 5],
        "aim": None,
        "direction": None,
    }


def test_propose_requires_template_and_revision_in_tactical() -> None:
    table, char_entry, goblin, _hidden = _tactical_aoe_table()
    service = _spells(table)
    with pytest.raises(ValueError, match="template"):
        service.propose_aoe(
            table.player_actor,
            _propose_input(char_entry, goblin, template=None,
                           board_revision=_board_revision(table)),
        )
    with pytest.raises(ValueError, match="board_revision"):
        service.propose_aoe(
            table.player_actor,
            _propose_input(char_entry, goblin, board_revision=None),
        )


def test_monster_proposal_keeps_dm_adjudication_without_template() -> None:
    """Repository-level: monster tactical AoE stores dm_adjudicated metadata and
    skips the board-revision gate (expected_board_revision=None)."""
    table, _char, goblin, _hidden = _tactical_aoe_table()
    repository = CombatSpellRepository(table.engine, table.events.repository)
    binding = table.events._stored_binding(table.dm_actor)
    combat = table.combat.get_active_combat(table.dm_actor)
    assert combat is not None
    # The monster casts on its own turn.
    table.combat.advance_turn(table.dm_actor)
    assert table.combat.get_active_combat(table.dm_actor).current_turn_entry_id == goblin
    proposed, _event = repository.propose_character_aoe(
        binding=binding,
        combat_id=combat.id,
        caster_entry_id=goblin,
        subject_seat_id=None,
        execution_mode="self",
        profile_id="monster",
        spell_ref=FIREBALL_REF,
        spell_level=3,
        slot_level=3,
        save_ability_ref="srd5.1:ability:dex",
        save_dc=13,
        save_damage_mode=SaveDamageMode.HALF,
        proposed_target_ids=(goblin,),
        idempotency_key="p5d-monster-aoe",
        expected_board_revision=None,
        tactical={"candidate_source": "dm_adjudicated"},
    )
    assert proposed.status == "dm_adjudication_required"
    assert _action_payload(table, proposed.action_id)["tactical"] == {
        "candidate_source": "dm_adjudicated"
    }


# ---------------------------------------------------------------------------
# D.5 stale board revision
# ---------------------------------------------------------------------------


def test_stale_revision_conflicts_with_zero_side_effects() -> None:
    table, char_entry, goblin, _hidden = _tactical_aoe_table()
    service = _spells(table)
    stale_revision = _board_revision(table)
    # The board changes after the preview: the DM repositions the goblin,
    # bumping the board runtime revision (plain placement does not bump it).
    _movement(table).reposition(
        table.dm_actor,
        goblin,
        RepositionInput(
            entry_id=goblin,
            anchor_x=7,
            anchor_y=5,
            reason="DM correction",
            expected_position_revision=1,
            idempotency_key="p5d-stale-move",
        ),
    )
    assert _board_revision(table) == stale_revision + 1

    actions_before = _action_count(table)
    events_before = _event_count(table)
    with pytest.raises(CombatBoardStaleError):
        service.propose_aoe(
            table.player_actor,
            _propose_input(
                char_entry,
                goblin,
                board_revision=stale_revision,
                idempotency_key="p5d-stale-propose",
            ),
        )
    assert _action_count(table) == actions_before
    assert _event_count(table) == events_before

    # Re-preview and resend with the fresh revision succeeds.
    response = service.propose_aoe(
        table.player_actor,
        _propose_input(
            char_entry,
            goblin,
            board_revision=_board_revision(table),
            idempotency_key="p5d-stale-propose-retry",
        ),
    )
    assert response.status == "dm_adjudication_required"


def test_tactical_propose_allows_empty_candidate_set() -> None:
    table, char_entry, _goblin, _hidden = _tactical_aoe_table()
    service = _spells(table)
    # Fireball on empty ground: the geometry recompute honestly finds zero
    # candidates and the proposal still succeeds (Tactical only).
    template = AoeTemplateInput(shape="circle", size_feet=20, origin_x=25, origin_y=15)
    preview = service.preview_aoe(
        table.player_actor,
        PreviewAoeSpellInput(
            caster_entry_id=char_entry, spell_ref=FIREBALL_REF, template=template
        ),
    )
    assert preview.candidates == ()
    response = service.propose_aoe(
        table.player_actor,
        ProposeAoeSpellInput(
            caster_entry_id=char_entry,
            spell_ref=FIREBALL_REF,
            slot_level=3,
            proposed_target_ids=(uuid4(),),  # ignored for Tactical
            template=template,
            board_revision=preview.board_revision,
            idempotency_key="p5d-empty-candidates",
        ),
    )
    assert response.status == "dm_adjudication_required"
    assert response.proposed_target_ids == ()
    tactical = _action_payload(table, response.action_id)["tactical"]
    assert tactical["candidate_source"] == "geometry"
    # DM confirms the empty set and the spell resolves (slot still spent).
    resolved = service.resolve_aoe(
        table.dm_actor,
        ResolveAoeSpellInput(
            action_id=response.action_id,
            confirmed_target_ids=(),
            save_modifiers={},
            save_d20s={},
            damage_parts=(DamageRollPart(damage_type=DamageType.FIRE, dice=(8, 8)),),
            roll_source="server",
            idempotency_key="p5d-empty-candidates-resolve",
        ),
    )
    assert resolved.status == "resolved"
    assert resolved.confirmed_target_ids == ()


def test_quick_propose_still_rejects_empty_targets() -> None:
    table, char_entry, _goblin, _hidden = _tactical_aoe_table()
    repository = CombatSpellRepository(table.engine, table.events.repository)
    binding = table.events._stored_binding(table.dm_actor)
    combat = table.combat.get_active_combat(table.dm_actor)
    assert combat is not None
    with pytest.raises(ValueError, match="at least one proposed target"):
        repository.propose_character_aoe(
            binding=binding,
            combat_id=combat.id,
            caster_entry_id=char_entry,
            subject_seat_id=table.player_actor.seat_id,
            execution_mode="self",
            profile_id="character",
            spell_ref=FIREBALL_REF,
            spell_level=3,
            slot_level=3,
            save_ability_ref="dexterity",
            save_dc=15,
            save_damage_mode="half",
            proposed_target_ids=(),
            idempotency_key="p5d-quick-empty",
        )


def test_api_maps_board_stale_to_409() -> None:
    error = _map_error(CombatBoardStaleError("board changed"))
    assert error.status_code == 409
    assert error.code == "combat_board_stale"


# ---------------------------------------------------------------------------
# D.6 DM adjudication, resolve-once, secrecy
# ---------------------------------------------------------------------------


def test_dm_confirm_can_add_and_remove_tactical_targets() -> None:
    table, char_entry, goblin, hidden = _tactical_aoe_table()
    service = _spells(table)
    response = service.propose_aoe(
        table.player_actor,
        _propose_input(
            char_entry,
            goblin,
            board_revision=_board_revision(table),
            idempotency_key="p5d-dm-adjudicate",
        ),
    )
    # Remove the proposed goblin, add the hidden one: allowed for Tactical.
    resolved = service.resolve_aoe(
        table.dm_actor,
        ResolveAoeSpellInput(
            action_id=response.action_id,
            confirmed_target_ids=(hidden,),
            save_modifiers={hidden: 0},
            save_d20s={hidden: 1},
            damage_parts=(
                DamageRollPart(damage_type=DamageType.FIRE, dice=(8, 8)),
            ),
            roll_source="server",
            idempotency_key="p5d-dm-adjudicate-resolve",
        ),
    )
    assert resolved.status == "resolved"
    assert set(resolved.confirmed_target_ids) == {hidden}
    stored = service.repository.get_aoe_action(
        session_id=table.session_id, action_id=response.action_id
    )
    assert stored is not None
    assert {UUID(v) for v in stored.adjudication.confirmed_target_ids} == {hidden}


def test_confirm_aoe_still_rejects_subset_violation_for_quick() -> None:
    proposed = propose_aoe(
        command_id="quick:1", acting_entry_id="caster", target_ids=("a", "b")
    )
    with pytest.raises(ValueError):
        confirm_aoe(proposed, confirmed_target_ids=("a", "c"))
    with pytest.raises(ValueError):
        confirm_aoe(proposed, confirmed_target_ids=("a", "b", "b"))
    # Exact subset still works.
    confirmed = confirm_aoe(proposed, confirmed_target_ids=("a",))
    assert confirmed.confirmed_target_ids == ("a",)
    # Domain propose_aoe keeps the P4 non-empty gate; Tactical opts out.
    with pytest.raises(ValueError):
        propose_aoe(command_id="quick:2", acting_entry_id="caster", target_ids=())
    empty = propose_aoe(
        command_id="quick:3", acting_entry_id="caster", target_ids=(), allow_empty=True
    )
    assert empty.proposed_target_ids == ()


def test_resolve_happens_once_and_consumes_action() -> None:
    table, char_entry, goblin, _hidden = _tactical_aoe_table()
    service = _spells(table)
    response = service.propose_aoe(
        table.player_actor,
        _propose_input(
            char_entry,
            goblin,
            board_revision=_board_revision(table),
            idempotency_key="p5d-resolve-once",
        ),
    )
    resolved = service.resolve_aoe(
        table.dm_actor,
        ResolveAoeSpellInput(
            action_id=response.action_id,
            confirmed_target_ids=(goblin,),
            save_modifiers={goblin: 0},
            save_d20s={goblin: 1},
            damage_parts=(
                DamageRollPart(damage_type=DamageType.FIRE, dice=(8, 8)),
            ),
            roll_source="server",
            idempotency_key="p5d-resolve-once-resolve",
        ),
    )
    assert resolved.status == "resolved"
    assert resolved.resolution_result is not None
    with table.engine.connect() as conn:
        action_available = conn.scalar(
            select(combat_entries.c.action_available).where(
                combat_entries.c.id == char_entry
            )
        )
    assert action_available is False
    # Second resolve is rejected (already resolved).
    with pytest.raises(Exception):
        service.resolve_aoe(
            table.dm_actor,
            ResolveAoeSpellInput(
                action_id=response.action_id,
                confirmed_target_ids=(goblin,),
                idempotency_key="p5d-resolve-once-retry",
            ),
        )


def test_hidden_caster_entry_id_redacted_from_player_event() -> None:
    payload = {
        "combat_id": str(uuid4()),
        "action_id": str(uuid4()),
        "caster_entry_id": "hidden-caster",
        "spell_ref": FIREBALL_REF,
        "proposed_target_ids": ["t1"],
        "status": "dm_adjudication_required",
        "tactical": {"candidate_source": "dm_adjudicated"},
    }
    player_payload = project_combat_event_payload(
        "combat.spell_aoe_adjudication_requested",
        dict(payload),
        audience="player",
        hidden_entry_ids={"hidden-caster"},
    )
    assert player_payload["caster_entry_id"] is None
    assert player_payload["tactical"] == {"candidate_source": "dm_adjudicated"}
    dm_payload = project_combat_event_payload(
        "combat.spell_aoe_adjudication_requested",
        dict(payload),
        audience="dm",
        hidden_entry_ids={"hidden-caster"},
    )
    assert dm_payload["caster_entry_id"] == "hidden-caster"


def test_tactical_event_projection_strips_hidden_targets() -> None:
    table, char_entry, goblin, hidden = _tactical_aoe_table()
    service = _spells(table)
    response = service.propose_aoe(
        table.player_actor,
        _propose_input(
            char_entry,
            goblin,
            board_revision=_board_revision(table),
            idempotency_key="p5d-event-secrecy",
        ),
    )
    stored = service.repository.get_aoe_action(
        session_id=table.session_id, action_id=response.action_id
    )
    assert stored is not None
    with table.engine.connect() as conn:
        proposal_payload = conn.execute(
            select(session_events.c.payload)
            .where(
                session_events.c.session_id == table.session_id,
                session_events.c.kind == "combat.spell_aoe_adjudication_requested",
            )
            .order_by(session_events.c.seq.desc())
        ).mappings().first()["payload"]
    assert proposal_payload["action_id"] == str(response.action_id)
    assert set(proposal_payload["proposed_target_ids"]) == {str(goblin), str(hidden)}
    player_payload = project_combat_event_payload(
        "combat.spell_aoe_adjudication_requested",
        dict(proposal_payload),
        audience="player",
        hidden_entry_ids={str(hidden)},
    )
    assert str(hidden) not in player_payload["proposed_target_ids"]
    assert str(goblin) in player_payload["proposed_target_ids"]
    # Tactical geometry metadata survives projection (no entry ids inside).
    assert player_payload["tactical"]["candidate_source"] == "geometry"
    dm_payload = project_combat_event_payload(
        "combat.spell_aoe_adjudication_requested",
        dict(proposal_payload),
        audience="dm",
        hidden_entry_ids={str(hidden)},
    )
    assert set(dm_payload["proposed_target_ids"]) == {str(goblin), str(hidden)}
