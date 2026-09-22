import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { AdventureEntry, AttachedAdventure } from '../../api/adventures'
import * as adventuresApi from '../../api/adventures'
import type {
  CampaignAdventureEntryOverlayView,
  CampaignRuntimeContext,
  RuntimeWorldEntryDmView,
} from '../../api/campaignRuntime'
import * as campaignRuntimeApi from '../../api/campaignRuntime'
import type { RoomAsset } from '../../api/roomAssets'
import * as roomAssetsApi from '../../api/roomAssets'
import { SessionApiError } from '../../api/sessions'
import * as sessionsApi from '../../api/sessions'
import { campaignRuntimeCopy } from './campaignRuntimeCopy'
import {
  buildStageCandidates,
  executeActiveSessionMutation,
  type ActiveSessionRuntimeSnapshot,
  type SessionCampaignRuntimeActions,
  type StageCandidate,
} from './sessionCampaignRuntime'
import { SessionCampaignRuntimePanelView } from './SessionCampaignRuntimePanel'

const ROOM_ID = '10000000-0000-4000-8000-000000000001'
const CAMPAIGN_ID = '20000000-0000-4000-8000-000000000001'
const SESSION_ID = '30000000-0000-4000-8000-000000000001'
const TOKEN = 'test-token'

const sampleAdvImageAsset: RoomAsset = {
  id: 'asset-img-001',
  room_id: ROOM_ID,
  kind: 'image',
  original_filename: 'dungeon-entrance.png',
  mime_type: 'image/png',
  size_bytes: 1024,
  sha256: 'sha-001',
  visibility: 'room',
  created_at: '2026-09-22T00:00:00Z',
}

const sampleAdvAttachmentAsset: RoomAsset = {
  id: 'asset-attach-002',
  room_id: ROOM_ID,
  kind: 'image',
  original_filename: 'dm-handout-notes.png',
  mime_type: 'image/png',
  size_bytes: 512,
  sha256: 'sha-002',
  visibility: 'room',
  created_at: '2026-09-22T00:00:00Z',
}

const sampleRoomImageAsset: RoomAsset = {
  id: 'asset-room-003',
  room_id: ROOM_ID,
  kind: 'image',
  original_filename: 'world-map.jpg',
  mime_type: 'image/jpeg',
  size_bytes: 2048,
  sha256: 'sha-003',
  visibility: 'room',
  created_at: '2026-09-22T00:00:00Z',
}

const sampleRoomDocAsset: RoomAsset = {
  id: 'asset-doc-004',
  room_id: ROOM_ID,
  kind: 'source_document',
  original_filename: 'rules-handout.pdf',
  mime_type: 'application/pdf',
  size_bytes: 4096,
  sha256: 'sha-004',
  visibility: 'room',
  created_at: '2026-09-22T00:00:00Z',
}

const sampleAdvEntry: AdventureEntry = {
  id: 'adv-entry-001',
  adventure_id: 'adv-01',
  parent_entry_id: null,
  kind: 'scene',
  title: 'Crypt Portal',
  body: 'Ancient stone archway',
  data: { kind: 'scene' },
  visibility: 'public',
  sort_order: 1,
  assets: [
    { asset: sampleAdvImageAsset, role: 'image', sort_order: 1 },
    { asset: sampleAdvAttachmentAsset, role: 'attachment', sort_order: 2 },
  ],
  created_at: '2026-09-22T00:00:00Z',
  updated_at: '2026-09-22T00:00:00Z',
}

const sampleRuntimeEntry: RuntimeWorldEntryDmView = {
  id: 'rt-entry-001',
  campaign_id: CAMPAIGN_ID,
  kind: 'scene',
  title: 'Excavated Portal',
  body: 'The rubble has been cleared away.',
  state: { kind: 'scene' },
  visibility: 'public',
  dm_notes: null,
  needs_review: false,
  source_adventure_entry_id: 'adv-entry-001',
  provenance_json: null,
  character_recipient_ids: [],
  revision: 3,
  created_by_actor_kind: 'human',
  created_by_actor_id: 'seat-1',
  created_at: '2026-09-22T00:00:00Z',
  updated_at: '2026-09-22T00:00:00Z',
  archived_at: null,
}

const sampleAttachedAdv: AttachedAdventure = {
  campaign_id: CAMPAIGN_ID,
  adventure_id: 'adv-01',
  sort_order: 1,
  attached_at: '2026-09-22T00:00:00Z',
  name: 'Crypt Adventure',
  summary: null,
  status: 'finalized',
}

const sampleOverlayWithOverride: CampaignAdventureEntryOverlayView = {
  id: 'adv-entry-002',
  adventure_id: 'adv-01',
  parent_entry_id: null,
  kind: 'scene',
  title: 'Inner Vault',
  body: 'Chamber with iron chest',
  data: { kind: 'scene' },
  visibility: 'public',
  sort_order: 2,
  override: {
    id: 'override-001',
    campaign_id: CAMPAIGN_ID,
    adventure_entry_id: 'adv-entry-002',
    state_json: {},
    note: 'Chest has been forced open',
    needs_review: false,
    revision: 2,
    created_at: '2026-09-22T00:00:00Z',
    updated_at: '2026-09-22T00:00:00Z',
  },
}

const sampleContext: CampaignRuntimeContext = {
  campaign_id: CAMPAIGN_ID,
  current_adventure_scene_entry_id: null,
  current_runtime_scene_entry_id: null,
  current_situation: null,
  revision: 1,
  created_at: null,
  updated_at: null,
}

const sampleSnapshot: ActiveSessionRuntimeSnapshot = {
  entries: [sampleRuntimeEntry],
  context: sampleContext,
  attachedAdventures: [sampleAttachedAdv],
  overlays: [sampleOverlayWithOverride],
}

afterEach(() => {
  vi.restoreAllMocks()
})

function fakeActions(
  overrides: Partial<SessionCampaignRuntimeActions> = {},
): SessionCampaignRuntimeActions {
  return {
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
    ...overrides,
  }
}

describe('D5 Step 1: Session DM panel Set-Stage control and needs_review toggles view path', () => {
  it('renders Set-Stage control and needs_review toggles when actions is non-null', () => {
    const copy = campaignRuntimeCopy('en')
    const actions = fakeActions()

    const html = renderToStaticMarkup(
      <SessionCampaignRuntimePanelView
        snapshot={sampleSnapshot}
        characters={[]}
        loading={false}
        error={null}
        refreshStatus={null}
        actions={actions}
        copy={copy}
        onRetry={vi.fn()}
      />,
    )

    expect(html).toContain(copy.stageImageHeading)
    expect(html).toContain(copy.openStagePickerButton)
    expect(html).toContain(copy.sessionReviewHeading)
    expect(html).toContain(copy.markNeedsReviewButton)
  })

  it('renders neither Set-Stage control nor needs_review toggles when actions is null (Player / non-DM view)', () => {
    const copy = campaignRuntimeCopy('en')

    const html = renderToStaticMarkup(
      <SessionCampaignRuntimePanelView
        snapshot={sampleSnapshot}
        characters={[]}
        loading={false}
        error={null}
        refreshStatus={null}
        actions={null}
        copy={copy}
        onRetry={vi.fn()}
      />,
    )

    expect(html).not.toContain(copy.stageImageHeading)
    expect(html).not.toContain(copy.openStagePickerButton)
    expect(html).not.toContain(copy.sessionReviewHeading)
    expect(html).not.toContain(copy.markNeedsReviewButton)
    expect(html).not.toContain(copy.clearNeedsReviewButton)
    expect(html).not.toContain('session-world-stage')
    expect(html).not.toContain('session-world-review')
  })
})

describe('D5 Step 2: Candidate loading and building three groups', () => {
  it('builds three groups and correctly filters out non-image roles and source documents', () => {
    const copy = campaignRuntimeCopy('en')
    const candidates = buildStageCandidates(
      [sampleAttachedAdv],
      { 'adv-01': [sampleAdvEntry] },
      [sampleRuntimeEntry],
      [sampleRoomImageAsset, sampleRoomDocAsset],
      copy.unnamedEntry,
    )

    // Group 1: Adventure entry images
    expect(candidates.adventureCandidates).toHaveLength(1)
    expect(candidates.adventureCandidates[0]).toEqual({
      key: 'candidate-adv-1',
      label: 'Crypt Portal — dungeon-entrance.png',
      group: 'adventure',
      source: {
        kind: 'adventure_entry_asset',
        adventure_id: 'adv-01',
        adventure_entry_id: 'adv-entry-001',
        asset_id: 'asset-img-001',
      },
    })

    // Group 2: Runtime entries linked to adventure entry with image/map
    expect(candidates.runtimeCandidates).toHaveLength(1)
    expect(candidates.runtimeCandidates[0]).toEqual({
      key: 'candidate-rt-2',
      label: 'Excavated Portal — dungeon-entrance.png',
      group: 'runtime',
      source: {
        kind: 'runtime_entry_image',
        runtime_entry_id: 'rt-entry-001',
        adventure_id: 'adv-01',
        asset_id: 'asset-img-001',
      },
    })

    // Group 3: Room images
    expect(candidates.roomCandidates).toHaveLength(1)
    expect(candidates.roomCandidates[0]).toEqual({
      key: 'candidate-room-3',
      label: 'world-map.jpg',
      group: 'room',
      source: {
        kind: 'room_asset',
        asset_id: 'asset-room-003',
      },
    })

    // Exclusions verified:
    // sampleAdvAttachmentAsset ('dm-handout-notes.png', role: 'attachment') is excluded
    // sampleRoomDocAsset ('rules-handout.pdf', kind: 'source_document') is excluded
    const allLabels = candidates.allCandidates.map((c) => c.label)
    expect(allLabels).not.toContain('Crypt Portal — dm-handout-notes.png')
    expect(allLabels).not.toContain('rules-handout.pdf')
    expect(candidates.allCandidates).toHaveLength(3)
  })

  it('renders candidates in grouped select with adventure, runtime, and room optgroups in order', () => {
    const copy = campaignRuntimeCopy('en')
    const candidates = buildStageCandidates(
      [sampleAttachedAdv],
      { 'adv-01': [sampleAdvEntry] },
      [sampleRuntimeEntry],
      [sampleRoomImageAsset],
      copy.unnamedEntry,
    )

    const html = renderToStaticMarkup(
      <SessionCampaignRuntimePanelView
        snapshot={sampleSnapshot}
        characters={[]}
        loading={false}
        error={null}
        refreshStatus={null}
        actions={fakeActions({
          stagePickerOpen: true,
          stageCandidates: candidates.allCandidates,
          stageSelectedKey: candidates.allCandidates[0].key,
          onOpenStagePicker: vi.fn(),
          onCloseStagePicker: vi.fn(),
          onSelectStageCandidate: vi.fn(),
          onSubmitStageImage: vi.fn(),
        })}
        copy={copy}
        onRetry={vi.fn()}
      />,
    )

    expect(html).toContain(`label="${copy.stageImageGroupAdventure}"`)
    expect(html).toContain(`label="${copy.stageImageGroupRuntime}"`)
    expect(html).toContain(`label="${copy.stageImageGroupRoom}"`)
    expect(html).toContain('Crypt Portal — dungeon-entrance.png')
    expect(html).toContain('Excavated Portal — dungeon-entrance.png')
    expect(html).toContain('world-map.jpg')
    expect(html).toContain(copy.submitStageImageButton)
  })

  it('omits submit button and shows localized empty state when no candidates available', () => {
    const copy = campaignRuntimeCopy('en')
    const html = renderToStaticMarkup(
      <SessionCampaignRuntimePanelView
        snapshot={sampleSnapshot}
        characters={[]}
        loading={false}
        error={null}
        refreshStatus={null}
        actions={fakeActions({
          stagePickerOpen: true,
          stageCandidates: [],
          stageSelectedKey: null,
          onOpenStagePicker: vi.fn(),
          onCloseStagePicker: vi.fn(),
          onSelectStageCandidate: vi.fn(),
          onSubmitStageImage: vi.fn(),
        })}
        copy={copy}
        onRetry={vi.fn()}
      />,
    )

    expect(html).toContain(copy.stageImageEmpty)
    expect(html).not.toContain(copy.submitStageImageButton)
    expect(html).toContain(copy.closeStagePickerButton)
  })
})

describe('D5 Step 3: Submit calls getSessionStage then setSessionStageImageSource with canonical revision', () => {
  it('calls getSessionStage then setSessionStageImageSource for adventure_entry_asset', async () => {
    const copy = campaignRuntimeCopy('en')
    const getStageSpy = vi.spyOn(sessionsApi, 'getSessionStage').mockResolvedValue({
      session_id: SESSION_ID,
      revision: 6,
      text: null,
      image_id: null,
      image_media_type: null,
      image_filename: null,
    })
    const setStageSpy = vi.spyOn(sessionsApi, 'setSessionStageImageSource').mockResolvedValue({
      session_id: SESSION_ID,
      revision: 7,
      text: null,
      image_id: 'new-img-id',
      image_media_type: 'image/png',
      image_filename: 'dungeon-entrance.png',
    })

    const source: sessionsApi.StageImageSource = {
      kind: 'adventure_entry_asset',
      adventure_id: 'adv-01',
      adventure_entry_id: 'adv-entry-001',
      asset_id: 'asset-img-001',
    }

    const successFn = vi.fn()
    const errorFn = vi.fn()

    await executeActiveSessionMutation({
      action: async () => {
        const stage = await sessionsApi.getSessionStage(ROOM_ID, CAMPAIGN_ID, SESSION_ID, TOKEN)
        return sessionsApi.setSessionStageImageSource(
          ROOM_ID,
          CAMPAIGN_ID,
          SESSION_ID,
          {
            source,
            expected_revision: stage.revision,
            idempotency_key: 'idem-key-stage-1',
          },
          TOKEN,
        )
      },
      onSuccess: successFn,
      onError: errorFn,
      copy,
    })

    expect(getStageSpy).toHaveBeenCalledWith(ROOM_ID, CAMPAIGN_ID, SESSION_ID, TOKEN)
    expect(setStageSpy).toHaveBeenCalledWith(
      ROOM_ID,
      CAMPAIGN_ID,
      SESSION_ID,
      {
        source,
        expected_revision: 6,
        idempotency_key: 'idem-key-stage-1',
      },
      TOKEN,
    )
    expect(successFn).toHaveBeenCalled()
    expect(errorFn).not.toHaveBeenCalled()
  })

  it('calls getSessionStage then setSessionStageImageSource for runtime_entry_image', async () => {
    const copy = campaignRuntimeCopy('en')
    vi.spyOn(sessionsApi, 'getSessionStage').mockResolvedValue({
      session_id: SESSION_ID,
      revision: 9,
      text: null,
      image_id: null,
      image_media_type: null,
      image_filename: null,
    })
    const setStageSpy = vi.spyOn(sessionsApi, 'setSessionStageImageSource').mockResolvedValue({
      session_id: SESSION_ID,
      revision: 10,
      text: null,
      image_id: 'new-img-id',
      image_media_type: 'image/png',
      image_filename: 'excavated.png',
    })

    const source: sessionsApi.StageImageSource = {
      kind: 'runtime_entry_image',
      runtime_entry_id: 'rt-entry-001',
      adventure_id: 'adv-01',
      asset_id: 'asset-img-001',
    }

    await executeActiveSessionMutation({
      action: async () => {
        const stage = await sessionsApi.getSessionStage(ROOM_ID, CAMPAIGN_ID, SESSION_ID, TOKEN)
        return sessionsApi.setSessionStageImageSource(
          ROOM_ID,
          CAMPAIGN_ID,
          SESSION_ID,
          {
            source,
            expected_revision: stage.revision,
            idempotency_key: 'idem-key-stage-2',
          },
          TOKEN,
        )
      },
      onSuccess: vi.fn(),
      onError: vi.fn(),
      copy,
    })

    expect(setStageSpy).toHaveBeenCalledWith(
      ROOM_ID,
      CAMPAIGN_ID,
      SESSION_ID,
      {
        source,
        expected_revision: 9,
        idempotency_key: 'idem-key-stage-2',
      },
      TOKEN,
    )
  })

  it('calls getSessionStage then setSessionStageImageSource for room_asset', async () => {
    const copy = campaignRuntimeCopy('en')
    vi.spyOn(sessionsApi, 'getSessionStage').mockResolvedValue({
      session_id: SESSION_ID,
      revision: 12,
      text: null,
      image_id: null,
      image_media_type: null,
      image_filename: null,
    })
    const setStageSpy = vi.spyOn(sessionsApi, 'setSessionStageImageSource').mockResolvedValue({
      session_id: SESSION_ID,
      revision: 13,
      text: null,
      image_id: 'new-img-id',
      image_media_type: 'image/jpeg',
      image_filename: 'world-map.jpg',
    })

    const source: sessionsApi.StageImageSource = {
      kind: 'room_asset',
      asset_id: 'asset-room-003',
    }

    await executeActiveSessionMutation({
      action: async () => {
        const stage = await sessionsApi.getSessionStage(ROOM_ID, CAMPAIGN_ID, SESSION_ID, TOKEN)
        return sessionsApi.setSessionStageImageSource(
          ROOM_ID,
          CAMPAIGN_ID,
          SESSION_ID,
          {
            source,
            expected_revision: stage.revision,
            idempotency_key: 'idem-key-stage-3',
          },
          TOKEN,
        )
      },
      onSuccess: vi.fn(),
      onError: vi.fn(),
      copy,
    })

    expect(setStageSpy).toHaveBeenCalledWith(
      ROOM_ID,
      CAMPAIGN_ID,
      SESSION_ID,
      {
        source,
        expected_revision: 12,
        idempotency_key: 'idem-key-stage-3',
      },
      TOKEN,
    )
  })
})

describe('D5 Step 4: 409 revision conflict and 403 authority loss error handling', () => {
  it('surfaces the conflict copy on 409 and sends no second PUT without retry', async () => {
    const copy = campaignRuntimeCopy('en')
    vi.spyOn(sessionsApi, 'getSessionStage').mockResolvedValue({
      session_id: SESSION_ID,
      revision: 3,
      text: null,
      image_id: null,
      image_media_type: null,
      image_filename: null,
    })
    const setStageSpy = vi.spyOn(sessionsApi, 'setSessionStageImageSource').mockRejectedValue(
      new SessionApiError(409, 'stage_revision_conflict', 'Main Stage changed since this editor loaded'),
    )

    const errorFn = vi.fn()
    const successFn = vi.fn()

    const ok = await executeActiveSessionMutation({
      action: async () => {
        const stage = await sessionsApi.getSessionStage(ROOM_ID, CAMPAIGN_ID, SESSION_ID, TOKEN)
        return sessionsApi.setSessionStageImageSource(
          ROOM_ID,
          CAMPAIGN_ID,
          SESSION_ID,
          {
            source: { kind: 'room_asset', asset_id: 'asset-room-003' },
            expected_revision: stage.revision,
            idempotency_key: 'idem-409',
          },
          TOKEN,
        )
      },
      onSuccess: successFn,
      onError: errorFn,
      copy,
    })

    expect(ok).toBe(false)
    expect(setStageSpy).toHaveBeenCalledTimes(1)
    expect(successFn).not.toHaveBeenCalled()
    expect(errorFn).toHaveBeenCalledWith(copy.errCampaignRuntimeRevisionConflict)
  })

  it('triggers authority loss on 403 following the existing authority-loss path', async () => {
    const copy = campaignRuntimeCopy('en')
    vi.spyOn(sessionsApi, 'getSessionStage').mockResolvedValue({
      session_id: SESSION_ID,
      revision: 3,
      text: null,
      image_id: null,
      image_media_type: null,
      image_filename: null,
    })
    vi.spyOn(sessionsApi, 'setSessionStageImageSource').mockRejectedValue(
      new SessionApiError(403, 'table_actor_unauthorized', 'Only the current Session DM can update Main Stage'),
    )

    const authorityLossFn = vi.fn()
    const errorFn = vi.fn()

    const ok = await executeActiveSessionMutation({
      action: async () => {
        const stage = await sessionsApi.getSessionStage(ROOM_ID, CAMPAIGN_ID, SESSION_ID, TOKEN)
        return sessionsApi.setSessionStageImageSource(
          ROOM_ID,
          CAMPAIGN_ID,
          SESSION_ID,
          {
            source: { kind: 'room_asset', asset_id: 'asset-room-003' },
            expected_revision: stage.revision,
            idempotency_key: 'idem-403',
          },
          TOKEN,
        )
      },
      onSuccess: vi.fn(),
      onError: errorFn,
      onAuthorityLoss: authorityLossFn,
      copy,
    })

    expect(ok).toBe(false)
    expect(authorityLossFn).toHaveBeenCalledWith(copy.errCampaignRuntimeForbidden)
    expect(errorFn).not.toHaveBeenCalled()
  })
})

describe('D5 Step 5: needs_review toggle for entry and override with 409 conflict handling', () => {
  it('sends correct expected_revision and needs_review for an entry', async () => {
    const copy = campaignRuntimeCopy('en')
    const updateSpy = vi.spyOn(campaignRuntimeApi, 'updateActiveRuntimeEntry').mockResolvedValue({
      ...sampleRuntimeEntry,
      needs_review: true,
      revision: 4,
    })

    await executeActiveSessionMutation({
      action: () =>
        campaignRuntimeApi.updateActiveRuntimeEntry(
          ROOM_ID,
          CAMPAIGN_ID,
          SESSION_ID,
          sampleRuntimeEntry.id,
          TOKEN,
          {
            idempotency_key: 'idem-review-1',
            expected_revision: sampleRuntimeEntry.revision,
            needs_review: !sampleRuntimeEntry.needs_review,
          },
        ),
      onSuccess: vi.fn(),
      onError: vi.fn(),
      copy,
    })

    expect(updateSpy).toHaveBeenCalledWith(
      ROOM_ID,
      CAMPAIGN_ID,
      SESSION_ID,
      sampleRuntimeEntry.id,
      TOKEN,
      {
        idempotency_key: 'idem-review-1',
        expected_revision: 3,
        needs_review: true,
      },
    )
  })

  it('sends correct expected_override_id, expected_revision and needs_review for an override', async () => {
    const copy = campaignRuntimeCopy('en')
    const updateSpy = vi.spyOn(campaignRuntimeApi, 'updateActiveOverride').mockResolvedValue({
      ...sampleOverlayWithOverride.override!,
      needs_review: true,
      revision: 3,
    })

    const overlay = sampleOverlayWithOverride
    await executeActiveSessionMutation({
      action: () =>
        campaignRuntimeApi.updateActiveOverride(
          ROOM_ID,
          CAMPAIGN_ID,
          SESSION_ID,
          overlay.id,
          TOKEN,
          {
            idempotency_key: 'idem-review-2',
            expected_override_id: overlay.override!.id,
            expected_revision: overlay.override!.revision,
            needs_review: !overlay.override!.needs_review,
          },
        ),
      onSuccess: vi.fn(),
      onError: vi.fn(),
      copy,
    })

    expect(updateSpy).toHaveBeenCalledWith(
      ROOM_ID,
      CAMPAIGN_ID,
      SESSION_ID,
      'adv-entry-002',
      TOKEN,
      {
        idempotency_key: 'idem-review-2',
        expected_override_id: 'override-001',
        expected_revision: 2,
        needs_review: true,
      },
    )
  })

  it('surfaces conflict copy on 409 when toggling needs_review', async () => {
    const copy = campaignRuntimeCopy('en')
    vi.spyOn(campaignRuntimeApi, 'updateActiveRuntimeEntry').mockRejectedValue(
      new campaignRuntimeApi.CampaignRuntimeApiError(
        409,
        'campaign_runtime_revision_conflict',
        'Runtime world state was modified by another action',
      ),
    )

    const errorFn = vi.fn()
    await executeActiveSessionMutation({
      action: () =>
        campaignRuntimeApi.updateActiveRuntimeEntry(
          ROOM_ID,
          CAMPAIGN_ID,
          SESSION_ID,
          sampleRuntimeEntry.id,
          TOKEN,
          {
            idempotency_key: 'idem-review-3',
            expected_revision: sampleRuntimeEntry.revision,
            needs_review: !sampleRuntimeEntry.needs_review,
          },
        ),
      onSuccess: vi.fn(),
      onError: errorFn,
      copy,
    })

    expect(errorFn).toHaveBeenCalledWith(copy.errCampaignRuntimeRevisionConflict)
  })
})

describe('D5 Step 6: Rendered text never contains asset id or storage key strings', () => {
  it('does not leak internal asset ids or storage keys in visible panel markup', () => {
    const copy = campaignRuntimeCopy('en')
    const secretAssetId = 'secret-raw-asset-id-99887766'
    const secretStorageKey = 'storage-key-secret-never-expose'

    const customAsset: RoomAsset = {
      ...sampleAdvImageAsset,
      id: secretAssetId,
      original_filename: 'visible-name.png',
    }

    const customAdvEntry: AdventureEntry = {
      ...sampleAdvEntry,
      title: 'Secret Cave',
      assets: [{ asset: customAsset, role: 'image', sort_order: 1 }],
    }

    const candidates = buildStageCandidates(
      [sampleAttachedAdv],
      { 'adv-01': [customAdvEntry] },
      [],
      [],
      copy.unnamedEntry,
    )

    const html = renderToStaticMarkup(
      <SessionCampaignRuntimePanelView
        snapshot={sampleSnapshot}
        characters={[]}
        loading={false}
        error={null}
        refreshStatus={null}
        actions={fakeActions({
          stagePickerOpen: true,
          stageCandidates: candidates.allCandidates,
          stageSelectedKey: candidates.allCandidates[0]?.key ?? null,
          onOpenStagePicker: vi.fn(),
          onCloseStagePicker: vi.fn(),
          onSelectStageCandidate: vi.fn(),
          onSubmitStageImage: vi.fn(),
        })}
        copy={copy}
        onRetry={vi.fn()}
      />,
    )

    expect(html).toContain('Secret Cave — visible-name.png')
    // Asset ID and storage key are never in visible text
    expect(html).not.toContain(secretAssetId)
    expect(html).not.toContain(secretStorageKey)
  })
})

describe('D5 Step 7: Locale parity for new D5 copy keys', () => {
  it('exposes all new keys in both en and zh-TW with distinct non-empty values and zero phase jargon', () => {
    const en = campaignRuntimeCopy('en')
    const zhTw = campaignRuntimeCopy('zh-TW')

    const d5Keys: (keyof typeof en)[] = [
      'stageImageHeading',
      'openStagePickerButton',
      'closeStagePickerButton',
      'submitStageImageButton',
      'stageImageSelectLabel',
      'stageImageAriaSelect',
      'stageImageGroupAdventure',
      'stageImageGroupRuntime',
      'stageImageGroupRoom',
      'stageImageEmpty',
      'stageImageSuccess',
      'sessionReviewHeading',
      'sessionReviewEmpty',
      'markNeedsReviewButton',
      'clearNeedsReviewButton',
    ]

    for (const key of d5Keys) {
      expect(en[key]).toBeTruthy()
      expect(zhTw[key]).toBeTruthy()
      expect(typeof en[key]).toBe('string')
      expect(typeof zhTw[key]).toBe('string')
      expect(en[key].length).toBeGreaterThan(0)
      expect(zhTw[key].length).toBeGreaterThan(0)
      expect(en[key]).not.toEqual(zhTw[key])
    }

    const forbiddenPhaseTerms = [
      'P6',
      'P6-B',
      'P6B',
      'P6-D',
      'P6D',
      'B5a',
      'B5b',
      'B5c',
      'B5d',
      'D5',
      'Subphase',
    ]

    for (const term of forbiddenPhaseTerms) {
      for (const key of d5Keys) {
        expect(en[key]).not.toContain(term)
        expect(zhTw[key]).not.toContain(term)
      }
    }
  })
})
