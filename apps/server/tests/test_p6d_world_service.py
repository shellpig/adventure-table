from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, insert, select

from app.domain.campaign_runtime import (
    CampaignAdventureOverride,
    CampaignRuntimeActiveSessionError,
    CampaignRuntimeAuthorityError,
    CampaignRuntimeContext,
    CampaignRuntimeContextPatch,
    CampaignRuntimeIdempotencyConflictError,
    CampaignRuntimeNotFoundError,
    CampaignRuntimeRevisionConflictError,
    CampaignRuntimeSessionNotActiveError,
    CampaignRuntimeValidationError,
    CampaignWorldService,
    ClearAdventureOverrideIntent,
    GrantCharacterKnowledgeIntent,
    RuntimeEntryVisibilityError,
    RuntimeWorldEntryCreate,
    RuntimeWorldEntryDmView,
    RuntimeWorldEntryPatch,
    RuntimeWorldEntryPlayerView,
    SetAdventureOverrideIntent,
    SetCurrentContextIntent,
    SetEntryNeedsReviewIntent,
    SetOverrideNeedsReviewIntent,
)
from app.domain.rooms.schemas import RoomAccessContext
from app.domain.rooms.table_events import TableActorContext
from app.persistence.adventures.tables import campaign_adventure_links
from app.persistence.campaign_runtime.tables import (
    campaign_adventure_overrides,
    campaign_runtime_context,
    campaign_world_entries,
    campaign_world_mutations,
)
from app.persistence.characters import characters
from app.persistence.rooms.table_runtime import session_events
from app.persistence.rooms.tables import (
    campaigns,
)
from tests.p6_active_fixture import (
    ActiveFixture,
    _build_active_fixture,
    _snapshot,
    setup_authority_failure_actor,
)


@pytest.fixture
def fix() -> ActiveFixture:
    return _build_active_fixture()


@pytest.fixture
def world_service(fix: ActiveFixture) -> CampaignWorldService:
    return CampaignWorldService(fix.service)


def _link_ai_campaign_adventure(fix: ActiveFixture) -> None:
    """Ensure AI campaign is also attached to the test adventure for override parity tests."""
    with fix.engine.begin() as conn:
        adv_id = conn.scalar(
            select(campaign_adventure_links.c.adventure_id).where(
                campaign_adventure_links.c.campaign_id == fix.campaign_id
            )
        )
        assert adv_id is not None
        existing = conn.scalar(
            select(func.count()).select_from(campaign_adventure_links).where(
                campaign_adventure_links.c.campaign_id == fix.ai_campaign_id,
                campaign_adventure_links.c.adventure_id == adv_id,
            )
        )
        if not existing:
            conn.execute(
                insert(campaign_adventure_links).values(
                    campaign_id=fix.ai_campaign_id,
                    adventure_id=adv_id,
                    sort_order=0,
                    attached_at=datetime.now(timezone.utc),
                )
            )


def _normalize_entry_event_payload(payload: dict[str, object]) -> dict[str, object]:
    """Normalize legitimate actor and record identity differences for parity assertions."""
    norm = deepcopy(payload)
    norm.pop("entry_id", None)
    return norm


# ---------------------------------------------------------------------------
# 1. Human / AI DM Parity: Event Shape & Validation
# ---------------------------------------------------------------------------


def test_human_and_ai_dm_event_shape_and_semantic_parity(
    fix: ActiveFixture,
    world_service: CampaignWorldService,
) -> None:
    _link_ai_campaign_adventure(fix)

    # 1. Fact Create Parity
    fact_create = RuntimeWorldEntryCreate(
        kind="fact",
        body="Ancient runes are inscribed on the archway.",
        dm_notes="Decipherable with DC 15 Arcana.",
        visibility="public",
    )
    human_fact = world_service.create_world_entry(
        fix.human_dm_actor, fact_create, idempotency_key="fact-human-parity"
    )
    ai_fact = world_service.create_world_entry(
        fix.ai_dm_actor, fact_create, idempotency_key="fact-ai-parity"
    )

    assert human_fact.kind == ai_fact.kind == "fact"
    assert human_fact.body == ai_fact.body == fact_create.body
    assert human_fact.dm_notes == ai_fact.dm_notes == fact_create.dm_notes
    assert human_fact.visibility == ai_fact.visibility == "public"
    assert human_fact.revision == ai_fact.revision == 1

    with fix.engine.connect() as conn:
        human_ev = conn.execute(
            select(session_events).where(
                session_events.c.session_id == fix.session_id,
                session_events.c.kind == "world.entry.created",
            )
        ).mappings().one()
        ai_ev = conn.execute(
            select(session_events).where(
                session_events.c.session_id == fix.ai_session_id,
                session_events.c.kind == "world.entry.created",
            )
        ).mappings().one()

    assert human_ev["kind"] == ai_ev["kind"] == "world.entry.created"
    assert human_ev["visibility"] == ai_ev["visibility"] == "public"
    assert set(human_ev["payload"].keys()) == set(ai_ev["payload"].keys())
    assert _normalize_entry_event_payload(human_ev["payload"]) == _normalize_entry_event_payload(ai_ev["payload"])

    # 2. NPC Create Parity
    npc_create = RuntimeWorldEntryCreate(
        kind="npc",
        title="Borgan Ironbreaker",
        body="A stern dwarf blacksmith.",
        state={"monster_template_ref": "dwarf_warrior"},
    )
    human_npc = world_service.create_world_entry(
        fix.human_dm_actor, npc_create, idempotency_key="npc-human-parity"
    )
    ai_npc = world_service.create_world_entry(
        fix.ai_dm_actor, npc_create, idempotency_key="npc-ai-parity"
    )

    assert human_npc.title == ai_npc.title == "Borgan Ironbreaker"
    assert human_npc.body == ai_npc.body == "A stern dwarf blacksmith."
    assert human_npc.revision == ai_npc.revision == 1


def test_human_and_ai_dm_negative_validation_parity(
    fix: ActiveFixture,
    world_service: CampaignWorldService,
) -> None:
    # Pre-create entry for both actors
    create_payload = RuntimeWorldEntryCreate(
        kind="fact",
        body="A secret pass through the mountains.",
    )
    h_entry = world_service.create_world_entry(
        fix.human_dm_actor, create_payload, idempotency_key="h-entry-val"
    )
    ai_entry = world_service.create_world_entry(
        fix.ai_dm_actor, create_payload, idempotency_key="ai-entry-val"
    )

    # 1. Stale revision rejection parity
    stale_patch = RuntimeWorldEntryPatch(
        expected_revision=999,
        body="Updated text that should be rejected.",
    )
    with fix.engine.connect() as conn:
        h_row_before = conn.execute(
            select(campaign_world_entries).where(
                campaign_world_entries.c.id == h_entry.id
            )
        ).mappings().one()
        ai_row_before = conn.execute(
            select(campaign_world_entries).where(
                campaign_world_entries.c.id == ai_entry.id
            )
        ).mappings().one()
        h_mut_before = conn.scalar(
            select(func.count()).select_from(campaign_world_mutations).where(
                campaign_world_mutations.c.campaign_id == fix.campaign_id
            )
        )
        ai_mut_before = conn.scalar(
            select(func.count()).select_from(campaign_world_mutations).where(
                campaign_world_mutations.c.campaign_id == fix.ai_campaign_id
            )
        )
        h_ev_before = conn.scalar(
            select(func.count()).select_from(session_events).where(
                session_events.c.session_id == fix.session_id
            )
        )
        ai_ev_before = conn.scalar(
            select(func.count()).select_from(session_events).where(
                session_events.c.session_id == fix.ai_session_id
            )
        )
    h_notifier_before = len(fix.notifier.notifications)

    h_snap_before = _snapshot(fix.engine, fix.campaign_id)
    with pytest.raises(CampaignRuntimeRevisionConflictError):
        world_service.update_world_entry(
            fix.human_dm_actor, h_entry.id, stale_patch, idempotency_key="h-stale-rev"
        )
    assert _snapshot(fix.engine, fix.campaign_id) == h_snap_before

    ai_snap_before = _snapshot(fix.engine, fix.ai_campaign_id)
    with pytest.raises(CampaignRuntimeRevisionConflictError):
        world_service.update_world_entry(
            fix.ai_dm_actor, ai_entry.id, stale_patch, idempotency_key="ai-stale-rev"
        )
    assert _snapshot(fix.engine, fix.ai_campaign_id) == ai_snap_before

    with fix.engine.connect() as conn:
        h_row_after = conn.execute(
            select(campaign_world_entries).where(
                campaign_world_entries.c.id == h_entry.id
            )
        ).mappings().one()
        ai_row_after = conn.execute(
            select(campaign_world_entries).where(
                campaign_world_entries.c.id == ai_entry.id
            )
        ).mappings().one()
        h_mut_after = conn.scalar(
            select(func.count()).select_from(campaign_world_mutations).where(
                campaign_world_mutations.c.campaign_id == fix.campaign_id
            )
        )
        ai_mut_after = conn.scalar(
            select(func.count()).select_from(campaign_world_mutations).where(
                campaign_world_mutations.c.campaign_id == fix.ai_campaign_id
            )
        )
        h_ev_after = conn.scalar(
            select(func.count()).select_from(session_events).where(
                session_events.c.session_id == fix.session_id
            )
        )
        ai_ev_after = conn.scalar(
            select(func.count()).select_from(session_events).where(
                session_events.c.session_id == fix.ai_session_id
            )
        )

    assert dict(h_row_after) == dict(h_row_before)
    assert dict(ai_row_after) == dict(ai_row_before)
    assert h_mut_after == h_mut_before
    assert ai_mut_after == ai_mut_before
    assert h_ev_after == h_ev_before
    assert ai_ev_after == ai_ev_before
    assert len(fix.notifier.notifications) == h_notifier_before

    # 2. Invalid recipient set rejection parity (empty recipients for character visibility)
    invalid_grant_h = GrantCharacterKnowledgeIntent(
        entry_id=h_entry.id,
        expected_revision=1,
        character_recipient_ids=(),
    )
    with pytest.raises(RuntimeEntryVisibilityError, match="at least one character recipient"):
        world_service.grant_character_knowledge(
            fix.human_dm_actor, invalid_grant_h, idempotency_key="h-bad-recipients"
        )
    assert _snapshot(fix.engine, fix.campaign_id) == h_snap_before

    invalid_grant_ai = GrantCharacterKnowledgeIntent(
        entry_id=ai_entry.id,
        expected_revision=1,
        character_recipient_ids=(),
    )
    with pytest.raises(RuntimeEntryVisibilityError, match="at least one character recipient"):
        world_service.grant_character_knowledge(
            fix.ai_dm_actor, invalid_grant_ai, idempotency_key="ai-bad-recipients"
        )
    assert _snapshot(fix.engine, fix.ai_campaign_id) == ai_snap_before


@pytest.mark.parametrize("actor_role", ["human_dm", "ai_dm"])
def test_human_and_ai_dm_parity_all_eight_intents(
    fix: ActiveFixture,
    world_service: CampaignWorldService,
    actor_role: Literal["human_dm", "ai_dm"],
) -> None:
    _link_ai_campaign_adventure(fix)
    actor = fix.human_dm_actor if actor_role == "human_dm" else fix.ai_dm_actor

    # 1. create_world_entry
    entry = world_service.create_world_entry(
        actor,
        RuntimeWorldEntryCreate(
            kind="scene",
            title="The Sunken Cavern",
            body="Water drips from the ceiling.",
            visibility="dm_only",
        ),
        idempotency_key=f"{actor_role}-intent-create",
    )
    assert entry.revision == 1
    assert entry.visibility == "dm_only"

    # 2. update_world_entry
    updated = world_service.update_world_entry(
        actor,
        entry.id,
        RuntimeWorldEntryPatch(
            expected_revision=1,
            body="Glowing moss covers the damp walls.",
        ),
        idempotency_key=f"{actor_role}-intent-update",
    )
    assert updated.revision == 2
    assert updated.body == "Glowing moss covers the damp walls."

    # 3. grant_character_knowledge
    granted = world_service.grant_character_knowledge(
        actor,
        GrantCharacterKnowledgeIntent(
            entry_id=entry.id,
            expected_revision=2,
            character_recipient_ids=(fix.char_1_id,),
        ),
        idempotency_key=f"{actor_role}-intent-grant",
    )
    assert granted.revision == 3
    assert granted.visibility == "character"
    assert granted.character_recipient_ids == (fix.char_1_id,)

    # 4. set_needs_review (entry)
    reviewed = world_service.set_needs_review(
        actor,
        SetEntryNeedsReviewIntent(
            entry_id=entry.id,
            expected_revision=3,
            needs_review=True,
        ),
        idempotency_key=f"{actor_role}-intent-nr-entry",
    )
    assert isinstance(reviewed, RuntimeWorldEntryDmView)
    assert reviewed.revision == 4
    assert reviewed.needs_review is True

    # 5. archive_world_entry
    archived = world_service.archive_world_entry(
        actor,
        entry.id,
        expected_revision=4,
        idempotency_key=f"{actor_role}-intent-archive",
    )
    assert archived.revision == 5
    assert archived.archived_at is not None

    # 6. set_adventure_override (create)
    override = world_service.set_adventure_override(
        actor,
        SetAdventureOverrideIntent(
            adventure_entry_id=fix.adv_entry_id,
            state={"dm_summary": "Flooded during rainstorm."},
            note="Flooded during rainstorm.",
        ),
        idempotency_key=f"{actor_role}-intent-set-override",
    )
    assert isinstance(override, CampaignAdventureOverride)
    assert override.revision == 1
    assert override.state_json == {"dm_summary": "Flooded during rainstorm."}
    assert override.note == "Flooded during rainstorm."
    assert override.needs_review is False

    # 6b. set_adventure_override (update only note, preserving state and needs_review)
    override_up = world_service.set_adventure_override(
        actor,
        SetAdventureOverrideIntent(
            adventure_entry_id=fix.adv_entry_id,
            expected_override_id=override.id,
            expected_revision=1,
            note="Water receded slightly.",
        ),
        idempotency_key=f"{actor_role}-intent-set-override-update",
    )
    assert override_up.revision == 2
    assert override_up.note == "Water receded slightly."
    assert override_up.state_json == {"dm_summary": "Flooded during rainstorm."}
    assert override_up.needs_review is False

    # 7. clear_adventure_override
    cleared = world_service.clear_adventure_override(
        actor,
        ClearAdventureOverrideIntent(
            adventure_entry_id=fix.adv_entry_id,
            expected_override_id=override.id,
            expected_revision=2,
        ),
        idempotency_key=f"{actor_role}-intent-clear-override",
    )
    assert isinstance(cleared, CampaignAdventureOverride)
    assert cleared.id == override.id
    assert cleared.revision == 2
    with pytest.raises(CampaignRuntimeNotFoundError):
        fix.service.get_override_active(actor, fix.adv_entry_id)

    # 8. set_current_context
    ctx = world_service.set_current_context(
        actor,
        SetCurrentContextIntent(
            expected_revision=0,
            current_situation="Party rests near the entrance.",
        ),
        idempotency_key=f"{actor_role}-intent-context",
    )
    assert isinstance(ctx, CampaignRuntimeContext)
    assert ctx.current_situation == "Party rests near the entrance."


# ---------------------------------------------------------------------------
# 2. Coherent Session-outside-Human Management Flow (All 8 Intents)
# ---------------------------------------------------------------------------


def test_human_management_coherent_flow_all_eight_intents(
    fix: ActiveFixture,
    world_service: CampaignWorldService,
) -> None:
    now = datetime.now(timezone.utc)
    mgmt_campaign_id = uuid4()

    # Create campaign with NO active session
    with fix.engine.begin() as conn:
        conn.execute(
            insert(campaigns).values(
                id=mgmt_campaign_id,
                room_id=fix.room_id,
                name="Management Only Campaign",
                ruleset="dnd-5e-2014",
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
        adv_id = conn.scalar(
            select(campaign_adventure_links.c.adventure_id).where(
                campaign_adventure_links.c.campaign_id == fix.campaign_id
            )
        )
        assert adv_id is not None
        conn.execute(
            insert(campaign_adventure_links).values(
                campaign_id=mgmt_campaign_id,
                adventure_id=adv_id,
                sort_order=0,
                attached_at=now,
            )
        )

    initial_notifications = len(fix.notifier.notifications)
    with fix.engine.connect() as conn:
        initial_events = conn.scalar(select(func.count()).select_from(session_events)) or 0

    # 1. create_world_entry (scene)
    scene = world_service.create_world_entry(
        fix.owner_context,
        RuntimeWorldEntryCreate(
            kind="scene",
            title="The Grand Library",
            body="Shelves rise to the vaulted ceiling.",
            visibility="dm_only",
        ),
        idempotency_key="mgmt-flow-1",
        campaign_id=mgmt_campaign_id,
    )
    assert scene.revision == 1
    assert scene.created_by_actor_kind == "human"
    assert scene.created_by_actor_id == fix.owner_context.access_session_id

    # 2. update_world_entry
    scene_up = world_service.update_world_entry(
        fix.owner_context,
        scene.id,
        RuntimeWorldEntryPatch(
            expected_revision=1,
            body="Shelves of ancient tomes rise to the vaulted ceiling.",
        ),
        idempotency_key="mgmt-flow-2",
        campaign_id=mgmt_campaign_id,
    )
    assert scene_up.revision == 2

    # 3. grant_character_knowledge
    scene_grant = world_service.grant_character_knowledge(
        fix.owner_context,
        GrantCharacterKnowledgeIntent(
            entry_id=scene.id,
            expected_revision=2,
            character_recipient_ids=(fix.char_1_id,),
        ),
        idempotency_key="mgmt-flow-3",
        campaign_id=mgmt_campaign_id,
    )
    assert scene_grant.revision == 3
    assert scene_grant.visibility == "character"
    assert scene_grant.character_recipient_ids == (fix.char_1_id,)

    # 4. set_needs_review (entry true)
    scene_nr_t = world_service.set_needs_review(
        fix.owner_context,
        SetEntryNeedsReviewIntent(
            entry_id=scene.id,
            expected_revision=3,
            needs_review=True,
        ),
        idempotency_key="mgmt-flow-4",
        campaign_id=mgmt_campaign_id,
    )
    assert isinstance(scene_nr_t, RuntimeWorldEntryDmView)
    assert scene_nr_t.revision == 4
    assert scene_nr_t.needs_review is True

    # 5. set_needs_review (entry false)
    scene_nr_f = world_service.set_needs_review(
        fix.owner_context,
        SetEntryNeedsReviewIntent(
            entry_id=scene.id,
            expected_revision=4,
            needs_review=False,
        ),
        idempotency_key="mgmt-flow-5",
        campaign_id=mgmt_campaign_id,
    )
    assert isinstance(scene_nr_f, RuntimeWorldEntryDmView)
    assert scene_nr_f.revision == 5
    assert scene_nr_f.needs_review is False

    # 6. archive_world_entry
    scene_arch = world_service.archive_world_entry(
        fix.owner_context,
        scene.id,
        expected_revision=5,
        idempotency_key="mgmt-flow-6",
        campaign_id=mgmt_campaign_id,
    )
    assert scene_arch.revision == 6
    assert scene_arch.archived_at is not None

    # 7. set_adventure_override (create)
    ov = world_service.set_adventure_override(
        fix.owner_context,
        SetAdventureOverrideIntent(
            adventure_entry_id=fix.adv_entry_id,
            state={"dm_summary": "Library is locked by decree."},
            note="Locked by decree.",
        ),
        idempotency_key="mgmt-flow-7",
        campaign_id=mgmt_campaign_id,
    )
    assert isinstance(ov, CampaignAdventureOverride)
    assert ov.revision == 1

    # 8. set_needs_review (override true)
    ov_nr_t = world_service.set_needs_review(
        fix.owner_context,
        SetOverrideNeedsReviewIntent(
            adventure_entry_id=fix.adv_entry_id,
            expected_override_id=ov.id,
            expected_revision=1,
            needs_review=True,
        ),
        idempotency_key="mgmt-flow-8",
        campaign_id=mgmt_campaign_id,
    )
    assert isinstance(ov_nr_t, CampaignAdventureOverride)
    assert ov_nr_t.revision == 2
    assert ov_nr_t.needs_review is True

    # 9. set_needs_review (override false)
    ov_nr_f = world_service.set_needs_review(
        fix.owner_context,
        SetOverrideNeedsReviewIntent(
            adventure_entry_id=fix.adv_entry_id,
            expected_override_id=ov.id,
            expected_revision=2,
            needs_review=False,
        ),
        idempotency_key="mgmt-flow-9",
        campaign_id=mgmt_campaign_id,
    )
    assert isinstance(ov_nr_f, CampaignAdventureOverride)
    assert ov_nr_f.revision == 3
    assert ov_nr_f.needs_review is False

    # 9b. set_adventure_override (update only note, preserving state and needs_review)
    ov_updated = world_service.set_adventure_override(
        fix.owner_context,
        SetAdventureOverrideIntent(
            adventure_entry_id=fix.adv_entry_id,
            expected_override_id=ov.id,
            expected_revision=3,
            note="Updated note: decree lifted by the guildmaster.",
        ),
        idempotency_key="mgmt-flow-9b",
        campaign_id=mgmt_campaign_id,
    )
    assert isinstance(ov_updated, CampaignAdventureOverride)
    assert ov_updated.revision == 4
    assert ov_updated.note == "Updated note: decree lifted by the guildmaster."
    assert ov_updated.state_json == {"dm_summary": "Library is locked by decree."}
    assert ov_updated.needs_review is False

    # 10. clear_adventure_override
    ov_cleared = world_service.clear_adventure_override(
        fix.owner_context,
        ClearAdventureOverrideIntent(
            adventure_entry_id=fix.adv_entry_id,
            expected_override_id=ov.id,
            expected_revision=4,
        ),
        idempotency_key="mgmt-flow-10",
        campaign_id=mgmt_campaign_id,
    )
    assert isinstance(ov_cleared, CampaignAdventureOverride)
    assert ov_cleared.id == ov.id

    # 11. set_current_context
    ctx = world_service.set_current_context(
        fix.owner_context,
        SetCurrentContextIntent(
            expected_revision=0,
            current_situation="Planning the expedition.",
        ),
        idempotency_key="mgmt-flow-11",
        campaign_id=mgmt_campaign_id,
    )
    assert isinstance(ctx, CampaignRuntimeContext)
    assert ctx.current_situation == "Planning the expedition."

    # Audit assertions:
    # 1. Mutation records created for mgmt_campaign_id with human actor audit
    with fix.engine.connect() as conn:
        mutations = conn.execute(
            select(campaign_world_mutations).where(
                campaign_world_mutations.c.campaign_id == mgmt_campaign_id
            )
        ).mappings().fetchall()
        assert len(mutations) == 12
        for mut in mutations:
            assert mut["created_by_actor_kind"] == "human"
            assert mut["created_by_actor_id"] == fix.owner_context.access_session_id

        # 2. ZERO session events created
        current_events = conn.scalar(select(func.count()).select_from(session_events)) or 0
        assert current_events == initial_events

    # 3. ZERO notifications sent
    assert len(fix.notifier.notifications) == initial_notifications


def test_human_management_rejected_when_session_is_active(
    fix: ActiveFixture,
    world_service: CampaignWorldService,
) -> None:
    # Attempt management write while session is active on fix.campaign_id
    with pytest.raises(CampaignRuntimeActiveSessionError, match="active session"):
        world_service.create_world_entry(
            fix.owner_context,
            RuntimeWorldEntryCreate(
                kind="fact",
                body="Management during active session should fail.",
            ),
            idempotency_key="mgmt-blocked-1",
            campaign_id=fix.campaign_id,
        )


# ---------------------------------------------------------------------------
# 3. Management Path Idempotency Retries
# ---------------------------------------------------------------------------


def test_management_path_idempotency_retries(
    fix: ActiveFixture,
    world_service: CampaignWorldService,
) -> None:
    now = datetime.now(timezone.utc)
    mgmt_campaign_id = uuid4()

    with fix.engine.begin() as conn:
        conn.execute(
            insert(campaigns).values(
                id=mgmt_campaign_id,
                room_id=fix.room_id,
                name="Idempotency Mgmt Campaign",
                ruleset="dnd-5e-2014",
                status="active",
                created_at=now,
                updated_at=now,
            )
        )

    with fix.engine.connect() as conn:
        events_before = conn.scalar(select(func.count()).select_from(session_events)) or 0
    notifs_before = len(fix.notifier.notifications)

    # 1. create_world_entry management retry
    create_key = "mgmt-idem-create"
    create_payload = RuntimeWorldEntryCreate(
        kind="npc",
        title="Mayor Stone",
        body="Town magistrate.",
    )
    v1 = world_service.create_world_entry(
        fix.owner_context,
        create_payload,
        idempotency_key=create_key,
        campaign_id=mgmt_campaign_id,
    )
    v2 = world_service.create_world_entry(
        fix.owner_context,
        create_payload,
        idempotency_key=create_key,
        campaign_id=mgmt_campaign_id,
    )
    assert v1 == v2

    with fix.engine.connect() as conn:
        mut_count = conn.scalar(
            select(func.count()).select_from(campaign_world_mutations).where(
                campaign_world_mutations.c.campaign_id == mgmt_campaign_id,
                campaign_world_mutations.c.idempotency_key == create_key,
            )
        )
        assert mut_count == 1

        events_after = conn.scalar(select(func.count()).select_from(session_events)) or 0
        assert events_after == events_before

    assert len(fix.notifier.notifications) == notifs_before

    # Replay with conflicting command raises error
    with pytest.raises(CampaignRuntimeIdempotencyConflictError):
        world_service.create_world_entry(
            fix.owner_context,
            RuntimeWorldEntryCreate(
                kind="npc",
                title="Different Mayor",
                body="Different body.",
            ),
            idempotency_key=create_key,
            campaign_id=mgmt_campaign_id,
        )

    # 2. Special dispatch intent 1: grant_character_knowledge
    grant_key = "mgmt-idem-grant"
    grant_intent = GrantCharacterKnowledgeIntent(
        entry_id=v1.id,
        expected_revision=1,
        character_recipient_ids=(fix.char_1_id,),
    )
    g1 = world_service.grant_character_knowledge(
        fix.owner_context,
        grant_intent,
        idempotency_key=grant_key,
        campaign_id=mgmt_campaign_id,
    )
    g2 = world_service.grant_character_knowledge(
        fix.owner_context,
        grant_intent,
        idempotency_key=grant_key,
        campaign_id=mgmt_campaign_id,
    )
    assert g1 == g2

    with fix.engine.connect() as conn:
        mut_count = conn.scalar(
            select(func.count()).select_from(campaign_world_mutations).where(
                campaign_world_mutations.c.campaign_id == mgmt_campaign_id,
                campaign_world_mutations.c.idempotency_key == grant_key,
            )
        )
        assert mut_count == 1
        assert (conn.scalar(select(func.count()).select_from(session_events)) or 0) == events_before

    assert len(fix.notifier.notifications) == notifs_before

    # 3. Special dispatch intent 2: set_needs_review
    nr_key = "mgmt-idem-nr"
    nr_intent = SetEntryNeedsReviewIntent(
        entry_id=v1.id,
        expected_revision=2,
        needs_review=True,
    )
    nr1 = world_service.set_needs_review(
        fix.owner_context,
        nr_intent,
        idempotency_key=nr_key,
        campaign_id=mgmt_campaign_id,
    )
    nr2 = world_service.set_needs_review(
        fix.owner_context,
        nr_intent,
        idempotency_key=nr_key,
        campaign_id=mgmt_campaign_id,
    )
    assert nr1 == nr2

    with fix.engine.connect() as conn:
        mut_count = conn.scalar(
            select(func.count()).select_from(campaign_world_mutations).where(
                campaign_world_mutations.c.campaign_id == mgmt_campaign_id,
                campaign_world_mutations.c.idempotency_key == nr_key,
            )
        )
        assert mut_count == 1
        assert (conn.scalar(select(func.count()).select_from(session_events)) or 0) == events_before

    assert len(fix.notifier.notifications) == notifs_before


# ---------------------------------------------------------------------------
# 4. Active Idempotency Retries
# ---------------------------------------------------------------------------


def test_idempotency_retry_succeeds_once_and_does_not_duplicate_events(
    fix: ActiveFixture,
    world_service: CampaignWorldService,
) -> None:
    actor = fix.human_dm_actor
    key = "idem-world-entry-create-1"

    # 1. First call creates entry
    view1 = world_service.create_world_entry(
        actor,
        RuntimeWorldEntryCreate(
            kind="npc",
            title="Captain Vane",
            body="Harbor watch commander.",
        ),
        idempotency_key=key,
    )

    with fix.engine.connect() as conn:
        ev_count_1 = conn.scalar(
            select(func.count()).select_from(session_events).where(
                session_events.c.session_id == actor.session_id,
                session_events.c.kind == "world.entry.created",
            )
        )
        assert ev_count_1 == 1

    notif_count_1 = len(fix.notifier.notifications)

    # 2. Retry with same key returns identical result without duplicating events
    view2 = world_service.create_world_entry(
        actor,
        RuntimeWorldEntryCreate(
            kind="npc",
            title="Captain Vane",
            body="Harbor watch commander.",
        ),
        idempotency_key=key,
    )
    assert view2 == view1

    with fix.engine.connect() as conn:
        ev_count_2 = conn.scalar(
            select(func.count()).select_from(session_events).where(
                session_events.c.session_id == actor.session_id,
                session_events.c.kind == "world.entry.created",
            )
        )
        assert ev_count_2 == 1

    assert len(fix.notifier.notifications) == notif_count_1

    # 3. Replaying with different payload causes idempotency conflict
    with pytest.raises(CampaignRuntimeIdempotencyConflictError):
        world_service.create_world_entry(
            actor,
            RuntimeWorldEntryCreate(
                kind="npc",
                title="Different Name",
                body="Different body.",
            ),
            idempotency_key=key,
        )


def test_idempotency_retry_special_intents_active(
    fix: ActiveFixture,
    world_service: CampaignWorldService,
) -> None:
    actor = fix.human_dm_actor

    entry = world_service.create_world_entry(
        actor,
        RuntimeWorldEntryCreate(
            kind="secret",
            title="Hidden Map",
            body="Behind the portrait.",
            visibility="dm_only",
        ),
        idempotency_key="special-entry-1",
    )

    # grant_character_knowledge idempotency
    grant_key = "grant-idem-1"
    g1 = world_service.grant_character_knowledge(
        actor,
        GrantCharacterKnowledgeIntent(
            entry_id=entry.id,
            expected_revision=1,
            character_recipient_ids=(fix.char_1_id,),
        ),
        idempotency_key=grant_key,
    )
    g2 = world_service.grant_character_knowledge(
        actor,
        GrantCharacterKnowledgeIntent(
            entry_id=entry.id,
            expected_revision=1,
            character_recipient_ids=(fix.char_1_id,),
        ),
        idempotency_key=grant_key,
    )
    assert g1 == g2

    # set_needs_review idempotency
    nr_key = "nr-idem-1"
    nr1 = world_service.set_needs_review(
        actor,
        SetEntryNeedsReviewIntent(
            entry_id=entry.id,
            expected_revision=2,
            needs_review=True,
        ),
        idempotency_key=nr_key,
    )
    nr2 = world_service.set_needs_review(
        actor,
        SetEntryNeedsReviewIntent(
            entry_id=entry.id,
            expected_revision=2,
            needs_review=True,
        ),
        idempotency_key=nr_key,
    )
    assert nr1 == nr2


# ---------------------------------------------------------------------------
# 5. Independent Unauthorized Rejections (Zero Side Effects)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "failure_kind",
    [
        "human_player",
        "ai_player",
        "revoked_ai",
        "controller_epoch",
        "inactive_session",
    ],
)
def test_unauthorized_actors_rejected_with_zero_side_effects(
    fix: ActiveFixture,
    world_service: CampaignWorldService,
    failure_kind: str,
) -> None:
    create_payload = RuntimeWorldEntryCreate(
        kind="fact",
        body="This write should be rejected.",
    )

    if failure_kind == "human_player":
        actor = fix.human_player_1_actor
        expected_excs = (CampaignRuntimeAuthorityError,)
    elif failure_kind == "ai_player":
        actor = fix.ai_player_2_actor
        expected_excs = (CampaignRuntimeAuthorityError,)
    else:
        actor, expected_excs = setup_authority_failure_actor(fix, failure_kind)

    snap_before = _snapshot(fix.engine, actor.campaign_id)
    with fix.engine.connect() as conn:
        events_before = conn.scalar(select(func.count()).select_from(session_events)) or 0
    notifs_before = len(fix.notifier.notifications)

    with pytest.raises(expected_excs):
        world_service.create_world_entry(
            actor,
            create_payload,
            idempotency_key=f"unauth-{failure_kind}",
        )

    # Prove zero side effects across entries, mutations, overrides, contexts, events, and notifier
    assert _snapshot(fix.engine, actor.campaign_id) == snap_before

    with fix.engine.connect() as conn:
        events_after = conn.scalar(select(func.count()).select_from(session_events)) or 0
        assert events_after == events_before

    assert len(fix.notifier.notifications) == notifs_before


def test_room_and_campaign_mismatch_validation_rejected(
    fix: ActiveFixture,
    world_service: CampaignWorldService,
) -> None:
    create_payload = RuntimeWorldEntryCreate(
        kind="fact",
        body="This write should be rejected for mismatch.",
    )
    snap_before = _snapshot(fix.engine, fix.campaign_id)

    with pytest.raises(CampaignRuntimeValidationError, match="does not match actor campaign_id"):
        world_service.create_world_entry(
            fix.human_dm_actor,
            create_payload,
            idempotency_key="unauth-mismatch-campaign",
            campaign_id=uuid4(),
        )
    assert _snapshot(fix.engine, fix.campaign_id) == snap_before

    with pytest.raises(CampaignRuntimeValidationError, match="does not match actor room_id"):
        world_service.create_world_entry(
            fix.human_dm_actor,
            create_payload,
            idempotency_key="unauth-mismatch-room",
            room_id=uuid4(),
        )
    assert _snapshot(fix.engine, fix.campaign_id) == snap_before


# ---------------------------------------------------------------------------
# 6. grant_character_knowledge Validation and Secrecy Projection
# ---------------------------------------------------------------------------


def test_grant_character_knowledge_validation_and_secrecy(
    fix: ActiveFixture,
    world_service: CampaignWorldService,
) -> None:
    actor = fix.human_dm_actor

    entry = world_service.create_world_entry(
        actor,
        RuntimeWorldEntryCreate(
            kind="secret",
            title="Ancient Cipher",
            body="Reads: The key is under the stone altar.",
            visibility="dm_only",
        ),
        idempotency_key="secret-cipher-1",
    )

    # Validation errors
    with pytest.raises(RuntimeEntryVisibilityError, match="at least one character recipient"):
        world_service.grant_character_knowledge(
            actor,
            GrantCharacterKnowledgeIntent(
                entry_id=entry.id,
                expected_revision=1,
                character_recipient_ids=(),
            ),
            idempotency_key="grant-fail-empty",
        )

    with pytest.raises(RuntimeEntryVisibilityError, match="must be unique"):
        world_service.grant_character_knowledge(
            actor,
            GrantCharacterKnowledgeIntent(
                entry_id=entry.id,
                expected_revision=1,
                character_recipient_ids=(fix.char_1_id, fix.char_1_id),
            ),
            idempotency_key="grant-fail-dup",
        )

    with pytest.raises(CampaignRuntimeValidationError, match="does not belong to room"):
        world_service.grant_character_knowledge(
            actor,
            GrantCharacterKnowledgeIntent(
                entry_id=entry.id,
                expected_revision=1,
                character_recipient_ids=(uuid4(),),
            ),
            idempotency_key="grant-fail-foreign-char",
        )

    # Valid grant to character 1
    granted = world_service.grant_character_knowledge(
        actor,
        GrantCharacterKnowledgeIntent(
            entry_id=entry.id,
            expected_revision=1,
            character_recipient_ids=(fix.char_1_id,),
        ),
        idempotency_key="grant-valid-1",
    )
    assert granted.visibility == "character"
    assert granted.character_recipient_ids == (fix.char_1_id,)

    # Player 1 (controlling char_1) can read the entry
    p1_view = fix.service.get_active(fix.human_player_1_actor, entry.id)
    assert isinstance(p1_view, RuntimeWorldEntryPlayerView)
    assert p1_view.title == "Ancient Cipher"
    assert p1_view.body == "Reads: The key is under the stone altar."

    # Player 2 (controlling char_2, not char_1) cannot see the entry (404)
    with pytest.raises(CampaignRuntimeNotFoundError):
        fix.service.get_active(fix.ai_player_2_actor, entry.id)


# ---------------------------------------------------------------------------
# 7. set_needs_review Toggling and Read Availability
# ---------------------------------------------------------------------------


def test_set_needs_review_entry_and_override_does_not_block_reads(
    fix: ActiveFixture,
    world_service: CampaignWorldService,
) -> None:
    actor = fix.human_dm_actor

    # --- Entry needs_review ---
    entry = world_service.create_world_entry(
        actor,
        RuntimeWorldEntryCreate(
            kind="npc",
            title="Mysterious Traveler",
            body="Claims to be from the future.",
            needs_review=False,
        ),
        idempotency_key="nr-test-entry-create",
    )
    assert entry.needs_review is False

    # Set needs_review = True
    nr_true_entry = world_service.set_needs_review(
        actor,
        SetEntryNeedsReviewIntent(
            entry_id=entry.id,
            expected_revision=1,
            needs_review=True,
        ),
        idempotency_key="nr-test-entry-set-true",
    )
    assert isinstance(nr_true_entry, RuntimeWorldEntryDmView)
    assert nr_true_entry.needs_review is True
    assert nr_true_entry.revision == 2

    # Subsequent reads are NOT blocked
    read_active = fix.service.get_active(actor, entry.id)
    assert isinstance(read_active, RuntimeWorldEntryDmView)
    assert read_active.needs_review is True

    listed_active = fix.service.list_active(actor)
    assert any(e.id == entry.id for e in listed_active)

    # Set needs_review = False
    nr_false_entry = world_service.set_needs_review(
        actor,
        SetEntryNeedsReviewIntent(
            entry_id=entry.id,
            expected_revision=2,
            needs_review=False,
        ),
        idempotency_key="nr-test-entry-set-false",
    )
    assert isinstance(nr_false_entry, RuntimeWorldEntryDmView)
    assert nr_false_entry.needs_review is False
    assert nr_false_entry.revision == 3

    # --- Override needs_review ---
    override = world_service.set_adventure_override(
        actor,
        SetAdventureOverrideIntent(
            adventure_entry_id=fix.adv_entry_id,
            state={"dm_summary": "Passage collapsed."},
            needs_review=False,
        ),
        idempotency_key="nr-test-override-create",
    )
    assert override.needs_review is False

    # Set override needs_review = True
    nr_true_ov = world_service.set_needs_review(
        actor,
        SetOverrideNeedsReviewIntent(
            adventure_entry_id=fix.adv_entry_id,
            expected_override_id=override.id,
            expected_revision=1,
            needs_review=True,
        ),
        idempotency_key="nr-test-override-set-true",
    )
    assert isinstance(nr_true_ov, CampaignAdventureOverride)
    assert nr_true_ov.needs_review is True
    assert nr_true_ov.revision == 2

    # Subsequent override reads are NOT blocked
    read_ov = fix.service.get_override_active(actor, fix.adv_entry_id)
    assert read_ov.needs_review is True

    listed_ov = fix.service.list_overrides_active(actor)
    assert any(o.adventure_entry_id == fix.adv_entry_id for o in listed_ov)

    # Set override needs_review = False
    nr_false_ov = world_service.set_needs_review(
        actor,
        SetOverrideNeedsReviewIntent(
            adventure_entry_id=fix.adv_entry_id,
            expected_override_id=override.id,
            expected_revision=2,
            needs_review=False,
        ),
        idempotency_key="nr-test-override-set-false",
    )
    assert isinstance(nr_false_ov, CampaignAdventureOverride)
    assert nr_false_ov.needs_review is False
    assert nr_false_ov.revision == 3


# ---------------------------------------------------------------------------
# 8. Runtime Item Holder Changes Do Not Touch Character inventory_state
# ---------------------------------------------------------------------------


def test_runtime_item_holder_does_not_touch_character_inventory_state(
    fix: ActiveFixture,
    world_service: CampaignWorldService,
) -> None:
    actor = fix.human_dm_actor

    # Snapshot character record before item creation
    with fix.engine.connect() as conn:
        char_row_before = conn.execute(
            select(characters).where(characters.c.id == fix.char_1_id)
        ).mappings().one()

    # Create Runtime Item with holder = character
    item_view = world_service.create_world_entry(
        actor,
        RuntimeWorldEntryCreate(
            kind="item",
            title="Silver Longsword",
            body="A finely crafted blade.",
            state={
                "kind": "item",
                "holder_ref": {
                    "kind": "character",
                    "target_id": str(fix.char_1_id),
                },
            },
        ),
        idempotency_key="item-char-holder-1",
    )
    assert item_view.kind == "item"

    # Update item to different holder (party)
    world_service.update_world_entry(
        actor,
        item_view.id,
        RuntimeWorldEntryPatch(
            expected_revision=1,
            state={
                "kind": "item",
                "holder_ref": {
                    "kind": "party",
                },
            },
        ),
        idempotency_key="item-char-holder-2",
    )

    # Verify character row is completely untouched
    with fix.engine.connect() as conn:
        char_row_after = conn.execute(
            select(characters).where(characters.c.id == fix.char_1_id)
        ).mappings().one()

    assert dict(char_row_before) == dict(char_row_after)


# ---------------------------------------------------------------------------
# Override Update Semantics & Field Preservation
# ---------------------------------------------------------------------------


def test_set_adventure_override_intent_validation() -> None:
    entry_id = uuid4()
    ov_id = uuid4()

    # Create mode: expected_revision must be absent
    with pytest.raises(ValidationError, match="expected_revision must be absent"):
        SetAdventureOverrideIntent(
            adventure_entry_id=entry_id,
            expected_revision=1,
        )

    # Create mode: state cannot be None if explicitly supplied
    with pytest.raises(ValidationError, match="state cannot be None"):
        SetAdventureOverrideIntent(
            adventure_entry_id=entry_id,
            state=None,
        )

    # Create mode: defaults applied when omitted
    create_intent = SetAdventureOverrideIntent(adventure_entry_id=entry_id)
    assert create_intent.expected_override_id is None
    assert create_intent.expected_revision is None
    assert create_intent.state == {}
    assert create_intent.note is None
    assert create_intent.needs_review is False

    # Update mode: expected_revision is required
    with pytest.raises(ValidationError, match="expected_revision is required"):
        SetAdventureOverrideIntent(
            adventure_entry_id=entry_id,
            expected_override_id=ov_id,
            note="Note",
        )

    # Update mode: expected_revision must be >= 1
    with pytest.raises(ValidationError, match="expected_revision must be at least 1"):
        SetAdventureOverrideIntent(
            adventure_entry_id=entry_id,
            expected_override_id=ov_id,
            expected_revision=0,
            note="Note",
        )

    # Update mode: at least one of state/note/needs_review must be provided
    with pytest.raises(ValidationError, match="at least one of state, note, or needs_review"):
        SetAdventureOverrideIntent(
            adventure_entry_id=entry_id,
            expected_override_id=ov_id,
            expected_revision=1,
        )

    # Update mode: state cannot be None
    with pytest.raises(ValidationError, match="state cannot be None on update"):
        SetAdventureOverrideIntent(
            adventure_entry_id=entry_id,
            expected_override_id=ov_id,
            expected_revision=1,
            state=None,
        )

    # Update mode: needs_review cannot be None
    with pytest.raises(ValidationError, match="needs_review cannot be None on update"):
        SetAdventureOverrideIntent(
            adventure_entry_id=entry_id,
            expected_override_id=ov_id,
            expected_revision=1,
            needs_review=None,
        )

    # Update mode: explicit note=None is allowed (clearing note)
    clear_note_intent = SetAdventureOverrideIntent(
        adventure_entry_id=entry_id,
        expected_override_id=ov_id,
        expected_revision=1,
        note=None,
    )
    assert clear_note_intent.note is None
    assert "note" in clear_note_intent.model_fields_set

    # Update mode: updating only note
    note_intent = SetAdventureOverrideIntent(
        adventure_entry_id=entry_id,
        expected_override_id=ov_id,
        expected_revision=1,
        note="New note",
    )
    assert note_intent.note == "New note"
    assert "note" in note_intent.model_fields_set
    assert "state" not in note_intent.model_fields_set
    assert "needs_review" not in note_intent.model_fields_set


@pytest.mark.parametrize("actor_role", ["human_dm", "ai_dm"])
def test_set_adventure_override_update_preserves_omitted_fields_active_human_and_ai(
    fix: ActiveFixture,
    world_service: CampaignWorldService,
    actor_role: Literal["human_dm", "ai_dm"],
) -> None:
    _link_ai_campaign_adventure(fix)
    actor = fix.human_dm_actor if actor_role == "human_dm" else fix.ai_dm_actor

    # 1. Create initial override with state, note, and needs_review=True
    initial_state = {"dm_summary": "Initial summary", "read_aloud": "Initial read aloud"}
    created = world_service.set_adventure_override(
        actor,
        SetAdventureOverrideIntent(
            adventure_entry_id=fix.adv_entry_id,
            state=initial_state,
            note="Initial note",
            needs_review=True,
        ),
        idempotency_key=f"{actor_role}-ov-pres-create",
    )
    assert created.revision == 1
    assert created.state_json == initial_state
    assert created.note == "Initial note"
    assert created.needs_review is True

    # 2. Update ONLY note -> state and needs_review MUST be preserved
    updated_note = world_service.set_adventure_override(
        actor,
        SetAdventureOverrideIntent(
            adventure_entry_id=fix.adv_entry_id,
            expected_override_id=created.id,
            expected_revision=1,
            note="Updated note only",
        ),
        idempotency_key=f"{actor_role}-ov-pres-update-note",
    )
    assert updated_note.id == created.id
    assert updated_note.revision == 2
    assert updated_note.note == "Updated note only"
    assert updated_note.state_json == initial_state  # Preserved!
    assert updated_note.needs_review is True  # Preserved!

    # 3. Update ONLY note=None (explicit clearing) -> state and needs_review MUST be preserved
    cleared_note = world_service.set_adventure_override(
        actor,
        SetAdventureOverrideIntent(
            adventure_entry_id=fix.adv_entry_id,
            expected_override_id=created.id,
            expected_revision=2,
            note=None,
        ),
        idempotency_key=f"{actor_role}-ov-pres-clear-note",
    )
    assert cleared_note.id == created.id
    assert cleared_note.revision == 3
    assert cleared_note.note is None  # Cleared!
    assert cleared_note.state_json == initial_state  # Preserved!
    assert cleared_note.needs_review is True  # Preserved!

    # 4. Update ONLY state -> note and needs_review MUST be preserved
    new_state = {"dm_summary": "Updated summary only"}
    updated_state = world_service.set_adventure_override(
        actor,
        SetAdventureOverrideIntent(
            adventure_entry_id=fix.adv_entry_id,
            expected_override_id=created.id,
            expected_revision=3,
            state=new_state,
        ),
        idempotency_key=f"{actor_role}-ov-pres-update-state",
    )
    assert updated_state.id == created.id
    assert updated_state.revision == 4
    assert updated_state.state_json == new_state  # Updated!
    assert updated_state.note is None  # Preserved!
    assert updated_state.needs_review is True  # Preserved!


def test_set_adventure_override_update_preserves_omitted_fields_management(
    fix: ActiveFixture,
    world_service: CampaignWorldService,
) -> None:
    # Create management campaign outside active session
    with fix.engine.begin() as conn:
        adv_id = conn.scalar(
            select(campaign_adventure_links.c.adventure_id).where(
                campaign_adventure_links.c.campaign_id == fix.campaign_id
            )
        )
        assert adv_id is not None
        mgmt_campaign_id = uuid4()
        now = datetime.now(timezone.utc)
        conn.execute(
            insert(campaigns).values(
                id=mgmt_campaign_id,
                room_id=fix.room_id,
                name="Management Override Pres Test",
                ruleset="dnd-5e-2014",
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
        conn.execute(
            insert(campaign_adventure_links).values(
                campaign_id=mgmt_campaign_id,
                adventure_id=adv_id,
                sort_order=0,
                attached_at=datetime.now(timezone.utc),
            )
        )

    # 1. Create initial override in management
    initial_state = {"dm_summary": "Mgmt initial summary"}
    created = world_service.set_adventure_override(
        fix.owner_context,
        SetAdventureOverrideIntent(
            adventure_entry_id=fix.adv_entry_id,
            state=initial_state,
            note="Mgmt initial note",
            needs_review=True,
        ),
        idempotency_key="mgmt-ov-pres-create",
        campaign_id=mgmt_campaign_id,
    )
    assert created.revision == 1
    assert created.state_json == initial_state
    assert created.note == "Mgmt initial note"
    assert created.needs_review is True

    # 2. Update ONLY note in management -> state and needs_review MUST be preserved
    updated_note = world_service.set_adventure_override(
        fix.owner_context,
        SetAdventureOverrideIntent(
            adventure_entry_id=fix.adv_entry_id,
            expected_override_id=created.id,
            expected_revision=1,
            note="Mgmt updated note only",
        ),
        idempotency_key="mgmt-ov-pres-update-note",
        campaign_id=mgmt_campaign_id,
    )
    assert updated_note.id == created.id
    assert updated_note.revision == 2
    assert updated_note.note == "Mgmt updated note only"
    assert updated_note.state_json == initial_state  # Preserved!
    assert updated_note.needs_review is True  # Preserved!

    # Audit check: human actor audit in campaign_world_mutations
    with fix.engine.connect() as conn:
        mut_row = conn.execute(
            select(campaign_world_mutations).where(
                campaign_world_mutations.c.campaign_id == mgmt_campaign_id,
                campaign_world_mutations.c.idempotency_key == "mgmt-ov-pres-update-note",
            )
        ).mappings().one()
        assert mut_row["created_by_actor_kind"] == "human"
        assert mut_row["created_by_actor_id"] == fix.owner_context.access_session_id
        # Zero session events and zero notifications
        mgmt_ev_count = conn.scalar(
            select(func.count()).select_from(session_events).where(
                session_events.c.kind.like("world.%"),
                session_events.c.session_id == fix.session_id,  # active session
            )
        )
    assert len(fix.notifier.notifications) == 0

