import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'

import { expect, test } from '@playwright/test'

const fixturePath = (name: string) =>
  resolve(process.cwd(), '../server/tests/data/m03', name)

async function openImport(page: import('@playwright/test').Page) {
  await page.goto('/characters')
  await page.getByRole('button', { name: 'Import character JSON' }).first().click()
}

test('imports a character JSON file through preview and commit', async ({ page }) => {
  await openImport(page)
  await page.locator('input[type="file"]').setInputFiles(fixturePath('fixture_low_level_srd.json'))
  await page.getByRole('button', { name: 'Preview import' }).click()
  await expect(page.getByText(/0 unresolved/)).toBeVisible()
  await expect(page.getByText(/new character with full history/)).toBeVisible()
  await page.getByRole('button', { name: 'Continue import' }).click()
  await page.waitForURL(/\/characters\/[0-9a-f-]+$/)
})

test('pasted JSON uses the same preview path', async ({ page }) => {
  await openImport(page)
  const text = await readFile(fixturePath('fixture_low_level_srd.json'), 'utf8')
  await page.getByLabel('Paste character JSON').fill(text)
  await page.getByRole('button', { name: 'Preview import' }).click()
  await expect(page.getByText(/0 unresolved/)).toBeVisible()
  await expect(page.getByText(/Landing mode: new character with full history/)).toBeVisible()
})

test('state-only unresolved import requires explicit history-loss confirmation', async ({ page }) => {
  await openImport(page)
  await page.locator('input[type="file"]').setInputFiles(
    fixturePath('fixture_state_only_missing_inventory.json'),
  )
  await page.getByRole('button', { name: 'Preview import' }).click()
  await expect(page.getByText(/Current State and the complete Version History will not be kept/)).toBeVisible()
  const commit = page.getByRole('button', { name: 'Continue import' })
  await expect(commit).toBeDisabled()
  await page.getByLabel(/I understand that Current State and Version History will be discarded/).check()
  await expect(commit).toBeEnabled()
})

test('duplicate preview shows count and most-recent import time', async ({ page, request }) => {
  const text = await readFile(fixturePath('fixture_low_level_srd.json'), 'utf8')
  const committed = await request.post('/api/characters/import', {
    data: text,
    headers: { 'Content-Type': 'application/json' },
  })
  expect(committed.status()).toBe(201)

  await openImport(page)
  await page.getByLabel('Paste character JSON').fill(text)
  await page.getByRole('button', { name: 'Preview import' }).click()
  await expect(page.getByText(/Most recent:/)).toBeVisible()
})

test('import rejection messages are localized in English and zh-TW', async ({ page }) => {
  await openImport(page)
  await page.getByLabel('Paste character JSON').fill('{"envelope":')
  await page.getByRole('button', { name: 'Preview import' }).click()
  await expect(page.getByRole('alert')).toContainText('The import envelope is invalid')

  await page.getByRole('button', { name: 'Cancel' }).click()
  await page.getByTestId('locale-option-zh-TW').click()
  await page.getByRole('button', { name: '匯入角色 JSON' }).first().click()
  await page.getByLabel('貼上角色 JSON').fill('{"envelope":')
  await page.getByRole('button', { name: '預覽匯入' }).click()
  await expect(page.getByRole('alert')).toContainText('匯入檔案的外層格式無效')
})

test('missing XGE build refs land in a Draft when the backend is started without XGE', async ({ page }) => {
  test.skip(
    process.env.M03C_E2E_DISABLE_XGE !== '1',
    'run this contract with ADVENTURE_TABLE_ENABLED_CONTENT_PACKS excluding xge',
  )
  await openImport(page)
  await page.locator('input[type="file"]').setInputFiles(fixturePath('fixture_xge_dependent.json'))
  await page.getByRole('button', { name: 'Preview import' }).click()
  await expect(page.getByText(/Landing mode: Builder Draft/)).toBeVisible()
})

test('legacy import without provenance is rejected when a required pack is disabled', async ({ page }) => {
  test.skip(
    process.env.M03C_E2E_DISABLE_XGE !== '1',
    'run this contract with ADVENTURE_TABLE_ENABLED_CONTENT_PACKS excluding xge',
  )
  await openImport(page)
  const legacy = JSON.parse(await readFile(fixturePath('fixture_legacy_no_provenance.json'), 'utf8'))
  legacy.payload.versions[0].build_payload.race_ref = 'xge:race:portable-test-race'
  await page.getByLabel('Paste character JSON').fill(JSON.stringify(legacy))
  await page.getByRole('button', { name: 'Preview import' }).click()
  await expect(page.getByRole('alert')).toContainText('does not contain enough Builder provenance')
})
