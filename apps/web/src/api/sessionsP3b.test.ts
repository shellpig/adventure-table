import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  getSessionStageImage,
  replaceSessionStage,
  sendExplorationInput,
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
})
