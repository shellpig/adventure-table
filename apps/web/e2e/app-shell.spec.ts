import { expect, test } from '@playwright/test'

test('Adventure Table web shell opens at the Room-first entry', async ({ page }) => {
  await page.goto('/')

  await expect(page.getByRole('heading', { name: 'Adventure Table' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Start at the table' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Create Room' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Enter Room' })).toBeVisible()
  await expect(page.getByRole('link', { name: /Open P0 Fighter \/ Wizard Character Sheet/ })).toHaveCount(0)
})
