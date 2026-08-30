import { expect, test } from '@playwright/test'

test('Adventure Table app shell opens in a real browser', async ({ page }) => {
  await page.goto('/')

  await expect(page.getByRole('heading', { name: 'Adventure Table' })).toBeVisible()
  await expect(page.getByText('P1-G · Character Versions')).toBeVisible()
  await expect(page.getByRole('link', { name: /開啟 P0 Fighter \/ Wizard 角色卡/ })).toBeVisible()
})
