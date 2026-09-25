from __future__ import annotations

from dataclasses import dataclass

from app.mcp.tools import tool_reference_rows


@dataclass(frozen=True)
class GuideToolNames:
    context: str
    start: str
    character_context: str
    dialogue: str
    action: str
    ooc: str
    whisper_dm: str
    narration: str
    stage_text: str
    request_check: str
    roll_pending: str
    physical_roll: str
    quick_roll: str
    character_state: str
    pending_events: str
    wait_event: str
    combat_context: str
    resolve_adjudication: str
    respond_reaction: str
    request_adjudication: str
    roll_concentration: str
    advance_turn: str
    adjudicate_attack: str
    adjudicate_special_attack: str
    resolve_aoe_spell: str
    apply_damage: str
    campaign_context: str
    adventure_entry: str
    set_current_context: str
    set_override: str
    create_world_entry: str


_EXPECTED = {
    "get_session_context",
    "start_session",
    "get_character_context",
    "post_dialogue",
    "post_action",
    "post_ooc",
    "whisper_dm",
    "post_narration",
    "set_stage_text",
    "request_check",
    "roll_pending",
    "submit_physical_roll",
    "quick_roll",
    "update_character_state",
    "get_pending_events",
    "wait_for_event",
    "combat_get_active",
    "combat_list_attacks",
    "combat_request_attack",
    "combat_adjudicate_attack",
    "combat_roll_attack",
    "combat_apply_damage",
    "combat_apply_healing",
    "combat_request_saving_throws",
    "combat_roll_saving_throw",
    "combat_request_death_save",
    "combat_roll_death_save",
    "combat_request_special_attack",
    "combat_adjudicate_special_attack",
    "combat_roll_special_attack",
    "combat_start",
    "combat_add_character",
    "combat_add_monster",
    "combat_create_monster",
    "combat_create_quick_enemy",
    "combat_list_monster_instances",
    "combat_update_monster_instance",
    "combat_request_initiative",
    "combat_finalize_initiative",
    "combat_advance_turn",
    "combat_end",
    "combat_remove_entry",
    "combat_roll_initiative",
    "combat_use_action",
    "combat_withdraw_entry",
    "combat_set_monster_outcome",
    "get_combat_context",
    "combat_cast_spell",
    "combat_propose_aoe_spell",
    "combat_resolve_aoe_spell",
    "combat_roll_concentration",
    "combat_drop_concentration",
    "combat_open_reaction_window",
    "combat_respond_to_reaction",
    "combat_request_opportunity_attack",
    "combat_request_adjudication",
    "combat_resolve_adjudication",
    "get_campaign_context",
    "get_scene_context",
    "search_campaign_context",
    "get_world_entry",
    "get_adventure_entry",
    "world_create_entry",
    "world_update_entry",
    "world_archive_entry",
    "world_set_override",
    "world_clear_override",
    "world_set_current_context",
    "world_grant_knowledge",
    "world_set_needs_review",
    "world_resolve_action",
    "set_stage_image",
    "import_adventure_source",
    "get_import_draft",
    "update_import_draft",
    "resolve_import_warning",
    "answer_import_question",
    "finalize_adventure",
}


def guide_tool_names() -> GuideToolNames:
    """Resolve guide-facing names by identity, never by catalog position."""

    available = {row["name"] for row in tool_reference_rows(None)}
    if available != _EXPECTED:
        missing = sorted(_EXPECTED - available)
        extra = sorted(available - _EXPECTED)
        raise RuntimeError(f"MCP tool catalog shape changed; missing={missing}, extra={extra}")
    return GuideToolNames(
        context="get_session_context",
        start="start_session",
        character_context="get_character_context",
        dialogue="post_dialogue",
        action="post_action",
        ooc="post_ooc",
        whisper_dm="whisper_dm",
        narration="post_narration",
        stage_text="set_stage_text",
        request_check="request_check",
        roll_pending="roll_pending",
        physical_roll="submit_physical_roll",
        quick_roll="quick_roll",
        character_state="update_character_state",
        pending_events="get_pending_events",
        wait_event="wait_for_event",
        combat_context="get_combat_context",
        resolve_adjudication="combat_resolve_adjudication",
        respond_reaction="combat_respond_to_reaction",
        request_adjudication="combat_request_adjudication",
        roll_concentration="combat_roll_concentration",
        advance_turn="combat_advance_turn",
        adjudicate_attack="combat_adjudicate_attack",
        adjudicate_special_attack="combat_adjudicate_special_attack",
        resolve_aoe_spell="combat_resolve_aoe_spell",
        apply_damage="combat_apply_damage",
        campaign_context="get_campaign_context",
        adventure_entry="get_adventure_entry",
        set_current_context="world_set_current_context",
        set_override="world_set_override",
        create_world_entry="world_create_entry",
    )


__all__ = ["GuideToolNames", "guide_tool_names"]
