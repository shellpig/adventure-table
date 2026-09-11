import { expect, test, type Page } from './support/roomTest'

// Journey 4 (Campaign / Roster) and the pre-Session half of Journey 5 (Lobby /
// Seats) from docs/P2/測試指南.md §13. Session Start / End belong to P2-E and
// are deliberately absent here.
//
// The shared baseline Room already owns the seeded P0 fixture Character, so the
// roster step does not have to walk the whole Builder.

async function createCampaign(page: Page, roomId: string, name: string) {
  await page.goto(`/rooms/${roomId}/campaigns`)
  await expect(page.getByRole('heading', { name: 'Campaigns', level: 1 })).toBeVisible()
  await page.getByLabel('Campaign name').fill(name)
  await page.getByRole('button', { name: 'Create Campaign' }).click()

  const card = page.locator('article').filter({ has: page.getByRole('heading', { name, exact: true }) })
  await expect(card).toBeVisible()
  await card.getByRole('link', { name: 'Open Campaign' }).click()
  await expect(page.getByRole('heading', { name, level: 1 })).toBeVisible()
}

test('P2-D Owner drives Campaign, Roster and Lobby seats against the real backend', async ({ page, roomContext }) => {
  await createCampaign(page, roomContext.roomId, 'P2-D Lobby Journey')

  // Journey 4 — make it the Room's current active Campaign and put a Room
  // Character on the Party Roster.
  await page.getByRole('button', { name: 'Start Campaign', exact: true }).click()
  await expect(page.getByText('Status: Active')).toBeVisible()
  await page.getByRole('button', { name: 'Select Campaign' }).click()
  await expect(page.getByRole('link', { name: 'Open Lobby' })).toBeVisible()

  const rosterCharacterId = await page.getByLabel('Add Character').inputValue()
  expect(rosterCharacterId).not.toBe('')
  const rosterName = await page
    .getByLabel('Add Character')
    .locator(`option[value="${rosterCharacterId}"]`)
    .innerText()
  const characterName = rosterName.split(' · ')[0]

  await page.getByRole('button', { name: 'Add to Roster' }).click()
  await expect(page.getByRole('heading', { name: characterName, level: 3 })).toBeVisible()

  // Journey 5, pre-Session half — Lobby seats, controller assignment and the
  // one-Character-per-Seat selection.
  await page.getByRole('link', { name: 'Open Lobby' }).click()
  await expect(page).toHaveURL(/\/campaigns\/[0-9a-fA-F-]{36}\/lobby\/?$/)
  await expect(page.getByRole('heading', { name: 'Lobby & Seats', level: 1 })).toBeVisible()
  await expect(page.getByText('No seats yet.')).toBeVisible()

  await page.getByLabel('Seat label').fill('Front Line')
  await page.getByRole('button', { name: 'Add seat' }).click()
  const playerSeat = page.locator('article').filter({ has: page.getByRole('heading', { name: 'Front Line' }) })
  await expect(playerSeat.getByText('Role: Player')).toBeVisible()

  // Owner-only DM Seat. The role option is offered because this browser holds
  // the Owner grant.
  await page.getByLabel('Role').selectOption('dm')
  await page.getByLabel('Seat label').fill('Dungeon Master')
  await page.getByRole('button', { name: 'Add seat' }).click()
  const dmSeat = page.locator('article').filter({ has: page.getByRole('heading', { name: 'Dungeon Master' }) })
  await expect(dmSeat.getByText('Role: DM')).toBeVisible()

  // A DM Seat never offers an Active Character selector.
  await expect(dmSeat.getByLabel('Active character')).toHaveCount(0)

  // Owner assigns itself to the DM Seat; presence comes from the P2-A heartbeat
  // the Lobby page keeps sending, not from a second presence substrate.
  const dmController = dmSeat.getByLabel('Controller')
  const controllerValue = await dmController.locator('option').nth(1).getAttribute('value')
  await dmController.selectOption(controllerValue!)
  // Scoped to the summary line: the controller <option> text carries the same
  // presence word, so a bare getByText would match twice.
  await expect(dmSeat.locator('p').filter({ hasText: /^Controller: / })).toContainText('Connected')

  // Player Seat picks the rostered Character.
  await playerSeat.getByLabel('Active character').selectOption(rosterCharacterId)
  await expect(playerSeat.getByLabel('Active character')).toHaveValue(rosterCharacterId)

  // Archiving the Seat releases the Character so a new Seat can take it.
  await playerSeat.getByRole('button', { name: 'Archive seat' }).click()
  await expect(page.getByRole('heading', { name: 'Front Line' })).toHaveCount(0)

  await page.getByLabel('Role').selectOption('player')
  await page.getByLabel('Seat label').fill('Second Line')
  await page.getByRole('button', { name: 'Add seat' }).click()
  const replacement = page.locator('article').filter({ has: page.getByRole('heading', { name: 'Second Line' }) })
  await replacement.getByLabel('Active character').selectOption(rosterCharacterId)
  await expect(replacement.getByLabel('Active character')).toHaveValue(rosterCharacterId)

  // Seats with no Session history can be removed outright.
  page.once('dialog', (dialog) => dialog.accept())
  await replacement.getByRole('button', { name: 'Delete seat' }).click()
  await expect(page.getByRole('heading', { name: 'Second Line' })).toHaveCount(0)
})

test('P2-D Lobby is reachable only while the Campaign is the Room current active Campaign', async ({ page, roomContext }) => {
  await createCampaign(page, roomContext.roomId, 'P2-D Displaced Campaign')

  // A draft Campaign offers no Lobby entry at all.
  await expect(page.getByRole('link', { name: 'Open Lobby' })).toHaveCount(0)

  // Active status alone is still not enough.
  await page.getByRole('button', { name: 'Start Campaign', exact: true }).click()
  await expect(page.getByText('Status: Active')).toBeVisible()
  await expect(page.getByRole('link', { name: 'Open Lobby' })).toHaveCount(0)

  await page.getByRole('button', { name: 'Select Campaign' }).click()
  const lobbyLink = page.getByRole('link', { name: 'Open Lobby' })
  await expect(lobbyLink).toBeVisible()
  const lobbyUrl = new URL(await lobbyLink.getAttribute('href') ?? '', page.url()).pathname

  // Dropping the Room selection must close the Lobby door on the server, not
  // only hide the button.
  await page.getByRole('button', { name: 'Clear selection' }).click()
  await expect(page.getByRole('link', { name: 'Open Lobby' })).toHaveCount(0)

  const refused = page.waitForResponse(
    (response) => response.url().includes('/lobby') && response.status() === 409,
  )
  await page.goto(lobbyUrl)
  await refused
  await expect(page.getByRole('heading', { name: 'Lobby & Seats', level: 1 })).toBeVisible()
  await expect(page.locator('.error-banner')).toBeVisible()
})
