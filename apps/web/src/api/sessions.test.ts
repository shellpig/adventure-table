import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  abandonSession,
  endSession,
  getActiveSession,
  getSession,
  lateJoinSession,
  startSession,
} from './sessions'

const ROOM_ID = '10000000-0000-4000-8000-000000000001'
const CAMPAIGN_ID = '20000000-0000-4000-8000-000000000001'
const SESSION_ID = '30000000-0000-4000-8000-000000000001'
const SEAT_ID = '40000000-0000-4000-8000-000000000001'
const TOKEN = 'room-token'

const ok = (body: unknown = {}) => ({ ok: true, status: 200, json: async () => body })

afterEach(() => vi.unstubAllGlobals())

describe('P2-E Session API', () => {
  it('uses only Room/Campaign-scoped Session endpoints', async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok({ active_session: null }))
    vi.stubGlobal('fetch', fetchMock)

    await getActiveSession(ROOM_ID, CAMPAIGN_ID, TOKEN)
    await getSession(ROOM_ID, CAMPAIGN_ID, SESSION_ID, TOKEN)

    expect(fetchMock.mock.calls[0][0]).toBe(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/active`,
    )
    expect(fetchMock.mock.calls[1][0]).toBe(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/${SESSION_ID}`,
    )
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe(`Bearer ${TOKEN}`)
  })

  it('starts a Session without inventing Ready or online payload', async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok({}))
    vi.stubGlobal('fetch', fetchMock)

    await startSession(ROOM_ID, CAMPAIGN_ID, TOKEN)

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe(`/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions`)
    expect(init.method).toBe('POST')
    expect(init.body).toBeUndefined()
  })

  it('late joins by Seat identity only', async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok({}))
    vi.stubGlobal('fetch', fetchMock)

    await lateJoinSession(ROOM_ID, CAMPAIGN_ID, SESSION_ID, SEAT_ID, TOKEN)

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain(`/sessions/${SESSION_ID}/late-join`)
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body as string)).toEqual({ seat_id: SEAT_ID })
  })

  it('exposes explicit End and Abandon lifecycle calls', async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok({}))
    vi.stubGlobal('fetch', fetchMock)

    await endSession(ROOM_ID, CAMPAIGN_ID, SESSION_ID, TOKEN)
    await abandonSession(ROOM_ID, CAMPAIGN_ID, SESSION_ID, TOKEN)

    expect(fetchMock.mock.calls[0][0]).toContain(`/sessions/${SESSION_ID}/end`)
    expect(fetchMock.mock.calls[0][1].method).toBe('POST')
    expect(fetchMock.mock.calls[1][0]).toContain(`/sessions/${SESSION_ID}/abandon`)
    expect(fetchMock.mock.calls[1][1].method).toBe('POST')
  })
})
