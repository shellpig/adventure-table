import { expect, test } from './support/roomTest'
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
  startSession,
  type AttackResolution,
  type CombatAdjudication,
  type CombatDetail,
  type Lobby,
} from './support/quickCombat'

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

  const sessionId = await startSession(page, roomContext.roomId, campaign.id)
  const sessionUrl = `/rooms/${roomContext.roomId}/campaigns/${campaign.id}/sessions/${sessionId}`
  const prefix = `/api/rooms/${roomContext.roomId}/campaigns/${campaign.id}/sessions/${sessionId}`
  const playerHeaders = { Authorization: `Bearer ${playerGrant.access_token}` }
  const player = await openSessionAs(browser, playerGrant, roomContext, sessionUrl)

  try {
    // 1 + 2. DM starts Combat from the Session toolbar; the Party is included automatically.
    await expect(player.page.getByRole('button', { name: 'Start Combat' })).toHaveCount(0)
    await page.getByRole('button', { name: 'Start Combat' }).click()
    await expect(combatStage(page)).toBeVisible()
    await expect(combatStage(player.page)).toBeVisible()
    let detail = await readDetail(request, prefix)
    const heroEntry = entryNamed(detail, character.name)
    expect(heroEntry.character_id).toBe(character.id)
    await expect(initiativeRow(page, heroEntry.id)).toContainText(character.name)
    await expect(initiativeRow(player.page, heroEntry.id)).toContainText(character.name)

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
    expect(detail.entries).toHaveLength(3)
    const goblinEntry = entryNamed(detail, SRD_MONSTER)
    const thugEntry = entryNamed(detail, QUICK_ENEMY.name)

    // 9. Position Note is optional: the Goblin has none, the Thug shows it, nothing else changes.
    await expect(combatantCard(page, thugEntry.id)).toContainText(`Position Note:${QUICK_ENEMY.positionNote}`)
    await expect(combatantCard(page, goblinEntry.id)).not.toContainText('Position Note:')
    expect(combatantOf(detail, thugEntry.id).projection.armor_class).toBe(QUICK_ENEMY.ac)

    // 4. Initiative: DM requests, Player rolls their own entry, DM rolls the monsters, DM finalizes.
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
    let resolution: AttackResolution | null = null
    for (let round = 0; round < MAX_ATTACK_ROUNDS && !(resolution?.hit); round += 1) {
      await advanceUntilTurn(page, request, prefix, heroEntry.id)
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

    // 5. Off-turn: the action bar waits and the server refuses the attack without side effects.
    await page.getByRole('button', { name: 'Advance Turn' }).click()
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

    // End Combat clears the stage for both roles.
    page.once('dialog', (dialog) => dialog.accept())
    await page.getByRole('button', { name: 'End Combat' }).click()
    await expect(combatStage(page)).toHaveCount(0)
    await expect(combatStage(player.page)).toHaveCount(0)
  } finally {
    await player.context.close()
  }
})
