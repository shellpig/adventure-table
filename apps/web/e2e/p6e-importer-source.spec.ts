import { expect, test } from './support/roomTest'
import { enterAsMember } from './support/quickCombat'

test('P6-E Adventure Importer Journey: Owner creates import, adds text source, views chunk, adds draft entry, verifies persistence on reload; Member sees no importer and zero import requests', async ({
  page,
  browser,
  request,
  roomContext,
}) => {
  test.setTimeout(120_000)
  const { roomId } = roomContext

  // 1. Owner opens Adventures list page
  await page.goto(`/rooms/${roomId}/adventures`)
  const importer = page.locator('[data-testid="adventure-importer-panel"]')
  await expect(importer).toBeVisible()
  await expect(importer.getByRole('heading', { name: 'Adventure Importer', level: 2 })).toBeVisible()

  // 2. Create import by nonblank name
  const importName = 'P6-E Ancient Tomb Import'
  await importer.getByRole('textbox', { name: 'Import Name' }).fill(importName)
  await importer.getByRole('button', { name: 'Create Import' }).click()

  // 3. Verify import appears and is selected in active import card
  const activeCard = importer.locator('.importer-item-card--active')
  await expect(activeCard).toBeVisible()
  await expect(activeCard.getByText(importName)).toBeVisible()
  await expect(activeCard.getByText('Status: Source')).toBeVisible()
  await expect(activeCard.getByText('Revision: 0')).toBeVisible()

  // 4. Paste a distinctive text source
  const sourcesSection = importer.locator('.importer-section').filter({
    has: page.getByRole('heading', { name: 'Sources' }),
  })
  await expect(sourcesSection).toBeVisible()

  const distinctiveText =
    'The ancient tomb was carved from black obsidian and inscribed with glowing runes of warding.'
  await sourcesSection.getByRole('textbox', { name: 'Pasted text content' }).fill(distinctiveText)
  await sourcesSection.getByRole('button', { name: 'Add Source' }).click()

  // 5. Assert source card appears and view its chunk
  const sourceCard = sourcesSection.locator('.importer-item-card').first()
  await expect(sourceCard.getByRole('button', { name: 'View text' })).toBeVisible()
  await sourceCard.getByRole('button', { name: 'View text' }).click()

  const chunkViewer = sourcesSection.locator('.importer-chunk-viewer')
  await expect(chunkViewer).toBeVisible()
  await expect(chunkViewer.getByText(distinctiveText)).toBeVisible()
  await chunkViewer.getByRole('button', { name: 'Close' }).click()
  await expect(chunkViewer).toBeHidden()

  // 6. Draft area: assert initial draft revision 0 and add a simple scene entry
  const draftSection = importer.locator('.importer-section').filter({
    has: page.getByRole('heading', { name: 'Import Draft' }),
  })
  await expect(draftSection).toBeVisible()
  await expect(draftSection.getByText('Draft Revision: 0')).toBeVisible()

  await draftSection.getByRole('combobox', { name: 'Kind' }).selectOption('scene')
  await draftSection.getByRole('textbox', { name: 'DM summary' }).fill('Obsidian tomb entrance hall')
  await draftSection.getByRole('button', { name: 'Add to Draft' }).click()

  // 7. Assert draft entry is displayed with user_explicit provenance and revision advances to 1
  const draftEntry = draftSection.locator('.adventure-entry').first()
  await expect(draftEntry).toBeVisible()
  await expect(draftEntry.getByText('Obsidian tomb entrance hall')).toBeVisible()
  await expect(draftEntry.getByText('Provenance: User explicit')).toBeVisible()
  await expect(draftSection.getByText('Draft Revision: 1')).toBeVisible()

  // 8. Reload page: verify import, source, draft entry, and revision persist without localStorage state
  await page.reload()
  await expect(importer).toBeVisible()

  const reloadedActiveCard = importer.locator('.importer-item-card--active')
  await expect(reloadedActiveCard.getByText(importName)).toBeVisible()

  const reloadedSources = importer.locator('.importer-section').filter({
    has: page.getByRole('heading', { name: 'Sources' }),
  })
  await expect(
    reloadedSources.locator('.importer-item-card').first().getByRole('button', { name: 'View text' }),
  ).toBeVisible()

  const reloadedDraft = importer.locator('.importer-section').filter({
    has: page.getByRole('heading', { name: 'Import Draft' }),
  })
  await expect(reloadedDraft.getByText('Draft Revision: 1')).toBeVisible()
  await expect(
    reloadedDraft.locator('.adventure-entry').first().getByText('Obsidian tomb entrance hall'),
  ).toBeVisible()

  // 9. Member context: open separate context, visit Adventures page, assert no Importer and zero import requests
  const member = await enterAsMember(request, roomContext, 'P6-E Member')
  const memberContext = await browser.newContext({
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? 'http://127.0.0.1:4173',
  })
  const memberPage = await memberContext.newPage()
  await memberPage.goto('/')
  await memberPage.evaluate(
    ({ room }) => {
      window.localStorage.setItem('adventure-table.recent-rooms.v1', JSON.stringify([room]))
      window.localStorage.setItem('adventure-table.locale', 'en')
      window.sessionStorage.setItem('adventure-table.active-room.v1', room.roomId)
    },
    {
      room: {
        roomId,
        code: roomContext.code,
        name: roomContext.name,
        accessToken: member.access_token,
        authority: member.authority,
      },
    },
  )

  const importRequests: string[] = []
  memberPage.on('request', (req) => {
    const pathname = new URL(req.url()).pathname
    if (pathname.includes('/adventure-imports')) {
      importRequests.push(pathname)
    }
  })

  await memberPage.goto(`/rooms/${roomId}/adventures`)
  await expect(
    memberPage.getByText('Only the Room owner or DM can manage Adventures.'),
  ).toBeVisible()
  await expect(
    memberPage.locator('[data-testid="adventure-importer-panel"]'),
  ).toBeHidden()
  expect(importRequests).toEqual([])

  await memberContext.close()
})
