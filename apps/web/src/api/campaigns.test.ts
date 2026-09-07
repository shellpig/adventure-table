import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  deleteCampaign,
  selectCampaign,
  setRosterStatus,
} from './campaigns'

const ROOM_ID = '10000000-0000-4000-8000-000000000001'
const CAMPAIGN_ID = '20000000-0000-4000-8000-000000000001'
const CHARACTER_ID = '30000000-0000-4000-8000-000000000001'
const TOKEN = 'room-token'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('P2-C Campaign API', () => {
  it('keeps Campaign selection inside the Room-scoped endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: CAMPAIGN_ID }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await selectCampaign(ROOM_ID, CAMPAIGN_ID, TOKEN)

    expect(fetchMock).toHaveBeenCalledWith(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/select`,
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ Authorization: `Bearer ${TOKEN}` }),
      }),
    )
  })

  it('patches Campaign-local roster status without sending Character state', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        campaign_id: CAMPAIGN_ID,
        character_id: CHARACTER_ID,
        status: 'retired',
      }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await setRosterStatus(ROOM_ID, CAMPAIGN_ID, CHARACTER_ID, TOKEN, 'retired')

    const [, init] = fetchMock.mock.calls[0]
    expect(init.method).toBe('PATCH')
    expect(JSON.parse(init.body as string)).toEqual({ status: 'retired' })
  })

  it('accepts the 204 draft-delete response without parsing JSON', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 204 })
    vi.stubGlobal('fetch', fetchMock)

    await expect(deleteCampaign(ROOM_ID, CAMPAIGN_ID, TOKEN)).resolves.toBeUndefined()
  })
})
