import { resolve } from 'node:path'

import { expect, test, type Page } from './support/roomTest'
import {
  addPlayerSeat,
  addSeat,
  combatStage,
  createCampaign,
  enterAsMember,
  entryNamed,
  importCharacter,
  initiativeRow,
  json,
  openSessionAs,
  readDetail,
  responseJson,
  startSession,
  type CombatDetail,
  type Lobby,
} from './support/quickCombat'

import {
  advanceTo,
  cell,
  mapPanel,
  selectMatching,
  token,
  type Board,
  type MonsterInstance,
} from './support/tactical'

// Coordinates on the 25x15 tactical map
const HERO_START = { x: 1, y: 1 }
const CASTER_START = { x: 1, y: 2 }
const HERO_DIAG_1 = { x: 2, y: 2 }
const HERO_DIAG_2 = { x: 3, y: 3 }
const DIFFICULT_TERRAIN_CELL = { x: 4, y: 3 }
const THUG_START = { x: 3, y: 4 }
const THUG_PUSHED = { x: 3, y: 5 }
const GOBLIN_AT = { x: 5, y: 3 }
const MAGE_AT = { x: 10, y: 3 }
const OGRE_AT = { x: 22, y: 3 }
const STALKER_AT = { x: 20, y: 12 }

const CASTER_FIXTURE = resolve(
  process.cwd(),
  '../server/tests/data/p5g/fixture_wizard5_fireball.json',
)

const QUICK_ENEMY = { name: 'Bandit Thug', ac: 11, maxHp: 25 }

async function endFromSession(page: Page): Promise<void> {
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByRole('button', { name: 'End Session' }).click()
  await expect(page.getByText('Ended', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'End Session' })).toHaveCount(0)
}

test.use({ actionTimeout: 15_000 })

test('P5-G G.2 Tactical Combat full browser journey', async ({
  browser,
  page,
  request,
  roomContext,
}) => {
  test.setTimeout(300_000)

  // 1. Setup Room, Character, Campaign, and Seats
  const playerGrant = await enterAsMember(request, roomContext, 'P5-G Player')
  const character = await importCharacter(request)
  const caster = await importCharacter(request, CASTER_FIXTURE)
  const campaign = await createCampaign(request, roomContext.roomId, 'P5-G Tactical Full Journey')
  const ownerLobby = await json<Lobby>(await request.get(
    `/api/rooms/${roomContext.roomId}/campaigns/${campaign.id}/lobby`,
  ))
  await addSeat(request, roomContext.roomId, campaign.id, 'dm', ownerLobby.caller_access_session_id!)
  await addPlayerSeat(request, roomContext.roomId, campaign.id, character, playerGrant.access_session_id)
  await addPlayerSeat(request, roomContext.roomId, campaign.id, caster, playerGrant.access_session_id, 'P5-G Caster')

  // 2. Create Battle Map with Difficult Terrain and a Wall
  const mapsUrl = `/api/rooms/${roomContext.roomId}/battle-maps`
  const battleMap = await json<{ id: string; revision: number }>(await request.post(mapsUrl, {
    data: { name: 'P5-G Proving Grounds', source_kind: 'blank', width_cells: 25, height_cells: 15 },
  }))
  await json(await request.put(`${mapsUrl}/${battleMap.id}/objects`, {
    data: {
      expected_revision: battleMap.revision,
      walls: [{ x1: 8, y1: 9, x2: 8, y2: 12, visibility: 'public' }],
      terrain: [{ x: DIFFICULT_TERRAIN_CELL.x, y: DIFFICULT_TERRAIN_CELL.y, terrain_kind: 'difficult' }],
    },
  }))

  // 3. Start Session and open Player browser context
  const sessionId = await startSession(page, roomContext.roomId, campaign.id)
  const sessionUrl = `/rooms/${roomContext.roomId}/campaigns/${campaign.id}/sessions/${sessionId}`
  const prefix = `/api/rooms/${roomContext.roomId}/campaigns/${campaign.id}/sessions/${sessionId}`
  const playerHeaders = { Authorization: `Bearer ${playerGrant.access_token}` }
  const player = await openSessionAs(browser, playerGrant, roomContext, sessionUrl)

  const playerBoardResponses: string[] = []
  player.page.on('response', async (response) => {
    if (response.request().method() === 'GET' && /\/combat\/board$/.test(new URL(response.url()).pathname)) {
      playerBoardResponses.push(await response.text())
    }
  })

  const readBoard = async (headers?: Record<string, string>) =>
    json<Board>(await request.get(`${prefix}/combat/board`, headers ? { headers } : undefined))

  const positionOf = async (entryId: string) => {
    const board = await readBoard()
    const pos = board.positions.find((item) => item.entry_id === entryId)
    expect(pos).toBeDefined()
    return { x: pos!.anchor_x, y: pos!.anchor_y }
  }

  try {
    // 4. DM starts Tactical Combat from the Session toolbar
    await expect(player.page.getByTestId('tactical-start-open')).toHaveCount(0)
    await page.getByTestId('tactical-start-open').click()
    await page.getByTestId(`tactical-map-${battleMap.id}`).getByRole('radio').check()
    await page.getByTestId('tactical-start-confirm').click()

    await expect(mapPanel(page)).toBeVisible()
    await expect(mapPanel(player.page)).toBeVisible()
    await expect(page.getByRole('button', { name: 'Request Initiative' })).toBeVisible()

    let detail = await readDetail(request, prefix)
    const heroEntry = entryNamed(detail, character.name)
    const casterEntry = entryNamed(detail, caster.name)

    // G.2 item 1: an SRD Monster (from-content) and a Quick Enemy in the same Tactical combat
    // G.2 item 2: at least one Large token placed and visible with its footprint (Ogre is Large)
    // G.2 item 10: a hidden entity (Hidden Stalker) absent from Player DOM and board payload
    const ogre = await json<MonsterInstance>(await request.post(`${prefix}/monster-instances/from-content`, {
      data: { content_key: 'srd5.1:monster:ogre' },
    }))
    const goblin = await json<MonsterInstance>(await request.post(`${prefix}/monster-instances/from-content`, {
      data: { content_key: 'srd5.1:monster:goblin' },
    }))
    const mage = await json<MonsterInstance>(await request.post(`${prefix}/monster-instances/from-content`, {
      data: { content_key: 'srd5.1:monster:mage' },
    }))
    const thug = await json<MonsterInstance>(await request.post(`${prefix}/monster-instances/quick-enemy`, {
      data: { name: QUICK_ENEMY.name, armor_class: QUICK_ENEMY.ac, max_hp: QUICK_ENEMY.maxHp },
    }))
    const stalker = await json<MonsterInstance>(await request.post(`${prefix}/monster-instances/quick-enemy`, {
      data: { name: 'Hidden Stalker', armor_class: 13, max_hp: 20, visibility: 'hidden' },
    }))

    for (const instance of [ogre, goblin, mage, thug, stalker]) {
      const added = await request.post(`${prefix}/combat/entries/monsters`, {
        data: { monster_instance_id: instance.id },
      })
      expect(added.ok()).toBe(true)
    }

    detail = await readDetail(request, prefix)
    expect(detail.entries).toHaveLength(7)
    const ogreEntry = entryNamed(detail, 'Ogre')
    const goblinEntry = entryNamed(detail, 'Goblin')
    const mageEntry = entryNamed(detail, 'Mage')
    const thugEntry = entryNamed(detail, QUICK_ENEMY.name)
    const stalkerEntry = entryNamed(detail, 'Hidden Stalker')

    // 5. Placement: Hero through DM map UI, caster & monsters through REST
    await mapPanel(page).getByTestId(`tactical-place-${heroEntry.id}`).click()
    await cell(page, HERO_START).click()
    await expect(token(page, heroEntry.id)).toBeVisible()

    for (const [entryId, at] of [
      [casterEntry.id, CASTER_START],
      [ogreEntry.id, OGRE_AT],
      [goblinEntry.id, GOBLIN_AT],
      [mageEntry.id, MAGE_AT],
      [thugEntry.id, THUG_START],
      [stalkerEntry.id, STALKER_AT],
    ] as const) {
      const placed = await request.put(`${prefix}/combat/board/positions/${entryId}`, {
        data: { anchor_x: at.x, anchor_y: at.y },
      })
      expect(placed.ok()).toBe(true)
    }

    // G.2 item 2 assert: Large token footprint (Ogre is 2x2: width 80px, height 80px)
    const boardInitial = await readBoard()
    const ogrePosition = boardInitial.positions.find((p) => p.entry_id === ogreEntry.id)
    expect(ogrePosition).toBeDefined()
    expect(ogrePosition!.footprint_width).toBe(2)
    expect(ogrePosition!.footprint_height).toBe(2)
    await expect(token(page, ogreEntry.id).locator('rect')).toHaveAttribute('width', '80')
    await expect(token(page, ogreEntry.id).locator('rect')).toHaveAttribute('height', '80')
    await expect(token(player.page, ogreEntry.id).locator('rect')).toHaveAttribute('width', '80')
    await expect(token(player.page, ogreEntry.id).locator('rect')).toHaveAttribute('height', '80')

    // G.2 item 10 assert: hidden entity absent from Player DOM and Player board payload
    await expect(token(page, stalkerEntry.id)).toBeVisible()
    await expect(token(player.page, stalkerEntry.id)).toHaveCount(0)
    expect(playerBoardResponses.length).toBeGreaterThan(0)
    for (const body of playerBoardResponses) expect(body).not.toContain(stalkerEntry.id)
    expect(JSON.stringify(await readBoard(playerHeaders))).not.toContain(stalkerEntry.id)

    // 6. Initiative: Player rolls hero & caster, DM rolls monsters and finalizes
    await page.getByRole('button', { name: 'Request Initiative' }).click()
    await initiativeRow(player.page, heroEntry.id).getByRole('button', { name: 'Roll Initiative' }).click()
    await initiativeRow(player.page, casterEntry.id).getByRole('button', { name: 'Roll Initiative' }).click()
    for (const entryId of [ogreEntry.id, goblinEntry.id, mageEntry.id, thugEntry.id, stalkerEntry.id]) {
      await initiativeRow(page, entryId).getByRole('button', { name: 'Roll Initiative' }).click()
      await expect(initiativeRow(page, entryId).locator('.session-combat__initiative-total')).toBeVisible()
    }
    await page.getByRole('button', { name: 'Finalize Initiative' }).click()

    const readTurn = async () => (await readDetail(request, prefix)).current_turn_entry_id
    await advanceTo(page, readTurn, heroEntry.id, 12)

    // G.2 item 3: normal and diagonal movement with 5/10 diagonal cost shown in preview
    const movement = mapPanel(player.page).getByTestId('tactical-movement')
    await token(player.page, heroEntry.id).click()
    await cell(player.page, HERO_DIAG_1).click() // 1st diagonal: 5 ft
    await cell(player.page, HERO_DIAG_2).click() // 2nd diagonal: 10 ft -> total 15 ft
    await expect(movement.getByTestId('tactical-move-used')).toContainText('15')
    await expect(movement.getByTestId('tactical-move-remaining')).toContainText('15')

    // Confirm Move 1: Hero commits to (3, 3)
    await movement.getByTestId('tactical-move-confirm').click()
    await expect.poll(() => positionOf(heroEntry.id)).toEqual(HERO_DIAG_2)
    expect(await positionOf(heroEntry.id)).toEqual(HERO_DIAG_2)

    // G.2 item 9: Shove through the action bar with the resulting board state visible
    const actionBar = player.page.locator('[data-combat-action-bar="true"]')
    await actionBar.getByRole('combobox', { name: 'Action kind' }).selectOption('shove_push')
    await actionBar.getByRole('combobox', { name: 'Target' }).selectOption(thugEntry.id)
    await actionBar.getByRole('combobox', { name: 'Roll mode' }).selectOption('advantage')

    const shoveRequested = player.page.waitForResponse((r) => (
      r.request().method() === 'POST' && r.url().includes('/combat/special-attacks/request')
    ))
    await actionBar.getByRole('button', { name: 'Shove (push)' }).click()
    const shoveRes = await responseJson<{ action_id: string }>(await shoveRequested)

    // DM adjudicates reach
    const shoveAdj = page.locator(`[data-adjudication-id="${shoveRes.action_id}"]`)
    await expect(shoveAdj).toHaveAttribute('data-adjudication-kind', 'reach')
    const adjudicated = page.waitForResponse((r) => (
      r.request().method() === 'POST' && r.url().includes('/combat/special-attacks/adjudicate')
    ))
    await shoveAdj.getByRole('button', { name: 'In reach' }).click()
    const adjRes = await adjudicated
    expect(adjRes.ok(), await adjRes.text()).toBe(true)

    // Player rolls hero's Athletics check with advantage
    const playerRoll = actionBar.locator('[data-pending-roll]').first()
    await expect(playerRoll).toBeVisible()
    const playerRollId = await playerRoll.getAttribute('data-pending-roll')
    expect(playerRollId).toBeTruthy()
    const playerRolled = player.page.waitForResponse((r) => (
      r.request().method() === 'POST' && r.url().includes('/combat/special-attacks/roll')
    ))
    await playerRoll.click()
    const playerRolledRes = await playerRolled
    expect(playerRolledRes.ok(), await playerRolledRes.text()).toBe(true)

    // DM rolls Thug's contest check
    await expect(page.locator(`[data-pending-roll="${playerRollId}"]`)).toHaveCount(0)
    const dmRoll = page.locator(`[data-pending-roll]:not([data-pending-roll="${playerRollId}"])`).first()
    await expect(dmRoll).toBeVisible()
    const dmRolled = page.waitForResponse((r) => (
      r.request().method() === 'POST' && r.url().includes('/combat/special-attacks/roll')
    ))
    await dmRoll.click()
    const dmRolledRes = await dmRolled
    const dmRolledBody = await dmRolledRes.text()
    expect(dmRolledRes.ok(), dmRolledBody).toBe(true)
    // SpecialAttackView.resolution_result (server contest outcome). The contest is Server RNG,
    // so the board must match whichever side won: success pushes 5 ft, a loss or tie leaves it.
    const shove = JSON.parse(dmRolledBody) as {
      status: string
      resolution_result: { status: string; attacker_total: number; target_total: number; push_distance_ft: number | null }
    }
    expect(shove.status).toBe('resolved')
    const shoveWon = shove.resolution_result.status === 'success'
    expect(shoveWon).toBe(shove.resolution_result.attacker_total > shove.resolution_result.target_total)

    // Resulting board state: on success Bandit Thug is pushed 5 ft from (3, 4) to (3, 5)
    const thugExpected = shoveWon ? THUG_PUSHED : THUG_START
    await expect.poll(() => positionOf(thugEntry.id)).toEqual(thugExpected)
    expect(await positionOf(thugEntry.id)).toEqual(thugExpected)
    if (!shoveWon) {
      // A lost contest leaves the Thug next to the Hero's later path, which would add an extra OA.
      // The DM corrects its position through the formal reposition command so the rest of the
      // journey stays on one known board.
      const thugPosition = (await readBoard()).positions.find((p) => p.entry_id === thugEntry.id)!
      const corrected = await request.post(`${prefix}/combat/board/reposition`, {
        data: {
          entry_id: thugEntry.id,
          anchor_x: THUG_PUSHED.x,
          anchor_y: THUG_PUSHED.y,
          reason: 'P5-G journey: normalize board after a lost Shove contest',
          expected_position_revision: thugPosition.revision,
          idempotency_key: 'p5g-normalize-thug',
        },
      })
      expect(corrected.ok(), await corrected.text()).toBe(true)
      await expect.poll(() => positionOf(thugEntry.id)).toEqual(THUG_PUSHED)
    }
    await expect(token(page, thugEntry.id)).toBeVisible()
    await expect(token(player.page, thugEntry.id)).toBeVisible()

    // G.2 item 4: Difficult Terrain crossed by player with doubled cost in preview and committed movement
    // G.2 item 5: split movement (move, act, then move again in the same turn with remaining budget)
    await token(player.page, heroEntry.id).click()
    await cell(player.page, DIFFICULT_TERRAIN_CELL).click() // entering difficult terrain doubles 5 ft -> 10 ft
    await expect(movement.getByTestId('tactical-move-used')).toContainText('25')
    await expect(movement.getByTestId('tactical-move-remaining')).toContainText('5')
    await movement.getByTestId('tactical-move-confirm').click()
    await expect.poll(() => positionOf(heroEntry.id)).toEqual(DIFFICULT_TERRAIN_CELL)

    // Assert server movement status confirms split movement: 25 ft used, 5 ft remaining
    const moveStatus = await json<{ used_feet: number; remaining_feet: number }>(
      await request.get(`${prefix}/combat/board/movement/${heroEntry.id}/status`, {
        headers: playerHeaders,
      }),
    )
    expect(moveStatus.used_feet).toBe(25)
    expect(moveStatus.remaining_feet).toBe(5)

    // G.2 item 8: automatic OA that pauses movement, reaction resolves, movement resumes to destination
    // Advance past Hero's current turn, then advance to Hero's turn in round 2.
    // Hero is at (4, 3) adjacent to Goblin at (5, 3) (inside Goblin's 5 ft reach).
    // Stepping to (4, 2) is still adjacent to (5, 3) (dx=1, dy=1: inside 5 ft reach).
    const advancedPastHero = page.waitForResponse(
      (r) => r.request().method() === 'POST' && r.url().includes('/combat/turn/advance'),
    )
    await page.getByRole('button', { name: 'Advance Turn' }).click()
    const advancedPastHeroRes = await advancedPastHero
    expect(advancedPastHeroRes.ok(), await advancedPastHeroRes.text()).toBe(true)
    await advanceTo(page, readTurn, heroEntry.id, 12)
    await expect(actionBar).toHaveAttribute('data-combat-action-state', 'ready')

    // G.2 item 6: ranged attack target feedback for at least two of normal / long / out-of-range.
    // Checked at the start of the Hero's round-2 turn: the round-1 Action was spent on the Shove.
    await actionBar.getByRole('combobox', { name: 'Action kind' }).selectOption('attack')
    await selectMatching(actionBar.getByRole('combobox', { name: 'Attack', exact: true }), /Crossbow/)

    // Normal range (30 ft <= 80 ft normal): Mage at (10, 3) on the same row as Hero at (4, 3) (pure orthogonal)
    const normalCheck = player.page.waitForResponse((r) => r.url().includes('/combat/board/target-check'))
    await selectMatching(actionBar.getByRole('combobox', { name: 'Target' }), /Mage/)
    const normalCheckRes = await responseJson<{ distance_feet: number; range_band: string }>(await normalCheck)
    expect(normalCheckRes.distance_feet).toBe(30)
    expect(normalCheckRes.range_band).toBe('normal')
    await expect(actionBar.getByTestId('combat-target-range')).toContainText('In range')
    await expect(actionBar.getByTestId('combat-target-range')).toContainText('30 ft')

    // Long range (90 ft > 80 ft and <= 320 ft long): Ogre at (22, 3) on the same row as Hero at (4, 3) (pure orthogonal)
    const longCheck = player.page.waitForResponse((r) => r.url().includes('/combat/board/target-check'))
    await selectMatching(actionBar.getByRole('combobox', { name: 'Target' }), /Ogre/)
    const longCheckRes = await responseJson<{ distance_feet: number; range_band: string }>(await longCheck)
    expect(longCheckRes.distance_feet).toBe(90)
    expect(longCheckRes.range_band).toBe('long')
    await expect(actionBar.getByTestId('combat-target-range')).toContainText('Long range')
    await expect(actionBar.getByTestId('combat-target-range')).toContainText('90 ft')

    // Out of range (reach 5 ft exceeded): Battleaxe against Mage at (10, 3) (30 ft)
    await selectMatching(actionBar.getByRole('combobox', { name: 'Attack', exact: true }), /Battleaxe/)
    const outCheck = player.page.waitForResponse((r) => (
      r.url().includes('/combat/board/target-check') &&
      (r.request().postData() ?? '').includes(mageEntry.id)
    ))
    await selectMatching(actionBar.getByRole('combobox', { name: 'Target' }), /Mage/)
    const outCheckRes = await responseJson<{ distance_feet: number; range_band: string }>(await outCheck)
    expect(outCheckRes.distance_feet).toBe(30)
    expect(outCheckRes.range_band).toBe('out_of_range')
    await expect(actionBar.getByTestId('combat-target-range')).toContainText('Out of range')
    await expect(actionBar.getByTestId('combat-target-range')).toContainText('30 ft')


    await token(player.page, heroEntry.id).click()
    await cell(player.page, { x: 4, y: 2 }).click()
    await cell(player.page, { x: 4, y: 1 }).click()
    await movement.getByTestId('tactical-move-confirm').click()

    // Automatic OA pauses movement at (4, 2), the last cell still inside Goblin's reach
    await expect(mapPanel(player.page).getByTestId('tactical-move-paused')).toBeVisible()
    expect(await positionOf(heroEntry.id)).toEqual({ x: 4, y: 2 })
    const oaMoveStatus = await json<{ has_pending_movement: boolean }>(
      await request.get(`${prefix}/combat/board/movement/${heroEntry.id}/status`, {
        headers: playerHeaders,
      }),
    )
    expect(oaMoveStatus.has_pending_movement).toBe(true)

    // DM resolves the OA reaction window (declines)
    const dmReactions = page.locator('[data-combat-reactions="true"]')
    await expect(dmReactions).toBeVisible()
    await expect(dmReactions).toContainText(/Opportunity [Aa]ttack/)
    const reactionDeclined = page.waitForResponse((r) => (
      r.request().method() === 'POST' && /reaction/.test(r.url())
    ))
    await dmReactions.getByRole('button', { name: 'Decline' }).click()
    const reactionDeclinedRes = await reactionDeclined
    expect(reactionDeclinedRes.ok(), await reactionDeclinedRes.text()).toBe(true)
    await expect(dmReactions).toHaveCount(0)

    // Player resumes movement to destination (4, 1)
    const resumeButton = mapPanel(player.page).getByTestId('tactical-move-resume')
    await expect(resumeButton).toBeEnabled()
    const resumed = player.page.waitForResponse((r) => r.url().includes('/movement/resume'))
    await resumeButton.click()
    const resumedRes = await resumed
    expect(resumedRes.ok(), await resumedRes.text()).toBe(true)
    await expect.poll(() => positionOf(heroEntry.id)).toEqual({ x: 4, y: 1 })
    expect(await positionOf(heroEntry.id)).toEqual({ x: 4, y: 1 })

    // G.2 item 7: an AoE (Fireball placed by Player Caster on Tactical map)
    await advanceTo(page, readTurn, casterEntry.id, 12)
    const casterActionBar = player.page.locator('[data-combat-action-bar="true"]')
    await expect(casterActionBar).toHaveAttribute('data-combat-action-state', 'ready')
    // The action bar re-renders for the Caster after the turn advances; wait for its own weapon first.
    await expect(casterActionBar.getByRole('combobox', { name: 'Attack', exact: true })).toContainText('Quarterstaff')
    await casterActionBar.getByRole('combobox', { name: 'Action kind' }).selectOption('spell')
    await selectMatching(casterActionBar.locator('select[data-combat-spell="true"]'), /Fireball/)
    await casterActionBar.getByTestId('combat-aoe-place-template').click()

    // Place template at (10, 3) targeting Mage; Hero at (4, 1) is 30+ ft away (outside 20 ft radius)
    const aoePreviewed = player.page.waitForResponse((r) => (
      r.request().method() === 'POST' && r.url().includes('/spells/aoe/preview')
    ))
    await cell(player.page, { x: 10, y: 3 }).click()
    const aoePreviewedRes = await aoePreviewed
    expect(aoePreviewedRes.ok(), await aoePreviewedRes.text()).toBe(true)

    // Assert AoE template overlay cells and candidate targets on player tactical map
    await expect(mapPanel(player.page).getByTestId('battle-map-aoe-cell').first()).toBeVisible()
    expect(await mapPanel(player.page).getByTestId('battle-map-aoe-cell').count()).toBeGreaterThan(1)
    await expect(mapPanel(player.page).getByTestId('tactical-aoe-affected-count')).toBeVisible()
    await expect(mapPanel(player.page).getByTestId('tactical-aoe-candidates')).toBeVisible()

    // Confirm AoE template placement and propose to adjudication
    const aoeProposed = player.page.waitForResponse((r) => (
      r.request().method() === 'POST' && r.url().includes('/spells/aoe/propose')
    ))
    await mapPanel(player.page).getByTestId('tactical-aoe-confirm').click()
    const aoeProposal = await responseJson<{ action_id: string }>(await aoeProposed)

    // DM resolves AoE in adjudication
    const aoeAdj = page.locator(`[data-adjudication-id="${aoeProposal.action_id}"]`)
    await expect(aoeAdj).toHaveAttribute('data-adjudication-kind', 'affected_targets')
    const aoeResolved = page.waitForResponse((r) => (
      r.request().method() === 'POST' && r.url().includes('/spells/aoe/resolve')
    ))
    await aoeAdj.getByRole('button', { name: 'Resolve AoE' }).click()
    const aoeResolvedRes = await aoeResolved
    expect(aoeResolvedRes.ok(), await aoeResolvedRes.text()).toBe(true)
    await expect(aoeAdj).toHaveCount(0)

    // Hero is deterministically outside Fireball area (31+ ft away); assert no pending save
    await expect(player.page.locator('[data-pending-roll]')).toHaveCount(0)

    // G.2 item 11: End Session, Start Session on the same Campaign, the same Tactical board, positions and turn come back
    const boardBeforeSessionEnd = await readBoard()
    const detailBeforeSessionEnd = await readDetail(request, prefix)

    await endFromSession(page)
    const sessionId2 = await startSession(page, roomContext.roomId, campaign.id)
    const sessionUrl2 = `/rooms/${roomContext.roomId}/campaigns/${campaign.id}/sessions/${sessionId2}`
    const prefix2 = `/api/rooms/${roomContext.roomId}/campaigns/${campaign.id}/sessions/${sessionId2}`

    await player.page.goto(sessionUrl2)
    await expect(player.page.getByRole('heading', { name: 'Active Session', level: 1 })).toBeVisible()

    // Both DM and Player see active combat stage and tactical map panel restored
    await expect(combatStage(page)).toBeVisible()
    await expect(combatStage(player.page)).toBeVisible()
    await expect(mapPanel(page)).toBeVisible()
    await expect(mapPanel(player.page)).toBeVisible()

    // Assert server state continuity across session boundary
    const detail2 = await readDetail(request, prefix2)
    expect(detail2.id).toBe(detailBeforeSessionEnd.id)
    expect(detail2.status).toBe('running')
    expect(detail2.round_number).toBe(detailBeforeSessionEnd.round_number)
    expect(detail2.current_turn_entry_id).toBe(detailBeforeSessionEnd.current_turn_entry_id)

    const board2 = await json<Board>(await request.get(`${prefix2}/combat/board`))
    expect(board2.positions).toEqual(boardBeforeSessionEnd.positions)
    expect(board2.runtime_revision).toBe(boardBeforeSessionEnd.runtime_revision)

    // Re-verify hidden Stalker secrecy after session restart
    await expect(token(page, stalkerEntry.id)).toBeVisible()
    await expect(token(player.page, stalkerEntry.id)).toHaveCount(0)

    // G.2 item 12: End Combat and the map panel leaves the Session
    page.once('dialog', (dialog) => dialog.accept())
    const combatEnded = page.waitForResponse((r) => (
      r.request().method() === 'POST' && r.url().includes('/combat/end')
    ))
    await page.getByRole('button', { name: 'End Combat' }).click()
    const combatEndedRes = await combatEnded
    expect(combatEndedRes.ok(), await combatEndedRes.text()).toBe(true)
    const endView = await responseJson<{ status: string }>(combatEndedRes)
    expect(endView.status).toBe('ended')

    await expect(combatStage(page)).toHaveCount(0)
    await expect(combatStage(player.page)).toHaveCount(0)
    await expect(mapPanel(page)).toHaveCount(0)
    await expect(mapPanel(player.page)).toHaveCount(0)

    const detailEnded = await json<CombatDetail | null>(await request.get(`${prefix2}/combat/detail`))
    expect(detailEnded).toBeNull()
  } finally {
    await player.context.close()
  }
})
