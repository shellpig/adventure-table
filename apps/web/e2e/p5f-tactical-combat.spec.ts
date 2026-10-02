import { expect, test, type Page } from './support/roomTest'
import {
  addPlayerSeat,
  addSeat,
  createCampaign,
  enterAsMember,
  entryNamed,
  importCharacter,
  initiativeRow,
  json,
  openSessionAs,
  readDetail,
  startSession,
  type Lobby,
} from './support/quickCombat'

import {
  advanceTo,
  cameraStyle,
  cell,
  center,
  mapPanel,
  selectMatching,
  token,
  type Board,
  type MonsterInstance,
} from './support/tactical'

// Hero starts next to the Goblin so leaving its reach provokes an opportunity attack.
const HERO_START = { x: 2, y: 5 }
const HERO_STEP = { x: 2, y: 4 }
const HERO_RETREAT = { x: 0, y: 4 }
const HERO_REPOSITION = { x: 6, y: 8 }
const GOBLIN_AT = { x: 3, y: 5 }
const MAGE_AT = { x: 12, y: 5 }
const STALKER_AT = { x: 15, y: 9 }
const FIREBALL_ORIGIN = { x: 12, y: 2 }

test.use({ actionTimeout: 15_000 })

test('P5-F F.1 + F.2 Tactical Combat browser journey', async ({ browser, page, request, roomContext }) => {
  test.setTimeout(240_000)
  const playerGrant = await enterAsMember(request, roomContext, 'P5-F Player')
  const character = await importCharacter(request)
  const campaign = await createCampaign(request, roomContext.roomId, 'P5-F Tactical Journey')
  const ownerLobby = await json<Lobby>(await request.get(
    `/api/rooms/${roomContext.roomId}/campaigns/${campaign.id}/lobby`,
  ))
  await addSeat(request, roomContext.roomId, campaign.id, 'dm', ownerLobby.caller_access_session_id!)
  await addPlayerSeat(request, roomContext.roomId, campaign.id, character, playerGrant.access_session_id)

  const mapsUrl = `/api/rooms/${roomContext.roomId}/battle-maps`
  const battleMap = await json<{ id: string; revision: number }>(await request.post(mapsUrl, {
    data: { name: 'P5-F Crossroads', source_kind: 'blank', width_cells: 20, height_cells: 12 },
  }))
  await json(await request.put(`${mapsUrl}/${battleMap.id}/objects`, {
    data: {
      expected_revision: battleMap.revision,
      walls: [{ x1: 8, y1: 9, x2: 8, y2: 12, visibility: 'public' }],
    },
  }))

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
    const position = board.positions.find((item) => item.entry_id === entryId)
    expect(position).toBeDefined()
    return { x: position!.anchor_x, y: position!.anchor_y }
  }

  try {
    // DM starts Tactical Combat on the saved map from the Session toolbar.
    await expect(player.page.getByTestId('tactical-start-open')).toHaveCount(0)
    await page.getByTestId('tactical-start-open').click()
    await page.getByTestId(`tactical-map-${battleMap.id}`).getByRole('radio').check()
    await page.getByTestId('tactical-start-confirm').click()
    await expect(mapPanel(page)).toBeVisible()
    await expect(mapPanel(player.page)).toBeVisible()
    // Tactical adds the map next to the existing combat controls, it does not replace them.
    await expect(page.getByRole('button', { name: 'Request Initiative' })).toBeVisible()

    let detail = await readDetail(request, prefix)
    const heroEntry = entryNamed(detail, character.name)

    // Monsters: a visible Goblin and Mage, and a hidden Stalker only the DM may know about.
    const goblin = await json<MonsterInstance>(await request.post(`${prefix}/monster-instances/from-content`, {
      data: { content_key: 'srd5.1:monster:goblin' },
    }))
    const mage = await json<MonsterInstance>(await request.post(`${prefix}/monster-instances/from-content`, {
      data: { content_key: 'srd5.1:monster:mage' },
    }))
    const stalker = await json<MonsterInstance>(await request.post(`${prefix}/monster-instances/quick-enemy`, {
      data: { name: 'Hidden Stalker', armor_class: 13, max_hp: 20, visibility: 'hidden' },
    }))
    for (const instance of [goblin, mage, stalker]) {
      const added = await request.post(`${prefix}/combat/entries/monsters`, {
        data: { monster_instance_id: instance.id },
      })
      expect(added.ok()).toBe(true)
    }
    detail = await readDetail(request, prefix)
    const goblinEntry = entryNamed(detail, 'Goblin')
    const mageEntry = entryNamed(detail, 'Mage')
    const stalkerEntry = entryNamed(detail, 'Hidden Stalker')

    // Placement: the hero through the DM map toolbar, the monsters through the same route.
    await expect(mapPanel(player.page).getByTestId('tactical-token-mode')).toHaveCount(0)
    await expect(mapPanel(page).getByTestId('tactical-token-mode')).toBeEnabled()
    await mapPanel(page).getByTestId(`tactical-place-${heroEntry.id}`).click()
    await expect(mapPanel(page).getByTestId(`tactical-place-${heroEntry.id}`)).toHaveAttribute('data-placing', 'true')
    await cell(page, HERO_START).click()
    await expect(token(page, heroEntry.id)).toBeVisible()
    for (const [entryId, at] of [
      [goblinEntry.id, GOBLIN_AT],
      [mageEntry.id, MAGE_AT],
      [stalkerEntry.id, STALKER_AT],
    ] as const) {
      const placed = await request.put(`${prefix}/combat/board/positions/${entryId}`, {
        data: { anchor_x: at.x, anchor_y: at.y },
      })
      expect(placed.ok()).toBe(true)
    }
    await expect(token(player.page, goblinEntry.id)).toBeVisible()
    await expect(token(page, stalkerEntry.id)).toBeVisible()

    // Hidden token: absent from the Player DOM and from every Player board payload.
    await expect(token(player.page, stalkerEntry.id)).toHaveCount(0)
    expect(playerBoardResponses.length).toBeGreaterThan(0)
    for (const body of playerBoardResponses) expect(body).not.toContain(stalkerEntry.id)
    expect(JSON.stringify(await readBoard(playerHeaders))).not.toContain(stalkerEntry.id)

    // Initiative: Player rolls their own entry, DM rolls the monsters and finalizes.
    await page.getByRole('button', { name: 'Request Initiative' }).click()
    await initiativeRow(player.page, heroEntry.id).getByRole('button', { name: 'Roll Initiative' }).click()
    for (const entryId of [goblinEntry.id, mageEntry.id, stalkerEntry.id]) {
      await initiativeRow(page, entryId).getByRole('button', { name: 'Roll Initiative' }).click()
      await expect(initiativeRow(page, entryId).locator('.session-combat__initiative-total')).toBeVisible()
    }
    await page.getByRole('button', { name: 'Finalize Initiative' }).click()
    const readTurn = async () => (await readDetail(request, prefix)).current_turn_entry_id
    await advanceTo(page, readTurn, heroEntry.id)

    // F.2 Camera: zoom / pan / Fit Map are client-only and per client.
    const dmCameraBefore = await cameraStyle(page)
    const playerCameraBefore = await cameraStyle(player.page)
    const playerWrites: string[] = []
    const recordWrite = (req: { method(): string; url(): string }) => {
      // Camera changes must never write Session or map state (rules text lookups are read-only POSTs).
      if (req.method() !== 'GET' && (req.url().includes(prefix) || req.url().includes(mapsUrl))) {
        playerWrites.push(`${req.method()} ${req.url()}`)
      }
    }
    player.page.on('request', recordWrite)
    const revisionBeforeCamera = (await readBoard()).runtime_revision
    await mapPanel(player.page).getByTestId('tactical-zoom-in').click()
    await mapPanel(player.page).getByTestId('tactical-zoom-in').click()
    const board = mapPanel(player.page).getByTestId('tactical-board-wrap')
    const boardBox = await board.boundingBox()
    await player.page.mouse.move(boardBox!.x + 5, boardBox!.y + 5)
    await player.page.mouse.wheel(0, -200)
    await expect.poll(() => cameraStyle(player.page)).not.toBe(playerCameraBefore)
    await mapPanel(player.page).getByTestId('tactical-fit-map').click()
    player.page.off('request', recordWrite)
    expect(playerWrites).toEqual([])
    expect((await readBoard()).runtime_revision).toBe(revisionBeforeCamera)
    expect(await cameraStyle(page)).toBe(dmCameraBefore)

    // F.1 Player drag: dragging the own token only builds a plan and a preview.
    const confirmCalls: string[] = []
    player.page.on('request', (req) => {
      if (req.method() === 'POST' && req.url().includes('/board/movement/confirm')) confirmCalls.push(req.url())
    })
    await token(player.page, heroEntry.id).scrollIntoViewIfNeeded()
    const from = await center(player.page, token(player.page, heroEntry.id))
    const to = await center(player.page, cell(player.page, HERO_STEP))
    const previewed = player.page.waitForResponse((response) => (
      response.request().method() === 'POST' && response.url().includes('/board/movement/preview')
    ))
    await player.page.mouse.move(from.x, from.y)
    await player.page.mouse.down()
    await player.page.mouse.move(to.x, to.y, { steps: 8 })
    await player.page.mouse.up()
    await previewed
    const movement = mapPanel(player.page).getByTestId('tactical-movement')
    await expect(movement.getByTestId('tactical-move-used')).toContainText('5')
    await expect(movement.getByTestId('tactical-move-remaining')).toContainText('25')
    expect(confirmCalls).toEqual([])
    expect(await positionOf(heroEntry.id)).toEqual(HERO_START)

    // Confirm is the only step that writes the canonical position.
    await movement.getByTestId('tactical-move-confirm').click()
    await expect.poll(() => positionOf(heroEntry.id)).toEqual(HERO_STEP)
    expect(confirmCalls.length).toBe(1)

    // The Player cannot drag a token they do not control.
    await token(player.page, goblinEntry.id).scrollIntoViewIfNeeded()
    const goblinCenter = await center(player.page, token(player.page, goblinEntry.id))
    const away = await center(player.page, cell(player.page, { x: 4, y: 7 }))
    await player.page.mouse.move(goblinCenter.x, goblinCenter.y)
    await player.page.mouse.down()
    await player.page.mouse.move(away.x, away.y, { steps: 5 })
    await player.page.mouse.up()
    await expect(mapPanel(player.page).getByTestId('tactical-movement')).toHaveCount(0)
    expect(await positionOf(goblinEntry.id)).toEqual(GOBLIN_AT)

    // Ranged attack: the action bar shows server range feedback for the chosen target.
    const actionBar = player.page.locator('[data-combat-action-bar="true"]')
    await actionBar.getByRole('combobox', { name: 'Action kind' }).selectOption('attack')
    await selectMatching(actionBar.getByRole('combobox', { name: 'Attack', exact: true }), /Crossbow/)
    await selectMatching(actionBar.getByRole('combobox', { name: 'Target' }), /Mage/)
    await expect(actionBar.getByTestId('combat-target-range')).toContainText('In range')
    await expect(actionBar.getByTestId('combat-target-range')).toContainText('50 ft')

    // Leaving the Goblin's reach pauses movement for an automatic opportunity attack.
    await token(player.page, heroEntry.id).click()
    await cell(player.page, { x: 1, y: 4 }).click()
    await cell(player.page, HERO_RETREAT).click()
    await expect(movement.getByTestId('tactical-move-remaining')).toContainText('15')
    await movement.getByTestId('tactical-move-confirm').click()
    await expect(mapPanel(player.page).getByTestId('tactical-move-paused')).toBeVisible()
    expect(await positionOf(heroEntry.id)).toEqual(HERO_STEP)

    const dmActionBar = page.locator('[data-combat-action-bar="true"]')
    const decline = dmActionBar.getByRole('button', { name: 'Decline' })
    await expect(decline).toBeVisible()
    const declined = page.waitForResponse((response) => (
      response.request().method() === 'POST' && /reaction/.test(response.url())
    ))
    await decline.click()
    expect((await declined).ok()).toBe(true)
    const resumed = player.page.waitForResponse((r) => r.url().includes('/movement/resume'))
    await mapPanel(player.page).getByTestId('tactical-move-resume').click()
    expect((await resumed).ok()).toBe(true)
    await expect.poll(() => positionOf(heroEntry.id)).toEqual(HERO_RETREAT)

    // AoE: on the Mage's turn the DM places a Fireball template and sees server cells.
    await advanceTo(page, readTurn, mageEntry.id)
    // The action bar re-renders for the Mage after the turn advances; wait for its own attack first.
    await expect(dmActionBar.getByRole('combobox', { name: 'Attack', exact: true })).toContainText('Dagger')
    await dmActionBar.getByRole('combobox', { name: 'Action kind' }).selectOption('spell')
    await selectMatching(dmActionBar.locator('select[data-combat-spell="true"]'), /Fireball/)
    await dmActionBar.getByTestId('combat-aoe-place-template').click()
    const aoePreviewed = page.waitForResponse((response) => (
      response.request().method() === 'POST' && response.url().includes('/spells/aoe/preview')
    ))
    await cell(page, FIREBALL_ORIGIN).click()
    expect((await aoePreviewed).ok()).toBe(true)
    await expect(mapPanel(page).getByTestId('battle-map-aoe-cell').first()).toBeVisible()
    expect(await mapPanel(page).getByTestId('battle-map-aoe-cell').count()).toBeGreaterThan(1)
    await expect(mapPanel(page).getByTestId('tactical-aoe-affected-count')).toBeVisible()
    await mapPanel(page).getByTestId('tactical-aoe-clear').click()
    await expect(mapPanel(page).getByTestId('battle-map-aoe-cell')).toHaveCount(0)

    // DM reposition is a separate mode and command; the Player has no such control.
    await expect(mapPanel(player.page).getByTestId('tactical-reposition-mode')).toHaveCount(0)
    await mapPanel(page).getByTestId('tactical-reposition-mode').click()
    await token(page, heroEntry.id).click()
    await cell(page, HERO_REPOSITION).click()
    await mapPanel(page).getByTestId('tactical-reposition-reason').fill('Swept aside by the rockslide')
    await mapPanel(page).getByTestId('tactical-reposition-confirm').click()
    await expect.poll(() => positionOf(heroEntry.id)).toEqual(HERO_REPOSITION)
    await expect(token(player.page, heroEntry.id)).toBeVisible()

    // The hidden Stalker never reached the Player, before or after all those updates.
    await expect(token(player.page, stalkerEntry.id)).toHaveCount(0)
    for (const body of playerBoardResponses) expect(body).not.toContain(stalkerEntry.id)
  } finally {
    await player.context.close()
  }
})
