import { expect, test } from '@playwright/test'

test('P0-A app shell opens in a real browser', async ({ page }) => {
  await page.goto('/')

  await expect(page.getByRole('heading', { name: 'Adventure Table' })).toBeVisible()
  await expect(page.getByText('專案地基已啟動。')).toBeVisible()
})
