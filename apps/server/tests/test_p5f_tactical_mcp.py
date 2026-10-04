"""P5-F F1 backend tests: tactical MCP tools, target check, DM wall visibility, briefing.

Covers the P5 test-guide F.3-F.7 backend surface. New tests live only in
``tests/test_p5f_*.py``; no existing test file is modified.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from app.content.registry import ContentNotFoundError
from app.domain.battle_maps.service import BattleMapService
from app.domain.combat.ai_tools import (
    CombatAIToolApplicationService,
    CombatPlaceTokenToolInput,
)
from app.domain.combat.attack_definitions import AttackDefinitionResolver
from app.domain.combat.board import PlaceCombatantInput
from app.domain.combat.lifecycle import (
    AddMonsterInput,
    ResolveInitiativeOrderInput,
    StartTacticalCombatInput,
)
from app.domain.combat.movement import (
    ConfirmMovementInput,
    MovementAnchorInput,
    MovementService,
    PreviewMovementInput,
)
from app.domain.combat.reaction_service import CombatReactionService, OpenReactionInput
from app.domain.combat.roll_compat import CombatAwareRollRepository
from app.domain.combat.spell_service import CombatSpellService
from app.domain.combat.target_check import (
    TargetCheckInput,
    TargetCheckResult,
    TargetCheckService,
)
from app.domain.rooms.ai_controller_tokens import mint_ai_controller_token
from app.domain.rooms.ai_controllers import (
    AIControllerService,
    AIControllerUnauthorizedError,
    AIHandoffRequest,
)
from app.domain.rooms.ai_guidance import render_briefing
from app.domain.rooms.character_rolls import CharacterRollModifierResolver
from app.domain.rooms.exploration import ExplorationStageService
from app.domain.rooms.rolls import RollService
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.sessions import SessionService
from app.domain.rooms.table_events import TableEventActorUnauthorizedError
from app.mcp.guide_tool_names import guide_tool_names
from app.mcp.tools import tool_catalog
from app.persistence.combat.reactions import CombatReactionRepository
from app.persistence.combat.spells import CombatSpellRepository
from app.persistence.combat.tables import combat_entries
from app.persistence.room_assets.repository import RoomAssetRepository
from app.persistence.rooms.ai_controllers import AIControllerGrantRepository
from app.persistence.rooms.exploration import ExplorationRepository
from app.persistence.rooms.exploration_subjects import ExplorationSubjectRepository
from app.persistence.rooms.sessions import SessionRepository
from app.persistence.rooms.tables import ai_controller_grants, campaign_seats, sessions
from sqlalchemy import insert, update
from tests.p5a_tactical_helpers import (
    TacticalTable,
    insert_battle_map,
    setup_tactical_table,
)

# ---------------------------------------------------------------------------
# Fixture wiring
# ---------------------------------------------------------------------------


def _running_table(
    *, monster_visibility: str = "public", monster_at: tuple[int, int] = (8, 8)
) -> tuple[TacticalTable, UUID, UUID]:
    table = setup_tactical_table()
    table.combat.start_tactical_combat(
        table.dm_actor, StartTacticalCombatInput(blank_width_cells=20, blank_height_cells=15)
    )
    char_entry = next(e.id for e in table.combat.get_active_combat(table.dm_actor).entries)
    instance = table.combat.monster_repository.create_quick_enemy(
        campaign_id=table.campaign_id, name="Goblin",
        armor_class=15, max_hp=7, speed={"walk": "30 ft."},
        visibility=monster_visibility,
    )
    table.combat.add_monster(table.dm_actor, AddMonsterInput(monster_instance_id=instance.id))
    monster_entry = next(
        e.id for e in table.combat.get_active_combat(table.dm_actor).entries
        if e.subject_kind == "monster"
    )
    table.board.place_position(
        table.dm_actor, char_entry, PlaceCombatantInput(anchor_x=1, anchor_y=1)
    )
    table.board.place_position(
        table.dm_actor, monster_entry, PlaceCombatantInput(anchor_x=monster_at[0], anchor_y=monster_at[1])
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
        table.dm_actor, ResolveInitiativeOrderInput(ordered_entry_ids=(char_entry, monster_entry))
    )
    return table, char_entry, monster_entry


def _ai_controller_service(table: TacticalTable) -> AIControllerService:
    return AIControllerService(AIControllerGrantRepository(table.engine), table.events)


def _facade(
    table: TacticalTable,
    *,
    reaction_service: object | None = None,
) -> CombatAIToolApplicationService:
    movement = MovementService(
        board_repository=table.board.board_repository,
        board_service=table.board,
        combat_service=table.combat,
    )
    target_check = TargetCheckService(
        table_event_service=table.events,
        combat_service=table.combat,
        board_service=table.board,
        attack_definition_resolver=AttackDefinitionResolver(
            table.characters, table.combat.monster_repository, table.registry
        ),
        monster_repository=table.combat.monster_repository,
        registry=table.registry,
    )
    battle_maps = BattleMapService(table.battle_maps, RoomAssetRepository(table.engine), table.events)
    spell_service = CombatSpellService(
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
            CharacterRollModifierResolver(table.combat.character_repository, table.registry),
        ),
        registry=table.registry,
        board_service=table.board,
    )
    if reaction_service is None:
        reaction_service = MagicMock()
        reaction_service.get_reaction_window.return_value = None
    core_rolls = MagicMock()
    core_rolls.list_pending_rolls.return_value = []
    adjudications = MagicMock()
    adjudications.list_pending.return_value = []
    rolls = MagicMock()
    rolls.list_requests.return_value = []
    pending = MagicMock()
    pending.list.return_value = []
    return CombatAIToolApplicationService(
        ai_controller_service=_ai_controller_service(table),
        session_service=SessionService(SessionRepository(table.engine), event_service=table.events),
        stage_service=ExplorationStageService(ExplorationRepository(table.engine), table.events),
        action_service=MagicMock(),
        roll_service=rolls,
        state_service=MagicMock(),
        pending_action_service=pending,
        event_service=table.events,
        workspace_service=MagicMock(),
        combat_service=table.combat,
        combat_attack_service=MagicMock(),
        combat_resolution_service=MagicMock(),
        combat_core_roll_service=core_rolls,
        combat_special_attack_service=MagicMock(),
        combat_initiative_service=MagicMock(),
        monster_instance_service=MagicMock(),
        combat_spell_service=spell_service,
        combat_concentration_service=MagicMock(),
        combat_reaction_service=reaction_service,
        combat_adjudication_service=adjudications,
        movement_service=movement,
        combat_board_service=table.board,
        battle_map_service=battle_maps,
        target_check_service=target_check,
    )


def _dm_token(table: TacticalTable) -> str:
    minted = mint_ai_controller_token()
    now = datetime.now(UTC)
    with table.engine.begin() as conn:
        conn.execute(
            insert(ai_controller_grants).values(
                id=minted.grant_id, room_id=table.room_id, campaign_id=table.campaign_id,
                seat_id=table.dm_actor.seat_id, role="dm", session_id=table.session_id,
                secret_hash=minted.secret_hash, secret_prefix=minted.display_hint,
                generation=1, status="active", pre_session_expires_at=None,
                handoff_return_access_session_id=None, temporary_instruction=None,
                created_at=now, bound_at=now, revoked_at=None, last_seen_at=None,
            )
        )
        conn.execute(
            update(campaign_seats)
            .where(campaign_seats.c.id == table.dm_actor.seat_id)
            .values(
                controller_kind="ai", ai_controller_grant_id=minted.grant_id,
                controller_epoch=1, controller_access_session_id=None, updated_at=now,
            )
        )
        conn.execute(
            update(sessions)
            .where(sessions.c.id == table.session_id)
            .values(
                dm_controller_kind="ai", dm_controller_ai_grant_id=minted.grant_id,
                dm_controller_generation=1, dm_controller_access_session_id=None,
            )
        )
    return minted.plaintext


def _player_token(table: TacticalTable) -> str:
    view = _ai_controller_service(table).let_ai_control_player(
        room_id=table.room_id, campaign_id=table.campaign_id, session_id=table.session_id,
        seat_id=table.player_actor.seat_id,
        context=RoomAccessContext(
            room_id=table.room_id,
            access_session_id=table.player_actor.access_session_id,
            authority=RoomAccessAuthority.MEMBER,
        ),
        request=AIHandoffRequest(),
    )
    return view.token


def _event_count(table: TacticalTable) -> int:
    from app.persistence.rooms.table_runtime import session_events
    from sqlalchemy import func, select

    with table.engine.connect() as conn:
        return int(conn.execute(select(func.count()).select_from(session_events)).scalar() or 0)


def _movement_path() -> tuple[MovementAnchorInput, ...]:
    # Every step must be cell-adjacent: (1,1) -> (2,1) -> (3,1), 10 ft total.
    return (
        MovementAnchorInput(x=1, y=1),
        MovementAnchorInput(x=2, y=1),
        MovementAnchorInput(x=3, y=1),
    )


# ---------------------------------------------------------------------------
# F.3 — authorization, subject binding, grant revalidation
# ---------------------------------------------------------------------------


def test_f3_player_previews_own_movement_without_spending_budget() -> None:
    table, char_entry, _ = _running_table()
    facade = _facade(table)
    preview = facade.combat_preview_movement(
        _player_token(table), PreviewMovementInput(entry_id=char_entry, path=_movement_path())
    )
    assert preview["valid"] is True
    assert preview["used_feet"] == 10
    status = facade.movement_service.movement_status(table.player_actor, char_entry)
    assert status.used_feet == 0
    assert status.remaining_feet == status.budget_feet


def test_f3_player_cannot_place_monster_token_with_zero_side_effects() -> None:
    table, _, monster_entry = _running_table()
    facade = _facade(table)
    token = _player_token(table)
    board_before = table.board.get_board(table.dm_actor).model_dump(mode="json")
    events_before = _event_count(table)
    with pytest.raises(TableEventActorUnauthorizedError):
        facade.combat_place_token(
            token,
            CombatPlaceTokenToolInput(entry_id=monster_entry, anchor_x=2, anchor_y=2),
        )
    assert table.board.get_board(table.dm_actor).model_dump(mode="json") == board_before
    assert _event_count(table) == events_before


def test_f3_dm_proxy_movement_consumes_subject_budget() -> None:
    table, char_entry, _ = _running_table()
    facade = _facade(table)
    token = _dm_token(table)
    status_before = facade.movement_service.movement_status(table.dm_actor, char_entry)
    preview = facade.combat_preview_movement(
        token, PreviewMovementInput(entry_id=char_entry, path=_movement_path())
    )
    assert preview["valid"] is True
    facade.combat_confirm_movement(
        token,
        ConfirmMovementInput(
            entry_id=char_entry, path=_movement_path(),
            expected_position_revision=preview["position_revision"],
            expected_board_revision=preview["board_revision"],
        ),
    )
    status_after = facade.movement_service.movement_status(table.dm_actor, char_entry)
    assert status_after.used_feet == status_before.used_feet + preview["used_feet"]


def test_f3_revoked_grant_rejected_with_zero_side_effects() -> None:
    table, _, _ = _running_table()
    facade = _facade(table)
    token = _dm_token(table)
    # Sanity: the grant works before revocation.
    facade.combat_get_board(token)
    events_before = _event_count(table)
    now = datetime.now(UTC)
    with table.engine.begin() as conn:
        conn.execute(
            update(ai_controller_grants)
            .where(ai_controller_grants.c.seat_id == table.dm_actor.seat_id)
            .values(status="revoked", revoked_at=now)
        )
    with pytest.raises(AIControllerUnauthorizedError):
        facade.combat_get_board(token)
    assert _event_count(table) == events_before


def test_f3_stale_epoch_rejected_with_zero_side_effects() -> None:
    table, char_entry, _ = _running_table()
    facade = _facade(table)
    token = _dm_token(table)
    facade.combat_get_board(token)
    events_before = _event_count(table)
    with table.engine.begin() as conn:
        conn.execute(
            update(campaign_seats)
            .where(campaign_seats.c.id == table.dm_actor.seat_id)
            .values(controller_epoch=2, updated_at=datetime.now(UTC))
        )
    with pytest.raises(AIControllerUnauthorizedError):
        facade.combat_preview_movement(
            token, PreviewMovementInput(entry_id=char_entry, path=_movement_path())
        )
    assert _event_count(table) == events_before


# ---------------------------------------------------------------------------
# F.4 — MCP catalog, tactical context, board/movement/target/aoe, wall secrecy
# ---------------------------------------------------------------------------

_ALL_ROLE_TACTICAL = {
    "combat_get_board",
    "combat_preview_movement",
    "combat_confirm_movement",
    "combat_resume_movement",
    "combat_check_target",
    "combat_preview_aoe",
}
_DM_ONLY_TACTICAL = {
    "combat_start_tactical",
    "combat_place_token",
    "combat_reposition",
    "combat_set_door_state",
    "combat_cancel_pending_movement",
}
_DM_ONLY_BATTLE_MAP = {
    "battle_map_get",
    "battle_map_list",
}


def _auth_view(role: str):
    from app.domain.rooms.ai_controllers import AIControllerAuthView

    return AIControllerAuthView(
        grant_id=UUID(int=0), room_id=UUID(int=0), campaign_id=UUID(int=0),
        seat_id=UUID(int=0), role=role, session_id=UUID(int=0), generation=1,
        active_character_id=None, is_current_dm=role == "dm",
        temporary_instruction=None,
    )


def test_f4_role_catalogs_split_all_role_and_dm_only_tools() -> None:
    player_catalog = {item["name"] for item in tool_catalog(_auth_view("player"))}
    dm_catalog = {item["name"] for item in tool_catalog(_auth_view("dm"))}
    assert _ALL_ROLE_TACTICAL <= player_catalog
    assert _DM_ONLY_TACTICAL.isdisjoint(player_catalog)
    assert _DM_ONLY_BATTLE_MAP.isdisjoint(player_catalog)
    assert (_ALL_ROLE_TACTICAL | _DM_ONLY_TACTICAL | _DM_ONLY_BATTLE_MAP) <= dm_catalog
    # Guide names resolve without catalog-shape drift.
    assert guide_tool_names() is not None


def test_f4_mcp_tactical_context_carries_board_and_budget() -> None:
    table, char_entry, _ = _running_table()
    facade = _facade(table)
    ctx = facade.get_session_context(_dm_token(table))
    assert ctx["mode"] == "active_session"
    combat = ctx["combat"]
    assert combat["round"] == 1
    assert combat["current_turn_entry_id"] is not None
    entries = combat["combat"]["entries"]
    assert any(e["id"] == str(char_entry) for e in entries)
    status = facade.movement_service.movement_status(table.dm_actor, char_entry)
    assert status.budget_feet > 0
    assert "combat_preview_movement" in ctx["briefing"]
    assert "next_required_action" in ctx


def test_f4_mcp_preview_aoe_returns_cells_and_candidates() -> None:
    from app.domain.combat.spell_service import AoeTemplateInput, PreviewAoeSpellInput

    table, char_entry, monster_entry = _running_table()
    facade = _facade(table)
    token = _player_token(table)
    events_before = _event_count(table)
    result = facade.combat_preview_aoe(
        token,
        PreviewAoeSpellInput(
            caster_entry_id=char_entry,
            spell_ref="srd5.1:spell:fireball",
            template=AoeTemplateInput(
                shape="circle", size_feet=20, origin_x=8, origin_y=8
            ),
        ),
    )
    assert result["affected_cells"], "fireball must cover cells"
    candidate_ids = {c["entry_id"] for c in result["candidates"]}
    assert str(monster_entry) in candidate_ids
    assert str(char_entry) not in candidate_ids  # ~35 ft away, outside the circle
    assert result["board_revision"] >= 1
    # Preview is read-only: no events written.
    assert _event_count(table) == events_before


def test_f4_target_check_route_human_rest_path() -> None:
    # The Human REST route delegates to the same TargetCheckService the MCP
    # facade uses; exercise the real route function end to end (actor built
    # from a real human access session, no TestClient needed).
    from app.api.rooms.combat_board import check_target as target_check_route
    from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext

    table, char_entry, monster_entry = _running_table(monster_at=(2, 1))
    resolver = AttackDefinitionResolver(
        table.characters, table.combat.monster_repository, table.registry
    )
    attack_ref = resolver.character_attacks(
        table.combat.repository.get_entry(char_entry)
    )[0].source_ref
    service = TargetCheckService(
        table_event_service=table.events,
        combat_service=table.combat,
        board_service=table.board,
        attack_definition_resolver=resolver,
        monster_repository=table.combat.monster_repository,
        registry=table.registry,
    )
    context = RoomAccessContext(
        room_id=table.room_id,
        access_session_id=table.dm_actor.access_session_id,
        authority=RoomAccessAuthority.DM,
        display_name="DM",
    )
    events_before = _event_count(table)
    result = target_check_route(
        room_id=table.room_id,
        campaign_id=table.campaign_id,
        session_id=table.session_id,
        payload=TargetCheckInput(
            source_entry_id=char_entry,
            target_entry_id=monster_entry,
            attack_source_ref=attack_ref,
        ),
        context=context,
        event_service=table.events,
        service=service,
    )
    assert isinstance(result, TargetCheckResult)
    assert result.legal is True
    assert result.in_range is True
    assert result.blocked is False
    # Read-only route: no events written.
    assert _event_count(table) == events_before


def test_f4_target_check_attack_in_range_not_blocked() -> None:
    # Longsword reach is 5 ft, so the monster stands adjacent to the character.
    table, char_entry, monster_entry = _running_table(monster_at=(2, 1))
    facade = _facade(table)
    resolver = AttackDefinitionResolver(
        table.characters, table.combat.monster_repository, table.registry
    )
    attack_ref = resolver.character_attacks(
        table.combat.repository.get_entry(char_entry)
    )[0].source_ref
    result = facade.combat_check_target(
        _dm_token(table),
        TargetCheckInput(
            source_entry_id=char_entry, target_entry_id=monster_entry,
            attack_source_ref=attack_ref,
        ),
    )
    assert result["legal"] is True
    assert result["in_range"] is True
    assert result["distance_feet"] is not None and result["distance_feet"] > 0
    assert result["blocked"] is False
    assert result["requires_dm_adjudication"] is False


def test_f4_target_check_spell_and_unknown_ref_rejected() -> None:
    table, char_entry, monster_entry = _running_table()
    facade = _facade(table)
    token = _dm_token(table)
    # Magic missile has 120 ft range; the monster is ~35 ft away (7 cells diagonal).
    near = facade.combat_check_target(
        token,
        TargetCheckInput(
            source_entry_id=char_entry, target_entry_id=monster_entry,
            spell_ref="srd5.1:spell:magic-missile",
        ),
    )
    assert near["kind"] == "spell"
    assert near["legal"] is True
    assert near["in_range"] is True
    # Unknown spell ref is rejected, not guessed.
    with pytest.raises(ContentNotFoundError):
        facade.combat_check_target(
            token,
            TargetCheckInput(
                source_entry_id=char_entry, target_entry_id=monster_entry,
                spell_ref="srd5.1:spell:does-not-exist",
            ),
        )


def test_f4_dm_wall_visibility_dm_only_and_player_payload_shape() -> None:
    table = setup_tactical_table()
    map_id = insert_battle_map(table)
    table.combat.start_tactical_combat(table.dm_actor, StartTacticalCombatInput(battle_map_id=map_id))
    dm_dump = [
        w.model_dump(mode="json") for w in table.board.get_board(table.dm_actor).walls
    ]
    player_dump = [
        w.model_dump(mode="json") for w in table.board.get_board(table.player_actor).walls
    ]
    # DM sees the hidden wall with its visibility marker.
    assert any(w.get("visibility") == "hidden" for w in dm_dump)
    assert any(w.get("visibility") == "public" for w in dm_dump)
    # Players never see a visibility key at all — payload shape is unchanged.
    assert all("visibility" not in w for w in player_dump)
    # The hidden wall itself is absent from the Player projection: players see
    # the unrevealed hidden door as a plain wall instead.
    assert not any(w["x1"] == 10 and w["y1"] == 10 for w in player_dump)


def test_f4_pending_reaction_surfaces_in_combat_context() -> None:
    table, char_entry, monster_entry = _running_table()
    reaction_service = CombatReactionService(
        CombatReactionRepository(table.engine, table.events.repository),
        table.combat.repository,
        table.combat,
        table.events,
    )
    window = reaction_service.open_reaction_window(
        table.dm_actor,
        OpenReactionInput(
            entry_id=char_entry, kind="opportunity_attack",
            reason="test", source_entry_id=monster_entry,
            eligible_entry_ids=(char_entry,),
        ),
    )
    assert window is not None
    facade = _facade(table, reaction_service=reaction_service)
    payload = facade._combat_context(table.player_actor)
    assert "reaction_windows" in payload
    assert any(w["entry_id"] == str(char_entry) for w in payload["reaction_windows"])


# ---------------------------------------------------------------------------
# F.5 — Human REST and AI MCP share the same MovementService path
# ---------------------------------------------------------------------------


def _movement_event_kinds(table: TacticalTable, before: int) -> list[str]:
    from app.persistence.rooms.table_runtime import session_events
    from sqlalchemy import select

    with table.engine.connect() as conn:
        rows = conn.execute(
            select(session_events.c.kind)
            .where(session_events.c.seq > before)
            .order_by(session_events.c.seq)
        ).all()
    return [row[0] for row in rows]


def test_f5_human_rest_and_ai_mcp_share_movement_service_path() -> None:
    path = _movement_path()

    # Path A: AI MCP through the facade.
    table_a, char_a, _ = _running_table()
    facade = _facade(table_a)
    movement_a = facade.movement_service
    token_a = _dm_token(table_a)
    ai_actor_a = facade._actor(token_a)
    events_before_a = _event_count(table_a)
    preview_a = facade.combat_preview_movement(
        token_a, PreviewMovementInput(entry_id=char_a, path=path)
    )
    facade.combat_confirm_movement(
        token_a,
        ConfirmMovementInput(
            entry_id=char_a, path=path,
            expected_position_revision=preview_a["position_revision"],
            expected_board_revision=preview_a["board_revision"],
        ),
    )
    kinds_a = _movement_event_kinds(table_a, events_before_a)

    # Path B: Human REST-equivalent direct service call on the same fixture shape.
    table_b, char_b, _ = _running_table()
    movement_b = MovementService(
        board_repository=table_b.board.board_repository,
        board_service=table_b.board,
        combat_service=table_b.combat,
    )
    events_before_b = _event_count(table_b)
    preview_b = movement_b.preview(
        table_b.player_actor, char_b, PreviewMovementInput(entry_id=char_b, path=path)
    )
    movement_b.confirm(
        table_b.player_actor, char_b,
        ConfirmMovementInput(
            entry_id=char_b, path=path,
            expected_position_revision=preview_b.position_revision,
            expected_board_revision=preview_b.board_revision,
        ),
    )
    kinds_b = _movement_event_kinds(table_b, events_before_b)

    # Same service class on both paths; identical budgets, costs, and event kinds.
    assert type(movement_a) is type(movement_b) is MovementService
    status_a = movement_a.movement_status(ai_actor_a, char_a)
    status_b = movement_b.movement_status(table_b.player_actor, char_b)
    assert (status_a.used_feet, status_a.remaining_feet) == (
        status_b.used_feet, status_b.remaining_feet,
    )
    assert preview_a["used_feet"] == preview_b.used_feet
    assert kinds_a == kinds_b
    assert kinds_a, "expected movement events on both paths"


# ---------------------------------------------------------------------------
# F.6 — tactical briefing bounds and content
# ---------------------------------------------------------------------------


def test_f6_tactical_briefing_under_3000_chars_both_roles() -> None:
    for role in ("dm", "player"):
        briefing = render_briefing(role=role, mode="active_tactical_combat")
        assert len(briefing) <= 3000, (role, len(briefing))


def test_f6_tactical_briefing_covers_tool_order_and_both_languages() -> None:
    en_zh = render_briefing(role="dm", mode="active_tactical_combat")
    for marker in (
        "combat_preview_movement",
        "combat_confirm_movement",
        "combat_check_target",
        "combat_preview_aoe",
        "structured",
    ):
        assert marker in en_zh
    # The tactical loop ships EN and zh-TW in one text; assert exact zh-TW
    # fragments from the tactical add-on, not a loose single-character match.
    for fragment in (
        "戰術補充：combat_preview_movement→combat_confirm_movement",
        "暫停：combat_resume_movement",
        "僅 DM：combat_cancel_pending_movement",
        "攻擊／施法前 combat_check_target",
        "AoE 前 combat_preview_aoe",
        "只用 structured cells",
    ):
        assert fragment in en_zh, fragment


def test_f6_active_tactical_combat_context_briefing_within_bounds() -> None:
    table, _, _ = _running_table()
    facade = _facade(table)
    for token, role in ((_dm_token(table), "dm"), (_player_token(table), "player")):
        ctx = facade.get_session_context(token)
        assert ctx["mode"] == "active_session"
        assert ctx["combat"] is not None
        briefing = ctx["briefing"]
        assert len(briefing) <= 3000, (role, len(briefing))
        assert "next_required_action" in ctx


# ---------------------------------------------------------------------------
# F.7 — bilingual descriptions and error codes
# ---------------------------------------------------------------------------

_NEW_TOOL_NAMES = sorted(
    _ALL_ROLE_TACTICAL | _DM_ONLY_TACTICAL | _DM_ONLY_BATTLE_MAP
)


def test_f7_new_tool_descriptions_bilingual_and_unique_when_to_use() -> None:
    from app.mcp.tools import _TOOL_DEFINITIONS, _WHEN_TO_USE

    definitions = {d.name: d for d in _TOOL_DEFINITIONS}
    seen_en: dict[str, str] = {}
    seen_zh: dict[str, str] = {}
    for name in _NEW_TOOL_NAMES:
        assert name in definitions, name
        assert name in _WHEN_TO_USE, name
        en, zh = _WHEN_TO_USE[name]
        assert en.strip() and zh.strip(), name
        assert en not in seen_en, (name, seen_en[en])
        assert zh not in seen_zh, (name, seen_zh[zh])
        seen_en[en] = name
        seen_zh[zh] = name
        desc = definitions[name].rich_description()
        assert "When to use:" in desc and "使用時機：" in desc, name
        assert len(desc) >= 80, name


def test_f7_battle_map_error_codes_bilingual() -> None:
    import asyncio
    from uuid import uuid4

    from app.mcp.tools import call_tool

    table, _, _ = _running_table()
    facade = _facade(table)
    dm_token = _dm_token(table)
    # M07-B: battle-map reads re-validate the live DM grant, so use a real
    # auth view rather than a synthetic one.
    dm_auth = facade._auth(dm_token)

    # not_found: reading a battle map that does not exist.
    missing = asyncio.run(
        call_tool(
            facade, token=dm_token, auth=dm_auth, name="battle_map_get",
            arguments={"map_id": str(uuid4())},
        )
    )
    missing_error = missing["structuredContent"]["error"]
    assert missing_error["code"] == "not_found"
    assert missing_error["messages"]["en"].strip()
    assert missing_error["messages"]["zh-TW"].strip()

    # permission_denied: a Player role may not call DM-only battle-map tools.
    denied = asyncio.run(
        call_tool(
            facade, token=dm_token, auth=_auth_view("player"), name="battle_map_list",
            arguments={},
        )
    )
    denied_error = denied["structuredContent"]["error"]
    assert denied_error["code"] == "permission_denied"
    assert denied_error["messages"]["en"].strip()
    assert denied_error["messages"]["zh-TW"].strip()
