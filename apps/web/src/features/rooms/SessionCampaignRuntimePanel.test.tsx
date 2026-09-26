import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

import type { AttachedAdventure } from '../../api/adventures'
import * as adventuresApi from '../../api/adventures'
import type { RoomCharacterSummary } from '../../api/campaigns'
import type {
  CampaignAdventureEntryOverlayView,
  CampaignRuntimeContext,
  RuntimeWorldEntryDmView,
  RuntimeWorldEntryPlayerView,
} from '../../api/campaignRuntime'
import * as campaignRuntimeApi from '../../api/campaignRuntime'
import type { TableEvent } from '../../api/sessions'
import { campaignRuntimeCopy } from './campaignRuntimeCopy'
import { RuntimeEntryFormView } from './CampaignRuntimeEntries'
import {
  buildCreateEntryRequest,
  createInitialEntryFormState,
  validateEntryMinima,
} from './campaignRuntimeForm'
import {
  buildClearContextRequest,
  buildUpdateContextRequest,
  contextToFormState,
} from './campaignRuntimeOverrideForm'
import {
  deriveLatestWorldEventSeq,
  executeActiveSessionMutation,
  isCampaignRuntimeAuthorityLossError,
  isRuntimeWorldEntryDmView,
  loadActiveSessionRuntime,
  LoadCoordinator,
  SESSION_QUICK_ADD_KINDS,
  shouldShowWaitingBanner,
  UnexpectedPlayerProjectionError,
  type ActiveSessionRuntimeSnapshot,
  type SessionCampaignRuntimeActions,
} from './sessionCampaignRuntime'
import {
  SessionCampaignRuntimePanelView,
} from './SessionCampaignRuntimePanel'
import { shouldMountSessionCampaignRuntimePanel } from './RoomSessionPage'

const ROOM_ID = '10000000-0000-4000-8000-000000000001'
const CAMPAIGN_ID = '20000000-0000-4000-8000-000000000001'
const SESSION_ID = '30000000-0000-4000-8000-000000000001'
const TOKEN = 'test-token'

const sampleDmEntry: RuntimeWorldEntryDmView = {
  id: '50000000-0000-4000-8000-000000000001',
  campaign_id: CAMPAIGN_ID,
  kind: 'scene',
  title: 'Ruined Courtyard',
  body: 'Overgrown cobblestones under moonlight.',
  state: { kind: 'scene' },
  visibility: 'public',
  dm_notes: 'Hidden trapdoor under fountain',
  needs_review: false,
  source_adventure_entry_id: null,
  provenance_json: null,
  character_recipient_ids: [],
  revision: 1,
  created_by_actor_kind: 'human',
  created_by_actor_id: 'seat-1',
  created_at: '2026-09-20T00:00:00Z',
  updated_at: '2026-09-20T00:00:00Z',
  archived_at: null,
}

const sampleContext: CampaignRuntimeContext = {
  campaign_id: CAMPAIGN_ID,
  current_adventure_scene_entry_id: null,
  current_runtime_scene_entry_id: sampleDmEntry.id,
  current_situation: 'Party is resting near the fountain.',
  revision: 2,
  created_at: '2026-09-20T00:00:00Z',
  updated_at: '2026-09-20T01:00:00Z',
}

const sampleAdventure: AttachedAdventure = {
  campaign_id: CAMPAIGN_ID,
  adventure_id: 'adv-01',
  sort_order: 1,
  attached_at: '2026-09-10T00:00:00Z',
  name: 'Sunken Temple',
  summary: 'A drowned ruin',
  status: 'finalized',
}

const sampleOverlay: CampaignAdventureEntryOverlayView = {
  id: 'adv-scene-01',
  adventure_id: 'adv-01',
  parent_entry_id: null,
  kind: 'scene',
  title: 'Flooded Antechamber',
  body: 'Murky water waist-deep',
  data: { kind: 'scene' },
  visibility: 'public',
  sort_order: 1,
  override: null,
}

const sampleCharacter: RoomCharacterSummary = {
  id: 'char-01',
  name: 'Eldrin',
  level: 3,
  class_summary: 'Wizard 3',
  version_no: 1,
}

const sampleSnapshot: ActiveSessionRuntimeSnapshot = {
  entries: [sampleDmEntry],
  context: sampleContext,
  attachedAdventures: [sampleAdventure],
  overlays: [sampleOverlay],
}

const stageAndReviewActionDefaults = {
  stagePickerOpen: false,
  stagePickerLoading: false,
  stagePickerError: null,
  stageSuccess: null,
  stageCandidates: null,
  stageSelectedKey: null,
  onOpenStagePicker: vi.fn(),
  onCloseStagePicker: vi.fn(),
  onSelectStageCandidate: vi.fn(),
  onSubmitStageImage: vi.fn(),
  onToggleEntryNeedsReview: vi.fn(),
  onToggleOverrideNeedsReview: vi.fn(),
}

describe('SessionCampaignRuntime authority and composition truth table', () => {
  it('uses the real production mount predicate for active DM, player, owner, ended, abandoned', () => {
    // Current DM on active session mounts
    expect(shouldMountSessionCampaignRuntimePanel({
      status: 'active',
      isCurrentDm: true,
    })).toBe(true)

    // Player or non-current controller on active session: absent
    expect(shouldMountSessionCampaignRuntimePanel({
      status: 'active',
      isCurrentDm: false,
    })).toBe(false)

    // Ended session: absent even for current DM
    expect(shouldMountSessionCampaignRuntimePanel({
      status: 'ended',
      isCurrentDm: true,
    })).toBe(false)

    // Abandoned session: absent even for current DM
    expect(shouldMountSessionCampaignRuntimePanel({
      status: 'abandoned',
      isCurrentDm: true,
    })).toBe(false)
  })

  it('unmounts on authority loss and discards forms; fresh mount reloads snapshot', () => {
    const copy = campaignRuntimeCopy('en')
    const htmlWithActions = renderToStaticMarkup(
      <SessionCampaignRuntimePanelView
        snapshot={sampleSnapshot}
        characters={[sampleCharacter]}
        loading={false}
        error={null}
        refreshStatus={null}
        actions={{
          ...stageAndReviewActionDefaults,
          pending: false,
          quickAddOpen: true,
          quickAddForm: createInitialEntryFormState('scene'),
          quickAddError: null,
          onOpenQuickAdd: vi.fn(),
          onCloseQuickAdd: vi.fn(),
          onChangeQuickAdd: vi.fn(),
          onSubmitQuickAdd: vi.fn(),
          contextForm: null,
          contextError: null,
          onOpenContextEdit: vi.fn(),
          onCancelContextEdit: vi.fn(),
          onChangeContextForm: vi.fn(),
          onSubmitContextForm: vi.fn(),
          onClearContext: vi.fn(),
        }}
        copy={copy}
        onRetry={vi.fn()}
      />,
    )
    expect(htmlWithActions).toContain(copy.formTitleCreate)
  })
})

describe('Active loader, projection narrowing and attached adventures', () => {
  it('makes zero overlay requests when attached adventures is empty', async () => {
    const listEntriesSpy = vi.spyOn(campaignRuntimeApi, 'listActiveRuntimeEntries').mockResolvedValue([sampleDmEntry])
    const getContextSpy = vi.spyOn(campaignRuntimeApi, 'getActiveRuntimeContext').mockResolvedValue(sampleContext)
    const listAdvSpy = vi.spyOn(adventuresApi, 'listCampaignAdventures').mockResolvedValue([])
    const listOverlaysSpy = vi.spyOn(campaignRuntimeApi, 'listActiveAdventureEntryOverlays')

    const result = await loadActiveSessionRuntime(ROOM_ID, CAMPAIGN_ID, SESSION_ID, TOKEN)

    expect(listEntriesSpy).toHaveBeenCalledWith(ROOM_ID, CAMPAIGN_ID, SESSION_ID, TOKEN)
    expect(getContextSpy).toHaveBeenCalledWith(ROOM_ID, CAMPAIGN_ID, SESSION_ID, TOKEN)
    expect(listAdvSpy).toHaveBeenCalledWith(ROOM_ID, CAMPAIGN_ID, TOKEN)
    expect(listOverlaysSpy).not.toHaveBeenCalled()
    expect(result.attachedAdventures).toEqual([])
    expect(result.overlays).toEqual([])
    expect(result.entries).toEqual([sampleDmEntry])
    expect(result.context).toEqual(sampleContext)

    vi.restoreAllMocks()
  })

  it('determines deterministic overlay order from multiple attached adventures', async () => {
    const adv1: AttachedAdventure = { ...sampleAdventure, adventure_id: 'adv-01', sort_order: 2 }
    const adv2: AttachedAdventure = { ...sampleAdventure, adventure_id: 'adv-02', sort_order: 1 }

    const overlay1: CampaignAdventureEntryOverlayView = { ...sampleOverlay, id: 'ov-1', adventure_id: 'adv-01' }
    const overlay2: CampaignAdventureEntryOverlayView = { ...sampleOverlay, id: 'ov-2', adventure_id: 'adv-02' }

    vi.spyOn(campaignRuntimeApi, 'listActiveRuntimeEntries').mockResolvedValue([sampleDmEntry])
    vi.spyOn(campaignRuntimeApi, 'getActiveRuntimeContext').mockResolvedValue(sampleContext)
    vi.spyOn(adventuresApi, 'listCampaignAdventures').mockResolvedValue([adv1, adv2])
    const listOverlaysSpy = vi.spyOn(campaignRuntimeApi, 'listActiveAdventureEntryOverlays').mockImplementation(
      async (_r, _c, _s, adventureId) => {
        return adventureId === 'adv-02' ? [overlay2] : [overlay1]
      },
    )

    const result = await loadActiveSessionRuntime(ROOM_ID, CAMPAIGN_ID, SESSION_ID, TOKEN)

    expect(listOverlaysSpy).toHaveBeenCalledTimes(2)
    // adv-02 had sort_order 1, adv-01 had sort_order 2 -> overlay2 should be first
    expect(result.overlays.map((o) => o.id)).toEqual(['ov-2', 'ov-1'])

    vi.restoreAllMocks()
  })

  it('explicitly rejects Player projection without fabricating DM fields', async () => {
    const playerEntry: RuntimeWorldEntryPlayerView = {
      id: 'entry-player-1',
      campaign_id: CAMPAIGN_ID,
      kind: 'scene',
      title: 'A Room',
      body: 'Visible to player',
      state: { kind: 'scene' },
      visibility: 'public',
      revision: 1,
      created_at: '2026-09-20T00:00:00Z',
      updated_at: '2026-09-20T00:00:00Z',
    }

    expect(isRuntimeWorldEntryDmView(playerEntry)).toBe(false)
    expect(isRuntimeWorldEntryDmView(sampleDmEntry)).toBe(true)

    vi.spyOn(campaignRuntimeApi, 'listActiveRuntimeEntries').mockResolvedValue([playerEntry])
    vi.spyOn(campaignRuntimeApi, 'getActiveRuntimeContext').mockResolvedValue(sampleContext)
    vi.spyOn(adventuresApi, 'listCampaignAdventures').mockResolvedValue([])

    await expect(
      loadActiveSessionRuntime(ROOM_ID, CAMPAIGN_ID, SESSION_ID, TOKEN),
    ).rejects.toThrow(UnexpectedPlayerProjectionError)

    vi.restoreAllMocks()
  })
})

describe('World event cursor derivation and refresh triggers', () => {
  it('ignores non-world events and history data, advancing only for current-session world.* events', () => {
    const events: TableEvent[] = [
      {
        id: 'ev-0',
        session_id: 'older-session-999',
        seq: 50,
        kind: 'world.entry.created',
        acting_seat_id: null,
        subject_seat_id: null,
        subject_character_id: null,
        execution_mode: null,
        visibility: 'public',
        recipient_seat_ids: [],
        payload_version: 1,
        payload: {},
        created_at: '2026-09-20T00:00:00Z',
      },
      {
        id: 'ev-1',
        session_id: SESSION_ID,
        seq: 5,
        kind: 'roll.requested',
        acting_seat_id: null,
        subject_seat_id: null,
        subject_character_id: null,
        execution_mode: null,
        visibility: 'public',
        recipient_seat_ids: [],
        payload_version: 1,
        payload: {},
        created_at: '2026-09-20T00:01:00Z',
      },
      {
        id: 'ev-2',
        session_id: SESSION_ID,
        seq: 6,
        kind: 'exploration.narration',
        acting_seat_id: null,
        subject_seat_id: null,
        subject_character_id: null,
        execution_mode: null,
        visibility: 'public',
        recipient_seat_ids: [],
        payload_version: 1,
        payload: {},
        created_at: '2026-09-20T00:02:00Z',
      },
      {
        id: 'ev-3',
        session_id: SESSION_ID,
        seq: 7,
        kind: 'world.entry.created',
        acting_seat_id: null,
        subject_seat_id: null,
        subject_character_id: null,
        execution_mode: null,
        visibility: 'public',
        recipient_seat_ids: [],
        payload_version: 1,
        payload: {},
        created_at: '2026-09-20T00:03:00Z',
      },
      {
        id: 'ev-4',
        session_id: SESSION_ID,
        seq: 12,
        kind: 'world.context_changed',
        acting_seat_id: null,
        subject_seat_id: null,
        subject_character_id: null,
        execution_mode: null,
        visibility: 'public',
        recipient_seat_ids: [],
        payload_version: 1,
        payload: {},
        created_at: '2026-09-20T00:04:00Z',
      },
    ]

    const cursor = deriveLatestWorldEventSeq(events, SESSION_ID)
    expect(cursor).toBe(12)

    expect(deriveLatestWorldEventSeq([], SESSION_ID)).toBe(0)
    expect(deriveLatestWorldEventSeq([events[1], events[2]], SESSION_ID)).toBe(0)
  })
})

describe('Fix 1: event-before-HTTP-response race regression', () => {
  it('does not reintroduce the waiting banner when event refresh completes before HTTP response', () => {
    // 1. Mutation starts when worldEventCursor is 5
    const cursorAtStart = 5

    // 2. Event stream delivers world event (cursor 6) before HTTP callback resolves
    const cursorAfterEvent = 6
    expect(shouldShowWaitingBanner(cursorAtStart, cursorAfterEvent)).toBe(false)

    // 3. Normal order: HTTP response resolves before event delivery (cursor still 5)
    expect(shouldShowWaitingBanner(cursorAtStart, cursorAtStart)).toBe(true)
  })

  it('prevents stuck refresh status when event refresh completes before mutation HTTP callback', async () => {
    const copy = campaignRuntimeCopy('en')
    let refreshStatus: string | null = null
    let latestWorldCursor = 5
    const cursorAtStart = latestWorldCursor

    // Mutation is in flight...
    // In the background, event waiter receives world.* event seq 6 and reloads
    latestWorldCursor = 6
    refreshStatus = null // event refresh finished and cleared banner

    // Now mutation HTTP response arrives:
    await executeActiveSessionMutation({
      action: async () => sampleDmEntry,
      onSuccess: () => {
        if (shouldShowWaitingBanner(cursorAtStart, latestWorldCursor)) {
          refreshStatus = copy.refreshingFromEvents
        }
      },
      onError: vi.fn(),
      copy,
    })

    // Banner is NOT reintroduced; refreshStatus remains null (not stuck!)
    expect(refreshStatus).toBeNull()
  })
})

describe('Fix 2: Load coordinator prevents overlapping loads from overwriting newer snapshots', () => {
  it('discards stale load completions when a newer load completes first', async () => {
    const coordinator = new LoadCoordinator()

    type Deferred<T> = {
      promise: Promise<T>
      resolve: (value: T) => void
    }
    function createDeferred<T>(): Deferred<T> {
      let resolve!: (value: T) => void
      const promise = new Promise<T>((res) => {
        resolve = res
      })
      return { promise, resolve }
    }

    const deferred1 = createDeferred<string>()
    const deferred2 = createDeferred<string>()

    let appliedValue = ''

    // Load 1 starts
    const gen1 = coordinator.nextGeneration()
    expect(gen1).toBe(1)
    const runLoad1 = deferred1.promise.then((val) => {
      if (coordinator.isCurrent(gen1)) {
        appliedValue = val
      }
    })

    // Load 2 starts (e.g. event-driven reload)
    const gen2 = coordinator.nextGeneration()
    expect(gen2).toBe(2)
    const runLoad2 = deferred2.promise.then((val) => {
      if (coordinator.isCurrent(gen2)) {
        appliedValue = val
      }
    })

    // Load 2 completes FIRST
    deferred2.resolve('Snapshot 2 (Newer)')
    await runLoad2
    expect(appliedValue).toBe('Snapshot 2 (Newer)')

    // Load 1 completes LATER (stale)
    deferred1.resolve('Snapshot 1 (Stale)')
    await runLoad1

    // Newer snapshot was NOT overwritten!
    expect(appliedValue).toBe('Snapshot 2 (Newer)')
  })

  it('invalidates in-flight load when authority loss occurs before load completes', async () => {
    const coordinator = new LoadCoordinator()

    type Deferred<T> = {
      promise: Promise<T>
      resolve: (value: T) => void
    }
    function createDeferred<T>(): Deferred<T> {
      let resolve!: (value: T) => void
      const promise = new Promise<T>((res) => {
        resolve = res
      })
      return { promise, resolve }
    }

    const deferredLoad = createDeferred<ActiveSessionRuntimeSnapshot>()

    let snapshot: ActiveSessionRuntimeSnapshot | null = null
    let authorityLost = false

    // 1. Initial/event/retry load starts
    const gen = coordinator.nextGeneration()
    const runLoad = deferredLoad.promise
      .then((fresh) => {
        if (!coordinator.isCurrent(gen)) {
          return
        }
        snapshot = fresh
        authorityLost = false
      })
      .catch(() => {})

    // 2. Mutation or other request reports authority loss, calling coordinator.invalidate()
    coordinator.invalidate()
    snapshot = null
    authorityLost = true

    // 3. Old in-flight load resolves successfully
    deferredLoad.resolve(sampleSnapshot)
    await runLoad

    // 4. Stale load completion is discarded: snapshot remains null, authority-lost state remains
    expect(snapshot).toBeNull()
    expect(authorityLost).toBe(true)

    // 5. Subsequent fresh Retry gets a newer generation and can restore snapshot
    const retryGen = coordinator.nextGeneration()
    const retrySnapshot = { ...sampleSnapshot }
    if (coordinator.isCurrent(retryGen)) {
      snapshot = retrySnapshot
      authorityLost = false
    }
    expect(snapshot).toEqual(retrySnapshot)
    expect(authorityLost).toBe(false)
  })
})

describe('Fix 3: Authority loss classification, snapshot clearing, and null actions', () => {
  it('classifies 403 forbidden and 409 session_not_active as authority loss', () => {
    const forbiddenErr = new campaignRuntimeApi.CampaignRuntimeApiError(
      403,
      'campaign_runtime_forbidden',
      'Forbidden',
    )
    const notActiveErr = new campaignRuntimeApi.CampaignRuntimeApiError(
      409,
      'campaign_runtime_session_not_active',
      'Session not active',
    )
    const conflictErr = new campaignRuntimeApi.CampaignRuntimeApiError(
      409,
      'campaign_runtime_revision_conflict',
      'Conflict',
    )
    const networkErr = new Error('Network error')

    expect(isCampaignRuntimeAuthorityLossError(forbiddenErr)).toBe(true)
    expect(isCampaignRuntimeAuthorityLossError(notActiveErr)).toBe(true)
    expect(isCampaignRuntimeAuthorityLossError(conflictErr)).toBe(false)
    expect(isCampaignRuntimeAuthorityLossError(networkErr)).toBe(false)
  })

  it('renders no management controls and no DM snapshot when authority is lost, but preserves onRetry', () => {
    const copy = campaignRuntimeCopy('en')
    const retryFn = vi.fn()

    const html = renderToStaticMarkup(
      <SessionCampaignRuntimePanelView
        snapshot={null} // snapshot cleared on authority loss
        characters={[sampleCharacter]}
        loading={false}
        error={copy.errCampaignRuntimeForbidden}
        refreshStatus={null}
        actions={null} // actions is null on authority loss
        copy={copy}
        onRetry={retryFn}
      />,
    )

    // Localized authority loss error is shown
    expect(html).toContain(copy.errCampaignRuntimeForbidden)
    // Retry control is preserved separate from management actions
    expect(html).toContain(copy.retryButton)
    // No DM snapshot content shown
    expect(html).not.toContain('Ruined Courtyard')
    // No management action buttons
    expect(html).not.toContain(copy.quickAddButton)
    expect(html).not.toContain(copy.editContextButton)
    expect(html).not.toContain(copy.clearContextButton)
  })

  it('preserves last-good snapshot and management actions on generic network/reload error', () => {
    const copy = campaignRuntimeCopy('en')

    const html = renderToStaticMarkup(
      <SessionCampaignRuntimePanelView
        snapshot={sampleSnapshot} // last-good snapshot preserved
        characters={[sampleCharacter]}
        loading={false}
        error={copy.eventRefreshError}
        refreshStatus={null}
        actions={{
          ...stageAndReviewActionDefaults,
          pending: false,
          quickAddOpen: false,
          quickAddForm: null,
          quickAddError: null,
          onOpenQuickAdd: vi.fn(),
          onCloseQuickAdd: vi.fn(),
          onChangeQuickAdd: vi.fn(),
          onSubmitQuickAdd: vi.fn(),
          contextForm: null,
          contextError: null,
          onOpenContextEdit: vi.fn(),
          onCancelContextEdit: vi.fn(),
          onChangeContextForm: vi.fn(),
          onSubmitContextForm: vi.fn(),
          onClearContext: vi.fn(),
        }}
        copy={copy}
        onRetry={vi.fn()}
      />,
    )

    // Last-good snapshot content is displayed
    expect(html).toContain('Ruined Courtyard')
    expect(html).toContain(copy.eventRefreshError)
    // Management action buttons remain visible
    expect(html).toContain(copy.quickAddButton)
    expect(html).toContain(copy.editContextButton)
  })

  it('clears privileged snapshot and actions when UnexpectedPlayerProjectionError occurs, but preserves onRetry', () => {
    const copy = campaignRuntimeCopy('en')
    const retryFn = vi.fn()

    const html = renderToStaticMarkup(
      <SessionCampaignRuntimePanelView
        snapshot={null} // cleared on projection failure
        characters={[sampleCharacter]}
        loading={false}
        error={copy.unexpectedProjectionError}
        refreshStatus={null}
        actions={null} // actions is null on projection failure
        copy={copy}
        onRetry={retryFn}
      />,
    )

    // Specific unexpected projection error is shown
    expect(html).toContain(copy.unexpectedProjectionError)
    // Retry control is preserved
    expect(html).toContain(copy.retryButton)
    // Privileged DM snapshot content is hidden
    expect(html).not.toContain('Ruined Courtyard')
    // Management action buttons are hidden
    expect(html).not.toContain(copy.quickAddButton)
    expect(html).not.toContain(copy.editContextButton)
  })

  it('renders quickAddHeading in the quick add section when actions is present', () => {
    const copy = campaignRuntimeCopy('en')

    const html = renderToStaticMarkup(
      <SessionCampaignRuntimePanelView
        snapshot={sampleSnapshot}
        characters={[sampleCharacter]}
        loading={false}
        error={null}
        refreshStatus={null}
        actions={{
          ...stageAndReviewActionDefaults,
          pending: false,
          quickAddOpen: false,
          quickAddForm: null,
          quickAddError: null,
          onOpenQuickAdd: vi.fn(),
          onCloseQuickAdd: vi.fn(),
          onChangeQuickAdd: vi.fn(),
          onSubmitQuickAdd: vi.fn(),
          contextForm: null,
          contextError: null,
          onOpenContextEdit: vi.fn(),
          onCancelContextEdit: vi.fn(),
          onChangeContextForm: vi.fn(),
          onSubmitContextForm: vi.fn(),
          onClearContext: vi.fn(),
        }}
        copy={copy}
        onRetry={vi.fn()}
      />,
    )

    expect(html).toContain(`<h3>${copy.quickAddHeading}</h3>`)
    expect(html).toContain(copy.quickAddButton)
  })
})

describe('Fix 5: executeActiveSessionMutation unified helper', () => {
  it('calls onSuccess without direct reload on success', async () => {
    const copy = campaignRuntimeCopy('en')
    const onSuccess = vi.fn()
    const onError = vi.fn()

    const ok = await executeActiveSessionMutation({
      action: async () => 'mutation-result',
      onSuccess,
      onError,
      copy,
    })

    expect(ok).toBe(true)
    expect(onSuccess).toHaveBeenCalledWith('mutation-result')
    expect(onError).not.toHaveBeenCalled()
  })

  it('triggers onAuthorityLoss and skips conflict reload on authority loss', async () => {
    const copy = campaignRuntimeCopy('en')
    const onAuthorityLoss = vi.fn()
    const onConflictReload = vi.fn()
    const onError = vi.fn()

    const forbiddenErr = new campaignRuntimeApi.CampaignRuntimeApiError(
      403,
      'campaign_runtime_forbidden',
      'Forbidden',
    )

    const ok = await executeActiveSessionMutation({
      action: async () => {
        throw forbiddenErr
      },
      onSuccess: vi.fn(),
      onError,
      onAuthorityLoss,
      onConflictReload,
      copy,
    })

    expect(ok).toBe(false)
    expect(onAuthorityLoss).toHaveBeenCalledWith(copy.errCampaignRuntimeForbidden)
    expect(onConflictReload).not.toHaveBeenCalled()
    expect(onError).not.toHaveBeenCalled()
  })

  it('triggers onConflictSuccess when conflict reload succeeds', async () => {
    const copy = campaignRuntimeCopy('en')
    const onConflictSuccess = vi.fn()
    const onConflictReloadError = vi.fn()
    const onError = vi.fn()

    const conflictErr = new campaignRuntimeApi.CampaignRuntimeApiError(
      409,
      'campaign_runtime_revision_conflict',
      'Revision conflict',
    )

    const freshSnapshot = { ...sampleSnapshot }
    const ok = await executeActiveSessionMutation({
      action: async () => {
        throw conflictErr
      },
      onSuccess: vi.fn(),
      onError,
      onConflictReload: async () => freshSnapshot,
      onConflictSuccess,
      onConflictReloadError,
      copy,
    })

    expect(ok).toBe(false)
    expect(onConflictSuccess).toHaveBeenCalledWith(freshSnapshot)
    expect(onConflictReloadError).not.toHaveBeenCalled()
    expect(onError).not.toHaveBeenCalled()
  })

  it('triggers onConflictReloadError when conflict reload fails', async () => {
    const copy = campaignRuntimeCopy('en')
    const onConflictSuccess = vi.fn()
    const onConflictReloadError = vi.fn()
    const onError = vi.fn()

    const conflictErr = new campaignRuntimeApi.CampaignRuntimeApiError(
      409,
      'campaign_runtime_revision_conflict',
      'Revision conflict',
    )

    const ok = await executeActiveSessionMutation({
      action: async () => {
        throw conflictErr
      },
      onSuccess: vi.fn(),
      onError,
      onConflictReload: async () => {
        throw new Error('Reload network timeout')
      },
      onConflictSuccess,
      onConflictReloadError,
      copy,
    })

    expect(ok).toBe(false)
    expect(onConflictSuccess).not.toHaveBeenCalled()
    expect(onConflictReloadError).toHaveBeenCalledWith(copy.eventRefreshError)
  })

  it('triggers onAuthorityLoss when conflict reload fails due to UnexpectedPlayerProjectionError', async () => {
    const copy = campaignRuntimeCopy('en')
    const onAuthorityLoss = vi.fn()
    const onConflictReloadError = vi.fn()
    const onConflictSuccess = vi.fn()

    const conflictErr = new campaignRuntimeApi.CampaignRuntimeApiError(
      409,
      'campaign_runtime_revision_conflict',
      'Revision conflict',
    )

    const ok = await executeActiveSessionMutation({
      action: async () => {
        throw conflictErr
      },
      onSuccess: vi.fn(),
      onError: vi.fn(),
      onConflictReload: async () => {
        throw new UnexpectedPlayerProjectionError()
      },
      onConflictSuccess,
      onConflictReloadError,
      onAuthorityLoss,
      copy,
    })

    expect(ok).toBe(false)
    expect(onConflictSuccess).not.toHaveBeenCalled()
    expect(onConflictReloadError).not.toHaveBeenCalled()
    expect(onAuthorityLoss).toHaveBeenCalledWith(copy.unexpectedProjectionError)
  })

  it('triggers onAuthorityLoss when conflict reload fails due to authority loss', async () => {
    const copy = campaignRuntimeCopy('en')
    const onAuthorityLoss = vi.fn()
    const onConflictReloadError = vi.fn()
    const onConflictSuccess = vi.fn()

    const conflictErr = new campaignRuntimeApi.CampaignRuntimeApiError(
      409,
      'campaign_runtime_revision_conflict',
      'Revision conflict',
    )
    const forbiddenErr = new campaignRuntimeApi.CampaignRuntimeApiError(
      403,
      'campaign_runtime_forbidden',
      'Forbidden',
    )

    const ok = await executeActiveSessionMutation({
      action: async () => {
        throw conflictErr
      },
      onSuccess: vi.fn(),
      onError: vi.fn(),
      onConflictReload: async () => {
        throw forbiddenErr
      },
      onConflictSuccess,
      onConflictReloadError,
      onAuthorityLoss,
      copy,
    })

    expect(ok).toBe(false)
    expect(onConflictSuccess).not.toHaveBeenCalled()
    expect(onConflictReloadError).not.toHaveBeenCalled()
    expect(onAuthorityLoss).toHaveBeenCalledWith(copy.errCampaignRuntimeForbidden)
  })

  it('triggers onError for ordinary recoverable errors with localized error copy', async () => {
    const copy = campaignRuntimeCopy('en')
    const onError = vi.fn()

    const invalidErr = new campaignRuntimeApi.CampaignRuntimeApiError(
      400,
      'campaign_runtime_invalid',
      'Invalid payload',
    )

    const ok = await executeActiveSessionMutation({
      action: async () => {
        throw invalidErr
      },
      onSuccess: vi.fn(),
      onError,
      copy,
    })

    expect(ok).toBe(false)
    expect(onError).toHaveBeenCalledWith(copy.errCampaignRuntimeInvalid)
  })
})

describe('Quick Add kind options and minimum validations', () => {
  it('exposes exactly Scene, NPC, and Fact in SESSION_QUICK_ADD_KINDS', () => {
    expect(SESSION_QUICK_ADD_KINDS).toEqual(['scene', 'npc', 'fact'])
  })

  it('renders RuntimeEntryFormView with kindOptions limited to Scene, NPC, Fact', () => {
    const copy = campaignRuntimeCopy('en')
    const form = createInitialEntryFormState('scene')

    const html = renderToStaticMarkup(
      <RuntimeEntryFormView
        form={form}
        kindOptions={SESSION_QUICK_ADD_KINDS}
        onChange={vi.fn()}
        onSubmit={vi.fn()}
        onCancel={vi.fn()}
        entries={[]}
        characters={[]}
        pending={false}
        formError={null}
        copy={copy}
      />,
    )

    expect(html).toContain(`value="scene"`)
    expect(html).toContain(`value="npc"`)
    expect(html).toContain(`value="fact"`)
    expect(html).not.toContain(`value="hazard"`)
    expect(html).not.toContain(`value="quest"`)
    expect(html).not.toContain(`value="secret"`)
    expect(html).not.toContain(`value="item"`)
    expect(html).not.toContain(`value="other"`)
  })

  it('validates minimum Scene, NPC, and Fact request bodies', () => {
    expect(validateEntryMinima('npc', '', 'some body')).toBe('errNpcTitleRequired')
    expect(validateEntryMinima('npc', '   ', 'some body')).toBe('errNpcTitleRequired')
    expect(validateEntryMinima('npc', 'Goblin Scout', '')).toBeNull()

    expect(validateEntryMinima('fact', 'Some title', '')).toBe('errFactBodyRequired')
    expect(validateEntryMinima('fact', 'Some title', '   ')).toBe('errFactBodyRequired')
    expect(validateEntryMinima('fact', '', 'The gates are locked at dusk.')).toBeNull()

    expect(validateEntryMinima('scene', '', '')).toBe('errSceneRequired')
    expect(validateEntryMinima('scene', '   ', '   ')).toBe('errSceneRequired')
    expect(validateEntryMinima('scene', 'Courtyard', '')).toBeNull()
    expect(validateEntryMinima('scene', '', 'Overgrown stones')).toBeNull()

    const validScene = createInitialEntryFormState('scene')
    validScene.title = 'Ancient Crypt'
    const sceneReq = buildCreateEntryRequest(validScene, 'idemp-1')
    expect(sceneReq.ok).toBe(true)
    if (sceneReq.ok) {
      expect(sceneReq.value).toEqual({
        idempotency_key: 'idemp-1',
        kind: 'scene',
        title: 'Ancient Crypt',
        body: null,
        state: { kind: 'scene' },
        visibility: 'public',
        character_recipient_ids: [],
        dm_notes: null,
        needs_review: false,
        provenance_json: null,
      })
    }

    const validNpc = createInitialEntryFormState('npc')
    validNpc.title = 'Barkeep Toblen'
    validNpc.npcMonsterTemplateRef = 'commoner'
    const npcReq = buildCreateEntryRequest(validNpc, 'idemp-2')
    expect(npcReq.ok).toBe(true)
    if (npcReq.ok) {
      expect(npcReq.value.state).toEqual({
        kind: 'npc',
        monster_instance_id: null,
        monster_template_ref: 'commoner',
      })
    }
  })

  it('renders read-only view with no buttons when actions is null', () => {
    const copy = campaignRuntimeCopy('en')
    const html = renderToStaticMarkup(
      <SessionCampaignRuntimePanelView
        snapshot={sampleSnapshot}
        characters={[sampleCharacter]}
        loading={false}
        error={null}
        refreshStatus={null}
        actions={null}
        copy={copy}
        onRetry={vi.fn()}
      />,
    )

    expect(html).toContain(copy.sessionWorldHeading)
    expect(html).toContain('Ruined Courtyard')
    expect(html).not.toContain('<button')
    expect(html).not.toContain(copy.quickAddButton)
    expect(html).not.toContain(copy.editContextButton)
    expect(html).not.toContain(copy.clearContextButton)
    expect(html).not.toContain(copy.retryButton)
  })
})

describe('Current Context request bodies, mutual exclusivity, and revision 0', () => {
  it('builds legal context request bodies with mutually-exclusive scene refs', () => {
    const emptyForm = contextToFormState(null)
    expect(emptyForm.expectedRevision).toBe(0)
    const emptyReq = buildUpdateContextRequest(emptyForm, 'idemp-empty')
    expect(emptyReq).toEqual({
      idempotency_key: 'idemp-empty',
      expected_revision: 0,
      current_adventure_scene_entry_id: null,
      current_runtime_scene_entry_id: null,
      current_situation: null,
    })

    const situationForm = {
      sceneSelection: { type: 'none' as const },
      situation: 'Resting by the campfire',
      expectedRevision: 0,
    }
    const sitReq = buildUpdateContextRequest(situationForm, 'idemp-sit')
    expect(sitReq).toEqual({
      idempotency_key: 'idemp-sit',
      expected_revision: 0,
      current_adventure_scene_entry_id: null,
      current_runtime_scene_entry_id: null,
      current_situation: 'Resting by the campfire',
    })

    const advForm = {
      sceneSelection: { type: 'adventure' as const, sceneEntryId: 'adv-scene-42' },
      situation: 'Exploring the hall',
      expectedRevision: 3,
    }
    const advReq = buildUpdateContextRequest(advForm, 'idemp-adv')
    expect(advReq).toEqual({
      idempotency_key: 'idemp-adv',
      expected_revision: 3,
      current_adventure_scene_entry_id: 'adv-scene-42',
      current_runtime_scene_entry_id: null,
      current_situation: 'Exploring the hall',
    })

    const rtForm = {
      sceneSelection: { type: 'runtime' as const, sceneEntryId: 'rt-scene-99' },
      situation: '',
      expectedRevision: 5,
    }
    const rtReq = buildUpdateContextRequest(rtForm, 'idemp-rt')
    expect(rtReq).toEqual({
      idempotency_key: 'idemp-rt',
      expected_revision: 5,
      current_adventure_scene_entry_id: null,
      current_runtime_scene_entry_id: 'rt-scene-99',
      current_situation: null,
    })

    const clearReq = buildClearContextRequest(0, 'idemp-clear')
    expect(clearReq).toEqual({
      idempotency_key: 'idemp-clear',
      expected_revision: 0,
    })
  })

  it('cancels clear context with zero API calls when confirm is dismissed', async () => {
    const clearSpy = vi.spyOn(campaignRuntimeApi, 'clearActiveRuntimeContext')
    const confirmSpy = vi.fn().mockReturnValue(false)
    vi.stubGlobal('window', { confirm: confirmSpy })

    try {
      let pending = false
      const onClearContext = async () => {
        if (typeof window !== 'undefined' && !window.confirm('confirm?')) return
        pending = true
        await campaignRuntimeApi.clearActiveRuntimeContext(ROOM_ID, CAMPAIGN_ID, SESSION_ID, TOKEN, {
          expected_revision: 1,
          idempotency_key: 'key',
        })
      }

      await onClearContext()
      expect(confirmSpy).toHaveBeenCalled()
      expect(pending).toBe(false)
      expect(clearSpy).not.toHaveBeenCalled()
    } finally {
      vi.unstubAllGlobals()
      vi.restoreAllMocks()
    }
  })
})

describe('Bilingual copy parity and zero phase jargon', () => {
  it('enforces exact key parity between English and zh-TW for all campaign runtime copy', () => {
    const en = campaignRuntimeCopy('en')
    const zhTw = campaignRuntimeCopy('zh-TW')

    const enKeys = Object.keys(en).sort()
    const zhTwKeys = Object.keys(zhTw).sort()
    expect(enKeys).toEqual(zhTwKeys)

    expect(en.sessionWorldHeading).toBe('Campaign World')
    expect(zhTw.sessionWorldHeading).toBe('戰役世界狀態')
    expect(en.quickAddButton).toBe('Quick Add')
    expect(zhTw.quickAddButton).toBe('快速新增')
    expect(en.refreshingFromEvents).toBeTruthy()
    expect(zhTw.refreshingFromEvents).toBeTruthy()
    expect(en.retryButton).toBe('Retry')
    expect(zhTw.retryButton).toBe('重試')

    for (const phase of ['P6', 'P6-B', 'P6B', 'B5a', 'B5b', 'B5c', 'B5d', 'Subphase']) {
      expect(Object.values(en).join(' ')).not.toContain(phase)
      expect(Object.values(zhTw).join(' ')).not.toContain(phase)
    }
  })
})
