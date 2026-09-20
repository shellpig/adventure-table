import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  archiveActiveRuntimeEntry,
  archiveRuntimeEntry,
  CampaignRuntimeApiError,
  clearActiveOverride,
  clearActiveRuntimeContext,
  clearOverride,
  clearRuntimeContext,
  createActiveOverride,
  createActiveRuntimeEntry,
  createOverride,
  createRuntimeEntry,
  getActiveAdventureEntryOverlay,
  getActiveOverride,
  getActiveRuntimeContext,
  getActiveRuntimeEntry,
  getAdventureEntryOverlay,
  getOverride,
  getRuntimeContext,
  getRuntimeEntry,
  listActiveAdventureEntryOverlays,
  listActiveOverrides,
  listActiveRuntimeEntries,
  listAdventureEntryOverlays,
  listOverrides,
  listRuntimeEntries,
  updateActiveOverride,
  updateActiveRuntimeContext,
  updateActiveRuntimeEntry,
  updateOverride,
  updateRuntimeContext,
  updateRuntimeEntry,
} from './campaignRuntime'

const ROOM_ID = '10000000-0000-4000-8000-000000000001'
const CAMPAIGN_ID = '20000000-0000-4000-8000-000000000001'
const SESSION_ID = '30000000-0000-4000-8000-000000000001'
const ENTRY_ID = '40000000-0000-4000-8000-000000000001'
const ADVENTURE_ENTRY_ID = '50000000-0000-4000-8000-000000000001'
const ADVENTURE_ID = '60000000-0000-4000-8000-000000000001'
const TOKEN = 'room-test-token'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('P6-B Campaign Runtime API client', () => {
  it('listRuntimeEntries GETs /entries with Bearer header and optional include_archived query param', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => [{ id: ENTRY_ID, kind: 'npc' }],
    })
    vi.stubGlobal('fetch', fetchMock)

    const result1 = await listRuntimeEntries(ROOM_ID, CAMPAIGN_ID, TOKEN)
    expect(fetchMock).toHaveBeenLastCalledWith(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/runtime/entries`,
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: `Bearer ${TOKEN}`,
          'Content-Type': 'application/json',
        }),
      }),
    )
    expect(result1).toEqual([{ id: ENTRY_ID, kind: 'npc' }])

    await listRuntimeEntries(ROOM_ID, CAMPAIGN_ID, TOKEN, { includeArchived: true })
    expect(fetchMock).toHaveBeenLastCalledWith(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/runtime/entries?include_archived=true`,
      expect.anything(),
    )
  })

  it('getRuntimeEntry GETs /entries/{entryId} with Bearer header', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: ENTRY_ID, kind: 'scene', title: 'Tavern' }),
    })
    vi.stubGlobal('fetch', fetchMock)

    const result = await getRuntimeEntry(ROOM_ID, CAMPAIGN_ID, ENTRY_ID, TOKEN)
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/runtime/entries/${ENTRY_ID}`,
      expect.anything(),
    )
    expect(result.id).toBe(ENTRY_ID)
  })

  it('createRuntimeEntry POSTs exact body to /entries with 201 response', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      json: async () => ({ id: ENTRY_ID, kind: 'npc', title: 'Barkeep', revision: 1 }),
    })
    vi.stubGlobal('fetch', fetchMock)

    const payload = {
      idempotency_key: 'idemp-entry-1',
      kind: 'npc' as const,
      title: 'Barkeep',
      visibility: 'public' as const,
    }
    const result = await createRuntimeEntry(ROOM_ID, CAMPAIGN_ID, TOKEN, payload)

    expect(fetchMock).toHaveBeenCalledWith(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/runtime/entries`,
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          Authorization: `Bearer ${TOKEN}`,
          'Content-Type': 'application/json',
        }),
        body: JSON.stringify(payload),
      }),
    )
    expect(result.title).toBe('Barkeep')
  })

  it('updateRuntimeEntry PATCHes /entries/{entryId}', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: ENTRY_ID, revision: 2 }),
    })
    vi.stubGlobal('fetch', fetchMock)

    const payload = {
      idempotency_key: 'idemp-patch-1',
      expected_revision: 1,
      title: 'Updated Barkeep',
    }
    const result = await updateRuntimeEntry(ROOM_ID, CAMPAIGN_ID, ENTRY_ID, TOKEN, payload)

    expect(fetchMock).toHaveBeenCalledWith(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/runtime/entries/${ENTRY_ID}`,
      expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify(payload),
      }),
    )
    expect(result.revision).toBe(2)
  })

  it('archiveRuntimeEntry POSTs to /entries/{entryId}/archive', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: ENTRY_ID, archived_at: '2026-09-21T00:00:00Z' }),
    })
    vi.stubGlobal('fetch', fetchMock)

    const payload = { expected_revision: 2, idempotency_key: 'idemp-arch-1' }
    await archiveRuntimeEntry(ROOM_ID, CAMPAIGN_ID, ENTRY_ID, TOKEN, payload)

    expect(fetchMock).toHaveBeenCalledWith(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/runtime/entries/${ENTRY_ID}/archive`,
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify(payload),
      }),
    )
  })

  it('handles overrides management routes: list, get, create, update, clear', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: 'ovr-1', adventure_entry_id: ADVENTURE_ENTRY_ID }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await listOverrides(ROOM_ID, CAMPAIGN_ID, TOKEN)
    expect(fetchMock).toHaveBeenLastCalledWith(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/runtime/overrides`,
      expect.anything(),
    )

    await getOverride(ROOM_ID, CAMPAIGN_ID, ADVENTURE_ENTRY_ID, TOKEN)
    expect(fetchMock).toHaveBeenLastCalledWith(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/runtime/overrides/${ADVENTURE_ENTRY_ID}`,
      expect.anything(),
    )

    const createPayload = {
      idempotency_key: 'idemp-ovr-create',
      adventure_entry_id: ADVENTURE_ENTRY_ID,
      note: 'Modified disposition',
    }
    await createOverride(ROOM_ID, CAMPAIGN_ID, TOKEN, createPayload)
    expect(fetchMock).toHaveBeenLastCalledWith(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/runtime/overrides`,
      expect.objectContaining({ method: 'POST', body: JSON.stringify(createPayload) }),
    )

    const updatePayload = {
      idempotency_key: 'idemp-ovr-update',
      expected_override_id: 'ovr-1',
      expected_revision: 1,
      note: 'Further note',
    }
    await updateOverride(ROOM_ID, CAMPAIGN_ID, ADVENTURE_ENTRY_ID, TOKEN, updatePayload)
    expect(fetchMock).toHaveBeenLastCalledWith(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/runtime/overrides/${ADVENTURE_ENTRY_ID}`,
      expect.objectContaining({ method: 'PATCH', body: JSON.stringify(updatePayload) }),
    )

    const clearPayload = {
      idempotency_key: 'idemp-ovr-clear',
      expected_override_id: 'ovr-1',
      expected_revision: 2,
    }
    await clearOverride(ROOM_ID, CAMPAIGN_ID, ADVENTURE_ENTRY_ID, TOKEN, clearPayload)
    expect(fetchMock).toHaveBeenLastCalledWith(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/runtime/overrides/${ADVENTURE_ENTRY_ID}/clear`,
      expect.objectContaining({ method: 'POST', body: JSON.stringify(clearPayload) }),
    )
  })

  it('handles context management routes: get, update, clear', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        campaign_id: CAMPAIGN_ID,
        current_situation: 'Party resting',
        revision: 1,
      }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await getRuntimeContext(ROOM_ID, CAMPAIGN_ID, TOKEN)
    expect(fetchMock).toHaveBeenLastCalledWith(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/runtime/context`,
      expect.anything(),
    )

    const updatePayload = {
      idempotency_key: 'idemp-ctx-update',
      expected_revision: 1,
      current_situation: 'Ambush ahead',
    }
    await updateRuntimeContext(ROOM_ID, CAMPAIGN_ID, TOKEN, updatePayload)
    expect(fetchMock).toHaveBeenLastCalledWith(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/runtime/context`,
      expect.objectContaining({ method: 'PATCH', body: JSON.stringify(updatePayload) }),
    )

    const clearPayload = {
      idempotency_key: 'idemp-ctx-clear',
      expected_revision: 2,
    }
    await clearRuntimeContext(ROOM_ID, CAMPAIGN_ID, TOKEN, clearPayload)
    expect(fetchMock).toHaveBeenLastCalledWith(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/runtime/context/clear`,
      expect.objectContaining({ method: 'POST', body: JSON.stringify(clearPayload) }),
    )
  })

  it('handles overlays management routes: single and adventure list', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: ADVENTURE_ENTRY_ID, adventure_id: ADVENTURE_ID, kind: 'scene' }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await getAdventureEntryOverlay(ROOM_ID, CAMPAIGN_ID, ADVENTURE_ENTRY_ID, TOKEN)
    expect(fetchMock).toHaveBeenLastCalledWith(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/runtime/adventure-overlays/${ADVENTURE_ENTRY_ID}`,
      expect.anything(),
    )

    await listAdventureEntryOverlays(ROOM_ID, CAMPAIGN_ID, ADVENTURE_ID, TOKEN)
    expect(fetchMock).toHaveBeenLastCalledWith(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/runtime/adventures/${ADVENTURE_ID}/overlays`,
      expect.anything(),
    )
  })

  it('active prefix endpoints format URLs with /sessions/{sessionId}/runtime', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: ENTRY_ID, kind: 'fact' }),
    })
    vi.stubGlobal('fetch', fetchMock)

    const activeBase = `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/${SESSION_ID}/runtime`

    await listActiveRuntimeEntries(ROOM_ID, CAMPAIGN_ID, SESSION_ID, TOKEN)
    expect(fetchMock).toHaveBeenLastCalledWith(`${activeBase}/entries`, expect.anything())

    await getActiveRuntimeEntry(ROOM_ID, CAMPAIGN_ID, SESSION_ID, ENTRY_ID, TOKEN)
    expect(fetchMock).toHaveBeenLastCalledWith(`${activeBase}/entries/${ENTRY_ID}`, expect.anything())

    await createActiveRuntimeEntry(ROOM_ID, CAMPAIGN_ID, SESSION_ID, TOKEN, {
      idempotency_key: 'k',
      kind: 'fact',
      body: 'Active fact',
    })
    expect(fetchMock).toHaveBeenLastCalledWith(
      `${activeBase}/entries`,
      expect.objectContaining({ method: 'POST' }),
    )

    await updateActiveRuntimeEntry(ROOM_ID, CAMPAIGN_ID, SESSION_ID, ENTRY_ID, TOKEN, {
      idempotency_key: 'k',
      expected_revision: 1,
      body: 'Updated fact',
    })
    expect(fetchMock).toHaveBeenLastCalledWith(
      `${activeBase}/entries/${ENTRY_ID}`,
      expect.objectContaining({ method: 'PATCH' }),
    )

    await archiveActiveRuntimeEntry(ROOM_ID, CAMPAIGN_ID, SESSION_ID, ENTRY_ID, TOKEN, {
      idempotency_key: 'k',
      expected_revision: 1,
    })
    expect(fetchMock).toHaveBeenLastCalledWith(
      `${activeBase}/entries/${ENTRY_ID}/archive`,
      expect.objectContaining({ method: 'POST' }),
    )

    await listActiveOverrides(ROOM_ID, CAMPAIGN_ID, SESSION_ID, TOKEN)
    expect(fetchMock).toHaveBeenLastCalledWith(`${activeBase}/overrides`, expect.anything())

    await getActiveOverride(ROOM_ID, CAMPAIGN_ID, SESSION_ID, ADVENTURE_ENTRY_ID, TOKEN)
    expect(fetchMock).toHaveBeenLastCalledWith(
      `${activeBase}/overrides/${ADVENTURE_ENTRY_ID}`,
      expect.anything(),
    )

    await createActiveOverride(ROOM_ID, CAMPAIGN_ID, SESSION_ID, TOKEN, {
      idempotency_key: 'k',
      adventure_entry_id: ADVENTURE_ENTRY_ID,
    })
    expect(fetchMock).toHaveBeenLastCalledWith(
      `${activeBase}/overrides`,
      expect.objectContaining({ method: 'POST' }),
    )

    await updateActiveOverride(ROOM_ID, CAMPAIGN_ID, SESSION_ID, ADVENTURE_ENTRY_ID, TOKEN, {
      idempotency_key: 'k',
      expected_override_id: 'ovr-1',
      expected_revision: 1,
      note: 'Updated during the active Session',
    })
    expect(fetchMock).toHaveBeenLastCalledWith(
      `${activeBase}/overrides/${ADVENTURE_ENTRY_ID}`,
      expect.objectContaining({ method: 'PATCH' }),
    )

    await clearActiveOverride(ROOM_ID, CAMPAIGN_ID, SESSION_ID, ADVENTURE_ENTRY_ID, TOKEN, {
      idempotency_key: 'k',
      expected_override_id: 'ovr-1',
      expected_revision: 2,
    })
    expect(fetchMock).toHaveBeenLastCalledWith(
      `${activeBase}/overrides/${ADVENTURE_ENTRY_ID}/clear`,
      expect.objectContaining({ method: 'POST' }),
    )

    await getActiveRuntimeContext(ROOM_ID, CAMPAIGN_ID, SESSION_ID, TOKEN)
    expect(fetchMock).toHaveBeenLastCalledWith(`${activeBase}/context`, expect.anything())

    await updateActiveRuntimeContext(ROOM_ID, CAMPAIGN_ID, SESSION_ID, TOKEN, {
      idempotency_key: 'k',
      expected_revision: 1,
      current_situation: 'The party reached the gate',
    })
    expect(fetchMock).toHaveBeenLastCalledWith(
      `${activeBase}/context`,
      expect.objectContaining({ method: 'PATCH' }),
    )

    await clearActiveRuntimeContext(ROOM_ID, CAMPAIGN_ID, SESSION_ID, TOKEN, {
      idempotency_key: 'k',
      expected_revision: 2,
    })
    expect(fetchMock).toHaveBeenLastCalledWith(
      `${activeBase}/context/clear`,
      expect.objectContaining({ method: 'POST' }),
    )

    await getActiveAdventureEntryOverlay(ROOM_ID, CAMPAIGN_ID, SESSION_ID, ADVENTURE_ENTRY_ID, TOKEN)
    expect(fetchMock).toHaveBeenLastCalledWith(
      `${activeBase}/adventure-overlays/${ADVENTURE_ENTRY_ID}`,
      expect.anything(),
    )

    await listActiveAdventureEntryOverlays(ROOM_ID, CAMPAIGN_ID, SESSION_ID, ADVENTURE_ID, TOKEN)
    expect(fetchMock).toHaveBeenLastCalledWith(
      `${activeBase}/adventures/${ADVENTURE_ID}/overlays`,
      expect.anything(),
    )
  })

  it('rejects with CampaignRuntimeApiError parsing stable error codes', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 409,
      json: async () => ({
        error: {
          code: 'campaign_runtime_revision_conflict',
          message: 'Conflict revision',
        },
      }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(
      updateRuntimeContext(ROOM_ID, CAMPAIGN_ID, TOKEN, {
        idempotency_key: 'k',
        expected_revision: 1,
      }),
    ).rejects.toThrow(CampaignRuntimeApiError)

    try {
      await updateRuntimeContext(ROOM_ID, CAMPAIGN_ID, TOKEN, {
        idempotency_key: 'k',
        expected_revision: 1,
      })
    } catch (err) {
      expect(err).toBeInstanceOf(CampaignRuntimeApiError)
      const apiErr = err as CampaignRuntimeApiError
      expect(apiErr.status).toBe(409)
      expect(apiErr.code).toBe('campaign_runtime_revision_conflict')
      expect(apiErr.message).toBe('Conflict revision')
    }
  })

  it('handles non-JSON error response with stable fallback', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 502,
      json: async () => {
        throw new Error('Bad Gateway HTML')
      },
    })
    vi.stubGlobal('fetch', fetchMock)

    try {
      await getRuntimeContext(ROOM_ID, CAMPAIGN_ID, TOKEN)
      expect.unreachable('Should have thrown')
    } catch (err) {
      expect(err).toBeInstanceOf(CampaignRuntimeApiError)
      const apiErr = err as CampaignRuntimeApiError
      expect(apiErr.status).toBe(502)
      expect(apiErr.code).toBe('campaign_runtime_request_failed')
      expect(apiErr.message).toContain('502')
    }
  })
})
