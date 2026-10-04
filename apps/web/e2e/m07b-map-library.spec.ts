import { deflateSync } from 'node:zlib'

import { expect, test, type Page } from './support/roomTest'
import {
  addSeat,
  createCampaign,
  json,
  startSession,
  type Lobby,
} from './support/quickCombat'

const CELL_SIZE = 40

/**
 * Minimal 8-bit truecolor PNG writer (solid colour). The bundled background
 * image must be a decodable png/jpeg/webp, so the spec draws its own known
 * grid fixture instead of shipping a binary.
 */
function makeSolidPng(width: number, height: number, r: number, g: number, b: number): Buffer {
  const crcTable = new Int32Array(256)
  for (let n = 0; n < 256; n += 1) {
    let c = n
    for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1
    crcTable[n] = c
  }
  const crc32 = (chunk: Buffer): Buffer => {
    let c = -1
    for (const byte of chunk) c = crcTable[(c ^ byte) & 0xff] ^ (c >>> 8)
    const out = Buffer.alloc(4)
    out.writeInt32BE(c ^ -1)
    return out
  }
  const chunk = (type: string, data: Buffer): Buffer => {
    const header = Buffer.alloc(8)
    header.writeUInt32BE(data.length, 0)
    header.write(type, 4, 'ascii')
    return Buffer.concat([header, data, crc32(Buffer.concat([Buffer.from(type, 'ascii'), data]))])
  }
  const header = Buffer.alloc(13)
  header.writeUInt32BE(width, 0)
  header.writeUInt32BE(height, 4)
  header[8] = 8 // bit depth
  header[9] = 2 // truecolor
  const rows: Buffer[] = []
  for (let y = 0; y < height; y += 1) {
    const row = Buffer.alloc(1 + width * 3)
    row[0] = 0 // filter: none
    for (let x = 0; x < width; x += 1) {
      row[1 + x * 3] = r
      row[1 + x * 3 + 1] = g
      row[1 + x * 3 + 2] = b
    }
    rows.push(row)
  }
  const signature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])
  return Buffer.concat([
    signature,
    chunk('IHDR', header),
    chunk('IDAT', deflateSync(Buffer.concat(rows))),
    chunk('IEND', Buffer.alloc(0)),
  ])
}

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

test('M07-D F13 Upload Image aligns the grid, saves offsets, and reopens with them', async ({
  page,
  request,
  roomContext,
}) => {
  test.setTimeout(180_000)
  const { roomId } = roomContext
  const mapName = 'E2E M07D Grid Photo'

  // A 400x400 background: at 40 px per cell it is exactly a 10x10 map.
  const png = makeSolidPng(400, 400, 90, 120, 160)

  await page.goto(`/rooms/${roomId}/battle-maps`)
  await expect(page.getByRole('heading', { name: 'Map Library', level: 1 })).toBeVisible()
  await page.getByTestId('create-image-map-btn').click()
  await page.getByTestId('create-image-map-name').fill(mapName)
  await page.getByTestId('create-image-map-file').setInputFiles({
    name: 'grid.png',
    mimeType: 'image/png',
    buffer: png,
  })
  // Uploading shows the grid overlay preview before confirming.
  await expect(page.getByTestId('create-image-map-preview')).toBeVisible()
  await page.getByTestId('create-image-map-width').fill('10')
  await page.getByTestId('create-image-map-height').fill('10')
  await page.getByTestId('create-image-map-grid-size').fill('40')
  await page.getByTestId('create-image-map-grid-offset-x').fill('5')
  await page.getByTestId('create-image-map-grid-offset-y').fill('7')
  await page.getByTestId('create-image-map-submit').click()

  const card = page.locator('.battle-map-card', { hasText: mapName })
  await expect(card).toBeVisible()

  const listed = await json<Array<{ id: string; name: string }>>(
    await request.get(`/api/rooms/${roomId}/battle-maps`),
  )
  const mapId = listed.find((m) => m.name === mapName)!.id
  const created = await json<{
    grid_pixel_size: number | null
    grid_offset_x: number | null
    grid_offset_y: number | null
  }>(await request.get(`/api/rooms/${roomId}/battle-maps/${mapId}`))
  expect(created).toMatchObject({ grid_pixel_size: 40, grid_offset_x: 5, grid_offset_y: 7 })

  // The editor keeps the saved values and draws the image aligned to them
  // (scale 1 here: 40 px per cell over a 40 px canvas cell).
  await card.getByRole('button', { name: 'Edit Map' }).click()
  await expect(page.getByTestId('map-editor-canvas')).toBeVisible()
  await expect(page.getByTestId('map-grid-panel')).toBeVisible()
  await expect(page.getByTestId('map-grid-size')).toHaveValue('40')
  await expect(page.getByTestId('map-grid-offset-x')).toHaveValue('5')
  await expect(page.getByTestId('map-grid-offset-y')).toHaveValue('7')
  const image = page.getByTestId('map-editor-canvas').getByTestId('battle-map-image')
  await expect(image).toHaveAttribute('x', '-5')
  await expect(image).toHaveAttribute('y', '-7')
  await expect(image).toHaveAttribute('width', '400')
  await expect(image).toHaveAttribute('height', '400')

  // Adjusting the offset in the editor persists across a reopen.
  await page.getByTestId('map-grid-offset-x').fill('9')
  await page.getByTestId('map-grid-save').click()
  await expect(page.getByTestId('map-grid-save-message')).toHaveText('Grid alignment saved.')
  await expect(image).toHaveAttribute('x', '-9')
  await page.getByTestId('editor-back-link').click()
  await expect(page.getByRole('heading', { name: 'Map Library', level: 1 })).toBeVisible()
  const reopenedCard = page.locator('.battle-map-card', { hasText: mapName })
  await reopenedCard.getByRole('button', { name: 'Edit Map' }).click()
  await expect(page.getByTestId('map-grid-offset-x')).toHaveValue('9')
  await expect(
    page.getByTestId('map-editor-canvas').getByTestId('battle-map-image'),
  ).toHaveAttribute('x', '-9')
})
