import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  administrativelyReassignPlayer,
  configurePreSessionAiDm,
  fetchMcpPublicOrigin,
  letAiControlPlayer,
  revokePreSessionAiDm,
  takeBackPlayer,
} from './aiControllers'

const ROOM = '10000000-0000-4000-8000-000000000001'
const CAMPAIGN = '20000000-0000-4000-8000-000000000001'
const SESSION = '30000000-0000-4000-8000-000000000001'
const SEAT = '40000000-0000-4000-8000-000000000001'
const TARGET = '50000000-0000-4000-8000-000000000001'
const ROOM_TOKEN = 'room-access-token'

function okJson(value: unknown, status = 200): Response {
  return {
    ok: true,
    status,
    json: async () => value,
  } as Response
}

function noContent(): Response {
  return { ok: true, status: 204 } as Response
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('AI controller API client', () => {
  it('creates Player handoff with the optional temporary instruction', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(okJson({
      grant_id: 'grant',
      seat_id: SEAT,
      role: 'player',
      session_id: SESSION,
      generation: 3,
      token: 'ai-token-once',
      token_hint: 'p3d_grant…',
      expires_at: null,
    }, 201))

    const result = await letAiControlPlayer(
      ROOM,
      CAMPAIGN,
      SESSION,
      SEAT,
      ROOM_TOKEN,
      'Protect the wizard',
    )

    expect(result.token).toBe('ai-token-once')
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/rooms/${ROOM}/campaigns/${CAMPAIGN}/sessions/${SESSION}/seats/${SEAT}/ai-control`,
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ Authorization: `Bearer ${ROOM_TOKEN}` }),
        body: JSON.stringify({ temporary_instruction: 'Protect the wizard' }),
      }),
    )
  })

  it('uses exact Take Back and administrative recovery endpoints', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(noContent())

    await takeBackPlayer(ROOM, CAMPAIGN, SESSION, SEAT, ROOM_TOKEN)
    await administrativelyReassignPlayer(
      ROOM,
      CAMPAIGN,
      SESSION,
      SEAT,
      ROOM_TOKEN,
      TARGET,
    )

    expect(fetchMock.mock.calls[0][0]).toBe(
      `/api/rooms/${ROOM}/campaigns/${CAMPAIGN}/sessions/${SESSION}/seats/${SEAT}/take-back`,
    )
    expect(fetchMock.mock.calls[1][0]).toBe(
      `/api/rooms/${ROOM}/campaigns/${CAMPAIGN}/sessions/${SESSION}/seats/${SEAT}/reassign-human`,
    )
    expect(JSON.parse(String((fetchMock.mock.calls[1][1] as RequestInit).body))).toEqual({
      target_access_session_id: TARGET,
    })
  })

  it('creates and revokes finite pre-session AI DM grants on the DM Seat endpoint', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(okJson({
        grant_id: 'grant',
        seat_id: SEAT,
        role: 'dm',
        session_id: null,
        generation: 2,
        token: 'dm-token-once',
        token_hint: 'p3d_grant…',
        expires_at: '2026-09-10T05:00:00Z',
      }, 201))
      .mockResolvedValueOnce(noContent())

    const issued = await configurePreSessionAiDm(ROOM, CAMPAIGN, SEAT, ROOM_TOKEN)
    await revokePreSessionAiDm(ROOM, CAMPAIGN, SEAT, ROOM_TOKEN)

    expect(issued.expires_at).not.toBeNull()
    expect(fetchMock.mock.calls[0][0]).toBe(
      `/api/rooms/${ROOM}/campaigns/${CAMPAIGN}/seats/${SEAT}/ai-dm-grant`,
    )
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe('POST')
    expect((fetchMock.mock.calls[1][1] as RequestInit).method).toBe('DELETE')
  })

  it('reads the public MCP origin without a Room token and passes null through', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(okJson({ public_origin: 'https://table.example.ts.net' }))
      .mockResolvedValueOnce(okJson({ public_origin: null }))

    expect(await fetchMcpPublicOrigin()).toBe('https://table.example.ts.net')
    expect(await fetchMcpPublicOrigin()).toBeNull()
    expect(fetchMock.mock.calls[0][0]).toBe('/api/mcp/public-origin')
    expect(fetchMock.mock.calls[0][1]).toBeUndefined()
  })
})
