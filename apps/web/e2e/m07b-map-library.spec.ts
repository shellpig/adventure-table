import { expect, test, type Page } from './support/roomTest'
import {
  addSeat,
  createCampaign,
  json,
  startSession,
  type Lobby,
} from './support/quickCombat'

const CELL_SIZE = 40

async function mapPoint(page: Page, x: number, y: number) {
  return page
    .getByTestId('map-editor-canvas')
    .locator('svg[data-testid="battle-map"]')
    .evaluate(
      (svg, [cx, cy, size]) => {
        const point = new DOMPoint(cx * size, cy * size).matrixTransform(
          (svg as SVGSVGElement).getScreenCTM()!,
        )
        return { x: point.x, y: point.y }
      },
      [x, y, CELL_SIZE] as const,
    )
}

test('M07-B Map Library lifecycle journey in English: create, edit wall, save, reopen, copy, archive, and tactical combat selection', async ({
  page,
  request,
  roomContext,
}) => {
  test.setTimeout(180_000)
  const { roomId } = roomContext

  // 1. From Room workspace with no Session open the map library
  await page.goto(`/rooms/${roomId}`)
  const libLink = page.getByRole('link', { name: 'Open Map Library' })
  await expect(libLink).toBeVisible()
  await libLink.click()
  await expect(page).toHaveURL(new RegExp(`/rooms/${roomId}/battle-maps/?$`))
  await expect(page.getByRole('heading', { name: 'Map Library', level: 1 })).toBeVisible()

  // 2. Create a blank map
  await page.getByTestId('create-blank-map-btn').click()
  await page.getByTestId('create-blank-map-name').fill('E2E Fortress')
  await page.getByTestId('create-blank-map-width').fill('10')
  await page.getByTestId('create-blank-map-height').fill('8')
  await page.getByTestId('create-blank-map-submit').click()

  const card = page.locator('.battle-map-card', { hasText: 'E2E Fortress' })
  await expect(card).toBeVisible()

  // 3. Edit it in the editor (add a wall)
  await card.getByRole('button', { name: 'Edit Map' }).click()
  await expect(page.getByTestId('map-editor-canvas')).toBeVisible()
  await page.getByTestId('map-editor-tool-wall').click()
  await page.getByTestId('map-editor-canvas').scrollIntoViewIfNeeded()
  const wallAt = await mapPoint(page, 4.5, 4.05)
  await page.mouse.click(wallAt.x, wallAt.y)
  await expect(page.getByTestId('map-editor-canvas').getByTestId('battle-map-wall')).toHaveCount(1)

  // 4. Save
  await page.getByTestId('map-editor-save').click()
  await expect(page.getByTestId('map-editor-save-message')).toHaveText('Saved')
  await page.getByTestId('editor-back-link').click()
  await expect(page.getByRole('heading', { name: 'Map Library', level: 1 })).toBeVisible()

  // 5. Reopen and see the wall
  await card.getByRole('button', { name: 'Edit Map' }).click()
  await expect(page.getByTestId('map-editor-canvas')).toBeVisible()
  await expect(page.getByTestId('map-editor-canvas').getByTestId('battle-map-wall')).toHaveCount(1)
  await page.getByTestId('editor-back-link').click()

  // 6. Copy it
  await card.getByRole('button', { name: 'Copy' }).click()
  await page.getByTestId('copy-map-name').fill('E2E Fortress Copy')
  await page.getByTestId('copy-map-submit').click()
  const copyCard = page.locator('.battle-map-card', { hasText: 'E2E Fortress Copy' })
  await expect(copyCard).toBeVisible()

  // 7. Archive the copy (hidden by default, visible with the toggle)
  page.once('dialog', async (dialog) => {
    await dialog.accept()
  })
  await copyCard.getByRole('button', { name: 'Archive' }).click()

  // Verify hidden by default
  await expect(page.locator('.battle-map-card', { hasText: 'E2E Fortress Copy' })).toHaveCount(0)

  // Visible with toggle
  await page.getByTestId('show-archived-toggle').check()
  const archivedCard = page.locator('.battle-map-card', { hasText: 'E2E Fortress Copy' })
  await expect(archivedCard).toBeVisible()
  await expect(archivedCard.getByTestId(/map-archived-badge-/)).toBeVisible()

  // 8. In a Session open Tactical Setup and see the original map selectable while the archived copy is not
  const campaign = await createCampaign(request, roomId, 'M07-B Tactical Setup En')
  const lobby = await json<Lobby>(
    await request.get(`/api/rooms/${roomId}/campaigns/${campaign.id}/lobby`),
  )
  await addSeat(request, roomId, campaign.id, 'dm', lobby.caller_access_session_id!, 'DM En')
  await startSession(page, roomId, campaign.id)
  await page.getByTestId('tactical-start-open').click()

  // Original map visible
  await expect(page.locator('.tactical-setup__map-list', { hasText: 'E2E Fortress' })).toBeVisible()
  // Archived map not visible
  await expect(page.locator('.tactical-setup__map-list', { hasText: 'E2E Fortress Copy' })).toHaveCount(0)
})

test('M07-B Map Library lifecycle journey in zh-TW: create, edit wall, save, reopen, copy, archive, and tactical combat selection', async ({
  page,
  request,
  roomContext,
}) => {
  test.setTimeout(180_000)
  const { roomId } = roomContext

  // Set locale in browser localStorage
  await page.goto('/')
  await page.evaluate(
    ({ room }) => {
      window.localStorage.setItem('adventure-table.recent-rooms.v1', JSON.stringify([room]))
      window.localStorage.setItem('adventure-table.locale', 'zh-TW')
      window.sessionStorage.setItem('adventure-table.active-room.v1', room.roomId)
    },
    {
      room: {
        roomId,
        code: roomContext.code,
        name: roomContext.name,
        accessToken: roomContext.accessToken,
        authority: roomContext.authority,
      },
    },
  )

  // 1. From Room workspace with no Session open the map library
  await page.goto(`/rooms/${roomId}`)
  const libLink = page.getByRole('link', { name: '開啟地圖庫' })
  await expect(libLink).toBeVisible()
  await libLink.click()
  await expect(page).toHaveURL(new RegExp(`/rooms/${roomId}/battle-maps/?$`))
  await expect(page.getByRole('heading', { name: '地圖庫', level: 1 })).toBeVisible()

  // 2. Create a blank map
  await page.getByTestId('create-blank-map-btn').click()
  await page.getByTestId('create-blank-map-name').fill('繁中要塞')
  await page.getByTestId('create-blank-map-width').fill('10')
  await page.getByTestId('create-blank-map-height').fill('8')
  await page.getByTestId('create-blank-map-submit').click()

  const card = page.locator('.battle-map-card', { hasText: '繁中要塞' })
  await expect(card).toBeVisible()

  // 3. Edit it in the editor (add a wall)
  await card.getByRole('button', { name: '編輯地圖' }).click()
  await expect(page.getByTestId('map-editor-canvas')).toBeVisible()
  await page.getByTestId('map-editor-tool-wall').click()
  await page.getByTestId('map-editor-canvas').scrollIntoViewIfNeeded()
  const wallAt = await mapPoint(page, 4.5, 4.05)
  await page.mouse.click(wallAt.x, wallAt.y)
  await expect(page.getByTestId('map-editor-canvas').getByTestId('battle-map-wall')).toHaveCount(1)

  // 4. Save
  await page.getByTestId('map-editor-save').click()
  await expect(page.getByTestId('map-editor-save-message')).toHaveText('已儲存')
  await page.getByTestId('editor-back-link').click()
  await expect(page.getByRole('heading', { name: '地圖庫', level: 1 })).toBeVisible()

  // 5. Reopen and see the wall
  await card.getByRole('button', { name: '編輯地圖' }).click()
  await expect(page.getByTestId('map-editor-canvas')).toBeVisible()
  await expect(page.getByTestId('map-editor-canvas').getByTestId('battle-map-wall')).toHaveCount(1)
  await page.getByTestId('editor-back-link').click()

  // 6. Copy it
  await card.getByRole('button', { name: '複製' }).click()
  await page.getByTestId('copy-map-name').fill('繁中要塞副本')
  await page.getByTestId('copy-map-submit').click()
  const copyCard = page.locator('.battle-map-card', { hasText: '繁中要塞副本' })
  await expect(copyCard).toBeVisible()

  // 7. Archive the copy (hidden by default, visible with the toggle)
  page.once('dialog', async (dialog) => {
    await dialog.accept()
  })
  await copyCard.getByRole('button', { name: '封存' }).click()

  // Verify hidden by default
  await expect(page.locator('.battle-map-card', { hasText: '繁中要塞副本' })).toHaveCount(0)

  // Visible with toggle
  await page.getByTestId('show-archived-toggle').check()
  const archivedCard = page.locator('.battle-map-card', { hasText: '繁中要塞副本' })
  await expect(archivedCard).toBeVisible()
  await expect(archivedCard.getByTestId(/map-archived-badge-/)).toBeVisible()

  // 8. In a Session open Tactical Setup and see the original map selectable while the archived copy is not
  const campaign = await createCampaign(request, roomId, 'M07-B Tactical Setup Zh')
  const lobby = await json<Lobby>(
    await request.get(`/api/rooms/${roomId}/campaigns/${campaign.id}/lobby`),
  )
  await addSeat(request, roomId, campaign.id, 'dm', lobby.caller_access_session_id!, 'DM Zh')
  // The shared startSession helper drives the English lobby; the zh-TW library
  // flow above is what this test covers.
  await page.evaluate(() => window.localStorage.setItem('adventure-table.locale', 'en'))
  await startSession(page, roomId, campaign.id)
  await page.getByTestId('tactical-start-open').click()

  // Original map visible
  await expect(page.locator('.tactical-setup__map-list', { hasText: '繁中要塞' })).toBeVisible()
  // Archived map not visible
  await expect(page.locator('.tactical-setup__map-list', { hasText: '繁中要塞副本' })).toHaveCount(0)
})
