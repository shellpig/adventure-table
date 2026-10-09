import { expect, test, type Page } from './support/roomTest'
import { addSeat, createCampaign, json, startSession, type Lobby } from './support/quickCombat'

type SavedMap = {
  id: string
  revision: number
  walls: Array<{ id: string; x1: number; y1: number; x2: number; y2: number }>
  doors: Array<{ id: string; x1: number; y1: number; x2: number; y2: number }>
  drawings: Array<{ id: string; payload: Record<string, unknown> }>
}

const CELL_SIZE = 40

const editorCanvas = (page: Page) => page.getByTestId('map-editor-canvas')

/** Viewport point of a map coordinate (in cells), through the editor SVG's screen CTM. */
async function mapPoint(page: Page, x: number, y: number) {
  return editorCanvas(page)
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

test.use({ actionTimeout: 15_000 })

test('P5-G map editor saves new walls, doors and pen-styled drawings', async ({ page, request, roomContext }) => {
  test.setTimeout(120_000)
  const campaign = await createCampaign(request, roomContext.roomId, 'P5-G Map Editor Save')
  const lobby = await json<Lobby>(await request.get(
    `/api/rooms/${roomContext.roomId}/campaigns/${campaign.id}/lobby`,
  ))
  await addSeat(request, roomContext.roomId, campaign.id, 'dm', lobby.caller_access_session_id!, 'P5-G')

  // A map that already has a saved wall: its id must survive editor saves.
  const mapsUrl = `/api/rooms/${roomContext.roomId}/battle-maps`
  const created = await json<SavedMap>(await request.post(mapsUrl, {
    data: { name: 'P5-G Editor Save', source_kind: 'blank', width_cells: 10, height_cells: 8 },
  }))
  const seeded = await json<SavedMap>(await request.put(`${mapsUrl}/${created.id}/objects`, {
    data: {
      expected_revision: created.revision,
      walls: [{ x1: 0, y1: 1, x2: 3, y2: 1, visibility: 'public' }],
    },
  }))
  const seededWallId = seeded.walls[0].id
  const readMap = async () => json<SavedMap>(await request.get(`${mapsUrl}/${created.id}`))

  await startSession(page, roomContext.roomId, campaign.id)
  await page.getByTestId('tactical-start-open').click()
  await page.getByTestId(`tactical-edit-map-${created.id}`).click()
  await expect(editorCanvas(page)).toBeVisible()
  await editorCanvas(page).scrollIntoViewIfNeeded()

  // Drag handle: pulling it down makes the editing area taller.
  const heightBefore = (await editorCanvas(page).boundingBox())!.height
  await page.getByTestId('map-editor-resize-handle').scrollIntoViewIfNeeded()
  const handle = (await page.getByTestId('map-editor-resize-handle').boundingBox())!
  await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2)
  await page.mouse.down()
  await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2 + 120, { steps: 4 })
  await page.mouse.up()
  await expect.poll(async () => (await editorCanvas(page).boundingBox())!.height).toBeGreaterThan(heightBefore + 100)
  await editorCanvas(page).scrollIntoViewIfNeeded()

  // Pen: red, width 8, one freehand stroke.
  await page.getByTestId('map-editor-tool-draw').click()
  await page.getByTestId('map-editor-color-red').click()
  await expect(page.getByTestId('map-editor-color-red')).toHaveAttribute('aria-pressed', 'true')
  await page.getByTestId('map-editor-pen-width').fill('8')
  const strokeStart = await mapPoint(page, 2, 3)
  const strokeEnd = await mapPoint(page, 5, 5)
  await page.mouse.move(strokeStart.x, strokeStart.y)
  await page.mouse.down()
  await page.mouse.move(strokeEnd.x, strokeEnd.y, { steps: 10 })
  await page.mouse.up()
  await expect(editorCanvas(page).getByTestId('battle-map-drawing')).toHaveAttribute('stroke', '#e05252')

  // Single clicks next to a grid edge place a one-cell wall and door.
  await page.getByTestId('map-editor-tool-wall').click()
  // Leaving the pen tool removes its picker row and shifts the canvas; bring
  // the canvas back into view before clicking grid edges.
  await editorCanvas(page).scrollIntoViewIfNeeded()
  const wallAt = await mapPoint(page, 6.5, 4.05)
  await page.mouse.click(wallAt.x, wallAt.y)
  await page.getByTestId('map-editor-tool-door').click()
  const doorAt = await mapPoint(page, 8.5, 4.05)
  await page.mouse.click(doorAt.x, doorAt.y)
  await expect(editorCanvas(page).getByTestId('battle-map-wall')).toHaveCount(2)
  await expect(editorCanvas(page).getByTestId('battle-map-door')).toHaveCount(1)

  const save = async () => {
    const saved = page.waitForResponse((response) => (
      response.request().method() === 'PUT' && response.url().endsWith(`/battle-maps/${created.id}/objects`)
    ))
    await page.getByTestId('map-editor-save').click()
    expect((await saved).status()).toBe(200)
    await expect(page.getByTestId('map-editor-save-message')).toHaveText('Saved')
  }

  await save()
  const first = await readMap()
  expect(first.walls).toHaveLength(2)
  expect(first.walls.map((wall) => wall.id)).toContain(seededWallId)
  expect(first.walls).toContainEqual(expect.objectContaining({ x1: 6, y1: 4, x2: 7, y2: 4 }))
  expect(first.doors).toEqual([expect.objectContaining({ x1: 8, y1: 4, x2: 9, y2: 4 })])
  expect(first.drawings).toHaveLength(1)
  expect(first.drawings[0].payload).toEqual(expect.objectContaining({
    kind: 'freehand',
    color: '#e05252',
    width: 8,
  }))

  // Saving again keeps every id the server assigned.
  await save()
  const second = await readMap()
  expect(second.walls.map((wall) => wall.id).sort()).toEqual(first.walls.map((wall) => wall.id).sort())
  expect(second.doors.map((door) => door.id)).toEqual(first.doors.map((door) => door.id))
  expect(second.drawings.map((drawing) => drawing.id)).toEqual(first.drawings.map((drawing) => drawing.id))

  // Reopening after a reload shows what was saved, in the pen's colour and width.
  await page.reload()
  await page.getByTestId('tactical-start-open').click()
  await page.getByTestId(`tactical-edit-map-${created.id}`).click()
  const drawing = editorCanvas(page).getByTestId('battle-map-drawing')
  await expect(drawing).toHaveAttribute('data-drawing-id', first.drawings[0].id)
  await expect(drawing).toHaveAttribute('stroke', '#e05252')
  await expect(drawing).toHaveAttribute('stroke-width', '8')
  await expect(editorCanvas(page).getByTestId('battle-map-wall')).toHaveCount(2)
  await expect(editorCanvas(page).getByTestId('battle-map-door')).toHaveCount(1)
})
