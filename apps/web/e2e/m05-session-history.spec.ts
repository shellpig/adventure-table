import { expect, test, type APIRequestContext, type Page } from './support/roomTest'

// Direct backend MCP endpoint, the same way p3e-mcp-browser-integration reaches it.
const MCP_ENDPOINT = process.env.PLAYWRIGHT_MCP_URL ?? 'http://127.0.0.1:8000/mcp'
const MCP_PROTOCOL_VERSION = '2026-07-28'

type Campaign = { id: string }
type Seat = { id: string }
type Lobby = { caller_access_session_id: string | null }
type AIDMGrant = { token: string }
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
  expect(result.isError).toBe(false)
  if (!result.structuredContent.ok) {
    throw new Error(`MCP tool ${name} failed: ${result.structuredContent.error.code} ${result.structuredContent.error.messages.en}`)
  }
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

async function getActiveSession(request: APIRequestContext, roomId: string, campaignId: string) {
  return json<SessionResume>(await request.get(`/api/rooms/${roomId}/campaigns/${campaignId}/sessions/active`))
}

async function openSessionPage(page: Page, roomId: string, campaignId: string, sessionId: string) {
  await page.goto(`/rooms/${roomId}/campaigns/${campaignId}/sessions/${sessionId}`)
  await expect(page.getByRole('heading', { name: 'Active Session', level: 1 })).toBeVisible()
}

test('M05-A Owner ends an AI DM Session from the browser, then reassigns a human DM and starts again', async ({
  page,
  request,
  roomContext,
}) => {
  const { campaign, dmSeat, aiDmToken } = await createAiDmCampaign(request, roomContext.roomId, 'M05-A AI DM')

  // The AI DM opens the Session through MCP and leaves one narration on the table.
  const started = await mcpToolData<SessionSnapshot>(request, aiDmToken, 'start_session', {})
  expect(started.dm_controller_kind).toBe('ai')
  await mcpToolData(request, aiDmToken, 'set_stage_text', { expected_revision: 0, text: 'The Old Mill Basement' })
  await mcpToolData(request, aiDmToken, 'post_narration', { text: 'Dust falls from the rafters as the door groans shut.' })

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
})
