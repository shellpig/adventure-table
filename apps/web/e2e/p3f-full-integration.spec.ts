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
const ONE_PIXEL_PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Zl1sAAAAASUVORK5CYII=',
  'base64',
)

type Campaign = { id: string }
type CharacterSummary = { id: string; name: string }
type CharacterImportResult = {
  character_id: string | null
  character_preview: { name: string }
}
type PersistedCharacter = {
  id: string
  state: { temporary_hp: number }
}
type Seat = { id: string; label: string | null }
type Lobby = { caller_access_session_id: string | null }
type RoomGrant = {
  room: { id: string; code: string; name: string }
  authority: 'member' | 'dm' | 'owner'
  access_session_id: string
  access_token: string
}
type PendingAction = {
  id: string
  subject_seat_id: string
  text: string
  status: 'pending' | 'processing' | 'waiting_for_roll' | 'resolved' | 'cancelled'
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
  total: number
}
type RollSubmission = {
  result_id: string
  roll_request_id: string | null
  hidden: boolean
  result: RollResult | null
}
type TableStateResponse = {
  character_id: string
  state: { temporary_hp: number }
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

async function addDmSeat(
  request: APIRequestContext,
  roomId: string,
  campaignId: string,
  accessSessionId: string,
): Promise<Seat> {
  const seat = await json<Seat>(await request.post(
    `/api/rooms/${roomId}/campaigns/${campaignId}/seats`,
    { data: { role: 'dm', label: 'P3-F DM' } },
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
  const seat = await json<Seat>(await request.post(
    `/api/rooms/${roomId}/campaigns/${campaignId}/seats`,
    { data: { role: 'player', label: 'P3-F Player' } },
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

async function sendSlash(page: Page, command: string) {
  await page.getByPlaceholder(/Type here/).fill(command)
  await page.getByRole('button', { name: 'Send' }).click()
}

async function endSession(page: Page) {
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByRole('button', { name: 'End Session' }).click()
  await expect(page.getByText('Ended', { exact: true })).toBeVisible()
}

test('P3-F Journey F1 keeps one human exploration-to-roll-to-state path canonical through reload and End', async ({
  browser,
  page,
  request,
  roomContext,
}) => {
  const playerGrant = await enterAsMember(request, roomContext, 'P3-F Player Controller')
  const character = await importCharacter(request)
  const campaign = await createCampaign(request, roomContext.roomId, 'P3-F Full Human Journey')
  const ownerLobby = await json<Lobby>(await request.get(
    `/api/rooms/${roomContext.roomId}/campaigns/${campaign.id}/lobby`,
  ))
  expect(ownerLobby.caller_access_session_id).not.toBeNull()
  await addDmSeat(request, roomContext.roomId, campaign.id, ownerLobby.caller_access_session_id!)
  const playerSeat = await addPlayerSeat(
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

  try {
    await page.getByLabel('Stage text').fill('Rain falls over the ruined observatory.')
    await page.getByLabel('Stage image (PNG / JPEG / WebP)').setInputFiles({
      name: 'observatory.png',
      mimeType: 'image/png',
      buffer: ONE_PIXEL_PNG,
    })
    await page.getByRole('button', { name: 'Update Stage' }).click()
    await expect(player.page.getByText('Rain falls over the ruined observatory.', { exact: true })).toBeVisible()
    await expect(player.page.locator('.session-stage img')).toBeVisible()

    await player.page
      .getByRole('combobox', { name: 'Character', exact: true })
      .selectOption(playerSeat.id)

    await sendSlash(player.page, '/action I pry open the brass hatch.')
    await expect(page.getByText('I pry open the brass hatch.', { exact: true })).toBeVisible()

    await sendSlash(player.page, '/search hidden star chart')
    await expect(page.getByText('hidden star chart', { exact: true })).toBeVisible()

    await sendSlash(player.page, '/ooc checking the north wall first')
    await expect(page.getByText('checking the north wall first', { exact: true })).toBeVisible()

    await sendSlash(player.page, '/whisper The hatch has my family crest.')
    await expect(page.getByText('The hatch has my family crest.', { exact: true })).toBeVisible()

    const pendingResponsePromise = player.page.waitForResponse((response) => (
      response.request().method() === 'POST'
      && response.url().includes(`/sessions/${sessionId}/pending-actions`)
    ))
    await sendSlash(player.page, '/check inspect the star chart')
    const pendingAction = await responseJson<PendingAction>(await pendingResponsePromise)
    expect(pendingAction).toMatchObject({
      subject_seat_id: playerSeat.id,
      text: 'inspect the star chart',
      status: 'pending',
    })

    const rollRequestsBefore = await json<RollRequest[]>(await request.get(`${prefix}/roll-requests`))
    expect(rollRequestsBefore).toHaveLength(0)

    await page.getByRole('button', { name: 'Dice', exact: true }).click()
    const target = page.getByRole('checkbox', { name: /P3-F Player/ })
    await expect(target).toBeChecked()
    await page.getByRole('combobox', { name: 'Check type' }).selectOption('skill')
    await page.getByRole('combobox', { name: 'Skill' }).selectOption('srd5.1:skill:investigation')
    await page.getByLabel('DC (optional)', { exact: true }).fill('17')
    await page.getByRole('combobox', { name: 'Roll mode' }).selectOption('normal')
    await page.getByRole('combobox', { name: 'Result visibility' }).selectOption('roller_dm')
    await page.getByLabel('Label', { exact: true }).fill('Read the star chart')

    const checkResponsePromise = page.waitForResponse((response) => (
      response.request().method() === 'POST'
      && response.url().includes(`/sessions/${sessionId}/checks`)
    ))
    await page.getByRole('button', { name: 'Create Check' }).click()
    const check = await responseJson<RequestCheckResponse>(await checkResponsePromise)
    expect(check.requests).toHaveLength(1)
    const rollRequestId = check.requests[0].id
    expect(check.requests[0]).toMatchObject({
      target_seat_id: playerSeat.id,
      dc: 17,
      status: 'pending',
    })

    await player.page.getByRole('button', { name: 'Dice', exact: true }).click()
    const playerRequest = player.page.locator('.session-roll-request').filter({
      has: player.page.getByText('Read the star chart', { exact: true }),
    })
    await expect(playerRequest).toHaveAttribute('data-roll-request-status', 'pending')
    await expect(playerRequest.getByText('DC 17', { exact: true })).toHaveCount(0)

    const rollResponsePromise = player.page.waitForResponse((response) => (
      response.request().method() === 'POST'
      && response.url().includes(`/sessions/${sessionId}/rolls/formal`)
    ))
    await playerRequest.getByRole('button', { name: 'Roll formally' }).click()
    const rollSubmission = await responseJson<RollSubmission>(await rollResponsePromise)
    expect(rollSubmission.hidden).toBe(false)
    expect(rollSubmission.result).not.toBeNull()
    const result = rollSubmission.result!
    expect(result.roll_request_id).toBe(rollRequestId)
    expect(result.raw_dice).toHaveLength(1)

    const stateResponse = await json<TableStateResponse>(await request.patch(
      `${prefix}/character-state/${playerSeat.id}`,
      {
        data: { temporary_hp: 3, idempotency_key: 'p3f-e2e-temp-hp' },
        headers: { Authorization: `Bearer ${playerGrant.access_token}` },
      },
    ))
    expect(stateResponse.character_id).toBe(character.id)
    expect(stateResponse.state.temporary_hp).toBe(3)

    await Promise.all([page.reload(), player.page.reload()])
    await expect(page.getByRole('heading', { name: 'Active Session', level: 1 })).toBeVisible()
    await expect(player.page.getByRole('heading', { name: 'Active Session', level: 1 })).toBeVisible()
    await expect(
      page.locator('.session-stage__canvas').getByText(
        'Rain falls over the ruined observatory.',
        { exact: true },
      ),
    ).toBeVisible()
    await expect(player.page.getByText('I pry open the brass hatch.', { exact: true })).toBeVisible()

    await player.page.getByRole('button', { name: 'Dice', exact: true }).click()
    const reloadedRequest = player.page.locator('.session-roll-request').filter({
      has: player.page.getByText('Read the star chart', { exact: true }),
    })
    await expect(reloadedRequest).toHaveAttribute('data-roll-request-status', 'resolved')
    await expect(reloadedRequest.getByText(`Total: ${result.total}`, { exact: true })).toBeVisible()
    await expect(reloadedRequest.getByText('DC 17', { exact: true })).toHaveCount(0)

    const persistedBeforeEnd = await json<PersistedCharacter>(
      await request.get(`/api/characters/${character.id}`),
    )
    expect(persistedBeforeEnd.state.temporary_hp).toBe(3)
  } finally {
    await player.context.close()
  }

  await endSession(page)

  const persistedAfterEnd = await json<PersistedCharacter>(
    await request.get(`/api/characters/${character.id}`),
  )
  expect(persistedAfterEnd.state.temporary_hp).toBe(3)
})
