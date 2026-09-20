import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'

import { expect, test, type APIRequestContext, type Browser, type BrowserContext, type Page } from './support/roomTest'

// Direct backend MCP endpoint, the same way p3e-mcp-browser-integration reaches it.
const MCP_ENDPOINT = process.env.PLAYWRIGHT_MCP_URL ?? 'http://127.0.0.1:8000/mcp'
const MCP_PROTOCOL_VERSION = '2026-07-28'
const PLAYWRIGHT_BASE_URL = process.env.PLAYWRIGHT_BASE_URL ?? 'http://127.0.0.1:4173'
const ROOM_PASSWORD = 'p2-e2e-room-pass'
const RECENT_ROOMS_STORAGE_KEY = 'adventure-table.recent-rooms.v1'
const ACTIVE_ROOM_STORAGE_KEY = 'adventure-table.active-room.v1'
const LOCALE_STORAGE_KEY = 'adventure-table.locale'
const IMPORT_FIXTURE = resolve(process.cwd(), '../server/tests/data/m03/fixture_low_level_srd.json')
const AI_NARRATION = 'Dust falls from the rafters as the door groans shut.'
const SECRET_GLANCE = 'M05 secret glance at the sigil'

type Campaign = { id: string }
type Seat = { id: string }
type Lobby = { caller_access_session_id: string | null }
type AIDMGrant = { token: string }
type RoomGrant = { access_token: string; authority: string; access_session_id: string }
type CharacterImportResult = { character_id: string | null }
type SessionSnapshot = { id: string; status: string; dm_controller_kind: string }
type SessionResume = { active_session: SessionSnapshot | null }
type McpToolCallResult<T> = {
  isError: boolean
  structuredContent: { ok: true; data: T } | { ok: false; error: { code: string; messages: { en: string } } }
}

let nextMcpRequestId = 1

async function json<T>(response: Awaited<ReturnType<APIRequestContext['get']>>): Promise<T> {
  if (!response.ok()) expect(response.ok(), await response.text()).toBe(true)
  return response.json() as Promise<T>
}

async function mcpToolData<T>(
  request: APIRequestContext,
  token: string,
  name: string,
  arguments_: Record<string, unknown>,
): Promise<T> {
  const id = nextMcpRequestId++
  const response = await request.post(MCP_ENDPOINT, {
    data: {
      jsonrpc: '2.0',
      id,
      method: 'tools/call',
      params: {
        name,
        arguments: arguments_,
        _meta: {
          'io.modelcontextprotocol/protocolVersion': MCP_PROTOCOL_VERSION,
          'io.modelcontextprotocol/clientCapabilities': {},
        },
      },
    },
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
      'MCP-Protocol-Version': MCP_PROTOCOL_VERSION,
      'Mcp-Method': 'tools/call',
      'Mcp-Name': name,
    },
  })
  const body = await response.json() as { id: number; result?: McpToolCallResult<T> }
  expect(response.ok(), JSON.stringify(body)).toBe(true)
  expect(body.id).toBe(id)
  const result = body.result!
  if (!result.structuredContent.ok) {
    throw new Error(`MCP tool ${name} failed: ${result.structuredContent.error.code} ${result.structuredContent.error.messages.en}`)
  }
  expect(result.isError).toBe(false)
  return result.structuredContent.data
}

// Owner-side setup: an active Campaign whose DM Seat carries a pre-session AI DM grant.
async function createAiDmCampaign(request: APIRequestContext, roomId: string, name: string) {
  const campaign = await json<Campaign>(await request.post(`/api/rooms/${roomId}/campaigns`, {
    data: { name, ruleset: 'dnd5e-2014' },
  }))
  await json(await request.patch(`/api/rooms/${roomId}/campaigns/${campaign.id}/status`, {
    data: { status: 'active' },
  }))
  await json(await request.post(`/api/rooms/${roomId}/campaigns/${campaign.id}/select`))
  const dmSeat = await json<Seat>(await request.post(
    `/api/rooms/${roomId}/campaigns/${campaign.id}/seats`,
    { data: { role: 'dm', label: `${name} DM` } },
  ))
  const grant = await json<AIDMGrant>(await request.post(
    `/api/rooms/${roomId}/campaigns/${campaign.id}/seats/${dmSeat.id}/ai-dm-grant`,
  ))
  return { campaign, dmSeat, aiDmToken: grant.token }
}

async function enterAsMember(request: APIRequestContext, code: string, displayName: string): Promise<RoomGrant> {
  return json<RoomGrant>(await request.post('/api/rooms/enter', {
    data: { code, password: ROOM_PASSWORD, display_name: displayName },
  }))
}

async function importCharacter(request: APIRequestContext): Promise<string> {
  const envelope = await readFile(IMPORT_FIXTURE, 'utf8')
  const result = await json<CharacterImportResult>(await request.post('/api/characters/import', {
    data: envelope,
    headers: { 'Content-Type': 'application/json' },
  }))
  expect(result.character_id).not.toBeNull()
  return result.character_id!
}

// A human-controlled Player Seat with a Character; bound before the first Session
// starts so the member is a participant of both Sessions and can be the target of a Check.
async function addPlayerSeat(
  request: APIRequestContext,
  roomId: string,
  campaignId: string,
  label: string,
  accessSessionId: string,
): Promise<Seat> {
  const characterId = await importCharacter(request)
  await json(await request.post(`/api/rooms/${roomId}/campaigns/${campaignId}/roster`, {
    data: { character_id: characterId, status: 'active' },
  }))
  const seat = await json<Seat>(await request.post(
    `/api/rooms/${roomId}/campaigns/${campaignId}/seats`,
    { data: { role: 'player', label } },
  ))
  await json(await request.patch(
    `/api/rooms/${roomId}/campaigns/${campaignId}/seats/${seat.id}/controller`,
    { data: { controller_kind: 'human', controller_access_session_id: accessSessionId } },
  ))
  await json(await request.patch(
    `/api/rooms/${roomId}/campaigns/${campaignId}/seats/${seat.id}/character`,
    { data: { selected_character_id: characterId } },
  ))
  return seat
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

// Pages the chat backwards until the given text from an earlier Session appears.
async function loadEarlierUntilVisible(page: Page, text: string) {
  await page.getByRole('button', { name: 'Chat', exact: true }).click()
  for (let attempt = 0; attempt < 4 && (await page.getByText(text).count()) === 0; attempt += 1) {
    await page.locator('[data-chat-load-older]').click()
    await expect(page.locator('[data-chat-load-older]')).toBeEnabled()
  }
  await expect(page.getByText(text)).toBeVisible()
}

async function getActiveSession(request: APIRequestContext, roomId: string, campaignId: string) {
  return json<SessionResume>(await request.get(`/api/rooms/${roomId}/campaigns/${campaignId}/sessions/active`))
}

async function openSessionPage(page: Page, roomId: string, campaignId: string, sessionId: string) {
  await page.goto(`/rooms/${roomId}/campaigns/${campaignId}/sessions/${sessionId}`)
  await expect(page.getByRole('heading', { name: 'Active Session', level: 1 })).toBeVisible()
}

test('M05 Owner ends an AI DM Session, restarts as human DM, and the chat pages back across the boundary', async ({
  browser,
  page,
  request,
  roomContext,
}) => {
  const { campaign, dmSeat, aiDmToken } = await createAiDmCampaign(request, roomContext.roomId, 'M05-A AI DM')
  const mira = await enterAsMember(request, roomContext.code, 'Mira')
  const kael = await enterAsMember(request, roomContext.code, 'Kael')
  const miraSeat = await addPlayerSeat(request, roomContext.roomId, campaign.id, 'Mira Seat', mira.access_session_id)
  await addPlayerSeat(request, roomContext.roomId, campaign.id, 'Kael Seat', kael.access_session_id)

  // The AI DM opens the Session through MCP and leaves one narration on the table.
  const started = await mcpToolData<SessionSnapshot>(request, aiDmToken, 'start_session', {})
  expect(started.dm_controller_kind).toBe('ai')
  await mcpToolData(request, aiDmToken, 'set_stage_text', { expected_revision: 0, text: 'The Old Mill Basement' })
  await mcpToolData(request, aiDmToken, 'post_narration', { text: AI_NARRATION })
  // A roller-and-DM Check addressed to Mira's Seat: its prompt is seat-private, so
  // Kael must not see it when paging back into this Session later.
  await mcpToolData(request, aiDmToken, 'request_check', {
    target_seat_ids: [miraSeat.id],
    request_type: 'skill',
    skill_ref: 'perception',
    visibility: 'roller_and_dm',
    label: SECRET_GLANCE,
  })

  await openSessionPage(page, roomContext.roomId, campaign.id, started.id)

  // The Owner holds no Seat in this Session, so the table stream is not readable for them
  // (pre-M05 behaviour, unchanged here); the Session-management controls still are.
  // Owner is not this Session's DM Controller: End is offered because the DM is an AI, Abandon stays as well.
  await expect(page.getByText(/This Session is run by an AI DM/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Abandon Session' })).toBeVisible()
  page.once('dialog', (dialog) => {
    expect(dialog.message()).toContain('End this AI DM Session?')
    void dialog.accept()
  })
  await page.getByRole('button', { name: 'End Session' }).click()
  await expect(page.getByText('Ended', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'End Session' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Abandon Session' })).toHaveCount(0)

  // The old AI DM credential is revoked by the End.
  const revoked = await request.post(MCP_ENDPOINT, {
    data: {
      jsonrpc: '2.0', id: 'm05a-revoked', method: 'tools/call',
      params: {
        name: 'get_session_context', arguments: {},
        _meta: { 'io.modelcontextprotocol/protocolVersion': MCP_PROTOCOL_VERSION, 'io.modelcontextprotocol/clientCapabilities': {} },
      },
    },
    headers: {
      Authorization: `Bearer ${aiDmToken}`,
      'Content-Type': 'application/json',
      'MCP-Protocol-Version': MCP_PROTOCOL_VERSION,
      'Mcp-Method': 'tools/call',
      'Mcp-Name': 'get_session_context',
    },
  })
  expect([401, 403]).toContain(revoked.status())

  // Lobby has no active Session; the Owner takes the DM Seat as a human and starts the next one.
  expect((await getActiveSession(request, roomContext.roomId, campaign.id)).active_session).toBeNull()
  await page.getByRole('link', { name: 'Back to Lobby' }).click()
  await expect(page.getByRole('heading', { name: 'Lobby & Seats', level: 1 })).toBeVisible()

  const lobby = await json<Lobby>(await request.get(`/api/rooms/${roomContext.roomId}/campaigns/${campaign.id}/lobby`))
  expect(lobby.caller_access_session_id).not.toBeNull()
  await json(await request.patch(
    `/api/rooms/${roomContext.roomId}/campaigns/${campaign.id}/seats/${dmSeat.id}/controller`,
    { data: { controller_kind: 'human', controller_access_session_id: lobby.caller_access_session_id } },
  ))
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Lobby & Seats', level: 1 })).toBeVisible()
  await page.getByRole('button', { name: 'Start Session' }).click()
  await expect(page).toHaveURL(
    new RegExp(`/rooms/${roomContext.roomId}/campaigns/${campaign.id}/sessions/[0-9a-fA-F-]{36}/?$`),
  )
  await expect(page.getByRole('heading', { name: 'Active Session', level: 1 })).toBeVisible()

  const resumed = await getActiveSession(request, roomContext.roomId, campaign.id)
  expect(resumed.active_session?.dm_controller_kind).toBe('human')
  expect(resumed.active_session?.id).not.toBe(started.id)
  // The human DM has the normal End; the Owner-on-AI-DM hint is gone.
  await expect(page.getByRole('button', { name: 'End Session' })).toBeVisible()
  await expect(page.getByText(/This Session is run by an AI DM/)).toHaveCount(0)

  // ---- M05-B: the new Session's chat pages back into the AI DM Session ----
  const sessionUrl = page.url()
  await page.getByRole('button', { name: 'Chat', exact: true }).click()
  await page.getByRole('combobox', { name: 'Type', exact: true }).selectOption('narration')
  await page.getByPlaceholder(/Type here/).fill('The party regroups at dawn.')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.getByText('The party regroups at dawn.', { exact: true })).toBeVisible()

  await loadEarlierUntilVisible(page, AI_NARRATION)
  const divider = page.locator(`[data-session-divider="${started.id}"]`)
  await expect(divider).toBeVisible()
  await expect(divider).toContainText('Earlier Session (ended)')
  await expect(divider).toContainText('DM: AI')
  // The human DM now holds the old Session's DM Seat, so its DM-layer prompt is visible to them.
  await expect(page.getByText(SECRET_GLANCE)).toBeVisible()
  // Divider, then the earlier narration, then this Session's narration.
  const order = await page.locator('.session-chat__messages').evaluate((node) => node.textContent ?? '')
  expect(order.indexOf('Earlier Session (ended)')).toBeLessThan(order.indexOf(AI_NARRATION))
  expect(order.indexOf(AI_NARRATION)).toBeLessThan(order.indexOf('The party regroups at dawn.'))
  // One more click reaches the beginning of the Campaign.
  await page.locator('[data-chat-load-older]').click()
  await expect(page.locator('[data-chat-history-start]')).toBeVisible()
  await expect(page.locator('[data-chat-load-older]')).toHaveCount(0)
  // Stage stays on the current Session.
  await expect(page.getByText('The Old Mill Basement')).toHaveCount(0)

  // Kael (another Player Seat) sees the public narration but not Mira's seat-private prompt.
  const kaelView = await openSessionAs(browser, kael, roomContext, sessionUrl)
  try {
    await loadEarlierUntilVisible(kaelView.page, AI_NARRATION)
    await expect(kaelView.page.locator(`[data-session-divider="${started.id}"]`)).toBeVisible()
    await expect(kaelView.page.getByText(SECRET_GLANCE)).toHaveCount(0)
  } finally {
    await kaelView.context.close()
  }

  // Mira, whose Seat the prompt addressed, does see it across the boundary.
  const miraView = await openSessionAs(browser, mira, roomContext, sessionUrl)
  try {
    await loadEarlierUntilVisible(miraView.page, SECRET_GLANCE)
  } finally {
    await miraView.context.close()
  }
})
