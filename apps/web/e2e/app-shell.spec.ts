import { expect, test } from '@playwright/test'

test('Adventure Table app shell opens in a real browser', async ({ page }) => {
  await page.goto('/')

  await expect(page.getByRole('heading', { name: 'Adventure Table' })).toBeVisible()
  await expect(page.getByText('M02-B · Localized Character Tools')).toBeVisible()
  await expect(page.getByRole('link', { name: /Open P0 Fighter \/ Wizard Character Sheet/ })).toBeVisible()
})
