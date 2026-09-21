import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { RoomCharacterSummary } from '../../api/campaigns'
import { CampaignRuntimeApiError, type RuntimeWorldEntryDmView } from '../../api/campaignRuntime'
import {
  campaignRuntimeCopy,
  campaignRuntimeErrorMessage,
} from './campaignRuntimeCopy'
import {
  campaignChangesRouteFromPath,
  CampaignChangesView,
  isCampaignChangesEmpty,
  type CampaignChangesManagement,
} from './CampaignChangesPage'
import {
  RuntimeEntryCardView,
  RuntimeEntryFormView,
} from './CampaignRuntimeEntries'
import {
  buildCreateEntryRequest,
  buildUpdateEntryRequest,
  createInitialEntryFormState,
  EDITABLE_RUNTIME_ENTRY_KINDS,
  entryToFormState,
  executeRuntimeMutation,
  handleArchiveRuntimeEntry,
  isEditableRuntimeEntryKind,
  loadCampaignChanges,
  onFormKindChange,
  onFormVisibilityChange,
  validateAndParseOtherData,
  validateAndParseProvenanceJson,
  validateEntryMinima,
} from './campaignRuntimeForm'
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

    for (const phase of ['P6', 'P6-B', 'P6B', 'B5a', 'B5b', 'Subphase']) {
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
    expect(isCampaignChangesEmpty([], [], null, [])).toBe(true)
    expect(
      isCampaignChangesEmpty([], [], {
        current_adventure_scene_entry_id: null,
        current_runtime_scene_entry_id: null,
        current_situation: null,
      }, []),
    ).toBe(true)

    expect(isCampaignChangesEmpty([{ id: '1' }] as never[], [], null, [])).toBe(false)
    expect(isCampaignChangesEmpty([], [{ id: '1' }] as never[], null, [])).toBe(false)
    expect(
      isCampaignChangesEmpty([], [], {
        current_adventure_scene_entry_id: 'scene-1',
        current_runtime_scene_entry_id: null,
        current_situation: null,
      }, []),
    ).toBe(false)
    expect(
      isCampaignChangesEmpty([], [], {
        current_adventure_scene_entry_id: null,
        current_runtime_scene_entry_id: null,
        current_situation: 'Party resting in the grove',
      }, []),
    ).toBe(false)
    expect(isCampaignChangesEmpty([], [], null, [{ id: 'adventure-1' }])).toBe(false)
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
        attachedAdventures={[]}
        overlays={[]}
        management={null}
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
        attachedAdventures={[]}
        overlays={[]}
        management={null}
        copy={copy}
      />,
    )

    expect(html).toContain('error-banner')
    expect(html).toContain(errorMsg)
    expect(html).not.toContain(copy.emptyState)
    expect(html).not.toContain(copy.entriesHeading)
  })

  it('renders empty state informational notice and keeps sections accessible when entries, overrides, and context are empty', () => {
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
        attachedAdventures={[]}
        overlays={[]}
        management={null}
        copy={copy}
      />,
    )

    expect(html).toContain(copy.emptyState)
    expect(html).not.toContain(copy.loading)
    expect(html).toContain(copy.entriesHeading)
    expect(html).toContain(copy.contextHeading)
    expect(html).toContain(copy.reviewQueueHeading)
    expect(html).toContain(copy.overridesHeading)
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
        attachedAdventures={[]}
        overlays={[]}
        management={null}
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

describe('H.1 Quick-add minima validation and serialization', () => {
  it('validates NPC requires nonblank title or name', () => {
    expect(validateEntryMinima('npc', 'Goblin Scout', '')).toBeNull()
    expect(validateEntryMinima('npc', '', '')).toBe('errNpcTitleRequired')
    expect(validateEntryMinima('npc', '   ', '')).toBe('errNpcTitleRequired')

    const form = createInitialEntryFormState('npc')
    form.title = 'Goblin Scout'
    const res = buildCreateEntryRequest(form, 'key-1')
    expect(res.ok).toBe(true)
    if (res.ok) {
      expect(res.value.title).toBe('Goblin Scout')
      expect(res.value.body).toBeNull()
    }
  })

  it('validates Fact requires nonblank body text', () => {
    expect(validateEntryMinima('fact', '', 'The gate is locked at dusk.')).toBeNull()
    expect(validateEntryMinima('fact', 'Gate', '')).toBe('errFactBodyRequired')
    expect(validateEntryMinima('fact', '', '   ')).toBe('errFactBodyRequired')

    const form = createInitialEntryFormState('fact')
    form.body = 'The gate is locked at dusk.'
    const res = buildCreateEntryRequest(form, 'key-2')
    expect(res.ok).toBe(true)
    if (res.ok) {
      expect(res.value.title).toBeNull()
      expect(res.value.body).toBe('The gate is locked at dusk.')
    }
  })

  it('validates Scene requires nonblank title OR body', () => {
    expect(validateEntryMinima('scene', 'Ancient Crypt', '')).toBeNull()
    expect(validateEntryMinima('scene', '', 'Damp air and cobwebs.')).toBeNull()
    expect(validateEntryMinima('scene', 'Crypt', 'Damp air')).toBeNull()
    expect(validateEntryMinima('scene', '', '')).toBe('errSceneRequired')
    expect(validateEntryMinima('scene', '   ', '   ')).toBe('errSceneRequired')

    const form = createInitialEntryFormState('scene')
    form.title = 'Ancient Crypt'
    const res = buildCreateEntryRequest(form, 'key-3')
    expect(res.ok).toBe(true)
    if (res.ok) {
      expect(res.value.title).toBe('Ancient Crypt')
      expect(res.value.body).toBeNull()
    }
  })

  it('allows Quest, Item, Secret, Other to have blank title and body', () => {
    for (const kind of ['quest', 'item', 'secret', 'other'] as const) {
      expect(validateEntryMinima(kind, '', '')).toBeNull()
      const form = createInitialEntryFormState(kind)
      const res = buildCreateEntryRequest(form, `key-${kind}`)
      expect(res.ok).toBe(true)
      if (res.ok) {
        expect(res.value.title).toBeNull()
        expect(res.value.body).toBeNull()
      }
    }
  })

  it('defaults secret to dm_only when selected in create mode without overriding explicit selection', () => {
    const initial = createInitialEntryFormState('scene')
    expect(initial.visibility).toBe('public')

    const switchedToSecret = onFormKindChange(initial, 'secret')
    expect(switchedToSecret.visibility).toBe('dm_only')

    const explicitlyCharacter = onFormVisibilityChange(switchedToSecret, 'character')
    expect(explicitlyCharacter.visibility).toBe('character')

    const switchedAgain = onFormKindChange(explicitlyCharacter, 'secret')
    expect(switchedAgain.visibility).toBe('character')
  })
})

describe('H.2 Exact typed state and rejection cases', () => {
  it('handles NPC monster references and trims blanks to null', () => {
    const form = createInitialEntryFormState('npc')
    form.title = 'Gundren'
    form.npcMonsterInstanceId = '40000000-0000-4000-8000-000000000001'
    form.npcMonsterTemplateRef = '  srd:dwarf-noble  '

    const res = buildCreateEntryRequest(form, 'key-npc')
    expect(res.ok).toBe(true)
    if (res.ok) {
      expect(res.value.state).toEqual({
        kind: 'npc',
        monster_instance_id: '40000000-0000-4000-8000-000000000001',
        monster_template_ref: 'srd:dwarf-noble',
      })
    }

    form.npcMonsterInstanceId = '   '
    form.npcMonsterTemplateRef = '   '
    const resBlank = buildCreateEntryRequest(form, 'key-npc-2')
    expect(resBlank.ok).toBe(true)
    if (resBlank.ok) {
      expect(resBlank.value.state).toEqual({
        kind: 'npc',
        monster_instance_id: null,
        monster_template_ref: null,
      })
    }
  })

  it('handles Item holder for every holder kind including required target validation', () => {
    const form = createInitialEntryFormState('item')
    form.title = 'Moonblade'

    // None
    form.itemHolderKind = ''
    const r1 = buildCreateEntryRequest(form, 'k1')
    expect(r1.ok).toBe(true)
    if (r1.ok) {
      expect(r1.value.state).toEqual({
        kind: 'item',
        holder_ref: null,
      })
    }

    // Party (no target)
    form.itemHolderKind = 'party'
    const r2 = buildCreateEntryRequest(form, 'k2')
    expect(r2.ok).toBe(true)
    if (r2.ok) {
      expect(r2.value.state).toEqual({
        kind: 'item',
        holder_ref: { kind: 'party', target_id: null },
      })
    }

    // Unknown (no target)
    form.itemHolderKind = 'unknown'
    const r3 = buildCreateEntryRequest(form, 'k3')
    expect(r3.ok).toBe(true)
    if (r3.ok) {
      expect(r3.value.state).toEqual({
        kind: 'item',
        holder_ref: { kind: 'unknown', target_id: null },
      })
    }

    // Scene with target
    form.itemHolderKind = 'scene'
    form.itemHolderTargetId = 'scene-42'
    const r4 = buildCreateEntryRequest(form, 'k4')
    expect(r4.ok).toBe(true)
    if (r4.ok) {
      expect(r4.value.state).toEqual({
        kind: 'item',
        holder_ref: { kind: 'scene', target_id: 'scene-42' },
      })
    }

    // Scene without target
    form.itemHolderTargetId = '   '
    const r5 = buildCreateEntryRequest(form, 'k5')
    expect(r5.ok).toBe(false)
    if (!r5.ok) {
      expect(r5.errorKey).toBe('errItemHolderTargetRequired')
    }

    // NPC with target
    form.itemHolderKind = 'npc'
    form.itemHolderTargetId = 'npc-88'
    const r6 = buildCreateEntryRequest(form, 'k6')
    expect(r6.ok).toBe(true)
    if (r6.ok) {
      expect(r6.value.state).toEqual({
        kind: 'item',
        holder_ref: { kind: 'npc', target_id: 'npc-88' },
      })
    }

    // NPC without target
    form.itemHolderTargetId = ''
    const r7 = buildCreateEntryRequest(form, 'k7')
    expect(r7.ok).toBe(false)
    if (!r7.ok) {
      expect(r7.errorKey).toBe('errItemHolderTargetRequired')
    }

    // Character with target
    form.itemHolderKind = 'character'
    form.itemHolderTargetId = 'char-99'
    const r8 = buildCreateEntryRequest(form, 'k8')
    expect(r8.ok).toBe(true)
    if (r8.ok) {
      expect(r8.value.state).toEqual({
        kind: 'item',
        holder_ref: { kind: 'character', target_id: 'char-99' },
      })
    }

    // Character without target
    form.itemHolderTargetId = ''
    const r9 = buildCreateEntryRequest(form, 'k9')
    expect(r9.ok).toBe(false)
    if (!r9.ok) {
      expect(r9.errorKey).toBe('errItemHolderTargetRequired')
    }
  })

  it('validates Other scalar data and rejects arrays, null, nested objects, and invalid JSON', () => {
    const validRes = validateAndParseOtherData('{"key": "val", "num": 12, "active": true}')
    expect(validRes.ok).toBe(true)
    if (validRes.ok) {
      expect(validRes.value).toEqual({ key: 'val', num: 12, active: true })
    }

    const emptyRes = validateAndParseOtherData('')
    expect(emptyRes.ok).toBe(true)
    if (emptyRes.ok) {
      expect(emptyRes.value).toEqual({})
    }

    // Invalid JSON
    const brokenRes = validateAndParseOtherData('{broken: true}')
    expect(brokenRes.ok).toBe(false)
    if (!brokenRes.ok) {
      expect(brokenRes.errorKey).toBe('errOtherDataInvalidJson')
    }

    // Non-object (array)
    const arrRes = validateAndParseOtherData('[1, 2, 3]')
    expect(arrRes.ok).toBe(false)
    if (!arrRes.ok) {
      expect(arrRes.errorKey).toBe('errOtherDataInvalidJson')
    }

    // Non-scalar: nested object
    const nestedRes = validateAndParseOtherData('{"nested": {"a": 1}}')
    expect(nestedRes.ok).toBe(false)
    if (!nestedRes.ok) {
      expect(nestedRes.errorKey).toBe('errOtherDataScalarOnly')
    }

    // Non-scalar: array value
    const arrValRes = validateAndParseOtherData('{"list": ["a", "b"]}')
    expect(arrValRes.ok).toBe(false)
    if (!arrValRes.ok) {
      expect(arrValRes.errorKey).toBe('errOtherDataScalarOnly')
    }

    // Non-scalar: null value
    const nullValRes = validateAndParseOtherData('{"nullField": null}')
    expect(nullValRes.ok).toBe(false)
    if (!nullValRes.ok) {
      expect(nullValRes.errorKey).toBe('errOtherDataScalarOnly')
    }
  })
})

describe('H.3 Visibility and character recipient invariant rules', () => {
  it('clears recipients when public or dm_only, even if form held selections', () => {
    const form = createInitialEntryFormState('scene')
    form.title = 'Marketplace'
    form.characterRecipientIds = ['char-1', 'char-2']

    form.visibility = 'public'
    const pubRes = buildCreateEntryRequest(form, 'k-pub')
    expect(pubRes.ok).toBe(true)
    if (pubRes.ok) {
      expect(pubRes.value.character_recipient_ids).toEqual([])
    }

    form.visibility = 'dm_only'
    const dmRes = buildCreateEntryRequest(form, 'k-dm')
    expect(dmRes.ok).toBe(true)
    if (dmRes.ok) {
      expect(dmRes.value.character_recipient_ids).toEqual([])
    }

    const stateCleared = onFormVisibilityChange(form, 'public')
    expect(stateCleared.characterRecipientIds).toEqual([])
  })

  it('requires at least one recipient for character visibility and serializes exact deduplicated ids', () => {
    const form = createInitialEntryFormState('secret')
    form.title = 'Traitor in the Council'
    form.visibility = 'character'
    form.characterRecipientIds = []

    const emptyRes = buildCreateEntryRequest(form, 'k-char-empty')
    expect(emptyRes.ok).toBe(false)
    if (!emptyRes.ok) {
      expect(emptyRes.errorKey).toBe('errCharacterRecipientsRequired')
    }

    form.characterRecipientIds = ['char-1', 'char-2', 'char-1']
    const validRes = buildCreateEntryRequest(form, 'k-char-valid')
    expect(validRes.ok).toBe(true)
    if (validRes.ok) {
      expect(validRes.value.character_recipient_ids).toEqual(['char-1', 'char-2'])
    }
  })
})

describe('H.4 Update payload preserves invariants and non-exposed fields', () => {
  const existingEntry: RuntimeWorldEntryDmView = {
    id: 'entry-555',
    campaign_id: CAMPAIGN_ID,
    kind: 'npc',
    title: 'Old Title',
    body: 'Old Body',
    state: { kind: 'npc', monster_instance_id: null, monster_template_ref: null },
    visibility: 'public',
    dm_notes: 'Old Notes',
    needs_review: false,
    source_adventure_entry_id: 'adv-entry-999',
    provenance_json: { orig: 'draft' },
    character_recipient_ids: [],
    revision: 4,
    created_by_actor_kind: 'human',
    created_by_actor_id: null,
    created_at: '2026-09-20T00:00:00Z',
    updated_at: '2026-09-20T00:00:00Z',
    archived_at: null,
  }

  it('serializes expected_revision, omits kind and source_adventure_entry_id, trims blanks, and handles provenance', () => {
    const form = entryToFormState(existingEntry)
    expect(form).not.toBeNull()
    if (!form) return

    expect(form.mode).toBe('edit')
    expect(form.expectedRevision).toBe(4)
    expect(form.sourceAdventureEntryId).toBe('adv-entry-999')

    form.title = 'Sildar Hallwinter'
    form.body = 'Updated description'
    form.dmNotes = '   '
    form.needsReview = true
    form.provenanceJson = '{"editor": "DM"}'

    const res = buildUpdateEntryRequest(form, 'update-key-1')
    expect(res.ok).toBe(true)
    if (res.ok) {
      const req = res.value
      expect(req.expected_revision).toBe(4)
      expect('kind' in req).toBe(false)
      expect('source_adventure_entry_id' in req).toBe(false)
      expect(req.title).toBe('Sildar Hallwinter')
      expect(req.body).toBe('Updated description')
      expect(req.dm_notes).toBeNull()
      expect(req.needs_review).toBe(true)
      expect(req.provenance_json).toEqual({ editor: 'DM' })
    }
  })

  it('rejects invalid provenance JSON on update', () => {
    const form = entryToFormState(existingEntry)
    expect(form).not.toBeNull()
    if (!form) return

    form.title = 'Valid Title'
    form.provenanceJson = '{invalid json'
    const res = buildUpdateEntryRequest(form, 'update-key-2')
    expect(res.ok).toBe(false)
    if (!res.ok) {
      expect(res.errorKey).toBe('errProvenanceInvalidJson')
    }
  })
})

describe('H.5 Archive wiring inputs and confirmation seam', () => {
  const copy = campaignRuntimeCopy('en')

  it('aborts archive and invokes onCancel without setting pending, start, api, or reload', async () => {
    const archiveFn = vi.fn()
    const reloadFn = vi.fn()
    const errorFn = vi.fn()
    const startFn = vi.fn()
    const cancelFn = vi.fn()
    const committedReloadErrorFn = vi.fn()

    const result = await handleArchiveRuntimeEntry({
      roomId: ROOM_ID,
      campaignId: CAMPAIGN_ID,
      entryId: ENTRY_ID,
      revision: 3,
      token: 'tok-123',
      idempotencyKey: 'arch-key-1',
      confirmFn: () => false,
      onStart: startFn,
      onCancel: cancelFn,
      archiveFn,
      onReload: reloadFn,
      onError: errorFn,
      onCommittedReloadError: committedReloadErrorFn,
      copy,
    })

    expect(result).toBe(false)
    expect(startFn).not.toHaveBeenCalled()
    expect(cancelFn).toHaveBeenCalledTimes(1)
    expect(archiveFn).not.toHaveBeenCalled()
    expect(reloadFn).not.toHaveBeenCalled()
    expect(errorFn).not.toHaveBeenCalled()
    expect(committedReloadErrorFn).not.toHaveBeenCalled()
  })

  it('calls archive API with expected_revision and fresh idempotency key when confirmed', async () => {
    const archiveFn = vi.fn().mockResolvedValue({} as RuntimeWorldEntryDmView)
    const reloadFn = vi.fn().mockResolvedValue(undefined)
    const successFn = vi.fn()
    const errorFn = vi.fn()
    const startFn = vi.fn()
    const committedReloadErrorFn = vi.fn()

    const result = await handleArchiveRuntimeEntry({
      roomId: ROOM_ID,
      campaignId: CAMPAIGN_ID,
      entryId: ENTRY_ID,
      revision: 7,
      token: 'tok-123',
      idempotencyKey: 'arch-key-2',
      confirmFn: () => true,
      onStart: startFn,
      archiveFn,
      onReload: reloadFn,
      onSuccess: successFn,
      onError: errorFn,
      onCommittedReloadError: committedReloadErrorFn,
      copy,
    })

    expect(result).toBe(true)
    expect(startFn).toHaveBeenCalledTimes(1)
    expect(archiveFn).toHaveBeenCalledWith(ROOM_ID, CAMPAIGN_ID, ENTRY_ID, 'tok-123', {
      expected_revision: 7,
      idempotency_key: 'arch-key-2',
    })
    expect(reloadFn).toHaveBeenCalled()
    expect(successFn).toHaveBeenCalled()
    expect(errorFn).not.toHaveBeenCalled()
    expect(committedReloadErrorFn).not.toHaveBeenCalled()
  })
})

describe('H.6 Revision-conflict reload flow and error presentation', () => {
  const copy = campaignRuntimeCopy('en')

  it('reloads latest entries BEFORE presenting localized revision conflict message', async () => {
    const callOrder: string[] = []
    const conflictError = new CampaignRuntimeApiError(
      409,
      'campaign_runtime_revision_conflict',
      'version mismatch',
    )

    const action = vi.fn().mockImplementation(() => {
      callOrder.push('action')
      throw conflictError
    })
    const onReload = vi.fn().mockImplementation(async () => {
      callOrder.push('reload')
    })
    const onError = vi.fn().mockImplementation((msg: string) => {
      callOrder.push(`error:${msg}`)
    })
    const onCommittedReloadError = vi.fn().mockImplementation((msg: string) => {
      callOrder.push(`committed-reload-error:${msg}`)
    })

    const ok = await executeRuntimeMutation({
      action,
      onReload,
      onError,
      onCommittedReloadError,
      copy,
    })

    expect(ok).toBe(false)
    expect(callOrder).toEqual([
      'action',
      'reload',
      `error:${copy.errCampaignRuntimeRevisionConflict}`,
    ])
    expect(onCommittedReloadError).not.toHaveBeenCalled()
  })

  it('surfaces reload error when onReload fails during revision conflict and does not claim conflict was refreshed', async () => {
    const callOrder: string[] = []
    const conflictError = new CampaignRuntimeApiError(
      409,
      'campaign_runtime_revision_conflict',
      'version mismatch',
    )
    const reloadFailure = new CampaignRuntimeApiError(
      403,
      'campaign_runtime_forbidden',
      'forbidden during reload',
    )

    const action = vi.fn().mockImplementation(() => {
      callOrder.push('action')
      throw conflictError
    })
    const onReload = vi.fn().mockImplementation(async () => {
      callOrder.push('reload')
      throw reloadFailure
    })
    const onError = vi.fn().mockImplementation((msg: string) => {
      callOrder.push(`error:${msg}`)
    })
    const onCommittedReloadError = vi.fn().mockImplementation((msg: string) => {
      callOrder.push(`committed-reload-error:${msg}`)
    })

    const ok = await executeRuntimeMutation({
      action,
      onReload,
      onError,
      onCommittedReloadError,
      copy,
    })

    expect(ok).toBe(false)
    expect(callOrder).toEqual([
      'action',
      'reload',
      `error:${copy.errCampaignRuntimeForbidden}`,
    ])
    expect(onCommittedReloadError).not.toHaveBeenCalled()
  })

  it('does not reload on non-conflict errors and presents corresponding error copy', async () => {
    const forbiddenError = new CampaignRuntimeApiError(
      403,
      'campaign_runtime_forbidden',
      'not allowed',
    )

    const action = vi.fn().mockRejectedValue(forbiddenError)
    const onReload = vi.fn().mockResolvedValue(undefined)
    const onError = vi.fn()
    const onCommittedReloadError = vi.fn()

    const ok = await executeRuntimeMutation({
      action,
      onReload,
      onError,
      onCommittedReloadError,
      copy,
    })

    expect(ok).toBe(false)
    expect(onReload).not.toHaveBeenCalled()
    expect(onError).toHaveBeenCalledWith(copy.errCampaignRuntimeForbidden)
    expect(onCommittedReloadError).not.toHaveBeenCalled()
  })

  it('invokes onCommittedReloadError when action succeeds but reload fails, and does not invoke onError or onSuccess', async () => {
    const callOrder: string[] = []
    const reloadFailure = new CampaignRuntimeApiError(
      500,
      'campaign_runtime_request_failed',
      'reload failed',
    )

    const action = vi.fn().mockImplementation(async () => {
      callOrder.push('action')
      return { id: 'created-1' }
    })
    const onReload = vi.fn().mockImplementation(async () => {
      callOrder.push('reload')
      throw reloadFailure
    })
    const onSuccess = vi.fn().mockImplementation(() => {
      callOrder.push('success')
    })
    const onError = vi.fn().mockImplementation((msg: string) => {
      callOrder.push(`error:${msg}`)
    })
    const onCommittedReloadError = vi.fn().mockImplementation((msg: string) => {
      callOrder.push(`committed-reload-error:${msg}`)
    })

    const ok = await executeRuntimeMutation({
      action,
      onReload,
      onSuccess,
      onError,
      onCommittedReloadError,
      copy,
    })

    expect(ok).toBe(false)
    expect(callOrder).toEqual([
      'action',
      'reload',
      `committed-reload-error:${copy.requestFailed}`,
    ])
    expect(onError).not.toHaveBeenCalled()
    expect(onSuccess).not.toHaveBeenCalled()
  })
})

describe('Hazard display and edit restriction', () => {
  const hazardEntry: RuntimeWorldEntryDmView = {
    id: 'hazard-1',
    campaign_id: CAMPAIGN_ID,
    kind: 'hazard',
    title: 'Poison Dart Trap',
    body: 'Pressure plate triggers darts from wall.',
    state: { kind: 'hazard' },
    visibility: 'dm_only',
    dm_notes: 'DC 14 Investigation to discover.',
    needs_review: false,
    source_adventure_entry_id: null,
    provenance_json: null,
    character_recipient_ids: [],
    revision: 1,
    created_by_actor_kind: 'human',
    created_by_actor_id: null,
    created_at: '2026-09-20T00:00:00Z',
    updated_at: '2026-09-20T00:00:00Z',
    archived_at: null,
  }

  it('renders hazard card with archive action but omits edit button', () => {
    const onEdit = vi.fn()
    const onArchive = vi.fn()
    const copy = campaignRuntimeCopy('en')

    const html = renderToStaticMarkup(
      <RuntimeEntryCardView
        entry={hazardEntry}
        entries={[hazardEntry]}
        characters={[]}
        actions={{ disabled: false, onEdit, onArchive }}
        copy={copy}
      />,
    )

    expect(html).toContain('Poison Dart Trap')
    expect(html).toContain(copy.kindHazard)
    expect(html).toContain(copy.archiveEntryButton)
    expect(html).not.toContain(copy.editEntryButton)
  })

  it('rejects hazard from entryToFormState returning null', () => {
    expect(entryToFormState(hazardEntry)).toBeNull()
  })

  it('isEditableRuntimeEntryKind returns false for hazard', () => {
    expect(isEditableRuntimeEntryKind('hazard')).toBe(false)
  })

  it('renders committed-warning and preserves entries list while omitting form after committed+reload-failed', () => {
    for (const loc of ['en', 'zh-TW'] as const) {
      const copy = campaignRuntimeCopy(loc)
      const management = createTestManagement({
        committedWarning: copy.committedReloadWarning,
      })

      const html = renderToStaticMarkup(
        <CampaignChangesView
          roomId={ROOM_ID}
          campaignId={CAMPAIGN_ID}
          loading={false}
          error={null}
          entries={[hazardEntry]}
          overrides={[]}
          context={null}
          attachedAdventures={[]}
          overlays={[]}
          management={management}
          copy={copy}
        />,
      )

      expect(html).toContain(copy.committedReloadWarning)
      expect(html).toContain('notice-banner')
      expect(html).toContain('Poison Dart Trap')
      expect(html).not.toContain('<form')
      expect(html).not.toContain(`<h3>${copy.formTitleCreate}</h3>`)
      expect(html).not.toContain(`<h3>${copy.formTitleEdit}</h3>`)
      expect(html).not.toContain(copy.submitCreate)
      expect(html).not.toContain(copy.submitUpdate)
    }
  })
})

describe('H.7 Static rendering in en and zh-TW without leaked placeholders and with typed-state display', () => {
  const charA: RoomCharacterSummary = {
    id: 'char-101',
    name: 'Alandra',
    level: 3,
    class_summary: 'Wizard',
    version_no: 1,
  }
  const charB: RoomCharacterSummary = {
    id: 'char-102',
    name: 'Brog',
    level: 3,
    class_summary: 'Barbarian',
    version_no: 1,
  }

  const sampleEntry: RuntimeWorldEntryDmView = {
    id: ENTRY_ID,
    campaign_id: CAMPAIGN_ID,
    kind: 'secret',
    title: 'Secret Tunnel Behind Cellar',
    body: 'Hidden lever opens stone door.',
    state: { kind: 'secret' },
    visibility: 'character',
    dm_notes: 'DC 15 Perception to spot.',
    needs_review: true,
    source_adventure_entry_id: 'adv-entry-77',
    provenance_json: { module: 'Ch1' },
    character_recipient_ids: ['char-101'],
    revision: 2,
    created_by_actor_kind: 'human',
    created_by_actor_id: null,
    created_at: '2026-09-20T00:00:00Z',
    updated_at: '2026-09-20T00:00:00Z',
    archived_at: null,
  }

  it('renders RuntimeEntryCardView with character recipient names in en and zh-TW', () => {
    for (const loc of ['en', 'zh-TW'] as const) {
      const copy = campaignRuntimeCopy(loc)
      const html = renderToStaticMarkup(
        <RuntimeEntryCardView
          entry={sampleEntry}
          entries={[]}
          characters={[charA, charB]}
          actions={null}
          copy={copy}
        />,
      )

      expect(html).toContain('Alandra')
      expect(html).toContain('adv-entry-77')
      expect(html).toContain('DC 15 Perception to spot.')
      expect(html).toContain(copy.needsReviewBadge)
      expect(html).not.toContain('?')
    }
  })

  it('renders RuntimeEntryCardView typed state values for NPC, Item, and Other in en and zh-TW', () => {
    const npcEntry: RuntimeWorldEntryDmView = {
      ...sampleEntry,
      id: 'npc-entry-1',
      kind: 'npc',
      title: 'Captain Kaelen',
      state: {
        kind: 'npc',
        monster_instance_id: '12345678-1234-4000-8000-123456789012',
        monster_template_ref: 'srd:guard-captain',
      },
    }

    const sceneEntry: RuntimeWorldEntryDmView = {
      ...sampleEntry,
      id: 'scene-entry-1',
      kind: 'scene',
      title: 'Castle Gate',
      state: { kind: 'scene' },
    }

    const itemSceneHolder: RuntimeWorldEntryDmView = {
      ...sampleEntry,
      id: 'item-entry-1',
      kind: 'item',
      title: 'Iron Key',
      state: {
        kind: 'item',
        holder_ref: { kind: 'scene', target_id: 'scene-entry-1' },
      },
    }

    const itemCharHolder: RuntimeWorldEntryDmView = {
      ...sampleEntry,
      id: 'item-entry-2',
      kind: 'item',
      title: 'Healing Potion',
      state: {
        kind: 'item',
        holder_ref: { kind: 'character', target_id: 'char-101' },
      },
    }

    const itemPartyHolder: RuntimeWorldEntryDmView = {
      ...sampleEntry,
      id: 'item-entry-3',
      kind: 'item',
      title: 'Ration Pack',
      visibility: 'public',
      character_recipient_ids: [],
      state: {
        kind: 'item',
        holder_ref: { kind: 'party', target_id: null },
      },
    }

    const otherEntry: RuntimeWorldEntryDmView = {
      ...sampleEntry,
      id: 'other-entry-1',
      kind: 'other',
      title: 'Custom Marker',
      visibility: 'public',
      character_recipient_ids: [],
      state: {
        kind: 'other',
        data: { active: true, difficulty: 5 },
      },
    }

    for (const loc of ['en', 'zh-TW'] as const) {
      const copy = campaignRuntimeCopy(loc)

      // NPC
      const npcHtml = renderToStaticMarkup(
        <RuntimeEntryCardView
          entry={npcEntry}
          entries={[]}
          characters={[]}
          actions={null}
          copy={copy}
        />,
      )
      expect(npcHtml).toContain(copy.monsterInstanceIdLabel)
      expect(npcHtml).toContain('12345678-1234-4000-8000-123456789012')
      expect(npcHtml).toContain(copy.monsterTemplateRefLabel)
      expect(npcHtml).toContain('srd:guard-captain')
      expect(npcHtml).not.toContain('?')

      // Item held by scene
      const itemSceneHtml = renderToStaticMarkup(
        <RuntimeEntryCardView
          entry={itemSceneHolder}
          entries={[sceneEntry]}
          characters={[]}
          actions={null}
          copy={copy}
        />,
      )
      expect(itemSceneHtml).toContain(copy.itemHolderKindLabel)
      expect(itemSceneHtml).toContain(copy.itemHolderScene)
      expect(itemSceneHtml).toContain('Castle Gate')
      expect(itemSceneHtml).not.toContain('?')

      // Item held by character
      const itemCharHtml = renderToStaticMarkup(
        <RuntimeEntryCardView
          entry={itemCharHolder}
          entries={[]}
          characters={[charA]}
          actions={null}
          copy={copy}
        />,
      )
      expect(itemCharHtml).toContain(copy.itemHolderCharacter)
      expect(itemCharHtml).toContain('Alandra')
      expect(itemCharHtml).not.toContain('?')

      // Item held by party
      const itemPartyHtml = renderToStaticMarkup(
        <RuntimeEntryCardView
          entry={itemPartyHolder}
          entries={[]}
          characters={[]}
          actions={null}
          copy={copy}
        />,
      )
      expect(itemPartyHtml).toContain(copy.itemHolderParty)
      expect(itemPartyHtml).not.toContain('(')
      expect(itemPartyHtml).not.toContain('?')

      // Other with data
      const otherHtml = renderToStaticMarkup(
        <RuntimeEntryCardView
          entry={otherEntry}
          entries={[]}
          characters={[]}
          actions={null}
          copy={copy}
        />,
      )
      expect(otherHtml).toContain(copy.otherDataLabel)
      expect(otherHtml).toContain('&quot;difficulty&quot;: 5')
      expect(otherHtml).not.toContain('?')
    }
  })

  it('renders RuntimeEntryCardView with absent title, body, and notes without placeholder artifacts', () => {
    const emptyEntry: RuntimeWorldEntryDmView = {
      ...sampleEntry,
      title: null,
      body: null,
      dm_notes: null,
      source_adventure_entry_id: null,
      provenance_json: null,
      visibility: 'public',
      character_recipient_ids: [],
    }

    for (const loc of ['en', 'zh-TW'] as const) {
      const copy = campaignRuntimeCopy(loc)
      const html = renderToStaticMarkup(
        <RuntimeEntryCardView
          entry={emptyEntry}
          entries={[]}
          characters={[]}
          actions={null}
          copy={copy}
        />,
      )

      expect(html).not.toContain('?')
      expect(html).toContain(copy.kindSecret)
      expect(html).toContain(copy.visibilityPublic)
    }
  })

  it('renders RuntimeEntryFormView in create mode and edit mode without placeholder artifacts', () => {
    const createForm = createInitialEntryFormState('npc')
    const editForm = entryToFormState(sampleEntry)
    expect(editForm).not.toBeNull()
    if (!editForm) throw new Error('expected editForm')

    for (const loc of ['en', 'zh-TW'] as const) {
      const copy = campaignRuntimeCopy(loc)

      const createHtml = renderToStaticMarkup(
        <RuntimeEntryFormView
          form={createForm}
          kindOptions={EDITABLE_RUNTIME_ENTRY_KINDS}
          onChange={vi.fn()}
          onSubmit={vi.fn()}
          onCancel={vi.fn()}
          entries={[]}
          characters={[charA, charB]}
          pending={false}
          formError={null}
          copy={copy}
        />,
      )
      expect(createHtml).toContain(copy.formTitleCreate)
      expect(createHtml).toContain(copy.submitCreate)
      expect(createHtml).not.toContain('?')

      const editHtml = renderToStaticMarkup(
        <RuntimeEntryFormView
          form={editForm}
          kindOptions={EDITABLE_RUNTIME_ENTRY_KINDS}
          onChange={vi.fn()}
          onSubmit={vi.fn()}
          onCancel={vi.fn()}
          entries={[]}
          characters={[charA, charB]}
          pending={false}
          formError={null}
          copy={copy}
        />,
      )
      expect(editHtml).toContain(copy.formTitleEdit)
      expect(editHtml).toContain(copy.submitUpdate)
      expect(editHtml).not.toContain('?')
    }
  })
})

describe('H.8 loadCampaignChanges snapshot helper', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('loads entries, overrides, context, and characters in a single typed snapshot', async () => {
    const fakeEntries = [{ id: ENTRY_ID, kind: 'npc' }]
    const fakeOverrides = [{ id: 'ovr-1', source_adventure_entry_id: 'adv-1' }]
    const fakeContext = { campaign_id: CAMPAIGN_ID, active_scene_entry_id: null }
    const fakeCharacters = [
      { id: 'char-1', name: 'Alandra', level: 3, class_summary: 'Wizard', version_no: 1 },
    ]

    const fetchMock = vi.fn().mockImplementation(async (url: string) => {
      if (url.includes('/runtime/entries')) {
        return { ok: true, status: 200, json: async () => fakeEntries }
      }
      if (url.includes('/runtime/overrides')) {
        return { ok: true, status: 200, json: async () => fakeOverrides }
      }
      if (url.includes('/runtime/context')) {
        return { ok: true, status: 200, json: async () => fakeContext }
      }
      if (url.includes('/characters')) {
        return { ok: true, status: 200, json: async () => fakeCharacters }
      }
      if (url.includes('/adventures')) {
        return { ok: true, status: 200, json: async () => [] }
      }
      return { ok: false, status: 404, json: async () => ({}) }
    })
    vi.stubGlobal('fetch', fetchMock)

    const snapshot = await loadCampaignChanges(ROOM_ID, CAMPAIGN_ID, 'test-token')

    expect(snapshot).toEqual({
      entries: fakeEntries,
      overrides: fakeOverrides,
      context: fakeContext,
      characters: fakeCharacters,
      attachedAdventures: [],
      overlays: [],
    })
    expect(fetchMock).toHaveBeenCalledTimes(5)
  })

  it('preserves fatal rejection if any underlying query fails', async () => {
    const fetchMock = vi.fn().mockImplementation(async (url: string) => {
      if (url.includes('/runtime/entries')) {
        return {
          ok: false,
          status: 500,
          json: async () => ({ error: { code: 'server_error', message: 'fatal' } }),
        }
      }
      return { ok: true, status: 200, json: async () => [] }
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(loadCampaignChanges(ROOM_ID, CAMPAIGN_ID, 'test-token')).rejects.toThrow()
  })
})
