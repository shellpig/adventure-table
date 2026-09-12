import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'

import {
  expect,
  test,
  type APIRequestContext,
  type Browser,
  type BrowserContext,
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

type Campaign = { id: string }
type CharacterSummary = { id: string; name: string }
type CharacterImportResult = {
  character_id: string | null
  character_preview: { name: string }
}
type Seat = {
  id: string
  label: string | null
}
type Lobby = {
  caller_access_session_id: string | null
}
type RoomGrant = {
  room: { id: string; code: string; name: string }
  authority: 'member' | 'dm' | 'owner'
  access_session_id: string
  access_token: string
}
type RollRequest = {
  id: string
  target_seat_id: string
  dc: number | null
  status: 'pending' | 'resolved' | 'cancelled'
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
type RequestCheckResponse = {
  roll_group_id: string
  requests: RollRequest[]
}
type TableEvent = {
  seq: number
  kind: string
  payload: Record<string, unknown>
}
type EventPage = { events: TableEvent[] }

type BrowserFetchResult<T> = {
  status: number
  body: T
}

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
  return {
    id: result.character_id!,
    name: result.character_preview.name,
  }
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

async function addDmSeat(
  request: APIRequestContext,
  roomId: string,
  campaignId: string,
  accessSessionId: string,
): Promise<Seat> {
  const seat = await json<Seat>(await request.post(
    `/api/rooms/${roomId}/campaigns/${campaignId}/seats`,
    { data: { role: 'dm', label: 'C1 DM' } },
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

async function addCharacterAndPlayerSeat(
  request: APIRequestContext,
  roomId: string,
  campaignId: string,
  character: CharacterSummary,
  accessSessionId: string,
): Promise<Seat> {
  await json(await request.post(`/api/rooms/${roomId}/campaigns/${campaignId}/roster`, {
    data: { character_id: character.id, status: 'active' },
  }))
  const seat = await json<Seat>(await request.post(
    `/api/rooms/${roomId}/campaigns/${campaignId}/seats`,
    { data: { role: 'player', label: 'C1 Player' } },
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

async function browserFetch<T>(
  page: Page,
  url: string,
  token: string,
): Promise<BrowserFetchResult<T>> {
  return page.evaluate(async ({ requestUrl, accessToken }) => {
    const response = await fetch(requestUrl, {
      headers: { Authorization: `Bearer ${accessToken}` },
    })
    return {
      status: response.status,
      body: await response.json(),
    }
  }, { requestUrl: url, accessToken: token }) as Promise<BrowserFetchResult<T>>
}

async function endSession(page: Page) {
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByRole('button', { name: 'End Session' }).click()
  await expect(page.getByText('Ended', { exact: true })).toBeVisible()
}

test('P3-C Journey C1 keeps a formal roll resolved through reload without rolling twice', async ({
  browser,
  page,
  request,
  roomContext,
}) => {
  const playerGrant = await enterAsMember(request, roomContext, 'C1 Player Controller')
  const character = await importCharacter(request)
  const campaign = await createCampaign(request, roomContext.roomId, 'P3-C Journey C1')

  const ownerLobby = await json<Lobby>(await request.get(
    `/api/rooms/${roomContext.roomId}/campaigns/${campaign.id}/lobby`,
  ))
  expect(ownerLobby.caller_access_session_id).not.toBeNull()
  await addDmSeat(
    request,
    roomContext.roomId,
    campaign.id,
    ownerLobby.caller_access_session_id!,
  )
  const playerSeat = await addCharacterAndPlayerSeat(
    request,
    roomContext.roomId,
    campaign.id,
    character,
    playerGrant.access_session_id,
  )

  const sessionId = await startSession(page, roomContext.roomId, campaign.id)
  const sessionUrl = `/rooms/${roomContext.roomId}/campaigns/${campaign.id}/sessions/${sessionId}`
  const prefix = `/api/rooms/${roomContext.roomId}/campaigns/${campaign.id}/sessions/${sessionId}`
  const player = await openSessionAs(browser, playerGrant, roomContext, sessionUrl)

  let formalPostCount = 0
  player.page.on('request', (outgoing) => {
    if (
      outgoing.method() === 'POST'
      && outgoing.url().includes(`/sessions/${sessionId}/rolls/formal`)
    ) {
      formalPostCount += 1
    }
  })

  try {
    // C1: Player Action -> DM adjudicates it into one formal Request Check.
    await player.page.getByRole('combobox', { name: 'Type', exact: true }).selectOption('action')
    await player.page
      .getByRole('combobox', { name: 'Character', exact: true })
      .selectOption(playerSeat.id)
    await player.page.getByPlaceholder(/Type here/).fill('I check the door.')
    await player.page.getByRole('button', { name: 'Send' }).click()
    await expect(page.getByText('I check the door.', { exact: true })).toBeVisible()

    await page.getByRole('button', { name: 'Dice', exact: true }).click()
    const target = page.getByRole('checkbox', { name: /C1 Player/ })
    await expect(target).toBeChecked()
    await page.getByRole('combobox', { name: 'Check type' }).selectOption('skill')
    await page.getByRole('combobox', { name: 'Skill' }).selectOption('srd5.1:skill:investigation')
    await page.getByLabel('DC (optional)', { exact: true }).fill('15')
    await page.getByRole('combobox', { name: 'Roll mode' }).selectOption('normal')
    await page.getByRole('combobox', { name: 'Result visibility' }).selectOption('public')
    await page.getByLabel('Label', { exact: true }).fill('Check the door')

    const checkResponsePromise = page.waitForResponse((response) => (
      response.request().method() === 'POST'
      && response.url().includes(`/sessions/${sessionId}/checks`)
    ))
    await page.getByRole('button', { name: 'Create Check' }).click()
    const checkResponse = await responseJson<RequestCheckResponse>(await checkResponsePromise)
    expect(checkResponse.requests).toHaveLength(1)
    const rollRequestId = checkResponse.requests[0].id
    expect(checkResponse.requests[0]).toMatchObject({
      target_seat_id: playerSeat.id,
      dc: 15,
      status: 'pending',
    })
    await expect(page.getByRole('status')).toHaveText('Created 1 formal RollRequest(s).')

    const rollPrompt = `The DM asks ${character.name} to make Investigation (Skill Check): Check the door.`
    await expect(player.page.getByText(rollPrompt, { exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'Chat', exact: true }).click()
    await expect(page.getByText(rollPrompt, { exact: true })).toHaveCount(1)
    await page.getByRole('button', { name: 'Dice', exact: true }).click()

    const dmRequest = page.locator('.session-roll-request').first()
    await expect(dmRequest).toHaveAttribute('data-roll-request-status', 'pending')
    await expect(dmRequest.getByText('DC 15', { exact: true })).toBeVisible()

    // Player receives the pending request, but the secret-bearing DC projection is null.
    await player.page.getByRole('button', { name: 'Dice', exact: true }).click()
    const playerRequest = player.page.locator('.session-roll-request').first()
    await expect(playerRequest).toHaveAttribute('data-roll-request-status', 'pending')
    await expect(playerRequest.getByText('Waiting to roll', { exact: true })).toBeVisible()
    await expect(playerRequest.getByText('DC 15', { exact: true })).toHaveCount(0)

    const playerPendingProjection = await browserFetch<RollRequest[]>(
      player.page,
      `${prefix}/roll-requests`,
      playerGrant.access_token,
    )
    expect(playerPendingProjection.status).toBe(200)
    expect(playerPendingProjection.body.find((item) => item.id === rollRequestId)).toMatchObject({
      id: rollRequestId,
      target_seat_id: playerSeat.id,
      dc: null,
      status: 'pending',
    })

    // Current Player controller rolls once through the server-authoritative path.
    const rollResponsePromise = player.page.waitForResponse((response) => (
      response.request().method() === 'POST'
      && response.url().includes(`/sessions/${sessionId}/rolls/formal`)
    ))
    await playerRequest.getByRole('button', { name: 'Roll formally' }).click()
    const rollSubmission = await responseJson<RollSubmission>(await rollResponsePromise)
    expect(formalPostCount).toBe(1)
    expect(rollSubmission.hidden).toBe(false)
    expect(rollSubmission.roll_request_id).toBe(rollRequestId)
    expect(rollSubmission.result).not.toBeNull()
    const result = rollSubmission.result!
    expect(result.roll_request_id).toBe(rollRequestId)
    expect(result.raw_dice).toHaveLength(1)
    expect(result.raw_dice[0]).toBeGreaterThanOrEqual(1)
    expect(result.raw_dice[0]).toBeLessThanOrEqual(20)
    expect(result.kept_dice).toEqual(result.raw_dice)

    await expect(playerRequest).toHaveAttribute('data-roll-request-status', 'resolved')
    await expect(playerRequest.getByText(`Total: ${result.total}`, { exact: true })).toBeVisible()
    await expect(dmRequest).toHaveAttribute('data-roll-request-status', 'resolved')
    await expect(dmRequest.getByText(`Total: ${result.total}`, { exact: true })).toBeVisible()

    // DM projection keeps the DC and the durable result event exposes the audited raw/result.
    const dmRequests = await json<RollRequest[]>(await request.get(`${prefix}/roll-requests`))
    expect(dmRequests.find((item) => item.id === rollRequestId)).toMatchObject({
      dc: 15,
      status: 'resolved',
    })
    const eventsBeforeReload = await json<EventPage>(await request.get(`${prefix}/events?after=0&limit=50`))
    const resolvedBeforeReload = eventsBeforeReload.events.filter((event) => (
      event.kind === 'roll.resolved'
      && event.payload.roll_request_id === rollRequestId
    ))
    expect(resolvedBeforeReload).toHaveLength(1)
    expect(resolvedBeforeReload[0].payload).toMatchObject({
      raw_dice: result.raw_dice,
      kept_dice: result.kept_dice,
      base_modifier: result.base_modifier,
      flat_adjustment: result.flat_adjustment,
      total: result.total,
      visibility: 'public',
    })

    // Reload both sides. Canonical request remains resolved; no UI/network path rolls again.
    await Promise.all([page.reload(), player.page.reload()])
    await expect(page.getByRole('heading', { name: 'Active Session', level: 1 })).toBeVisible()
    await expect(player.page.getByRole('heading', { name: 'Active Session', level: 1 })).toBeVisible()
    await page.getByRole('button', { name: 'Dice', exact: true }).click()
    await player.page.getByRole('button', { name: 'Dice', exact: true }).click()

    const dmReloadedRequest = page.locator('.session-roll-request').first()
    const playerReloadedRequest = player.page.locator('.session-roll-request').first()
    await expect(dmReloadedRequest).toHaveAttribute('data-roll-request-status', 'resolved')
    await expect(playerReloadedRequest).toHaveAttribute('data-roll-request-status', 'resolved')
    await expect(dmReloadedRequest.getByText('DC 15', { exact: true })).toBeVisible()
    await expect(playerReloadedRequest.getByText('DC 15', { exact: true })).toHaveCount(0)
    await expect(dmReloadedRequest.getByText(`Total: ${result.total}`, { exact: true })).toBeVisible()
    await expect(playerReloadedRequest.getByText(`Total: ${result.total}`, { exact: true })).toBeVisible()
    await expect(playerReloadedRequest.getByRole('button', { name: 'Roll formally' })).toHaveCount(0)
    expect(formalPostCount).toBe(1)

    const playerReloadedProjection = await browserFetch<RollRequest[]>(
      player.page,
      `${prefix}/roll-requests`,
      playerGrant.access_token,
    )
    expect(playerReloadedProjection.status).toBe(200)
    expect(playerReloadedProjection.body.find((item) => item.id === rollRequestId)).toMatchObject({
      dc: null,
      status: 'resolved',
    })

    const eventsAfterReload = await json<EventPage>(await request.get(`${prefix}/events?after=0&limit=50`))
    const resolvedAfterReload = eventsAfterReload.events.filter((event) => (
      event.kind === 'roll.resolved'
      && event.payload.roll_request_id === rollRequestId
    ))
    expect(resolvedAfterReload).toHaveLength(1)
    expect(resolvedAfterReload[0].seq).toBe(resolvedBeforeReload[0].seq)
    expect(resolvedAfterReload[0].payload).toEqual(resolvedBeforeReload[0].payload)
  } finally {
    await player.context.close()
  }

  await endSession(page)
})
