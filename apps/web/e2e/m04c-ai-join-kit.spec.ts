import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'

import { expect, test, type APIRequestContext, type Page } from './support/roomTest'

const IMPORT_FIXTURE = resolve(process.cwd(), '../server/tests/data/m03/fixture_low_level_srd.json')
const MCP_PROTOCOL_VERSION = '2026-07-28'
// The vite dev server only proxies /api; /mcp and /mcp/guide are reached on the
// backend directly, the same way p3e-mcp-browser-integration does.
const MCP_ENDPOINT = process.env.PLAYWRIGHT_MCP_URL ?? 'http://127.0.0.1:8000/mcp'

type Campaign = { id: string }
type Lobby = { caller_access_session_id: string | null }
type Seat = { id: string }
type CharacterImportResult = { character_id: string | null }

async function json<T>(response: Awaited<ReturnType<APIRequestContext['get']>>): Promise<T> {
  if (!response.ok()) expect(response.ok(), await response.text()).toBe(true)
  return response.json() as Promise<T>
}

async function createActiveCampaign(page: Page, roomId: string, name: string) {
  await page.goto(`/rooms/${roomId}/campaigns`)
  await page.getByLabel('Campaign name').fill(name)
  await page.getByRole('button', { name: 'Create Campaign' }).click()
  const card = page.locator('article').filter({ has: page.getByRole('heading', { name, exact: true }) })
  await expect(card).toBeVisible()
  await card.getByRole('link', { name: 'Open Campaign' }).click()
  await page.getByRole('button', { name: 'Start Campaign', exact: true }).click()
  await page.getByRole('button', { name: 'Select Campaign' }).click()
  await page.getByRole('link', { name: 'Open Lobby' }).click()
  await expect(page.getByRole('heading', { name: 'Lobby & Seats', level: 1 })).toBeVisible()
}

function mcpBody(name: string) {
  return {
    jsonrpc: '2.0', id: 'm04c-e2e', method: 'tools/call',
    params: {
      name, arguments: {},
      _meta: {
        'io.modelcontextprotocol/protocolVersion': MCP_PROTOCOL_VERSION,
        'io.modelcontextprotocol/clientCapabilities': {},
      },
    },
  }
}

async function getSessionContextWithKitToken(request: APIRequestContext, token: string) {
  const response = await request.post(MCP_ENDPOINT, {
    data: mcpBody('get_session_context'),
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
      'MCP-Protocol-Version': MCP_PROTOCOL_VERSION,
      'Mcp-Method': 'tools/call',
      'Mcp-Name': 'get_session_context',
    },
  })
  expect(response.ok(), await response.text()).toBe(true)
  return response.json() as Promise<{ result: { structuredContent: { ok: true; data: { mode: string } } } }>
}

test('M04-C public MCP guide is reachable in both supported locales', async ({ request }) => {
  for (const locale of ['en', 'zh-TW'] as const) {
    const response = await request.get(`${MCP_ENDPOINT}/guide?locale=${locale}`)
    expect(response.ok(), await response.text()).toBe(true)
    expect(response.headers()['cache-control']).toBe('public, max-age=300')
    const guide = await response.text()
    expect(guide).toContain(locale === 'en' ? 'Adventure Table AI Join Guide' : 'Adventure Table AI 接入指引')
    expect(guide).toContain('/mcp')
    expect(guide).toContain('wait_for_event')
    expect(guide).toContain('120')
    expect(guide).toContain('get_session_context')
  }
})

test('M04-C Lobby AI DM kit token reaches pre_session context', async ({ page, request, roomContext }) => {
  await createActiveCampaign(page, roomContext.roomId, 'M04-C Join Kit Journey')
  await page.getByLabel('Role').selectOption('dm')
  await page.getByLabel('Seat label').fill('M04-C AI DM')
  await page.getByRole('button', { name: 'Add seat' }).click()

  const dmSeat = page.locator('article').filter({ has: page.getByRole('heading', { name: 'M04-C AI DM' }) })
  await expect(dmSeat.getByText('Role: DM')).toBeVisible()
  const panel = page.locator('[data-ai-dm-grant-panel]').filter({ has: page.getByRole('heading', { name: 'AI DM start credential' }) })
  await panel.getByRole('button', { name: 'Create AI DM Token' }).click()

  const once = panel.locator('[data-ai-dm-token-once="true"]')
  await expect(once).toBeVisible()
  const token = await once.getByLabel('AI DM Token (shown once)').inputValue()
  const kit = panel.locator('[data-ai-join-kit="dm"]')
  const kitText = kit.locator('.ai-join-kit__text')
  const origin = new URL(page.url()).origin
  await expect(kitText).toContainText(`URL: ${origin}/mcp`)
  await expect(kitText).toContainText(`${origin}/mcp/guide?locale=en`)
  await expect(kitText).toContainText('Role: DM')
  await expect(kitText).toContainText('Expires:')
  await expect(kitText).toContainText('get_session_context')

  const context = await getSessionContextWithKitToken(request, token)
  expect(context.result.structuredContent).toMatchObject({ ok: true, data: { mode: 'pre_session' } })

  const downloadPromise = page.waitForEvent('download')
  await kit.getByRole('button', { name: 'Download .txt' }).click()
  const download = await downloadPromise
  expect(download.suggestedFilename()).toMatch(/^adventure-table-ai-dm-\d{8}\.txt$/)
  expect(download.suggestedFilename()).not.toContain('token')
})

test('M04-C Lobby AI DM kit renders in zh-TW', async ({ page, request, roomContext }) => {
  await createActiveCampaign(page, roomContext.roomId, 'M04-C Join Kit zh-TW')
  await page.getByRole('button', { name: 'Traditional Chinese' }).click()
  await expect(page.getByRole('heading', { name: '大廳與座位', level: 1 })).toBeVisible()

  await page.getByLabel('角色').selectOption('dm')
  await page.getByLabel('座位名稱').fill('M04-C AI DM zh')
  await page.getByRole('button', { name: '新增座位' }).click()

  const panel = page.locator('[data-ai-dm-grant-panel]').filter({ has: page.getByRole('heading', { name: 'AI DM 開場憑證' }) })
  await panel.getByRole('button', { name: '建立 AI DM Token' }).click()

  const once = panel.locator('[data-ai-dm-token-once="true"]')
  await expect(once).toBeVisible()
  const token = await once.getByLabel('AI DM Token（僅顯示這一次）').inputValue()
  const kitText = panel.locator('[data-ai-join-kit="dm"] .ai-join-kit__text')
  const origin = new URL(page.url()).origin
  await expect(kitText).toContainText(`URL: ${origin}/mcp`)
  await expect(kitText).toContainText(`${origin}/mcp/guide?locale=zh-TW`)
  await expect(kitText).toContainText('Role: DM')
  await expect(kitText).toContainText('連上後第一步一律呼叫 get_session_context')
  await expect(kitText).toContainText('安全：此 token 只顯示這一次')
  await expect(panel.getByRole('button', { name: '複製 Join Kit' })).toBeVisible()
  await expect(panel.getByRole('button', { name: '下載 .txt' })).toBeVisible()

  const context = await getSessionContextWithKitToken(request, token)
  expect(context.result.structuredContent).toMatchObject({ ok: true, data: { mode: 'pre_session' } })
})

test('M04-C Player Let AI Control reveals a Player Join Kit', async ({ page, request, roomContext }) => {
  const campaign = await json<Campaign>(await request.post(`/api/rooms/${roomContext.roomId}/campaigns`, {
    data: { name: 'M04-C Player Kit Journey', ruleset: 'dnd5e-2014' },
  }))
  await json(await request.patch(`/api/rooms/${roomContext.roomId}/campaigns/${campaign.id}/status`, { data: { status: 'active' } }))
  await json(await request.post(`/api/rooms/${roomContext.roomId}/campaigns/${campaign.id}/select`))
  const lobby = await json<Lobby>(await request.get(`/api/rooms/${roomContext.roomId}/campaigns/${campaign.id}/lobby`))
  expect(lobby.caller_access_session_id).not.toBeNull()

  const envelope = await readFile(IMPORT_FIXTURE, 'utf8')
  const imported = await json<CharacterImportResult>(await request.post('/api/characters/import', {
    data: envelope,
    headers: { 'Content-Type': 'application/json' },
  }))
  expect(imported.character_id).not.toBeNull()
  await json(await request.post(`/api/rooms/${roomContext.roomId}/campaigns/${campaign.id}/roster`, {
    data: { character_id: imported.character_id, status: 'active' },
  }))

  const dmSeat = await json<Seat>(await request.post(`/api/rooms/${roomContext.roomId}/campaigns/${campaign.id}/seats`, { data: { role: 'dm', label: 'M04-C Human DM' } }))
  await json(await request.patch(`/api/rooms/${roomContext.roomId}/campaigns/${campaign.id}/seats/${dmSeat.id}/controller`, {
    data: { controller_kind: 'human', controller_access_session_id: lobby.caller_access_session_id },
  }))
  const playerSeat = await json<Seat>(await request.post(`/api/rooms/${roomContext.roomId}/campaigns/${campaign.id}/seats`, { data: { role: 'player', label: 'M04-C Human Player' } }))
  await json(await request.patch(`/api/rooms/${roomContext.roomId}/campaigns/${campaign.id}/seats/${playerSeat.id}/controller`, {
    data: { controller_kind: 'human', controller_access_session_id: lobby.caller_access_session_id },
  }))
  await json(await request.patch(`/api/rooms/${roomContext.roomId}/campaigns/${campaign.id}/seats/${playerSeat.id}/character`, {
    data: { selected_character_id: imported.character_id },
  }))

  await page.goto(`/rooms/${roomContext.roomId}/campaigns/${campaign.id}/lobby`)
  await page.getByRole('button', { name: 'Start Session' }).click()
  await expect(page.getByRole('heading', { name: 'Active Session', level: 1 })).toBeVisible()
  const panel = page.locator(`[data-ai-controller-panel="${playerSeat.id}"]`)
  await expect(panel.getByRole('button', { name: 'Let AI Control' })).toBeVisible()
  await panel.getByRole('button', { name: 'Let AI Control' }).click()
  await expect(panel.locator('[data-ai-token-once="true"]')).toBeVisible()
  const kit = panel.locator('[data-ai-join-kit="player"]')
  await expect(kit).toBeVisible()
  await expect(kit.locator('.ai-join-kit__text')).toContainText('Role: Player')
  await expect(kit.locator('.ai-join-kit__text')).toContainText('get_session_context')
})
