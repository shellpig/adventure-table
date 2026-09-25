import { expect, test } from './support/roomTest'
import { enterAsMember } from './support/quickCombat'

test('P6-F Adventure Import Review & Finalize Journey: Owner creates import, adds source & entry, injects blocking warning via established API, resolves warning, finalizes into Adventure, verifies in list & after reload, and verifies Member sees no importer or review controls', async ({
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

  // 2. Create import with distinctive name
  const importName = 'P6-F Sunken Crypt Import'
  await importer.getByRole('textbox', { name: 'Import Name' }).fill(importName)
  await importer.getByRole('button', { name: 'Create Import' }).click()

  // Verify import is created and selected
  const activeCard = importer.locator('.importer-item-card--active')
  await expect(activeCard).toBeVisible()
  await expect(activeCard.getByText(importName)).toBeVisible()
  await expect(activeCard.getByText('Status: Source')).toBeVisible()

  // 3. Paste a distinctive text source
  const sourcesSection = importer.locator('[data-testid="importer-source-section"]')
  await expect(sourcesSection).toBeVisible()

  const sourceText =
    'The sunken crypt of King Gerald lies beneath black water. The iron doors require an Athletics DC 18 check to force open.'
  await sourcesSection.getByRole('textbox', { name: 'Pasted text content' }).fill(sourceText)
  await sourcesSection.getByRole('button', { name: 'Add Source' }).click()

  // Verify source card appears
  const sourceCard = sourcesSection.locator('.importer-item-card').first()
  await expect(sourceCard.getByRole('button', { name: 'View text' })).toBeVisible()

  // 4. Add a draft entry via the UI
  const reviewSection = importer.locator('[data-testid="importer-review-section"]')
  await expect(reviewSection).toBeVisible()

  await reviewSection.getByRole('combobox', { name: 'Kind' }).selectOption('scene')
  await reviewSection.getByRole('textbox', { name: 'DM summary' }).fill('Sunken Crypt Iron Doors')
  await reviewSection.getByRole('button', { name: 'Add to Draft' }).click()

  // Verify entry appears with pending review status and review action buttons
  const firstEntry = reviewSection.locator('.adventure-entry').first()
  await expect(firstEntry).toBeVisible()
  await expect(firstEntry.getByText('Sunken Crypt Iron Doors')).toBeVisible()
  await expect(firstEntry.getByText('Review status: Pending')).toBeVisible()
  await expect(firstEntry.getByRole('button', { name: 'Accept' })).toBeVisible()
  await expect(firstEntry.getByRole('button', { name: 'Ignore' })).toBeVisible()
  await expect(firstEntry.getByRole('button', { name: 'Mark uncertain' })).toBeVisible()
  // Entry created without source reference does NOT have View source button
  await expect(firstEntry.getByRole('button', { name: 'View source' })).toBeHidden()

  // Accept the first entry to test review mutation
  await firstEntry.getByRole('button', { name: 'Accept' }).click()
  await expect(firstEntry.getByText('Review status: Accepted')).toBeVisible()

  // 5. Query the backend API for the import ID and source ID
  const listImportsResp = await request.get(`/api/rooms/${roomId}/adventure-imports`)
  expect(listImportsResp.ok()).toBeTruthy()
  const importsData = await listImportsResp.json()
  const currentImport = importsData.find((item: { name: string }) => item.name === importName)
  expect(currentImport).toBeDefined()
  const importId = currentImport.id

  const listSourcesResp = await request.get(`/api/rooms/${roomId}/adventure-imports/${importId}/sources`)
  expect(listSourcesResp.ok()).toBeTruthy()
  const sourcesData = await listSourcesResp.json()
  expect(sourcesData.length).toBeGreaterThan(0)
  const sourceId = sourcesData[0].id

  // 6. Inject an entry with source_ref AND a blocking warning via established draft PUT API
  const getDraftResp = await request.get(`/api/rooms/${roomId}/adventure-imports/${importId}/draft`)
  expect(getDraftResp.ok()).toBeTruthy()
  const draftData = await getDraftResp.json()

  const putDraftResp = await request.put(`/api/rooms/${roomId}/adventure-imports/${importId}/draft`, {
    data: {
      draft: {
        schema_version: 1,
        questions: [],
        entries: [
          ...draftData.draft.entries,
          {
            entry_id: 'door_check_entry',
            entry_kind: 'suggested_check',
            payload: {
              kind: 'suggested_check',
              ability: 'str',
              skill: 'athletics',
              dc: 18,
            },
            parent_entry_id: null,
            provenance: 'source_document',
            source_ref: {
              source_id: sourceId,
              locator: 'offset:0',
            },
            note: 'DC 18 Athletics check',
            review_status: 'pending',
            asset_ids: [],
            title: null,
            body: null,
            visibility: 'dm_only',
          },
        ],
      },
      warnings: [
        {
          warning_id: 'blocker_dc_check',
          level: 'blocking',
          code: 'unverified_rule_value',
          message: 'Athletics DC 18 requires DM verification',
          entry_id: 'door_check_entry',
          source_id: sourceId,
          resolved: false,
          resolution: null,
        },
      ],
      expected_revision: draftData.revision,
    },
  })
  expect(putDraftResp.ok()).toBeTruthy()

  // 7. In UI: reload the import to pick up the updated draft and blocking warning
  await importer.getByRole('button', { name: 'Reload' }).click()

  // Verify the second entry appears with View source button
  const secondEntry = reviewSection.locator('[data-testid="draft-entry-door_check_entry"]')
  await expect(secondEntry).toBeVisible()
  await expect(secondEntry.getByRole('button', { name: 'View source' })).toBeVisible()

  // Click View source and verify chunk viewer opens with the matching text
  await secondEntry.getByRole('button', { name: 'View source' }).click()
  const chunkViewer = sourcesSection.locator('[data-testid="importer-chunk-viewer"]')
  await expect(chunkViewer).toBeVisible()
  await expect(chunkViewer.getByText('King Gerald')).toBeVisible()
  await chunkViewer.getByRole('button', { name: 'Close' }).click()
  await expect(chunkViewer).toBeHidden()

  // Mark the second entry as uncertain to demonstrate Accept is not mandatory
  await secondEntry.getByRole('button', { name: 'Mark uncertain' }).click()
  await expect(secondEntry.getByText('Review status: Uncertain')).toBeVisible()

  // 8. Blocking Gate: Verify Finalize is blocked while blocking warning is unresolved
  const finalizeSection = reviewSection.locator('[data-testid="importer-finalize-section"]')
  await expect(finalizeSection).toBeVisible()

  const blockingNotice = reviewSection.locator('[data-testid="importer-blocking-notice"]')
  await expect(blockingNotice).toBeVisible()
  await expect(finalizeSection.locator('[data-testid="finalize-blocked-reason"]')).toBeVisible()

  const finalizeButton = finalizeSection.getByRole('button', { name: 'Finalize' })
  await expect(finalizeButton).toBeDisabled()

  // 9. Resolve the blocking warning via the UI resolution control
  const blockingCard = reviewSection.locator('.importer-warning-card--blocking')
  await expect(blockingCard).toBeVisible()
  await expect(blockingCard.getByText('Athletics DC 18 requires DM verification')).toBeVisible()

  await blockingCard.getByPlaceholder('Resolution notes (optional)').fill('Verified from official module notes')
  await blockingCard.getByRole('button', { name: 'Resolve' }).click()

  // Verify warning is now marked resolved and blocking notice is removed
  await expect(blockingCard.locator('.importer-resolved-badge')).toBeVisible()
  await expect(blockingNotice).toBeHidden()
  await expect(finalizeSection.locator('[data-testid="finalize-blocked-reason"]')).toBeHidden()

  // 10. Finalize is now enabled (even though entries are Accepted and Uncertain, not all Accepted)
  await expect(finalizeButton).toBeEnabled()

  const finalizedAdventureName = 'P6-F Finalized Sunken Crypt'
  await finalizeSection.getByRole('textbox', { name: 'Adventure Name' }).fill(finalizedAdventureName)
  await finalizeSection.getByRole('textbox', { name: 'Summary (optional)' }).fill('A sunken tomb with heavy iron doors.')
  await finalizeButton.click()

  // 11. Success: verifies auto-navigation to existing Adventure editor
  await expect(page).toHaveURL(new RegExp(`/rooms/${roomId}/adventures/[0-9a-fA-F-]{36}`))
  await expect(page.getByRole('heading', { name: finalizedAdventureName, level: 1 })).toBeVisible()

  // Extract target adventure id from URL
  const targetAdventureUrl = page.url()
  const targetAdventureId = targetAdventureUrl.split('/').pop()!

  // 12. Return to Adventures list page
  await page.goto(`/rooms/${roomId}/adventures`)

  // Verify Adventures list now contains the newly finalized Adventure
  const adventureGrid = page.locator('.adventure-grid')
  await expect(adventureGrid.getByRole('heading', { name: finalizedAdventureName })).toBeVisible()

  // Verify Importer panel displays the finalized import and target adventure link
  const finalizedCard = importer.locator('.importer-item-card').filter({ hasText: importName })
  await expect(finalizedCard).toBeVisible()
  await expect(finalizedCard.getByText('Status: Finalized')).toBeVisible()
  const openTargetLink = finalizedCard.getByRole('link', { name: 'Open Adventure' })
  await expect(openTargetLink).toBeVisible()
  await expect(openTargetLink).toHaveAttribute('href', `/rooms/${roomId}/adventures/${targetAdventureId}`)

  // 13. Reload page: verify finalized import and target adventure link persist
  await page.reload()
  await expect(importer).toBeVisible()
  const reloadedCard = importer.locator('.importer-item-card').filter({ hasText: importName })
  await expect(reloadedCard.getByText('Status: Finalized')).toBeVisible()
  await expect(
    reloadedCard.getByRole('link', { name: 'Open Adventure' }),
  ).toHaveAttribute('href', `/rooms/${roomId}/adventures/${targetAdventureId}`)

  // 14. Member context: open separate context, assert Member sees no Importer and zero import requests
  const member = await enterAsMember(request, roomContext, 'P6-F Member Player')
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

  const memberImportRequests: string[] = []
  memberPage.on('request', (req) => {
    const pathname = new URL(req.url()).pathname
    if (pathname.includes('/adventure-imports')) {
      memberImportRequests.push(pathname)
    }
  })

  await memberPage.goto(`/rooms/${roomId}/adventures`)
  await expect(
    memberPage.getByText('Only the Room owner or DM can manage Adventures.'),
  ).toBeVisible()
  await expect(
    memberPage.locator('[data-testid="adventure-importer-panel"]'),
  ).toBeHidden()
  expect(memberImportRequests).toEqual([])

  await memberContext.close()
})
