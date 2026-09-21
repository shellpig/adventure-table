from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Engine

from app.domain.campaign_runtime import (
    ActiveCombatRef,
    AdventureSceneRef,
    CampaignAdventureOverrideCreate,
    CampaignContextDmView,
    CampaignContextPlayerView,
    CampaignContextService,
    CampaignInvalidSceneRefError,
    CampaignRuntimeAuthorityError,
    CampaignRuntimeContextPatch,
    CampaignRuntimeNotFoundError,
    CampaignRuntimeSessionNotActiveError,
    RuntimeSceneRef,
    RuntimeWorldEntryCreate,
    RuntimeWorldEntryDmView,
    RuntimeWorldEntryPlayerView,
    SceneContextDmView,
    SceneContextPlayerView,
)
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.table_events import TableActorContext
from app.persistence.adventures.tables import (
    adventure_definitions,
    adventure_entries,
    campaign_adventure_links,
)
from app.persistence.campaign_runtime.tables import (
    campaign_adventure_overrides,
    campaign_runtime_context,
    campaign_world_entries,
    campaign_world_mutations,
)
from app.persistence.combat.tables import combats
from app.persistence.rooms.tables import (
    ai_controller_grants,
    campaign_seats,
    campaigns,
    room_access_sessions,
    session_participants,
    sessions,
)
from tests.test_p6b_runtime_active_service import ActiveFixture, fix as base_fix


def _scan_str(obj: object, target: str) -> bool:
    if isinstance(obj, str):
        return target in obj
    if isinstance(obj, dict):
        return any(_scan_str(k, target) or _scan_str(v, target) for k, v in obj.items())
    if isinstance(obj, (list, tuple, set)):
        return any(_scan_str(item, target) for item in obj)
    return False


def _snapshot(engine: Engine, campaign_id: UUID) -> dict[str, int]:
    with engine.connect() as conn:
        return {
            "entries": conn.scalar(
                select(func.count()).select_from(campaign_world_entries).where(
                    campaign_world_entries.c.campaign_id == campaign_id
                )
            ) or 0,
            "mutations": conn.scalar(
                select(func.count()).select_from(campaign_world_mutations).where(
                    campaign_world_mutations.c.campaign_id == campaign_id
                )
            ) or 0,
            "overrides": conn.scalar(
                select(func.count()).select_from(campaign_adventure_overrides).where(
                    campaign_adventure_overrides.c.campaign_id == campaign_id
                )
            ) or 0,
            "contexts": conn.scalar(
                select(func.count()).select_from(campaign_runtime_context).where(
                    campaign_runtime_context.c.campaign_id == campaign_id
                )
            ) or 0,
        }


@pytest.fixture
def fix(base_fix: ActiveFixture) -> ActiveFixture:
    now = datetime.now(timezone.utc)
    # Attach adventure and link to ai_campaign_id for DM parity
    with base_fix.engine.begin() as conn:
        adv_def_id = conn.scalar(
            select(adventure_entries.c.adventure_id).where(
                adventure_entries.c.id == base_fix.adv_entry_id
            )
        )
        assert adv_def_id is not None
        conn.execute(
            insert(campaign_adventure_links).values(
                campaign_id=base_fix.ai_campaign_id,
                adventure_id=adv_def_id,
                sort_order=0,
                attached_at=now,
            )
        )

    # Seed override, runtime scene, dm-only secret, char-only fact, related item, context
    base_fix.service.create_override_active(
        base_fix.human_dm_actor,
        CampaignAdventureOverrideCreate(
            adventure_entry_id=base_fix.adv_entry_id,
            state={"dm_summary": "The scene has been cleared."},
            note="Override note",
        ),
        idempotency_key="seed-override",
    )
    base_fix.service.create_active(
        base_fix.human_dm_actor,
        RuntimeWorldEntryCreate(
            kind="scene",
            title="Runtime Inn",
            body="A noisy tavern.",
            visibility="public",
        ),
        idempotency_key="seed-rt-scene",
    )
    base_fix.service.create_active(
        base_fix.human_dm_actor,
        RuntimeWorldEntryCreate(
            kind="secret",
            title="Secret Room",
            body="Behind the chimney.",
            visibility="dm_only",
            dm_notes="DC 15 trap",
        ),
        idempotency_key="seed-secret",
    )
    base_fix.service.create_active(
        base_fix.human_dm_actor,
        RuntimeWorldEntryCreate(
            kind="fact",
            body="Player 1 secret heritage.",
            visibility="character",
            character_recipient_ids=(base_fix.char_1_id,),
        ),
        idempotency_key="seed-fact",
    )
    base_fix.service.create_active(
        base_fix.human_dm_actor,
        RuntimeWorldEntryCreate(
            kind="item",
            title="Relic Blade",
            visibility="public",
            state={
                "kind": "item",
                "holder_ref": {"kind": "party"},
            },
            source_adventure_entry_id=base_fix.adv_entry_id,
        ),
        idempotency_key="seed-item",
    )
    base_fix.service.update_context_active(
        base_fix.human_dm_actor,
        CampaignRuntimeContextPatch(
            expected_revision=0,
            current_adventure_scene_entry_id=base_fix.adv_entry_id,
            current_situation="Party rests at the entrance.",
        ),
        idempotency_key="seed-context",
    )
    # Mirror context to AI DM campaign
    base_fix.service.create_override_active(
        base_fix.ai_dm_actor,
        CampaignAdventureOverrideCreate(
            adventure_entry_id=base_fix.adv_entry_id,
            state={"dm_summary": "The scene has been cleared."},
            note="Override note",
        ),
        idempotency_key="ai-seed-override",
    )
    base_fix.service.update_context_active(
        base_fix.ai_dm_actor,
        CampaignRuntimeContextPatch(
            expected_revision=0,
            current_adventure_scene_entry_id=base_fix.adv_entry_id,
            current_situation="Party rests at the entrance.",
        ),
        idempotency_key="ai-seed-context",
    )
    return base_fix


@pytest.fixture
def svc(fix: ActiveFixture) -> CampaignContextService:
    return CampaignContextService(fix.service)


# 1. DM/AI-DM parity
@pytest.mark.parametrize("intent", ["campaign", "scene"])
def test_dm_and_ai_dm_parity(fix: ActiveFixture, svc: CampaignContextService, intent: str) -> None:
    if intent == "campaign":
        h_view = svc.get_campaign_context(fix.human_dm_actor)
        a_view = svc.get_campaign_context(fix.ai_dm_actor)
        assert isinstance(h_view, CampaignContextDmView)
        assert isinstance(a_view, CampaignContextDmView)
        assert h_view.current_scene.kind == a_view.current_scene.kind == "adventure"
        assert h_view.current_scene.label == a_view.current_scene.label == "Adventure Scene"
        assert len(h_view.attached_adventures) == len(a_view.attached_adventures) == 1
    else:
        ref = AdventureSceneRef(adventure_entry_id=fix.adv_entry_id)
        h_scene = svc.get_scene_context(fix.human_dm_actor, ref)
        a_scene = svc.get_scene_context(fix.ai_dm_actor, ref)
        assert isinstance(h_scene, SceneContextDmView)
        assert isinstance(a_scene, SceneContextDmView)
        assert h_scene.current_truth == a_scene.current_truth == "override"
        assert h_scene.override is not None and a_scene.override is not None
        assert h_scene.override.state_json == a_scene.override.state_json


# 2. Player/AI-Player: no attached_adventures, no Adventure fields/ids/titles, no secrets
@pytest.mark.parametrize("actor_name", ["human_player_1_actor", "ai_player_2_actor"])
def test_player_projection_secrecy(
    fix: ActiveFixture, svc: CampaignContextService, actor_name: str
) -> None:
    actor: TableActorContext = getattr(fix, actor_name)
    c_view = svc.get_campaign_context(actor)
    assert isinstance(c_view, CampaignContextPlayerView)
    c_dump = c_view.model_dump(mode="json")
    assert "attached_adventures" not in c_dump
    for forbidden in [str(fix.adv_entry_id), "Adventure Scene", "Secret Room", "DC 15 trap", "dm_only"]:
        assert not _scan_str(c_dump, forbidden)
    if actor_name == "ai_player_2_actor":
        assert not _scan_str(c_dump, "Player 1 secret heritage")

    s_view = svc.get_scene_context(actor, None)
    assert isinstance(s_view, SceneContextPlayerView)
    s_dump = s_view.model_dump(mode="json")
    for key in ["baseline", "override", "attached_adventures"]:
        assert key not in s_dump
    for forbidden in [str(fix.adv_entry_id), "Adventure Scene", "Secret Room", "DC 15 trap", "dm_only"]:
        assert not _scan_str(s_dump, forbidden)


# 3. Override present: DM marks truth, Player carries neither baseline nor override
def test_override_truth_and_player_omission(fix: ActiveFixture, svc: CampaignContextService) -> None:
    ref = AdventureSceneRef(adventure_entry_id=fix.adv_entry_id)
    dm_scene = svc.get_scene_context(fix.human_dm_actor, ref)
    assert isinstance(dm_scene, SceneContextDmView)
    assert dm_scene.baseline is not None
    assert dm_scene.override is not None
    assert dm_scene.current_truth == "override"
    assert dm_scene.override.state_json == {"dm_summary": "The scene has been cleared."}

    # Players cannot reference Adventure entries at all: existing and random ids
    # raise the same typed error, so existence cannot be probed.
    for actor in (fix.human_player_1_actor, fix.ai_player_2_actor):
        for entry_id in (fix.adv_entry_id, uuid4()):
            with pytest.raises(CampaignInvalidSceneRefError):
                svc.get_scene_context(actor, AdventureSceneRef(adventure_entry_id=entry_id))
    # Current Scene pointing at an Adventure scene degrades to "no scene" for Players,
    # with only Runtime entries already projected for them.
    p_scene = svc.get_scene_context(fix.human_player_1_actor, None)
    assert isinstance(p_scene, SceneContextPlayerView)
    p_dump = p_scene.model_dump(mode="json")
    assert p_scene.scene_id is None and "baseline" not in p_dump and "override" not in p_dump
    assert not _scan_str(p_dump, str(fix.adv_entry_id))
    assert not _scan_str(p_dump, "Adventure Scene")


# 4. Scene ref sources: explicit adventure, explicit runtime, current scenes, no scene, invalid
@pytest.mark.parametrize("source_kind", ["explicit_adv", "explicit_rt", "current_rt", "no_scene", "invalid_adv", "invalid_rt"])
def test_scene_ref_sources(fix: ActiveFixture, svc: CampaignContextService, source_kind: str) -> None:
    rt_entries = fix.service.list_active(fix.human_dm_actor)
    rt_scene_entry = next(e for e in rt_entries if e.kind == "scene")

    if source_kind == "explicit_adv":
        res = svc.get_scene_context(fix.human_dm_actor, AdventureSceneRef(adventure_entry_id=fix.adv_entry_id))
        assert isinstance(res, SceneContextDmView) and res.scene_kind == "adventure"
    elif source_kind == "explicit_rt":
        res = svc.get_scene_context(fix.human_dm_actor, RuntimeSceneRef(runtime_entry_id=rt_scene_entry.id))
        assert isinstance(res, SceneContextDmView) and res.scene_kind == "runtime" and res.current_truth == "runtime"
    elif source_kind == "current_rt":
        fix.service.update_context_active(
            fix.human_dm_actor,
            CampaignRuntimeContextPatch(expected_revision=1, current_adventure_scene_entry_id=None, current_runtime_scene_entry_id=rt_scene_entry.id),
            idempotency_key="switch-rt-scene",
        )
        res = svc.get_scene_context(fix.human_dm_actor, None)
        assert isinstance(res, SceneContextDmView) and res.scene_kind == "runtime"
    elif source_kind == "no_scene":
        fix.service.clear_context_active(fix.human_dm_actor, expected_revision=1, idempotency_key="clr-ctx")
        res_dm = svc.get_scene_context(fix.human_dm_actor, None)
        res_p = svc.get_scene_context(fix.human_player_1_actor, None)
        assert isinstance(res_dm, SceneContextDmView) and res_dm.scene_id is None
        assert isinstance(res_p, SceneContextPlayerView) and res_p.scene_id is None
    elif source_kind == "invalid_adv":
        with pytest.raises(CampaignInvalidSceneRefError):
            svc.get_scene_context(fix.human_dm_actor, AdventureSceneRef(adventure_entry_id=uuid4()))
    elif source_kind == "invalid_rt":
        with pytest.raises(CampaignInvalidSceneRefError):
            svc.get_scene_context(fix.human_dm_actor, RuntimeSceneRef(runtime_entry_id=uuid4()))


# 5. Empty Campaign returns valid minimal view
def test_empty_campaign_minimal_view(fix: ActiveFixture, svc: CampaignContextService) -> None:
    empty_camp_id = uuid4()
    empty_sess_id = uuid4()
    empty_seat_id = uuid4()
    now = datetime.now(timezone.utc)
    with fix.engine.begin() as conn:
        conn.execute(
            insert(campaigns).values(
                id=empty_camp_id, room_id=fix.room_id, name="Empty Campaign", ruleset="dnd-5e-2014", status="active", created_at=now, updated_at=now
            )
        )
        conn.execute(
            insert(campaign_seats).values(
                id=empty_seat_id, campaign_id=empty_camp_id, role="dm", controller_kind="human",
                controller_access_session_id=fix.human_dm_access_id, ai_controller_grant_id=None, controller_epoch=1, created_at=now, updated_at=now
            )
        )
        conn.execute(
            insert(sessions).values(
                id=empty_sess_id, campaign_id=empty_camp_id, status="active", dm_seat_id=empty_seat_id,
                dm_controller_kind="human", dm_controller_access_session_id=fix.human_dm_access_id, started_at=now, created_at=now
            )
        )
        conn.execute(
            insert(session_participants).values(
                id=uuid4(), session_id=empty_sess_id, seat_id=empty_seat_id, role_snapshot="dm",
                controller_kind_at_join="human", controller_access_session_id_at_join=fix.human_dm_access_id, joined_at=now
            )
        )

    actor = fix.service.event_service.resolve_human_actor(
        room_id=fix.room_id, campaign_id=empty_camp_id, session_id=empty_sess_id,
        context=RoomAccessContext(room_id=fix.room_id, access_session_id=fix.human_dm_access_id, authority=RoomAccessAuthority.DM)
    )
    c_view = svc.get_campaign_context(actor)
    assert isinstance(c_view, CampaignContextDmView)
    assert c_view.current_scene.kind == "none"
    assert c_view.attached_adventures == ()
    assert c_view.world_entries == ()

    s_view = svc.get_scene_context(actor, None)
    assert isinstance(s_view, SceneContextDmView)
    assert s_view.scene_id is None
    assert s_view.related_entries == ()


# 6. get_adventure_entry as Player / AI Player raises authority error before lookup
@pytest.mark.parametrize("actor_name", ["human_player_1_actor", "ai_player_2_actor"])
@pytest.mark.parametrize("target_id_kind", ["existing", "non_existent"])
def test_player_get_adventure_entry_forbidden(
    fix: ActiveFixture, svc: CampaignContextService, actor_name: str, target_id_kind: str
) -> None:
    actor: TableActorContext = getattr(fix, actor_name)
    target_id = fix.adv_entry_id if target_id_kind == "existing" else uuid4()
    before = _snapshot(fix.engine, fix.campaign_id)
    with pytest.raises(CampaignRuntimeAuthorityError):
        svc.get_adventure_entry(actor, target_id)
    assert _snapshot(fix.engine, fix.campaign_id) == before


# 7. Inactive Session and revoked access/grant rejected for all four intents with zero side-effects
@pytest.mark.parametrize("intent", ["campaign_context", "scene_context", "world_entry", "adventure_entry"])
@pytest.mark.parametrize("failure_kind", ["inactive_session", "revoked_human", "revoked_ai"])
def test_authority_lifecycle_rejections_zero_side_effects(
    fix: ActiveFixture, svc: CampaignContextService, intent: str, failure_kind: str
) -> None:
    now = datetime.now(timezone.utc)
    target_entry_id = fix.adv_entry_id

    if failure_kind == "inactive_session":
        # Inactive session actor
        actor = TableActorContext(
            actor_kind=fix.human_dm_actor.actor_kind,
            room_id=fix.room_id,
            campaign_id=fix.campaign_id,
            session_id=fix.inactive_session_id,
            seat_id=fix.dm_seat_id,
            controlled_seat_ids=(fix.dm_seat_id,),
            role="dm",
            is_current_dm=True,
            access_session_id=fix.human_dm_access_id,
        )
        expected_exc = (CampaignRuntimeSessionNotActiveError, CampaignRuntimeNotFoundError)
    elif failure_kind == "revoked_human":
        with fix.engine.begin() as conn:
            conn.execute(
                update(room_access_sessions)
                .where(room_access_sessions.c.id == fix.human_dm_access_id)
                .values(revoked_at=now)
            )
        actor = fix.human_dm_actor
        expected_exc = (CampaignRuntimeAuthorityError,)
    else:  # revoked_ai
        with fix.engine.begin() as conn:
            conn.execute(
                update(ai_controller_grants)
                .where(ai_controller_grants.c.id == fix.ai_dm_grant_id)
                .values(status="revoked", revoked_at=now)
            )
        actor = fix.ai_dm_actor
        expected_exc = (CampaignRuntimeAuthorityError,)

    before = _snapshot(fix.engine, actor.campaign_id)
    with pytest.raises(expected_exc):
        if intent == "campaign_context":
            svc.get_campaign_context(actor)
        elif intent == "scene_context":
            svc.get_scene_context(actor, None)
        elif intent == "world_entry":
            svc.get_world_entry(actor, target_entry_id)
        elif intent == "adventure_entry":
            svc.get_adventure_entry(actor, target_entry_id)
    assert _snapshot(fix.engine, actor.campaign_id) == before


# 8. Active combat present -> compact ref only
def test_active_combat_compact_ref(fix: ActiveFixture, svc: CampaignContextService) -> None:
    combat_id = uuid4()
    turn_id = uuid4()
    now = datetime.now(timezone.utc)
    with fix.engine.begin() as conn:
        conn.execute(
            insert(combats).values(
                id=combat_id,
                campaign_id=fix.campaign_id,
                started_session_id=fix.session_id,
                status="running",
                round_number=3,
                current_turn_entry_id=turn_id,
                revision=1,
                started_at=now,
                updated_at=now,
            )
        )
    view = svc.get_campaign_context(fix.human_dm_actor)
    assert view.active_combat is not None
    assert isinstance(view.active_combat, ActiveCombatRef)
    assert view.active_combat.combat_id == combat_id
    assert view.active_combat.round == 3
    assert view.active_combat.current_turn_entry_id == turn_id
    assert set(view.active_combat.model_dump(mode="json").keys()) == {"combat_id", "round", "current_turn_entry_id"}
