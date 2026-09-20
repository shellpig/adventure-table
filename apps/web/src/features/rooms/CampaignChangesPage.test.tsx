import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { CampaignRuntimeApiError, type RuntimeWorldEntryDmView } from '../../api/campaignRuntime'
import {
  campaignRuntimeCopy,
  campaignRuntimeErrorMessage,
} from './campaignRuntimeCopy'
import {
  campaignChangesRouteFromPath,
  CampaignChangesView,
  isCampaignChangesEmpty,
} from './CampaignChangesPage'
import { campaignPermissions } from './RoomCampaignPage'

const ROOM_ID = '10000000-0000-4000-8000-000000000001'
const CAMPAIGN_ID = '20000000-0000-4000-8000-000000000001'
const ENTRY_ID = '30000000-0000-4000-8000-000000000001'

describe('CampaignChanges route parsing', () => {
  it('parses Campaign Changes route independently of generic Campaign detail', () => {
    expect(
      campaignChangesRouteFromPath(`/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/changes`),
    ).toEqual({
      roomId: ROOM_ID,
      campaignId: CAMPAIGN_ID,
    })
    expect(
      campaignChangesRouteFromPath(`/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/changes/`),
    ).toEqual({
      roomId: ROOM_ID,
      campaignId: CAMPAIGN_ID,
    })
    expect(
      campaignChangesRouteFromPath(`/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}`),
    ).toBeNull()
    expect(
      campaignChangesRouteFromPath(`/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/lobby`),
    ).toBeNull()
    expect(
      campaignChangesRouteFromPath('/rooms/not-a-uuid/campaigns/not-a-uuid/changes'),
    ).toBeNull()
  })
})

describe('Campaign Runtime bilingual copy & machine error mapping', () => {
  it('enforces exact key parity between English and zh-TW without phase jargon', () => {
    const en = campaignRuntimeCopy('en')
    const zhTw = campaignRuntimeCopy('zh-TW')

    const enKeys = Object.keys(en).sort()
    const zhTwKeys = Object.keys(zhTw).sort()
    expect(enKeys).toEqual(zhTwKeys)

    for (const phase of ['P6', 'P6-B', 'P6B', 'B5a', 'Subphase']) {
      expect(Object.values(en).join(' ')).not.toContain(phase)
      expect(Object.values(zhTw).join(' ')).not.toContain(phase)
    }
  })

  it('maps every B4 stable error code to product-facing text and hides raw exception detail', () => {
    const en = campaignRuntimeCopy('en')
    const zhTw = campaignRuntimeCopy('zh-TW')

    const stableCodes = [
      'campaign_runtime_forbidden',
      'campaign_runtime_not_found',
      'campaign_runtime_archived',
      'campaign_runtime_active_session',
      'campaign_runtime_session_not_active',
      'campaign_runtime_idempotency_conflict',
      'campaign_runtime_revision_conflict',
      'campaign_runtime_override_exists',
      'campaign_runtime_invalid',
    ]

    for (const code of stableCodes) {
      const rawSecretDetail = 'CRITICAL SQL EXCEPTION: thread 0x4f deadlocked on table campaign_world_entries'
      const error = new CampaignRuntimeApiError(409, code, rawSecretDetail)

      const enMsg = campaignRuntimeErrorMessage(error, en)
      const zhTwMsg = campaignRuntimeErrorMessage(error, zhTw)

      expect(enMsg).not.toContain(rawSecretDetail)
      expect(zhTwMsg).not.toContain(rawSecretDetail)
      expect(enMsg).not.toBe(en.requestFailed)
      expect(zhTwMsg).not.toBe(zhTw.requestFailed)
    }

    expect(campaignRuntimeErrorMessage(new Error('raw error'), en)).toBe(en.requestFailed)
  })
})

describe('isCampaignChangesEmpty helper', () => {
  it('returns true only when entries and overrides are empty and context fields are null', () => {
    expect(isCampaignChangesEmpty([], [], null)).toBe(true)
    expect(
      isCampaignChangesEmpty([], [], {
        current_adventure_scene_entry_id: null,
        current_runtime_scene_entry_id: null,
        current_situation: null,
      }),
    ).toBe(true)

    expect(isCampaignChangesEmpty([{ id: '1' }] as never[], [], null)).toBe(false)
    expect(isCampaignChangesEmpty([], [{ id: '1' }] as never[], null)).toBe(false)
    expect(
      isCampaignChangesEmpty([], [], {
        current_adventure_scene_entry_id: 'scene-1',
        current_runtime_scene_entry_id: null,
        current_situation: null,
      }),
    ).toBe(false)
    expect(
      isCampaignChangesEmpty([], [], {
        current_adventure_scene_entry_id: null,
        current_runtime_scene_entry_id: null,
        current_situation: 'Party resting in the grove',
      }),
    ).toBe(false)
  })
})

describe('CampaignChangesView pure presentational component', () => {
  const copy = campaignRuntimeCopy('en')

  it('renders explicit loading state', () => {
    const html = renderToStaticMarkup(
      <CampaignChangesView
        roomId={ROOM_ID}
        campaignId={CAMPAIGN_ID}
        loading={true}
        error={null}
        entries={[]}
        overrides={[]}
        context={null}
        copy={copy}
      />,
    )

    expect(html).toContain(copy.changesTitle)
    expect(html).toContain(copy.loading)
    expect(html).not.toContain(copy.emptyState)
    expect(html).not.toContain(copy.entriesHeading)
  })

  it('renders a single localized fatal state on error without empty/nonempty content', () => {
    const errorMsg = copy.errCampaignRuntimeForbidden
    const html = renderToStaticMarkup(
      <CampaignChangesView
        roomId={ROOM_ID}
        campaignId={CAMPAIGN_ID}
        loading={false}
        error={errorMsg}
        entries={[]}
        overrides={[]}
        context={null}
        copy={copy}
      />,
    )

    expect(html).toContain('error-banner')
    expect(html).toContain(errorMsg)
    expect(html).not.toContain(copy.emptyState)
    expect(html).not.toContain(copy.entriesHeading)
  })

  it('renders empty state when entries, overrides, and context are empty', () => {
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
          current_situation: null,
          revision: 0,
          created_at: null,
          updated_at: null,
        }}
        copy={copy}
      />,
    )

    expect(html).toContain(copy.emptyState)
    expect(html).not.toContain(copy.loading)
    expect(html).not.toContain(copy.entriesHeading)
  })

  it('renders nonempty skeleton with counts, headings, and current situation summary', () => {
    const fakeEntry: RuntimeWorldEntryDmView = {
      id: ENTRY_ID,
      campaign_id: CAMPAIGN_ID,
      kind: 'npc',
      title: 'Elminster',
      body: 'Sage of Shadowdale',
      state: {
        kind: 'npc',
        monster_instance_id: null,
        monster_template_ref: null,
      },
      visibility: 'public',
      dm_notes: null,
      needs_review: false,
      source_adventure_entry_id: null,
      provenance_json: null,
      character_recipient_ids: [],
      revision: 1,
      created_by_actor_kind: 'human',
      created_by_actor_id: null,
      created_at: '2026-09-21T00:00:00Z',
      updated_at: '2026-09-21T00:00:00Z',
      archived_at: null,
    }

    const html = renderToStaticMarkup(
      <CampaignChangesView
        roomId={ROOM_ID}
        campaignId={CAMPAIGN_ID}
        loading={false}
        error={null}
        entries={[fakeEntry]}
        overrides={[]}
        context={{
          campaign_id: CAMPAIGN_ID,
          current_adventure_scene_entry_id: null,
          current_runtime_scene_entry_id: 'scene-99',
          current_situation: 'Party resting by the campfire',
          revision: 1,
          created_at: '2026-09-21T00:00:00Z',
          updated_at: '2026-09-21T00:00:00Z',
        }}
        copy={copy}
      />,
    )

    expect(html).not.toContain(copy.emptyState)
    expect(html).toContain(copy.contextHeading)
    expect(html).toContain('Party resting by the campfire')
    expect(html).toContain('scene-99')
    expect(html).toContain(copy.entriesHeading)
    expect(html).toContain(`${copy.entryCountLabel}: 1`)
    expect(html).toContain(copy.overridesHeading)
    expect(html).toContain(`${copy.overrideCountLabel}: 0`)
    expect(html).toContain(`href="/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}"`)
  })
})

describe('Owner/DM vs member entry gate', () => {
  it('grants Campaign Changes entry access only to Owner and DM roles', () => {
    expect(campaignPermissions('owner').canManageRuntime).toBe(true)
    expect(campaignPermissions('dm').canManageRuntime).toBe(true)
    expect(campaignPermissions('member').canManageRuntime).toBe(false)
    expect(campaignPermissions(null).canManageRuntime).toBe(false)
    expect(campaignPermissions(undefined).canManageRuntime).toBe(false)
  })
})
