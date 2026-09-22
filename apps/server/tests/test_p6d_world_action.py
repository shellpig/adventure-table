from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import Connection, Engine, func, insert, select

from app.api.rooms.table_event_wait import ProcessLocalTableEventNotifier
from app.domain.campaign_runtime import (
    ArchiveWorldEntryChange,
    CampaignAdventureOverride,
    CampaignRuntimeAuthorityError,
    CampaignRuntimeContext,
    CampaignRuntimeContextPatch,
    CampaignRuntimeIdempotencyConflictError,
    CampaignRuntimeNotFoundError,
    CampaignRuntimeRevisionConflictError,
    CampaignRuntimeService,
    CampaignRuntimeSessionNotActiveError,
    CampaignRuntimeValidationError,
    CampaignWorldService,
    ClearAdventureOverrideChange,
    ClearAdventureOverrideIntent,
    CreateWorldEntryChange,
    ResolveWorldActionRequest,
    ResolveWorldActionResult,
    RuntimeWorldEntryCreate,
    RuntimeWorldEntryDmView,
    RuntimeWorldEntryPatch,
    SetAdventureOverrideChange,
    SetAdventureOverrideIntent,
    SetCurrentContextChange,
    UpdateWorldEntryChange,
)
from app.domain.campaign_runtime.entry_mutations import RESERVED_INTERNAL_IDEMPOTENCY_PREFIX
from app.domain.rooms.table_events import (
    TableActorContext,
    TableEventService,
)
from app.persistence.adventures.tables import campaign_adventure_links
from app.persistence.campaign_runtime.tables import (
    campaign_adventure_overrides,
    campaign_runtime_context,
    campaign_world_entries,
    campaign_world_mutations,
)
from app.persistence.rooms.exploration_messages import (
    ExplorationMessageRepository,
    session_messages,
)
from app.persistence.rooms.table_runtime import (
    StoredTableActorBinding,
    StoredTableEvent,
    TableEventRepository,
    session_events,
    session_table_runtime,
)
from tests.p6_active_fixture import (
    ActiveFixture,
    _build_active_fixture,
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


def _full_state_snapshot(engine: Engine, campaign_id: UUID, session_id: UUID) -> dict[str, object]:
    with engine.connect() as conn:
        return {
            "entries": conn.scalar(
                select(func.count()).select_from(campaign_world_entries).where(
                    campaign_world_entries.c.campaign_id == campaign_id
                )
            ) or 0,
            "entry_rows": [
                dict(r)
                for r in conn.execute(
                    select(campaign_world_entries)
                    .where(campaign_world_entries.c.campaign_id == campaign_id)
                    .order_by(campaign_world_entries.c.id)
                ).mappings().all()
            ],
            "overrides": conn.scalar(
                select(func.count()).select_from(campaign_adventure_overrides).where(
                    campaign_adventure_overrides.c.campaign_id == campaign_id
                )
            ) or 0,
            "override_rows": [
                dict(r)
                for r in conn.execute(
                    select(campaign_adventure_overrides)
                    .where(campaign_adventure_overrides.c.campaign_id == campaign_id)
                    .order_by(campaign_adventure_overrides.c.adventure_entry_id)
                ).mappings().all()
            ],
            "contexts": conn.scalar(
                select(func.count()).select_from(campaign_runtime_context).where(
                    campaign_runtime_context.c.campaign_id == campaign_id
                )
            ) or 0,
            "context_rows": [
                dict(r)
                for r in conn.execute(
                    select(campaign_runtime_context)
                    .where(campaign_runtime_context.c.campaign_id == campaign_id)
                ).mappings().all()
            ],
            "mutations": conn.scalar(
                select(func.count()).select_from(campaign_world_mutations).where(
                    campaign_world_mutations.c.campaign_id == campaign_id
                )
            ) or 0,
            "events": conn.scalar(
                select(func.count()).select_from(session_events).where(
                    session_events.c.session_id == session_id
                )
            ) or 0,
            "messages": conn.scalar(
                select(func.count()).select_from(session_messages).where(
                    session_messages.c.session_id == session_id
                )
            ) or 0,
            "cursor": conn.scalar(
                select(session_table_runtime.c.last_event_seq).where(
                    session_table_runtime.c.session_id == session_id
                )
            ) or 0,
            "runtime_revision": conn.scalar(
                select(session_table_runtime.c.revision).where(
                    session_table_runtime.c.session_id == session_id
                )
            ) or 0,
        }


# ---------------------------------------------------------------------------
# 1. Human / AI DM Parity: Event Shape, Order, Visibility & Safe Payload
# ---------------------------------------------------------------------------


def test_human_and_ai_dm_parity_for_world_action(
    fix: ActiveFixture,
    world_service: CampaignWorldService,
) -> None:
    _link_ai_campaign_adventure(fix)

    # A. Entry Create Change
    fact_create = CreateWorldEntryChange(
        payload=RuntimeWorldEntryCreate(
            kind="fact",
            body="A hidden archway stands in the shadows.",
            dm_notes="Requires DC 14 Investigation to notice runes.",
            visibility="public",
        )
    )
    req_human = ResolveWorldActionRequest(
        change=fact_create,
        narration="You notice a hidden archway standing in the shadows.",
    )
    req_ai = ResolveWorldActionRequest(
        change=fact_create,
        narration="You notice a hidden archway standing in the shadows.",
    )

    res_human = world_service.resolve_world_action(
        fix.human_dm_actor, req_human, idempotency_key="parity-fact-human"
    )
    res_ai = world_service.resolve_world_action(
        fix.ai_dm_actor, req_ai, idempotency_key="parity-fact-ai"
    )

    assert res_human.action == res_ai.action == "create_entry"
    assert res_human.entry is not None and res_ai.entry is not None
    assert res_human.entry.kind == res_ai.entry.kind == "fact"
    assert res_human.entry.visibility == res_ai.entry.visibility == "public"

    with fix.engine.connect() as conn:
        human_evs = conn.execute(
            select(session_events)
            .where(session_events.c.session_id == fix.session_id)
            .order_by(session_events.c.seq)
        ).mappings().all()
        ai_evs = conn.execute(
            select(session_events)
            .where(session_events.c.session_id == fix.ai_session_id)
            .order_by(session_events.c.seq)
        ).mappings().all()

    assert len(human_evs) == len(ai_evs) == 2
    assert human_evs[0]["kind"] == ai_evs[0]["kind"] == "world.action.resolved"
    assert human_evs[0]["visibility"] == ai_evs[0]["visibility"] == "public"
    assert human_evs[0]["payload"]["action"] == ai_evs[0]["payload"]["action"] == "create_entry"
    assert human_evs[0]["payload"]["entry_kind"] == ai_evs[0]["payload"]["entry_kind"] == "fact"
    assert human_evs[0]["payload"]["revision"] == ai_evs[0]["payload"]["revision"] == 1
    # Secret dm_notes and body must NOT be in event payload
    assert "dm_notes" not in human_evs[0]["payload"]
    assert "body" not in human_evs[0]["payload"]
    assert "dm_notes" not in ai_evs[0]["payload"]
    assert "body" not in ai_evs[0]["payload"]

    assert human_evs[1]["kind"] == ai_evs[1]["kind"] == "exploration.narration"
    assert human_evs[1]["visibility"] == ai_evs[1]["visibility"] == "public"

    # B. Override Set Change
    override_change = SetAdventureOverrideChange(
        intent=SetAdventureOverrideIntent(
            adventure_entry_id=fix.adv_entry_id,
            state={"dm_summary": "Flooded during rainstorm."},
            note="Flooded during rainstorm.",
        )
    )
    ov_res_human = world_service.resolve_world_action(
        fix.human_dm_actor,
        ResolveWorldActionRequest(change=override_change),
        idempotency_key="parity-override-human",
    )
    ov_res_ai = world_service.resolve_world_action(
        fix.ai_dm_actor,
        ResolveWorldActionRequest(change=override_change),
        idempotency_key="parity-override-ai",
    )
    assert ov_res_human.action == ov_res_ai.action == "set_override"
    assert ov_res_human.override is not None and ov_res_ai.override is not None
    assert ov_res_human.override.state_json == ov_res_ai.override.state_json == {"dm_summary": "Flooded during rainstorm."}

    with fix.engine.connect() as conn:
        human_ov_ev = conn.execute(
            select(session_events)
            .where(
                session_events.c.session_id == fix.session_id,
                session_events.c.seq == ov_res_human.action_event_seq,
            )
        ).mappings().one()
        ai_ov_ev = conn.execute(
            select(session_events)
            .where(
                session_events.c.session_id == fix.ai_session_id,
                session_events.c.seq == ov_res_ai.action_event_seq,
            )
        ).mappings().one()

    assert human_ov_ev["kind"] == ai_ov_ev["kind"] == "world.action.resolved"
    assert human_ov_ev["visibility"] == ai_ov_ev["visibility"] == "dm_only"
    assert human_ov_ev["payload"]["action"] == ai_ov_ev["payload"]["action"] == "set_override"
    assert human_ov_ev["payload"]["revision"] == ai_ov_ev["payload"]["revision"] == 1
    # Secret note and state must NOT be in event payload
    assert "note" not in human_ov_ev["payload"]
    assert "state" not in human_ov_ev["payload"]

    # C. Context Update Change
    context_change = SetCurrentContextChange(
        patch=CampaignRuntimeContextPatch(
            expected_revision=0,
            current_situation="The dungeon begins to collapse.",
        )
    )
    ctx_res_human = world_service.resolve_world_action(
        fix.human_dm_actor,
        ResolveWorldActionRequest(change=context_change),
        idempotency_key="parity-context-human",
    )
    ctx_res_ai = world_service.resolve_world_action(
        fix.ai_dm_actor,
        ResolveWorldActionRequest(change=context_change),
        idempotency_key="parity-context-ai",
    )
    assert ctx_res_human.action == ctx_res_ai.action == "set_context"
    assert ctx_res_human.context is not None and ctx_res_ai.context is not None
    assert (
        ctx_res_human.context.current_situation
        == ctx_res_ai.context.current_situation
        == "The dungeon begins to collapse."
    )

    # D. Entry Update Change
    assert res_human.entry is not None and res_ai.entry is not None
    update_change_human = UpdateWorldEntryChange(
        entry_id=res_human.entry.id,
        patch=RuntimeWorldEntryPatch(
            expected_revision=1,
            body="A hidden archway stands in the shadows, glowing faintly.",
            dm_notes="Runes glow with faint abjuration aura.",
        ),
    )
    update_change_ai = UpdateWorldEntryChange(
        entry_id=res_ai.entry.id,
        patch=RuntimeWorldEntryPatch(
            expected_revision=1,
            body="A hidden archway stands in the shadows, glowing faintly.",
            dm_notes="Runes glow with faint abjuration aura.",
        ),
    )
    up_res_human = world_service.resolve_world_action(
        fix.human_dm_actor,
        ResolveWorldActionRequest(change=update_change_human),
        idempotency_key="parity-update-human",
    )
    up_res_ai = world_service.resolve_world_action(
        fix.ai_dm_actor,
        ResolveWorldActionRequest(change=update_change_ai),
        idempotency_key="parity-update-ai",
    )
    assert up_res_human.action == up_res_ai.action == "update_entry"
    assert up_res_human.entry is not None and up_res_ai.entry is not None
    assert up_res_human.entry.revision == up_res_ai.entry.revision == 2
    assert up_res_human.entry.body == up_res_ai.entry.body == "A hidden archway stands in the shadows, glowing faintly."

    with fix.engine.connect() as conn:
        up_human_ev = conn.execute(
            select(session_events).where(
                session_events.c.session_id == fix.session_id,
                session_events.c.seq == up_res_human.action_event_seq,
            )
        ).mappings().one()
        up_ai_ev = conn.execute(
            select(session_events).where(
                session_events.c.session_id == fix.ai_session_id,
                session_events.c.seq == up_res_ai.action_event_seq,
            )
        ).mappings().one()

    assert up_human_ev["payload"]["action"] == up_ai_ev["payload"]["action"] == "update_entry"
    assert up_human_ev["payload"]["revision"] == up_ai_ev["payload"]["revision"] == 2
    assert "body" not in up_human_ev["payload"]
    assert "dm_notes" not in up_human_ev["payload"]
    assert "body" not in up_ai_ev["payload"]
    assert "dm_notes" not in up_ai_ev["payload"]

    # E. Entry Archive Change
    archive_change_human = ArchiveWorldEntryChange(
        entry_id=res_human.entry.id,
        expected_revision=2,
    )
    archive_change_ai = ArchiveWorldEntryChange(
        entry_id=res_ai.entry.id,
        expected_revision=2,
    )
    arc_res_human = world_service.resolve_world_action(
        fix.human_dm_actor,
        ResolveWorldActionRequest(change=archive_change_human),
        idempotency_key="parity-archive-human",
    )
    arc_res_ai = world_service.resolve_world_action(
        fix.ai_dm_actor,
        ResolveWorldActionRequest(change=archive_change_ai),
        idempotency_key="parity-archive-ai",
    )
    assert arc_res_human.action == arc_res_ai.action == "archive_entry"
    assert arc_res_human.entry is not None and arc_res_ai.entry is not None
    assert arc_res_human.entry.revision == arc_res_ai.entry.revision == 3
    assert arc_res_human.entry.archived_at is not None and arc_res_ai.entry.archived_at is not None

    with fix.engine.connect() as conn:
        arc_human_ev = conn.execute(
            select(session_events).where(
                session_events.c.session_id == fix.session_id,
                session_events.c.seq == arc_res_human.action_event_seq,
            )
        ).mappings().one()
        arc_ai_ev = conn.execute(
            select(session_events).where(
                session_events.c.session_id == fix.ai_session_id,
                session_events.c.seq == arc_res_ai.action_event_seq,
            )
        ).mappings().one()

    assert arc_human_ev["payload"]["action"] == arc_ai_ev["payload"]["action"] == "archive_entry"
    assert arc_human_ev["payload"]["revision"] == arc_ai_ev["payload"]["revision"] == 3

    # F. Override Clear Change
    assert ov_res_human.override is not None and ov_res_ai.override is not None
    clear_change_human = ClearAdventureOverrideChange(
        intent=ClearAdventureOverrideIntent(
            adventure_entry_id=fix.adv_entry_id,
            expected_override_id=ov_res_human.override.id,
            expected_revision=1,
        )
    )
    clear_change_ai = ClearAdventureOverrideChange(
        intent=ClearAdventureOverrideIntent(
            adventure_entry_id=fix.adv_entry_id,
            expected_override_id=ov_res_ai.override.id,
            expected_revision=1,
        )
    )
    clr_res_human = world_service.resolve_world_action(
        fix.human_dm_actor,
        ResolveWorldActionRequest(change=clear_change_human),
        idempotency_key="parity-clear-human",
    )
    clr_res_ai = world_service.resolve_world_action(
        fix.ai_dm_actor,
        ResolveWorldActionRequest(change=clear_change_ai),
        idempotency_key="parity-clear-ai",
    )
    assert clr_res_human.action == clr_res_ai.action == "clear_override"
    assert clr_res_human.override is not None and clr_res_ai.override is not None
    assert clr_res_human.override.revision == clr_res_ai.override.revision == 1

    with fix.engine.connect() as conn:
        clr_human_ev = conn.execute(
            select(session_events).where(
                session_events.c.session_id == fix.session_id,
                session_events.c.seq == clr_res_human.action_event_seq,
            )
        ).mappings().one()
        clr_ai_ev = conn.execute(
            select(session_events).where(
                session_events.c.session_id == fix.ai_session_id,
                session_events.c.seq == clr_res_ai.action_event_seq,
            )
        ).mappings().one()

    assert clr_human_ev["payload"]["action"] == clr_ai_ev["payload"]["action"] == "clear_override"
    assert clr_human_ev["payload"]["revision"] == clr_ai_ev["payload"]["revision"] == 1


# ---------------------------------------------------------------------------
# 2. Success With Narration: Order, Events, session_messages, No world.narration
# ---------------------------------------------------------------------------


def test_success_with_narration(
    fix: ActiveFixture,
    world_service: CampaignWorldService,
) -> None:
    req = ResolveWorldActionRequest(
        change=CreateWorldEntryChange(
            payload=RuntimeWorldEntryCreate(
                kind="scene",
                title="Grand Hall",
                body="A vast chamber supported by marble pillars.",
                visibility="public",
            )
        ),
        narration="You step across the threshold into a vast hall of marble pillars.",
    )

    res = world_service.resolve_world_action(
        fix.human_dm_actor, req, idempotency_key="success-narration-1"
    )

    assert res.action == "create_entry"
    assert res.entry is not None
    assert res.entry.kind == "scene"
    assert res.narration == "You step across the threshold into a vast hall of marble pillars."
    assert res.action_event_id is not None
    assert res.narration_event_id is not None
    assert res.action_event_seq < res.narration_event_seq

    with fix.engine.connect() as conn:
        evs = conn.execute(
            select(session_events)
            .where(session_events.c.session_id == fix.session_id)
            .order_by(session_events.c.seq)
        ).mappings().all()

        msgs = conn.execute(
            select(session_messages)
            .where(session_messages.c.session_id == fix.session_id)
        ).mappings().all()

    assert len(evs) == 2
    assert evs[0]["id"] == res.action_event_id
    assert evs[0]["kind"] == "world.action.resolved"
    assert evs[0]["seq"] == res.action_event_seq

    assert evs[1]["id"] == res.narration_event_id
    assert evs[1]["kind"] == "exploration.narration"
    assert evs[1]["seq"] == res.narration_event_seq
    assert evs[1]["payload"] == {
        "type": "narration",
        "text": "You step across the threshold into a vast hall of marble pillars.",
        "source_command": None,
    }

    # Exactly one matching session_messages row
    assert len(msgs) == 1
    assert msgs[0]["event_id"] == res.narration_event_id
    assert msgs[0]["kind"] == "narration"
    assert msgs[0]["text"] == "You step across the threshold into a vast hall of marble pillars."
    assert msgs[0]["execution_mode"] == "self"
    assert msgs[0]["visibility"] == "public"

    # Verify no world.narration exists anywhere in events or messages
    for ev in evs:
        assert ev["kind"] != "world.narration"
    for msg in msgs:
        assert msg["kind"] != "world.narration"

    # Notifier called once after commit
    assert fix.notifier.notifications == [fix.session_id]


# ---------------------------------------------------------------------------
# 3. Success Without Narration: World Event Only, Mutation Persists
# ---------------------------------------------------------------------------


def test_success_without_narration(
    fix: ActiveFixture,
    world_service: CampaignWorldService,
) -> None:
    req = ResolveWorldActionRequest(
        change=CreateWorldEntryChange(
            payload=RuntimeWorldEntryCreate(
                kind="quest",
                title="Rescue the Captive",
                body="Find the lost prisoner in the lower cells.",
                visibility="public",
            )
        ),
        narration=None,
    )

    res = world_service.resolve_world_action(
        fix.human_dm_actor, req, idempotency_key="success-no-narration-1"
    )

    assert res.action == "create_entry"
    assert res.entry is not None
    assert res.narration is None
    assert res.action_event_id is not None
    assert res.narration_event_id is None
    assert res.narration_event_seq is None

    with fix.engine.connect() as conn:
        evs = conn.execute(
            select(session_events).where(session_events.c.session_id == fix.session_id)
        ).mappings().all()
        msgs = conn.execute(
            select(session_messages).where(session_messages.c.session_id == fix.session_id)
        ).mappings().all()
        entry_row = conn.execute(
            select(campaign_world_entries).where(
                campaign_world_entries.c.id == res.entry.id
            )
        ).mappings().one()
        mutation_row = conn.execute(
            select(campaign_world_mutations).where(
                campaign_world_mutations.c.campaign_id == fix.campaign_id,
                campaign_world_mutations.c.idempotency_key == "success-no-narration-1",
            )
        ).mappings().one()

    # Exactly 1 event, 0 messages
    assert len(evs) == 1
    assert evs[0]["kind"] == "world.action.resolved"
    assert len(msgs) == 0

    # World mutation persisted
    assert entry_row["title"] == "Rescue the Captive"
    assert mutation_row["action_kind"] == "world_action.resolve"
    assert mutation_row["target_id"] == res.entry.id

    # Notifier called once
    assert fix.notifier.notifications == [fix.session_id]


# ---------------------------------------------------------------------------
# 4. Invalid Override / Reference / Revision: Complete Zero-Side-Effect Rollback
# ---------------------------------------------------------------------------


def test_invalid_world_change_with_narration_rolls_back_everything(
    fix: ActiveFixture,
    world_service: CampaignWorldService,
) -> None:
    snap_before = _full_state_snapshot(fix.engine, fix.campaign_id, fix.session_id)

    # 1. Stale revision on override update with definitive narration
    fake_override_id = uuid4()
    req = ResolveWorldActionRequest(
        change=SetAdventureOverrideChange(
            intent=SetAdventureOverrideIntent(
                adventure_entry_id=fix.adv_entry_id,
                expected_override_id=fake_override_id,
                expected_revision=99,
                state={"status": "destroyed"},
            )
        ),
        narration="The ancient door crumbles to dust under the magical surge.",
    )

    with pytest.raises(CampaignRuntimeNotFoundError):
        world_service.resolve_world_action(
            fix.human_dm_actor, req, idempotency_key="invalid-override-1"
        )

    snap_after = _full_state_snapshot(fix.engine, fix.campaign_id, fix.session_id)
    assert snap_before == snap_after
    assert len(fix.notifier.notifications) == 0

    # 2. Invalid holder reference on Item create with narration
    fake_holder_id = uuid4()
    req_item = ResolveWorldActionRequest(
        change=CreateWorldEntryChange(
            payload=RuntimeWorldEntryCreate(
                kind="item",
                title="Sunblade",
                body="A blade of pure radiant light.",
                state={
                    "holder_ref": {
                        "kind": "npc",
                        "target_id": str(fake_holder_id),
                    }
                },
            )
        ),
        narration="The warrior draws forth the glowing Sunblade.",
    )

    with pytest.raises(CampaignRuntimeValidationError):
        world_service.resolve_world_action(
            fix.human_dm_actor, req_item, idempotency_key="invalid-item-holder-1"
        )

    snap_after_2 = _full_state_snapshot(fix.engine, fix.campaign_id, fix.session_id)
    assert snap_before == snap_after_2
    assert len(fix.notifier.notifications) == 0


# ---------------------------------------------------------------------------
# 5. Forced Final Narration Projection Step Failure: Proves Atomic Rollback
# ---------------------------------------------------------------------------


def test_forced_narration_projection_failure_rolls_back_world_and_events(
    fix: ActiveFixture,
    world_service: CampaignWorldService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snap_before = _full_state_snapshot(fix.engine, fix.campaign_id, fix.session_id)

    orig_append_message = world_service.message_repo.append_message_in_transaction

    def failing_append_message(
        connection: Connection,
        *,
        binding: StoredTableActorBinding,
        message_kind: str,
        text: str,
        acting_seat_id: UUID,
        subject_seat_id: UUID | None,
        subject_character_id: UUID | None,
        execution_mode: str,
        visibility: str,
        recipient_seat_ids: tuple[UUID, ...],
        source_command: str | None,
        idempotency_key: str | None,
    ) -> StoredTableEvent:
        orig_append_message(
            connection,
            binding=binding,
            message_kind=message_kind,
            text=text,
            acting_seat_id=acting_seat_id,
            subject_seat_id=subject_seat_id,
            subject_character_id=subject_character_id,
            execution_mode=execution_mode,
            visibility=visibility,
            recipient_seat_ids=recipient_seat_ids,
            source_command=source_command,
            idempotency_key=idempotency_key,
        )
        raise RuntimeError("Forced simulation error in final projection step")

    monkeypatch.setattr(
        world_service.message_repo,
        "append_message_in_transaction",
        failing_append_message,
    )

    req = ResolveWorldActionRequest(
        change=CreateWorldEntryChange(
            payload=RuntimeWorldEntryCreate(
                kind="fact",
                body="The bridge is heavily guarded.",
                visibility="public",
            )
        ),
        narration="You see armed sentries stationed across the bridge.",
    )

    with pytest.raises(RuntimeError, match="Forced simulation error"):
        world_service.resolve_world_action(
            fix.human_dm_actor, req, idempotency_key="forced-fail-1"
        )

    snap_after = _full_state_snapshot(fix.engine, fix.campaign_id, fix.session_id)
    assert snap_before == snap_after
    assert len(fix.notifier.notifications) == 0


# ---------------------------------------------------------------------------
# 6. Same-Key Retry and Conflicts
# ---------------------------------------------------------------------------


def test_same_key_retry_and_conflicts(
    fix: ActiveFixture,
    world_service: CampaignWorldService,
) -> None:
    req = ResolveWorldActionRequest(
        change=CreateWorldEntryChange(
            payload=RuntimeWorldEntryCreate(
                kind="npc",
                title="Garrick",
                body="A grizzled veteran guard.",
                visibility="public",
            )
        ),
        narration="Garrick steps forward, resting his hand on his sword.",
    )

    # Initial execution
    res1 = world_service.resolve_world_action(
        fix.human_dm_actor, req, idempotency_key="act-retry-key-1"
    )
    assert res1.action == "create_entry"
    assert res1.entry is not None
    assert len(fix.notifier.notifications) == 1

    # Retry with same key and identical request
    res2 = world_service.resolve_world_action(
        fix.human_dm_actor, req, idempotency_key="act-retry-key-1"
    )

    # Identical result returned
    assert res1 == res2
    assert res1.model_dump() == res2.model_dump()

    # Still only 1 mutation, 1 action event, 1 narration event, 1 message, and NO second notify
    assert len(fix.notifier.notifications) == 1
    with fix.engine.connect() as conn:
        mutations = conn.execute(
            select(campaign_world_mutations).where(
                campaign_world_mutations.c.campaign_id == fix.campaign_id,
                campaign_world_mutations.c.idempotency_key == "act-retry-key-1",
            )
        ).mappings().all()
        events = conn.execute(
            select(session_events).where(session_events.c.session_id == fix.session_id)
        ).mappings().all()
        messages = conn.execute(
            select(session_messages).where(session_messages.c.session_id == fix.session_id)
        ).mappings().all()

    assert len(mutations) == 1
    assert len(events) == 2
    assert len(messages) == 1

    snap_after_success = _full_state_snapshot(fix.engine, fix.campaign_id, fix.session_id)

    # Conflict 1: Same key + DIFFERENT narration
    req_diff_narration = ResolveWorldActionRequest(
        change=req.change,
        narration="Garrick draws his sword and shouts an alarm!",
    )
    with pytest.raises(CampaignRuntimeIdempotencyConflictError):
        world_service.resolve_world_action(
            fix.human_dm_actor, req_diff_narration, idempotency_key="act-retry-key-1"
        )
    assert _full_state_snapshot(fix.engine, fix.campaign_id, fix.session_id) == snap_after_success
    assert len(fix.notifier.notifications) == 1

    # Conflict 2: Same key + DIFFERENT mutation
    req_diff_change = ResolveWorldActionRequest(
        change=CreateWorldEntryChange(
            payload=RuntimeWorldEntryCreate(
                kind="npc",
                title="Different Name",
                body="A different person entirely.",
                visibility="public",
            )
        ),
        narration=req.narration,
    )
    with pytest.raises(CampaignRuntimeIdempotencyConflictError):
        world_service.resolve_world_action(
            fix.human_dm_actor, req_diff_change, idempotency_key="act-retry-key-1"
        )
    assert _full_state_snapshot(fix.engine, fix.campaign_id, fix.session_id) == snap_after_success
    assert len(fix.notifier.notifications) == 1


# ---------------------------------------------------------------------------
# 7. Waiter Awakened by Post-Commit Notifier & Cursor Ordering
# ---------------------------------------------------------------------------


def test_wait_for_event_awakened_by_notifier_and_cursor_ordering(
    fix: ActiveFixture,
) -> None:
    async def _test() -> None:
        # Use real ProcessLocalTableEventNotifier to test live async waiter wakeup
        real_notifier = ProcessLocalTableEventNotifier()
        event_service = TableEventService(
            TableEventRepository(fix.engine),
            notifier=real_notifier,
        )
        runtime_service = CampaignRuntimeService(fix.engine, event_service)
        world_service = CampaignWorldService(runtime_service)

        # Start waiting as human_player_1
        wait_task = asyncio.create_task(
            event_service.wait_after(
                fix.human_player_1_actor,
                after_seq=0,
                limit=10,
                timeout=2.0,
            )
        )

        # Yield control so waiter registers and enters wait
        await asyncio.sleep(0.05)

        req = ResolveWorldActionRequest(
            change=CreateWorldEntryChange(
                payload=RuntimeWorldEntryCreate(
                    kind="fact",
                    body="The statue has emerald eyes.",
                    visibility="public",
                )
            ),
            narration="Two glowing emeralds shine in the statue's eye sockets.",
        )

        # Execute resolve_world_action in a worker thread (non-blocking)
        res = await asyncio.to_thread(
            world_service.resolve_world_action,
            fix.human_dm_actor,
            req,
            idempotency_key="waiter-test-key-1",
        )

        # Waiter should wake up well before timeout
        page = await asyncio.wait_for(wait_task, timeout=1.5)

        assert len(page.events) == 2
        ev_action = page.events[0]
        ev_narration = page.events[1]

        assert ev_action.kind == "world.action.resolved"
        assert ev_action.seq == res.action_event_seq
        assert ev_narration.kind == "exploration.narration"
        assert ev_narration.seq == res.narration_event_seq

        # Cursor ordering strictly preserved: world action before narration
        assert ev_action.seq < ev_narration.seq
        assert page.cursor == ev_narration.seq

    asyncio.run(_test())


# ---------------------------------------------------------------------------
# 8. Authority Rejections: Players, Inactive Session, Stale/Revoked Grants
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "actor_kind_or_failure",
    [
        "player_human",
        "player_ai",
        "inactive_session",
        "revoked_human",
        "controller_epoch",
        "revoked_ai",
    ],
)
def test_authority_rejections(
    actor_kind_or_failure: str,
) -> None:
    # Fresh fixture for each parametrization to avoid state contamination
    f = _build_active_fixture()
    ws = CampaignWorldService(f.service)

    if actor_kind_or_failure == "player_human":
        test_actor = f.human_player_1_actor
        expected_excs = (CampaignRuntimeAuthorityError,)
    elif actor_kind_or_failure == "player_ai":
        test_actor = f.ai_player_2_actor
        expected_excs = (CampaignRuntimeAuthorityError,)
    else:
        test_actor, expected_excs = setup_authority_failure_actor(f, actor_kind_or_failure)

    snap_before = _full_state_snapshot(f.engine, f.campaign_id, f.session_id)

    req = ResolveWorldActionRequest(
        change=CreateWorldEntryChange(
            payload=RuntimeWorldEntryCreate(
                kind="fact",
                body="Unauthorized fact attempt.",
                visibility="public",
            )
        ),
        narration="Unauthorized narration.",
    )

    with pytest.raises(expected_excs):
        ws.resolve_world_action(
            test_actor, req, idempotency_key=f"auth-fail-{actor_kind_or_failure}"
        )

    snap_after = _full_state_snapshot(f.engine, f.campaign_id, f.session_id)
    assert snap_before == snap_after
    assert len(f.notifier.notifications) == 0


# ---------------------------------------------------------------------------
# 9. Secret / Character-Only Secrecy Projection & Explicit Narration Only
# ---------------------------------------------------------------------------


def test_secret_and_character_knowledge_event_projection_and_secrecy(
    fix: ActiveFixture,
    world_service: CampaignWorldService,
) -> None:
    # 1. DM-only Secret Entry
    secret_req = ResolveWorldActionRequest(
        change=CreateWorldEntryChange(
            payload=RuntimeWorldEntryCreate(
                kind="secret",
                title="Hidden Assassin",
                body="An assassin hides in the rafters above.",
                dm_notes="Perception DC 18 to spot.",
                visibility="dm_only",
            )
        ),
        narration="A faint rustle of wind echoes from above.",
    )

    secret_res = world_service.resolve_world_action(
        fix.human_dm_actor, secret_req, idempotency_key="secret-secrecy-1"
    )

    with fix.engine.connect() as conn:
        ev_row = conn.execute(
            select(session_events).where(session_events.c.id == secret_res.action_event_id)
        ).mappings().one()

    # Event visibility must be dm_only, no recipients
    assert ev_row["visibility"] == "dm_only"
    assert ev_row["recipient_seat_ids"] == []
    # Event payload contains only safe refs
    assert ev_row["payload"]["action"] == "create_entry"
    assert ev_row["payload"]["entry_kind"] == "secret"
    assert "dm_notes" not in ev_row["payload"]
    assert "body" not in ev_row["payload"]

    # Player 1 cannot see the action event
    player_page = fix.service.event_service.list_after(
        fix.human_player_1_actor, after_seq=0, limit=10
    )
    action_event_ids = [ev.id for ev in player_page.events]
    assert secret_res.action_event_id not in action_event_ids
    # Player 1 CAN see the public narration
    assert secret_res.narration_event_id in action_event_ids

    # 2. Character-Only Knowledge Entry
    char_req = ResolveWorldActionRequest(
        change=CreateWorldEntryChange(
            payload=RuntimeWorldEntryCreate(
                kind="fact",
                title="Clue for Player 1",
                body="The riddle solution is 'shadow'.",
                dm_notes="Given because of background feature.",
                visibility="character",
                character_recipient_ids=(fix.char_1_id,),
            )
        ),
        narration="A forgotten memory surfaces in your mind.",
    )

    char_res = world_service.resolve_world_action(
        fix.human_dm_actor, char_req, idempotency_key="char-knowledge-secrecy-1"
    )

    with fix.engine.connect() as conn:
        char_ev_row = conn.execute(
            select(session_events).where(session_events.c.id == char_res.action_event_id)
        ).mappings().one()

    # Visibility is seat_private, recipient is player_1_seat_id
    assert char_ev_row["visibility"] == "seat_private"
    assert char_ev_row["recipient_seat_ids"] == [str(fix.player_1_seat_id)]
    # Safe payload only
    assert "body" not in char_ev_row["payload"]
    assert "dm_notes" not in char_ev_row["payload"]

    # Player 1 CAN see this event
    p1_page = fix.service.event_service.list_after(
        fix.human_player_1_actor, after_seq=0, limit=10
    )
    p1_event_ids = [ev.id for ev in p1_page.events]
    assert char_res.action_event_id in p1_event_ids

    # Player 2 (unrelated character) CANNOT see this event
    p2_page = fix.service.event_service.list_after(
        fix.ai_player_2_actor, after_seq=0, limit=10
    )
    p2_event_ids = [ev.id for ev in p2_page.events]
    assert char_res.action_event_id not in p2_event_ids


# ---------------------------------------------------------------------------
# 10. Extraction Regression: Legacy TableEventRepository & ExplorationMessageRepository
# ---------------------------------------------------------------------------


def test_extraction_regression_table_event_and_exploration_message_repos(
    fix: ActiveFixture,
) -> None:
    event_repo = TableEventRepository(fix.engine)
    msg_repo = ExplorationMessageRepository(fix.engine)

    binding = StoredTableActorBinding(
        actor_kind="human",
        room_id=fix.room_id,
        campaign_id=fix.campaign_id,
        session_id=fix.session_id,
        seat_id=fix.dm_seat_id,
        controlled_seat_ids=(fix.dm_seat_id,),
        role="dm",
        is_current_dm=True,
        access_session_id=fix.human_dm_access_id,
    )

    # 1. TableEventRepository.append legacy call
    ev1 = event_repo.append(
        room_id=fix.room_id,
        campaign_id=fix.campaign_id,
        session_id=fix.session_id,
        kind="test.legacy.append",
        acting_seat_id=fix.dm_seat_id,
        subject_seat_id=None,
        subject_character_id=None,
        execution_mode="self",
        visibility="public",
        recipient_seat_ids=(),
        payload_version=1,
        payload={"legacy": True},
        idempotency_key="legacy-append-1",
        expected_actor_binding=binding,
    )
    assert ev1.seq >= 1
    assert ev1.kind == "test.legacy.append"

    # Idempotency return on legacy append
    ev1_retry = event_repo.append(
        room_id=fix.room_id,
        campaign_id=fix.campaign_id,
        session_id=fix.session_id,
        kind="test.legacy.append",
        acting_seat_id=fix.dm_seat_id,
        subject_seat_id=None,
        subject_character_id=None,
        execution_mode="self",
        visibility="public",
        recipient_seat_ids=(),
        payload_version=1,
        payload={"legacy": True},
        idempotency_key="legacy-append-1",
        expected_actor_binding=binding,
    )
    assert ev1_retry.id == ev1.id
    assert ev1_retry.seq == ev1.seq

    # 2. TableEventRepository.append_in_transaction
    projection_ran = False

    def proj(conn: Connection, ev_id: UUID, seq: int) -> None:
        nonlocal projection_ran
        projection_ran = True

    with fix.engine.begin() as conn:
        ev2 = event_repo.append_in_transaction(
            conn,
            room_id=fix.room_id,
            campaign_id=fix.campaign_id,
            session_id=fix.session_id,
            kind="test.in_tx.append",
            acting_seat_id=fix.dm_seat_id,
            subject_seat_id=None,
            subject_character_id=None,
            execution_mode="self",
            visibility="public",
            recipient_seat_ids=(),
            payload_version=1,
            payload={"in_tx": True},
            idempotency_key="in-tx-append-1",
            expected_actor_binding=binding,
            transaction_projection=proj,
        )

    assert projection_ran is True
    assert ev2.seq == ev1.seq + 1
    assert ev2.kind == "test.in_tx.append"

    # 3. ExplorationMessageRepository.append_message legacy call
    msg_ev1 = msg_repo.append_message(
        binding=binding,
        message_kind="narration",
        text="A legacy narration message.",
        acting_seat_id=fix.dm_seat_id,
        subject_seat_id=None,
        subject_character_id=None,
        execution_mode="self",
        visibility="public",
        recipient_seat_ids=(),
        source_command=None,
        idempotency_key="legacy-msg-1",
    )
    assert msg_ev1.kind == "exploration.narration"

    with fix.engine.connect() as conn:
        msg_row = conn.execute(
            select(session_messages).where(session_messages.c.event_id == msg_ev1.id)
        ).mappings().one()
    assert msg_row["text"] == "A legacy narration message."
    assert msg_row["kind"] == "narration"

    # 4. ExplorationMessageRepository.append_message_in_transaction
    with fix.engine.begin() as conn:
        msg_ev2 = msg_repo.append_message_in_transaction(
            conn,
            binding=binding,
            message_kind="narration",
            text="An in-transaction narration message.",
            acting_seat_id=fix.dm_seat_id,
            subject_seat_id=None,
            subject_character_id=None,
            execution_mode="self",
            visibility="public",
            recipient_seat_ids=(),
            source_command=None,
            idempotency_key="in-tx-msg-1",
        )
    assert msg_ev2.kind == "exploration.narration"

    with fix.engine.connect() as conn:
        msg_row2 = conn.execute(
            select(session_messages).where(session_messages.c.event_id == msg_ev2.id)
        ).mappings().one()
    assert msg_row2["text"] == "An in-transaction narration message."


# ---------------------------------------------------------------------------
# 11. Distinct Tests for Update, Archive, and Clear Changes
# ---------------------------------------------------------------------------


def test_update_world_entry_change_successful_execution(
    fix: ActiveFixture,
    world_service: CampaignWorldService,
) -> None:
    created = world_service.resolve_world_action(
        fix.human_dm_actor,
        ResolveWorldActionRequest(
            change=CreateWorldEntryChange(
                payload=RuntimeWorldEntryCreate(
                    kind="fact",
                    title="Old Title",
                    body="Old Body",
                    dm_notes="Old Secret",
                    visibility="public",
                )
            )
        ),
        idempotency_key="standalone-update-create",
    )
    assert created.entry is not None

    update_change = UpdateWorldEntryChange(
        entry_id=created.entry.id,
        patch=RuntimeWorldEntryPatch(
            expected_revision=1,
            title="New Title",
            body="New Body",
            dm_notes="New Secret",
        ),
    )
    res = world_service.resolve_world_action(
        fix.human_dm_actor,
        ResolveWorldActionRequest(change=update_change),
        idempotency_key="standalone-update-exec",
    )

    assert res.action == "update_entry"
    assert res.entry is not None
    assert res.entry.revision == 2
    assert res.entry.title == "New Title"
    assert res.entry.body == "New Body"
    assert res.entry.dm_notes == "New Secret"
    assert res.action_event_id is not None

    with fix.engine.connect() as conn:
        ev = conn.execute(
            select(session_events).where(
                session_events.c.session_id == fix.session_id,
                session_events.c.seq == res.action_event_seq,
            )
        ).mappings().one()
        entry_row = conn.execute(
            select(campaign_world_entries).where(
                campaign_world_entries.c.id == created.entry.id
            )
        ).mappings().one()

    assert ev["payload"]["action"] == "update_entry"
    assert ev["payload"]["revision"] == 2
    assert ev["payload"]["entry_id"] == str(created.entry.id)
    assert "body" not in ev["payload"]
    assert "dm_notes" not in ev["payload"]
    assert entry_row["revision"] == 2
    assert entry_row["title"] == "New Title"
    assert entry_row["body"] == "New Body"


def test_archive_world_entry_change_successful_execution_without_room_id_error(
    fix: ActiveFixture,
    world_service: CampaignWorldService,
) -> None:
    created = world_service.resolve_world_action(
        fix.human_dm_actor,
        ResolveWorldActionRequest(
            change=CreateWorldEntryChange(
                payload=RuntimeWorldEntryCreate(
                    kind="fact",
                    body="To be archived entry.",
                    visibility="public",
                )
            )
        ),
        idempotency_key="standalone-archive-create",
    )
    assert created.entry is not None

    archive_change = ArchiveWorldEntryChange(
        entry_id=created.entry.id,
        expected_revision=1,
    )
    # This call passes without TypeError: execute_archive_entry_in_transaction() got unexpected keyword argument 'room_id'
    res = world_service.resolve_world_action(
        fix.human_dm_actor,
        ResolveWorldActionRequest(change=archive_change),
        idempotency_key="standalone-archive-exec",
    )

    assert res.action == "archive_entry"
    assert res.entry is not None
    assert res.entry.revision == 2
    assert res.entry.archived_at is not None

    with fix.engine.connect() as conn:
        ev = conn.execute(
            select(session_events).where(
                session_events.c.session_id == fix.session_id,
                session_events.c.seq == res.action_event_seq,
            )
        ).mappings().one()
        entry_row = conn.execute(
            select(campaign_world_entries).where(
                campaign_world_entries.c.id == created.entry.id
            )
        ).mappings().one()

    assert ev["payload"]["action"] == "archive_entry"
    assert ev["payload"]["revision"] == 2
    assert ev["payload"]["entry_id"] == str(created.entry.id)
    assert entry_row["revision"] == 2
    assert entry_row["archived_at"] is not None


def test_clear_adventure_override_change_successful_execution(
    fix: ActiveFixture,
    world_service: CampaignWorldService,
) -> None:
    created = world_service.resolve_world_action(
        fix.human_dm_actor,
        ResolveWorldActionRequest(
            change=SetAdventureOverrideChange(
                intent=SetAdventureOverrideIntent(
                    adventure_entry_id=fix.adv_entry_id,
                    state={"dm_summary": "Active override to clear."},
                )
            )
        ),
        idempotency_key="standalone-clear-create",
    )
    assert created.override is not None

    clear_change = ClearAdventureOverrideChange(
        intent=ClearAdventureOverrideIntent(
            adventure_entry_id=fix.adv_entry_id,
            expected_override_id=created.override.id,
            expected_revision=1,
        )
    )
    res = world_service.resolve_world_action(
        fix.human_dm_actor,
        ResolveWorldActionRequest(change=clear_change),
        idempotency_key="standalone-clear-exec",
    )

    assert res.action == "clear_override"
    assert res.override is not None
    assert res.override.revision == 1

    with fix.engine.connect() as conn:
        ev = conn.execute(
            select(session_events).where(
                session_events.c.session_id == fix.session_id,
                session_events.c.seq == res.action_event_seq,
            )
        ).mappings().one()
        ov_count = conn.scalar(
            select(func.count())
            .select_from(campaign_adventure_overrides)
            .where(
                campaign_adventure_overrides.c.campaign_id == fix.campaign_id,
                campaign_adventure_overrides.c.adventure_entry_id == fix.adv_entry_id,
            )
        )

    assert ev["payload"]["action"] == "clear_override"
    assert ev["payload"]["revision"] == 1
    assert ev["payload"]["adventure_entry_id"] == str(fix.adv_entry_id)
    assert ov_count == 0


# ---------------------------------------------------------------------------
# 12. Shared SetAdventureOverrideIntent Conversion and Validation Tests
# ---------------------------------------------------------------------------


def test_set_adventure_override_shared_intent_conversion_and_validation(
    fix: ActiveFixture,
    world_service: CampaignWorldService,
) -> None:
    # 1. Pydantic validation rejects expected_revision on create
    with pytest.raises(ValidationError, match="expected_revision must be absent"):
        SetAdventureOverrideIntent(
            adventure_entry_id=fix.adv_entry_id,
            state={"dm_summary": "Invalid create"},
            expected_revision=1,
        )

    # 2. _convert_override_intent rejects expected_revision on create (both D1 and D2)
    invalid_create_intent = SetAdventureOverrideIntent.model_construct(
        adventure_entry_id=fix.adv_entry_id,
        state={"dm_summary": "Invalid create"},
        expected_revision=1,
    )
    with pytest.raises(CampaignRuntimeValidationError, match="expected_revision must be absent"):
        world_service.set_adventure_override(
            fix.human_dm_actor,
            invalid_create_intent,
            idempotency_key="invalid-create-d1",
        )
    with pytest.raises(CampaignRuntimeValidationError, match="expected_revision must be absent"):
        world_service.resolve_world_action(
            fix.human_dm_actor,
            ResolveWorldActionRequest.model_construct(
                change=SetAdventureOverrideChange.model_construct(
                    action="set_override",
                    intent=invalid_create_intent,
                )
            ),
            idempotency_key="invalid-create-d2",
        )

    # 3. Reject missing expected_revision on update (both D1 and D2)
    fake_override_id = uuid4()
    invalid_update_intent = SetAdventureOverrideIntent.model_construct(
        adventure_entry_id=fix.adv_entry_id,
        expected_override_id=fake_override_id,
        expected_revision=None,
        state={"dm_summary": "Invalid update"},
    )
    with pytest.raises(CampaignRuntimeValidationError, match="expected_revision is required"):
        world_service.set_adventure_override(
            fix.human_dm_actor,
            invalid_update_intent,
            idempotency_key="invalid-update-d1",
        )
    with pytest.raises(CampaignRuntimeValidationError, match="expected_revision is required"):
        world_service.resolve_world_action(
            fix.human_dm_actor,
            ResolveWorldActionRequest.model_construct(
                change=SetAdventureOverrideChange.model_construct(
                    action="set_override",
                    intent=invalid_update_intent,
                )
            ),
            idempotency_key="invalid-update-d2",
        )

    # 4. Partial update semantics: only fields in model_fields_set are updated
    valid_create_intent = SetAdventureOverrideIntent(
        adventure_entry_id=fix.adv_entry_id,
        state={"dm_summary": "Initial state"},
        note="Initial note",
        needs_review=False,
    )
    ov = world_service.set_adventure_override(
        fix.human_dm_actor,
        valid_create_intent,
        idempotency_key="partial-update-create-d1",
    )
    # Update state only; note must be preserved
    partial_update_intent = SetAdventureOverrideIntent(
        adventure_entry_id=fix.adv_entry_id,
        expected_override_id=ov.id,
        expected_revision=1,
        state={"dm_summary": "Updated state"},
    )
    ov_updated = world_service.resolve_world_action(
        fix.human_dm_actor,
        ResolveWorldActionRequest(
            change=SetAdventureOverrideChange(intent=partial_update_intent)
        ),
        idempotency_key="partial-update-exec-d2",
    )
    assert ov_updated.override is not None
    assert ov_updated.override.state_json == {"dm_summary": "Updated state"}
    assert ov_updated.override.note == "Initial note"  # Note preserved!

    # Explicit note=None in model_fields_set clears the note
    clear_note_intent = SetAdventureOverrideIntent(
        adventure_entry_id=fix.adv_entry_id,
        expected_override_id=ov.id,
        expected_revision=2,
        note=None,
    )
    ov_cleared_note = world_service.resolve_world_action(
        fix.human_dm_actor,
        ResolveWorldActionRequest(
            change=SetAdventureOverrideChange(intent=clear_note_intent)
        ),
        idempotency_key="partial-update-clear-note-d2",
    )
    assert ov_cleared_note.override is not None
    assert ov_cleared_note.override.note is None


# ---------------------------------------------------------------------------
# 13. Concurrent Idempotency Window Lock Ordering
# ---------------------------------------------------------------------------


def test_concurrent_idempotency_window_lock_ordering(
    fix: ActiveFixture,
    world_service: CampaignWorldService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_order: list[str] = []

    orig_lock = world_service.runtime_service.campaign_repo.get_for_update_in_transaction
    orig_lookup = world_service.runtime_service.mutation_repo.get_in_transaction

    def tracked_lock(connection: Connection, campaign_id: UUID) -> object:
        call_order.append("lock")
        return orig_lock(connection, campaign_id)

    def tracked_lookup(connection: Connection, campaign_id: UUID, idempotency_key: str) -> object:
        call_order.append("lookup")
        return orig_lookup(connection, campaign_id, idempotency_key)

    monkeypatch.setattr(
        world_service.runtime_service.campaign_repo,
        "get_for_update_in_transaction",
        tracked_lock,
    )
    monkeypatch.setattr(
        world_service.runtime_service.mutation_repo,
        "get_in_transaction",
        tracked_lookup,
    )

    req = ResolveWorldActionRequest(
        change=CreateWorldEntryChange(
            payload=RuntimeWorldEntryCreate(
                kind="fact",
                body="Lock ordering fact.",
                visibility="public",
            )
        )
    )

    # First execution: lock occurs before lookup
    res = world_service.resolve_world_action(
        fix.human_dm_actor, req, idempotency_key="lock-ordering-1"
    )
    assert res.action == "create_entry"
    assert call_order == ["lock", "lookup"]

    # Retry execution: lock still occurs before lookup
    call_order.clear()
    retry_res = world_service.resolve_world_action(
        fix.human_dm_actor, req, idempotency_key="lock-ordering-1"
    )
    assert retry_res.action == "create_entry"
    assert call_order == ["lock", "lookup"]


# ---------------------------------------------------------------------------
# 14. Reserved Internal Idempotency Prefix Rejection
# ---------------------------------------------------------------------------


def test_reserved_internal_idempotency_prefix_rejected_with_zero_side_effects(
    fix: ActiveFixture,
    world_service: CampaignWorldService,
) -> None:
    snap_before = _full_state_snapshot(fix.engine, fix.campaign_id, fix.session_id)

    reserved_key = f"{RESERVED_INTERNAL_IDEMPOTENCY_PREFIX}caller-attempt"

    # 1. D1 call rejects reserved prefix
    with pytest.raises(CampaignRuntimeValidationError, match="reserved prefix"):
        world_service.create_world_entry(
            fix.human_dm_actor,
            RuntimeWorldEntryCreate(
                kind="fact",
                body="Should not be created",
                visibility="public",
            ),
            idempotency_key=reserved_key,
        )

    # 2. D2 call rejects reserved prefix
    req = ResolveWorldActionRequest(
        change=CreateWorldEntryChange(
            payload=RuntimeWorldEntryCreate(
                kind="fact",
                body="Should not be created",
                visibility="public",
            )
        )
    )
    with pytest.raises(CampaignRuntimeValidationError, match="reserved prefix"):
        world_service.resolve_world_action(
            fix.human_dm_actor, req, idempotency_key=reserved_key
        )

    snap_after = _full_state_snapshot(fix.engine, fix.campaign_id, fix.session_id)
    assert snap_before == snap_after
    assert len(fix.notifier.notifications) == 0


# ---------------------------------------------------------------------------
# 15. ResolveWorldActionRequest Narration Validation
# ---------------------------------------------------------------------------


def test_resolve_world_action_request_narration_validation() -> None:
    change = CreateWorldEntryChange(
        payload=RuntimeWorldEntryCreate(
            kind="fact",
            body="Narration validation body",
            visibility="public",
        )
    )

    # 1. Omitted narration -> None
    req1 = ResolveWorldActionRequest(change=change)
    assert req1.narration is None

    # 2. Explicit None -> None
    req2 = ResolveWorldActionRequest(change=change, narration=None)
    assert req2.narration is None

    # 3. Valid trimmed text
    req3 = ResolveWorldActionRequest(change=change, narration="  The cave echoes loudly.  ")
    assert req3.narration == "The cave echoes loudly."

    # 4. Blank string rejected
    with pytest.raises(ValidationError, match="narration cannot be blank"):
        ResolveWorldActionRequest(change=change, narration="   ")

    # 5. Empty string rejected
    with pytest.raises(ValidationError, match="narration cannot be blank"):
        ResolveWorldActionRequest(change=change, narration="")

    # 6. Max length exceeded (> 8,000 characters)
    with pytest.raises(ValidationError):
        ResolveWorldActionRequest(change=change, narration="A" * 8001)
