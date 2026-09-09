import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'

import {
  expect,
  test,
  type APIRequestContext,
  type Browser,
  type BrowserContext,
  type Page,
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
type Seat = {
  id: string
  label: string | null
  controller_kind: 'human' | 'ai' | 'none'
  controller_access_session_id: string | null
}
type Lobby = {
  caller_access_session_id: string | null
  seats: Seat[]
}
type RoomGrant = {
  room: { id: string; code: string; name: string }
  authority: 'member' | 'dm' | 'owner'
  access_session_id: string
  access_token: string
}
type TableEvent = {
  seq: number
  kind: string
  acting_seat_id: string | null
  subject_seat_id: string | null
  execution_mode: string | null
  payload: Record<string, unknown>
}
type EventPage = { events: TableEvent[] }

async function json<T>(response: Awaited<ReturnType<APIRequestContext['get']>>): Promise<T> {
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

async function addCharacterAndPlayerSeat(
  request: APIRequestContext,
  roomId: string,
  campaignId: string,
  character: CharacterSummary,
  label: string,
  accessSessionId: string,
): Promise<Seat> {
  await json(await request.post(`/api/rooms/${roomId}/campaigns/${campaignId}/roster`, {
    data: { character_id: character.id, status: 'active' },
  }))
  const seat = await json<Seat>(await request.post(
    `/api/rooms/${roomId}/campaigns/${campaignId}/seats`,
    { data: { role: 'player', label } },
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

async function addDmSeat(
  request: APIRequestContext,
  roomId: string,
  campaignId: string,
  accessSessionId: string,
  label: string,
): Promise<Seat> {
  const seat = await json<Seat>(await request.post(
    `/api/rooms/${roomId}/campaigns/${campaignId}/seats`,
    { data: { role: 'dm', label } },
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

async function sendComposer(
  page: Page,
  options: { kind: 'dialogue' | 'action' | 'ooc' | 'whisper_dm'; text: string; subjectSeatId?: string },
) {
  await page.getByLabel('Type').selectOption(options.kind)
  if (options.subjectSeatId) {
    await page.getByLabel('Character').selectOption(options.subjectSeatId)
  }
  await page.getByPlaceholder(/Type here/).fill(options.text)
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.getByText(options.text, { exact: true })).toBeVisible()
}

async function endSession(page: Page) {
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByRole('button', { name: 'End Session' }).click()
  await expect(page.getByText('Ended', { exact: true })).toBeVisible()
}

test('P3-B Journey B1 keeps Stage, public stream, and own Whisper correct through reload', async ({
  browser,
  page,
  request,
  roomContext,
}) => {
  const p1Grant = await enterAsMember(request, roomContext, 'B1 Player One')
  const p2Grant = await enterAsMember(request, roomContext, 'B1 Player Two')
  const p1Character = await importCharacter(request)
  const p2Character = await importCharacter(request)
  const campaign = await createCampaign(request, roomContext.roomId, 'P3-B Journey B1')

  const ownerLobby = await json<Lobby>(await request.get(
    `/api/rooms/${roomContext.roomId}/campaigns/${campaign.id}/lobby`,
  ))
  expect(ownerLobby.caller_access_session_id).not.toBeNull()
  await addDmSeat(
    request,
    roomContext.roomId,
    campaign.id,
    ownerLobby.caller_access_session_id!,
    'B1 DM',
  )
  const p1Seat = await addCharacterAndPlayerSeat(
    request,
    roomContext.roomId,
    campaign.id,
    p1Character,
    'B1 Player One',
    p1Grant.access_session_id,
  )
  await addCharacterAndPlayerSeat(
    request,
    roomContext.roomId,
    campaign.id,
    p2Character,
    'B1 Player Two',
    p2Grant.access_session_id,
  )

  const sessionId = await startSession(page, roomContext.roomId, campaign.id)
  const sessionUrl = `/rooms/${roomContext.roomId}/campaigns/${campaign.id}/sessions/${sessionId}`
  const p1 = await openSessionAs(browser, p1Grant, roomContext, sessionUrl)
  const p2 = await openSessionAs(browser, p2Grant, roomContext, sessionUrl)

  try {
    await page.getByLabel('Stage text').fill('Moonlit archive')
    await page.getByLabel('Stage image (PNG / JPEG / WebP)').setInputFiles({
      name: 'moon.png',
      mimeType: 'image/png',
      buffer: ONE_PIXEL_PNG,
    })
    await page.getByRole('button', { name: 'Update Stage' }).click()
    await expect(page.getByText('Moonlit archive', { exact: true })).toBeVisible()
    await expect(p1.page.getByText('Moonlit archive', { exact: true })).toBeVisible()
    await expect(p2.page.getByText('Moonlit archive', { exact: true })).toBeVisible()
    await expect(p1.page.locator('.session-stage img')).toBeVisible()

    await sendComposer(p1.page, {
      kind: 'dialogue',
      subjectSeatId: p1Seat.id,
      text: 'I found the ledger.',
    })
    await sendComposer(p1.page, {
      kind: 'action',
      subjectSeatId: p1Seat.id,
      text: 'I inspect the locked drawer.',
    })
    await p1.page.getByPlaceholder(/Type here/).fill('/search hidden compartment')
    await p1.page.getByRole('button', { name: 'Send' }).click()
    await expect(p1.page.getByText('hidden compartment', { exact: true })).toBeVisible()

    await sendComposer(p1.page, {
      kind: 'ooc',
      text: 'OOC from player one',
    })
    const ooc = page.locator('.session-chat__message').filter({ hasText: 'OOC from player one' })
    await expect(ooc.getByText('B1 Player One', { exact: true })).toBeVisible()
    await expect(ooc.getByText('OOC', { exact: true })).toBeVisible()

    const secret = 'Only the DM should know this.'
    await sendComposer(p1.page, { kind: 'whisper_dm', text: secret })
    const dmWhisper = page.locator('.session-chat__message').filter({ hasText: secret })
    await expect(dmWhisper.getByText('B1 Player One', { exact: true })).toBeVisible()
    await expect(dmWhisper.getByText('You + DM only', { exact: true })).toBeVisible()
    await expect(p2.page.getByText(secret, { exact: true })).toHaveCount(0)

    await page.reload()
    await p1.page.reload()
    await p2.page.reload()
    await expect(page.getByText('Moonlit archive', { exact: true })).toBeVisible()
    await expect(p1.page.getByText('Moonlit archive', { exact: true })).toBeVisible()
    await expect(p1.page.getByText('I found the ledger.', { exact: true })).toBeVisible()
    await expect(p1.page.getByText(secret, { exact: true })).toBeVisible()
    await expect(page.getByText(secret, { exact: true })).toBeVisible()
    await expect(p2.page.getByText(secret, { exact: true })).toHaveCount(0)
  } finally {
    await p1.context.close()
    await p2.context.close()
  }

  await endSession(page)
})

test('P3-B Journey B2 DM proxy keeps acting DM and subject Player identity without controller handoff', async ({
  page,
  request,
  roomContext,
}) => {
  const playerGrant = await enterAsMember(request, roomContext, 'B2 Mira Controller')
  const character = await importCharacter(request)
  const campaign = await createCampaign(request, roomContext.roomId, 'P3-B Journey B2')
  const ownerLobby = await json<Lobby>(await request.get(
    `/api/rooms/${roomContext.roomId}/campaigns/${campaign.id}/lobby`,
  ))
  expect(ownerLobby.caller_access_session_id).not.toBeNull()
  const dmSeat = await addDmSeat(
    request,
    roomContext.roomId,
    campaign.id,
    ownerLobby.caller_access_session_id!,
    'B2 DM',
  )
  const playerSeat = await addCharacterAndPlayerSeat(
    request,
    roomContext.roomId,
    campaign.id,
    character,
    'B2 Mira',
    playerGrant.access_session_id,
  )

  const sessionId = await startSession(page, roomContext.roomId, campaign.id)
  await sendComposer(page, {
    kind: 'action',
    subjectSeatId: playerSeat.id,
    text: 'Mira checks the silent corridor.',
  })

  const rendered = page.locator('.session-chat__message').filter({
    hasText: 'Mira checks the silent corridor.',
  })
  await expect(rendered.getByText('B2 Mira', { exact: true })).toBeVisible()
  await expect(rendered.getByText('DM proxy', { exact: true })).toBeVisible()

  const prefix = (
    `/api/rooms/${roomContext.roomId}/campaigns/${campaign.id}`
    + `/sessions/${sessionId}`
  )
  const events = await json<EventPage>(await request.get(`${prefix}/events?after=0&limit=50`))
  const proxy = events.events.find((event) => event.payload.text === 'Mira checks the silent corridor.')
  expect(proxy).toMatchObject({
    kind: 'exploration.action',
    acting_seat_id: dmSeat.id,
    subject_seat_id: playerSeat.id,
    execution_mode: 'dm_proxy',
  })

  const lobbyAfter = await json<Lobby>(await request.get(
    `/api/rooms/${roomContext.roomId}/campaigns/${campaign.id}/lobby`,
  ))
  const playerAfter = lobbyAfter.seats.find((seat) => seat.id === playerSeat.id)
  expect(playerAfter).toMatchObject({
    controller_kind: 'human',
    controller_access_session_id: playerGrant.access_session_id,
  })

  await endSession(page)
})
