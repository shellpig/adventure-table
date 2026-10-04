import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  archiveBattleMap,
  copyBattleMap,
  createBattleMap,
  deleteBattleMap,
  getBattleMap,
  listBattleMaps,
  patchBattleMap,
  replaceBattleMapObjects,
  replaceMonsterPlacements,
} from './battleMaps'

const ROOM_ID = '10000000-0000-4000-8000-000000000001'
const TOKEN = 'room-token'
const MAP_ID = '20000000-0000-4000-8000-000000000001'

const ok = (body: unknown = {}) =>
  ({ ok: true, status: 200, json: async () => body }) as Response

type FetchMock = (url: string, init?: RequestInit) => Promise<Response>

function mockFetch(responseBody: unknown = {}) {
  const fetchMock = vi.fn<FetchMock>(async () => ok(responseBody))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

afterEach(() => vi.unstubAllGlobals())

describe('Battle Maps API client', () => {
  it('calls listBattleMaps with expected endpoint', async () => {
    const fetchMock = mockFetch([])
    await listBattleMaps(ROOM_ID, TOKEN)
    expect(fetchMock).toHaveBeenCalledOnce()
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe(`/api/rooms/${ROOM_ID}/battle-maps`)
    expect(init?.headers).toMatchObject({ Authorization: `Bearer ${TOKEN}` })
  })

  it('calls createBattleMap with POST and body', async () => {
    const fetchMock = mockFetch({ id: MAP_ID })
    const body = { name: 'Test Map', source_kind: 'blank' as const, width_cells: 20, height_cells: 20 }
    await createBattleMap(ROOM_ID, body, TOKEN)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe(`/api/rooms/${ROOM_ID}/battle-maps`)
    expect(init?.method).toBe('POST')
    expect(JSON.parse(init?.body as string)).toEqual(body)
  })

  it('calls getBattleMap with map id', async () => {
    const fetchMock = mockFetch({ id: MAP_ID })
    await getBattleMap(ROOM_ID, MAP_ID, TOKEN)
    const [url] = fetchMock.mock.calls[0]
    expect(url).toBe(`/api/rooms/${ROOM_ID}/battle-maps/${MAP_ID}`)
  })

  it('calls patchBattleMap with PATCH and expected_revision', async () => {
    const fetchMock = mockFetch({ id: MAP_ID })
    await patchBattleMap(ROOM_ID, MAP_ID, { expected_revision: 3, name: 'Renamed' }, TOKEN)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe(`/api/rooms/${ROOM_ID}/battle-maps/${MAP_ID}`)
    expect(init?.method).toBe('PATCH')
    expect(JSON.parse(init?.body as string)).toEqual({ expected_revision: 3, name: 'Renamed' })
  })

  it('calls replaceBattleMapObjects with PUT and expected_revision', async () => {
    const fetchMock = mockFetch({ id: MAP_ID })
    const body = {
      expected_revision: 5,
      walls: [{ x1: 0, y1: 0, x2: 5, y2: 0, visibility: 'hidden' as const }],
      doors: [],
      terrain: [{ x: 1, y: 1, terrain_kind: 'difficult' as const }],
      drawings: [],
    }
    await replaceBattleMapObjects(ROOM_ID, MAP_ID, body, TOKEN)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe(`/api/rooms/${ROOM_ID}/battle-maps/${MAP_ID}/objects`)
    expect(init?.method).toBe('PUT')
    expect(JSON.parse(init?.body as string)).toEqual(body)
  })

  it('calls listBattleMaps with include_archived=true when requested', async () => {
    const fetchMock = mockFetch([])
    await listBattleMaps(ROOM_ID, TOKEN, { includeArchived: true })
    expect(fetchMock).toHaveBeenCalledOnce()
    const [url] = fetchMock.mock.calls[0]
    expect(url).toBe(`/api/rooms/${ROOM_ID}/battle-maps?include_archived=true`)
  })

  it('calls copyBattleMap with POST, /copy URL, and expected_revision', async () => {
    const fetchMock = mockFetch({ id: 'copy-id', revision: 1 })
    const body = { expected_revision: 2, name: 'Copied Map' }
    await copyBattleMap(ROOM_ID, MAP_ID, body, TOKEN)
    expect(fetchMock).toHaveBeenCalledOnce()
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe(`/api/rooms/${ROOM_ID}/battle-maps/${MAP_ID}/copy`)
    expect(init?.method).toBe('POST')
    expect(JSON.parse(init?.body as string)).toEqual(body)
  })

  it('calls archiveBattleMap with POST, /archive URL, and expected_revision', async () => {
    const fetchMock = mockFetch({ id: MAP_ID, revision: 3, archived_at: '2026-10-04T00:00:00Z' })
    const body = { expected_revision: 2 }
    await archiveBattleMap(ROOM_ID, MAP_ID, body, TOKEN)
    expect(fetchMock).toHaveBeenCalledOnce()
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe(`/api/rooms/${ROOM_ID}/battle-maps/${MAP_ID}/archive`)
    expect(init?.method).toBe('POST')
    expect(JSON.parse(init?.body as string)).toEqual(body)
  })

  it('calls deleteBattleMap with DELETE, expected_revision query param, and resolves on 204', async () => {
    const fetchMock = vi.fn<FetchMock>(async () => ({ ok: true, status: 204 } as Response))
    vi.stubGlobal('fetch', fetchMock)
    await expect(deleteBattleMap(ROOM_ID, MAP_ID, 4, TOKEN)).resolves.toBeUndefined()
    expect(fetchMock).toHaveBeenCalledOnce()
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe(`/api/rooms/${ROOM_ID}/battle-maps/${MAP_ID}?expected_revision=4`)
    expect(init?.method).toBe('DELETE')
  })

  it('calls replaceMonsterPlacements with PUT, expected_revision, and the full placement set', async () => {
    const fetchMock = mockFetch({ id: MAP_ID, revision: 8 })
    const body = {
      expected_revision: 7,
      placements: [
        {
          id: '20000000-0000-4000-8000-000000000001',
          template_key: 'srd5.1:monster:goblin',
          custom_template_id: null,
          anchor_x: 2,
          anchor_y: 3,
          visibility: 'hidden' as const,
          sort_order: 0,
        },
        {
          id: null,
          template_key: null,
          custom_template_id: '30000000-0000-4000-8000-000000000001',
          anchor_x: 5,
          anchor_y: 5,
          visibility: 'public' as const,
          sort_order: 1,
        },
      ],
    }
    await replaceMonsterPlacements(ROOM_ID, MAP_ID, body, TOKEN)
    expect(fetchMock).toHaveBeenCalledOnce()
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe(`/api/rooms/${ROOM_ID}/battle-maps/${MAP_ID}/monster-placements`)
    expect(init?.method).toBe('PUT')
    expect(JSON.parse(init?.body as string)).toEqual(body)
  })
})
