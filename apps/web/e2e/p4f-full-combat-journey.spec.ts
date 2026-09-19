import { resolve } from 'node:path'

import { expect, test, type APIRequestContext, type Page } from './support/roomTest'
import {
  addPlayerSeat,
  addSeat,
  advanceUntilTurn,
  combatantCard,
  combatantOf,
  combatStage,
  createCampaign,
  enterAsMember,
  entryNamed,
  importCharacter,
  initiativeRow,
  json,
  openSessionAs,
  pickSrdMonster,
  playerAttack,
  readDetail,
  responseJson,
  restartE2EServer,
  startSession,
  type AttackResolution,
  type CombatAdjudication,
  type CombatDetail,
  type Lobby,
} from './support/quickCombat'

const MULTICLASS_FIXTURE = resolve(
  process.cwd(),
  '../server/tests/data/m03/fixture_multiclass_mixed.json',
)
const SRD_MONSTER = 'Goblin'
const QUICK_ENEMY = { name: 'Bandit Thug', ac: 1, maxHp: 1 }
const MAX_CONTEST_ROUNDS = 6
const MAX_ATTACK_ROUNDS = 6
const PRONE_REF = 'srd5.1:condition:prone'
const HERO_MAX_HP = 49
const HERO_START_HP = 30

type SpecialAttackRequestResponse = {
  action_id: string
  attacker_roll_request_id: string | null
}

type SpecialAttackRollResponse = {
  total: number
  status: string
}

type SpellCastResponse = {
  cast_mode: string
  status: string
  roll_request_id: string | null
}

type SavingThrowRequestResponse = {
  roll_group_id: string
  requests: Array<{
    id: string
    target_entry_id: string
    ability_ref: string
    dc: number | null
    status: string
  }>
}

type SavingThrowRollResponse = {
  total: number
  succeeded: boolean
}

type PendingRollItem = {
  id: string
  request_type: string
  target_entry_id: string
  dc: number | null
}

type CombatEndEntry = {
  id: string
  initiative_total: number | null
  turn_order: number | null
  action_available: boolean
  bonus_action_available: boolean
  reaction_available: boolean
  attacks_used: number
}

type CombatEndView = {
  id: string
  status: string
  round_number: number | null
  current_turn_entry_id: string | null
  entries: CombatEndEntry[]
}

type ResourceCounterView = {
  used: number
  remaining: number
}

type CharacterSheetSummary = {
  character_id: string
  current_hp: number
  spell_slots: Record<string, ResourceCounterView>
}

type CharacterExportDocument = {
  payload: {
    current_state: {
      state_payload: {
        concentration: Record<string, unknown> | null
      }
    }
  }
}

async function endFromSession(page: Page): Promise<void> {
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByRole('button', { name: 'End Session' }).click()
  await expect(page.getByText('Ended', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'End Session' })).toHaveCount(0)
}

async function dmAdvanceTurn(page: Page): Promise<void> {
  const advanced = page.waitForResponse((response) => (
    response.request().method() === 'POST' && response.url().includes('/combat/turn/advance')
  ))
  await page.getByRole('button', { name: 'Advance Turn' }).click()
  await responseJson(await advanced)
}

/**
 * Brings the turn back to the hero with a fresh Action: when the hero still holds the turn
 * after acting, the DM advances off it first so `advanceUntilTurn` cycles a full round.
 */
async function advanceToHeroTurn(
  page: Page,
  request: APIRequestContext,
  prefix: string,
  heroEntryId: string,
): Promise<void> {
  const detail = await readDetail(request, prefix)
  const hero = detail.entries.find((entry) => entry.id === heroEntryId)
  expect(hero, 'hero combat entry').toBeTruthy()
  const actionSpent = !hero!.action_available || hero!.attacks_used >= hero!.attacks_allowed
  if (detail.current_turn_entry_id === heroEntryId && actionSpent) {
    await dmAdvanceTurn(page)
  }
  await advanceUntilTurn(page, request, prefix, heroEntryId)
}

/**
 * Player declares Shove (prone) against targetEntryId; DM adjudicates reach; both roll.
 * Returns true if target entry has srd5.1:condition:prone applied.
 */
async function playerShoveProne(
  dm: Page,
  player: Page,
  request: APIRequestContext,
  prefix: string,
  sessionId: string,
  targetEntryId: string,
): Promise<boolean> {
  const actionBar = player.locator('[data-combat-action-bar="true"]')
  await expect(actionBar).toHaveAttribute('data-combat-action-state', 'ready')
  await actionBar.getByRole('combobox', { name: 'Action kind' }).selectOption('shove_prone')
  await actionBar.getByRole('combobox', { name: 'Target' }).selectOption(targetEntryId)

  const requested = player.waitForResponse((response) => (
    response.request().method() === 'POST'
    && response.url().includes(`/sessions/${sessionId}/combat/special-attacks/request`)
  ))
  await actionBar.getByRole('button', { name: 'Shove (prone)' }).click()
  const requestResult = await responseJson<SpecialAttackRequestResponse>(await requested)
  expect(requestResult.attacker_roll_request_id).toBeNull()
  await expect(actionBar).toHaveAttribute('data-combat-action-state', 'adjudication-pending')

  const adjudication = dm.locator(`[data-adjudication-id="${requestResult.action_id}"]`)
  await expect(adjudication).toHaveAttribute('data-adjudication-kind', 'reach')
  const adjudicated = dm.waitForResponse((response) => (
    response.request().method() === 'POST'
    && response.url().includes(`/sessions/${sessionId}/combat/special-attacks/adjudicate`)
  ))
  await adjudication.getByRole('button', { name: 'In reach' }).click()
  await responseJson(await adjudicated)
  await expect(adjudication).toHaveCount(0)

  // Player rolls hero's Athletics check
  const playerRollButton = actionBar.locator('[data-pending-roll]').first()
  await expect(playerRollButton).toBeVisible()
  const playerRolled = player.waitForResponse((response) => (
    response.request().method() === 'POST'
    && response.url().includes(`/sessions/${sessionId}/combat/special-attacks/roll`)
  ))
  await playerRollButton.click()
  await responseJson<SpecialAttackRollResponse>(await playerRolled)

  // DM rolls target monster's contest check
  const pendingRolls = await json<PendingRollItem[]>(await request.get(`${prefix}/combat/pending-rolls`))
  const monsterRoll = pendingRolls.find((roll) => roll.target_entry_id === targetEntryId)
  expect(monsterRoll).toBeTruthy()
  const dmRollButton = dm.locator(`[data-pending-roll="${monsterRoll!.id}"]`)
  await expect(dmRollButton).toBeVisible()
  const dmRolled = dm.waitForResponse((response) => (
    response.request().method() === 'POST'
    && response.url().includes(`/sessions/${sessionId}/combat/special-attacks/roll`)
  ))
  await dmRollButton.click()
  await responseJson<SpecialAttackRollResponse>(await dmRolled)

  const detail = await readDetail(request, prefix)
  return combatantOf(detail, targetEntryId).projection.conditions.includes(PRONE_REF)
}

/** Player casts a single-target spell on their own combatant from the action bar. */
async function playerCastOnSelf(
  player: Page,
  sessionId: string,
  spellLabel: string,
  heroEntryId: string,
): Promise<SpellCastResponse> {
  const actionBar = player.locator('[data-combat-action-bar="true"]')
  await expect(actionBar).toHaveAttribute('data-combat-action-state', 'ready')
  await actionBar.getByRole('combobox', { name: 'Action kind' }).selectOption('spell')
  await actionBar.locator('select[data-combat-spell="true"]').selectOption({ label: spellLabel })
  await actionBar.locator('select[data-combat-spell-target="true"]').selectOption(heroEntryId)
  const cast = player.waitForResponse((response) => (
    response.request().method() === 'POST'
    && response.url().includes(`/sessions/${sessionId}/combat/spells/cast`)
  ))
  await actionBar.getByRole('button', { name: 'Cast Spell' }).click()
  return responseJson<SpellCastResponse>(await cast)
}

test('P4-F F.2 full Quick Combat journey: condition, healing, concentration, save, 0 HP outcome', async ({
  browser,
  page,
  request,
  roomContext,
}) => {
  test.setTimeout(240_000)
  const playerGrant = await enterAsMember(request, roomContext, 'P4-F Player Controller')
  const character = await importCharacter(request, MULTICLASS_FIXTURE)
  await json(await request.patch(`/api/characters/${character.id}/state`, {
    data: { current_hp: HERO_START_HP },
  }))
  const campaign = await createCampaign(request, roomContext.roomId, 'P4-F Full Combat Journey')
  const ownerLobby = await json<Lobby>(await request.get(
    `/api/rooms/${roomContext.roomId}/campaigns/${campaign.id}/lobby`,
  ))
  expect(ownerLobby.caller_access_session_id).not.toBeNull()
  await addSeat(request, roomContext.roomId, campaign.id, 'dm', ownerLobby.caller_access_session_id!, 'P4-F')
  await addPlayerSeat(
    request,
    roomContext.roomId,
    campaign.id,
    character,
    playerGrant.access_session_id,
    'P4-F',
  )

  const sessionId = await startSession(page, roomContext.roomId, campaign.id)
  const sessionUrl = `/rooms/${roomContext.roomId}/campaigns/${campaign.id}/sessions/${sessionId}`
  const prefix = `/api/rooms/${roomContext.roomId}/campaigns/${campaign.id}/sessions/${sessionId}`
  const playerHeaders = { Authorization: `Bearer ${playerGrant.access_token}` }
  const player = await openSessionAs(browser, playerGrant, roomContext, sessionUrl)

  try {
    // 1. DM Start Combat; hero entry present on both pages. Add SRD Goblin and Quick Enemy.
    await expect(player.page.getByRole('button', { name: 'Start Combat' })).toHaveCount(0)
    await page.getByRole('button', { name: 'Start Combat' }).click()
    await expect(combatStage(page)).toBeVisible()
    await expect(combatStage(player.page)).toBeVisible()

    let detail = await readDetail(request, prefix)
    const heroEntry = entryNamed(detail, character.name)
    expect(heroEntry.character_id).toBe(character.id)
    await expect(initiativeRow(page, heroEntry.id)).toContainText(character.name)
    await expect(initiativeRow(player.page, heroEntry.id)).toContainText(character.name)

    await pickSrdMonster(page, SRD_MONSTER)
    await page.getByRole('button', { name: 'Add to Combat' }).click()
    await expect(page.locator('.session-combat__initiative-row', { hasText: SRD_MONSTER })).toBeVisible()
    await expect(player.page.locator('.session-combat__initiative-row', { hasText: SRD_MONSTER })).toBeVisible()

    await page.getByRole('button', { name: 'Quick Enemy' }).click()
    const quickForm = page.locator('.session-combat__add-enemy form')
    await quickForm.getByLabel('Name', { exact: true }).fill(QUICK_ENEMY.name)
    await quickForm.getByLabel('AC', { exact: true }).fill(String(QUICK_ENEMY.ac))
    await quickForm.getByLabel('Max HP', { exact: true }).fill(String(QUICK_ENEMY.maxHp))
    await page.getByRole('button', { name: 'Add to Combat' }).click()
    await expect(page.locator('.session-combat__initiative-row', { hasText: QUICK_ENEMY.name })).toBeVisible()

    detail = await readDetail(request, prefix)
    expect(detail.entries).toHaveLength(3)
    const goblinEntry = entryNamed(detail, SRD_MONSTER)
    const thugEntry = entryNamed(detail, QUICK_ENEMY.name)

    // 2. Initiative: DM requests, Player rolls hero, DM rolls monsters, DM finalizes.
    await page.getByRole('button', { name: 'Request Initiative' }).click()
    const playerInitiativeButton = initiativeRow(player.page, heroEntry.id).getByRole('button', {
      name: 'Roll Initiative',
    })
    await expect(playerInitiativeButton).toBeVisible()
    await expect(initiativeRow(player.page, goblinEntry.id).getByRole('button')).toHaveCount(0)
    await playerInitiativeButton.click()
    await expect(initiativeRow(player.page, heroEntry.id).locator('.session-combat__initiative-total')).toBeVisible()

    for (const entryId of [goblinEntry.id, thugEntry.id]) {
      await initiativeRow(page, entryId).getByRole('button', { name: 'Roll Initiative' }).click()
      await expect(initiativeRow(page, entryId).locator('.session-combat__initiative-total')).toBeVisible()
    }
    await page.getByRole('button', { name: 'Finalize Initiative' }).click()
    await expect(combatStage(page).locator('.session-combat__round-badge')).toHaveText('Round 1')
    await expect(combatStage(player.page).locator('.session-combat__round-badge')).toHaveText('Round 1')

    // 3. Secrecy baseline: Player cards have data-hostile and no HP/AC; Player detail API has null HP/AC.
    for (const enemyId of [goblinEntry.id, thugEntry.id]) {
      await expect(combatantCard(player.page, enemyId)).toHaveAttribute('data-hostile', 'true')
      await expect(combatantCard(player.page, enemyId)).not.toContainText('HP:')
      await expect(combatantCard(player.page, enemyId)).not.toContainText('AC:')
      await expect(combatantCard(page, enemyId)).toContainText('HP:')
      await expect(combatantCard(page, enemyId)).toContainText('AC:')
    }
    const playerDetailBaseline = await json<CombatDetail>(await request.get(`${prefix}/combat/detail`, {
      headers: playerHeaders,
    }))
    for (const enemyId of [goblinEntry.id, thugEntry.id]) {
      const projection = combatantOf(playerDetailBaseline, enemyId).projection
      expect(projection.current_hp ?? null).toBeNull()
      expect(projection.armor_class ?? null).toBeNull()
    }

    // 4. Condition via shove: Player selects shove_prone, DM confirms reach, contest rolls, verify prone.
    let shoveSucceeded = false
    for (let round = 0; round < MAX_CONTEST_ROUNDS && !shoveSucceeded; round += 1) {
      await advanceToHeroTurn(page, request, prefix, heroEntry.id)
      await expect(combatStage(player.page).locator('.session-combat__your-turn-badge')).toBeVisible()
      shoveSucceeded = await playerShoveProne(page, player.page, request, prefix, sessionId, goblinEntry.id)
    }
    expect(shoveSucceeded, 'shove prone contest never succeeded within round budget').toBe(true)
    // Prone is a public condition (P4-C 4.5): both the DM and the Player see the pill.
    await expect(combatantCard(page, goblinEntry.id).locator('.session-combat__condition-pill')).toContainText('prone')
    await expect(combatantCard(player.page, goblinEntry.id).locator('.session-combat__condition-pill')).toContainText('prone')
    const playerDetailProne = await json<CombatDetail>(await request.get(`${prefix}/combat/detail`, {
      headers: playerHeaders,
    }))
    expect(combatantOf(playerDetailProne, goblinEntry.id).projection.conditions).toContain(PRONE_REF)

    // 5. Healing: Player casts Cure Wounds on themself (F6a self-target); HP rises on the card.
    await advanceToHeroTurn(page, request, prefix, heroEntry.id)
    await expect(combatStage(player.page).locator('.session-combat__your-turn-badge')).toBeVisible()
    const healResult = await playerCastOnSelf(player.page, sessionId, 'Cure Wounds (Lv 1)', heroEntry.id)
    expect(healResult.cast_mode).toBe('heal')
    await expect(player.page.locator('[data-spell-result="true"]')).toBeVisible()

    detail = await readDetail(request, prefix)
    const heroAfterHeal = combatantOf(detail, heroEntry.id).projection
    expect(heroAfterHeal.current_hp).toBeGreaterThan(HERO_START_HP)
    expect(heroAfterHeal.current_hp).toBeLessThanOrEqual(HERO_MAX_HP)
    await expect(combatantCard(player.page, heroEntry.id)).toContainText(`HP:${heroAfterHeal.current_hp}/${HERO_MAX_HP}`)

    // 6. Concentration: Player casts Bless on themself; DM and Player detail both carry concentration.
    await advanceToHeroTurn(page, request, prefix, heroEntry.id)
    await expect(combatStage(player.page).locator('.session-combat__your-turn-badge')).toBeVisible()
    const blessResult = await playerCastOnSelf(player.page, sessionId, 'Bless (Lv 1)', heroEntry.id)
    expect(blessResult.cast_mode).toBe('utility')

    detail = await readDetail(request, prefix)
    expect(combatantOf(detail, heroEntry.id).projection.concentration ?? null).not.toBeNull()
    const playerDetailBless = await json<CombatDetail>(await request.get(`${prefix}/combat/detail`, {
      headers: playerHeaders,
    }))
    expect(combatantOf(playerDetailBless, heroEntry.id).projection.concentration ?? null).not.toBeNull()

    // 7. Saving throw: DM requests DEX save DC 5 on hero; Player rolls in browser; verify results.
    const saveRequest = await json<SavingThrowRequestResponse>(await request.post(
      `${prefix}/combat/saving-throws/request`,
      {
        data: {
          target_entry_ids: [heroEntry.id],
          ability_ref: 'dexterity',
          dc: 5,
          idempotency_key: 'p4f-e2e-dex-save',
        },
      },
    ))
    expect(saveRequest.requests).toHaveLength(1)
    const saveRollId = saveRequest.requests[0].id

    const saveRollButton = player.page.locator(`[data-pending-roll="${saveRollId}"]`)
    await expect(saveRollButton).toBeVisible()
    const saveRow = player.page.locator('.session-combat-actions__pending-roll-row', {
      has: saveRollButton,
    })
    // The DC stays with the DM (P4-E secrecy): the Player row names the save but never the number.
    await expect(saveRow).toContainText('dexterity')
    await expect(saveRow).not.toContainText('DC')
    const dmPendingSaves = await json<PendingRollItem[]>(await request.get(`${prefix}/combat/pending-rolls`))
    expect(dmPendingSaves.find((roll) => roll.id === saveRollId)?.dc).toBe(5)

    const saveRolled = player.page.waitForResponse((response) => (
      response.request().method() === 'POST'
      && response.url().includes(`/sessions/${sessionId}/combat/saving-throws/roll`)
    ))
    await saveRollButton.click()
    const saveResult = await responseJson<SavingThrowRollResponse>(await saveRolled)
    expect(typeof saveResult.total).toBe('number')
    expect(typeof saveResult.succeeded).toBe('boolean')
    await expect(player.page.locator('[data-roll-result="saving_throw"]')).toBeVisible()

    const pendingRollsAfterSave = await json<PendingRollItem[]>(await request.get(
      `${prefix}/combat/pending-rolls`,
    ))
    expect(pendingRollsAfterSave.some((roll) => roll.id === saveRollId)).toBe(false)
    const adjudications = await json<CombatAdjudication[]>(await request.get(
      `${prefix}/combat/adjudications`,
    ))
    expect(adjudications).toHaveLength(0)

    // 8. Damage + 0 HP: Attack loop until hit lands on Bandit Thug (1 HP); verify 0 HP and active status.
    let attackResolution: AttackResolution | null = null
    for (let round = 0; round < MAX_ATTACK_ROUNDS && !attackResolution?.hit; round += 1) {
      await advanceToHeroTurn(page, request, prefix, heroEntry.id)
      await expect(combatStage(player.page).locator('.session-combat__your-turn-badge')).toBeVisible()
      attackResolution = await playerAttack(page, player.page, sessionId, QUICK_ENEMY.name)
    }
    expect(attackResolution?.hit, 'attack against Bandit Thug never hit within round budget').toBe(true)
    const hit = attackResolution!
    expect(hit.after_hp ?? null).toBeNull()
    await expect(player.page.locator('[data-attack-result="true"]')).toContainText(`Damage ${hit.damage_total}`)
    await expect(player.page.locator('[data-attack-result="true"]')).not.toContainText('HP:')

    detail = await readDetail(request, prefix)
    const thugCombatant = combatantOf(detail, thugEntry.id)
    expect(thugCombatant.projection.current_hp).toBe(0)
    const thugEntryDetail = entryNamed(detail, QUICK_ENEMY.name)
    expect(thugEntryDetail.status).toBe('active')

    // 9. Outcome: Advance if monster holds turn; DM sets outcome surrendered; verify badges and log.
    if (detail.current_turn_entry_id === thugEntry.id) {
      await dmAdvanceTurn(page)
    }

    const thugControls = page.locator(`[data-monster-controls="${thugEntry.id}"]`)
    await thugControls.locator('select[data-monster-outcome]').selectOption('surrendered')
    const outcomeSubmitted = page.waitForResponse((response) => (
      response.request().method() === 'POST'
      && response.url().includes(`/combat/entries/${thugEntry.id}/outcome`)
    ))
    await thugControls.locator('[data-monster-outcome-submit]').click()
    await responseJson(await outcomeSubmitted)

    await expect(initiativeRow(page, thugEntry.id).locator('.session-combat__status-badge')).toHaveText('Surrendered')
    await expect(initiativeRow(player.page, thugEntry.id).locator('.session-combat__status-badge')).toHaveText('Surrendered')
    await expect(thugControls.locator('[data-monster-outcome]')).toHaveCount(0)
    await expect(thugControls.locator('[data-monster-visibility]')).toBeVisible()
    await expect(player.page.locator('[data-monster-controls]')).toHaveCount(0)

    await page.getByRole('button', { name: 'Log', exact: true }).click()
    const dmOutcomeLog = page.locator('.session-log p', { hasText: `${QUICK_ENEMY.name} · Surrendered` })
    await expect(dmOutcomeLog).toBeVisible()

    // 10. Off-turn secrecy re-check: Player detail API has no enemy HP/AC after damage and outcome.
    const playerDetailFinal = await json<CombatDetail>(await request.get(`${prefix}/combat/detail`, {
      headers: playerHeaders,
    }))
    for (const enemyId of [goblinEntry.id, thugEntry.id]) {
      const projection = combatantOf(playerDetailFinal, enemyId).projection
      expect(projection.current_hp ?? null).toBeNull()
      expect(projection.armor_class ?? null).toBeNull()
    }

    // 10a. Session boundary: End Session, Start Session on the same Campaign, the same Combat resumes.
    const detailBeforeSessionEnd = await readDetail(request, prefix)
    await endFromSession(page)
    const sessionId2 = await startSession(page, roomContext.roomId, campaign.id)
    const sessionUrl2 = `/rooms/${roomContext.roomId}/campaigns/${campaign.id}/sessions/${sessionId2}`
    const prefix2 = `/api/rooms/${roomContext.roomId}/campaigns/${campaign.id}/sessions/${sessionId2}`

    await player.page.goto(sessionUrl2)
    await expect(player.page.getByRole('heading', { name: 'Active Session', level: 1 })).toBeVisible()

    await expect(combatStage(page)).toBeVisible()
    await expect(combatStage(player.page)).toBeVisible()

    const detail2 = await readDetail(request, prefix2)
    expect(detail2.id).toBe(detailBeforeSessionEnd.id)
    expect(detail2.status).toBe('running')
    expect(detail2.round_number).toBe(detailBeforeSessionEnd.round_number)
    expect(detail2.current_turn_entry_id).toBe(detailBeforeSessionEnd.current_turn_entry_id)
    expect(detail2.entries).toHaveLength(3)
    expect(entryNamed(detail2, QUICK_ENEMY.name).status).toBe('surrendered')
    expect(combatantOf(detail2, goblinEntry.id).projection.conditions).toContain(PRONE_REF)

    await expect(combatantCard(page, goblinEntry.id).locator('.session-combat__condition-pill')).toContainText('prone')
    await expect(combatantCard(player.page, goblinEntry.id).locator('.session-combat__condition-pill')).toContainText('prone')
    await expect(initiativeRow(page, thugEntry.id).locator('.session-combat__status-badge')).toHaveText('Surrendered')
    await expect(initiativeRow(player.page, thugEntry.id).locator('.session-combat__status-badge')).toHaveText('Surrendered')

    for (const enemyId of [goblinEntry.id, thugEntry.id]) {
      await expect(combatantCard(player.page, enemyId)).not.toContainText('HP:')
      await expect(combatantCard(player.page, enemyId)).not.toContainText('AC:')
    }

    // 10b. Real backend process restart with a pending save: state intact, the save resolves exactly once.
    const restartSaveRequest = await json<SavingThrowRequestResponse>(await request.post(
      `${prefix2}/combat/saving-throws/request`,
      {
        data: {
          target_entry_ids: [heroEntry.id],
          ability_ref: 'wisdom',
          dc: 5,
          idempotency_key: 'p4f-e2e-restart-save',
        },
      },
    ))
    expect(restartSaveRequest.requests).toHaveLength(1)
    const restartSaveId = restartSaveRequest.requests[0].id

    const beforeRestart = await readDetail(request, prefix2)
    await restartE2EServer(request)

    await page.reload()
    await expect(page.getByRole('heading', { name: 'Active Session', level: 1 })).toBeVisible()
    await expect(combatStage(page)).toBeVisible()

    await player.page.reload()
    await expect(player.page.getByRole('heading', { name: 'Active Session', level: 1 })).toBeVisible()
    await expect(combatStage(player.page)).toBeVisible()

    const afterRestart = await readDetail(request, prefix2)
    expect(afterRestart.id).toBe(beforeRestart.id)
    expect(afterRestart.revision).toBe(beforeRestart.revision)
    expect(afterRestart.round_number).toBe(beforeRestart.round_number)
    expect(afterRestart.current_turn_entry_id).toBe(beforeRestart.current_turn_entry_id)
    expect(afterRestart.entries.map((entry) => [entry.id, entry.status])).toEqual(
      beforeRestart.entries.map((entry) => [entry.id, entry.status]),
    )

    const restartSaveButton = player.page.locator(`[data-pending-roll="${restartSaveId}"]`)
    await expect(restartSaveButton).toBeVisible()
    const restartSaveRolled = player.page.waitForResponse((response) => (
      response.request().method() === 'POST'
      && response.url().includes(`/sessions/${sessionId2}/combat/saving-throws/roll`)
    ))
    await restartSaveButton.click()
    const restartSaveResult = await responseJson<SavingThrowRollResponse>(await restartSaveRolled)
    expect(typeof restartSaveResult.total).toBe('number')
    expect(typeof restartSaveResult.succeeded).toBe('boolean')

    await expect(player.page.locator(`[data-pending-roll="${restartSaveId}"]`)).toHaveCount(0)
    const dmPendingRollsAfterRestart = await json<PendingRollItem[]>(await request.get(
      `${prefix2}/combat/pending-rolls`,
    ))
    expect(dmPendingRollsAfterRestart.some((roll) => roll.id === restartSaveId)).toBe(false)
    await expect(player.page.locator('[data-roll-result="saving_throw"]')).toBeVisible()

    // 11. End Combat: DM ends combat, verify CombatView cleanup fields on response.
    page.once('dialog', (dialog) => dialog.accept())
    const combatEnded = page.waitForResponse((response) => (
      response.request().method() === 'POST'
      && response.url().includes(`/sessions/${sessionId2}/combat/end`)
    ))
    await page.getByRole('button', { name: 'End Combat' }).click()
    const endView = await responseJson<CombatEndView>(await combatEnded)
    expect(endView.status).toBe('ended')
    expect(endView.round_number).toBeNull()
    expect(endView.current_turn_entry_id).toBeNull()
    expect(endView.entries.length).toBeGreaterThan(0)
    for (const entry of endView.entries) {
      expect(entry.initiative_total).toBeNull()
      expect(entry.turn_order).toBeNull()
      expect(entry.action_available).toBe(true)
      expect(entry.bonus_action_available).toBe(true)
      expect(entry.reaction_available).toBe(true)
      expect(entry.attacks_used).toBe(0)
    }

    // 12. Preserved state after End Combat: Character HP, spell slots, and concentration survive.
    const sheet = await json<CharacterSheetSummary>(
      await request.get(`/api/characters/${character.id}/sheet`),
    )
    expect(sheet.current_hp).toBe(heroAfterHeal.current_hp)
    expect(sheet.spell_slots['1']?.used).toBe(2)

    const exportDocument = await json<CharacterExportDocument>(
      await request.get(`/api/characters/${character.id}/export`),
    )
    expect(exportDocument.payload.current_state.state_payload.concentration).not.toBeNull()

    // 13. Both pages: combatStage count 0 and Player page shows no [data-monster-controls].
    await expect(combatStage(page)).toHaveCount(0)
    await expect(combatStage(player.page)).toHaveCount(0)
    await expect(player.page.locator('[data-monster-controls]')).toHaveCount(0)
  } finally {
    await player.context.close()
  }
})
