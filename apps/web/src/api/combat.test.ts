import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  addMonsterToCombat,
  adjudicateAttackRange,
  advanceTurn,
  createMonsterFromContent,
  createQuickEnemy,
  endCombat,
  finalizeInitiative,
  getSuggestedInitiativeOrder,
  listAdjudications,
  listAttacks,
  listPendingCombatRolls,
  requestAttack,
  requestInitiative,
  requestOpportunityAttack,
  requestSpecialAdjudication,
  resolveAdjudication,
  rollAttack,
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

  it('calls attack list, request, and roll endpoints with expected request details', async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok({}))
    vi.stubGlobal('fetch', fetchMock)

    await listAttacks(ROOM_ID, CAMPAIGN_ID, SESSION_ID, 'entry-1', TOKEN)
    const [listUrl, listInit] = fetchMock.mock.calls[0]
    expect(listUrl).toBe(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/${SESSION_ID}/combat/entries/entry-1/attacks`,
    )
    expect(listInit.method).toBeUndefined()
    expect(listInit.body).toBeUndefined()
    expect(listInit.headers.Authorization).toBe(`Bearer ${TOKEN}`)

    await requestAttack(
      ROOM_ID,
      CAMPAIGN_ID,
      SESSION_ID,
      {
        attacker_entry_id: 'entry-1',
        target_entry_id: 'entry-2',
        source_ref: 'weapon:longsword',
        modifier_mode: 'advantage',
        range_confirmed: true,
        idempotency_key: 'attack-request-1',
      },
      TOKEN,
    )
    const [requestUrl, requestInit] = fetchMock.mock.calls[1]
    expect(requestUrl).toBe(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/${SESSION_ID}/combat/attacks/request`,
    )
    expect(requestInit.method).toBe('POST')
    expect(requestInit.headers.Authorization).toBe(`Bearer ${TOKEN}`)
    expect(JSON.parse(requestInit.body as string)).toEqual({
      attacker_entry_id: 'entry-1',
      target_entry_id: 'entry-2',
      source_ref: 'weapon:longsword',
      modifier_mode: 'advantage',
      range_confirmed: true,
      idempotency_key: 'attack-request-1',
    })

    await rollAttack(
      ROOM_ID,
      CAMPAIGN_ID,
      SESSION_ID,
      { roll_request_id: 'roll-request-1', source: 'server', idempotency_key: 'attack-roll-1' },
      TOKEN,
    )
    const [rollUrl, rollInit] = fetchMock.mock.calls[2]
    expect(rollUrl).toBe(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/${SESSION_ID}/combat/attacks/roll`,
    )
    expect(rollInit.method).toBe('POST')
    expect(rollInit.headers.Authorization).toBe(`Bearer ${TOKEN}`)
    expect(JSON.parse(rollInit.body as string)).toEqual({
      roll_request_id: 'roll-request-1',
      source: 'server',
      idempotency_key: 'attack-roll-1',
    })
  })

  it('calls pending combat rolls endpoint with GET and Bearer auth', async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok([]))
    vi.stubGlobal('fetch', fetchMock)

    await listPendingCombatRolls(ROOM_ID, CAMPAIGN_ID, SESSION_ID, TOKEN)

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/${SESSION_ID}/combat/pending-rolls`,
    )
    expect(init.method).toBeUndefined()
    expect(init.body).toBeUndefined()
    expect(init.headers.Authorization).toBe(`Bearer ${TOKEN}`)
  })

  it('calls range, list, and resolve adjudication endpoints with expected request details', async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok({}))
    vi.stubGlobal('fetch', fetchMock)

    await adjudicateAttackRange(
      ROOM_ID,
      CAMPAIGN_ID,
      SESSION_ID,
      {
        action_id: 'action-1',
        in_range: true,
        roll_mode: 'normal',
        note: 'Within bow range',
        idempotency_key: 'range-1',
      },
      TOKEN,
    )
    const [rangeUrl, rangeInit] = fetchMock.mock.calls[0]
    expect(rangeUrl).toBe(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/${SESSION_ID}/combat/attacks/adjudicate`,
    )
    expect(rangeInit.method).toBe('POST')
    expect(rangeInit.headers.Authorization).toBe(`Bearer ${TOKEN}`)
    expect(JSON.parse(rangeInit.body as string)).toEqual({
      action_id: 'action-1',
      in_range: true,
      roll_mode: 'normal',
      note: 'Within bow range',
      idempotency_key: 'range-1',
    })

    await listAdjudications(ROOM_ID, CAMPAIGN_ID, SESSION_ID, TOKEN)
    const [listUrl, listInit] = fetchMock.mock.calls[1]
    expect(listUrl).toBe(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/${SESSION_ID}/combat/adjudications`,
    )
    expect(listInit.method).toBeUndefined()
    expect(listInit.body).toBeUndefined()
    expect(listInit.headers.Authorization).toBe(`Bearer ${TOKEN}`)

    await resolveAdjudication(
      ROOM_ID,
      CAMPAIGN_ID,
      SESSION_ID,
      'action-2',
      { trigger: true, ruling: 'The reaction triggers', idempotency_key: 'resolve-1' },
      TOKEN,
    )
    const [resolveUrl, resolveInit] = fetchMock.mock.calls[2]
    expect(resolveUrl).toBe(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/${SESSION_ID}/combat/adjudications/action-2/resolve`,
    )
    expect(resolveInit.method).toBe('POST')
    expect(resolveInit.headers.Authorization).toBe(`Bearer ${TOKEN}`)
    expect(JSON.parse(resolveInit.body as string)).toEqual({
      trigger: true,
      ruling: 'The reaction triggers',
      idempotency_key: 'resolve-1',
    })
  })

  it('calls opportunity-attack and special adjudication endpoints with expected request details', async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok({}))
    vi.stubGlobal('fetch', fetchMock)

    await requestOpportunityAttack(
      ROOM_ID,
      CAMPAIGN_ID,
      SESSION_ID,
      {
        mover_entry_id: 'entry-2',
        reactor_entry_id: 'entry-1',
        question: 'Does leaving reach trigger an opportunity attack?',
        idempotency_key: 'oa-1',
      },
      TOKEN,
    )
    const [oaUrl, oaInit] = fetchMock.mock.calls[0]
    expect(oaUrl).toBe(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/${SESSION_ID}/combat/adjudications/opportunity-attack`,
    )
    expect(oaInit.method).toBe('POST')
    expect(oaInit.headers.Authorization).toBe(`Bearer ${TOKEN}`)
    expect(JSON.parse(oaInit.body as string)).toEqual({
      mover_entry_id: 'entry-2',
      reactor_entry_id: 'entry-1',
      question: 'Does leaving reach trigger an opportunity attack?',
      idempotency_key: 'oa-1',
    })

    await requestSpecialAdjudication(
      ROOM_ID,
      CAMPAIGN_ID,
      SESSION_ID,
      {
        subject_entry_id: 'entry-1',
        target_entry_ids: ['entry-2', 'entry-3'],
        question: 'Can this improvised action affect both targets?',
        idempotency_key: 'special-1',
      },
      TOKEN,
    )
    const [specialUrl, specialInit] = fetchMock.mock.calls[1]
    expect(specialUrl).toBe(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/${SESSION_ID}/combat/adjudications/special`,
    )
    expect(specialInit.method).toBe('POST')
    expect(specialInit.headers.Authorization).toBe(`Bearer ${TOKEN}`)
    expect(JSON.parse(specialInit.body as string)).toEqual({
      subject_entry_id: 'entry-1',
      target_entry_ids: ['entry-2', 'entry-3'],
      question: 'Can this improvised action affect both targets?',
      idempotency_key: 'special-1',
    })
  })
})