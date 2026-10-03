import { expect, test, type APIRequestContext, type Page } from './support/roomTest'
import {
  addSeat,
  createCampaign,
  enterAsMember,
  json,
  startSession,
  PLAYWRIGHT_BASE_URL,
  type Lobby,
} from './support/quickCombat'

type MonsterSummary = { ref: string; name: string }
type MonsterDetail = { ref: string; name: string; revision: number }
type MonsterInstance = { id: string }

test('M07-A Monster Library journey in English: create from built-in, edit only AC, copy, archive, referenced delete error, refresh', async ({
  page,
  request,
  roomContext,
}) => {
  test.setTimeout(180_000)
  const { roomId } = roomContext

  // 1. Room workspace -> Monster Library button visible for Owner
  await page.goto(`/rooms/${roomId}`)
  const libLink = page.getByRole('link', { name: 'Open Monster Library' })
  await expect(libLink).toBeVisible()
  await libLink.click()
  await expect(page).toHaveURL(new RegExp(`/rooms/${roomId}/monster-library/?$`))

  // 2. Verify "Load more" reveals entries beyond the first page
  await expect(page.getByRole('heading', { name: 'Monster Library', level: 1 })).toBeVisible()
  const loadMoreBtn = page.getByRole('button', { name: 'Load more' })
  await expect(loadMoreBtn).toBeVisible()
  const initialCount = await page.locator('.monster-library__item').count()
  expect(initialCount).toBe(50)
  await loadMoreBtn.click()
  await expect(page.locator('.monster-library__item')).toHaveCount(100)

  // 2b. Find built-in Goblin by typing into the search box
  const searchInput = page.getByPlaceholder('Search by monster name, type, or subtype…')
  await searchInput.fill('Goblin')
  await page.getByRole('button', { name: 'Refresh' }).click()
  const goblinItem = page.locator('.monster-library__item').filter({
    has: page.locator('.monster-library__item-name', { hasText: /^Goblin$/ }),
  })
  await expect(goblinItem).toBeVisible()
  await goblinItem.click()

  // 3. Detail pane shows read-only built-in detail and "Create custom monster from this"
  await expect(page.locator('.monster-library__builtin-view')).toBeVisible()
  const createFromContentBtn = page.getByRole('button', { name: 'Create custom monster from this' })
  await expect(createFromContentBtn).toBeVisible()
  await createFromContentBtn.click()

  // 4. Modal: specify new custom name
  const nameInput = page.getByLabel('New template name (optional)')
  await nameInput.fill('E2E Goblin Scout')
  await page.getByRole('button', { name: 'Create', exact: true }).click()

  // 5. New custom monster is created, selected, and form is editable
  const customHeading = page.locator('.monster-library__title-block h2').filter({ hasText: /^E2E Goblin Scout$/ })
  await expect(customHeading).toBeVisible()

  // 6. Edit only AC to 16, leaving other abilities untouched
  const acInput = page.getByLabel('Armor Class (AC)')
  await acInput.fill('16')
  await page.getByRole('button', { name: 'Save Changes' }).click()
  await expect(page.locator('.form-success')).toBeVisible()

  // Reload or verify input retained 16 and traits are still present
  await expect(acInput).toHaveValue('16')
  await expect(page.locator('input[value="Nimble Escape"]')).toBeVisible()

  // 7. Copy custom monster
  await page.getByRole('button', { name: 'Copy', exact: true }).click()
  const copyInput = page.getByLabel('New template name (optional)')
  await copyInput.fill('E2E Goblin Veteran')
  await page.getByRole('button', { name: 'Copy Monster', exact: true }).click()

  // 8. Copy appears in the list and can be archived
  const vetItem = page.locator('.monster-library__item').filter({
    has: page.locator('.monster-library__item-name', { hasText: /^E2E Goblin Veteran$/ }),
  })
  await expect(vetItem).toBeVisible()
  await vetItem.click()

  page.once('dialog', (dialog) => void dialog.accept())
  await page.getByRole('button', { name: 'Archive', exact: true }).click()
  await expect(page.locator('.monster-library__title-block .badge.archived')).toBeVisible()

  // 9. Reference protection: create a combat session referencing E2E Goblin Scout
  // First, find the template id for E2E Goblin Scout
  const scoutItem = page.locator('.monster-library__item').filter({
    has: page.locator('.monster-library__item-name', { hasText: /^E2E Goblin Scout$/ }),
  })
  await scoutItem.click()

  // Create Campaign and Session, then spawn an instance referencing this custom template
  const campaign = await createCampaign(request, roomId, 'M07A E2E Campaign')
  const ownerLobby = await json<Lobby>(
    await request.get(`/api/rooms/${roomId}/campaigns/${campaign.id}/lobby`),
  )
  expect(ownerLobby.caller_access_session_id).not.toBeNull()
  await addSeat(
    request,
    roomId,
    campaign.id,
    'dm',
    ownerLobby.caller_access_session_id!,
    'M07-A',
  )
  const sessionId = await startSession(page, roomId, campaign.id)

  // Grab the custom template ref from the list via API
  const listedCustom = await json<MonsterSummary[]>(
    await request.get(`/api/rooms/${roomId}/monster-library?source=custom`),
  )
  const scoutTemplate = listedCustom.find((m) => m.name === 'E2E Goblin Scout')
  expect(scoutTemplate).toBeDefined()
  const scoutRef = scoutTemplate!.ref

  // Create instance in session referencing custom template
  await json<MonsterInstance>(
    await request.post(
      `/api/rooms/${roomId}/campaigns/${campaign.id}/sessions/${sessionId}/monster-instances/from-content`,
      {
        data: {
          content_key: scoutRef,
          name: 'Active Scout Instance',
          idempotency_key: `e2e-m07a-${Date.now()}`,
        },
      },
    ),
  )

  // Navigate back to Monster Library to attempt delete on the referenced template
  await page.goto(`/rooms/${roomId}/monster-library`)
  const searchInputAgain = page.getByPlaceholder('Search by monster name, type, or subtype…')
  await searchInputAgain.fill('E2E Goblin Scout')
  await page.getByRole('button', { name: 'Refresh' }).click()
  const scoutItemRef = page.locator('.monster-library__item').filter({
    has: page.locator('.monster-library__item-name', { hasText: /^E2E Goblin Scout$/ }),
  })
  await scoutItemRef.click()

  // Now attempt to delete E2E Goblin Scout in UI -> Expect referenced error
  page.once('dialog', (dialog) => void dialog.accept())
  await page.getByRole('button', { name: 'Delete', exact: true }).click()
  await expect(
    page.getByText('This monster template is in use (referenced by map placements, campaigns, or history) and cannot be deleted; archive it instead.'),
  ).toBeVisible()

  // Form values remain intact
  await expect(acInput).toHaveValue('16')

  // 10. Refresh keeps state
  await page.reload()
  const searchInputReload = page.getByPlaceholder('Search by monster name, type, or subtype…')
  await searchInputReload.fill('E2E Goblin Scout')
  await page.getByRole('button', { name: 'Refresh' }).click()
  const scoutItemAfterReload = page.locator('.monster-library__item').filter({
    has: page.locator('.monster-library__item-name', { hasText: /^E2E Goblin Scout$/ }),
  })
  await scoutItemAfterReload.click()
  await expect(acInput).toHaveValue('16')
})

test('M07-A Monster Library in zh-TW: built-in shows Chinese names and English desc with label, search ignores desc words', async ({
  page,
  roomContext,
}) => {
  test.setTimeout(180_000)
  const { roomId } = roomContext

  // Set locale in browser localStorage
  await page.goto('/')
  await page.evaluate(
    ({ room }) => {
      window.localStorage.setItem('adventure-table.recent-rooms.v1', JSON.stringify([room]))
      window.localStorage.setItem('adventure-table.locale', 'zh-TW')
      window.sessionStorage.setItem('adventure-table.active-room.v1', room.roomId)
    },
    {
      room: {
        roomId,
        code: roomContext.code,
        name: roomContext.name,
        accessToken: roomContext.accessToken,
        authority: roomContext.authority,
      },
    },
  )

  await page.goto(`/rooms/${roomId}/monster-library`)
  await expect(page.getByRole('heading', { name: '怪物庫', level: 1 })).toBeVisible()

  // Find built-in Goblin by typing into the search box (displays as '地精' in zh-TW)
  const searchInput = page.getByPlaceholder('搜尋怪物名稱、類型或子類型…')
  await searchInput.fill('地精')
  await page.getByRole('button', { name: '重新整理' }).click()

  const goblinItem = page.locator('.monster-library__item').filter({
    has: page.locator('.monster-library__item-name', { hasText: /^地精$/ }),
  })
  await expect(goblinItem).toBeVisible()
  await goblinItem.click()

  // Heading and ability names are localized, while ability desc shows English original with label
  await expect(page.locator('.monster-library__title-block h2').filter({ hasText: /^地精$/ })).toBeVisible()
  await expect(page.getByText('迅捷逃逸')).toBeVisible()
  await expect(page.locator('.monster-library__desc-lang-label').first()).toContainText('英文原文')

  // Search by an English description-only word: should NOT match Goblin
  await searchInput.fill('disengage')
  await page.getByRole('button', { name: '重新整理' }).click()

  await expect(page.getByText('找不到符合條件的怪物範本。')).toBeVisible()
  await expect(
    page.locator('.monster-library__item').filter({
      has: page.locator('.monster-library__item-name', { hasText: /^地精$/ }),
    }),
  ).not.toBeVisible()

  // Search by Chinese name: matches Goblin
  await searchInput.fill('地精')
  await page.getByRole('button', { name: '重新整理' }).click()
  await expect(
    page.locator('.monster-library__item').filter({
      has: page.locator('.monster-library__item-name', { hasText: /^地精$/ }),
    }),
  ).toBeVisible()
})

test('M07-A Member directly visiting /monster-library gets no library data and sees forbidden error', async ({
  browser,
  request,
  roomContext,
}) => {
  test.setTimeout(180_000)
  const { roomId } = roomContext
  const member = await enterAsMember(request, roomContext, 'M07A Member User')

  const context = await browser.newContext({ baseURL: PLAYWRIGHT_BASE_URL })
  const memberPage = await context.newPage()
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

  // 1. On room workspace, Monster Library button is NOT visible for member
  await memberPage.goto(`/rooms/${roomId}`)
  await expect(memberPage.getByRole('link', { name: 'Open Monster Library' })).not.toBeVisible()

  // 2. Direct navigation to /monster-library shows forbidden error and NO library data
  await memberPage.goto(`/rooms/${roomId}/monster-library`)
  await expect(
    memberPage.getByText('Only the Room owner or DM can manage the monster library.'),
  ).toBeVisible()
  await expect(memberPage.locator('.monster-library__list')).not.toBeVisible()
  await expect(memberPage.getByRole('button', { name: 'Create Custom Monster' })).not.toBeVisible()

  await context.close()
})
