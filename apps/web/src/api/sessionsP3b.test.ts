import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  getSessionStage,
  getSessionStageImage,
  replaceSessionStage,
  sendExplorationInput,
  setSessionStageImageSource,
} from './sessions'

const ROOM_ID = '10000000-0000-4000-8000-000000000001'
const CAMPAIGN_ID = '20000000-0000-4000-8000-000000000001'
const SESSION_ID = '30000000-0000-4000-8000-000000000001'


afterEach(() => {
  vi.unstubAllGlobals()
})

describe('P3-B Session API client', () => {
  it('uses one canonical Stage route with revision CAS and one typed exploration route', async () => {
    const responses = [
      {
        session_id: SESSION_ID,
        revision: 3,
        text: 'Gate',
        image_id: null,
        image_media_type: null,
        image_filename: null,
      },
      {
        id: '50000000-0000-4000-8000-000000000001',
        session_id: SESSION_ID,
        seq: 2,
        kind: 'exploration.action',
        acting_seat_id: null,
        subject_seat_id: null,
        subject_character_id: null,
        execution_mode: 'self',
        visibility: 'public',
        recipient_seat_ids: [],
        payload_version: 1,
        payload: { text: 'Search' },
        created_at: '2026-09-09T00:00:00Z',
      },
    ]
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => responses[0] })
      .mockResolvedValueOnce({ ok: true, json: async () => responses[1] })
    vi.stubGlobal('fetch', fetchMock)

    await replaceSessionStage(
      ROOM_ID,
      CAMPAIGN_ID,
      SESSION_ID,
      { expected_revision: 2, text: 'Gate' },
      'token',
    )
    await sendExplorationInput(ROOM_ID, CAMPAIGN_ID, SESSION_ID, {
      kind: 'action',
      text: 'Search',
      subject_seat_id: '40000000-0000-4000-8000-000000000001',
      source_command: 'search',
    }, 'token')

    expect(fetchMock.mock.calls[0][0]).toBe(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/${SESSION_ID}/stage`,
    )
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: 'PUT' })
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toMatchObject({
      expected_revision: 2,
      text: 'Gate',
    })
    expect(fetchMock.mock.calls[1][0]).toBe(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/${SESSION_ID}/exploration`,
    )
    expect(fetchMock.mock.calls[1][1]).toMatchObject({ method: 'POST' })
  })

  it('loads Stage images with bearer auth instead of exposing the Room token in an img URL', async () => {
    const blob = new Blob(['x'], { type: 'image/png' })
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, blob: async () => blob })
    vi.stubGlobal('fetch', fetchMock)

    await getSessionStageImage(
      ROOM_ID,
      CAMPAIGN_ID,
      SESSION_ID,
      '60000000-0000-4000-8000-000000000001',
      'secret-token',
    )

    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).not.toContain('secret-token')
    expect(init.headers.Authorization).toBe('Bearer secret-token')
  })

  it('gets canonical Stage and sets Stage image source with expected revision', async () => {
    const stageState = {
      session_id: SESSION_ID,
      revision: 4,
      text: null,
      image_id: 'img-01',
      image_media_type: 'image/png',
      image_filename: 'map.png',
    }
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => stageState })
    vi.stubGlobal('fetch', fetchMock)

    const got = await getSessionStage(ROOM_ID, CAMPAIGN_ID, SESSION_ID, 'token-123')
    expect(got).toEqual(stageState)
    expect(fetchMock.mock.calls[0][0]).toBe(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/${SESSION_ID}/stage`,
    )
    expect(fetchMock.mock.calls[0][1]).toMatchObject({
      headers: { Authorization: 'Bearer token-123' },
    })

    await setSessionStageImageSource(
      ROOM_ID,
      CAMPAIGN_ID,
      SESSION_ID,
      {
        source: {
          kind: 'adventure_entry_asset',
          adventure_id: 'adv-01',
          adventure_entry_id: 'entry-01',
          asset_id: 'asset-01',
        },
        expected_revision: 4,
        idempotency_key: 'idem-key-1',
      },
      'token-123',
    )

    expect(fetchMock.mock.calls[1][0]).toBe(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/${SESSION_ID}/stage/image-source`,
    )
    expect(fetchMock.mock.calls[1][1]).toMatchObject({
      method: 'PUT',
      headers: {
        Authorization: 'Bearer token-123',
        'Content-Type': 'application/json',
      },
    })
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({
      source: {
        kind: 'adventure_entry_asset',
        adventure_id: 'adv-01',
        adventure_entry_id: 'entry-01',
        asset_id: 'asset-01',
      },
      expected_revision: 4,
      idempotency_key: 'idem-key-1',
    })
  })
})
