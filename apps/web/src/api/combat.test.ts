import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  addMonsterToCombat,
  adjudicateAttackRange,
  adjudicateSpecialAttack,
  advanceTurn,
  castSpell,
  createMonsterFromContent,
  createQuickEnemy,
  endCombat,
  finalizeInitiative,
  getReactionWindow,
  getSuggestedInitiativeOrder,
  listAdjudications,
  listAttacks,
  listCastableSpells,
  listPendingCombatRolls,
  proposeAoeSpell,
  requestAttack,
  requestInitiative,
  requestOpportunityAttack,
  requestSpecialAdjudication,
  requestSpecialAttack,
  resolveAdjudication,
  resolveAoeSpell,
  resolveReaction,
  rollAttack,
  rollConcentration,
  rollDeathSave,
  rollInitiative,
  rollSavingThrow,
  rollSpecialAttack,
  setMonsterOutcome,
  startCombat,
  updateMonsterInstance,
} from './combat'

const ROOM_ID = '10000000-0000-4000-8000-000000000001'
const CAMPAIGN_ID = '20000000-0000-4000-8000-000000000001'
const SESSION_ID = '30000000-0000-4000-8000-000000000001'
const TOKEN = 'room-token'

const ok = (body: unknown = {}) => ({ ok: true, status: 200, json: async () => body })

afterEach(() => vi.unstubAllGlobals())

describe('Combat API client', () => {
  it('calls startCombat with expected endpoint, method, and body', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(ok({ id: 'combat-1', status: 'initiative_pending' }))
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
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        ok({
          result_id: 'res-1',
          roll_request_id: 'req-1',
          total: 15,
          combat_entry_ids: ['entry-1'],
        }),
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

  it('calls setMonsterOutcome and updateMonsterInstance with expected request details', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(ok({ id: 'combat-1' }))
      .mockResolvedValueOnce(ok({ id: 'inst-1', name: 'Goblin Scout' }))
    vi.stubGlobal('fetch', fetchMock)

    await setMonsterOutcome(
      ROOM_ID,
      CAMPAIGN_ID,
      SESSION_ID,
      'entry-1',
      {
        outcome: 'unconscious',
        note: null,
        idempotency_key: 'outcome-key-1',
      },
      TOKEN,
    )

    const [outcomeUrl, outcomeInit] = fetchMock.mock.calls[0]
    expect(outcomeUrl).toBe(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/${SESSION_ID}/combat/entries/entry-1/outcome`,
    )
    expect(outcomeInit.method).toBe('POST')
    expect(outcomeInit.headers.Authorization).toBe(`Bearer ${TOKEN}`)
    expect(JSON.parse(outcomeInit.body as string)).toEqual({
      outcome: 'unconscious',
      note: null,
      idempotency_key: 'outcome-key-1',
    })

    await updateMonsterInstance(
      ROOM_ID,
      CAMPAIGN_ID,
      SESSION_ID,
      'inst-1',
      {
        name: 'Goblin Veteran',
        visibility: 'public',
        position_note: 'behind pillar',
        reveal: { armor_class: true, position_note: true },
        idempotency_key: 'update-key-1',
      },
      TOKEN,
    )

    const [updateUrl, updateInit] = fetchMock.mock.calls[1]
    expect(updateUrl).toBe(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/${SESSION_ID}/monster-instances/inst-1`,
    )
    expect(updateInit.method).toBe('PATCH')
    expect(updateInit.headers.Authorization).toBe(`Bearer ${TOKEN}`)
    expect(JSON.parse(updateInit.body as string)).toEqual({
      name: 'Goblin Veteran',
      visibility: 'public',
      position_note: 'behind pillar',
      reveal: { armor_class: true, position_note: true },
      idempotency_key: 'update-key-1',
    })
  })

  it('calls attack list, request, and roll endpoints with expected request details', async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok({}))
    vi.stubGlobal('fetch', fetchMock)
    await listAttacks(ROOM_ID, CAMPAIGN_ID, SESSION_ID, 'entry-1', TOKEN)
    expect(fetchMock.mock.calls[0][0]).toBe(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/${SESSION_ID}/combat/entries/entry-1/attacks`,
    )
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
    expect(fetchMock.mock.calls[1][0]).toBe(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/${SESSION_ID}/combat/attacks/request`,
    )
    await rollAttack(
      ROOM_ID,
      CAMPAIGN_ID,
      SESSION_ID,
      { roll_request_id: 'roll-request-1', source: 'server', idempotency_key: 'attack-roll-1' },
      TOKEN,
    )
    expect(fetchMock.mock.calls[2][0]).toBe(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/${SESSION_ID}/combat/attacks/roll`,
    )
    for (const [, init] of fetchMock.mock.calls)
      expect(init.headers.Authorization).toBe(`Bearer ${TOKEN}`)
  })

  it('calls castable spell list endpoint with GET and Bearer auth', async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok([]))
    vi.stubGlobal('fetch', fetchMock)
    await listCastableSpells(ROOM_ID, CAMPAIGN_ID, SESSION_ID, 'entry-1', TOKEN)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/${SESSION_ID}/combat/entries/entry-1/spells`,
    )
    expect(init.method).toBeUndefined()
    expect(init.body).toBeUndefined()
    expect(init.headers.Authorization).toBe(`Bearer ${TOKEN}`)
  })

  it('calls spell cast, AoE propose, and AoE resolve endpoints', async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok({}))
    vi.stubGlobal('fetch', fetchMock)
    const castBody = {
      caster_entry_id: 'entry-1',
      target_entry_id: 'entry-2',
      spell_ref: 'srd5.1:spell:fire-bolt',
      slot_level: 0,
      profile_id: 'wizard',
      attack_mode: 'advantage' as const,
      idempotency_key: 'spell-cast-1',
    }
    await castSpell(ROOM_ID, CAMPAIGN_ID, SESSION_ID, castBody, TOKEN)
    const proposeBody = {
      caster_entry_id: 'entry-1',
      spell_ref: 'srd5.1:spell:fireball',
      slot_level: 3,
      profile_id: 'wizard',
      proposed_target_ids: ['entry-2', 'entry-3'],
      idempotency_key: 'spell-aoe-propose-1',
    }
    await proposeAoeSpell(ROOM_ID, CAMPAIGN_ID, SESSION_ID, proposeBody, TOKEN)
    const resolveBody = {
      action_id: 'action-aoe-1',
      confirmed_target_ids: ['entry-2'],
      idempotency_key: 'spell-aoe-resolve-1',
    }
    await resolveAoeSpell(ROOM_ID, CAMPAIGN_ID, SESSION_ID, resolveBody, TOKEN)

    const expected = [
      ['spells/cast', castBody],
      ['spells/aoe/propose', proposeBody],
      ['spells/aoe/resolve', resolveBody],
    ] as const
    expected.forEach(([path, body], index) => {
      const [url, init] = fetchMock.mock.calls[index]
      expect(url).toBe(
        `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/${SESSION_ID}/combat/${path}`,
      )
      expect(init.method).toBe('POST')
      expect(init.headers.Authorization).toBe(`Bearer ${TOKEN}`)
      expect(JSON.parse(init.body as string)).toEqual(body)
    })
  })

  it('calls saving throw, death save, concentration, and special-attack roll endpoints', async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok({}))
    vi.stubGlobal('fetch', fetchMock)
    const body = {
      roll_request_id: 'roll-request-1',
      source: 'server' as const,
      idempotency_key: 'pending-roll-1',
    }
    await rollSavingThrow(ROOM_ID, CAMPAIGN_ID, SESSION_ID, body, TOKEN)
    await rollDeathSave(ROOM_ID, CAMPAIGN_ID, SESSION_ID, body, TOKEN)
    await rollConcentration(ROOM_ID, CAMPAIGN_ID, SESSION_ID, body, TOKEN)
    await rollSpecialAttack(ROOM_ID, CAMPAIGN_ID, SESSION_ID, body, TOKEN)
    const paths = [
      'saving-throws/roll',
      'death-saves/roll',
      'concentration/roll',
      'special-attacks/roll',
    ]
    paths.forEach((path, index) => {
      const [url, init] = fetchMock.mock.calls[index]
      expect(url).toBe(
        `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/${SESSION_ID}/combat/${path}`,
      )
      expect(init.method).toBe('POST')
      expect(init.headers.Authorization).toBe(`Bearer ${TOKEN}`)
      expect(JSON.parse(init.body as string)).toEqual(body)
    })
  })

  it('calls reaction window GET and resolve endpoints with expected request details', async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok({}))
    vi.stubGlobal('fetch', fetchMock)
    await getReactionWindow(ROOM_ID, CAMPAIGN_ID, SESSION_ID, 'entry-1', TOKEN)
    const [getUrl, getInit] = fetchMock.mock.calls[0]
    expect(getUrl).toBe(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/${SESSION_ID}/combat/entries/entry-1/reaction`,
    )
    expect(getInit.method).toBeUndefined()
    expect(getInit.headers.Authorization).toBe(`Bearer ${TOKEN}`)
    const body = {
      owner_entry_id: 'entry-1',
      actor_entry_id: 'entry-2',
      accept: true,
      idempotency_key: 'reaction-1',
    }
    await resolveReaction(ROOM_ID, CAMPAIGN_ID, SESSION_ID, body, TOKEN)
    const [resolveUrl, resolveInit] = fetchMock.mock.calls[1]
    expect(resolveUrl).toBe(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/${SESSION_ID}/combat/reactions/resolve`,
    )
    expect(resolveInit.method).toBe('POST')
    expect(resolveInit.headers.Authorization).toBe(`Bearer ${TOKEN}`)
    expect(JSON.parse(resolveInit.body as string)).toEqual(body)
  })

  it('calls special-attack request and adjudicate endpoints with expected request details', async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok({}))
    vi.stubGlobal('fetch', fetchMock)
    const requestBody = {
      attacker_entry_id: 'entry-1',
      target_entry_id: 'entry-2',
      kind: 'grapple' as const,
      attacker_modifier_mode: 'advantage' as const,
      defender_modifier_mode: 'normal' as const,
      idempotency_key: 'special-request-1',
    }
    await requestSpecialAttack(ROOM_ID, CAMPAIGN_ID, SESSION_ID, requestBody, TOKEN)
    const [requestUrl, requestInit] = fetchMock.mock.calls[0]
    expect(requestUrl).toBe(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/${SESSION_ID}/combat/special-attacks/request`,
    )
    expect(requestInit.method).toBe('POST')
    expect(requestInit.headers.Authorization).toBe(`Bearer ${TOKEN}`)
    expect(JSON.parse(requestInit.body as string)).toEqual(requestBody)
    const adjudicateBody = {
      action_id: 'special-action-1',
      in_reach: true,
      idempotency_key: 'special-adjudicate-1',
    }
    await adjudicateSpecialAttack(ROOM_ID, CAMPAIGN_ID, SESSION_ID, adjudicateBody, TOKEN)
    const [adjudicateUrl, adjudicateInit] = fetchMock.mock.calls[1]
    expect(adjudicateUrl).toBe(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/${SESSION_ID}/combat/special-attacks/adjudicate`,
    )
    expect(adjudicateInit.method).toBe('POST')
    expect(adjudicateInit.headers.Authorization).toBe(`Bearer ${TOKEN}`)
    expect(JSON.parse(adjudicateInit.body as string)).toEqual(adjudicateBody)
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
    expect(fetchMock.mock.calls[0][0]).toBe(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/${SESSION_ID}/combat/attacks/adjudicate`,
    )
    await listAdjudications(ROOM_ID, CAMPAIGN_ID, SESSION_ID, TOKEN)
    expect(fetchMock.mock.calls[1][0]).toBe(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/${SESSION_ID}/combat/adjudications`,
    )
    await resolveAdjudication(
      ROOM_ID,
      CAMPAIGN_ID,
      SESSION_ID,
      'action-2',
      { trigger: true, ruling: 'The reaction triggers', idempotency_key: 'resolve-1' },
      TOKEN,
    )
    expect(fetchMock.mock.calls[2][0]).toBe(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/${SESSION_ID}/combat/adjudications/action-2/resolve`,
    )
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
    expect(fetchMock.mock.calls[0][0]).toBe(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/${SESSION_ID}/combat/adjudications/opportunity-attack`,
    )
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
    expect(fetchMock.mock.calls[1][0]).toBe(
      `/api/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/sessions/${SESSION_ID}/combat/adjudications/special`,
    )
  })
})