import { resolve } from 'node:path'

import { expect, test } from './support/roomTest'
import {
  addPlayerSeat,
  addSeat,
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
  startSession,
  type AttackResolution,
  type CombatAdjudication,
  type CombatDetail,
  type Lobby,
} from './support/quickCombat'
import { advanceTo, mapPanel, selectMatching } from './support/tactical'

const CASTER_FIXTURE = resolve(
  process.cwd(),
  '../server/tests/data/p5g/fixture_wizard5_fireball.json',
)

// Quick Enemy AC 1 keeps the attack loop short; only a natural 1 misses.
const QUICK_ENEMY = { name: 'Bandit Thug', ac: 1, maxHp: 30, positionNote: 'Behind the barrels' }
const SRD_MONSTER = 'Goblin'
const MAX_ATTACK_ROUNDS = 6

test('P4-E E.1 DM + Player Quick Combat journey with enemy secrecy and range adjudication', async ({
  browser,
  page,
  request,
  roomContext,
}) => {
  test.setTimeout(180_000)
  const playerGrant = await enterAsMember(request, roomContext, 'P4-E Player Controller')
  const character = await importCharacter(request)
  const caster = await importCharacter(request, CASTER_FIXTURE)
  const campaign = await createCampaign(request, roomContext.roomId, 'P4-E Quick Combat Journey')
  const ownerLobby = await json<Lobby>(await request.get(
    `/api/rooms/${roomContext.roomId}/campaigns/${campaign.id}/lobby`,
  ))
  expect(ownerLobby.caller_access_session_id).not.toBeNull()
  await addSeat(request, roomContext.roomId, campaign.id, 'dm', ownerLobby.caller_access_session_id!)
  await addPlayerSeat(
    request,
    roomContext.roomId,
    campaign.id,
    character,
    playerGrant.access_session_id,
  )
  await addPlayerSeat(
    request,
    roomContext.roomId,
    campaign.id,
    caster,
    playerGrant.access_session_id,
    'P4-E Caster',
  )

  const sessionId = await startSession(page, roomContext.roomId, campaign.id)
  const sessionUrl = `/rooms/${roomContext.roomId}/campaigns/${campaign.id}/sessions/${sessionId}`
  const prefix = `/api/rooms/${roomContext.roomId}/campaigns/${campaign.id}/sessions/${sessionId}`
  const playerHeaders = { Authorization: `Bearer ${playerGrant.access_token}` }
  const player = await openSessionAs(browser, playerGrant, roomContext, sessionUrl)
  const boardRequests: string[] = []
  const recordBoard = (req: { method(): string; url(): string }) => {
    if (req.url().includes('/combat/board')) {
      boardRequests.push(`${req.method()} ${req.url()}`)
    }
  }
  page.on('request', recordBoard)
  player.page.on('request', recordBoard)

  try {
    // 1 + 2. DM starts Combat from the Session toolbar; the Party is included automatically.
    await expect(player.page.getByRole('button', { name: 'Start Combat' })).toHaveCount(0)
    await page.getByRole('button', { name: 'Start Combat' }).click()
    await expect(combatStage(page)).toBeVisible()
    await expect(combatStage(player.page)).toBeVisible()
    let detail = await readDetail(request, prefix)
    const heroEntry = entryNamed(detail, character.name)
    const casterEntry = entryNamed(detail, caster.name)
    expect(heroEntry.character_id).toBe(character.id)
    expect(casterEntry.character_id).toBe(caster.id)
    await expect(initiativeRow(page, heroEntry.id)).toContainText(character.name)
    await expect(initiativeRow(player.page, heroEntry.id)).toContainText(character.name)
    await expect(initiativeRow(page, casterEntry.id)).toContainText(caster.name)
    await expect(initiativeRow(player.page, casterEntry.id)).toContainText(caster.name)

    // 3. One SRD Monster (no Position Note) and one Quick Enemy (with Position Note).
    await pickSrdMonster(page, SRD_MONSTER)
    await page.getByRole('button', { name: 'Add to Combat' }).click()
    await expect(page.locator('.session-combat__initiative-row', { hasText: SRD_MONSTER })).toBeVisible()
    await expect(player.page.locator('.session-combat__initiative-row', { hasText: SRD_MONSTER })).toBeVisible()

    await page.getByRole('button', { name: 'Quick Enemy' }).click()
    const quickForm = page.locator('.session-combat__add-enemy form')
    await quickForm.getByLabel('Name', { exact: true }).fill(QUICK_ENEMY.name)
    await quickForm.getByLabel('AC', { exact: true }).fill(String(QUICK_ENEMY.ac))
    await quickForm.getByLabel('Max HP', { exact: true }).fill(String(QUICK_ENEMY.maxHp))
    await quickForm.getByLabel('Position Note', { exact: true }).fill(QUICK_ENEMY.positionNote)
    await page.getByRole('button', { name: 'Add to Combat' }).click()
    await expect(page.locator('.session-combat__initiative-row', { hasText: QUICK_ENEMY.name })).toBeVisible()

    detail = await readDetail(request, prefix)
    expect(detail.entries).toHaveLength(4)
    const goblinEntry = entryNamed(detail, SRD_MONSTER)
    const thugEntry = entryNamed(detail, QUICK_ENEMY.name)

    // 9. Position Note is optional: the Goblin has none, the Thug shows it, nothing else changes.
    await expect(combatantCard(page, thugEntry.id)).toContainText(`Position Note:${QUICK_ENEMY.positionNote}`)
    await expect(combatantCard(page, goblinEntry.id)).not.toContainText('Position Note:')
    expect(combatantOf(detail, thugEntry.id).projection.armor_class).toBe(QUICK_ENEMY.ac)

    // Add an SRD Mage for AoE and OA coverage in the Quick journey.
    await page.getByRole('button', { name: 'SRD Monster' }).click()
    await pickSrdMonster(page, 'Mage')
    await page.getByRole('button', { name: 'Add to Combat' }).click()
    await expect(page.locator('.session-combat__initiative-row', { hasText: 'Mage' })).toBeVisible()
    await expect(player.page.locator('.session-combat__initiative-row', { hasText: 'Mage' })).toBeVisible()
    detail = await readDetail(request, prefix)
    expect(detail.entries).toHaveLength(5)
    const mageEntry = entryNamed(detail, 'Mage')

    // 4. Initiative: DM requests, Player rolls their own entry, DM rolls the monsters, DM finalizes.
    await page.getByRole('button', { name: 'Request Initiative' }).click()
    const playerInitiativeButton = initiativeRow(player.page, heroEntry.id).getByRole('button', {
      name: 'Roll Initiative',
    })
    await expect(playerInitiativeButton).toBeVisible()
    await expect(initiativeRow(player.page, goblinEntry.id).getByRole('button')).toHaveCount(0)
    await playerInitiativeButton.click()
    await expect(initiativeRow(player.page, heroEntry.id).locator('.session-combat__initiative-total')).toBeVisible()

    const casterInitiativeButton = initiativeRow(player.page, casterEntry.id).getByRole('button', {
      name: 'Roll Initiative',
    })
    await expect(casterInitiativeButton).toBeVisible()
    await casterInitiativeButton.click()
    await expect(initiativeRow(player.page, casterEntry.id).locator('.session-combat__initiative-total')).toBeVisible()

    for (const entryId of [goblinEntry.id, thugEntry.id, mageEntry.id]) {
      await initiativeRow(page, entryId).getByRole('button', { name: 'Roll Initiative' }).click()
      await expect(initiativeRow(page, entryId).locator('.session-combat__initiative-total')).toBeVisible()
    }
    await page.getByRole('button', { name: 'Finalize Initiative' }).click()
    await expect(combatStage(page).locator('.session-combat__round-badge')).toHaveText('Round 1')
    await expect(combatStage(player.page).locator('.session-combat__round-badge')).toHaveText('Round 1')

    // 7 + 8. Enemy secrecy: the Player sees no exact enemy HP / AC, the DM sees everything.
    for (const enemyId of [goblinEntry.id, thugEntry.id]) {
      await expect(combatantCard(player.page, enemyId)).toHaveAttribute('data-hostile', 'true')
      await expect(combatantCard(player.page, enemyId)).not.toContainText('HP:')
      await expect(combatantCard(player.page, enemyId)).not.toContainText('AC:')
      await expect(combatantCard(page, enemyId)).toContainText('HP:')
      await expect(combatantCard(page, enemyId)).toContainText('AC:')
    }
    await expect(combatantCard(player.page, heroEntry.id)).toContainText('HP:')
    const playerDetail = await json<CombatDetail>(await request.get(`${prefix}/combat/detail`, {
      headers: playerHeaders,
    }))
    for (const enemyId of [goblinEntry.id, thugEntry.id]) {
      const projection = combatantOf(playerDetail, enemyId).projection
      expect(projection.current_hp ?? null).toBeNull()
      expect(projection.armor_class ?? null).toBeNull()
    }

    // 5 + 6 + 10. Player attacks on their own turn through DM range adjudication until a hit lands.
    const readTurn = async () => (await readDetail(request, prefix)).current_turn_entry_id
    let resolution: AttackResolution | null = null
    for (let round = 0; round < MAX_ATTACK_ROUNDS && !(resolution?.hit); round += 1) {
      await advanceTo(page, readTurn, heroEntry.id, 12)
      await expect(combatStage(player.page).locator('.session-combat__your-turn-badge')).toBeVisible()
      resolution = await playerAttack(page, player.page, sessionId, QUICK_ENEMY.name)
    }
    expect(resolution?.hit, 'attack never hit within the round budget').toBe(true)
    const hit = resolution!
    expect(hit.after_hp ?? null).toBeNull()
    await expect(player.page.locator('[data-attack-result="true"]')).toContainText(`Damage ${hit.damage_total}`)
    await expect(player.page.locator('[data-attack-result="true"]')).not.toContainText('HP:')

    detail = await readDetail(request, prefix)
    const thugAfter = combatantOf(detail, thugEntry.id).projection
    expect(thugAfter.current_hp).toBe(QUICK_ENEMY.maxHp - hit.damage_total)
    await expect(combatantCard(page, thugEntry.id)).toContainText(`HP:${thugAfter.current_hp}/${QUICK_ENEMY.maxHp}`)
    await expect(combatantCard(player.page, thugEntry.id)).not.toContainText('HP:')

    // 6. The compact Log carries the same result on both sides, HP only for the DM.
    await page.getByRole('button', { name: 'Log', exact: true }).click()
    const dmLogLine = page.locator('.session-log p', { hasText: `Battleaxe · → ${QUICK_ENEMY.name}` }).last()
    await expect(dmLogLine).toContainText(`Damage ${hit.damage_total}`)
    await expect(dmLogLine).toContainText(`HP ${thugAfter.current_hp}/${QUICK_ENEMY.maxHp}`)
    await player.page.getByRole('button', { name: 'Log', exact: true }).click()
    const playerLogLine = player.page
      .locator('.session-log p', { hasText: `Battleaxe · → ${QUICK_ENEMY.name}` })
      .last()
    await expect(playerLogLine).toContainText(`Damage ${hit.damage_total}`)
    await expect(playerLogLine).not.toContainText('HP ')
    await expect(playerLogLine).not.toContainText('AC ')

    // 5. Off-turn: advance to an enemy turn; the action bar waits and the server refuses the attack without side effects.
    while ((await readTurn()) === heroEntry.id || (await readTurn()) === casterEntry.id) {
      const advanced = page.waitForResponse(
        (r) => r.request().method() === 'POST' && r.url().includes('/combat/turn/advance'),
      )
      await page.getByRole('button', { name: 'Advance Turn' }).click()
      const advancedRes = await advanced
      expect(advancedRes.ok(), await advancedRes.text()).toBe(true)
    }
    await expect(player.page.locator('[data-combat-action-bar="true"]')).toHaveAttribute(
      'data-combat-action-state',
      'waiting',
    )
    await expect(player.page.getByText(/^Waiting for .*'s turn$/)).toBeVisible()
    const heroAttacks = await json<Array<{ source_ref: string }>>(await request.get(
      `${prefix}/combat/entries/${heroEntry.id}/attacks`,
      { headers: playerHeaders },
    ))
    expect(heroAttacks.length).toBeGreaterThan(0)
    const rejected = await request.post(`${prefix}/combat/attacks/request`, {
      headers: playerHeaders,
      data: {
        attacker_entry_id: heroEntry.id,
        target_entry_id: goblinEntry.id,
        source_ref: heroAttacks[0].source_ref,
        modifier_mode: 'normal',
        idempotency_key: 'p4e-e2e-off-turn-attack',
      },
    })
    expect(rejected.status()).toBe(409)
    const adjudications = await json<CombatAdjudication[]>(await request.get(`${prefix}/combat/adjudications`))
    expect(adjudications).toHaveLength(0)

    // G.1 AoE with DM-selected targets: on the Caster's turn, Player proposes Fireball (AoE)
    // from the Player action bar, and DM confirms targets in the adjudication panel without any tactical map.
    await advanceTo(page, readTurn, casterEntry.id, 12)
    const playerActionBar = player.page.locator('[data-combat-action-bar="true"]')
    await expect(playerActionBar).toHaveAttribute('data-combat-action-state', 'ready')
    // The action bar re-renders for the Caster after the turn advances; wait for its own weapon first.
    await expect(playerActionBar.getByRole('combobox', { name: 'Attack', exact: true })).toContainText('Quarterstaff')
    await playerActionBar.getByRole('combobox', { name: 'Action kind' }).selectOption('spell')
    await selectMatching(playerActionBar.locator('select[data-combat-spell="true"]'), /Fireball/)
    const aoeProposed = player.page.waitForResponse((response) => (
      response.request().method() === 'POST' && response.url().includes('/spells/aoe/propose')
    ))
    await playerActionBar.getByRole('button', { name: 'Cast Spell' }).click()
    const proposal = await responseJson<{ action_id: string }>(await aoeProposed)

    // DM selects targets in the adjudication panel: uncheck Goblin and Mage, leaving Hero and Thug.
    const aoeAdjudication = page.locator(`[data-adjudication-id="${proposal.action_id}"]`)
    await expect(aoeAdjudication).toHaveAttribute('data-adjudication-kind', 'affected_targets')
    const heroCheckbox = aoeAdjudication.getByLabel(character.name, { exact: true })
    const goblinCheckbox = aoeAdjudication.getByLabel(SRD_MONSTER, { exact: true })
    const mageCheckbox = aoeAdjudication.getByLabel('Mage', { exact: true })
    const thugCheckbox = aoeAdjudication.getByLabel(QUICK_ENEMY.name, { exact: true })

    await expect(heroCheckbox).toBeChecked()
    await expect(goblinCheckbox).toBeChecked()
    await expect(mageCheckbox).toBeChecked()
    await expect(thugCheckbox).toBeChecked()

    await goblinCheckbox.uncheck()
    await mageCheckbox.uncheck()

    await expect(heroCheckbox).toBeChecked()
    await expect(goblinCheckbox).not.toBeChecked()
    await expect(mageCheckbox).not.toBeChecked()
    await expect(thugCheckbox).toBeChecked()

    const aoeResolved = page.waitForResponse((response) => (
      response.request().method() === 'POST' && response.url().includes('/spells/aoe/resolve')
    ))
    await aoeAdjudication.getByRole('button', { name: 'Resolve AoE' }).click()
    const aoeResolvedRes = await aoeResolved
    expect(aoeResolvedRes.ok(), await aoeResolvedRes.text()).toBe(true)
    const aoeResolution = await responseJson<{
      action_id: string
      combat_id: string
      caster_entry_id: string
      spell_ref: string
      status: string
      confirmed_target_ids: string[]
    }>(aoeResolvedRes)
    const resolvedTargets = aoeResolution.confirmed_target_ids.slice().sort()
    expect(resolvedTargets).toEqual([heroEntry.id, thugEntry.id].slice().sort())
    await expect(aoeAdjudication).toHaveCount(0)

    // AoE saving throws are resolved by the server as part of resolution; assert no pending rolls remain.
    await expect(player.page.locator('[data-pending-roll]')).toHaveCount(0)

    // G.1 OA triggered by the DM: Player requests OA against the moving Mage;
    // DM triggers it in adjudication, opening a reaction window that the Player resolves.
    const oaReq = await json<{ action_id: string }>(await request.post(
      `${prefix}/combat/adjudications/opportunity-attack`,
      {
        headers: playerHeaders,
        data: {
          mover_entry_id: mageEntry.id,
          reactor_entry_id: heroEntry.id,
          question: 'Mage moves away from Hero without disengaging, provoke OA?',
          idempotency_key: 'p4e-quick-oa-request',
        },
      },
    ))
    const oaAdjudication = page.locator(`[data-adjudication-id="${oaReq.action_id}"]`)
    await expect(oaAdjudication).toHaveAttribute('data-adjudication-kind', 'opportunity_attack')
    const oaTriggered = page.waitForResponse((response) => (
      response.request().method() === 'POST' && response.url().includes(`/adjudications/${oaReq.action_id}/resolve`)
    ))
    await oaAdjudication.getByRole('button', { name: 'Trigger', exact: true }).click()
    const oaTriggeredRes = await oaTriggered
    expect(oaTriggeredRes.ok(), await oaTriggeredRes.text()).toBe(true)
    await expect(oaAdjudication).toHaveCount(0)

    // The Player sees the reaction window in their action bar and declines it.
    const playerReactions = player.page.locator('[data-combat-reactions="true"]')
    await expect(playerReactions).toBeVisible()
    await expect(playerReactions).toContainText(/Opportunity [Aa]ttack/)
    const reactionDeclined = player.page.waitForResponse((response) => (
      response.request().method() === 'POST' && response.url().includes('/combat/reactions/resolve')
    ))
    await playerReactions.getByRole('button', { name: 'Decline' }).click()
    const reactionDeclinedRes = await reactionDeclined
    expect(reactionDeclinedRes.ok(), await reactionDeclinedRes.text()).toBe(true)
    await expect(playerReactions).toHaveCount(0)

    // Assert that throughout the Quick journey, Tactical map panel never renders
    // and no request was sent to any /combat/board route.
    await expect(mapPanel(page)).toHaveCount(0)
    await expect(mapPanel(player.page)).toHaveCount(0)
    expect(boardRequests).toEqual([])

    // End Combat clears the stage for both roles.
    page.once('dialog', (dialog) => dialog.accept())
    await page.getByRole('button', { name: 'End Combat' }).click()
    await expect(combatStage(page)).toHaveCount(0)
    await expect(combatStage(player.page)).toHaveCount(0)
    await expect(mapPanel(page)).toHaveCount(0)
    await expect(mapPanel(player.page)).toHaveCount(0)
    expect(boardRequests).toEqual([])
  } finally {
    await player.context.close()
  }
})
