import { readFile } from 'node:fs/promises'

import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

const FIXTURE_ID = '00000000-0000-4000-8000-0000000000e0'

async function downloadedJson(page: Page, buttonName: string | RegExp) {
  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: buttonName }).click()
  const download = await downloadPromise
  const path = await download.path()
  expect(path).not.toBeNull()
  const document = JSON.parse(await readFile(path!, 'utf8'))
  return { download, document }
}

test('Workshop exports an active character and exposes unstable schema controls', async ({ page }) => {
  await page.goto('/characters')
  const card = page.locator('article.workshop-card').filter({ hasText: 'P0 Human Fighter 5 / Wizard 5' })
  await expect(card).toBeVisible()

  const downloadPromise = page.waitForEvent('download')
  await card.getByRole('button', { name: 'Export character JSON' }).click()
  const download = await downloadPromise
  const path = await download.path()
  expect(path).not.toBeNull()
  const document = JSON.parse(await readFile(path!, 'utf8'))
  expect(document.envelope.schema_version).toBe('unstable')
  expect(document.envelope.schema_status).toBe('unstable')
})

test('Character Sheet mounts export inside the real sheet header', async ({ page }) => {
  await page.goto(`/characters/${FIXTURE_ID}`)
  const hero = page.locator('.character-hero')
  await expect(hero.getByRole('button', { name: 'Export character JSON' })).toBeVisible()
  await expect(page.locator('.character-export-sheet-action')).not.toHaveCSS('position', 'fixed')

  const { document } = await downloadedJson(page, 'Export character JSON')
  expect(document.payload.current_version_no).toBeGreaterThanOrEqual(1)
})

test('export labels are complete in English and zh-TW', async ({ page }) => {
  await page.goto(`/characters/${FIXTURE_ID}`)
  await expect(page.getByRole('button', { name: 'Export character JSON' })).toHaveText('Export JSON')

  await page.getByTestId('locale-option-zh-TW').click()
  await expect(page.getByRole('button', { name: '匯出角色 JSON' })).toHaveText('匯出 JSON')
})

test('archived character remains exportable from Workshop', async ({ page, request }) => {
  const archived = await request.post(`/api/characters/${FIXTURE_ID}/archive`)
  expect(archived.ok()).toBeTruthy()
  try {
    await page.goto('/characters')
    const card = page.locator('article.workshop-card--archived').filter({ hasText: 'P0 Human Fighter 5 / Wizard 5' })
    await expect(card).toBeVisible()
    const downloadPromise = page.waitForEvent('download')
    await card.getByRole('button', { name: 'Export character JSON' }).click()
    const download = await downloadPromise
    expect(download.suggestedFilename()).toMatch(/\.json$/)
  } finally {
    const restored = await request.post(`/api/characters/${FIXTURE_ID}/unarchive`)
    expect(restored.ok()).toBeTruthy()
  }
})

test('filename star preserves Unicode without mojibake', async ({ page }) => {
  await page.route(`**/api/characters/${FIXTURE_ID}/export`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      headers: {
        'content-disposition': "attachment; filename=\"character-v1-test.json\"; filename*=UTF-8''%E6%B8%AC%E8%A9%A6%20%E8%A7%92%E8%89%B2-v1-test.json",
      },
      body: JSON.stringify({ envelope: { schema_version: 'unstable', schema_status: 'unstable' } }),
    })
  })
  await page.goto(`/characters/${FIXTURE_ID}`)
  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Export character JSON' }).click()
  const download = await downloadPromise
  expect(download.suggestedFilename()).toBe('測試 角色-v1-test.json')
})

test('M03-B UI exposes no import action before M03-C', async ({ page }) => {
  await page.goto('/characters')
  await expect(page.getByRole('button', { name: /import/i })).toHaveCount(0)
  await expect(page.getByRole('link', { name: /import/i })).toHaveCount(0)
})
