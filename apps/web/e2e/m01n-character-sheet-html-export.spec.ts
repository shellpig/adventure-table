import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

const FIXTURE_ID = '00000000-0000-4000-8000-0000000000e0'
const CHARACTER_URL = `/characters/${FIXTURE_ID}`

async function downloadFromSheet(page: Page) {
  const downloadPromise = page.waitForEvent('download')
  await page.getByTestId('character-html-export-button').click()
  return downloadPromise
}

test('M01-N exports both human-readable Character Sheet scopes', async ({ page }) => {
  await page.goto(CHARACTER_URL)
  await expect(page.getByRole('heading', { name: 'P0 Human Fighter 5 / Wizard 5' })).toBeVisible()

  const scope = page.getByTestId('character-html-export-scope')
  const exportButton = page.getByTestId('character-html-export-button')

  await expect(scope).toHaveValue('build')
  await expect(exportButton).toBeVisible()

  const buildDownload = await downloadFromSheet(page)
  expect(buildDownload.suggestedFilename()).toMatch(/-v\d+-build\.html$/)

  await scope.selectOption('snapshot')
  await expect(scope).toHaveValue('snapshot')
  const snapshotDownload = await downloadFromSheet(page)
  expect(snapshotDownload.suggestedFilename()).toMatch(/-v\d+-snapshot\.html$/)
})

test('M01-N HTML export stays independent from the existing JSON export action', async ({ page }) => {
  await page.goto(CHARACTER_URL)
  const hero = page.locator('.character-hero')

  await expect(hero.locator('.character-export-action button')).toBeVisible()
  await expect(hero.getByTestId('character-html-export-button')).toBeVisible()
  await expect(hero.getByTestId('character-html-export-scope')).toBeVisible()

  await page.getByRole('tab', { name: /Inventory/ }).click()
  await expect(page.getByText('Potion of Healing', { exact: true })).toBeVisible()
  await expect(hero.getByTestId('character-html-export-button')).toBeVisible()
})
