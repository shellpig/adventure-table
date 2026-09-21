import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { AdventureEntryKind, AttachedAdventure } from '../../api/adventures'
import {
  CampaignRuntimeApiError,
  type CampaignAdventureEntryOverlayView,
  type CampaignAdventureOverride,
  type CampaignRuntimeContext,
  type RuntimeWorldEntryDmView,
} from '../../api/campaignRuntime'
import {
  adventureEntryKindLabel,
  campaignRuntimeCopy,
  type CampaignRuntimeCopy,
} from './campaignRuntimeCopy'
import {
  CampaignChangesView,
  isCampaignChangesEmpty,
  type CampaignChangesManagement,
} from './CampaignChangesPage'
import {
  CampaignRuntimeContextView,
} from './CampaignRuntimeContext'
import {
  executeRuntimeMutation,
  loadCampaignChanges,
} from './campaignRuntimeForm'
import {
  buildClearContextRequest,
  buildClearOverrideRequest,
  buildCreateOverrideRequest,
  buildUpdateContextRequest,
  buildUpdateOverrideRequest,
  collectReviewQueueItems,
  computeDetachBlockers,
  contextToFormState,
  encodeSceneSelection,
  handleClearContext,
  handleClearOverride,
  overlayToOverrideFormState,
  parseSceneSelection,
  validateAndParseOverrideState,
  type ContextFormState,
  type CreateOverrideFormState,
  type EditOverrideFormState,
} from './campaignRuntimeOverrideForm'
import {
  CampaignAdventureEntryOverlayCard,
  CampaignAdventureOverrideFormView,
  CampaignAttachedAdventuresSection,
} from './CampaignRuntimeOverrides'
import {
  CampaignRuntimeReviewQueue,
} from './CampaignRuntimeReviewQueue'

const ROOM_ID = '10000000-0000-4000-8000-000000000001'
const CAMPAIGN_ID = '20000000-0000-4000-8000-000000000001'
const ADV_1_ID = '40000000-0000-4000-8000-000000000001'
const ADV_2_ID = '40000000-0000-4000-8000-000000000002'
const ENTRY_1_ID = '50000000-0000-4000-8000-000000000001'
const ENTRY_2_ID = '50000000-0000-4000-8000-000000000002'

describe('B5c SCOPE A — loadCampaignChanges snapshot and attached adventures', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('loads zero attached adventures without making any overlay requests', async () => {
    const fetchMock = vi.fn().mockImplementation(async (url: string) => {
      if (url.includes('/runtime/entries')) {
        return { ok: true, status: 200, json: async () => [] }
      }
      if (url.includes('/runtime/overrides')) {
        return { ok: true, status: 200, json: async () => [] }
      }
      if (url.includes('/runtime/context')) {
        return { ok: true, status: 200, json: async () => ({ campaign_id: CAMPAIGN_ID, revision: 0 }) }
      }
      if (url.includes('/characters')) {
        return { ok: true, status: 200, json: async () => [] }
      }
      if (url.includes('/adventures')) {
        return { ok: true, status: 200, json: async () => [] }
      }
      return { ok: false, status: 404, json: async () => ({}) }
    })
    vi.stubGlobal('fetch', fetchMock)

    const snapshot = await loadCampaignChanges(ROOM_ID, CAMPAIGN_ID, 'token-123')

    expect(snapshot.attachedAdventures).toEqual([])
    expect(snapshot.overlays).toEqual([])
    // 5 base queries: entries, overrides, context, characters, adventures. 0 overlay queries!
    expect(fetchMock).toHaveBeenCalledTimes(5)
    const calledUrls = fetchMock.mock.calls.map((c: unknown[]) => String(c[0]))
    expect(calledUrls.some((u: string) => u.includes('/overlays'))).toBe(false)
  })

  it('loads multiple attached adventures and flattens overlays deterministically in response order', async () => {
    const fakeAdventures: AttachedAdventure[] = [
      {
        campaign_id: CAMPAIGN_ID,
        adventure_id: ADV_1_ID,
        sort_order: 1,
        attached_at: '2026-09-21T00:00:00Z',
        name: 'Lost Mine',
        summary: 'A goblin cave',
        status: 'finalized',
      },
      {
        campaign_id: CAMPAIGN_ID,
        adventure_id: ADV_2_ID,
        sort_order: 2,
        attached_at: '2026-09-21T01:00:00Z',
        name: 'Sunless Citadel',
        summary: 'A deep ravine',
        status: 'finalized',
      },
    ]

    const overlaysAdv1: CampaignAdventureEntryOverlayView[] = [
      {
        id: ENTRY_1_ID,
        adventure_id: ADV_1_ID,
        parent_entry_id: null,
        kind: 'scene',
        title: 'Cragmaw Hideout',
        body: 'A dark cave mouth',
        data: { kind: 'scene', dm_summary: 'Watch out for traps' },
        visibility: 'dm_only',
        sort_order: 1,
        override: null,
      },
    ]

    const overlaysAdv2: CampaignAdventureEntryOverlayView[] = [
      {
        id: ENTRY_2_ID,
        adventure_id: ADV_2_ID,
        parent_entry_id: null,
        kind: 'npc',
        title: 'Meepo',
        body: 'Kobold keeper',
        data: { kind: 'npc', role: 'Keeper', disposition: 'neutral' },
        visibility: 'public',
        sort_order: 1,
        override: {
          id: 'ovr-meepo',
          campaign_id: CAMPAIGN_ID,
          adventure_entry_id: ENTRY_2_ID,
          state_json: { disposition: 'friendly' },
          note: 'Befriended party',
          needs_review: false,
          revision: 1,
          created_at: '2026-09-21T02:00:00Z',
          updated_at: '2026-09-21T02:00:00Z',
        },
      },
    ]

    const fetchMock = vi.fn().mockImplementation(async (url: string) => {
      if (url.includes('/runtime/entries')) {
        return { ok: true, status: 200, json: async () => [] }
      }
      if (url.includes('/runtime/overrides')) {
        return { ok: true, status: 200, json: async () => [] }
      }
      if (url.includes('/runtime/context')) {
        return { ok: true, status: 200, json: async () => ({ campaign_id: CAMPAIGN_ID, revision: 0 }) }
      }
      if (url.includes('/characters')) {
        return { ok: true, status: 200, json: async () => [] }
      }
      if (url.includes(`/adventures/${ADV_1_ID}/overlays`)) {
        return { ok: true, status: 200, json: async () => overlaysAdv1 }
      }
      if (url.includes(`/adventures/${ADV_2_ID}/overlays`)) {
        return { ok: true, status: 200, json: async () => overlaysAdv2 }
      }
      if (url.includes('/adventures')) {
        return { ok: true, status: 200, json: async () => fakeAdventures }
      }
      return { ok: false, status: 404, json: async () => ({}) }
    })
    vi.stubGlobal('fetch', fetchMock)

    const snapshot = await loadCampaignChanges(ROOM_ID, CAMPAIGN_ID, 'token-123')

    expect(snapshot.attachedAdventures).toEqual(fakeAdventures)
    expect(snapshot.overlays).toEqual([...overlaysAdv1, ...overlaysAdv2])
    expect(fetchMock).toHaveBeenCalledTimes(7) // 5 base + 2 overlays
  })
})

describe('B5c SCOPE B — Override builders, validation, and JSON handling', () => {
  it('validates and parses override state JSON: blank means {}, objects accepted, rejects non-objects', () => {
    expect(validateAndParseOverrideState('')).toEqual({ ok: true, value: {} })
    expect(validateAndParseOverrideState('   ')).toEqual({ ok: true, value: {} })
    expect(validateAndParseOverrideState('{}')).toEqual({ ok: true, value: {} })
    expect(validateAndParseOverrideState('{"disposition": "hostile"}')).toEqual({
      ok: true,
      value: { disposition: 'hostile' },
    })

    expect(validateAndParseOverrideState('not a json')).toEqual({
      ok: false,
      errorKey: 'errOverrideStateInvalidJson',
    })
    expect(validateAndParseOverrideState('[1, 2, 3]')).toEqual({
      ok: false,
      errorKey: 'errOverrideStateInvalidJson',
    })
    expect(validateAndParseOverrideState('"just a string"')).toEqual({
      ok: false,
      errorKey: 'errOverrideStateInvalidJson',
    })
    expect(validateAndParseOverrideState('123')).toEqual({
      ok: false,
      errorKey: 'errOverrideStateInvalidJson',
    })
    expect(validateAndParseOverrideState('null')).toEqual({
      ok: false,
      errorKey: 'errOverrideStateInvalidJson',
    })
  })

  it('builds create override request and trims blank note to null', () => {
    const form: CreateOverrideFormState = {
      mode: 'create',
      adventureId: ADV_1_ID,
      adventureEntryId: ENTRY_1_ID,
      entryTitle: 'Gundren Rockseeker',
      entryKind: 'npc',
      stateJson: '{"disposition": "hostile"}',
      note: '  Turned hostile after interrogation  ',
      needsReview: true,
    }
    const result = buildCreateOverrideRequest(form, 'idemp-ovr-create-1')
    expect(result).toEqual({
      ok: true,
      value: {
        idempotency_key: 'idemp-ovr-create-1',
        adventure_entry_id: ENTRY_1_ID,
        state: { disposition: 'hostile' },
        note: 'Turned hostile after interrogation',
        needs_review: true,
      },
    })
    if (result.ok) {
      expect(result.value).not.toHaveProperty('title')
      expect(result.value).not.toHaveProperty('body')
      expect(result.value).not.toHaveProperty('data')
    }

    const blankNoteForm: CreateOverrideFormState = {
      ...form,
      note: '   ',
      stateJson: '',
    }
    const blankResult = buildCreateOverrideRequest(blankNoteForm, 'idemp-ovr-create-2')
    expect(blankResult).toEqual({
      ok: true,
      value: {
        idempotency_key: 'idemp-ovr-create-2',
        adventure_entry_id: ENTRY_1_ID,
        state: {},
        note: null,
        needs_review: true,
      },
    })
  })

  it('builds update override request with exact override id and revision', () => {
    const form: EditOverrideFormState = {
      mode: 'edit',
      adventureId: ADV_1_ID,
      adventureEntryId: ENTRY_1_ID,
      entryTitle: 'Gundren Rockseeker',
      entryKind: 'npc',
      expectedOverrideId: 'ovr-999',
      expectedRevision: 3,
      stateJson: '{"status": "escaped"}',
      note: '',
      needsReview: false,
    }
    const result = buildUpdateOverrideRequest(form, 'idemp-ovr-update-1')
    expect(result).toEqual({
      ok: true,
      value: {
        idempotency_key: 'idemp-ovr-update-1',
        expected_override_id: 'ovr-999',
        expected_revision: 3,
        state: { status: 'escaped' },
        note: null,
        needs_review: false,
      },
    })
    if (result.ok) {
      expect(result.value).not.toHaveProperty('title')
      expect(result.value).not.toHaveProperty('body')
      expect(result.value).not.toHaveProperty('data')
      expect(result.value).not.toHaveProperty('adventure_entry_id')
    }
  })

  it('builds clear override request with exact override identity and revision', () => {
    const req = buildClearOverrideRequest('ovr-123', 4, 'idemp-ovr-clear-1')
    expect(req).toEqual({
      idempotency_key: 'idemp-ovr-clear-1',
      expected_override_id: 'ovr-123',
      expected_revision: 4,
    })
  })

  it('starts override edit from override.state_json, NEVER from merged overlay.data', () => {
    const overlayWithOverride: CampaignAdventureEntryOverlayView = {
      id: ENTRY_1_ID,
      adventure_id: ADV_1_ID,
      parent_entry_id: null,
      kind: 'npc',
      title: 'Klarg',
      body: 'Bugbear leader',
      data: { kind: 'npc', role: 'Leader', disposition: 'hostile' },
      visibility: 'public',
      sort_order: 1,
      override: {
        id: 'ovr-klarg',
        campaign_id: CAMPAIGN_ID,
        adventure_entry_id: ENTRY_1_ID,
        state_json: { role: 'Unconscious Prisoner' },
        note: 'Captured by party',
        needs_review: true,
        revision: 2,
        created_at: '2026-09-21T00:00:00Z',
        updated_at: '2026-09-21T00:00:00Z',
      },
    }

    const formState = overlayToOverrideFormState(overlayWithOverride)
    expect(formState.mode).toBe('edit')
    if (formState.mode === 'edit') {
      expect(formState.expectedOverrideId).toBe('ovr-klarg')
      expect(formState.expectedRevision).toBe(2)
      // Must contain override state_json, NOT overlay.data
      expect(formState.stateJson).toContain('Unconscious Prisoner')
      expect(formState.stateJson).not.toContain('Bugbear leader')
      expect(formState.stateJson).not.toContain('Leader')
      expect(formState.note).toBe('Captured by party')
      expect(formState.needsReview).toBe(true)
    }
  })

})

describe('B5c SCOPE B & E — Clear cancel lifecycle', () => {
  const copy = campaignRuntimeCopy('en')

  it('canceling clear override confirmation performs no API call, no pending, and no reload', async () => {
    const clearFn = vi.fn()
    const onReload = vi.fn()
    const onStart = vi.fn()
    const onCancel = vi.fn()
    const onError = vi.fn()
    const onCommittedReloadError = vi.fn()

    const success = await handleClearOverride({
      roomId: ROOM_ID,
      campaignId: CAMPAIGN_ID,
      adventureEntryId: ENTRY_1_ID,
      expectedOverrideId: 'ovr-1',
      expectedRevision: 1,
      token: 'tok',
      idempotencyKey: 'k-1',
      confirmFn: () => false, // user cancels
      onStart,
      onCancel,
      clearFn,
      onReload,
      onError,
      onCommittedReloadError,
      copy,
    })

    expect(success).toBe(false)
    expect(onCancel).toHaveBeenCalledTimes(1)
    expect(onStart).not.toHaveBeenCalled()
    expect(clearFn).not.toHaveBeenCalled()
    expect(onReload).not.toHaveBeenCalled()
  })

  it('canceling clear context confirmation performs no API call, no pending, and no reload', async () => {
    const clearFn = vi.fn()
    const onReload = vi.fn()
    const onStart = vi.fn()
    const onCancel = vi.fn()
    const onError = vi.fn()
    const onCommittedReloadError = vi.fn()

    const success = await handleClearContext({
      roomId: ROOM_ID,
      campaignId: CAMPAIGN_ID,
      expectedRevision: 0,
      token: 'tok',
      idempotencyKey: 'k-ctx-clr',
      confirmFn: () => false, // user cancels
      onStart,
      onCancel,
      clearFn,
      onReload,
      onError,
      onCommittedReloadError,
      copy,
    })

    expect(success).toBe(false)
    expect(onCancel).toHaveBeenCalledTimes(1)
    expect(onStart).not.toHaveBeenCalled()
    expect(clearFn).not.toHaveBeenCalled()
    expect(onReload).not.toHaveBeenCalled()
  })
})

describe('B5c SCOPE C — Detach blocker guidance', () => {
  const copy = campaignRuntimeCopy('en')

  const overlay1: CampaignAdventureEntryOverlayView = {
    id: ENTRY_1_ID,
    adventure_id: ADV_1_ID,
    parent_entry_id: null,
    kind: 'scene',
    title: 'Goblin Hideout',
    body: null,
    data: { kind: 'scene' },
    visibility: 'public',
    sort_order: 1,
    override: null,
  }

  it('identifies active override blocker alone', () => {
    const overlayWithOvr: CampaignAdventureEntryOverlayView = {
      ...overlay1,
      override: {
        id: 'ovr-1',
        campaign_id: CAMPAIGN_ID,
        adventure_entry_id: ENTRY_1_ID,
        state_json: {},
        note: null,
        needs_review: false,
        revision: 1,
        created_at: '',
        updated_at: '',
      },
    }

    const status = computeDetachBlockers(ADV_1_ID, [overlayWithOvr], null)
    expect(status.hasActiveOverrides).toBe(true)
    expect(status.hasActiveContextScene).toBe(false)
    expect(status.isBlocked).toBe(true)

    const html = renderToStaticMarkup(
      <CampaignAttachedAdventuresSection
        actions={{
          activeOverrideForm: null,
          overrideFormError: null,
          pending: false,
          onCancelOverrideForm: () => {},
          onChangeOverrideForm: () => {},
          onClearOverride: () => {},
          onOpenCreateOverride: () => {},
          onOpenEditOverride: () => {},
          onSubmitOverrideForm: () => {},
        }}
        attachedAdventures={[
          {
            campaign_id: CAMPAIGN_ID,
            adventure_id: ADV_1_ID,
            sort_order: 1,
            attached_at: '',
            name: 'Lost Mine',
            summary: null,
            status: 'finalized',
          },
        ]}
        context={null}
        copy={copy}
        overrideCount={1}
        overlays={[overlayWithOvr]}
      />,
    )
    expect(html).toContain(copy.detachBlockerOverrides)
    expect(html).not.toContain(copy.detachBlockerContextScene)
  })

  it('identifies current context adventure scene blocker alone', () => {
    const context: CampaignRuntimeContext = {
      campaign_id: CAMPAIGN_ID,
      current_adventure_scene_entry_id: ENTRY_1_ID,
      current_runtime_scene_entry_id: null,
      current_situation: null,
      revision: 1,
      created_at: null,
      updated_at: null,
    }

    const status = computeDetachBlockers(ADV_1_ID, [overlay1], context)
    expect(status.hasActiveOverrides).toBe(false)
    expect(status.hasActiveContextScene).toBe(true)
    expect(status.isBlocked).toBe(true)

    const html = renderToStaticMarkup(
      <CampaignAttachedAdventuresSection
        actions={{
          activeOverrideForm: null,
          overrideFormError: null,
          pending: false,
          onCancelOverrideForm: () => {},
          onChangeOverrideForm: () => {},
          onClearOverride: () => {},
          onOpenCreateOverride: () => {},
          onOpenEditOverride: () => {},
          onSubmitOverrideForm: () => {},
        }}
        attachedAdventures={[
          {
            campaign_id: CAMPAIGN_ID,
            adventure_id: ADV_1_ID,
            sort_order: 1,
            attached_at: '',
            name: 'Lost Mine',
            summary: null,
            status: 'finalized',
          },
        ]}
        context={context}
        copy={copy}
        overrideCount={0}
        overlays={[overlay1]}
      />,
    )
    expect(html).not.toContain(copy.detachBlockerOverrides)
    expect(html).toContain(copy.detachBlockerContextScene)
  })

  it('shows both blockers when active overrides and context scene are both present', () => {
    const overlayWithOvr: CampaignAdventureEntryOverlayView = {
      ...overlay1,
      override: {
        id: 'ovr-1',
        campaign_id: CAMPAIGN_ID,
        adventure_entry_id: ENTRY_1_ID,
        state_json: {},
        note: null,
        needs_review: false,
        revision: 1,
        created_at: '',
        updated_at: '',
      },
    }

    const context: CampaignRuntimeContext = {
      campaign_id: CAMPAIGN_ID,
      current_adventure_scene_entry_id: ENTRY_1_ID,
      current_runtime_scene_entry_id: null,
      current_situation: null,
      revision: 1,
      created_at: null,
      updated_at: null,
    }

    const status = computeDetachBlockers(ADV_1_ID, [overlayWithOvr], context)
    expect(status.hasActiveOverrides).toBe(true)
    expect(status.hasActiveContextScene).toBe(true)
    expect(status.isBlocked).toBe(true)

    const html = renderToStaticMarkup(
      <CampaignAttachedAdventuresSection
        actions={{
          activeOverrideForm: null,
          overrideFormError: null,
          pending: false,
          onCancelOverrideForm: () => {},
          onChangeOverrideForm: () => {},
          onClearOverride: () => {},
          onOpenCreateOverride: () => {},
          onOpenEditOverride: () => {},
          onSubmitOverrideForm: () => {},
        }}
        attachedAdventures={[
          {
            campaign_id: CAMPAIGN_ID,
            adventure_id: ADV_1_ID,
            sort_order: 1,
            attached_at: '',
            name: 'Lost Mine',
            summary: null,
            status: 'finalized',
          },
        ]}
        context={context}
        copy={copy}
        overrideCount={1}
        overlays={[overlayWithOvr]}
      />,
    )
    expect(html).toContain(copy.detachBlockerOverrides)
    expect(html).toContain(copy.detachBlockerContextScene)
  })

  it('explicitly does NOT treat Runtime entry provenance as a detach blocker', () => {
    // Provenance ref in runtime entry, but 0 overrides and context does not point to this adventure
    const status = computeDetachBlockers(ADV_1_ID, [overlay1], null)
    expect(status.hasActiveOverrides).toBe(false)
    expect(status.hasActiveContextScene).toBe(false)
    expect(status.isBlocked).toBe(false)
  })
})

describe('B5c SCOPE D — Centralized needs_review queue', () => {
  const copy = campaignRuntimeCopy('en')

  const runtimeEntryFlagged: RuntimeWorldEntryDmView = {
    id: 'rt-flagged-1',
    campaign_id: CAMPAIGN_ID,
    kind: 'fact',
    title: 'Dragon sighted',
    body: 'Seen over the mountains',
    state: { kind: 'fact' },
    visibility: 'public',
    dm_notes: null,
    needs_review: true, // FLAGGED
    source_adventure_entry_id: null,
    provenance_json: null,
    character_recipient_ids: [],
    revision: 1,
    created_by_actor_kind: 'human',
    created_by_actor_id: null,
    created_at: '',
    updated_at: '',
    archived_at: null,
  }

  const runtimeEntryClean: RuntimeWorldEntryDmView = {
    ...runtimeEntryFlagged,
    id: 'rt-clean-1',
    needs_review: false,
  }

  const overlayFlagged: CampaignAdventureEntryOverlayView = {
    id: ENTRY_1_ID,
    adventure_id: ADV_1_ID,
    parent_entry_id: null,
    kind: 'npc',
    title: 'Sildar Hallwinter',
    body: null,
    data: { kind: 'npc' },
    visibility: 'public',
    sort_order: 1,
    override: {
      id: 'ovr-sildar',
      campaign_id: CAMPAIGN_ID,
      adventure_entry_id: ENTRY_1_ID,
      state_json: { disposition: 'hostile' },
      note: 'Mind controlled',
      needs_review: true, // FLAGGED
      revision: 1,
      created_at: '',
      updated_at: '',
    },
  }

  const overlayClean: CampaignAdventureEntryOverlayView = {
    ...overlayFlagged,
    id: ENTRY_2_ID,
    override: {
      ...overlayFlagged.override!,
      id: 'ovr-clean',
      needs_review: false,
    },
  }

  const attachedAdventures: AttachedAdventure[] = [
    {
      campaign_id: CAMPAIGN_ID,
      adventure_id: ADV_1_ID,
      sort_order: 1,
      attached_at: '',
      name: 'Lost Mine',
      summary: null,
      status: 'finalized',
    },
  ]

  it('collects only items with needs_review=true across runtime and overrides', () => {
    const items = collectReviewQueueItems(
      [runtimeEntryFlagged, runtimeEntryClean],
      [overlayFlagged, overlayClean],
      attachedAdventures,
    )
    expect(items).toHaveLength(2)
    expect(items[0]).toEqual({ type: 'runtime', entry: runtimeEntryFlagged })
    expect(items[1]).toEqual({
      type: 'override',
      overlay: overlayFlagged,
      adventureName: 'Lost Mine',
    })
  })

  it('renders queue non-blockingly and shows review actions', () => {
    const onOpenEditRuntime = vi.fn()
    const onOpenEditOverride = vi.fn()

    const items = collectReviewQueueItems(
      [runtimeEntryFlagged],
      [overlayFlagged],
      attachedAdventures,
    )

    const html = renderToStaticMarkup(
      <CampaignRuntimeReviewQueue
        actions={{
          disabled: false,
          onOpenEditOverride,
          onOpenEditRuntime,
        }}
        copy={copy}
        items={items}
      />,
    )

    expect(html).toContain(copy.reviewQueueHeading)
    expect(html).toContain(`${copy.reviewQueueCountLabel}: 2`)
    expect(html).toContain('Dragon sighted')
    expect(html).toContain('Sildar Hallwinter')
    expect(html).toContain(copy.reviewSourceTypeRuntime)
    expect(html).toContain(copy.reviewSourceTypeOverride)
    expect(html).toContain(copy.reviewButton)
  })
})

describe('B5c SCOPE E — Current Context builders, switching, and revision 0', () => {
  it('covers no scene and no situation', () => {
    const form: ContextFormState = {
      sceneSelection: { type: 'none' },
      situation: '',
      expectedRevision: 0,
    }
    const req = buildUpdateContextRequest(form, 'k-ctx-1')
    expect(req).toEqual({
      idempotency_key: 'k-ctx-1',
      expected_revision: 0,
      current_adventure_scene_entry_id: null,
      current_runtime_scene_entry_id: null,
      current_situation: null,
    })
  })

  it('covers situation-only with no scene', () => {
    const form: ContextFormState = {
      sceneSelection: { type: 'none' },
      situation: '  Party camped near the river  ',
      expectedRevision: 1,
    }
    const req = buildUpdateContextRequest(form, 'k-ctx-2')
    expect(req).toEqual({
      idempotency_key: 'k-ctx-2',
      expected_revision: 1,
      current_adventure_scene_entry_id: null,
      current_runtime_scene_entry_id: null,
      current_situation: 'Party camped near the river',
    })
  })

  it('covers Adventure Scene selection and explicitly sets runtime scene ref to null', () => {
    const form: ContextFormState = {
      sceneSelection: { type: 'adventure', sceneEntryId: 'adv-scene-42' },
      situation: 'Ambushed',
      expectedRevision: 2,
    }
    const req = buildUpdateContextRequest(form, 'k-ctx-3')
    expect(req).toEqual({
      idempotency_key: 'k-ctx-3',
      expected_revision: 2,
      current_adventure_scene_entry_id: 'adv-scene-42',
      current_runtime_scene_entry_id: null,
      current_situation: 'Ambushed',
    })
  })

  it('covers Runtime Scene selection and explicitly sets adventure scene ref to null', () => {
    const form: ContextFormState = {
      sceneSelection: { type: 'runtime', sceneEntryId: 'rt-scene-99' },
      situation: 'Searching for clues',
      expectedRevision: 3,
    }
    const req = buildUpdateContextRequest(form, 'k-ctx-4')
    expect(req).toEqual({
      idempotency_key: 'k-ctx-4',
      expected_revision: 3,
      current_adventure_scene_entry_id: null,
      current_runtime_scene_entry_id: 'rt-scene-99',
      current_situation: 'Searching for clues',
    })
  })

  it('preserves revision 0 accurately in update and clear request bodies', () => {
    const updateReq = buildUpdateContextRequest(
      { sceneSelection: { type: 'none' }, situation: '', expectedRevision: 0 },
      'k-rev-0',
    )
    expect(updateReq.expected_revision).toBe(0)

    const clearReq = buildClearContextRequest(0, 'k-clear-0')
    expect(clearReq.expected_revision).toBe(0)
    expect(clearReq.idempotency_key).toBe('k-clear-0')
  })

  it('encodes and parses scene selection strings deterministically', () => {
    expect(encodeSceneSelection({ type: 'none' })).toBe('')
    expect(encodeSceneSelection({ type: 'adventure', sceneEntryId: 'adv-1' })).toBe('adventure:adv-1')
    expect(encodeSceneSelection({ type: 'runtime', sceneEntryId: 'rt-1' })).toBe('runtime:rt-1')

    expect(parseSceneSelection('')).toEqual({ type: 'none' })
    expect(parseSceneSelection('adventure:adv-1')).toEqual({ type: 'adventure', sceneEntryId: 'adv-1' })
    expect(parseSceneSelection('runtime:rt-1')).toEqual({ type: 'runtime', sceneEntryId: 'rt-1' })
    expect(parseSceneSelection('invalid-format')).toEqual({ type: 'none' })
  })
})

describe('B5c SCOPE E — Selectors filter non-scene and archived entries', () => {
  const copy = campaignRuntimeCopy('en')

  it('excludes non-scene adventure entries and non-scene/archived runtime entries from scene dropdown', () => {
    const overlays: CampaignAdventureEntryOverlayView[] = [
      {
        id: 'adv-scene-entry',
        adventure_id: ADV_1_ID,
        parent_entry_id: null,
        kind: 'scene', // SCENE
        title: 'Wave Echo Cave',
        body: null,
        data: { kind: 'scene' },
        visibility: 'public',
        sort_order: 1,
        override: null,
      },
      {
        id: 'adv-npc-entry',
        adventure_id: ADV_1_ID,
        parent_entry_id: null,
        kind: 'npc', // NOT SCENE
        title: 'Nezznar',
        body: null,
        data: { kind: 'npc' },
        visibility: 'public',
        sort_order: 2,
        override: null,
      },
      {
        id: 'adv-unnamed-scene',
        adventure_id: ADV_1_ID,
        parent_entry_id: null,
        kind: 'scene', // UNNAMED SCENE -> safe fallback
        title: null,
        body: null,
        data: { kind: 'scene' },
        visibility: 'public',
        sort_order: 3,
        override: null,
      },
    ]

    const entries: RuntimeWorldEntryDmView[] = [
      {
        id: 'rt-scene-active',
        campaign_id: CAMPAIGN_ID,
        kind: 'scene', // ACTIVE SCENE
        title: 'Stonehill Inn',
        body: null,
        state: { kind: 'scene' },
        visibility: 'public',
        dm_notes: null,
        needs_review: false,
        source_adventure_entry_id: null,
        provenance_json: null,
        character_recipient_ids: [],
        revision: 1,
        created_by_actor_kind: 'human',
        created_by_actor_id: null,
        created_at: '',
        updated_at: '',
        archived_at: null,
      },
      {
        id: 'rt-scene-archived',
        campaign_id: CAMPAIGN_ID,
        kind: 'scene', // ARCHIVED SCENE -> must exclude
        title: 'Old Ruins',
        body: null,
        state: { kind: 'scene' },
        visibility: 'public',
        dm_notes: null,
        needs_review: false,
        source_adventure_entry_id: null,
        provenance_json: null,
        character_recipient_ids: [],
        revision: 1,
        created_by_actor_kind: 'human',
        created_by_actor_id: null,
        created_at: '',
        updated_at: '',
        archived_at: '2026-09-21T00:00:00Z',
      },
      {
        id: 'rt-npc-entry',
        campaign_id: CAMPAIGN_ID,
        kind: 'npc', // NOT SCENE -> must exclude
        title: 'Innkeeper Toblen',
        body: null,
        state: { kind: 'npc', monster_instance_id: null, monster_template_ref: null },
        visibility: 'public',
        dm_notes: null,
        needs_review: false,
        source_adventure_entry_id: null,
        provenance_json: null,
        character_recipient_ids: [],
        revision: 1,
        created_by_actor_kind: 'human',
        created_by_actor_id: null,
        created_at: '',
        updated_at: '',
        archived_at: null,
      },
    ]

    const attachedAdventures: AttachedAdventure[] = [
      {
        campaign_id: CAMPAIGN_ID,
        adventure_id: ADV_1_ID,
        sort_order: 1,
        attached_at: '',
        name: 'Lost Mine',
        summary: null,
        status: 'finalized',
      },
    ]

    const html = renderToStaticMarkup(
      <CampaignRuntimeContextView
        actions={{
          pending: false,
          formState: { sceneSelection: { type: 'none' }, situation: '', expectedRevision: 0 },
          formError: null,
          onOpenEdit: () => {},
          onCancelEdit: () => {},
          onChangeForm: () => {},
          onSubmitForm: () => {},
          onClearContext: () => {},
        }}
        attachedAdventures={attachedAdventures}
        context={null}
        copy={copy}
        entries={entries}
        overlays={overlays}
      />,
    )

    // Included:
    expect(html).toContain('Wave Echo Cave')
    expect(html).toContain('Stonehill Inn')
    expect(html).toContain('adv-unnamed-scene') // safe fallback for unnamed

    // Excluded:
    expect(html).not.toContain('Nezznar')
    expect(html).not.toContain('Old Ruins')
    expect(html).not.toContain('Innkeeper Toblen')
    expect(html).not.toContain('?')
  })
})

describe('B5c Concurrency & Mutation Lifecycle', () => {
  const copy = campaignRuntimeCopy('en')

  it('revision conflict performs ordered reload before localized conflict reporting', async () => {
    const callOrder: string[] = []
    const onReload = vi.fn().mockImplementation(async () => {
      callOrder.push('reload')
    })
    const onError = vi.fn().mockImplementation(() => {
      callOrder.push('error')
    })

    const action = vi.fn().mockRejectedValue(
      new CampaignRuntimeApiError(409, 'campaign_runtime_revision_conflict', 'conflict'),
    )

    const success = await executeRuntimeMutation({
      action,
      onReload,
      onError,
      onCommittedReloadError: vi.fn(),
      copy,
    })

    expect(success).toBe(false)
    expect(callOrder).toEqual(['reload', 'error'])
    expect(onError).toHaveBeenCalledWith(copy.errCampaignRuntimeRevisionConflict)
  })

  it('committed mutation + reload failed triggers distinct committed reload error', async () => {
    const onReload = vi.fn().mockRejectedValue(new Error('Network down'))
    const onCommittedReloadError = vi.fn()
    const onError = vi.fn()

    const action = vi.fn().mockResolvedValue({ id: 'done' })

    const success = await executeRuntimeMutation({
      action,
      onReload,
      onError,
      onCommittedReloadError,
      copy,
    })

    expect(success).toBe(false)
    expect(onError).not.toHaveBeenCalled()
    expect(onCommittedReloadError).toHaveBeenCalledWith(copy.requestFailed)
  })
})

describe('B5c Bilingual parity and copy coverage', () => {
  it('renders all B5c components cleanly in en and zh-TW without missing keys or phase jargon', () => {
    for (const locale of ['en', 'zh-TW'] as const) {
      const copy = campaignRuntimeCopy(locale)

      const html = renderToStaticMarkup(
        <CampaignChangesView
          attachedAdventures={[
            {
              campaign_id: CAMPAIGN_ID,
              adventure_id: ADV_1_ID,
              sort_order: 1,
              attached_at: '',
              name: 'Adventure Name',
              summary: 'Adventure Summary',
              status: 'finalized',
            },
          ]}
          campaignId={CAMPAIGN_ID}
          context={{
            campaign_id: CAMPAIGN_ID,
            current_adventure_scene_entry_id: null,
            current_runtime_scene_entry_id: null,
            current_situation: 'Testing situation',
            revision: 1,
            created_at: null,
            updated_at: null,
          }}
          copy={copy}
          entries={[]}
          error={null}
          loading={false}
          management={null}
          overrides={[]}
          overlays={[
            {
              id: ENTRY_1_ID,
              adventure_id: ADV_1_ID,
              parent_entry_id: null,
              kind: 'scene',
              title: 'Cave',
              body: 'A dark entrance',
              data: { kind: 'scene' },
              visibility: 'public',
              sort_order: 1,
              override: null,
            },
          ]}
          roomId={ROOM_ID}
        />,
      )

      expect(html).toContain(copy.changesTitle)
      expect(html).toContain(copy.contextHeading)
      expect(html).toContain(copy.reviewQueueHeading)
      expect(html).toContain(copy.overridesHeading)
      expect(html).not.toContain('undefined')
      expect(html).not.toContain('null')
      expect(html).not.toContain('P6-B')
      expect(html).not.toContain('B5c')
    }
  })
})

function createTestManagement(
  overrides: Partial<CampaignChangesManagement> = {},
): CampaignChangesManagement {
  return {
    characters: [],
    formState: null,
    pending: false,
    formError: null,
    mutationError: null,
    committedWarning: null,
    onOpenCreate: vi.fn(),
    onOpenEdit: vi.fn(),
    onCancelForm: vi.fn(),
    onChangeForm: vi.fn(),
    onSubmitForm: vi.fn(),
    onArchiveEntry: vi.fn(),
    overrideFormState: null,
    overrideFormError: null,
    onOpenCreateOverride: vi.fn(),
    onOpenEditOverride: vi.fn(),
    onCancelOverrideForm: vi.fn(),
    onChangeOverrideForm: vi.fn(),
    onSubmitOverrideForm: vi.fn(),
    onClearOverride: vi.fn(),
    contextFormState: null,
    contextFormError: null,
    onOpenEditContext: vi.fn(),
    onCancelEditContext: vi.fn(),
    onChangeContextForm: vi.fn(),
    onSubmitContextForm: vi.fn(),
    onClearContext: vi.fn(),
    ...overrides,
  }
}

describe('B5c Fix 1 — Conductor Review regressions', () => {
  const copy = campaignRuntimeCopy('en')

  it('renders informational empty notice and provides Edit Context and Add Runtime controls on empty campaign', () => {
    const management = createTestManagement()
    const html = renderToStaticMarkup(
      <CampaignChangesView
        roomId={ROOM_ID}
        campaignId={CAMPAIGN_ID}
        loading={false}
        error={null}
        entries={[]}
        overrides={[]}
        context={null}
        attachedAdventures={[]}
        overlays={[]}
        management={management}
        copy={copy}
      />,
    )

    // Empty state is rendered as informational message:
    expect(html).toContain(copy.emptyState)
    // Context section has Edit Context button:
    expect(html).toContain(copy.editContextButton)
    // Entries section has Add Runtime Entry button:
    expect(html).toContain(copy.createEntryButton)
    // Only 1 Add Runtime button is rendered (no duplicate):
    const occurrences = html.split(copy.createEntryButton).length - 1
    expect(occurrences).toBe(1)
  })

  it('renders zero action buttons when action contract is null across Review Queue, Context, and Overrides', () => {
    // 1. Review Queue with actions=null
    const reviewHtml = renderToStaticMarkup(
      <CampaignRuntimeReviewQueue
        items={[
          {
            type: 'runtime',
            entry: {
              id: 'e-1',
              campaign_id: CAMPAIGN_ID,
              kind: 'fact',
              title: 'Fact 1',
              body: null,
              state: { kind: 'fact' },
              visibility: 'public',
              dm_notes: null,
              needs_review: true,
              source_adventure_entry_id: null,
              provenance_json: null,
              character_recipient_ids: [],
              revision: 1,
              created_by_actor_kind: 'human',
              created_by_actor_id: null,
              created_at: '',
              updated_at: '',
              archived_at: null,
            },
          },
        ]}
        actions={null}
        copy={copy}
      />,
    )
    expect(reviewHtml).toContain('Fact 1')
    expect(reviewHtml).not.toContain('<button')
    expect(reviewHtml).not.toContain(copy.reviewButton)

    // 2. Context with actions=null
    const contextHtml = renderToStaticMarkup(
      <CampaignRuntimeContextView
        context={{
          campaign_id: CAMPAIGN_ID,
          current_adventure_scene_entry_id: null,
          current_runtime_scene_entry_id: null,
          current_situation: 'Resting',
          revision: 1,
          created_at: null,
          updated_at: null,
        }}
        entries={[]}
        overlays={[]}
        attachedAdventures={[]}
        actions={null}
        copy={copy}
      />,
    )
    expect(contextHtml).toContain('Resting')
    expect(contextHtml).not.toContain('<button')
    expect(contextHtml).not.toContain(copy.editContextButton)
    expect(contextHtml).not.toContain(copy.clearContextButton)

    // 3. Overrides section with actions=null
    const adv: AttachedAdventure = {
      campaign_id: CAMPAIGN_ID,
      adventure_id: ADV_1_ID,
      sort_order: 1,
      attached_at: '',
      name: 'Phandelver',
      summary: null,
      status: 'finalized',
    }
    const overlay: CampaignAdventureEntryOverlayView = {
      id: ENTRY_1_ID,
      adventure_id: ADV_1_ID,
      parent_entry_id: null,
      kind: 'scene',
      title: 'Goblin Cave',
      body: null,
      data: { kind: 'scene' },
      visibility: 'dm_only',
      sort_order: 1,
      override: {
        id: 'ovr-1',
        campaign_id: CAMPAIGN_ID,
        adventure_entry_id: ENTRY_1_ID,
        state_json: { test: true },
        note: 'DM note',
        needs_review: false,
        revision: 1,
        created_at: '',
        updated_at: '',
      },
    }
    const overridesHtml = renderToStaticMarkup(
      <CampaignAttachedAdventuresSection
        attachedAdventures={[adv]}
        overlays={[overlay]}
        overrideCount={1}
        context={null}
        actions={null}
        copy={copy}
      />,
    )
    expect(overridesHtml).toContain('Goblin Cave')
    expect(overridesHtml).toContain('DM note')
    expect(overridesHtml).not.toContain('<button')
    expect(overridesHtml).not.toContain(copy.createOverrideButton)
    expect(overridesHtml).not.toContain(copy.editOverrideButton)
    expect(overridesHtml).not.toContain(copy.clearOverrideButton)
  })

  it('localizes all AdventureEntryKind values in en and zh-TW without machine token leakage', () => {
    const allAdventureKinds: AdventureEntryKind[] = [
      'section',
      'scene',
      'npc',
      'item',
      'monster_ref',
      'quest',
      'secret',
      'dm_note',
      'suggested_check',
      'map',
      'lore',
      'other',
    ]

    for (const loc of ['en', 'zh-TW'] as const) {
      const locCopy = campaignRuntimeCopy(loc)
      for (const kind of allAdventureKinds) {
        const label = adventureEntryKindLabel(kind, locCopy)
        expect(label).toBeTruthy()
        expect(label).not.toBe(kind)
        expect(typeof label).toBe('string')
      }
    }

    const copyEn = campaignRuntimeCopy('en')
    expect(adventureEntryKindLabel('section', copyEn)).toBe('Section')
    expect(adventureEntryKindLabel('monster_ref', copyEn)).toBe('Monster Reference')
    expect(adventureEntryKindLabel('dm_note', copyEn)).toBe('DM Note')
    expect(adventureEntryKindLabel('suggested_check', copyEn)).toBe('Suggested Check')
    expect(adventureEntryKindLabel('map', copyEn)).toBe('Map')
    expect(adventureEntryKindLabel('lore', copyEn)).toBe('Lore')

    const copyZh = campaignRuntimeCopy('zh-TW')
    expect(adventureEntryKindLabel('section', copyZh)).toBe('章節')
    expect(adventureEntryKindLabel('monster_ref', copyZh)).toBe('怪物參照')
    expect(adventureEntryKindLabel('dm_note', copyZh)).toBe('DM 備忘')
    expect(adventureEntryKindLabel('suggested_check', copyZh)).toBe('建議檢定')
    expect(adventureEntryKindLabel('map', copyZh)).toBe('地圖')
    expect(adventureEntryKindLabel('lore', copyZh)).toBe('傳聞知識')
  })

  it('renders global mutation error at the top of the card and keeps refreshed content visible', () => {
    const refreshedSituation = 'Situation updated by concurrent DM'
    const management = createTestManagement({
      mutationError: copy.errCampaignRuntimeRevisionConflict,
      contextFormState: null,
      overrideFormState: null,
    })

    const html = renderToStaticMarkup(
      <CampaignChangesView
        roomId={ROOM_ID}
        campaignId={CAMPAIGN_ID}
        loading={false}
        error={null}
        entries={[]}
        overrides={[]}
        context={{
          campaign_id: CAMPAIGN_ID,
          current_adventure_scene_entry_id: null,
          current_runtime_scene_entry_id: null,
          current_situation: refreshedSituation,
          revision: 2,
          created_at: null,
          updated_at: null,
        }}
        attachedAdventures={[]}
        overlays={[]}
        management={management}
        copy={copy}
      />,
    )

    expect(html).toContain('error-banner')
    expect(html).toContain(copy.errCampaignRuntimeRevisionConflict)
    expect(html).toContain(refreshedSituation)
    expect(html).not.toContain('<input')
    expect(html).not.toContain('<textarea')
  })

  it('shows non-blocking reminder hint and keeps Add Runtime Entry and Edit Context buttons enabled when review items exist', () => {
    for (const loc of ['en', 'zh-TW'] as const) {
      const locCopy = campaignRuntimeCopy(loc)
      expect(locCopy.reviewQueueHint).toBeTruthy()
      expect(locCopy.reviewButton).toBe(loc === 'en' ? 'Open/Edit' : '檢視／編輯')

      const management = createTestManagement()
      const items = [
        {
          type: 'runtime' as const,
          entry: {
            id: 'e-1',
            campaign_id: CAMPAIGN_ID,
            kind: 'fact' as const,
            title: 'Flagged rumor',
            body: null,
            state: { kind: 'fact' as const },
            visibility: 'public' as const,
            dm_notes: null,
            needs_review: true,
            source_adventure_entry_id: null,
            provenance_json: null,
            character_recipient_ids: [],
            revision: 1,
            created_by_actor_kind: 'human' as const,
            created_by_actor_id: null,
            created_at: '',
            updated_at: '',
            archived_at: null,
          },
        },
      ]

      const html = renderToStaticMarkup(
        <CampaignChangesView
          roomId={ROOM_ID}
          campaignId={CAMPAIGN_ID}
          loading={false}
          error={null}
          entries={[items[0].entry]}
          overrides={[]}
          context={{
            campaign_id: CAMPAIGN_ID,
            current_adventure_scene_entry_id: null,
            current_runtime_scene_entry_id: null,
            current_situation: 'Active Situation',
            revision: 1,
            created_at: null,
            updated_at: null,
          }}
          attachedAdventures={[]}
          overlays={[]}
          management={management}
          copy={locCopy}
        />,
      )

      expect(html).toContain(locCopy.reviewQueueHint)
      expect(html).toContain(locCopy.reviewButton)
      expect(html).toContain(locCopy.createEntryButton)
      expect(html).toContain(locCopy.editContextButton)
    }
  })

  it('triggers onConflict callback and reloads on 409 revision conflict in executeRuntimeMutation', async () => {
    const callOrder: string[] = []
    const onReload = vi.fn().mockImplementation(async () => {
      callOrder.push('reload')
    })
    const onConflict = vi.fn().mockImplementation((msg: string) => {
      callOrder.push(`conflict:${msg}`)
    })
    const onError = vi.fn().mockImplementation(() => {
      callOrder.push('error')
    })

    const action = vi.fn().mockRejectedValue(
      new CampaignRuntimeApiError(409, 'campaign_runtime_revision_conflict', 'conflict'),
    )

    const success = await executeRuntimeMutation({
      action,
      onReload,
      onConflict,
      onError,
      onCommittedReloadError: vi.fn(),
      copy,
    })

    expect(success).toBe(false)
    expect(callOrder).toEqual(['reload', `conflict:${copy.errCampaignRuntimeRevisionConflict}`])
    expect(onError).not.toHaveBeenCalled()
  })
})
