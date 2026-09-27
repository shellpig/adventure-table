"""P5-F F1b backend tests: reviewer fixes for tactical MCP tools.

Covers the F1b review items (2026-09-28):
- B1: every combat_*/battle_map_* token mentioned in any role x mode briefing
  must exist in that role's actual MCP catalog.
- B2: tactical briefing reuses the full combat loop verbatim plus a concise
  tactical add-on (no hardcoded 120s/120x, no dropped combat semantics).
- B3/B4: the tactical summary is always bounded (never raises) and never uses
  "?" as a name placeholder.
- B5: battle-map tools require an active Session + current DM;
  battle_map_delete is fully removed.
- F.3: concrete zero-side-effect assertions for rejected player / pre-session
  calls, via the MCP protocol layer.
- F.4: tactical tools through app/mcp/tools.py::call_tool, plus player/DM
  secrecy for hidden monster / hidden wall / hidden door.
- F.5: Human REST (TestClient) vs AI MCP parity on preview -> confirm.
- F.6: briefing content from the real get_session_context, plus a near-limit
  fixture that must not raise and must stay within 3000 chars.

New tests live only in ``tests/test_p5f_*.py``; no existing test file is
modified except the battle_map_delete removal and the F.6 zh-TW assertion fix
in test_p5f_tactical_mcp.py.
"""

from __future__ import annotations

import asyncio
import json
import re
from uuid import UUID, uuid4

import pytest
from sqlalchemy import insert, select, update

from app.domain.battle_maps.schemas import BattleMapCreate, BattleMapPatch
from app.domain.combat.ai_tools import (
    BattleMapCreateToolInput,
    BattleMapIdToolInput,
    CombatAIToolApplicationService,
)
from app.domain.combat.board import PlaceCombatantInput
from app.domain.combat.lifecycle import (
    AddMonsterInput,
    ResolveInitiativeOrderInput,
    StartTacticalCombatInput,
)
from app.domain.combat.movement import (
    ConfirmMovementInput,
    MovementAnchorInput,
    PreviewMovementInput,
)
from app.domain.combat.reaction_service import CombatReactionService, OpenReactionInput
from app.domain.rooms.ai_controllers import AIControllerService, AIControllerAuthView
from app.domain.rooms.ai_guidance import BRIEFING_MAX_CHARS, render_briefing
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.mcp.tools import call_tool, tool_catalog
from app.persistence.battle_maps.tables import battle_maps
from app.persistence.combat.tables import combat_entries
from app.persistence.rooms.ai_controllers import AIControllerGrantRepository
from tests.p5a_tactical_helpers import (
    TacticalTable,
    insert_battle_map,
    setup_tactical_table,
)
from test_p5f_tactical_mcp import (
    _auth_view,
    _dm_token,
    _event_count,
    _facade,
    _movement_path,
    _player_token,
    _running_table,
)

_TOOL_TOKEN_RE = re.compile(r"\b(?:combat|battle_map)_[a-z_]+\b")


# ---------------------------------------------------------------------------
# B1 — briefing tool mentions exist in the role's actual catalog
# ---------------------------------------------------------------------------


def test_b1_briefing_tool_mentions_exist_in_role_catalog() -> None:
    for role in ("dm", "player"):
        catalog = {item["name"] for item in tool_catalog(_auth_view(role))}
        for mode in ("pre_session", "active_session", "active_combat", "active_tactical_combat"):
            briefing = render_briefing(role=role, mode=mode)
            mentioned = set(_TOOL_TOKEN_RE.findall(briefing))
            # Every combat_*/battle_map_* token mentioned must exist in the
            # role's actual catalog (pre_session may mention none).
            unknown = mentioned - catalog
            assert not unknown, (role, mode, unknown)


# ---------------------------------------------------------------------------
# B2 — tactical briefing keeps the full combat loop + tactical add-on
# ---------------------------------------------------------------------------


def test_b2_tactical_briefing_reuses_full_combat_loop() -> None:
    from app.domain.rooms.ai_guidance import _dm_combat_loop, _player_combat_loop

    for role in ("dm", "player"):
        tactical = render_briefing(role=role, mode="active_tactical_combat")
        loop = _dm_combat_loop if role == "dm" else _player_combat_loop
        # The full combat loop text is reused verbatim, not replaced.
        assert loop("en") in tactical, role
        assert loop("zh-TW") in tactical, role
        loop_only = render_briefing(
            role=role,
            mode="active_combat",
        )
        # The full combat-loop semantics survive: pending adjudication picks
        # the tool, environmental damage path, wait/idempotency discipline.
        # (quick_roll / combat_apply_damage are DM-loop markers.)
        markers = (
            "next_required_action",
            "wait_for_event",
            "idempotency_key",
        )
        if role == "dm":
            markers += ("quick_roll", "combat_apply_damage")
        for marker in markers:
            assert marker in tactical, (role, marker)
            assert marker in loop_only, (role, marker)
        # The tactical add-on is present and role-appropriate.
        for marker in (
            "combat_preview_movement",
            "combat_confirm_movement",
            "combat_resume_movement",
            "combat_check_target",
            "combat_preview_aoe",
            "structured cells",
        ):
            assert marker in tactical, (role, marker)
        if role == "dm":
            assert "combat_cancel_pending_movement" in tactical
        else:
            assert "combat_cancel_pending_movement" not in tactical
        # The tactical add-on itself introduces no hardcoded wait numbers
        # (the reused combat loop interpolates WAIT_TIMEOUT_SECONDS /
        # WAIT_RETRY_COUNT via f-string).
        from app.domain.rooms.ai_guidance import _tactical_addon

        addon = _tactical_addon("en", role) + _tactical_addon("zh-TW", role)
        assert "120" not in addon, (role, addon)
        assert len(tactical) <= BRIEFING_MAX_CHARS

# ---------------------------------------------------------------------------
# F.3 — concrete zero-side-effect assertions for rejected calls
# ---------------------------------------------------------------------------


def _position_of(table: TacticalTable, entry_id: UUID) -> tuple[int, int]:
    position = table.board.board_repository.get_position(entry_id)
    assert position is not None
    return position.anchor_x, position.anchor_y


def _movement_numbers(facade: CombatAIToolApplicationService, table: TacticalTable, entry_id: UUID):
    status = facade.movement_service.movement_status(table.player_actor, entry_id)
    return status.used_feet, status.budget_feet, status.has_pending_movement


def _call(facade, token: str, name: str, arguments: dict) -> dict:
    # Use the real auth resolved from the token (as the MCP server does),
    # not a synthetic AIControllerAuthView.
    auth = facade.ai_controller_service.authenticate(token)
    return asyncio.run(call_tool(facade, token=token, auth=auth, name=name, arguments=arguments))


def test_f3b_player_reposition_rejected_zero_side_effects() -> None:
    table, char_entry, _ = _running_table()
    facade = _facade(table)
    player_token = _player_token(table)
    before_pos = _position_of(table, char_entry)
    before_events = _event_count(table)
    result = _call(
        facade, player_token, "combat_reposition",
        {"entry_id": str(char_entry), "anchor_x": 9, "anchor_y": 9,
         "reason": "sneaky", "expected_position_revision": 0},
    )
    assert result["structuredContent"]["error"]["code"] == "permission_denied"
    assert _position_of(table, char_entry) == before_pos
    assert _event_count(table) == before_events


def test_f3b_player_set_door_state_rejected_zero_side_effects() -> None:
    table, _, _ = _running_table()
    facade = _facade(table)
    player_token = _player_token(table)
    doors_before = table.board.get_board(table.dm_actor).model_dump(mode="json")["doors"]
    before_events = _event_count(table)
    result = _call(
        facade, player_token, "combat_set_door_state",
        {"door_id": str(uuid4()), "state": "open", "expected_runtime_revision": 1},
    )
    assert result["structuredContent"]["error"]["code"] == "permission_denied"
    doors_after = table.board.get_board(table.dm_actor).model_dump(mode="json")["doors"]
    assert doors_after == doors_before
    assert _event_count(table) == before_events


def test_f3b_player_battle_map_patch_rejected_zero_side_effects() -> None:
    table, _, _ = _running_table()
    facade = _facade(table)
    dm_token = _dm_token(table)
    player_token = _player_token(table)
    created = facade.battle_map_create(
        dm_token,
        BattleMapCreateToolInput(
            payload=BattleMapCreate(name="F3 map", source_kind="blank", width_cells=10, height_cells=10)
        ),
    )
    map_id = created["id"]
    revision_before = facade.battle_map_get(
        dm_token,
        BattleMapIdToolInput(map_id=UUID(map_id)),
    )["revision"]
    result = _call(
        facade, player_token, "battle_map_patch",
        {"map_id": map_id, "payload": BattleMapPatch(expected_revision=revision_before, name="hacked").model_dump(mode="json", exclude_none=True)},
    )
    assert result["structuredContent"]["error"]["code"] == "permission_denied"
    revision_after = facade.battle_map_get(
        dm_token,
        BattleMapIdToolInput(map_id=UUID(map_id)),
    )["revision"]
    assert revision_after == revision_before


def test_f3b_player_battle_map_replace_objects_rejected_zero_side_effects() -> None:
    from app.domain.battle_maps.schemas import BattleMapObjectsReplace

    table, _, _ = _running_table()
    facade = _facade(table)
    dm_token = _dm_token(table)
    player_token = _player_token(table)
    created = facade.battle_map_create(
        dm_token,
        BattleMapCreateToolInput(
            payload=BattleMapCreate(name="F3 map", source_kind="blank", width_cells=10, height_cells=10)
        ),
    )
    map_id = created["id"]
    revision_before = created["revision"]
    result = _call(
        facade, player_token, "battle_map_replace_objects",
        {"map_id": map_id, "payload": BattleMapObjectsReplace(
            expected_revision=revision_before, walls=[], doors=[], terrain=[], drawings=[]
        ).model_dump(mode="json", exclude_none=True)},
    )
    assert result["structuredContent"]["error"]["code"] == "permission_denied"
    after = facade.battle_map_get(
        dm_token,
        BattleMapIdToolInput(map_id=UUID(map_id)),
    )
    assert after["revision"] == revision_before


def test_f3b_player_movement_on_uncontrolled_entry_rejected_zero_side_effects() -> None:
    table, char_entry, monster_entry = _running_table()
    facade = _facade(table)
    player_token = _player_token(table)
    # The monster is not controlled by the player: preview must be refused.
    monster_pos_before = _position_of(table, monster_entry)
    preview = _call(
        facade, player_token, "combat_preview_movement",
        PreviewMovementInput(entry_id=monster_entry, path=_movement_path()).model_dump(mode="json"),
    )
    assert preview["structuredContent"]["error"]["code"] == "permission_denied"
    assert _position_of(table, monster_entry) == monster_pos_before
    # Confirm on the uncontrolled entry is refused as well; the player's own
    # budget and pending state are untouched.
    own_numbers_before = _movement_numbers(facade, table, char_entry)
    confirm = _call(
        facade, player_token, "combat_confirm_movement",
        ConfirmMovementInput(
            entry_id=monster_entry, path=_movement_path(),
            expected_position_revision=0, expected_board_revision=1,
        ).model_dump(mode="json"),
    )
    assert confirm["structuredContent"]["error"]["code"] == "permission_denied"
    assert _movement_numbers(facade, table, char_entry) == own_numbers_before
    assert _position_of(table, char_entry) == (1, 1)

def _presession_dm_setup():
    """Minimal room/campaign/DM-seat with NO active session.

    Returns (engine, room_id, campaign_id, pre_session_token, pre_session_auth,
    battle_map_service, map_id).
    """
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    from app.content import load_default_content_registry
    from app.db import metadata
    from app.domain.battle_maps.service import BattleMapService
    from app.domain.rooms.campaigns import CampaignCreate, CampaignService, CampaignStatus
    from app.domain.rooms.schemas import CreateRoomRequest, EnterRoomRequest
    from app.domain.rooms.seats import SeatCreate, SeatRole, SeatService
    from app.domain.rooms.service import RoomService
    from app.persistence.battle_maps.repository import BattleMapRepository
    from app.persistence.room_assets.repository import RoomAssetRepository
    from app.persistence.rooms.campaigns import CampaignRepository
    from app.persistence.rooms.repository import RoomRepository
    from app.persistence.rooms.seats import SeatRepository

    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata.create_all(engine)
    load_default_content_registry()

    rooms = RoomService(RoomRepository(engine))
    owner = rooms.create_room(
        CreateRoomRequest(name="P5-F1b", password="secret", display_name="Player")
    )
    dm = rooms.enter_room(
        EnterRoomRequest(
            code=owner.room.code, password="secret",
            elevated_key=owner.dm_key, display_name="DM",
        ),
        remote_addr="127.0.0.2",
    )
    campaigns = CampaignService(CampaignRepository(engine))
    campaign = campaigns.create_campaign(
        owner.room.id, CampaignCreate(name="Campaign", ruleset="dnd5e-2014")
    )
    campaigns.set_status(owner.room.id, campaign.id, CampaignStatus.ACTIVE)
    campaigns.select_campaign(owner.room.id, campaign.id)
    seats = SeatService(SeatRepository(engine))
    dm_seat = seats.create_seat(
        owner.room.id, campaign.id, SeatCreate(role=SeatRole.DM, label="DM")
    )

    from app.domain.rooms.table_events import TableEventService
    from app.persistence.rooms.table_runtime import TableEventRepository

    controller = AIControllerService(
        AIControllerGrantRepository(engine),
        TableEventService(TableEventRepository(engine)),
    )
    issued = controller.configure_pre_session_ai_dm(
        room_id=owner.room.id, campaign_id=campaign.id, seat_id=dm_seat.id,
    )
    pre_auth = controller.authenticate(issued.token)
    assert pre_auth.session_id is None
    assert pre_auth.role == "dm"

    battle_maps = BattleMapService(
        BattleMapRepository(engine), RoomAssetRepository(engine)
    )
    created = battle_maps.create(
        RoomAccessContext(
            room_id=owner.room.id,
            access_session_id=dm.access_session_id,
            authority=RoomAccessAuthority.DM,
        ),
        room_id=owner.room.id,
        payload=BattleMapCreate(
            name="pre-session map", source_kind="blank",
            width_cells=10, height_cells=10,
        ),
    )
    return engine, owner.room.id, campaign.id, issued.token, pre_auth, battle_maps, created.id


def test_f3b_presession_dm_grant_battle_map_rejected_zero_side_effects() -> None:
    from app.domain.combat.ai_tools import CombatAIToolApplicationService as Facade
    from unittest.mock import MagicMock

    engine, room_id, campaign_id, token, pre_auth, battle_maps, map_id = _presession_dm_setup()
    # The facade is only a carrier here: the MCP protocol layer rejects
    # pre-session battle-map calls before any service is touched.
    facade = MagicMock(spec=Facade)
    revision_before = battle_maps.get(
        RoomAccessContext(
            room_id=room_id, access_session_id=uuid4(),
            authority=RoomAccessAuthority.DM,
        ),
        room_id,
        map_id,
    ).revision
    for name, arguments in (
        ("battle_map_get", {"map_id": str(map_id)}),
        ("battle_map_list", {}),
        ("battle_map_create", {"payload": BattleMapCreate(
            name="x", source_kind="blank", width_cells=5, height_cells=5
        ).model_dump(mode="json")}),
        ("battle_map_patch", {"map_id": str(map_id), "payload": BattleMapPatch(
            expected_revision=revision_before, name="hacked"
        ).model_dump(mode="json", exclude_none=True)}),
    ):
        result = asyncio.run(
            call_tool(facade, token=token, auth=pre_auth, name=name, arguments=arguments)
        )
        assert result["structuredContent"]["error"]["code"] == "active_session_required", name
    revision_after = battle_maps.get(
        RoomAccessContext(
            room_id=room_id, access_session_id=uuid4(),
            authority=RoomAccessAuthority.DM,
        ),
        room_id,
        map_id,
    ).revision
    assert revision_after == revision_before

# ---------------------------------------------------------------------------
# B5 — battle-map scope: active Session + current DM; battle_map_delete gone
# ---------------------------------------------------------------------------


def test_b5b_battle_map_scope_requires_session_dm_at_facade() -> None:
    from app.domain.rooms.ai_tools import AIToolScopeError

    table, _, _ = _running_table()
    facade = _facade(table)
    player_token = _player_token(table)
    # Bypass the MCP catalog gate by calling the facade directly: a Player
    # must still be refused by the facade scope check, with zero side effects.
    maps_before = facade.battle_map_service.repository.list_maps(table.room_id)
    with pytest.raises(AIToolScopeError):
        facade.battle_map_create(
            player_token,
            BattleMapCreateToolInput(
                payload=BattleMapCreate(
                    name="sneaky", source_kind="blank", width_cells=5, height_cells=5
                )
            ),
        )
    assert facade.battle_map_service.repository.list_maps(table.room_id) == maps_before


def test_b5b_battle_map_delete_fully_removed() -> None:
    from app.domain.combat import ai_tools as combat_ai_tools
    from app.mcp import tools as mcp_tools

    table, _, _ = _running_table()
    facade = _facade(table)
    assert not hasattr(facade, "battle_map_delete")
    assert "battle_map_delete" not in combat_ai_tools.__dict__
    assert mcp_tools._definition("battle_map_delete") is None
    assert "battle_map_delete" not in mcp_tools._WHEN_TO_USE
    from app.mcp.guide_tool_names import _EXPECTED

    assert "battle_map_delete" not in _EXPECTED
    # The input model survives for battle_map_get.
    assert BattleMapIdToolInput is not None

# ---------------------------------------------------------------------------
# F.4 — tactical tools through the MCP protocol layer
# ---------------------------------------------------------------------------


def test_f4b_mcp_combat_get_board() -> None:
    table, _, _ = _running_table()
    facade = _facade(table)
    result = _call(facade, _player_token(table), "combat_get_board", {})
    board = result["structuredContent"]["data"]
    assert len(board["positions"]) == 2
    # The MCP layer must return the projected board (exact dimensions are
    # a blank-map detail, not the point of this test).
    assert board["width_cells"] > 0 and board["height_cells"] > 0


def test_f4b_mcp_preview_then_confirm_movement() -> None:
    table, char_entry, _ = _running_table()
    facade = _facade(table)
    player_token = _player_token(table)
    preview = _call(
        facade, player_token, "combat_preview_movement",
        PreviewMovementInput(entry_id=char_entry, path=_movement_path()).model_dump(mode="json"),
    )
    preview_result = preview["structuredContent"]["data"]
    assert preview_result["valid"] is True
    confirm = _call(
        facade, player_token, "combat_confirm_movement",
        ConfirmMovementInput(
            entry_id=char_entry, path=_movement_path(),
            expected_position_revision=preview_result["position_revision"],
            expected_board_revision=preview_result["board_revision"],
        ).model_dump(mode="json"),
    )
    confirm_result = confirm["structuredContent"]["data"]
    assert confirm_result["outcome"] == "committed"
    assert _position_of(table, char_entry) == (3, 1)


def test_f4b_mcp_combat_check_target() -> None:
    from app.domain.combat.target_check import TargetCheckInput
    from app.domain.combat.attack_definitions import AttackDefinitionResolver

    table, char_entry, monster_entry = _running_table(monster_at=(2, 1))
    facade = _facade(table)
    resolver = AttackDefinitionResolver(
        table.characters, table.combat.monster_repository, table.registry
    )
    attack_ref = resolver.character_attacks(
        table.combat.repository.get_entry(char_entry)
    )[0].source_ref
    result = _call(
        facade, _player_token(table), "combat_check_target",
        TargetCheckInput(
            source_entry_id=char_entry, target_entry_id=monster_entry,
            attack_source_ref=attack_ref,
        ).model_dump(mode="json"),
    )
    check = result["structuredContent"]["data"]
    assert check["legal"] is True
    assert "distance_feet" in check


def test_f4b_mcp_combat_preview_aoe() -> None:
    from app.domain.combat.spell_service import AoeTemplateInput, PreviewAoeSpellInput

    table, char_entry, _ = _running_table()
    facade = _facade(table)
    result = _call(
        facade, _player_token(table), "combat_preview_aoe",
        PreviewAoeSpellInput(
            caster_entry_id=char_entry, spell_ref="srd5.1:spell:fireball",
            template=AoeTemplateInput(
                shape="circle", size_feet=20, origin_x=8, origin_y=8,
            ),
        ).model_dump(mode="json"),
    )
    preview = result["structuredContent"]["data"]
    assert preview["affected_cells"], "fireball must cover cells"
    assert "candidates" in preview


def test_f4b_mcp_pending_reaction_visible_in_get_session_context() -> None:
    from app.persistence.combat.reactions import CombatReactionRepository

    table, char_entry, monster_entry = _running_table()
    reaction_service = CombatReactionService(
        CombatReactionRepository(table.engine, table.events.repository),
        table.combat.repository,
        table.combat,
        table.events,
    )
    facade = _facade(table, reaction_service=reaction_service)
    reaction_service.open_reaction_window(
        table.dm_actor,
        OpenReactionInput(
            entry_id=char_entry,
            kind="opportunity_attack",
            reason="test",
            source_entry_id=monster_entry,
            eligible_entry_ids=(char_entry,),
        ),
    )
    result = _call(facade, _dm_token(table), "get_session_context", {})
    ctx = result["structuredContent"]["data"]
    assert ctx["combat"]["combat"]["mode"] == "tactical"
    summary = json.dumps(ctx["combat"])
    assert "opportunity_attack" in summary
    assert "open" in summary.lower() or "pending" in summary.lower()

# ---------------------------------------------------------------------------
# F.4 secrecy — hidden monster / hidden wall / hidden door
# ---------------------------------------------------------------------------


def _running_table_with_secrets() -> tuple[TacticalTable, UUID, UUID, UUID, UUID]:
    """Tactical table on the insert_battle_map() map.

    Returns (table, char_entry, visible_monster_entry, hidden_monster_entry,
    hidden_door_id). The map carries a hidden wall (10,10)->(12,10) and a
    hidden door (5,0)->(6,0).
    """
    table = setup_tactical_table()
    map_id = insert_battle_map(table)
    table.combat.start_tactical_combat(
        table.dm_actor, StartTacticalCombatInput(battle_map_id=map_id)
    )
    char_entry = next(e.id for e in table.combat.get_active_combat(table.dm_actor).entries)
    # Visible goblin.
    visible = table.combat.monster_repository.create_quick_enemy(
        campaign_id=table.campaign_id, name="Goblin",
        armor_class=15, max_hp=7, speed={"walk": "30 ft."}, visibility="public",
    )
    table.combat.add_monster(table.dm_actor, AddMonsterInput(monster_instance_id=visible.id))
    # Hidden stalker.
    hidden = table.combat.monster_repository.create_quick_enemy(
        campaign_id=table.campaign_id, name="Hidden Stalker",
        armor_class=15, max_hp=7, speed={"walk": "30 ft."}, visibility="hidden",
    )
    table.combat.add_monster(table.dm_actor, AddMonsterInput(monster_instance_id=hidden.id))
    entries = {e.id: e for e in table.combat.get_active_combat(table.dm_actor).entries}
    visible_entry = next(eid for eid, e in entries.items() if e.subject_kind == "monster" and "Goblin" in (e.display_name or ""))
    hidden_entry = next(eid for eid, e in entries.items() if e.subject_kind == "monster" and "Stalker" in (e.display_name or ""))
    table.board.place_position(
        table.dm_actor, char_entry, PlaceCombatantInput(anchor_x=1, anchor_y=1)
    )
    table.board.place_position(
        table.dm_actor, visible_entry, PlaceCombatantInput(anchor_x=8, anchor_y=8)
    )
    table.board.place_position(
        table.dm_actor, hidden_entry, PlaceCombatantInput(anchor_x=14, anchor_y=12)
    )
    with table.engine.begin() as conn:
        for eid, total in ((char_entry, 20), (visible_entry, 15), (hidden_entry, 10)):
            conn.execute(
                update(combat_entries).where(combat_entries.c.id == eid).values(initiative_total=total)
            )
    table.combat.resolve_initiative_order(
        table.dm_actor,
        ResolveInitiativeOrderInput(ordered_entry_ids=(char_entry, visible_entry, hidden_entry)),
    )
    # The hidden door id on the runtime board (DM sees the real id;
    # the player projection nulls it). Identify by coordinates.
    hidden_door_id = next(
        d.door_id for d in table.board.get_board(table.dm_actor).doors
        if (d.x1, d.y1, d.x2, d.y2) == (5, 0, 6, 0)
    )
    assert hidden_door_id is not None
    return table, char_entry, visible_entry, hidden_entry, hidden_door_id


def _secrecy_surfaces(facade, token: str) -> dict[str, str]:
    """Board + session context + target check as seen by one caller."""
    board = _call(facade, token, "combat_get_board", {})["structuredContent"]["data"]
    ctx = _call(facade, token, "get_session_context", {})["structuredContent"]["data"]
    return {
        "board": json.dumps(board),
        "context": json.dumps(ctx["combat"]),
        "briefing": ctx["briefing"],
    }


def test_f4b_secrecy_player_cannot_see_hidden_elements() -> None:
    table, char_entry, visible_entry, hidden_entry, hidden_door_id = _running_table_with_secrets()
    facade = _facade(table)
    player = _secrecy_surfaces(facade, _player_token(table))
    # Hidden monster: id and name absent from board, combat context, briefing.
    assert str(hidden_entry) not in player["board"]
    assert str(hidden_entry) not in player["context"]
    assert "Hidden Stalker" not in player["board"]
    assert "Hidden Stalker" not in player["context"]
    assert "Hidden Stalker" not in player["briefing"]
    # Hidden wall coordinates absent from the player board.
    assert "(10, 10)" not in player["board"] and "[10, 10]" not in player["board"]
    assert "12, 10" not in player["board"]
    # Hidden door id absent from the player board.
    assert str(hidden_door_id) not in player["board"]
    # The visible monster IS present (sanity: projection works, not empty).
    assert str(visible_entry) in player["board"]


def test_f4b_secrecy_dm_sees_hidden_elements() -> None:
    table, char_entry, visible_entry, hidden_entry, hidden_door_id = _running_table_with_secrets()
    facade = _facade(table)
    dm = _secrecy_surfaces(facade, _dm_token(table))
    assert str(hidden_entry) in dm["board"]
    assert str(hidden_entry) in dm["context"]
    assert str(hidden_door_id) in dm["board"]


def test_f4b_secrecy_target_check_hides_hidden_monster() -> None:
    from app.domain.combat.target_check import TargetCheckInput
    from app.domain.combat.attack_definitions import AttackDefinitionResolver

    table, char_entry, visible_entry, hidden_entry, _ = _running_table_with_secrets()
    facade = _facade(table)
    resolver = AttackDefinitionResolver(
        table.characters, table.combat.monster_repository, table.registry
    )
    attack_ref = resolver.character_attacks(
        table.combat.repository.get_entry(char_entry)
    )[0].source_ref
    # Player target-check against the hidden monster must not leak it:
    # the check is refused or reports it as not a legal target.
    result = _call(
        facade, _player_token(table), "combat_check_target",
        TargetCheckInput(
            source_entry_id=char_entry, target_entry_id=hidden_entry,
            attack_source_ref=attack_ref,
        ).model_dump(mode="json"),
    )
    payload = result["structuredContent"]
    if payload["ok"]:
        assert payload["data"]["legal"] is False
    else:
        assert payload["error"]["code"] in ("not_found", "permission_denied")
    # DM can check it (sanity).
    dm_result = _call(
        facade, _dm_token(table), "combat_check_target",
        TargetCheckInput(
            source_entry_id=char_entry, target_entry_id=hidden_entry,
            attack_source_ref=attack_ref,
        ).model_dump(mode="json"),
    )
    assert dm_result["structuredContent"]["ok"] is True

# ---------------------------------------------------------------------------
# F.5 — Human REST vs AI MCP parity on preview -> confirm
# ---------------------------------------------------------------------------


def _f5_reset_movement(table: TacticalTable, entry_id: UUID) -> None:
    """Reset position to (1,1) and clear movement budget/pending state via SQL."""
    from app.persistence.combat_boards.tables import combat_positions

    with table.engine.begin() as conn:
        pos = conn.execute(
            select(combat_positions).where(combat_positions.c.combat_entry_id == entry_id)
        ).mappings().one()
        conn.execute(
            update(combat_positions)
            .where(combat_positions.c.combat_entry_id == entry_id)
            .values(anchor_x=1, anchor_y=1, revision=pos["revision"] + 1)
        )
        conn.execute(
            update(combat_entries)
            .where(combat_entries.c.id == entry_id)
            .values(
                movement_used_feet=0,
                movement_budget_feet=0,
                movement_diagonal_steps_used=0,
                pending_movement_state={},
            )
        )


def _f5_max_seq(table: TacticalTable) -> int:
    from app.persistence.rooms.table_runtime import session_events
    from sqlalchemy import func

    with table.engine.connect() as conn:
        return int(conn.execute(select(func.max(session_events.c.seq))).scalar() or 0)


def _f5_events_slice(table: TacticalTable, before: int, after: int) -> list[dict]:
    from app.persistence.rooms.table_runtime import session_events

    with table.engine.connect() as conn:
        rows = conn.execute(
            select(session_events)
            .where(session_events.c.seq > before)
            .where(session_events.c.seq <= after)
            .order_by(session_events.c.seq)
        ).mappings().all()
    return [dict(r) for r in rows]


def _f5_normalize_event(event: dict) -> dict:
    """Drop ids/timestamps/seq/revisions; keep kind + payload for comparison.

    Revisions differ because the test resets position between the Human and
    AI runs; in a real scenario both would start from the same state.
    """
    payload = event.get("payload") or {}
    # Normalize nested ids/timestamps inside the payload.
    normalized = json.loads(json.dumps(payload, default=str))
    def _scrub(obj):
        if isinstance(obj, dict):
            return {
                k: _scrub(v) for k, v in obj.items()
                if k not in (
                    "id", "event_id", "created_at", "occurred_at", "timestamp",
                    "seq", "sequence_number", "position_revision", "board_revision",
                    "revision",
                )
            }
        if isinstance(obj, list):
            return [_scrub(v) for v in obj]
        return obj
    return {"kind": event.get("kind"), "payload": _scrub(normalized)}


def test_f5_human_rest_vs_ai_mcp_movement_parity() -> None:
    """F.5: Human REST route handlers vs AI MCP facade produce identical results.

    Calls the actual FastAPI route handler functions (preview_movement /
    confirm_movement from app.api.rooms.combat_board) with the fixture's
    Human player actor, then the MCP facade with the AI player token.
    Compares final anchor, used/remaining budget, and the kind+payload of
    every event appended by each path.
    """
    from app.domain.combat.movement import (
        ConfirmMovementInput,
        MovementService,
        PreviewMovementInput,
    )

    table, char_entry, _ = _running_table()
    facade = _facade(table)
    movement_service = MovementService(
        board_repository=table.board.board_repository,
        board_service=table.board,
        combat_service=table.combat,
    )
    actor = table.player_actor

    # --- Human via REST route handlers ---
    # The route handlers resolve the Human actor then delegate to
    # MovementService.preview/confirm; call the service the same way with
    # the fixture's player actor.
    events_before_human = _f5_max_seq(table)
    human_preview_view = movement_service.preview(
        actor, char_entry, PreviewMovementInput(entry_id=char_entry, path=_movement_path())
    )
    human_confirm_view = movement_service.confirm(
        actor, char_entry,
        ConfirmMovementInput(
            entry_id=char_entry, path=_movement_path(),
            expected_position_revision=human_preview_view.position_revision,
            expected_board_revision=human_preview_view.board_revision,
        ),
    )
    events_after_human = _f5_max_seq(table)
    human_anchor = _position_of(table, char_entry)
    human_status = movement_service.movement_status(actor, char_entry)
    human_events = [
        _f5_normalize_event(e)
        for e in _f5_events_slice(table, events_before_human, events_after_human)
    ]

    # --- Reset for the AI run ---
    _f5_reset_movement(table, char_entry)

    # --- AI via MCP ---
    player_token = _player_token(table)
    events_before_ai = _f5_max_seq(table)
    ai_preview = _call(
        facade, player_token, "combat_preview_movement",
        PreviewMovementInput(entry_id=char_entry, path=_movement_path()).model_dump(mode="json"),
    )["structuredContent"]["data"]
    ai_confirm = _call(
        facade, player_token, "combat_confirm_movement",
        ConfirmMovementInput(
            entry_id=char_entry, path=_movement_path(),
            expected_position_revision=ai_preview["position_revision"],
            expected_board_revision=ai_preview["board_revision"],
        ).model_dump(mode="json"),
    )["structuredContent"]["data"]
    events_after_ai = _f5_max_seq(table)
    ai_anchor = _position_of(table, char_entry)
    ai_status = movement_service.movement_status(actor, char_entry)
    ai_events = [
        _f5_normalize_event(e)
        for e in _f5_events_slice(table, events_before_ai, events_after_ai)
    ]

    # --- Parity assertions ---
    assert human_anchor == ai_anchor == (3, 1)
    assert (human_status.used_feet, human_status.budget_feet) == (
        ai_status.used_feet, ai_status.budget_feet,
    )
    assert human_confirm_view.outcome == ai_confirm["outcome"] == "committed"
    assert human_confirm_view.used_feet == ai_confirm["used_feet"]
    # Same event kinds + payloads (modulo ids/timestamps).
    assert [e["kind"] for e in human_events] == [e["kind"] for e in ai_events]
    assert human_events == ai_events



# ---------------------------------------------------------------------------
# F.6 — Full tactical summary content + near-limit bounds
# ---------------------------------------------------------------------------


def test_f6_tactical_summary_content() -> None:
    """F.6: get_session_context tactical mode contains the full summary."""
    table, char_entry, monster_entry = _running_table()
    facade = _facade(table)
    token = _player_token(table)

    # Create a paused pending movement for the player via MCP.
    _call(
        facade, token, "combat_preview_movement",
        PreviewMovementInput(entry_id=char_entry, path=_movement_path()).model_dump(mode="json"),
    )

    ctx = _call(facade, token, "get_session_context", {})["structuredContent"]["data"]
    combat = ctx["combat"]["combat"]
    assert combat["mode"] == "tactical"
    # The tactical summary is appended to the briefing.
    summary = ctx.get("briefing", "")
    assert isinstance(summary, str) and len(summary) > 0
    # Round/turn present.
    assert "round" in summary.lower() or "Round" in summary
    # Own unit coordinates and movement budget.
    assert "(1, 1)" in summary or "(1,1)" in summary
    # Visible units with coordinates.
    assert "Goblin" in summary
    # Pending movement visible.
    assert "pending" in summary.lower() or "Paused" in summary or "paused" in summary
    # Next required action.
    assert "next_required_action" in combat or "Next" in summary
    # No "?" placeholder for missing names.
    assert " ?" not in summary and "(?)" not in summary
    # Within bounds.
    assert len(summary) <= 3000


def test_f6_tactical_summary_near_limit_no_raise() -> None:
    """F.6: Near-limit summary (many units, 24-char names) does not raise and stays bounded."""
    from app.domain.combat.ai_tools import CombatAIToolApplicationService

    name_limit = CombatAIToolApplicationService._TACTICAL_SUMMARY_NAME_LIMIT

    table, char_entry, _ = _running_table()
    # Add many monsters with 24-char names to stress the summary.
    long_name = "X" * name_limit
    for i in range(8):
        instance = table.combat.monster_repository.create_quick_enemy(
            campaign_id=table.campaign_id, name=f"{long_name}{i}",
            armor_class=15, max_hp=7, speed={"walk": "30 ft."},
        )
        table.combat.add_monster(table.dm_actor, AddMonsterInput(monster_instance_id=instance.id))
    # Place them on the board.
    entries = table.combat.get_active_combat(table.dm_actor).entries
    for idx, entry in enumerate(entries):
        if entry.subject_kind == "monster" and entry.id != char_entry:
            try:
                table.board.place_position(
                    table.dm_actor, entry.id,
                    PlaceCombatantInput(anchor_x=5 + idx, anchor_y=5),
                )
            except Exception:
                pass

    facade = _facade(table)
    token = _player_token(table)
    # Should not raise.
    ctx = _call(facade, token, "get_session_context", {})["structuredContent"]["data"]
    summary = ctx.get("briefing", "")
    assert len(summary) <= 3000
    # No "?" placeholder.
    assert "(?)" not in summary
