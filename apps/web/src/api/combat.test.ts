import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  addMonsterToCombat,
  advanceTurn,
  createMonsterFromContent,
  createQuickEnemy,
  endCombat,
  finalizeInitiative,
  getSuggestedInitiativeOrder,
  requestInitiative,
  rollInitiative,
  startCombat,
} from './combat'

const ROOM_ID = '10000000-0000-4000-8000-000000000001'
const CAMPAIGN_ID = '20000000-0000-4000-8000-000000000001'
const SESSION_ID = '30000000-0000-4000-8000-000000000001'
const TOKEN = 'room-token'

const ok = (body: unknown = {}) => ({ ok: true, status: 200, json: async () => body })

afterEach(() => vi.unstubAllGlobals())

describe('Combat API client', () => {
  it('calls startCombat with expected endpoint, method, and body', async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok({ id: 'combat-1', status: 'initiative_pending' }))
    vi.stubGlobal('fetch', fetchMock)

    await startCombat(
      ROOM_ID,
      CAMPAIGN_ID,
      SESSION_ID,
      { include_active_party: true, idempotency_key: 'start-key-1' },
      TOKEN,
    )

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/${SESSION_ID}/combat/start`,
    )
    expect(init.method).toBe('POST')
    expect(init.headers.Authorization).toBe(`Bearer ${TOKEN}`)
    expect(JSON.parse(init.body as string)).toEqual({
      include_active_party: true,
      idempotency_key: 'start-key-1',
    })
  })

  it('calls rollInitiative with expected endpoint, method, and body', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      ok({ result_id: 'res-1', roll_request_id: 'req-1', total: 15, combat_entry_ids: ['entry-1'] }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await rollInitiative(
      ROOM_ID,
      CAMPAIGN_ID,
      SESSION_ID,
      { roll_request_id: 'req-1', source: 'server', idempotency_key: 'roll-key-1' },
      TOKEN,
    )

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/${SESSION_ID}/combat/initiative/roll`,
    )
    expect(init.method).toBe('POST')
    expect(init.headers.Authorization).toBe(`Bearer ${TOKEN}`)
    expect(JSON.parse(init.body as string)).toEqual({
      roll_request_id: 'req-1',
      source: 'server',
      idempotency_key: 'roll-key-1',
    })
  })

  it('calls endCombat, addMonsterToCombat, requestInitiative, advanceTurn, and finalizeInitiative', async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok({}))
    vi.stubGlobal('fetch', fetchMock)

    await endCombat(ROOM_ID, CAMPAIGN_ID, SESSION_ID, { idempotency_key: 'end-1' }, TOKEN)
    expect(fetchMock.mock.calls[0][0]).toBe(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/${SESSION_ID}/combat/end`,
    )

    await addMonsterToCombat(
      ROOM_ID,
      CAMPAIGN_ID,
      SESSION_ID,
      { monster_instance_id: 'inst-1', idempotency_key: 'add-1' },
      TOKEN,
    )
    expect(fetchMock.mock.calls[1][0]).toBe(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/${SESSION_ID}/combat/entries/monsters`,
    )

    await requestInitiative(
      ROOM_ID,
      CAMPAIGN_ID,
      SESSION_ID,
      { entry_ids: [], modifier_mode: 'normal', idempotency_key: 'init-req-1' },
      TOKEN,
    )
    expect(fetchMock.mock.calls[2][0]).toBe(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/${SESSION_ID}/combat/initiative/request`,
    )

    await getSuggestedInitiativeOrder(ROOM_ID, CAMPAIGN_ID, SESSION_ID, TOKEN)
    expect(fetchMock.mock.calls[3][0]).toBe(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/${SESSION_ID}/combat/initiative/suggested-order`,
    )

    await finalizeInitiative(
      ROOM_ID,
      CAMPAIGN_ID,
      SESSION_ID,
      { ordered_entry_ids: ['entry-1'], idempotency_key: 'init-fin-1' },
      TOKEN,
    )
    expect(fetchMock.mock.calls[4][0]).toBe(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/${SESSION_ID}/combat/initiative/finalize`,
    )

    await advanceTurn(ROOM_ID, CAMPAIGN_ID, SESSION_ID, { idempotency_key: 'adv-1' }, TOKEN)
    expect(fetchMock.mock.calls[5][0]).toBe(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/${SESSION_ID}/combat/turn/advance`,
    )
  })

  it('calls monster-instances endpoints fromContent and quickEnemy', async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok({ id: 'inst-1', name: 'Goblin' }))
    vi.stubGlobal('fetch', fetchMock)

    await createMonsterFromContent(
      ROOM_ID,
      CAMPAIGN_ID,
      SESSION_ID,
      {
        content_key: 'srd5.1:monster:goblin',
        visibility: 'public',
        idempotency_key: 'from-content-1',
      },
      TOKEN,
    )
    expect(fetchMock.mock.calls[0][0]).toBe(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/${SESSION_ID}/monster-instances/from-content`,
    )

    await createQuickEnemy(
      ROOM_ID,
      CAMPAIGN_ID,
      SESSION_ID,
      {
        name: 'Bandit',
        armor_class: 12,
        max_hp: 11,
        visibility: 'hidden',
        idempotency_key: 'quick-enemy-1',
      },
      TOKEN,
    )
    expect(fetchMock.mock.calls[1][0]).toBe(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/${SESSION_ID}/monster-instances/quick-enemy`,
    )
  })
})
