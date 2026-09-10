import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'

import {
  expect,
  test,
  type APIRequestContext,
  type Page,
  type Response,
} from './support/roomTest'

// Automated real-backend browser/MCP wire journey. This does not replace the
// P3-E external HTTPS/TLS client gate documented in docs/P3/測試指南.md.
const ROOM_PASSWORD = 'p2-e2e-room-pass'
const IMPORT_FIXTURE = resolve(
  process.cwd(),
  '../server/tests/data/m03/fixture_low_level_srd.json',
)
const MCP_PROTOCOL_VERSION = '2026-07-28'
const MCP_ENDPOINT = process.env.PLAYWRIGHT_MCP_URL ?? 'http://127.0.0.1:8000/mcp'
const TEMPORARY_INSTRUCTION = 'Protect the wizard; save the last 2nd-level slot.'
const AI_ACTION_TEXT = 'I inspect the rune-carved door for traps.'

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
type AIControllerGrant = {
  grant_id: string
  seat_id: string
  role: 'player' | 'dm'
  session_id: string | null
  generation: number
  token: string
  token_hint: string
  expires_at: string | null
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
type TableEvent = {
  seq: number
  kind: string
  acting_seat_id: string | null
  subject_seat_id: string | null
  execution_mode: string | null
  payload: Record<string, unknown>
}
type McpEventPage = {
  events: TableEvent[]
}
type McpSessionContext = {
  mode: 'active_session'
  caller: {
    seat_id: string
    role: 'player'
    is_current_dm: boolean
  }
  temporary_instruction: string | null
}
type RollResult = {
  id: string
  roll_request_id: string | null
  acting_seat_id: string
  subject_seat_id: string
  execution_mode: string
  source: string
  raw_dice: number[]
  kept_dice: number[]
  base_modifier: number
  flat_adjustment: number
  total: number
}
type McpToolListResult = {
  tools: Array<{
    name: string
    description: string
    inputSchema: Record<string, unknown>
  }>
  ttlMs: number
  cacheScope: string
}
type McpToolCallResult<T> = {
  structuredContent:
    | { ok: true; data: T }
    | {
        ok: false
        error: {
          code: string
          messages: { en: string; 'zh-TW': string }
        }
      }
  isError: boolean
}
type McpEnvelope<T> = {
  jsonrpc: '2.0'
  id: number
  result?: T
  error?: {
    code: number
    message: string
    data: {
      code: string
      messages: { en: string; 'zh-TW': string }
    }
  }
}

let nextMcpRequestId = 1

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
    { data: { role: 'dm', label: 'P3-E DM' } },
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
    { data: { role: 'player', label: 'P3-E Player' } },
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

function mcpMeta() {
  return {
    'io.modelcontextprotocol/protocolVersion': MCP_PROTOCOL_VERSION,
    'io.modelcontextprotocol/clientCapabilities': {},
  }
}

async function mcpRaw<T>(
  request: APIRequestContext,
  token: string,
  method: string,
  params: Record<string, unknown>,
  name?: string,
) {
  const id = nextMcpRequestId++
  const response = await request.post(MCP_ENDPOINT, {
    data: {
      jsonrpc: '2.0',
      id,
      method,
      params: {
        ...params,
        _meta: mcpMeta(),
      },
    },
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
      'MCP-Protocol-Version': MCP_PROTOCOL_VERSION,
      'Mcp-Method': method,
      ...(name ? { 'Mcp-Name': name } : {}),
    },
  })
  const body = await response.json() as McpEnvelope<T>
  expect(body.id).toBe(id)
  return { response, body }
}

async function mcpResult<T>(
  request: APIRequestContext,
  token: string,
  method: string,
  params: Record<string, unknown>,
  name?: string,
): Promise<T> {
  const { response, body } = await mcpRaw<T>(request, token, method, params, name)
  if (!response.ok()) {
    expect(response.ok(), JSON.stringify(body)).toBe(true)
  }
  expect(body.error).toBeUndefined()
  expect(body.result).toBeDefined()
  return body.result!
}

async function mcpToolData<T>(
  request: APIRequestContext,
  token: string,
  name: string,
  arguments_: Record<string, unknown>,
): Promise<T> {
  const result = await mcpResult<McpToolCallResult<T>>(
    request,
    token,
    'tools/call',
    { name, arguments: arguments_ },
    name,
  )
  expect(result.isError).toBe(false)
  if (!result.structuredContent.ok) {
    throw new Error(
      `MCP tool ${name} failed: ${result.structuredContent.error.code} `
      + result.structuredContent.error.messages.en,
    )
  }
  return result.structuredContent.data
}

async function endSession(page: Page) {
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByRole('button', { name: 'End Session' }).click()
  await expect(page.getByText('Ended', { exact: true })).toBeVisible()
}

test('P3-E browser and MCP AI share one canonical action and formal-roll journey', async ({
  page,
  request,
  roomContext,
}) => {
  const playerGrant = await enterAsMember(request, roomContext, 'P3-E Player Controller')
  const character = await importCharacter(request)
  const campaign = await createCampaign(request, roomContext.roomId, 'P3-E MCP Browser Journey')

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
  const sessionPrefix =
    `/api/rooms/${roomContext.roomId}/campaigns/${campaign.id}/sessions/${sessionId}`

  const handoff = await json<AIControllerGrant>(await request.post(
    `${sessionPrefix}/seats/${playerSeat.id}/ai-control`,
    {
      data: { temporary_instruction: TEMPORARY_INSTRUCTION },
      headers: { Authorization: `Bearer ${playerGrant.access_token}` },
    },
  ))
  expect(handoff).toMatchObject({
    seat_id: playerSeat.id,
    role: 'player',
    session_id: sessionId,
  })
  expect(handoff.token).toBeTruthy()

  // No discovery handshake: a valid 2026-07-28 tools/list call works immediately.
  const catalog = await mcpResult<McpToolListResult>(
    request,
    handoff.token,
    'tools/list',
    {},
  )
  const toolNames = catalog.tools.map((tool) => tool.name)
  expect(toolNames).toContain('get_session_context')
  expect(toolNames).toContain('post_action')
  expect(toolNames).toContain('get_pending_events')
  expect(toolNames).toContain('roll_pending')
  expect(toolNames).not.toContain('request_check')
  expect(toolNames).not.toContain('resolve_action')
  expect(catalog.ttlMs).toBeGreaterThan(0)
  expect(catalog.cacheScope).toBe('private')

  const context = await mcpToolData<McpSessionContext>(
    request,
    handoff.token,
    'get_session_context',
    {},
  )
  expect(context).toMatchObject({
    mode: 'active_session',
    caller: {
      seat_id: playerSeat.id,
      role: 'player',
      is_current_dm: false,
    },
    temporary_instruction: TEMPORARY_INSTRUCTION,
  })

  const actionEvent = await mcpToolData<TableEvent>(
    request,
    handoff.token,
    'post_action',
    {
      text: AI_ACTION_TEXT,
      idempotency_key: 'p3e-e2e-ai-action-1',
    },
  )
  expect(actionEvent).toMatchObject({
    kind: 'action',
    acting_seat_id: playerSeat.id,
    subject_seat_id: playerSeat.id,
    execution_mode: 'self',
  })
  await expect(page.getByText(AI_ACTION_TEXT, { exact: true })).toBeVisible()

  // Human DM adjudicates the AI action through the same browser flow used in P3-C.
  await page.getByRole('button', { name: 'Dice', exact: true }).click()
  const target = page.getByRole('checkbox', { name: /P3-E Player/ })
  await expect(target).toBeChecked()
  await page.getByRole('combobox', { name: 'Check type' }).selectOption('skill')
  await page.getByRole('combobox', { name: 'Skill' }).selectOption('srd5.1:skill:investigation')
  await page.getByLabel('DC (optional)', { exact: true }).fill('16')
  await page.getByRole('combobox', { name: 'Roll mode' }).selectOption('normal')
  await page.getByRole('combobox', { name: 'Result visibility' }).selectOption('public')
  await page.getByLabel('Label', { exact: true }).fill('Inspect the rune-carved door')

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
    dc: 16,
    status: 'pending',
  })

  const pending = await mcpToolData<McpEventPage>(
    request,
    handoff.token,
    'get_pending_events',
    { after_seq: actionEvent.seq, limit: 50 },
  )
  const rollRequested = pending.events.find((event) => (
    event.kind === 'roll.requested'
    && Array.isArray(event.payload.roll_request_ids)
    && event.payload.roll_request_ids.includes(rollRequestId)
  ))
  expect(rollRequested).toBeDefined()
  expect(rollRequested?.payload).not.toHaveProperty('dc')

  const rollResult = await mcpToolData<RollResult>(
    request,
    handoff.token,
    'roll_pending',
    {
      roll_request_id: rollRequestId,
      idempotency_key: 'p3e-e2e-ai-roll-1',
    },
  )
  expect(rollResult).toMatchObject({
    roll_request_id: rollRequestId,
    acting_seat_id: playerSeat.id,
    subject_seat_id: playerSeat.id,
    execution_mode: 'self',
    source: 'server',
  })
  expect(rollResult.raw_dice).toHaveLength(1)
  expect(rollResult.raw_dice[0]).toBeGreaterThanOrEqual(1)
  expect(rollResult.raw_dice[0]).toBeLessThanOrEqual(20)

  const dmRequest = page.locator('.session-roll-request').first()
  await expect(dmRequest).toHaveAttribute('data-roll-request-status', 'resolved')
  await expect(dmRequest.getByText('DC 16', { exact: true })).toBeVisible()
  await expect(
    dmRequest.getByText(`Total: ${rollResult.total}`, { exact: true }),
  ).toBeVisible()

  // The exact origin Human token takes the Seat back. Stateless MCP auth observes
  // the revocation/current-binding change on the very next request.
  const takeBack = await request.post(
    `${sessionPrefix}/seats/${playerSeat.id}/take-back`,
    {
      headers: { Authorization: `Bearer ${playerGrant.access_token}` },
    },
  )
  expect(takeBack.status()).toBe(204)

  const rejected = await mcpRaw<McpToolCallResult<McpSessionContext>>(
    request,
    handoff.token,
    'tools/call',
    { name: 'get_session_context', arguments: {} },
    'get_session_context',
  )
  expect(rejected.response.status()).toBe(401)
  expect(rejected.body.error?.data.code).toBe('ai_token_unauthorized')

  await endSession(page)
})
