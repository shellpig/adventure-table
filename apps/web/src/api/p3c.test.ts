import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  listRollRequests,
  requestCheck,
  submitFormalRoll,
  submitQuickRoll,
} from './p3c'

const ROOM = '10000000-0000-4000-8000-000000000001'
const CAMPAIGN = '20000000-0000-4000-8000-000000000001'
const SESSION = '30000000-0000-4000-8000-000000000001'
const SEAT = '40000000-0000-4000-8000-000000000001'
const REQUEST = '50000000-0000-4000-8000-000000000001'
const TOKEN = 'room-token'

function okJson(value: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => value,
  } as Response
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('P3-C roll API client', () => {
  it('posts DM Request Check to the canonical check endpoint', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(okJson({
      roll_group_id: 'group',
      requests: [],
    }))

    await requestCheck(ROOM, CAMPAIGN, SESSION, {
      target_seat_ids: [SEAT],
      request_type: 'skill',
      skill_ref: 'srd5.1:skill:perception',
      dc: 14,
      modifier_mode: 'advantage',
      visibility: 'roller_and_dm',
    }, TOKEN)

    expect(fetchMock).toHaveBeenCalledWith(
      `/api/rooms/${ROOM}/campaigns/${CAMPAIGN}/sessions/${SESSION}/checks`,
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ Authorization: `Bearer ${TOKEN}` }),
        body: expect.stringContaining('"dc":14'),
      }),
    )
  })

  it('lists caller-visible formal requests without a write', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(okJson([]))

    await listRollRequests(ROOM, CAMPAIGN, SESSION, TOKEN)

    expect(fetchMock).toHaveBeenCalledWith(
      `/api/rooms/${ROOM}/campaigns/${CAMPAIGN}/sessions/${SESSION}/roll-requests`,
      expect.not.objectContaining({ method: 'POST' }),
    )
  })

  it('submits physical formal rolls as raw dice rather than a client total', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(okJson({
      result_id: 'result',
      roll_request_id: REQUEST,
      hidden: false,
      result: null,
    }))

    await submitFormalRoll(ROOM, CAMPAIGN, SESSION, {
      roll_request_id: REQUEST,
      source: 'physical',
      raw_dice: [12, 17],
    }, TOKEN)

    const init = fetchMock.mock.calls[0][1] as RequestInit
    expect(JSON.parse(String(init.body))).toEqual({
      roll_request_id: REQUEST,
      source: 'physical',
      raw_dice: [12, 17],
    })
    expect(String(init.body)).not.toContain('total')
  })

  it('keeps Quick Dice on its separate endpoint', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(okJson({
      result_id: 'quick-result',
      roll_request_id: null,
      hidden: false,
      result: null,
    }))

    await submitQuickRoll(ROOM, CAMPAIGN, SESSION, {
      subject_seat_id: SEAT,
      dice_count: 2,
      die_sides: 6,
      flat_adjustment: 1,
    }, TOKEN)

    expect(fetchMock.mock.calls[0][0]).toBe(
      `/api/rooms/${ROOM}/campaigns/${CAMPAIGN}/sessions/${SESSION}/rolls/quick`,
    )
  })
})
