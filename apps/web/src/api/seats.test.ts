import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  archiveSeat,
  createSeat,
  deleteSeat,
  getLobby,
  setSeatCharacter,
  setSeatController,
} from './seats'

const ROOM_ID = '10000000-0000-4000-8000-000000000001'
const CAMPAIGN_ID = '20000000-0000-4000-8000-000000000001'
const SEAT_ID = '30000000-0000-4000-8000-000000000001'
const CHARACTER_ID = '40000000-0000-4000-8000-000000000001'
const ACCESS_ID = '50000000-0000-4000-8000-000000000001'
const TOKEN = 'room-token'

afterEach(() => vi.unstubAllGlobals())

const ok = (body: unknown = {}, status = 200) => ({ ok: true, status, json: async () => body })

describe('P2-D Seat API', () => {
  it('loads Lobby from the Campaign-scoped endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok({
      room_id: ROOM_ID,
      campaign_id: CAMPAIGN_ID,
      caller_access_session_id: ACCESS_ID,
      seats: [],
      controllers: [],
    }))
    vi.stubGlobal('fetch', fetchMock)
    await getLobby(ROOM_ID, CAMPAIGN_ID, TOKEN)
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/lobby`,
      expect.objectContaining({ headers: expect.objectContaining({ Authorization: `Bearer ${TOKEN}` }) }),
    )
  })

  it('creates only the requested Seat role and label', async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok())
    vi.stubGlobal('fetch', fetchMock)
    await createSeat(ROOM_ID, CAMPAIGN_ID, TOKEN, { role: 'player', label: 'Mira' })
    const [, init] = fetchMock.mock.calls[0]
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body as string)).toEqual({ role: 'player', label: 'Mira' })
  })

  it('binds Human controller by Room access-session identity', async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok())
    vi.stubGlobal('fetch', fetchMock)
    await setSeatController(ROOM_ID, CAMPAIGN_ID, SEAT_ID, TOKEN, {
      controller_kind: 'human',
      controller_access_session_id: ACCESS_ID,
    })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain(`/seats/${SEAT_ID}/controller`)
    expect(JSON.parse(init.body as string)).toEqual({
      controller_kind: 'human',
      controller_access_session_id: ACCESS_ID,
    })
  })

  it('sends only the lobby Character selection, never Character State', async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok())
    vi.stubGlobal('fetch', fetchMock)
    await setSeatCharacter(ROOM_ID, CAMPAIGN_ID, SEAT_ID, TOKEN, CHARACTER_ID)
    const [, init] = fetchMock.mock.calls[0]
    expect(JSON.parse(init.body as string)).toEqual({ selected_character_id: CHARACTER_ID })
  })

  it('exposes both archive and hard-delete lifecycle calls', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(ok())
      .mockResolvedValueOnce(ok({}, 204))
    vi.stubGlobal('fetch', fetchMock)

    await archiveSeat(ROOM_ID, CAMPAIGN_ID, SEAT_ID, TOKEN)
    await deleteSeat(ROOM_ID, CAMPAIGN_ID, SEAT_ID, TOKEN)

    expect(fetchMock.mock.calls[0][0]).toContain(`/seats/${SEAT_ID}/archive`)
    expect(fetchMock.mock.calls[0][1].method).toBe('POST')
    expect(fetchMock.mock.calls[1][0]).toContain(`/seats/${SEAT_ID}`)
    expect(fetchMock.mock.calls[1][1].method).toBe('DELETE')
  })
})
