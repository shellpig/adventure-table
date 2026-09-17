import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'

import {
  expect,
  test,
  type APIRequestContext,
  type Browser,
  type BrowserContext,
  type Locator,
  type Page,
  type Response,
} from './support/roomTest'

const ROOM_PASSWORD = 'p2-e2e-room-pass'
const RECENT_ROOMS_STORAGE_KEY = 'adventure-table.recent-rooms.v1'
const ACTIVE_ROOM_STORAGE_KEY = 'adventure-table.active-room.v1'
const LOCALE_STORAGE_KEY = 'adventure-table.locale'
const PLAYWRIGHT_BASE_URL = process.env.PLAYWRIGHT_BASE_URL ?? 'http://127.0.0.1:4173'
const IMPORT_FIXTURE = resolve(
  process.cwd(),
  '../server/tests/data/m03/fixture_low_level_srd.json',
)
// Quick Enemy AC 1 keeps the attack loop short; only a natural 1 misses.
const QUICK_ENEMY = { name: 'Bandit Thug', ac: 1, maxHp: 30, positionNote: 'Behind the barrels' }
const SRD_MONSTER = 'Goblin'
const MAX_ATTACK_ROUNDS = 6

type Campaign = { id: string }
type CharacterSummary = { id: string; name: string }
type CharacterImportResult = {
  character_id: string | null
  character_preview: { name: string }
}
type Seat = { id: string }
type Lobby = { caller_access_session_id: string | null }
type RoomGrant = {
  room: { id: string; code: string; name: string }
  authority: 'member' | 'dm' | 'owner'
  access_session_id: string
  access_token: string
}
type CombatEntry = {
  id: string
  subject_kind: string
  character_id: string | null
  display_name: string
  status: string
}
type CombatantProjection = {
  name: string
  armor_class?: number | null
  current_hp?: number | null
  max_hp?: number | null
  position_note?: string | null
}
type CombatDetail = {
  id: string
  status: string
  round_number: number | null
  current_turn_entry_id: string | null
  entries: CombatEntry[]
  combatants: Array<{ entry_id: string; is_hostile: boolean; projection: CombatantProjection }>
}
type AttackRequest = { action_id: string; roll_request_id: string | null }
type AttackResolution = {
  hit: boolean
  damage_total: number
  after_hp?: number | null
}
type CombatAdjudication = { action_id: string; kind: string }

async function json<T>(response: Awaited<ReturnType<APIRequestContext['get']>>): Promise<T> {
  if (!response.ok()) {
    expect(response.ok(), await response.text()).toBe(true)
  }
  return response.json() as Promise<T>
}

async function responseJson<T>(response: Response): Promise<T> {
  if (!response.ok()) {
    expect(response.ok(), await response.text()).toBe(true)
  }
  return response.json() as Promise<T>
}

async function importCharacter(request: APIRequestContext): Promise<CharacterSummary> {
  const envelope = await readFile(IMPORT_FIXTURE, 'utf8')
  const result = await json<CharacterImportResult>(await request.post('/api/characters/import', {
    data: envelope,
    headers: { 'Content-Type': 'application/json' },
  }))
  expect(result.character_id).not.toBeNull()
  return { id: result.character_id!, name: result.character_preview.name }
}

async function enterAsMember(
  request: APIRequestContext,
  room: { code: string },
  displayName: string,
): Promise<RoomGrant> {
  return json<RoomGrant>(await request.post('/api/rooms/enter', {
    data: {
      code: room.code,
      password: ROOM_PASSWORD,
      display_name: displayName,
    },
  }))
}

async function createCampaign(
  request: APIRequestContext,
  roomId: string,
  name: string,
): Promise<Campaign> {
  const campaign = await json<Campaign>(await request.post(`/api/rooms/${roomId}/campaigns`, {
    data: { name, ruleset: 'dnd5e-2014' },
  }))
  await json(await request.patch(`/api/rooms/${roomId}/campaigns/${campaign.id}/status`, {
    data: { status: 'active' },
  }))
  await json(await request.post(`/api/rooms/${roomId}/campaigns/${campaign.id}/select`))
  return campaign
}

async function addSeat(
  request: APIRequestContext,
  roomId: string,
  campaignId: string,
  role: 'dm' | 'player',
  accessSessionId: string,
): Promise<Seat> {
  const seat = await json<Seat>(await request.post(
    `/api/rooms/${roomId}/campaigns/${campaignId}/seats`,
    { data: { role, label: role === 'dm' ? 'P4-E DM' : 'P4-E Player' } },
  ))
  await json(await request.patch(
    `/api/rooms/${roomId}/campaigns/${campaignId}/seats/${seat.id}/controller`,
    {
      data: {
        controller_kind: 'human',
        controller_access_session_id: accessSessionId,
      },
    },
  ))
  return seat
}

async function addPlayerSeat(
  request: APIRequestContext,
  roomId: string,
  campaignId: string,
  character: CharacterSummary,
  accessSessionId: string,
): Promise<Seat> {
  await json(await request.post(`/api/rooms/${roomId}/campaigns/${campaignId}/roster`, {
    data: { character_id: character.id, status: 'active' },
  }))
  const seat = await addSeat(request, roomId, campaignId, 'player', accessSessionId)
  await json(await request.patch(
    `/api/rooms/${roomId}/campaigns/${campaignId}/seats/${seat.id}/character`,
    { data: { selected_character_id: character.id } },
  ))
  return seat
}

async function startSession(page: Page, roomId: string, campaignId: string): Promise<string> {
  await page.goto(`/rooms/${roomId}/campaigns/${campaignId}/lobby`)
  await expect(page.getByRole('heading', { name: 'Lobby & Seats', level: 1 })).toBeVisible()
  await page.getByRole('button', { name: 'Start Session' }).click()
  await expect(page).toHaveURL(
    new RegExp(`/rooms/${roomId}/campaigns/${campaignId}/sessions/[0-9a-fA-F-]{36}/?$`),
  )
  const sessionId = page.url().match(/\/sessions\/([0-9a-fA-F-]{36})\/?$/)?.[1]
  expect(sessionId).toBeTruthy()
  await expect(page.getByRole('heading', { name: 'Active Session', level: 1 })).toBeVisible()
  return sessionId!
}

async function openSessionAs(
  browser: Browser,
  grant: RoomGrant,
  roomContext: { roomId: string; code: string; name: string },
  sessionUrl: string,
): Promise<{ context: BrowserContext; page: Page }> {
  const context = await browser.newContext({ baseURL: PLAYWRIGHT_BASE_URL })
  const page = await context.newPage()
  await page.goto('/')
  await page.evaluate(
    ({ recentKey, activeKey, localeKey, room }) => {
      window.localStorage.setItem(recentKey, JSON.stringify([room]))
      window.localStorage.setItem(localeKey, 'en')
      window.sessionStorage.setItem(activeKey, room.roomId)
    },
    {
      recentKey: RECENT_ROOMS_STORAGE_KEY,
      activeKey: ACTIVE_ROOM_STORAGE_KEY,
      localeKey: LOCALE_STORAGE_KEY,
      room: {
        roomId: roomContext.roomId,
        code: roomContext.code,
        name: roomContext.name,
        accessToken: grant.access_token,
        authority: grant.authority,
      },
    },
  )
  await page.goto(sessionUrl)
  await expect(page.getByRole('heading', { name: 'Active Session', level: 1 })).toBeVisible()
  return { context, page }
}

function combatStage(page: Page): Locator {
  return page.getByRole('region', { name: 'Combat' })
}

function combatantCard(page: Page, entryId: string): Locator {
  return page.locator(`.session-combat__card[data-combat-entry="${entryId}"]`)
}

function initiativeRow(page: Page, entryId: string): Locator {
  return page.locator(`.session-combat__initiative-row[data-combat-entry="${entryId}"]`)
}

async function readDetail(request: APIRequestContext, prefix: string): Promise<CombatDetail> {
  const detail = await json<CombatDetail | null>(await request.get(`${prefix}/combat/detail`))
  expect(detail).not.toBeNull()
  return detail!
}

function entryNamed(detail: CombatDetail, name: string): CombatEntry {
  const entry = detail.entries.find((item) => item.display_name === name)
  expect(entry, `combat entry ${name}`).toBeTruthy()
  return entry!
}

function combatantOf(detail: CombatDetail, entryId: string) {
  const combatant = detail.combatants.find((item) => item.entry_id === entryId)
  expect(combatant, `combatant ${entryId}`).toBeTruthy()
  return combatant!
}

async function pickSrdMonster(page: Page, name: string) {
  const input = page.getByRole('combobox', { name: 'Choose Monster' })
  await input.fill(name)
  const listboxId = await input.getAttribute('aria-controls')
  expect(listboxId).toBeTruthy()
  const option = page
    .locator(`[id="${listboxId}"]`)
    .getByRole('option')
    .filter({ has: page.locator('span', { hasText: new RegExp(`^${name}$`) }) })
  await expect(option).toHaveCount(1)
  await option.click()
}

async function advanceUntilTurn(
  page: Page,
  request: APIRequestContext,
  prefix: string,
  entryId: string,
): Promise<void> {
  for (let step = 0; step < 4; step += 1) {
    const detail = await readDetail(request, prefix)
    if (detail.current_turn_entry_id === entryId) return
    const advanced = page.waitForResponse((response) => (
      response.request().method() === 'POST' && response.url().includes('/combat/turn/advance')
    ))
    await page.getByRole('button', { name: 'Advance Turn' }).click()
    await responseJson(await advanced)
  }
  throw new Error(`turn never reached ${entryId}`)
}

/**
 * Player declares an Attack from the Quick Action Bar; the DM confirms range in
 * the adjudication panel; the Player rolls. Returns the server resolution.
 */
async function playerAttack(
  dm: Page,
  player: Page,
  sessionId: string,
  targetName: string,
): Promise<AttackResolution> {
  const actionBar = player.locator('[data-combat-action-bar="true"]')
  await expect(actionBar).toHaveAttribute('data-combat-action-state', 'ready')
  await actionBar.getByRole('combobox', { name: 'Action kind' }).selectOption('attack')
  await expect(actionBar.getByRole('combobox', { name: 'Attack', exact: true })).toContainText('Battleaxe')
  await actionBar.getByRole('combobox', { name: 'Target' }).selectOption({ label: targetName })

  const requested = player.waitForResponse((response) => (
    response.request().method() === 'POST'
    && response.url().includes(`/sessions/${sessionId}/combat/attacks/request`)
  ))
  await actionBar.getByRole('button', { name: 'Request Attack' }).click()
  const attackRequest = await responseJson<AttackRequest>(await requested)
  // A Player never confirms geometry: the attack waits for DM range adjudication.
  expect(attackRequest.roll_request_id).toBeNull()
  await expect(actionBar).toHaveAttribute('data-combat-action-state', 'adjudication-pending')
  await expect(actionBar.getByText('Waiting for DM adjudication', { exact: true })).toBeVisible()

  const adjudication = dm.locator(`[data-adjudication-id="${attackRequest.action_id}"]`)
  await expect(adjudication).toHaveAttribute('data-adjudication-kind', 'range')
  const adjudicated = dm.waitForResponse((response) => (
    response.request().method() === 'POST'
    && response.url().includes(`/sessions/${sessionId}/combat/attacks/adjudicate`)
  ))
  await adjudication.getByRole('button', { name: 'In range' }).click()
  await responseJson(await adjudicated)
  await expect(adjudication).toHaveCount(0)

  const pendingRoll = actionBar.locator('[data-pending-roll]').first()
  await expect(pendingRoll).toBeVisible()
  const rolled = player.waitForResponse((response) => (
    response.request().method() === 'POST'
    && response.url().includes(`/sessions/${sessionId}/combat/attacks/roll`)
  ))
  await pendingRoll.click()
  return responseJson<AttackResolution>(await rolled)
}

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
