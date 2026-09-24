from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import insert, select

from app.domain.campaign_runtime import (
    CampaignContextDmView,
    CampaignContextPlayerView,
    CampaignContextService,
)
from app.domain.campaign_runtime import context as context_module
from app.domain.campaign_runtime.ai_tools import CampaignContextAIToolApplicationService
from app.domain.rooms.ai_guidance import BRIEFING_MAX_CHARS, render_briefing
from app.mcp.guide import render_guide
from app.persistence.adventures.tables import adventure_entries
from tests.p6_active_fixture import (
    ActiveFixture,
    _scan_str,
    active_fix,
    context_seeded_fix,
)

SECRET_TITLE = "Vault Lock Secret"
SECRET_BODY = "The inner chamber holds a silver key."


def _add_dm_only_entry(fix: ActiveFixture) -> UUID:
    entry_id = uuid4()
    now = datetime.now(timezone.utc)
    with fix.engine.begin() as conn:
        adventure_id = conn.scalar(
            select(adventure_entries.c.adventure_id).where(
                adventure_entries.c.id == fix.adv_entry_id
            )
        )
        conn.execute(
            insert(adventure_entries).values(
                id=entry_id,
                adventure_id=adventure_id,
                parent_entry_id=fix.adv_entry_id,
                kind="secret",
                title=SECRET_TITLE,
                body=SECRET_BODY,
                data_json={},
                visibility="dm_only",
                sort_order=1,
                created_at=now,
                updated_at=now,
            )
        )
    return entry_id


def _summary(fix: ActiveFixture, actor) -> dict:
    facade = object.__new__(CampaignContextAIToolApplicationService)
    facade.campaign_context_service = CampaignContextService(fix.service)
    return facade._active_context_extension(actor)["campaign_context"]


@pytest.mark.parametrize("actor_name", ["human_dm_actor", "ai_dm_actor"])
def test_dm_campaign_context_lists_adventure_outline_without_bodies(
    context_seeded_fix: ActiveFixture, actor_name: str
) -> None:
    fix = context_seeded_fix
    secret_id = _add_dm_only_entry(fix)

    view = CampaignContextService(fix.service).get_campaign_context(getattr(fix, actor_name))

    assert isinstance(view, CampaignContextDmView)
    (adventure,) = view.attached_adventures
    assert adventure.name == "Test Adventure"
    assert adventure.outline_truncated is False
    by_id = {entry.id: entry for entry in adventure.outline}
    scene = by_id[fix.adv_entry_id]
    assert (scene.kind, scene.title, scene.visibility, scene.has_override) == (
        "scene",
        "Adventure Scene",
        "public",
        True,
    )
    secret = by_id[secret_id]
    assert (secret.kind, secret.title, secret.visibility, secret.parent_entry_id) == (
        "secret",
        SECRET_TITLE,
        "dm_only",
        fix.adv_entry_id,
    )
    assert secret.has_override is False
    dump = view.model_dump(mode="json")
    assert not _scan_str(dump, SECRET_BODY)
    for entry in dump["attached_adventures"][0]["outline"]:
        assert set(entry) == {"id", "parent_entry_id", "kind", "title", "visibility", "has_override"}


@pytest.mark.parametrize("actor_name", ["human_player_1_actor", "ai_player_2_actor"])
def test_player_campaign_context_has_no_adventure_outline(
    context_seeded_fix: ActiveFixture, actor_name: str
) -> None:
    fix = context_seeded_fix
    secret_id = _add_dm_only_entry(fix)

    view = CampaignContextService(fix.service).get_campaign_context(getattr(fix, actor_name))

    assert isinstance(view, CampaignContextPlayerView)
    dump = view.model_dump(mode="json")
    assert "attached_adventures" not in dump
    for forbidden in [str(fix.adv_entry_id), str(secret_id), "Test Adventure", SECRET_TITLE]:
        assert not _scan_str(dump, forbidden)


def test_adventure_outline_is_bounded(
    context_seeded_fix: ActiveFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    fix = context_seeded_fix
    _add_dm_only_entry(fix)
    monkeypatch.setattr(context_module, "ADVENTURE_OUTLINE_MAX_ENTRIES", 1)

    view = CampaignContextService(fix.service).get_campaign_context(fix.human_dm_actor)

    assert isinstance(view, CampaignContextDmView)
    (adventure,) = view.attached_adventures
    assert [entry.id for entry in adventure.outline] == [fix.adv_entry_id]
    assert adventure.outline_truncated is True


def test_session_summary_points_dm_to_outline_and_scene_selection(active_fix: ActiveFixture) -> None:
    # The base fixture attaches an Adventure but sets no current scene.
    dm = _summary(active_fix, active_fix.human_dm_actor)

    assert dm["current_scene"]["kind"] == "none"
    assert dm["next_context_tools"][0] == "get_campaign_context"
    assert "world_set_current_context" in dm["next_context_tools"]
    assert dm["attached_adventures"] == [
        {
            "adventure_id": dm["attached_adventures"][0]["adventure_id"],
            "name": "Test Adventure",
            "outline_entry_count": 1,
        }
    ]

    player = _summary(active_fix, active_fix.human_player_1_actor)
    assert "attached_adventures" not in player
    assert "attached_adventure_count" not in player
    assert "world_set_current_context" not in player["next_context_tools"]
    assert not _scan_str(player, "Test Adventure")


def test_session_summary_omits_scene_selection_once_scene_is_set(
    context_seeded_fix: ActiveFixture,
) -> None:
    dm = _summary(context_seeded_fix, context_seeded_fix.human_dm_actor)

    assert dm["current_scene"]["kind"] == "adventure"
    assert dm["next_context_tools"][0] == "get_campaign_context"
    assert "world_set_current_context" not in dm["next_context_tools"]


ADVENTURE_TOOLS = (
    "get_campaign_context",
    "get_adventure_entry",
    "world_set_current_context",
    "world_set_override",
    "world_create_entry",
)


def test_dm_briefings_teach_adventure_discovery_and_write_back() -> None:
    active = render_briefing(role="dm", mode="active_session")
    en, zh = active.split("\nzh-TW：")
    for text in (en, zh):
        for tool in ADVENTURE_TOOLS:
            assert tool in text
        assert "attached_adventures[].outline" in text
    assert len(active) <= BRIEFING_MAX_CHARS

    pre = render_briefing(role="dm", mode="pre_session")
    pre_en, pre_zh = pre.split("\nzh-TW：")
    for text in (pre_en, pre_zh):
        for tool in ("get_campaign_context", "get_adventure_entry", "world_set_current_context"):
            assert tool in text

    player_pre = render_briefing(role="player", mode="pre_session")
    assert "get_adventure_entry" not in player_pre
    assert "world_set_current_context" not in player_pre


@pytest.mark.parametrize(
    ("locale", "heading"),
    [("zh-TW", "【Adventure 與世界狀態（DM）】"), ("en", "[Adventure and world state (DM)]")],
)
def test_guide_has_adventure_world_section(locale: str, heading: str) -> None:
    guide = render_guide(locale)
    section = guide[guide.index(heading) :].split("\n\n", 1)[0]
    for tool in ("get_session_context", *ADVENTURE_TOOLS):
        assert tool in section
    assert "attached_adventures[].outline" in section
