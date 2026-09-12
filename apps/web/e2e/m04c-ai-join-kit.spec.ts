import { expect, test, type Page } from './support/roomTest'

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

test('M04-C public MCP guide is reachable without an AI token', async ({ request }) => {
  const response = await request.get('/mcp/guide?locale=en')
  expect(response.ok(), await response.text()).toBe(true)

  const guide = await response.text()
  expect(guide).toContain('Adventure Table MCP')
  expect(guide).toContain('/mcp')
  expect(guide).toContain('wait_for_event')
  expect(guide).toContain('120')
})

test('M04-C Lobby AI DM issuance renders a complete Join Kit from the browser origin', async ({
  page,
  roomContext,
}) => {
  await createActiveCampaign(page, roomContext.roomId, 'M04-C Join Kit Journey')

  await page.getByLabel('Role').selectOption('dm')
  await page.getByLabel('Seat label').fill('M04-C AI DM')
  await page.getByRole('button', { name: 'Add seat' }).click()

  const dmSeat = page.locator('article').filter({ has: page.getByRole('heading', { name: 'M04-C AI DM' }) })
  await expect(dmSeat.getByText('Role: DM')).toBeVisible()

  const panel = page.locator('[data-ai-dm-grant-panel]').filter({
    has: page.getByRole('heading', { name: 'AI DM start credential' }),
  })
  await expect(panel).toBeVisible()
  await panel.getByRole('button', { name: 'Create AI DM Token' }).click()

  await expect(panel.locator('[data-ai-dm-token-once="true"]')).toBeVisible()
  const kit = panel.locator('[data-ai-join-kit="dm"]')
  await expect(kit).toBeVisible()

  const origin = new URL(page.url()).origin
  const kitText = kit.locator('.ai-join-kit__text')
  await expect(kitText).toContainText(`${origin}/mcp`)
  await expect(kitText).toContainText(`${origin}/mcp/guide?locale=en`)
  await expect(kitText).toContainText('Role: dm')
  await expect(kitText).toContainText('ChatGPT Web')
  await expect(kitText).toContainText('MCP client')
  await expect(kitText).toContainText('Raw HTTP')

  await expect(kit.getByRole('button', { name: 'Copy Join Kit' })).toBeVisible()
  const downloadPromise = page.waitForEvent('download')
  await kit.getByRole('button', { name: 'Download .txt' }).click()
  const download = await downloadPromise
  expect(download.suggestedFilename()).toMatch(/^adventure-table-ai-join-dm-\d{4}-\d{2}-\d{2}\.txt$/)
  expect(download.suggestedFilename()).not.toContain('token')
})
