import type { BattleMap } from '../src/api/battleMaps'
import type { CombatDetailView, AttackResolutionView } from '../src/api/combat'
import type { MonsterLibraryDetailView } from '../src/api/monsterLibrary'
import type { CombatBoardView } from '../src/api/tacticalCombat'
import { expect, test, type APIRequestContext, type Page } from './support/roomTest'
import {
  addPlayerSeat, addSeat, createCampaign, endCombat, enterAsMember, importCharacter,
  initiativeRow, json, LOCALE_STORAGE_KEY, openSessionAs, responseJson,
  restartE2EServer, startSession, type AttackRequest, type Lobby,
} from './support/quickCombat'
import { advanceTo, cell, mapPanel, selectMatching, token } from './support/tactical'

test.use({ actionTimeout: 15_000 })

async function endSession(page: Page) {
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByRole('button', { name: 'End Session', exact: true }).click()
  await expect(page.getByText('Ended', { exact: true })).toBeVisible()
}

async function loadLibraryMap(page: Page, mapId: string, monsters: boolean) {
  await page.getByTestId('tactical-start-open').click()
  await page.getByTestId(`tactical-map-${mapId}`).getByRole('radio').check()
  await page.getByTestId(monsters ? 'tactical-load-with-monsters' : 'tactical-load-map-only').check()
  await page.getByTestId('tactical-start-confirm').click()
  await expect(mapPanel(page)).toBeVisible()
}

async function board(request: APIRequestContext, prefix: string, headers?: Record<string, string>) {
  return json<CombatBoardView>(await request.get(`${prefix}/combat/board`, { headers }))
}

async function detail(request: APIRequestContext, prefix: string) {
  return json<CombatDetailView>(await request.get(`${prefix}/combat/detail`))
}

test('M07-D libraries load latest snapshots, survive pending OA across restart and Sessions, and isolate Campaigns', async ({
  browser, page, request, roomContext,
}) => {
  test.setTimeout(300_000)
  const { roomId } = roomContext
  const maps = `/api/rooms/${roomId}/battle-maps`
  const library = `/api/rooms/${roomId}/monster-library`
  let template = await json<MonsterLibraryDetailView>(await request.post(`${library}/custom/from-content`, {
    data: { content_key: 'srd5.1:monster:goblin' },
  }))
  const templateId = template.ref.slice('custom:'.length)
  let map = await json<BattleMap>(await request.post(maps, {
    data: { name: 'M07-D shared lair', source_kind: 'blank', width_cells: 12, height_cells: 10 },
  }))
  map = await json<BattleMap>(await request.put(`${maps}/${map.id}/monster-placements`, {
    data: {
      expected_revision: map.revision,
      placements: [
        { custom_template_id: templateId, anchor_x: 2, anchor_y: 1, visibility: 'public', sort_order: 0 },
        { template_key: 'srd5.1:monster:ogre', anchor_x: 8, anchor_y: 5, visibility: 'hidden', sort_order: 1 },
      ],
    },
  }))
  template = await json<MonsterLibraryDetailView>(await request.patch(`${library}/custom/${templateId}`, {
    data: { expected_revision: template.revision, max_hp: 40 },
  }))
  const character = await importCharacter(request)
  const playerGrant = await enterAsMember(request, roomContext, 'M07-D Player')
  const playerHeaders = { Authorization: `Bearer ${playerGrant.access_token}` }
  const campaign = await createCampaign(request, roomId, 'M07-D Campaign A')
  const lobby = await json<Lobby>(await request.get(`/api/rooms/${roomId}/campaigns/${campaign.id}/lobby`))
  await addSeat(request, roomId, campaign.id, 'dm', lobby.caller_access_session_id!, 'M07-D')
  await addPlayerSeat(request, roomId, campaign.id, character, playerGrant.access_session_id, 'M07-D')
  let sessionId = await startSession(page, roomId, campaign.id)
  let prefix = `/api/rooms/${roomId}/campaigns/${campaign.id}/sessions/${sessionId}`

  // The same prepared map can start without loading its optional monsters.
  await loadLibraryMap(page, map.id, false)
  expect((await detail(request, prefix)).entries.filter((entry) => entry.subject_kind === 'monster')).toEqual([])
  await endCombat(page, sessionId)
  await loadLibraryMap(page, map.id, true)
  const loaded = await detail(request, prefix)
  const hero = loaded.entries.find((entry) => entry.character_id === character.id)!
  const goblin = loaded.entries.find((entry) => entry.display_name === 'Goblin')!
  const ogre = loaded.entries.find((entry) => entry.display_name === 'Ogre')!
  expect(hero).toBeDefined()
  expect(goblin).toBeDefined()
  expect(ogre).toBeDefined()
  expect(loaded.combatants.find((item) => item.entry_id === goblin.id)!.projection.max_hp).toBe(40)
  const ogrePosition = (await board(request, prefix)).positions.find((item) => item.entry_id === ogre.id)!
  expect(ogrePosition).toMatchObject({ footprint_width: 2, footprint_height: 2 })
  await mapPanel(page).getByTestId(`tactical-place-${hero.id}`).click()
  await cell(page, { x: 1, y: 1 }).click()
  const player = await openSessionAs(browser, playerGrant, roomContext, page.url())
  try {
    await expect(mapPanel(player.page)).toBeVisible()
    await expect(token(player.page, goblin.id)).toBeVisible()
    await expect(token(player.page, ogre.id)).toHaveCount(0)
    const projected = await request.get(`${prefix}/combat/detail`, { headers: playerHeaders })
    expect(await projected.text()).not.toContain(ogre.id)
    expect(JSON.stringify(await board(request, prefix, playerHeaders))).not.toContain(ogre.id)
    await player.page.evaluate((key) => localStorage.setItem(key, 'zh-TW'), LOCALE_STORAGE_KEY)
    await player.page.reload()
    await expect(token(player.page, goblin.id)).toContainText('地精')
    await player.page.evaluate((key) => localStorage.setItem(key, 'en'), LOCALE_STORAGE_KEY)
    await player.page.reload()

    // Changes to the shared library never rewrite the running snapshot.
    template = await json<MonsterLibraryDetailView>(await request.patch(`${library}/custom/${templateId}`, {
      data: { expected_revision: template.revision, max_hp: 60, armor_class: 18 },
    }))
    expect((await detail(request, prefix)).combatants.find((item) => item.entry_id === goblin.id)!.projection.max_hp).toBe(40)
    await page.getByRole('button', { name: 'Request Initiative', exact: true }).click()
    await initiativeRow(player.page, hero.id).getByRole('button', { name: 'Roll Initiative' }).click()
    for (const entry of [goblin, ogre]) {
      await initiativeRow(page, entry.id).getByRole('button', { name: 'Roll Initiative' }).click()
      await expect(initiativeRow(page, entry.id).locator('.session-combat__initiative-total')).toBeVisible()
    }
    await page.getByRole('button', { name: 'Finalize Initiative', exact: true }).click()
    await advanceTo(page, async () => (await detail(request, prefix)).current_turn_entry_id, hero.id)
    const actionBar = player.page.locator('[data-combat-action-bar="true"]')
    await actionBar.getByRole('combobox', { name: 'Action kind' }).selectOption('attack')
    await selectMatching(actionBar.getByRole('combobox', { name: 'Attack', exact: true }), /Battleaxe/)
    await actionBar.getByRole('combobox', { name: 'Target', exact: true }).selectOption(goblin.id)
    const requested = player.page.waitForResponse((response) => (
      response.request().method() === 'POST' && response.url().endsWith('/combat/attacks/request')
    ), { timeout: 15_000 })
    await actionBar.getByRole('button', { name: 'Request Attack', exact: true }).click()
    const attackRequest = await responseJson<AttackRequest>(await requested)
    expect(attackRequest.roll_request_id).not.toBeNull()
    const rolled = player.page.waitForResponse((response) => (
      response.request().method() === 'POST' && response.url().includes('/combat/attacks/roll')
    ), { timeout: 15_000 })
    await actionBar.locator(`[data-attack-roll="${attackRequest.roll_request_id}"]`).click()
    const attack = await responseJson<AttackResolutionView>(await rolled)
    expect(typeof attack.hit).toBe('boolean')
    const damaged = (await detail(request, prefix)).combatants.find((item) => item.entry_id === goblin.id)!.projection
    expect(damaged.current_hp).toBe(40 - attack.damage_total)
    expect(damaged.current_hp).toBeGreaterThan(0)

    // Leaving the copied Goblin's reach triggers the existing OA engine.
    await token(player.page, hero.id).click()
    await cell(player.page, { x: 0, y: 1 }).click()
    await mapPanel(player.page).getByTestId('tactical-move-confirm').click()
    await expect(mapPanel(player.page).getByTestId('tactical-move-paused')).toBeVisible()
    const reactions = page.locator('[data-combat-reactions="true"]')
    await expect(reactions).toContainText(/Opportunity [Aa]ttack/)
    const before = await detail(request, prefix)
    const boardBefore = await board(request, prefix)
    expect(process.env.PLAYWRIGHT_E2E_SERVER_SERVICE).toBe('server-e2e')
    await restartE2EServer(request)
    await page.reload()
    await player.page.reload()
    await expect(reactions).toContainText(/Opportunity [Aa]ttack/)
    expect((await detail(request, prefix)).id).toBe(before.id)
    expect(await board(request, prefix)).toEqual(boardBefore)
    expect(await json<BattleMap>(await request.get(`${maps}/${map.id}`))).toEqual(map)

    // End and restart the Session with the OA still pending, then resolve it.
    await endSession(page)
    sessionId = await startSession(page, roomId, campaign.id)
    prefix = `/api/rooms/${roomId}/campaigns/${campaign.id}/sessions/${sessionId}`
    await player.page.goto(page.url())
    await expect(mapPanel(player.page)).toBeVisible()
    const restored = await detail(request, prefix)
    expect(restored.id).toBe(before.id)
    expect(restored.current_turn_entry_id).toBe(before.current_turn_entry_id)
    expect(restored.combatants.find((item) => item.entry_id === goblin.id)!.projection.current_hp).toBe(damaged.current_hp)
    expect(await board(request, prefix)).toEqual(boardBefore)
    await expect(reactions).toContainText(/Opportunity [Aa]ttack/)
    const declined = page.waitForResponse((response) => response.request().method() === 'POST' && /reaction/.test(response.url()))
    await reactions.getByRole('button', { name: 'Decline', exact: true }).click()
    expect((await declined).ok()).toBe(true)
    await expect(reactions).toHaveCount(0)
    await mapPanel(player.page).getByTestId('tactical-move-resume').click()
    await expect.poll(async () => (await board(request, prefix)).positions.find((item) => item.entry_id === hero.id))
      .toMatchObject({ anchor_x: 0, anchor_y: 1 })
    const reveal = page.locator(`[data-monster-controls="${ogre.id}"] [data-monster-visibility]`)
    await reveal.click()
    await expect(token(player.page, ogre.id)).toBeVisible()
    await endCombat(page, sessionId)
    await endSession(page)
  } finally {
    await player.context.close()
  }

  // A second Campaign shares authoring identity but owns new runtime identities.
  const campaignB = await createCampaign(request, roomId, 'M07-D Campaign B')
  await addSeat(request, roomId, campaignB.id, 'dm', lobby.caller_access_session_id!, 'M07-D B')
  sessionId = await startSession(page, roomId, campaignB.id)
  const prefixB = `/api/rooms/${roomId}/campaigns/${campaignB.id}/sessions/${sessionId}`
  await loadLibraryMap(page, map.id, true)
  const runtimeB = await detail(request, prefixB)
  expect(runtimeB.id).not.toBe(loaded.id)
  expect(runtimeB.entries.map((entry) => entry.monster_instance_id)).not.toContain(goblin.monster_instance_id)
  const goblinB = runtimeB.entries.find((entry) => entry.display_name === 'Goblin')!
  expect(runtimeB.combatants.find((item) => item.entry_id === goblinB.id)!.projection.current_hp).toBe(60)
  expect((await board(request, prefixB)).source_battle_map_id).toBe(map.id)
  expect((await board(request, prefixB)).positions.every((item) => item.entry_id !== goblin.id)).toBe(true)

  const otherRoom = await json<{ access_token: string }>(await request.post('/api/rooms', {
    data: { name: 'M07-D isolated Room', password: 'm07d-isolation', display_name: 'Other Owner' },
  }))
  for (const path of [`${maps}/${map.id}`, `${library}/${encodeURIComponent(template.ref)}`]) {
    const response = await request.get(path, { headers: { Authorization: `Bearer ${otherRoom.access_token}` } })
    expect(response.status()).toBe(403)
    expect((await response.json()).error.code).toBe('room_scope_mismatch')
    expect(await response.text()).not.toContain(map.name)
  }
  map = await json<BattleMap>(await request.post(`${maps}/${map.id}/archive`, {
    data: { expected_revision: map.revision },
  }))
  expect((await json<BattleMap[]>(await request.get(maps))).map((item) => item.id)).not.toContain(map.id)
  const rejected = await request.delete(`${maps}/${map.id}`, { params: { expected_revision: map.revision } })
  expect(rejected.status()).toBe(409)
  const afterArchive = await detail(request, prefixB)
  expect(afterArchive.id).toBe(runtimeB.id)
  expect(await board(request, prefixB)).toMatchObject({ source_battle_map_id: map.id })
  await endCombat(page, sessionId)
  await endSession(page)
})
