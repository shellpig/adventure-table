import { afterEach, describe, expect, it, vi } from 'vitest'

import { listSessionEvents, waitSessionEvents } from './sessions'

const ROOM_ID = '10000000-0000-4000-8000-000000000001'
const CAMPAIGN_ID = '20000000-0000-4000-8000-000000000001'
const SESSION_ID = '30000000-0000-4000-8000-000000000001'

const page = {
  session_id: SESSION_ID,
  after_seq: 7,
  cursor: 7,
  current_seq: 7,
  has_more: false,
  events: [],
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('P3-A Session event API client', () => {
  it('uses the bounded incremental event cursor endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => page })
    vi.stubGlobal('fetch', fetchMock)

    await listSessionEvents(ROOM_ID, CAMPAIGN_ID, SESSION_ID, 7, 'token', 25)

    expect(fetchMock).toHaveBeenCalledWith(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/${SESSION_ID}/events?after=7&limit=25`,
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer token' }),
      }),
    )
  })

  it('passes timeout and AbortSignal to the non-blocking wait endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => page })
    vi.stubGlobal('fetch', fetchMock)
    const controller = new AbortController()

    await waitSessionEvents(ROOM_ID, CAMPAIGN_ID, SESSION_ID, 7, 'token', {
      limit: 20,
      timeout: 0,
      signal: controller.signal,
    })

    expect(fetchMock).toHaveBeenCalledWith(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/${SESSION_ID}/events/wait?after=7&limit=20&timeout=0`,
      expect.objectContaining({
        signal: controller.signal,
        headers: expect.objectContaining({ Authorization: 'Bearer token' }),
      }),
    )
  })
})
