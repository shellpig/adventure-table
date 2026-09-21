from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import insert, select, update

from app.domain.campaign_runtime import (
    CampaignContextService,
    CampaignRuntimeAuthorityError,
    CampaignRuntimeNotFoundError,
    CampaignRuntimeSessionNotActiveError,
    CampaignRuntimeValidationError,
    CampaignSearchDmResult,
    CampaignSearchHitDmView,
    CampaignSearchPlayerResult,
)
from app.domain.campaign_runtime.context import _search_sort_key
from app.domain.rooms.table_events import TableActorContext
from app.persistence.adventures.tables import adventure_entries
from app.persistence.campaign_runtime.tables import campaign_world_entries
from app.persistence.rooms.tables import (
    ai_controller_grants,
    room_access_sessions,
)
from tests.p6_active_fixture import (
    ActiveFixture,
    _scan_str,
    _snapshot,
    context_seeded_fix,
)


@pytest.fixture
def fix(context_seeded_fix: ActiveFixture) -> ActiveFixture:
    base_fix = context_seeded_fix
    now = datetime.now(timezone.utc)
    with base_fix.engine.begin() as conn:
        adv_def_id = conn.scalar(
            select(adventure_entries.c.adventure_id).where(
                adventure_entries.c.id == base_fix.adv_entry_id
            )
        )
        assert adv_def_id is not None

        # (a) 120 attached Adventure entries with titles "Adventure Lore N" and bodies containing "ancientkey"
        # cycling kinds over public "lore"/"scene" and dm_only "secret"
        cycle = [("lore", "public"), ("scene", "public"), ("secret", "dm_only")]
        adv_rows = [
            {
                "id": uuid4(), "adventure_id": adv_def_id, "parent_entry_id": None,
                "kind": cycle[i % 3][0], "title": f"Adventure Lore {i}",
                "body": f"Ancient secrets of ancientkey lore {i} hidden deeply.",
                "data_json": {}, "visibility": cycle[i % 3][1], "sort_order": i + 1,
                "created_at": now, "updated_at": now,
            }
            for i in range(120)
        ]
        conn.execute(insert(adventure_entries).values(adv_rows))

        # (b) 60 Runtime public entries titled "Runtime Rumor N" whose bodies contain "ancientkey"
        # Seed into both campaign_id and ai_campaign_id for DM parity
        rt_rows = [
            {
                "id": uuid4(), "campaign_id": base_fix.campaign_id, "kind": "other",
                "title": f"Runtime Rumor {i}",
                "body": f"Whispers of ancientkey rumor {i} circulating the town.",
                "state_json": {"kind": "other"}, "visibility": "public",
                "needs_review": False, "revision": 1, "created_by_actor_kind": "human",
                "created_at": now, "updated_at": now,
            }
            for i in range(60)
        ]
        ai_rt_rows = [
            {
                "id": uuid4(), "campaign_id": base_fix.ai_campaign_id, "kind": "other",
                "title": f"Runtime Rumor {i}",
                "body": f"Whispers of ancientkey rumor {i} circulating the town.",
                "state_json": {"kind": "other"}, "visibility": "public",
                "needs_review": False, "revision": 1, "created_by_actor_kind": "ai",
                "created_at": now, "updated_at": now,
            }
            for i in range(60)
        ]
        conn.execute(insert(campaign_world_entries).values(rt_rows + ai_rt_rows))

    return base_fix


@pytest.fixture
def svc(fix: ActiveFixture) -> CampaignContextService:
    return CampaignContextService(fix.service)


# 1. Bounded: limit, offset, max snippet, validation of bounds
@pytest.mark.parametrize(
    ("limit", "offset", "expected_hits_len", "expected_has_more"),
    [(None, 0, 20, True), (50, 160, 20, False)],
)
def test_search_bounded_query(
    fix: ActiveFixture,
    svc: CampaignContextService,
    limit: int | None,
    offset: int,
    expected_hits_len: int,
    expected_has_more: bool,
) -> None:
    res = svc.search_campaign_context(fix.human_dm_actor, "ancientkey", limit=limit, offset=offset)
    assert isinstance(res, CampaignSearchDmResult)
    assert len(res.hits) == expected_hits_len and res.has_more is expected_has_more
    assert all(h.snippet is not None and len(h.snippet) <= 160 for h in res.hits)


@pytest.mark.parametrize(("limit", "offset"), [(0, 0), (51, 0), (20, -1)])
def test_search_invalid_bounds(
    fix: ActiveFixture, svc: CampaignContextService, limit: int, offset: int
) -> None:
    with pytest.raises(CampaignRuntimeValidationError):
        svc.search_campaign_context(fix.human_dm_actor, "ancientkey", limit=limit, offset=offset)


# 2. Empty / whitespace query rejected for DM and Player
@pytest.mark.parametrize("query", ["", "   ", "\t\n\r"])
@pytest.mark.parametrize("actor_name", ["human_dm_actor", "human_player_1_actor"])
def test_search_empty_query_rejected(
    fix: ActiveFixture, svc: CampaignContextService, query: str, actor_name: str
) -> None:
    actor: TableActorContext = getattr(fix, actor_name)
    with pytest.raises(CampaignRuntimeValidationError):
        svc.search_campaign_context(actor, query)


# 3. Deterministic order and stable pagination
def test_search_deterministic_and_pagination_stable(
    fix: ActiveFixture, svc: CampaignContextService
) -> None:
    res1 = svc.search_campaign_context(fix.human_dm_actor, "ancientkey", limit=50)
    res2 = svc.search_campaign_context(fix.human_dm_actor, "ancientkey", limit=50)
    assert res1.model_dump(mode="json") == res2.model_dump(mode="json")

    full_hits: list[CampaignSearchHitDmView] = []
    offset = 0
    while True:
        page = svc.search_campaign_context(fix.human_dm_actor, "ancientkey", limit=50, offset=offset)
        assert isinstance(page, CampaignSearchDmResult)
        full_hits.extend(page.hits)
        if not page.has_more:
            break
        offset += 50
    assert len(full_hits) == 180
    assert [h.id for h in full_hits] == [
        h.id for h in sorted(full_hits, key=lambda h: _search_sort_key(h, ["ancientkey"]))
    ]


# 4. DM vs Player same query "ancientkey": projection, secrecy, parity
def test_dm_vs_player_projection_secrecy(
    fix: ActiveFixture, svc: CampaignContextService
) -> None:
    dm_res = svc.search_campaign_context(fix.human_dm_actor, "ancientkey", limit=50)
    assert isinstance(dm_res, CampaignSearchDmResult)
    dm_page2 = svc.search_campaign_context(fix.human_dm_actor, "ancientkey", limit=50, offset=50)
    assert any(h.source == "adventure" for h in dm_page2.hits)

    p1_res = svc.search_campaign_context(fix.human_player_1_actor, "ancientkey", limit=50)
    p2_res = svc.search_campaign_context(fix.ai_player_2_actor, "ancientkey", limit=50)
    assert isinstance(p1_res, CampaignSearchPlayerResult) and isinstance(p2_res, CampaignSearchPlayerResult)
    assert p1_res.model_dump(mode="json") == p2_res.model_dump(mode="json")
    assert len(p1_res.hits) == 50 and p1_res.has_more is True

    p1_page2 = svc.search_campaign_context(fix.human_player_1_actor, "ancientkey", limit=50, offset=50)
    assert len(p1_page2.hits) == 10 and p1_page2.has_more is False

    p1_dump = p1_res.model_dump(mode="json")
    for forbidden in (str(fix.adv_entry_id), "Adventure Lore", "Secret Room", "Ancient secrets of ancientkey lore"):
        assert not _scan_str(p1_dump, forbidden)

    ai_dm_res = svc.search_campaign_context(fix.ai_dm_actor, "ancientkey", limit=50)
    assert isinstance(ai_dm_res, CampaignSearchDmResult)
    assert len(dm_res.hits) == len(ai_dm_res.hits) == 50
    assert dm_res.has_more == ai_dm_res.has_more is True
    assert [h.title for h in dm_res.hits] == [h.title for h in ai_dm_res.hits]
    assert [h.source for h in dm_res.hits] == [h.source for h in ai_dm_res.hits]
    assert [h.current_truth for h in dm_res.hits] == [h.current_truth for h in ai_dm_res.hits]


# 5. Player query matching only adventure or dm_only runtime entry
@pytest.mark.parametrize("query", ["chimney", "Adventure Lore"])
def test_player_secret_or_adventure_match_indistinguishable(
    fix: ActiveFixture, svc: CampaignContextService, query: str
) -> None:
    res = svc.search_campaign_context(fix.human_player_1_actor, query)
    res_nomatch = svc.search_campaign_context(fix.human_player_1_actor, "zzzznomatch")
    assert res.hits == res_nomatch.hits == ()
    assert res.has_more == res_nomatch.has_more is False
    assert res.limit == res_nomatch.limit and res.offset == res_nomatch.offset


# 6. Own-character fact search projection
def test_own_character_fact_search_projection(
    fix: ActiveFixture, svc: CampaignContextService
) -> None:
    p1_res = svc.search_campaign_context(fix.human_player_1_actor, "heritage")
    p2_res = svc.search_campaign_context(fix.ai_player_2_actor, "heritage")
    assert len(p1_res.hits) == 1 and p1_res.hits[0].kind == "fact"
    assert "heritage" in (p1_res.hits[0].snippet or "").casefold()
    assert len(p2_res.hits) == 0 and p2_res.hits == ()


# 7. Override marking: override vs baseline vs runtime
def test_dm_override_and_source_truth_marking(
    fix: ActiveFixture, svc: CampaignContextService
) -> None:
    adv_res = svc.search_campaign_context(fix.human_dm_actor, "Adventure Scene")
    hit = next(h for h in adv_res.hits if h.id == fix.adv_entry_id)
    assert hit.source == "adventure" and hit.has_override is True and hit.current_truth == "override"

    lore_res = svc.search_campaign_context(fix.human_dm_actor, "Adventure Lore 0")
    lore_hit = next(h for h in lore_res.hits if h.title == "Adventure Lore 0")
    assert lore_hit.source == "adventure" and lore_hit.has_override is False and lore_hit.current_truth == "baseline"

    rt_res = svc.search_campaign_context(fix.human_dm_actor, "Runtime Inn")
    rt_hit = next(h for h in rt_res.hits if h.title == "Runtime Inn")
    assert rt_hit.source == "runtime" and rt_hit.has_override is False and rt_hit.current_truth == "runtime"


# 8. Kinds filter
def test_search_kinds_filter(fix: ActiveFixture, svc: CampaignContextService) -> None:
    dm_res = svc.search_campaign_context(
        fix.human_dm_actor, "ancientkey", kinds=("secret",), limit=50
    )
    assert isinstance(dm_res, CampaignSearchDmResult)
    assert all(h.kind == "secret" for h in dm_res.hits) and len(dm_res.hits) == 40

    p_res = svc.search_campaign_context(
        fix.human_player_1_actor, "ancientkey", kinds=("secret",)
    )
    assert isinstance(p_res, CampaignSearchPlayerResult)
    assert p_res.hits == () and p_res.has_more is False

    with pytest.raises(CampaignRuntimeValidationError):
        svc.search_campaign_context(fix.human_dm_actor, "ancientkey", kinds=("invalid_kind",))


# 9. Authority lifecycle rejections & zero side-effects
@pytest.mark.parametrize("failure_kind", ["inactive_session", "revoked_human", "revoked_ai"])
def test_authority_lifecycle_rejections_zero_side_effects(
    fix: ActiveFixture, svc: CampaignContextService, failure_kind: str
) -> None:
    now = datetime.now(timezone.utc)
    if failure_kind == "inactive_session":
        actor = TableActorContext(
            actor_kind=fix.human_dm_actor.actor_kind, room_id=fix.room_id,
            campaign_id=fix.campaign_id, session_id=fix.inactive_session_id,
            seat_id=fix.dm_seat_id, controlled_seat_ids=(fix.dm_seat_id,),
            role="dm", is_current_dm=True, access_session_id=fix.human_dm_access_id,
        )
        expected_exc = (CampaignRuntimeSessionNotActiveError, CampaignRuntimeNotFoundError)
    elif failure_kind == "revoked_human":
        with fix.engine.begin() as conn:
            conn.execute(
                update(room_access_sessions)
                .where(room_access_sessions.c.id == fix.human_dm_access_id)
                .values(revoked_at=now)
            )
        actor, expected_exc = fix.human_dm_actor, (CampaignRuntimeAuthorityError,)
    else:  # revoked_ai
        with fix.engine.begin() as conn:
            conn.execute(
                update(ai_controller_grants)
                .where(ai_controller_grants.c.id == fix.ai_dm_grant_id)
                .values(status="revoked", revoked_at=now)
            )
        actor, expected_exc = fix.ai_dm_actor, (CampaignRuntimeAuthorityError,)

    before = _snapshot(fix.engine, actor.campaign_id)
    with pytest.raises(expected_exc):
        svc.search_campaign_context(actor, "ancientkey")
    assert _snapshot(fix.engine, actor.campaign_id) == before
