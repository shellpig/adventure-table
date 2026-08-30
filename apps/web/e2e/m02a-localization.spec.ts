import { expect, test, type Page } from '@playwright/test'

const LOCALE_STORAGE_KEY = 'adventure-table.locale'

type BuilderDraftSnapshot = {
  draft: {
    revision: number
    draft_payload: unknown
  }
}

async function resetLocale(page: Page) {
  await page.goto('/')
  await page.evaluate((key) => localStorage.removeItem(key), LOCALE_STORAGE_KEY)
  await page.reload()
}

async function readDraft(page: Page, draftId: string): Promise<BuilderDraftSnapshot> {
  return page.evaluate(async (id) => {
    const response = await fetch(`/api/character-builder/drafts/${id}`)
    if (!response.ok) throw new Error(`Failed to read Builder Draft (${response.status})`)
    return response.json()
  }, draftId)
}

test('M02-A switches locale without reload and persists browser preference', async ({ page, context }) => {
  await resetLocale(page)

  const initialUrl = page.url()
  await expect(page.locator('html')).toHaveAttribute('lang', 'zh-TW')
  await expect(page.getByTestId('locale-option-zh-TW')).toHaveAttribute('aria-pressed', 'true')

  await page.evaluate(() => {
    ;(window as Window & { __m02RuntimeMarker?: string }).__m02RuntimeMarker = 'alive'
  })
  await page.getByTestId('locale-option-en').click()

  await expect(page).toHaveURL(initialUrl)
  await expect(page.locator('html')).toHaveAttribute('lang', 'en')
  await expect(page.getByTestId('locale-option-en')).toHaveAttribute('aria-pressed', 'true')
  expect(
    await page.evaluate(() => (window as Window & { __m02RuntimeMarker?: string }).__m02RuntimeMarker),
  ).toBe('alive')
  expect(await page.evaluate((key) => localStorage.getItem(key), LOCALE_STORAGE_KEY)).toBe('en')

  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('lang', 'en')
  await expect(page.getByTestId('locale-option-en')).toHaveAttribute('aria-pressed', 'true')

  const reopened = await context.newPage()
  await reopened.goto('/')
  await expect(reopened.locator('html')).toHaveAttribute('lang', 'en')
  await expect(reopened.getByTestId('locale-option-en')).toHaveAttribute('aria-pressed', 'true')
  await reopened.close()

  await page.getByTestId('locale-option-zh-TW').click()
  await expect(page.locator('html')).toHaveAttribute('lang', 'zh-TW')
  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('lang', 'zh-TW')
})

test('M02-A invalid stored locale safely normalizes to zh-TW', async ({ page }) => {
  await page.goto('/')
  await page.evaluate((key) => localStorage.setItem(key, 'ja'), LOCALE_STORAGE_KEY)
  await page.reload()

  await expect(page.locator('html')).toHaveAttribute('lang', 'zh-TW')
  await expect(page.getByTestId('locale-option-zh-TW')).toHaveAttribute('aria-pressed', 'true')
  await expect.poll(() => page.evaluate((key) => localStorage.getItem(key), LOCALE_STORAGE_KEY)).toBe('zh-TW')
})

test('M02-A locale switching preserves Builder step, URL and Draft domain state', async ({ page }) => {
  await resetLocale(page)
  await page.goto('/characters')
  await expect(page.getByRole('heading', { name: 'Character Workshop' })).toBeVisible()

  await page.getByRole('button', { name: '+ Create Character' }).click()
  await expect(page).toHaveURL(/\/character-builder\/[0-9a-f-]{36}$/)
  await expect(page.getByText('Saved on server')).toBeVisible()

  await page.getByRole('button', { name: /Origin/ }).click()
  await expect(page.getByRole('heading', { name: 'Choose an origin' })).toBeVisible()

  const url = page.url()
  const draftId = url.match(/\/character-builder\/([0-9a-f-]{36})$/)?.[1]
  if (!draftId) throw new Error('Builder Draft id was not present in the URL')

  const before = await readDraft(page, draftId)
  const mutationRequests: string[] = []
  const mutationListener = (request: { method: () => string; url: () => string }) => {
    if (
      request.url().includes(`/api/character-builder/drafts/${draftId}`) &&
      ['PATCH', 'POST', 'DELETE'].includes(request.method())
    ) {
      mutationRequests.push(`${request.method()} ${request.url()}`)
    }
  }
  page.on('request', mutationListener)

  await page.getByTestId('locale-option-en').click()
  await expect(page).toHaveURL(url)
  await expect(page.locator('html')).toHaveAttribute('lang', 'en')
  await expect(page.getByRole('heading', { name: 'Choose an origin' })).toBeVisible()

  await page.getByTestId('locale-option-zh-TW').click()
  await expect(page).toHaveURL(url)
  await expect(page.locator('html')).toHaveAttribute('lang', 'zh-TW')
  await expect(page.getByRole('heading', { name: 'Choose an origin' })).toBeVisible()

  page.off('request', mutationListener)
  const after = await readDraft(page, draftId)

  expect(after.draft.revision).toBe(before.draft.revision)
  expect(after.draft.draft_payload).toEqual(before.draft.draft_payload)
  expect(mutationRequests).toEqual([])
})
