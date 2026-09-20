import { afterEach, describe, expect, it, vi } from 'vitest'

import {
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
})
