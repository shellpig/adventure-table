import { deflateSync } from 'node:zlib'

import { expect, test, type Page } from './support/roomTest'
import {
  ACTIVE_ROOM_STORAGE_KEY,
  addPlayerSeat,
  addSeat,
  createCampaign,
  enterAsMember,
  importCharacter,
  json,
  LOCALE_STORAGE_KEY,
  PLAYWRIGHT_BASE_URL,
  RECENT_ROOMS_STORAGE_KEY,
  startSession,
  type Lobby,
} from './support/quickCombat'
import { mapPanel, token } from './support/tactical'

const CELL_SIZE = 40
const GOBLIN_REF = 'srd5.1:monster:goblin'

/** Minimal 8-bit truecolor PNG writer (solid colour), copied from m07b. */
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
  header[8] = 8
  header[9] = 2
  const rows: Buffer[] = []
  for (let y = 0; y < height; y += 1) {
    const row = Buffer.alloc(1 + width * 3)
    row[0] = 0
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

function editorImage(page: Page) {
  return page.getByTestId('map-editor-canvas').getByTestId('battle-map-image')
}

function editorTokens(page: Page, extra = '') {
  return page.getByTestId('map-editor-canvas').locator(`[data-testid="battle-map-token"]${extra}`)
}

async function uploadImageMap(
  page: Page,
  mapName: string,
  png: Buffer,
  widthCells: string,
  heightCells: string,
  gridSize: string,
  offsetX: string,
  offsetY: string,
) {
  await page.getByTestId('create-image-map-btn').click()
  await page.getByTestId('create-image-map-name').fill(mapName)
  await page.getByTestId('create-image-map-file').setInputFiles({
    name: 'grid.png',
    mimeType: 'image/png',
    buffer: png,
  })
  await expect(page.getByTestId('create-image-map-preview')).toBeVisible()
  await page.getByTestId('create-image-map-width').fill(widthCells)
  await page.getByTestId('create-image-map-height').fill(heightCells)
  await page.getByTestId('create-image-map-grid-size').fill(gridSize)
  await page.getByTestId('create-image-map-grid-offset-x').fill(offsetX)
  await page.getByTestId('create-image-map-grid-offset-y').fill(offsetY)
  await page.getByTestId('create-image-map-submit').click()
  await expect(page.locator('.battle-map-card', { hasText: mapName })).toBeVisible()
}

test('M07-D D2c F13: default upload, size-only save, and draft preview all render the exact image rectangle', async ({
  page,
  request,
  roomContext,
}) => {
  test.setTimeout(240_000)
  const { roomId } = roomContext
  await page.goto(`/rooms/${roomId}/battle-maps`)
  await expect(page.getByRole('heading', { name: 'Map Library', level: 1 })).toBeVisible()

  // 1. Default upload: grid inputs left blank. The preview overlay already
  // shows the explicit size-40/offset-0 defaults, and the saved payload must
  // match it exactly (not nulls that would silently stretch).
  // 400x400 image on an 8x8 map: aligned width is 400, stretch would be 320.
  const defaultName = 'E2E D2c Default Grid Photo'
  await uploadImageMap(page, defaultName, makeSolidPng(400, 400, 90, 120, 160), '8', '8', '', '', '')
  const listed = await json<Array<{ id: string; name: string }>>(
    await request.get(`/api/rooms/${roomId}/battle-maps`),
  )
  const defaultId = listed.find((m) => m.name === defaultName)!.id
  const defaultSaved = await json<{
    grid_pixel_size: number | null
    grid_offset_x: number | null
    grid_offset_y: number | null
  }>(await request.get(`/api/rooms/${roomId}/battle-maps/${defaultId}`))
  expect(defaultSaved).toMatchObject({ grid_pixel_size: 40, grid_offset_x: 0, grid_offset_y: 0 })

  // The editor renders the actual image rectangle aligned, not stretched.
  await page.locator('.battle-map-card', { hasText: defaultName }).getByRole('button', { name: 'Edit Map' }).click()
  await expect(page.getByTestId('map-editor-canvas')).toBeVisible()
  await expect(page.getByTestId('map-grid-size')).toHaveValue('40')
  await expect(page.getByTestId('map-grid-offset-x')).toHaveValue('0')
  await expect(page.getByTestId('map-grid-offset-y')).toHaveValue('0')
  await expect(editorImage(page)).toHaveAttribute('x', '0')
  await expect(editorImage(page)).toHaveAttribute('y', '0')
  await expect(editorImage(page)).toHaveAttribute('width', '400')
  await expect(editorImage(page)).toHaveAttribute('height', '400')
  await page.getByTestId('editor-back-link').click()

  // 2. Size-only adjustment: a positive size with blank offsets saves zero
  // offsets and renders aligned. Size 20 on a 400px image scales 2x, so an
  // aligned 10x10 board is 800px wide; stretch would stay 400px.
  const sizeOnlyName = 'E2E D2c Size Only Photo'
  await uploadImageMap(page, sizeOnlyName, makeSolidPng(400, 400, 70, 110, 150), '10', '10', '20', '', '')
  const listed2 = await json<Array<{ id: string; name: string }>>(
    await request.get(`/api/rooms/${roomId}/battle-maps`),
  )
  const sizeOnlyId = listed2.find((m) => m.name === sizeOnlyName)!.id
  const sizeOnlySaved = await json<{
    grid_pixel_size: number | null
    grid_offset_x: number | null
    grid_offset_y: number | null
  }>(await request.get(`/api/rooms/${roomId}/battle-maps/${sizeOnlyId}`))
  expect(sizeOnlySaved).toMatchObject({ grid_pixel_size: 20, grid_offset_x: 0, grid_offset_y: 0 })
  await page.locator('.battle-map-card', { hasText: sizeOnlyName }).getByRole('button', { name: 'Edit Map' }).click()
  await expect(page.getByTestId('map-editor-canvas')).toBeVisible()
  await expect(editorImage(page)).toHaveAttribute('x', '0')
  await expect(editorImage(page)).toHaveAttribute('width', '800')
  await expect(editorImage(page)).toHaveAttribute('height', '800')

  // 3. Draft preview BEFORE Save: typing an offset moves the image
  // immediately, so the DM can visually align it. Saving persists the exact
  // preview, and reopening keeps it.
  await page.getByTestId('map-grid-offset-x').fill('9')
  await expect(editorImage(page)).toHaveAttribute('x', '-18')
  await expect(editorImage(page)).toHaveAttribute('width', '800')
  await page.getByTestId('map-grid-save').click()
  await expect(page.getByTestId('map-grid-save-message')).toHaveText('Grid alignment saved.')
  await expect(editorImage(page)).toHaveAttribute('x', '-18')
  await page.getByTestId('editor-back-link').click()
  await expect(page.getByRole('heading', { name: 'Map Library', level: 1 })).toBeVisible()
  await page.locator('.battle-map-card', { hasText: sizeOnlyName }).getByRole('button', { name: 'Edit Map' }).click()
  await expect(page.getByTestId('map-grid-offset-x')).toHaveValue('9')
  await expect(editorImage(page)).toHaveAttribute('x', '-18')
  await expect(editorImage(page)).toHaveAttribute('width', '800')
  await page.getByTestId('editor-back-link').click()

  // 4. Zero/negative sizes stay invalid: the grid save is disabled.
  await page.locator('.battle-map-card', { hasText: sizeOnlyName }).getByRole('button', { name: 'Edit Map' }).click()
  await expect(page.getByTestId('map-editor-canvas')).toBeVisible()
  await page.getByTestId('map-grid-size').fill('0')
  await expect(page.getByTestId('map-grid-save')).toBeDisabled()
  await page.getByTestId('map-grid-size').fill('-5')
  await expect(page.getByTestId('map-grid-save')).toBeDisabled()
})

test('M07-D D2c F13: frozen Tactical board renders the saved alignment for DM and projected Player', async ({
  browser,
  page,
  request,
  roomContext,
}) => {
  test.setTimeout(300_000)
  const { roomId } = roomContext
  // 400x300 image, grid size 20 (scale 2x): aligned board rect is
  // x=-10 (offset 5 * 2), width 800, height 600. Stretch would be 400x300.
  const mapName = 'E2E D2c Tactical Grid Photo'
  await page.goto(`/rooms/${roomId}/battle-maps`)
  await expect(page.getByRole('heading', { name: 'Map Library', level: 1 })).toBeVisible()
  await uploadImageMap(page, mapName, makeSolidPng(400, 300, 80, 100, 140), '10', '10', '20', '5', '0')
  const listed = await json<Array<{ id: string; name: string }>>(
    await request.get(`/api/rooms/${roomId}/battle-maps`),
  )
  const mapId = listed.find((m) => m.name === mapName)!.id

  const campaign = await createCampaign(request, roomId, 'D2c Grid Tactical Campaign')
  const lobby = await json<Lobby>(
    await request.get(`/api/rooms/${roomId}/campaigns/${campaign.id}/lobby`),
  )
  await addSeat(request, roomId, campaign.id, 'dm', lobby.caller_access_session_id!, 'D2c')
  const playerGrant = await enterAsMember(request, roomContext, 'D2c Watcher')
  const character = await importCharacter(request)
  await addPlayerSeat(request, roomId, campaign.id, character, playerGrant.access_session_id)
  const sessionId = await startSession(page, roomId, campaign.id)
  const prefix = `/api/rooms/${roomId}/campaigns/${campaign.id}/sessions/${sessionId}`
  const sessionUrl = `/rooms/${roomId}/campaigns/${campaign.id}/sessions/${sessionId}`

  const playerContext = await browser.newContext({ baseURL: PLAYWRIGHT_BASE_URL })
  const playerPage = await playerContext.newPage()
  try {
    await playerPage.goto('/')
    await playerPage.evaluate(
      ({ recentKey, activeKey, localeKey, room }) => {
        window.localStorage.setItem(recentKey, JSON.stringify([room]))
        window.localStorage.setItem(localeKey, 'en')
        window.sessionStorage.setItem(activeKey, room.roomId)
      },
      {
        recentKey: RECENT_ROOMS_STORAGE_KEY,
        activeKey: ACTIVE_ROOM_STORAGE_KEY,
        localeKey: LOCALE_STORAGE_KEY,
        room: {
          roomId,
          code: roomContext.code,
          name: roomContext.name,
          accessToken: playerGrant.access_token,
          authority: playerGrant.authority,
        },
      },
    )

    await page.getByTestId('tactical-start-open').click()
    await page.getByTestId(`tactical-map-${mapId}`).getByRole('radio').check()
    await page.getByTestId('tactical-start-confirm').click()
    await expect(mapPanel(page)).toBeVisible()

    // Frozen board carries the saved alignment.
    const board = await json<{
      grid_pixel_size: number | null
      grid_offset_x: number | null
      grid_offset_y: number | null
    }>(await request.get(`${prefix}/combat/board`))
    expect(board).toMatchObject({ grid_pixel_size: 20, grid_offset_x: 5, grid_offset_y: 0 })

    // DM board image rectangle matches the alignment (not stretch).
    const dmImage = mapPanel(page).getByTestId('battle-map-image')
    await expect(dmImage).toHaveAttribute('x', '-10')
    await expect(dmImage).toHaveAttribute('y', '0')
    await expect(dmImage).toHaveAttribute('width', '800')
    await expect(dmImage).toHaveAttribute('height', '600')

    // Projected Player sees the same aligned rectangle.
    await playerPage.goto(sessionUrl)
    await expect(mapPanel(playerPage)).toBeVisible()
    const playerImage = mapPanel(playerPage).getByTestId('battle-map-image')
    await expect(playerImage).toHaveAttribute('x', '-10')
    await expect(playerImage).toHaveAttribute('width', '800')
    await expect(playerImage).toHaveAttribute('height', '600')
  } finally {
    await playerContext.close()
  }
})

test('M07-D D2c F19: a drag released outside the canvas never moves the placement; drag and click-to-move still work', async ({
  page,
  request,
  roomContext,
}) => {
  test.setTimeout(180_000)
  const { roomId } = roomContext
  const mapName = 'E2E D2c Drag Outside Lair'
  await json(
    await request.post(`/api/rooms/${roomId}/battle-maps`, {
      data: { name: mapName, source_kind: 'blank', width_cells: 12, height_cells: 10 },
    }),
  )

  await page.goto(`/rooms/${roomId}/battle-maps`)
  await expect(page.getByRole('heading', { name: 'Map Library', level: 1 })).toBeVisible()
  await page.locator('.battle-map-card', { hasText: mapName }).getByRole('button', { name: 'Edit Map' }).click()
  await expect(page.getByTestId('map-editor-canvas')).toBeVisible()
  await page.getByTestId('map-editor-tool-monster').click()
  await expect(page.getByTestId('monster-placement-panel')).toBeVisible()
  const picker = page.getByTestId('monster-placement-template-picker')
  await expect.poll(async () => picker.locator('option').count(), { timeout: 15_000 }).toBeGreaterThan(1)
  const search = page.getByTestId('monster-placement-template-search')
  await search.fill('Goblin')
  await expect(picker.locator(`option[value="${GOBLIN_REF}"]`)).toHaveCount(1)
  await picker.selectOption(GOBLIN_REF)
  await page.getByTestId('map-editor-canvas').scrollIntoViewIfNeeded()
  const placedAt = await mapPoint(page, 5.5, 2.5)
  await page.mouse.click(placedAt.x, placedAt.y)
  await expect(editorTokens(page)).toHaveCount(1)
  const tokenRect = editorTokens(page).first().locator('rect')
  await expect(tokenRect).toHaveAttribute('x', String(5 * CELL_SIZE))

  // Arm a drag, release OUTSIDE the canvas, then hover back over other cells
  // with no button held: the anchor must stay where the release left it.
  // (The drag legitimately follows the pointer while armed, so the reference
  // point is the post-release anchor, not the original cell.)
  const tokenBox = await editorTokens(page).first().boundingBox()
  expect(tokenBox).not.toBeNull()
  await page.mouse.move(tokenBox!.x + tokenBox!.width / 2, tokenBox!.y + tokenBox!.height / 2)
  await page.mouse.down()
  const outsideDest = await mapPoint(page, 8.5, 2.5)
  await page.mouse.move(outsideDest.x, outsideDest.y, { steps: 5 })
  // Leave the canvas entirely before releasing (viewport corner).
  await page.mouse.move(6, 6)
  await page.mouse.up()
  const releasedX = await tokenRect.getAttribute('x')
  const releasedY = await tokenRect.getAttribute('y')
  expect(releasedX).not.toBeNull()
  // Plain hover back over cells with no button held must not move it further.
  const hoverBack = await mapPoint(page, 9.5, 5.5)
  await page.mouse.move(hoverBack.x, hoverBack.y, { steps: 5 })
  await expect(tokenRect).toHaveAttribute('x', releasedX!)
  await expect(tokenRect).toHaveAttribute('y', releasedY!)

  // Click-to-move still works: select the token, then click the destination.
  const tokenNow = await editorTokens(page).first().boundingBox()
  expect(tokenNow).not.toBeNull()
  await page.mouse.click(tokenNow!.x + tokenNow!.width / 2, tokenNow!.y + tokenNow!.height / 2)
  await expect(page.getByTestId('monster-placement-selection')).toBeVisible()
  const clickDest = await mapPoint(page, 6.5, 2.5)
  await page.mouse.click(clickDest.x, clickDest.y)
  await expect(tokenRect).toHaveAttribute('x', String(6 * CELL_SIZE))

  // Normal in-canvas drag still works.
  const dragBox = await editorTokens(page).first().boundingBox()
  expect(dragBox).not.toBeNull()
  await page.mouse.move(dragBox!.x + dragBox!.width / 2, dragBox!.y + dragBox!.height / 2)
  await page.mouse.down()
  const dragDest = await mapPoint(page, 9.5, 2.5)
  await page.mouse.move(dragDest.x, dragDest.y, { steps: 5 })
  await page.mouse.up()
  await expect(tokenRect).toHaveAttribute('x', String(9 * CELL_SIZE))

  // Persisted anchor matches the final drag.
  await page.getByTestId('monster-placement-save').click()
  await expect(page.getByTestId('monster-placement-save-message')).toHaveText(
    'Monster placements saved.',
  )
  const listed = await json<Array<{ id: string; name: string }>>(
    await request.get(`/api/rooms/${roomId}/battle-maps`),
  )
  const mapId = listed.find((m) => m.name === mapName)!.id
  const saved = await json<{ monster_placements: Array<{ anchor_x: number; anchor_y: number }> }>(
    await request.get(`/api/rooms/${roomId}/battle-maps/${mapId}`),
  )
  expect(saved.monster_placements).toHaveLength(1)
  expect(saved.monster_placements[0]).toMatchObject({ anchor_x: 9, anchor_y: 2 })
})
