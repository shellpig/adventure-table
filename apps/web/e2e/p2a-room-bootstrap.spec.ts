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
  } finally {
    await firstBrowser.close()
    await secondBrowser.close()
  }
})

test('P2-A Workshop helper keeps a real Room access context before transitional navigation', async ({ page }) => {
  const room = await enterRoom(page, { name: 'E2E Workshop Seam' })

  await openCharacterWorkshop(page, room)

  await expect(page.getByRole('heading', { name: 'Character Workshop' })).toBeVisible()
  await expect(page).toHaveURL(/\/characters\/?$/)
})
