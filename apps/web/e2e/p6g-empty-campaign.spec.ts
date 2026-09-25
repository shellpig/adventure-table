import { expect, test } from './support/roomTest'
import {
  addPlayerSeat,
  addQuickEnemy,
  addSeat,
  advanceUntilTurn,
  combatantCard,
  combatantOf,
  combatStage,
  createCampaign,
  endCombat,
  enterAsMember,
  entryNamed,
  importCharacter,
  initiativeRow,
  json,
  openSessionAs,
  playerAttack,
  readDetail,
  responseJson,
  startSession,
  type AttackResolution,
  type CombatDetail,
  type Lobby,
} from './support/quickCombat'

type RuntimeEntry = {
  id: string
  kind: string
  title: string | null
  body: string | null
  visibility: string
  dm_notes?: string | null
  revision: number
  [key: string]: unknown
}

type TableEvent = {
  seq: number
  kind: string
  acting_seat_id: string | null
  subject_seat_id: string | null
  payload: Record<string, unknown>
}

type EventPage = {
  events: TableEvent[]
}

type RollRequest = {
  id: string
  target_seat_id: string
  dc: number | null
  status: 'pending' | 'resolved' | 'cancelled'
}

type RequestCheckResponse = {
  roll_group_id: string
  requests: RollRequest[]
}

type RollResult = {
  id: string
  roll_request_id: string | null
  raw_dice: number[]
  kept_dice: number[]
  base_modifier: number
  flat_adjustment: number
  total: number
}

type RollSubmission = {
  result_id: string
  roll_request_id: string | null
  hidden: boolean
  result: RollResult | null
}

type RuntimeContext = {
  current_situation: string | null
  current_adventure_scene_entry_id: string | null
  current_runtime_scene_entry_id: string | null
  revision: number
}

type SessionHistoryLink = {
  session_id: string
  previous_session: { id: string; status: string } | null
  previous_last_event_seq: number
}

type MonsterInstance = {
  id: string
  name: string
  current_hp: number | null
  max_hp: number | null
}

test('P6-G G1b-2: empty Campaign through narration, combat, Current Situation, and next Session continuity', async ({
  browser,
  page,
  request,
  roomContext,
}) => {
  test.setTimeout(300_000)
  const { roomId } = roomContext

  // 1. Campaign with ZERO attached Adventures
  const campaign = await createCampaign(request, roomId, 'P6-G Empty Campaign')
  const attachedAdventures = await json<unknown[]>(
    await request.get(`/api/rooms/${roomId}/campaigns/${campaign.id}/adventures`),
  )
  expect(attachedAdventures).toEqual([])

  // 2. DM Seat and Player Seat with Character
  const lobby = await json<Lobby>(
    await request.get(`/api/rooms/${roomId}/campaigns/${campaign.id}/lobby`),
  )
  expect(lobby.caller_access_session_id).not.toBeNull()
  await addSeat(request, roomId, campaign.id, 'dm', lobby.caller_access_session_id!, 'P6-G DM')

  const playerGrant = await enterAsMember(request, roomContext, 'P6-G Player')
  const character = await importCharacter(request)
  const playerSeat = await addPlayerSeat(
    request,
    roomId,
    campaign.id,
    character,
    playerGrant.access_session_id,
    'P6-G Player',
  )

  // 3. Start Session through official UI
  const sessionId = await startSession(page, roomId, campaign.id)
  const sessionUrl = `/rooms/${roomId}/campaigns/${campaign.id}/sessions/${sessionId}`
  const activePrefix = `/api/rooms/${roomId}/campaigns/${campaign.id}/sessions/${sessionId}`

  const player = await openSessionAs(browser, playerGrant, roomContext, sessionUrl)

  try {
    // Assert initial layout & secrecy:
    // DM sees session-world-panel; Player sees session-journal-panel and NOT session-world-panel
    const worldPanel = page.locator('.session-world-panel')
    await expect(worldPanel).toBeVisible()
    await expect(page.locator('.session-journal-panel')).toHaveCount(0)

    const journalPanel = player.page.locator('.session-journal-panel')
    await expect(journalPanel).toBeVisible()
    await expect(player.page.locator('.session-world-panel')).toHaveCount(0)
    await expect(player.page.getByRole('button', { name: 'Quick Add' })).toHaveCount(0)

    // 4. DM narration through UI
    const NARRATION_TEXT = 'The sun sets behind the craggy ridge as darkness settles over the empty hills.'
    await page.getByRole('combobox', { name: 'Type', exact: true }).selectOption('narration')
    await page.getByPlaceholder(/Type here/).fill(NARRATION_TEXT)
    const narrationPromise = page.waitForResponse(
      (resp) => resp.request().method() === 'POST' && resp.url().includes(`/sessions/${sessionId}/exploration`),
    )
    await page.getByRole('button', { name: 'Send' }).click()
    await responseJson(await narrationPromise)

    await expect(page.getByText(NARRATION_TEXT, { exact: true })).toBeVisible()
    await expect(player.page.getByText(NARRATION_TEXT, { exact: true })).toBeVisible()

    // 5. Quick Add NPC and Fact through production UI
    // 5a. Quick Add NPC
    await worldPanel.getByRole('button', { name: 'Quick Add' }).click()
    const npcForm = worldPanel.locator('form')
    await expect(npcForm).toBeVisible()
    await npcForm.getByRole('combobox', { name: 'Kind', exact: true }).selectOption('npc')
    await npcForm.getByRole('textbox', { name: 'Title / Name' }).fill('Old Ben')
    await npcForm.getByRole('textbox', { name: 'Description / Body' }).fill('A wandering hermit who knows the hills.')
    await npcForm.getByRole('textbox', { name: 'DM Notes' }).fill('Secretly a retired ranger spying on goblin bands.')
    const npcCreatedPromise = page.waitForResponse(
      (resp) => resp.request().method() === 'POST' && resp.url().endsWith(`/sessions/${sessionId}/runtime/entries`),
    )
    await npcForm.getByRole('button', { name: 'Create Entry' }).click()
    await responseJson(await npcCreatedPromise)

    // Verify NPC appears in DM's panel
    await expect(worldPanel).toContainText('Old Ben')

    // 5b. Quick Add Fact
    await worldPanel.getByRole('button', { name: 'Quick Add' }).click()
    const factForm = worldPanel.locator('form')
    await expect(factForm).toBeVisible()
    await factForm.getByRole('combobox', { name: 'Kind', exact: true }).selectOption('fact')
    const FACT_TITLE = 'Night Moors'
    const FACT_TEXT = 'A cold wind carries the distant howl of wolves.'
    await factForm.getByRole('textbox', { name: 'Title / Name' }).fill(FACT_TITLE)
    await factForm.getByRole('textbox', { name: 'Description / Body' }).fill(FACT_TEXT)
    const factCreatedPromise = page.waitForResponse(
      (resp) => resp.request().method() === 'POST' && resp.url().endsWith(`/sessions/${sessionId}/runtime/entries`),
    )
    await factForm.getByRole('button', { name: 'Create Entry' }).click()
    await responseJson(await factCreatedPromise)

    // Verify Fact in DM panel and Player Journal
    await expect(worldPanel).toContainText(FACT_TITLE)
    await expect(journalPanel).toContainText(FACT_TEXT)

    // Player secrecy assertions:
    // Player does NOT see DM Notes in Journal or anywhere in DOM
    await expect(player.page.locator('body')).not.toContainText('Secretly a retired ranger')

    // Direct Adventure read check:
    // UI: player navigating to adventures page gets permission denied
    const playerAdventuresPage = await player.context.newPage()
    await playerAdventuresPage.goto(`/rooms/${roomId}/adventures`)
    await expect(playerAdventuresPage.getByText('Only the Room owner or DM can manage Adventures.')).toBeVisible()
    await playerAdventuresPage.close()

    // API: player direct read to /adventures is 404
    const playerDirectAdventuresResp = await request.get(`/api/rooms/${roomId}/adventures`, {
      headers: { Authorization: `Bearer ${playerGrant.access_token}` },
    })
    expect(playerDirectAdventuresResp.status()).toBe(404)

    // 6. Player exploration action through UI
    await player.page.getByRole('combobox', { name: 'Type', exact: true }).selectOption('action')
    await player.page.getByRole('combobox', { name: 'Character', exact: true }).selectOption(playerSeat.id)
    const ACTION_TEXT = 'I listen intently to identify how close the howling is.'
    await player.page.getByPlaceholder(/Type here/).fill(ACTION_TEXT)
    const actionPromise = player.page.waitForResponse(
      (resp) => resp.request().method() === 'POST' && resp.url().includes(`/sessions/${sessionId}/exploration`),
    )
    await player.page.getByRole('button', { name: 'Send' }).click()
    await responseJson(await actionPromise)

    await expect(page.getByText(ACTION_TEXT, { exact: true })).toBeVisible()
    await expect(player.page.getByText(ACTION_TEXT, { exact: true })).toBeVisible()

    // 7. DM formal Request Check
    await page.getByRole('button', { name: 'Dice', exact: true }).click()
    const targetCheckbox = page.getByRole('checkbox', { name: new RegExp(character.name) })
    await expect(targetCheckbox).toBeChecked()
    await page.getByRole('combobox', { name: 'Check type' }).selectOption('skill')
    await page.getByRole('combobox', { name: 'Skill' }).selectOption('srd5.1:skill:perception')
    await page.getByLabel('DC (optional)', { exact: true }).fill('12')
    await page.getByRole('combobox', { name: 'Roll mode' }).selectOption('normal')
    await page.getByRole('combobox', { name: 'Result visibility' }).selectOption('public')
    await page.getByLabel('Label', { exact: true }).fill('Listen for wolves')

    const checkPromise = page.waitForResponse(
      (resp) => resp.request().method() === 'POST' && resp.url().includes(`/sessions/${sessionId}/checks`),
    )
    await page.getByRole('button', { name: 'Create Check' }).click()
    const checkResponse = await responseJson<RequestCheckResponse>(await checkPromise)
    expect(checkResponse.requests).toHaveLength(1)
    const rollRequestId = checkResponse.requests[0].id
    expect(checkResponse.requests[0]).toMatchObject({
      target_seat_id: playerSeat.id,
      dc: 12,
      status: 'pending',
    })

    const rollPrompt = `The DM asks ${character.name} to make Perception (Skill Check): Listen for wolves.`
    await expect(player.page.getByText(rollPrompt, { exact: true })).toBeVisible()

    // DM sees pending request with DC 12
    const dmRequestCard = page.locator('.session-roll-request').first()
    await expect(dmRequestCard).toHaveAttribute('data-roll-request-status', 'pending')
    await expect(dmRequestCard.getByText('DC 12', { exact: true })).toBeVisible()

    // 8. Player completes roll
    await player.page.getByRole('button', { name: 'Dice', exact: true }).click()
    const playerRequestCard = player.page.locator('.session-roll-request').first()
    await expect(playerRequestCard).toHaveAttribute('data-roll-request-status', 'pending')
    await expect(playerRequestCard.getByText('Waiting to roll', { exact: true })).toBeVisible()
    // Player does NOT see DC (secrecy)
    await expect(playerRequestCard.getByText('DC 12', { exact: true })).toHaveCount(0)

    const rollPromise = player.page.waitForResponse(
      (resp) => resp.request().method() === 'POST' && resp.url().includes(`/sessions/${sessionId}/rolls/formal`),
    )
    await playerRequestCard.getByRole('button', { name: 'Roll formally' }).click()
    const rollSubmission = await responseJson<RollSubmission>(await rollPromise)
    expect(rollSubmission.roll_request_id).toBe(rollRequestId)
    expect(rollSubmission.result).not.toBeNull()
    expect(rollSubmission.result!.raw_dice).toHaveLength(1)
    expect(rollSubmission.result!.raw_dice[0]).toBeGreaterThanOrEqual(1)
    expect(rollSubmission.result!.raw_dice[0]).toBeLessThanOrEqual(20)

    // Player and DM see resolved status
    await expect(playerRequestCard).toHaveAttribute('data-roll-request-status', 'resolved')
    await expect(dmRequestCard).toHaveAttribute('data-roll-request-status', 'resolved')

    // 9. Assert persisted AT events & Runtime state
    // Check persisted events via API
    const eventPage = await json<EventPage>(
      await request.get(`${activePrefix}/events?after=0&limit=100`),
    )
    const eventKinds = eventPage.events.map((e) => e.kind)
    expect(eventKinds).toContain('exploration.narration')
    expect(eventKinds).toContain('world.entry.created')
    expect(eventKinds).toContain('exploration.action')
    expect(eventKinds).toContain('roll.requested')
    expect(eventKinds).toContain('roll.resolved')

    const narrationEvent = eventPage.events.find((e) => e.kind === 'exploration.narration')!
    expect(narrationEvent.payload.text).toBe(NARRATION_TEXT)

    const actionEvent = eventPage.events.find((e) => e.kind === 'exploration.action')!
    expect(actionEvent.payload.text).toBe(ACTION_TEXT)
    const speakerSeat = actionEvent.acting_seat_id ?? actionEvent.subject_seat_id
    expect(speakerSeat).toBe(playerSeat.id)

    // Check persisted Runtime state
    const dmEntries = await json<RuntimeEntry[]>(
      await request.get(`${activePrefix}/runtime/entries`),
    )
    expect(dmEntries.length).toBeGreaterThanOrEqual(2)
    const npcEntry = dmEntries.find((e) => e.kind === 'npc')
    expect(npcEntry).toBeDefined()
    expect(npcEntry!.title).toBe('Old Ben')
    expect(npcEntry!.dm_notes).toBe('Secretly a retired ranger spying on goblin bands.')

    const factEntry = dmEntries.find((e) => e.kind === 'fact')
    expect(factEntry).toBeDefined()
    expect(factEntry!.title).toBe(FACT_TITLE)
    expect(factEntry!.body).toBe(FACT_TEXT)

    // Check player-scoped runtime entries projection
    const playerEntries = await json<RuntimeEntry[]>(
      await request.get(`${activePrefix}/runtime/entries`, {
        headers: { Authorization: `Bearer ${playerGrant.access_token}` },
      }),
    )
    for (const entry of playerEntries) {
      expect(entry).not.toHaveProperty('dm_notes')
      expect(entry).not.toHaveProperty('character_recipient_ids')
      expect(entry).not.toHaveProperty('needs_review')
      expect(entry).not.toHaveProperty('provenance_json')
    }

    // 10. Quick Combat: DM starts combat, Player lacks start combat button
    await expect(player.page.getByRole('button', { name: 'Start Combat' })).toHaveCount(0)
    await page.getByRole('button', { name: 'Start Combat' }).click()
    await expect(combatStage(page)).toBeVisible()
    await expect(combatStage(player.page)).toBeVisible()

    let detail = await readDetail(request, activePrefix)
    expect(detail.status).toBe('initiative_pending')
    const heroEntry = entryNamed(detail, character.name)
    expect(heroEntry.character_id).toBe(character.id)
    await expect(initiativeRow(page, heroEntry.id)).toContainText(character.name)
    await expect(initiativeRow(player.page, heroEntry.id)).toContainText(character.name)

    // 11. Add legal Quick Enemy: Player lacks enemy addition controls; DM specifies AC 1 for deterministic attack
    await expect(player.page.getByRole('button', { name: 'Quick Enemy' })).toHaveCount(0)
    await expect(player.page.getByRole('button', { name: 'Add to Combat' })).toHaveCount(0)
    await expect(player.page.getByRole('combobox', { name: 'Choose Monster' })).toHaveCount(0)

    const QUICK_ENEMY = { name: 'Moor Bandit', ac: 1, maxHp: 30, positionNote: 'Behind the crag' }
    await addQuickEnemy(page, QUICK_ENEMY)

    await expect(page.locator('.session-combat__initiative-row', { hasText: QUICK_ENEMY.name })).toBeVisible()
    await expect(player.page.locator('.session-combat__initiative-row', { hasText: QUICK_ENEMY.name })).toBeVisible()

    detail = await readDetail(request, activePrefix)
    expect(detail.entries).toHaveLength(2)
    const enemyEntry = entryNamed(detail, QUICK_ENEMY.name)
    expect(combatantOf(detail, enemyEntry.id).projection.armor_class).toBe(QUICK_ENEMY.ac)
    await expect(combatantCard(page, enemyEntry.id)).toContainText(`Position Note:${QUICK_ENEMY.positionNote}`)

    // 12. Initiative: DM requests, Player rolls own initiative, DM rolls enemy, DM finalizes
    await expect(player.page.getByRole('button', { name: 'Request Initiative' })).toHaveCount(0)
    await expect(player.page.getByRole('button', { name: 'Finalize Initiative' })).toHaveCount(0)

    await page.getByRole('button', { name: 'Request Initiative' }).click()
    const playerInitiativeButton = initiativeRow(player.page, heroEntry.id).getByRole('button', {
      name: 'Roll Initiative',
    })
    await expect(playerInitiativeButton).toBeVisible()
    await expect(initiativeRow(player.page, enemyEntry.id).getByRole('button')).toHaveCount(0)
    await playerInitiativeButton.click()
    await expect(initiativeRow(player.page, heroEntry.id).locator('.session-combat__initiative-total')).toBeVisible()

    await initiativeRow(page, enemyEntry.id).getByRole('button', { name: 'Roll Initiative' }).click()
    await expect(initiativeRow(page, enemyEntry.id).locator('.session-combat__initiative-total')).toBeVisible()

    await page.getByRole('button', { name: 'Finalize Initiative' }).click()
    await expect(combatStage(page).locator('.session-combat__round-badge')).toHaveText('Round 1')
    await expect(combatStage(player.page).locator('.session-combat__round-badge')).toHaveText('Round 1')
    detail = await readDetail(request, activePrefix)
    expect(detail.status).toBe('running')

    // 13. Enemy secrecy: Player sees no exact HP/AC in UI or API; DM sees full projection
    await expect(combatantCard(player.page, enemyEntry.id)).toHaveAttribute('data-hostile', 'true')
    await expect(combatantCard(player.page, enemyEntry.id)).not.toContainText('HP:')
    await expect(combatantCard(player.page, enemyEntry.id)).not.toContainText('AC:')
    await expect(combatantCard(page, enemyEntry.id)).toContainText('HP:')
    await expect(combatantCard(page, enemyEntry.id)).toContainText('AC:')

    const playerCombatDetail = await json<CombatDetail>(
      await request.get(`${activePrefix}/combat/detail`, {
        headers: { Authorization: `Bearer ${playerGrant.access_token}` },
      }),
    )
    const playerEnemyCombatant = combatantOf(playerCombatDetail, enemyEntry.id)
    expect(playerEnemyCombatant.projection.current_hp ?? null).toBeNull()
    expect(playerEnemyCombatant.projection.armor_class ?? null).toBeNull()

    // 14. Resolve attack causing actual HP damage via official playerAttack helper
    const MAX_ATTACK_ROUNDS = 6
    let resolution: AttackResolution | null = null
    for (let round = 0; round < MAX_ATTACK_ROUNDS && !resolution?.hit; round += 1) {
      await advanceUntilTurn(page, request, activePrefix, heroEntry.id)
      await expect(combatStage(player.page).locator('.session-combat__your-turn-badge')).toBeVisible()
      resolution = await playerAttack(page, player.page, sessionId, QUICK_ENEMY.name)
    }
    expect(resolution?.hit, 'attack should hit bandit with AC 1').toBe(true)
    const hit = resolution!
    expect(hit.damage_total).toBeGreaterThan(0)
    expect(hit.after_hp ?? null).toBeNull()

    await expect(player.page.locator('[data-attack-result="true"]')).toContainText(`Damage ${hit.damage_total}`)
    await expect(player.page.locator('[data-attack-result="true"]')).not.toContainText('HP:')

    // Assert Player cannot access DM-only adjudication
    await expect(player.page.locator('[data-adjudication-id]')).toHaveCount(0)
    const rejectedAdjudicate = await request.post(`${activePrefix}/combat/attacks/adjudicate`, {
      headers: { Authorization: `Bearer ${playerGrant.access_token}` },
      data: {
        action_id: '00000000-0000-0000-0000-000000000001',
        in_range: true,
      },
    })
    expect(rejectedAdjudicate.status()).toBe(403)

    const rejectedResolve = await request.post(
      `${activePrefix}/combat/adjudications/00000000-0000-0000-0000-000000000001/resolve`,
      {
        headers: { Authorization: `Bearer ${playerGrant.access_token}` },
        data: { trigger: true },
      },
    )
    expect(rejectedResolve.status()).toBe(403)

    // Verify persisted combat resolution and enemy HP reduction via real API
    detail = await readDetail(request, activePrefix)
    const enemyAfter = combatantOf(detail, enemyEntry.id).projection
    expect(enemyAfter.current_hp).toBe(QUICK_ENEMY.maxHp - hit.damage_total)
    await expect(combatantCard(page, enemyEntry.id)).toContainText(`HP:${enemyAfter.current_hp}/${QUICK_ENEMY.maxHp}`)
    await expect(combatantCard(player.page, enemyEntry.id)).not.toContainText('HP:')

    // Verify Player Character Current State via real API (hero was not attacked, stays at 12 HP)
    const heroSheet = await json<{ current_hp: number; max_hp: number }>(
      await request.get(`/api/characters/${character.id}/sheet`),
    )
    expect(heroSheet.current_hp).toBe(12)
    expect(heroSheet.max_hp).toBe(12)

    // Verify attack roll resolution event persistence and secrecy
    const combatEvents = await json<EventPage>(
      await request.get(`${activePrefix}/events?after=0&limit=100`),
    )
    const dmAttackEvent = combatEvents.events.find(
      (e) => e.kind === 'roll.resolved' && Boolean(e.payload.attack_resolution),
    )
    expect(dmAttackEvent).toBeDefined()
    const dmResolution = dmAttackEvent!.payload.attack_resolution as {
      attack: { target_ac: number }
      damage: { adjusted_total: number; after: { current_hp: number } }
    }
    expect(dmResolution.attack.target_ac).toBe(QUICK_ENEMY.ac)
    expect(dmResolution.damage.adjusted_total).toBe(hit.damage_total)
    expect(dmResolution.damage.after.current_hp).toBe(QUICK_ENEMY.maxHp - hit.damage_total)

    const playerCombatEvents = await json<EventPage>(
      await request.get(`${activePrefix}/events?after=0&limit=100`, {
        headers: { Authorization: `Bearer ${playerGrant.access_token}` },
      }),
    )
    const playerAttackEvent = playerCombatEvents.events.find(
      (e) => e.kind === 'roll.resolved' && Boolean(e.payload.attack_resolution),
    )
    expect(playerAttackEvent).toBeDefined()
    const playerResolution = playerAttackEvent!.payload.attack_resolution as {
      attack: Record<string, unknown>
      damage: Record<string, unknown>
    }
    expect(playerResolution.attack).not.toHaveProperty('target_ac')
    expect(playerResolution.damage).not.toHaveProperty('before')
    expect(playerResolution.damage).not.toHaveProperty('after')
    expect(playerResolution.damage).not.toHaveProperty('before_hp')
    expect(playerResolution.damage).not.toHaveProperty('after_hp')

    // 15. End Combat: Player cannot end combat; DM ends combat, stage cleared and state persisted
    await expect(player.page.getByRole('button', { name: 'End Combat' })).toHaveCount(0)
    const rejectedEndCombat = await request.post(`${activePrefix}/combat/end`, {
      headers: { Authorization: `Bearer ${playerGrant.access_token}` },
      data: {},
    })
    expect(rejectedEndCombat.status()).toBe(403)

    const endView = await endCombat(page, sessionId)
    expect(endView.status).toBe('ended')
    expect(endView.round_number).toBeNull()
    expect(endView.current_turn_entry_id).toBeNull()

    await expect(combatStage(page)).toHaveCount(0)
    await expect(combatStage(player.page)).toHaveCount(0)

    // Verify active combat is now null via real API
    const endedDetail = await json<CombatDetail | null>(
      await request.get(`${activePrefix}/combat/detail`),
    )
    expect(endedDetail).toBeNull()

    // Verify combat.ended event is persisted in table events
    const finalEvents = await json<EventPage>(
      await request.get(`${activePrefix}/events?after=0&limit=100`),
    )
    const finalEventKinds = finalEvents.events.map((e) => e.kind)
    expect(finalEventKinds).toContain('combat.ended')

    // Verify Character Current State still persists after combat end
    const postCombatSheet = await json<{ current_hp: number; max_hp: number }>(
      await request.get(`/api/characters/${character.id}/sheet`),
    )
    expect(postCombatSheet.current_hp).toBe(12)
    expect(postCombatSheet.max_hp).toBe(12)

    // 16. In the SAME empty Campaign and still-active first Session:
    // Update Current Situation via official DM UI
    const contextCard = worldPanel.locator('.runtime-context-card')
    await contextCard.getByRole('button', { name: 'Edit Context' }).click()
    const CURRENT_SITUATION_TEXT =
      'The bandit threat is neutralized; the party catches their breath as dawn breaks over the moor.'
    await contextCard.getByRole('textbox', { name: 'Current Situation' }).fill(CURRENT_SITUATION_TEXT)
    const contextUpdatedPromise = page.waitForResponse(
      (resp) => resp.request().method() === 'PATCH' && resp.url().endsWith(`/sessions/${sessionId}/runtime/context`),
    )
    await contextCard.getByRole('button', { name: 'Save Context' }).click()
    await responseJson(await contextUpdatedPromise)
    await expect(contextCard).toContainText(CURRENT_SITUATION_TEXT)

    // Add persistent post-combat Fact via official DM UI
    await worldPanel.getByRole('button', { name: 'Quick Add' }).click()
    const aftermathFactForm = worldPanel.locator('form')
    await expect(aftermathFactForm).toBeVisible()
    await aftermathFactForm.getByRole('combobox', { name: 'Kind', exact: true }).selectOption('fact')
    const AFTERMATH_FACT_TITLE = 'Bandit Trail Cleared'
    const AFTERMATH_FACT_BODY = 'The solitary bandit was driven off; the mountain path is secure for now.'
    await aftermathFactForm.getByRole('textbox', { name: 'Title / Name' }).fill(AFTERMATH_FACT_TITLE)
    await aftermathFactForm.getByRole('textbox', { name: 'Description / Body' }).fill(AFTERMATH_FACT_BODY)
    const aftermathFactPromise = page.waitForResponse(
      (resp) => resp.request().method() === 'POST' && resp.url().endsWith(`/sessions/${sessionId}/runtime/entries`),
    )
    await aftermathFactForm.getByRole('button', { name: 'Create Entry' }).click()
    await responseJson(await aftermathFactPromise)

    await expect(worldPanel).toContainText(AFTERMATH_FACT_TITLE)
    await expect(journalPanel).toContainText(AFTERMATH_FACT_BODY)

    // Verify persisted runtime state via API before End Session
    const session1Context = await json<RuntimeContext>(
      await request.get(`${activePrefix}/runtime/context`),
    )
    expect(session1Context.current_situation).toBe(CURRENT_SITUATION_TEXT)

    // 17. End first Session via official UI
    page.once('dialog', (dialog) => dialog.accept())
    const endSessionPromise = page.waitForResponse(
      (resp) => resp.request().method() === 'POST' && resp.url().includes(`/sessions/${sessionId}/end`),
    )
    await page.getByRole('button', { name: 'End Session' }).click()
    await responseJson(await endSessionPromise)
    await expect(page.getByText('Ended', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'End Session' })).toHaveCount(0)

    // 18. Return to Lobby via official UI link, verify Seat lifecycle, and start second Session
    await page.getByRole('link', { name: 'Back to Lobby' }).click()
    await expect(page.getByRole('heading', { name: 'Lobby & Seats', level: 1 })).toBeVisible()

    // Verify DM Seat and Player Seat with Character persist in Lobby
    const dmSeatCard = page.locator('article').filter({ hasText: 'P6-G DM' })
    await expect(dmSeatCard).toBeVisible()
    const playerSeatCard = page.locator('article').filter({ hasText: 'P6-G Player' })
    await expect(playerSeatCard).toBeVisible()
    await expect(playerSeatCard).toContainText(character.name)

    // Start second Session via official UI
    await page.getByRole('button', { name: 'Start Session' }).click()
    await expect(page).toHaveURL(
      new RegExp(`/rooms/${roomId}/campaigns/${campaign.id}/sessions/[0-9a-fA-F-]{36}/?$`),
    )
    await expect(page.getByRole('heading', { name: 'Active Session', level: 1 })).toBeVisible()

    const nextSessionMatch = page.url().match(/\/sessions\/([0-9a-fA-F-]{36})/)
    expect(nextSessionMatch).not.toBeNull()
    const nextSessionId = nextSessionMatch![1]
    expect(nextSessionId).not.toBe(sessionId)
    const nextSessionUrl = `/rooms/${roomId}/campaigns/${campaign.id}/sessions/${nextSessionId}`
    const nextActivePrefix = `/api/rooms/${roomId}/campaigns/${campaign.id}/sessions/${nextSessionId}`

    // 19. Assert prior NPC / Fact / Current Situation in second Session
    const nextWorldPanel = page.locator('.session-world-panel')
    await expect(nextWorldPanel).toBeVisible()
    await expect(nextWorldPanel).toContainText('Old Ben')
    await expect(nextWorldPanel).toContainText(FACT_TITLE)
    await expect(nextWorldPanel).toContainText(AFTERMATH_FACT_TITLE)
    const nextContextCard = nextWorldPanel.locator('.runtime-context-card')
    await expect(nextContextCard).toContainText(CURRENT_SITUATION_TEXT)

    const nextContext = await json<RuntimeContext>(
      await request.get(`${nextActivePrefix}/runtime/context`),
    )
    expect(nextContext.current_situation).toBe(CURRENT_SITUATION_TEXT)
    expect(nextContext.current_adventure_scene_entry_id).toBeNull()
    expect(nextContext.current_runtime_scene_entry_id).toBeNull()

    const nextDmEntries = await json<RuntimeEntry[]>(
      await request.get(`${nextActivePrefix}/runtime/entries`),
    )
    const nextNpc = nextDmEntries.find((e) => e.kind === 'npc' && e.title === 'Old Ben')
    expect(nextNpc).toBeDefined()
    expect(nextNpc!.dm_notes).toBe('Secretly a retired ranger spying on goblin bands.')

    const nextFact = nextDmEntries.find((e) => e.kind === 'fact' && e.title === FACT_TITLE)
    expect(nextFact).toBeDefined()
    expect(nextFact!.body).toBe(FACT_TEXT)

    const nextAftermathFact = nextDmEntries.find((e) => e.kind === 'fact' && e.title === AFTERMATH_FACT_TITLE)
    expect(nextAftermathFact).toBeDefined()
    expect(nextAftermathFact!.body).toBe(AFTERMATH_FACT_BODY)

    // 20. Assert Character Current State remains true across Session boundary
    const nextHeroSheet = await json<{ current_hp: number; max_hp: number }>(
      await request.get(`/api/characters/${character.id}/sheet`),
    )
    expect(nextHeroSheet.current_hp).toBe(12)
    expect(nextHeroSheet.max_hp).toBe(12)

    // 21. Check absence of active Combat after End, while ended Combat outcome remains inspectable
    await expect(combatStage(page)).toHaveCount(0)
    const nextCombatDetail = await json<CombatDetail | null>(
      await request.get(`${nextActivePrefix}/combat/detail`),
    )
    expect(nextCombatDetail).toBeNull()

    const nextCombat = await json<CombatDetail | null>(
      await request.get(`${nextActivePrefix}/combat`),
    )
    expect(nextCombat).toBeNull()

    // Recorded ended Combat/outcome remains inspectable via correct existing read surfaces:
    // a) Previous Session link on the new active Session
    const prevLink = await json<SessionHistoryLink>(
      await request.get(`${nextActivePrefix}/previous`),
    )
    expect(prevLink.previous_session).not.toBeNull()
    expect(prevLink.previous_session!.id).toBe(sessionId)
    expect(prevLink.previous_session!.status).toBe('ended')

    // b) Ended Session's recorded monster instance reflects post-combat damaged HP outcome
    const prevMonsters = await json<MonsterInstance[]>(
      await request.get(`/api/rooms/${roomId}/campaigns/${campaign.id}/sessions/${sessionId}/monster-instances`),
    )
    const recordedBandit = prevMonsters.find((m) => m.name === QUICK_ENEMY.name)
    expect(recordedBandit).toBeDefined()
    expect(recordedBandit!.current_hp).toBe(QUICK_ENEMY.maxHp - hit.damage_total)

    // c) Ended Session's persisted event sequence includes combat.ended and world.context_changed
    const prevSessionEvents = await json<EventPage>(
      await request.get(`${activePrefix}/events?after=0&limit=100`),
    )
    expect(prevSessionEvents.events.map((e) => e.kind)).toContain('combat.ended')
    expect(prevSessionEvents.events.map((e) => e.kind)).toContain('world.context_changed')

    // Secrecy: Player does not see world.context_changed event in event stream
    const playerPrevEvents = await json<EventPage>(
      await request.get(`${activePrefix}/events?after=0&limit=100`, {
        headers: { Authorization: `Bearer ${playerGrant.access_token}` },
      }),
    )
    expect(playerPrevEvents.events.map((e) => e.kind)).not.toContain('world.context_changed')

    // 22. Campaign remains at zero attached Adventures and no mandatory Scene/Quest
    const nextAttachedAdventures = await json<unknown[]>(
      await request.get(`/api/rooms/${roomId}/campaigns/${campaign.id}/adventures`),
    )
    expect(nextAttachedAdventures).toEqual([])
    expect(nextContext.current_adventure_scene_entry_id).toBeNull()
    expect(nextContext.current_runtime_scene_entry_id).toBeNull()

    // 23. Reconnect Player page to next Session and assert secret filtering
    await player.page.goto(nextSessionUrl)
    await expect(player.page.getByRole('heading', { name: 'Active Session', level: 1 })).toBeVisible()

    const nextJournalPanel = player.page.locator('.session-journal-panel')
    await expect(nextJournalPanel).toBeVisible()
    await expect(player.page.locator('.session-world-panel')).toHaveCount(0)
    await expect(player.page.getByRole('button', { name: 'Quick Add' })).toHaveCount(0)
    await expect(player.page.getByRole('button', { name: 'Start Combat' })).toHaveCount(0)
    await expect(combatStage(player.page)).toHaveCount(0)

    // Player sees public facts in Journal
    await expect(nextJournalPanel).toContainText(FACT_TEXT)
    await expect(nextJournalPanel).toContainText(AFTERMATH_FACT_BODY)

    // Secrecy: Player does NOT see NPC DM Notes anywhere in DOM
    await expect(player.page.locator('body')).not.toContainText('Secretly a retired ranger spying on goblin bands.')
    await expect(player.page.locator('body')).not.toContainText('Secretly a retired ranger')

    // Secrecy: Player projection via API has no secrets
    const playerNextEntries = await json<RuntimeEntry[]>(
      await request.get(`${nextActivePrefix}/runtime/entries`, {
        headers: { Authorization: `Bearer ${playerGrant.access_token}` },
      }),
    )
    for (const entry of playerNextEntries) {
      expect(entry).not.toHaveProperty('dm_notes')
      expect(entry).not.toHaveProperty('character_recipient_ids')
      expect(entry).not.toHaveProperty('needs_review')
      expect(entry).not.toHaveProperty('provenance_json')
    }

    // Secrecy: Direct Adventure read check remains forbidden
    const playerNextDirectAdventures = await request.get(`/api/rooms/${roomId}/adventures`, {
      headers: { Authorization: `Bearer ${playerGrant.access_token}` },
    })
    expect(playerNextDirectAdventures.status()).toBe(404)
  } finally {
    await player.context.close()
  }
})
