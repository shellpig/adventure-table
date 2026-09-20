import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  AdventureApiError,
  attachCampaignAdventure,
  createAdventure,
  deleteAdventure,
  finalizeAdventure,
} from './adventures'

const ROOM_ID = '10000000-0000-4000-8000-000000000001'
const CAMPAIGN_ID = '20000000-0000-4000-8000-000000000001'
const ADVENTURE_ID = '30000000-0000-4000-8000-000000000001'
const TOKEN = 'room-token'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('P6-A Adventures API client', () => {
  it('createAdventure POSTs to /api/rooms/{room}/adventures with JSON body and Bearer header', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      json: async () => ({ id: ADVENTURE_ID, name: 'Sunless Citadel' }),
    })
    vi.stubGlobal('fetch', fetchMock)

    const result = await createAdventure(ROOM_ID, TOKEN, {
      name: 'Sunless Citadel',
      summary: 'A classic dungeon crawl',
    })

    expect(fetchMock).toHaveBeenCalledWith(
      `/api/rooms/${ROOM_ID}/adventures`,
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          'Content-Type': 'application/json',
          Authorization: `Bearer ${TOKEN}`,
        }),
        body: JSON.stringify({
          name: 'Sunless Citadel',
          summary: 'A classic dungeon crawl',
        }),
      }),
    )
    expect(result).toEqual({ id: ADVENTURE_ID, name: 'Sunless Citadel' })
  })

  it('finalizeAdventure POSTs /finalize', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: ADVENTURE_ID, status: 'finalized' }),
    })
    vi.stubGlobal('fetch', fetchMock)

    const result = await finalizeAdventure(ROOM_ID, ADVENTURE_ID, TOKEN)

    expect(fetchMock).toHaveBeenCalledWith(
      `/api/rooms/${ROOM_ID}/adventures/${ADVENTURE_ID}/finalize`,
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          Authorization: `Bearer ${TOKEN}`,
        }),
      }),
    )
    expect(result.status).toBe('finalized')
  })

  it('deleteAdventure sends DELETE and resolves undefined on 204', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(deleteAdventure(ROOM_ID, ADVENTURE_ID, TOKEN)).resolves.toBeUndefined()

    expect(fetchMock).toHaveBeenCalledWith(
      `/api/rooms/${ROOM_ID}/adventures/${ADVENTURE_ID}`,
      expect.objectContaining({
        method: 'DELETE',
        headers: expect.objectContaining({
          Authorization: `Bearer ${TOKEN}`,
        }),
      }),
    )
  })

  it('attachCampaignAdventure POSTs {adventure_id} to the campaign route', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      json: async () => ({
        campaign_id: CAMPAIGN_ID,
        adventure_id: ADVENTURE_ID,
        name: 'Sunless Citadel',
        status: 'finalized',
      }),
    })
    vi.stubGlobal('fetch', fetchMock)

    const result = await attachCampaignAdventure(ROOM_ID, CAMPAIGN_ID, TOKEN, ADVENTURE_ID)

    expect(fetchMock).toHaveBeenCalledWith(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/adventures`,
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          'Content-Type': 'application/json',
          Authorization: `Bearer ${TOKEN}`,
        }),
        body: JSON.stringify({ adventure_id: ADVENTURE_ID }),
      }),
    )
    expect(result.adventure_id).toBe(ADVENTURE_ID)
  })

  it('rejects with AdventureApiError on a 409 response carrying the error code', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 409,
      json: async () => ({
        error: {
          code: 'adventure_attached_use_archive',
          message: 'Adventure is attached to a campaign; use archive',
        },
      }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(deleteAdventure(ROOM_ID, ADVENTURE_ID, TOKEN)).rejects.toThrow(
      AdventureApiError,
    )

    try {
      await deleteAdventure(ROOM_ID, ADVENTURE_ID, TOKEN)
    } catch (err) {
      expect(err).toBeInstanceOf(AdventureApiError)
      const apiErr = err as AdventureApiError
      expect(apiErr.status).toBe(409)
      expect(apiErr.code).toBe('adventure_attached_use_archive')
    }
  })
})
