import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  getCombatBoard,
  placeCombatant,
  startTacticalCombat,
  updateBoardDoorState,
} from './tacticalCombat'

const ROOM_ID = '10000000-0000-4000-8000-000000000001'
const CAMPAIGN_ID = '20000000-0000-4000-8000-000000000001'
const SESSION_ID = '30000000-0000-4000-8000-000000000001'
const TOKEN = 'room-token'
const ENTRY_ID = '40000000-0000-4000-8000-000000000001'
const DOOR_ID = '50000000-0000-4000-8000-000000000001'

const ok = (body: unknown = {}) =>
  ({ ok: true, status: 200, json: async () => body }) as Response

type FetchMock = (url: string, init?: RequestInit) => Promise<Response>

function mockFetch(responseBody: unknown = {}) {
  const fetchMock = vi.fn<FetchMock>(async () => ok(responseBody))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

afterEach(() => vi.unstubAllGlobals())

const base = `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/${SESSION_ID}/combat`

describe('Tactical Combat API client', () => {
  it('calls startTacticalCombat with POST to tactical-start', async () => {
    const fetchMock = mockFetch({ id: 'combat-1' })
    vi.stubGlobal('fetch', fetchMock)
    const body = { battle_map_id: 'map-1', include_active_party: true, idempotency_key: 'key-1' }
    await startTacticalCombat(ROOM_ID, CAMPAIGN_ID, SESSION_ID, body, TOKEN)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe(`${base}/tactical-start`)
    expect(init?.method).toBe('POST')
    expect(JSON.parse(init?.body as string)).toEqual(body)
  })

  it('calls startTacticalCombat with blank dimensions', async () => {
    const fetchMock = mockFetch({ id: 'combat-1' })
    vi.stubGlobal('fetch', fetchMock)
    const body = { blank_width_cells: 20, blank_height_cells: 20, idempotency_key: 'key-2' }
    await startTacticalCombat(ROOM_ID, CAMPAIGN_ID, SESSION_ID, body, TOKEN)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe(`${base}/tactical-start`)
    expect(JSON.parse(init?.body as string)).toEqual(body)
  })

  it('calls getCombatBoard with expected endpoint', async () => {
    const fetchMock = mockFetch({ combat_id: 'combat-1' })
    vi.stubGlobal('fetch', fetchMock)
    await getCombatBoard(ROOM_ID, CAMPAIGN_ID, SESSION_ID, TOKEN)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe(`${base}/board`)
    expect(init?.headers).toMatchObject({ Authorization: `Bearer ${TOKEN}` })
  })

  it('calls placeCombatant with PUT to positions route', async () => {
    const fetchMock = mockFetch({ entry_id: ENTRY_ID })
    vi.stubGlobal('fetch', fetchMock)
    const body = { anchor_x: 5, anchor_y: 7, idempotency_key: 'key-3' }
    await placeCombatant(ROOM_ID, CAMPAIGN_ID, SESSION_ID, ENTRY_ID, body, TOKEN)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe(`${base}/board/positions/${ENTRY_ID}`)
    expect(init?.method).toBe('PUT')
    expect(JSON.parse(init?.body as string)).toEqual(body)
  })

  it('calls updateBoardDoorState with PATCH to doors route', async () => {
    const fetchMock = mockFetch({ door_id: DOOR_ID })
    vi.stubGlobal('fetch', fetchMock)
    const body = { state: 'open' as const, revealed: true }
    await updateBoardDoorState(ROOM_ID, CAMPAIGN_ID, SESSION_ID, DOOR_ID, body, TOKEN)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe(`${base}/board/doors/${DOOR_ID}`)
    expect(init?.method).toBe('PATCH')
    expect(JSON.parse(init?.body as string)).toEqual(body)
  })
})
