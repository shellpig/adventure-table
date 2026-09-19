import { spawnSync } from 'node:child_process'
import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'

import {
  expect,
  type APIRequestContext,
  type Browser,
  type BrowserContext,
  type Locator,
  type Page,
  type Response,
} from './roomTest'

export const ROOM_PASSWORD = 'p2-e2e-room-pass'
export const RECENT_ROOMS_STORAGE_KEY = 'adventure-table.recent-rooms.v1'
export const ACTIVE_ROOM_STORAGE_KEY = 'adventure-table.active-room.v1'
export const LOCALE_STORAGE_KEY = 'adventure-table.locale'
export const PLAYWRIGHT_BASE_URL = process.env.PLAYWRIGHT_BASE_URL ?? 'http://127.0.0.1:4173'
export const IMPORT_FIXTURE = resolve(
  process.cwd(),
  '../server/tests/data/m03/fixture_low_level_srd.json',
)

export type Campaign = { id: string }
export type CharacterSummary = { id: string; name: string }
export type CharacterImportResult = {
  character_id: string | null
  character_preview: { name: string }
}
export type Seat = { id: string }
export type Lobby = { caller_access_session_id: string | null }
export type RoomGrant = {
  room: { id: string; code: string; name: string }
  authority: 'member' | 'dm' | 'owner'
  access_session_id: string
  access_token: string
}
export type CombatEntry = {
  id: string
  subject_kind: string
  character_id: string | null
  display_name: string
  status: string
  action_available: boolean
  attacks_allowed: number
  attacks_used: number
}
export type CombatantProjection = {
  name: string
  armor_class?: number | null
  current_hp?: number | null
  max_hp?: number | null
  position_note?: string | null
  conditions: string[]
  concentration?: Record<string, unknown> | null
}
export type CombatDetail = {
  id: string
  status: string
  round_number: number | null
  current_turn_entry_id: string | null
  revision: number
  entries: CombatEntry[]
  combatants: Array<{ entry_id: string; is_hostile: boolean; projection: CombatantProjection }>
}
export type AttackRequest = { action_id: string; roll_request_id: string | null }
export type AttackResolution = {
  hit: boolean
  damage_total: number
  after_hp?: number | null
}
export type CombatAdjudication = { action_id: string; kind: string }

export async function json<T>(response: Awaited<ReturnType<APIRequestContext['get']>>): Promise<T> {
  if (!response.ok()) {
    expect(response.ok(), await response.text()).toBe(true)
  }
  return response.json() as Promise<T>
}

export async function responseJson<T>(response: Response): Promise<T> {
  if (!response.ok()) {
    expect(response.ok(), await response.text()).toBe(true)
  }
  return response.json() as Promise<T>
}

export async function importCharacter(
  request: APIRequestContext,
  fixturePath: string = IMPORT_FIXTURE,
): Promise<CharacterSummary> {
  const envelope = await readFile(fixturePath, 'utf8')
  const result = await json<CharacterImportResult>(await request.post('/api/characters/import', {
    data: envelope,
    headers: { 'Content-Type': 'application/json' },
  }))
  expect(result.character_id).not.toBeNull()
  return { id: result.character_id!, name: result.character_preview.name }
}

export async function enterAsMember(
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

export async function createCampaign(
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

export async function addSeat(
  request: APIRequestContext,
  roomId: string,
  campaignId: string,
  role: 'dm' | 'player',
  accessSessionId: string,
  labelPrefix: string = 'P4-E',
): Promise<Seat> {
  const seat = await json<Seat>(await request.post(
    `/api/rooms/${roomId}/campaigns/${campaignId}/seats`,
    { data: { role, label: role === 'dm' ? `${labelPrefix} DM` : `${labelPrefix} Player` } },
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

export async function addPlayerSeat(
  request: APIRequestContext,
  roomId: string,
  campaignId: string,
  character: CharacterSummary,
  accessSessionId: string,
  labelPrefix: string = 'P4-E',
): Promise<Seat> {
  await json(await request.post(`/api/rooms/${roomId}/campaigns/${campaignId}/roster`, {
    data: { character_id: character.id, status: 'active' },
  }))
  const seat = await addSeat(request, roomId, campaignId, 'player', accessSessionId, labelPrefix)
  await json(await request.patch(
    `/api/rooms/${roomId}/campaigns/${campaignId}/seats/${seat.id}/character`,
    { data: { selected_character_id: character.id } },
  ))
  return seat
}

export async function startSession(page: Page, roomId: string, campaignId: string): Promise<string> {
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

export async function openSessionAs(
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

export function combatStage(page: Page): Locator {
  return page.getByRole('region', { name: 'Combat' })
}

export function combatantCard(page: Page, entryId: string): Locator {
  return page.locator(`.session-combat__card[data-combat-entry="${entryId}"]`)
}

export function initiativeRow(page: Page, entryId: string): Locator {
  return page.locator(`.session-combat__initiative-row[data-combat-entry="${entryId}"]`)
}

export async function readDetail(request: APIRequestContext, prefix: string): Promise<CombatDetail> {
  const detail = await json<CombatDetail | null>(await request.get(`${prefix}/combat/detail`))
  expect(detail).not.toBeNull()
  return detail!
}

export function entryNamed(detail: CombatDetail, name: string): CombatEntry {
  const entry = detail.entries.find((item) => item.display_name === name)
  expect(entry, `combat entry ${name}`).toBeTruthy()
  return entry!
}

export function combatantOf(detail: CombatDetail, entryId: string) {
  const combatant = detail.combatants.find((item) => item.entry_id === entryId)
  expect(combatant, `combatant ${entryId}`).toBeTruthy()
  return combatant!
}

export async function pickSrdMonster(page: Page, name: string): Promise<void> {
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

export async function advanceUntilTurn(
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
export async function playerAttack(
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

export async function restartE2EServer(request: APIRequestContext): Promise<void> {
  const service = process.env.PLAYWRIGHT_E2E_SERVER_SERVICE
  if (!service) {
    throw new Error('PLAYWRIGHT_E2E_SERVER_SERVICE is not set; run through npm run test:e2e:docker')
  }
  const repoRoot = resolve(process.cwd(), '..', '..')
  const result = spawnSync('docker', ['compose', '--profile', 'e2e', 'restart', service], {
    cwd: repoRoot,
    stdio: 'inherit',
    shell: true,
  })
  if (result.status !== 0) {
    throw new Error(`docker compose restart ${service} failed with status ${result.status}`)
  }

  const deadline = Date.now() + 60_000
  while (Date.now() <= deadline) {
    try {
      if ((await request.get('/api/meta/capabilities')).ok()) return
    } catch {
      // server restarting / connection refused; retry until deadline
    }
    await new Promise((resolveWait) => setTimeout(resolveWait, 1000))
  }
  throw new Error(`Timed out waiting for E2E server to become ready after restart (${service})`)
}
