"""P6-G G5a: free-text and list fields in the AI campaign context stay bounded."""

from __future__ import annotations

import pytest
from sqlalchemy import update

from app.domain.campaign_runtime import CampaignContextDmView, CampaignContextService
from app.domain.campaign_runtime import context as context_module
from app.domain.campaign_runtime.ai_tools import CampaignContextAIToolApplicationService
from app.domain.campaign_runtime.context_schemas import (
    CAMPAIGN_CONTEXT_MAX_WORLD_REFS,
    CONTEXT_TEXT_MAX_CHARS,
    bounded_context_text,
)
from app.persistence.adventures.tables import adventure_definitions
from app.persistence.campaign_runtime.tables import campaign_runtime_context
from tests.p6_active_fixture import ActiveFixture, context_seeded_fix

LONG_TEXT = "x" * (CONTEXT_TEXT_MAX_CHARS + 500)


def _set_summary(fix: ActiveFixture, summary: str) -> None:
    with fix.engine.begin() as conn:
        conn.execute(update(adventure_definitions).values(summary=summary))


def _set_situation(fix: ActiveFixture, situation: str) -> None:
    with fix.engine.begin() as conn:
        conn.execute(update(campaign_runtime_context).values(current_situation=situation))


def _session_summary(fix: ActiveFixture, actor) -> dict:
    facade = object.__new__(CampaignContextAIToolApplicationService)
    facade.campaign_context_service = CampaignContextService(fix.service)
    return facade._active_context_extension(actor)["campaign_context"]


def test_bounded_context_text_cuts_only_long_values() -> None:
    assert bounded_context_text(None) == (None, False)
    short = "y" * CONTEXT_TEXT_MAX_CHARS
    assert bounded_context_text(short) == (short, False)
    cut, truncated = bounded_context_text(LONG_TEXT)
    assert truncated is True
    assert cut == LONG_TEXT[:CONTEXT_TEXT_MAX_CHARS]


@pytest.mark.parametrize("actor_name", ["human_dm_actor", "ai_dm_actor"])
def test_dm_adventure_summary_is_bounded(context_seeded_fix: ActiveFixture, actor_name: str) -> None:
    fix = context_seeded_fix
    _set_summary(fix, LONG_TEXT)

    view = CampaignContextService(fix.service).get_campaign_context(getattr(fix, actor_name))

    assert isinstance(view, CampaignContextDmView)
    [adventure] = view.attached_adventures
    assert len(adventure.summary) == CONTEXT_TEXT_MAX_CHARS
    assert adventure.summary_truncated is True


def test_short_adventure_summary_is_untouched(context_seeded_fix: ActiveFixture) -> None:
    fix = context_seeded_fix
    _set_summary(fix, "A short overview.")

    view = CampaignContextService(fix.service).get_campaign_context(fix.human_dm_actor)

    [adventure] = view.attached_adventures
    assert adventure.summary == "A short overview."
    assert adventure.summary_truncated is False


@pytest.mark.parametrize(
    "actor_name", ["human_dm_actor", "ai_dm_actor", "human_player_1_actor", "ai_player_2_actor"]
)
def test_current_situation_is_bounded_for_every_role(
    context_seeded_fix: ActiveFixture, actor_name: str
) -> None:
    fix = context_seeded_fix
    _set_situation(fix, LONG_TEXT)
    actor = getattr(fix, actor_name)

    view = CampaignContextService(fix.service).get_campaign_context(actor)
    assert len(view.current_situation) == CONTEXT_TEXT_MAX_CHARS
    assert view.current_situation_truncated is True

    summary = _session_summary(fix, actor)
    assert len(summary["current_situation"]) == CONTEXT_TEXT_MAX_CHARS
    assert summary["current_situation_truncated"] is True


def test_short_current_situation_is_untouched(context_seeded_fix: ActiveFixture) -> None:
    view = CampaignContextService(context_seeded_fix.service).get_campaign_context(
        context_seeded_fix.human_dm_actor
    )
    assert view.current_situation == "Party rests at the entrance."
    assert view.current_situation_truncated is False


def test_world_entry_list_is_bounded(
    context_seeded_fix: ActiveFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    fix = context_seeded_fix
    full = CampaignContextService(fix.service).get_campaign_context(fix.human_dm_actor)
    assert len(full.world_entries) > 1
    assert full.world_entries_truncated is False

    monkeypatch.setattr(context_module, "CAMPAIGN_CONTEXT_MAX_WORLD_REFS", 1)
    view = CampaignContextService(fix.service).get_campaign_context(fix.human_dm_actor)

    assert view.world_entries == full.world_entries[:1]
    assert view.world_entries_truncated is True


def test_world_entry_cap_matches_outline_scale() -> None:
    assert CAMPAIGN_CONTEXT_MAX_WORLD_REFS == 100
