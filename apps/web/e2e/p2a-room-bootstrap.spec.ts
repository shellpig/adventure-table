import { expect, test } from '@playwright/test'

import { enterRoom, openCharacterWorkshop } from './support/room'

test('P2-A Room bootstrap creates isolated browser Room contexts', async ({ browser }) => {
  const firstBrowser = await browser.newContext()
  const secondBrowser = await browser.newContext()
  const firstPage = await firstBrowser.newPage()
  const secondPage = await secondBrowser.newPage()

  try {
    const [first, second] = await Promise.all([
      enterRoom(firstPage, { name: 'E2E Bootstrap First' }),
      enterRoom(secondPage, { name: 'E2E Bootstrap Second' }),
    ])

    expect(first.authority).toBe('owner')
    expect(second.authority).toBe('owner')
    expect(first.roomId).not.toBe(second.roomId)
    expect(first.code).not.toBe(second.code)
    expect(first.accessToken).not.toBe(second.accessToken)
    await expect(firstPage.locator('html')).toHaveAttribute('lang', 'en')
    await expect(secondPage.locator('html')).toHaveAttribute('lang', 'en')
  } finally {
    await firstBrowser.close()
    await secondBrowser.close()
  }
})

test('P2-A Room bootstrap preserves the browser locale across navigation and reload', async ({ page }) => {
  await page.goto('/')
  await page.getByTestId('locale-option-en').click()
  await page.getByTestId('locale-option-zh-TW').click()
  await expect(page.locator('html')).toHaveAttribute('lang', 'zh-TW')

  await enterRoom(page, { name: 'E2E Locale Preserve' })
  await expect(page.locator('html')).toHaveAttribute('lang', 'zh-TW')

  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('lang', 'zh-TW')
})

test('P2-B Workshop helper navigates through the authenticated Room namespace', async ({ page }) => {
  const room = await enterRoom(page, { name: 'E2E Workshop Seam' })

  await openCharacterWorkshop(page, room)

  await expect(page.getByRole('heading', { name: /^(Character Workshop|角色工作坊)$/ })).toBeVisible()
  await expect(page).toHaveURL(new RegExp(`/rooms/${room.roomId}/characters/?$`))
})
