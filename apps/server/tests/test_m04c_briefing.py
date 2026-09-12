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
    for role in ("dm", "player"):
        assert len(render_briefing(role=role, mode="active_session")) <= 1_200
    assert len(render_briefing(role="dm", mode="pre_session")) <= 1_200


def test_briefing_wait_rule_and_write_back() -> None:
    dm = render_briefing(role="dm", mode="active_session")
    player = render_briefing(role="player", mode="active_session")
    for briefing in (dm, player):
        assert "120" in briefing
        assert "5" in briefing
        assert "wait_for_event" in briefing
    assert "post_narration" in dm
    assert "post_dialogue" in player


def test_briefing_contains_no_secret() -> None:
    for role in ("dm", "player"):
        briefing = render_briefing(role=role, mode="active_session")
        for forbidden in ("SECRET_TOKEN", "SECRET_DC", "at_ai_", "Keep the lantern lit."):
            assert forbidden not in briefing
