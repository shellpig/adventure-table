import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  getRoomAssetContent,
  RoomAssetApiError,
  roomAssetContentUrl,
  uploadRoomAsset,
} from './roomAssets'

const ROOM_ID = '10000000-0000-4000-8000-000000000001'
const ASSET_ID = '40000000-0000-4000-8000-000000000001'
const TOKEN = 'room-token'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('P6-A Room Assets API client', () => {
  it('uploadRoomAsset sends the Blob as body, Content-Type equal to Blob type, query string containing kind/filename/visibility, and NO application/json header', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      json: async () => ({
        id: ASSET_ID,
        room_id: ROOM_ID,
        kind: 'image',
        original_filename: 'map.png',
        mime_type: 'image/png',
        size_bytes: 1024,
        sha256: 'abc123',
        visibility: 'room',
        created_at: '2026-09-20T00:00:00Z',
      }),
    })
    vi.stubGlobal('fetch', fetchMock)

    const blob = new Blob(['fake image data'], { type: 'image/png' })

    const result = await uploadRoomAsset(ROOM_ID, TOKEN, {
      kind: 'image',
      filename: 'map.png',
      visibility: 'room',
      file: blob,
    })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]

    expect(url).toContain(`/api/rooms/${ROOM_ID}/assets?`)
    const parsedUrl = new URL(url as string, 'http://localhost')
    expect(parsedUrl.searchParams.get('kind')).toBe('image')
    expect(parsedUrl.searchParams.get('filename')).toBe('map.png')
    expect(parsedUrl.searchParams.get('visibility')).toBe('room')

    expect(init.method).toBe('POST')
    expect(init.body).toBe(blob)
    expect(init.headers).toEqual({
      Authorization: `Bearer ${TOKEN}`,
      'Content-Type': 'image/png',
    })
    expect(init.headers).not.toHaveProperty('Content-Type', 'application/json')
    expect(result.id).toBe(ASSET_ID)
  })

  it('roomAssetContentUrl returns relative path to asset content', () => {
    const url = roomAssetContentUrl(ROOM_ID, ASSET_ID)
    expect(url).toBe(`/api/rooms/${ROOM_ID}/assets/${ASSET_ID}/content`)
  })

  it('getRoomAssetContent fetches content with Bearer header and no Content-Type, resolves to Blob, and rejects with RoomAssetApiError on 404', async () => {
    const fakeBlob = new Blob(['fake image data'], { type: 'image/png' })
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      blob: async () => fakeBlob,
    })
    vi.stubGlobal('fetch', fetchMock)

    const result = await getRoomAssetContent(ROOM_ID, ASSET_ID, TOKEN)

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe(`/api/rooms/${ROOM_ID}/assets/${ASSET_ID}/content`)
    expect(init.headers).toEqual({
      Authorization: `Bearer ${TOKEN}`,
    })
    expect(init.headers).not.toHaveProperty('Content-Type')
    expect(result).toBe(fakeBlob)

    const errorFetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      json: async () => ({
        error: { code: 'room_asset_not_found', message: 'Asset not found' },
      }),
    })
    vi.stubGlobal('fetch', errorFetchMock)

    await expect(getRoomAssetContent(ROOM_ID, ASSET_ID, TOKEN)).rejects.toThrow(RoomAssetApiError)
    try {
      await getRoomAssetContent(ROOM_ID, ASSET_ID, TOKEN)
    } catch (err) {
      expect(err).toBeInstanceOf(RoomAssetApiError)
      const apiErr = err as RoomAssetApiError
      expect(apiErr.status).toBe(404)
      expect(apiErr.code).toBe('room_asset_not_found')
    }
  })
})
