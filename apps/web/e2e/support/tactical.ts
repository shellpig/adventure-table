import { expect, type Locator, type Page } from './roomTest'

export type BoardPosition = {
  entry_id: string
  anchor_x: number
  anchor_y: number
  revision: number
  footprint_width?: number
  footprint_height?: number
}

export type Board = {
  positions: BoardPosition[]
  runtime_revision: number
}

export type MonsterInstance = {
  id: string
}

export function mapPanel(page: Page): Locator {
  return page.getByTestId('tactical-map-panel')
}

export function token(page: Page, entryId: string): Locator {
  return mapPanel(page).locator(`[data-testid="battle-map-token"][data-entry-id="${entryId}"]`)
}

export function cell(page: Page, at: { x: number; y: number }): Locator {
  return mapPanel(page).locator(
    `[data-testid="battle-map-cell"][data-cell-x="${at.x}"][data-cell-y="${at.y}"]`,
  )
}

// Callers scroll the drag origin into view first; measuring must not scroll again mid-drag.
export async function center(page: Page, locator: Locator): Promise<{ x: number; y: number }> {
  const box = await locator.boundingBox()
  expect(box).not.toBeNull()
  return { x: box!.x + box!.width / 2, y: box!.y + box!.height / 2 }
}

export async function selectMatching(select: Locator, pattern: RegExp): Promise<void> {
  // Options load asynchronously (castable spells, attacks); wait until the wanted one exists.
  await expect.poll(async () => (await select.locator('option').allTextContents()).some((text) => pattern.test(text)), {
    timeout: 10_000,
  }).toBe(true)
  const labels = await select.locator('option').allTextContents()
  const label = labels.find((text) => pattern.test(text))
  expect(label, `${pattern} in ${labels.join(' | ')}`).toBeDefined()
  await select.selectOption({ label: label! })
}

// Combatants plus a possible round wrap: advance at most one full round and a half.
export async function advanceTo(
  page: Page,
  readTurn: () => Promise<string | null>,
  entryId: string,
  maxSteps: number = 8,
): Promise<void> {
  for (let step = 0; step < maxSteps; step += 1) {
    if ((await readTurn()) === entryId) return
    const advanced = page.waitForResponse(
      (response) =>
        response.request().method() === 'POST' && response.url().includes('/combat/turn/advance'),
    )
    await page.getByRole('button', { name: 'Advance Turn' }).click()
    expect((await advanced).ok()).toBe(true)
  }
  throw new Error(`turn never reached ${entryId}`)
}

export async function cameraStyle(page: Page): Promise<string | null> {
  return mapPanel(page).getByTestId('battle-map').getAttribute('style')
}
