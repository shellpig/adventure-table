from __future__ import annotations

from app.domain.rooms.ai_guidance import render_briefing


def test_pre_session_dm_briefing_mentions_start() -> None:
    briefing = render_briefing(role="dm", mode="pre_session")
    assert "start_session" in briefing
    assert "/mcp/guide" in briefing


def test_active_dm_briefing_excludes_player_tools() -> None:
    briefing = render_briefing(role="dm", mode="active_session")
    assert "post_narration" in briefing
    assert "request_check" in briefing
    assert "automatically posts the roll prompt" in briefing
    assert "自動顯示擲骰提示" in briefing
    assert "quick_roll" not in briefing
    assert "whisper_dm" not in briefing


def test_active_player_briefing_excludes_dm_tools() -> None:
    briefing = render_briefing(role="player", mode="active_session")
    assert "post_action" in briefing
    assert "post_dialogue" in briefing
    assert "request_check" not in briefing
    assert "post_narration" not in briefing
    assert "set_stage_text" not in briefing


def test_briefing_keeps_temporary_instruction_separate() -> None:
    for role in ("dm", "player"):
        briefing = render_briefing(role=role, mode="active_session")
        assert "Keep the lantern lit." not in briefing
        assert "temporary_instruction" in briefing


def test_briefing_length_cap() -> None:
    from app.domain.rooms.ai_guidance import BRIEFING_MAX_CHARS

    for role in ("dm", "player"):
        assert len(render_briefing(role=role, mode="active_session")) <= BRIEFING_MAX_CHARS
    assert len(render_briefing(role="dm", mode="pre_session")) <= BRIEFING_MAX_CHARS


def test_active_briefings_are_mandatory_step_loops() -> None:
    dm = render_briefing(role="dm", mode="active_session")
    player = render_briefing(role="player", mode="active_session")
    assert "MANDATORY DM LOOP" in dm
    assert "MANDATORY PLAYER LOOP" in player
    # The loop forbids stopping in host chat and mandates re-entering wait.
    for briefing in (dm, player):
        assert "host chat" in briefing
        assert briefing.count("wait_for_event") >= 2


def test_dm_active_briefing_leads_with_stage_setup() -> None:
    dm = render_briefing(role="dm", mode="active_session")
    assert "stage_unset" in dm
    assert "set_stage_text" in dm


def test_pre_session_briefing_states_no_join_step_and_stage_first() -> None:
    briefing = render_briefing(role="dm", mode="pre_session")
    assert "no join step" in briefing.lower() or "沒有另外的入席步驟" in briefing
    assert "set_stage_text" in briefing


def test_briefing_wait_rule_and_write_back() -> None:
    dm = render_briefing(role="dm", mode="active_session")
    player = render_briefing(role="player", mode="active_session")
    for briefing in (dm, player):
        assert "120" in briefing
        assert "5" in briefing
        assert "wait_for_event" in briefing
    assert "post_narration" in dm
    assert "post_dialogue" in player


def test_active_briefings_carry_the_invocation_rule() -> None:
    for role in ("dm", "player"):
        briefing = render_briefing(role=role, mode="active_session")
        assert "MCP invocation rule" in briefing
        assert "MCP 呼叫判定" in briefing
        assert "connection failed" in briefing
        assert "尚未測試" in briefing


def test_briefing_contains_no_secret() -> None:
    for role in ("dm", "player"):
        briefing = render_briefing(role=role, mode="active_session")
        for forbidden in ("SECRET_TOKEN", "SECRET_DC", "at_ai_", "Keep the lantern lit."):
            assert forbidden not in briefing


def test_stage_hint_steers_dm_to_set_stage_then_wait() -> None:
    from types import SimpleNamespace

    from app.domain.rooms.ai_tools import AIToolApplicationService

    hint = AIToolApplicationService._stage_hint
    empty = SimpleNamespace(text=None)
    blank = SimpleNamespace(text="   ")
    filled = SimpleNamespace(text="A flooded crypt.")

    assert hint(empty, role="dm") == (True, "set_stage_text")
    assert hint(blank, role="dm") == (True, "set_stage_text")
    assert hint(filled, role="dm") == (False, "wait_for_event")
    # A Player is never told to touch the DM-only Stage.
    assert hint(empty, role="player") == (True, "wait_for_event")
    assert hint(filled, role="player") == (False, "wait_for_event")
