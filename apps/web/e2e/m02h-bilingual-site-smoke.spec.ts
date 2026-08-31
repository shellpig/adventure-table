import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

const FIXTURE_ID = '00000000-0000-4000-8000-0000000000e0'
const LOCALE_STORAGE_KEY = 'adventure-table.locale'

type Locale = 'zh-TW' | 'en'

type RouteCheck = {
  path: string
  zh: string | RegExp
  en: string | RegExp
  role?: 'heading' | 'tablist'
}

const ROUTES: RouteCheck[] = [
  { path: '/', zh: 'Adventure Table', en: 'Adventure Table', role: 'heading' },
  { path: '/characters', zh: '角色工作坊', en: 'Character Workshop', role: 'heading' },
  { path: `/characters/${FIXTURE_ID}`, zh: '角色卡分頁', en: 'Character Sheet tabs', role: 'tablist' },
  { path: `/characters/${FIXTURE_ID}/versions`, zh: '角色版本', en: 'Character Versions', role: 'heading' },
]

const BUILDER_STEPS = {
  'zh-TW': [
    [/基本/, '先設定角色基本資料'],
    [/出身/, '選擇出身'],
    [/屬性/, '屬性與起始選擇'],
    [/職業/, '建立逐等級職業配置'],
    [/施法/, '施法與資源'],
    [/裝備/, '裝備與角色扮演'],
    [/檢視/, '角色配置快照與最終檢視'],
  ],
  en: [
    [/Basic/, 'Start with the character'],
    [/Origin/, 'Choose an origin'],
    [/Abilities/, 'Abilities & starting choices'],
    [/Class/, 'Build the level rail'],
    [/Spellcasting/, 'Spellcasting & resources'],
    [/Equipment/, 'Equipment & roleplay'],
    [/Review/, 'Build snapshot & final review'],
  ],
} as const

async function createDraft(request: APIRequestContext) {
  const response = await request.post('/api/character-builder/drafts', {
    data: { mode: 'create', draft_payload: {} },
  })
  expect(response.ok()).toBeTruthy()
  const payload = await response.json()
  return payload.draft.id as string
}

async function forceLocale(page: Page, locale: Locale) {
  await page.evaluate(
    ({ key, value }) => localStorage.setItem(key, value),
    { key: LOCALE_STORAGE_KEY, value: locale },
  )
  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('lang', locale)
}

async function expectNoHorizontalOverflow(page: Page) {
  const dimensions = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }))
  expect(
    dimensions.scrollWidth,
    `horizontal overflow: scrollWidth=${dimensions.scrollWidth}, clientWidth=${dimensions.clientWidth}`,
  ).toBeLessThanOrEqual(dimensions.clientWidth + 1)
}

async function expectRouteMarker(page: Page, route: RouteCheck, locale: Locale) {
  const marker = locale === 'zh-TW' ? route.zh : route.en
  if (route.role === 'tablist') {
    await expect(page.getByRole('tablist', { name: marker })).toBeVisible()
  } else {
    await expect(page.getByRole('heading', { name: marker })).toBeVisible()
  }
}

async function expectNoKnownOppositeLocaleLeak(page: Page, locale: Locale) {
  const body = page.locator('body')
  if (locale === 'zh-TW') {
    await expect(body.getByText('Character Workshop', { exact: true })).toHaveCount(0)
    await expect(body.getByText('Character Versions', { exact: true })).toHaveCount(0)
    await expect(body.getByText('Build snapshot & final review', { exact: true })).toHaveCount(0)
    await expect(body.getByText('Add Condition', { exact: true })).toHaveCount(0)
  } else {
    await expect(body.getByText('角色工作坊', { exact: true })).toHaveCount(0)
    await expect(body.getByText('角色版本', { exact: true })).toHaveCount(0)
    await expect(body.getByText('角色配置快照與最終檢視', { exact: true })).toHaveCount(0)
    await expect(body.getByText('新增狀態', { exact: true })).toHaveCount(0)
  }
}

for (const viewport of [
  { name: 'desktop', width: 1280, height: 720 },
  { name: 'mobile', width: 390, height: 844 },
] as const) {
  for (const locale of ['zh-TW', 'en'] as const) {
    test(`M02-H ${locale} ${viewport.name} route crawl has localized chrome and no horizontal overflow`, async ({ page }) => {
      const pageErrors: string[] = []
      const consoleErrors: string[] = []
      page.on('pageerror', (error) => pageErrors.push(error.message))
      page.on('console', (message) => {
        if (message.type() === 'error') consoleErrors.push(message.text())
      })
      await page.setViewportSize({ width: viewport.width, height: viewport.height })

      for (const route of ROUTES) {
        await page.goto(route.path)
        await forceLocale(page, locale)
        await expectRouteMarker(page, route, locale)
        await expectNoKnownOppositeLocaleLeak(page, locale)
        await expectNoHorizontalOverflow(page)
      }

      expect(pageErrors).toEqual([])
      expect(consoleErrors).toEqual([])
    })
  }
}

test('M02-H crawls every Builder step in zh-TW and en with localized headings and overflow gate', async ({ page, request }) => {
  test.slow()
  const draftId = await createDraft(request)

  for (const locale of ['zh-TW', 'en'] as const) {
    await page.goto(`/character-builder/${draftId}`)
    await forceLocale(page, locale)

    for (const [buttonName, heading] of BUILDER_STEPS[locale]) {
      await page.locator('.builder-rail').getByRole('button', { name: buttonName }).click()
      await expect(page.getByRole('heading', { name: heading })).toBeVisible()
      await expectNoKnownOppositeLocaleLeak(page, locale)
      await expectNoHorizontalOverflow(page)
    }
  }
})

test('M02-H mobile Builder step crawl catches layout overflow in both locales', async ({ page, request }) => {
  test.slow()
  const draftId = await createDraft(request)
  await page.setViewportSize({ width: 390, height: 844 })

  for (const locale of ['zh-TW', 'en'] as const) {
    await page.goto(`/character-builder/${draftId}`)
    await forceLocale(page, locale)
    for (const [buttonName, heading] of BUILDER_STEPS[locale]) {
      await page.locator('.builder-rail').getByRole('button', { name: buttonName }).click()
      await expect(page.getByRole('heading', { name: heading })).toBeVisible()
      await expectNoHorizontalOverflow(page)
    }
  }
})
