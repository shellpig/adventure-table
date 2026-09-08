import { expect, test, type APIRequestContext, type Page } from './support/roomTest'

const FIXTURE_ID = '00000000-0000-4000-8000-0000000000e0'

type Campaign = { id: string }
type Seat = { id: string }
type Lobby = { caller_access_session_id: string | null }

async function json<T>(response: Awaited<ReturnType<APIRequestContext['get']>>): Promise<T> {
  expect(response.ok(), await response.text()).toBe(true)
  return response.json() as Promise<T>
}

async function resetFixture(request: APIRequestContext) {
  const response = await request.patch(`/api/characters/${FIXTURE_ID}/state`, {
    data: {
      current_hp: 74,
      temporary_hp: 0,
      conditions: [],
      prepared_spell_entry_ids: ['wizard:magic-missile', 'wizard:shield', 'wizard:fireball'],
      spell_slots: {
        '1': { used: 1, remaining: 3 },
        '2': { used: 0, remaining: 3 },
        '3': { used: 1, remaining: 1 },
      },
      resources: { 'wizard:arcane-recovery': { used: 0, remaining: 1 } },
      hit_dice_state: { d10: 5, d6: 5 },
      inventory_state: [
        { entry_id: 'inventory:chain-mail', item_ref: 'srd5.1:equipment:chain-mail', quantity: 1, equipped: true, carried: true },
        { entry_id: 'inventory:shield', item_ref: 'srd5.1:equipment:shield', quantity: 1, equipped: true, carried: true },
        { entry_id: 'inventory:longsword', item_ref: 'srd5.1:equipment:longsword', quantity: 1, equipped: true, carried: true },
        { entry_id: 'inventory:healing-potion', item_ref: 'srd5.1:item:potion-of-healing-common', quantity: 2, equipped: false, carried: true },
      ],
    },
  })
  expect(response.ok(), await response.text()).toBe(true)
}

async function createCampaignWithFixture(
  request: APIRequestContext,
  roomId: string,
  name: string,
  options: { withSeats?: boolean } = {},
) {
  const campaign = await json<Campaign>(await request.post(`/api/rooms/${roomId}/campaigns`, {
    data: { name, ruleset: 'dnd5e-2014' },
  }))
  await json(await request.patch(`/api/rooms/${roomId}/campaigns/${campaign.id}/status`, {
    data: { status: 'active' },
  }))
  await json(await request.post(`/api/rooms/${roomId}/campaigns/${campaign.id}/roster`, {
    data: { character_id: FIXTURE_ID, status: 'active' },
  }))

  if (!options.withSeats) return { campaign }

  const dmSeat = await json<Seat>(await request.post(
    `/api/rooms/${roomId}/campaigns/${campaign.id}/seats`,
    { data: { role: 'dm', label: `${name} DM` } },
  ))
  const playerSeat = await json<Seat>(await request.post(
    `/api/rooms/${roomId}/campaigns/${campaign.id}/seats`,
    { data: { role: 'player', label: `${name} Player` } },
  ))
  const lobby = await json<Lobby>(await request.get(
    `/api/rooms/${roomId}/campaigns/${campaign.id}/lobby`,
  ).catch(async () => {
    await json(await request.post(`/api/rooms/${roomId}/campaigns/${campaign.id}/select`))
    return request.get(`/api/rooms/${roomId}/campaigns/${campaign.id}/lobby`)
  }))
  expect(lobby.caller_access_session_id).not.toBeNull()
  await json(await request.patch(
    `/api/rooms/${roomId}/campaigns/${campaign.id}/seats/${dmSeat.id}/controller`,
    {
      data: {
        controller_kind: 'human',
        controller_access_session_id: lobby.caller_access_session_id,
      },
    },
  ))
  await json(await request.patch(
    `/api/rooms/${roomId}/campaigns/${campaign.id}/seats/${playerSeat.id}/character`,
    { data: { selected_character_id: FIXTURE_ID } },
  ))
  return { campaign, dmSeat, playerSeat }
}

async function expectFixtureRoster(page: Page, roomId: string, campaign: Campaign, campaignName: string) {
  await page.goto(`/rooms/${roomId}/campaigns/${campaign.id}`)
  await expect(page.getByRole('heading', { name: campaignName, level: 1 })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'P0 Human Fighter 5 / Wizard 5', level: 3 })).toBeVisible()
}

async function openFixtureSheet(page: Page, roomId: string) {
  await page.goto(`/rooms/${roomId}/characters/${FIXTURE_ID}`)
  await expect(page.getByRole('heading', { name: 'P0 Human Fighter 5 / Wizard 5' })).toBeVisible()
}

test('P2-F Journey 7 shares rich Character State across two Campaign roster contexts', async ({
  page,
  request,
  roomContext,
}) => {
  await resetFixture(request)
  const alpha = await createCampaignWithFixture(request, roomContext.roomId, 'P2-F Alpha')
  const beta = await createCampaignWithFixture(request, roomContext.roomId, 'P2-F Beta')

  await expectFixtureRoster(page, roomContext.roomId, alpha.campaign, 'P2-F Alpha')
  await openFixtureSheet(page, roomContext.roomId)

  await page.getByTestId('current-hp-input').fill('61')
  await page.getByTestId('current-hp-input-save').click()
  await expect(page.getByTestId('header-hp')).toHaveText('61')

  await page.getByRole('tab', { name: /Spells/ }).click()
  const magicMissileCard = page
    .getByRole('heading', { name: 'Magic Missile' })
    .locator('xpath=ancestor::article')
  await magicMissileCard.getByRole('button', { name: 'Unprepare' }).click()
  await expect(magicMissileCard.getByText('Unprepared', { exact: true })).toBeVisible()
  await page.getByTestId('spell-slot-1-use').click()
  await expect(page.getByTestId('spell-slot-1-counter')).toHaveText('2 / 4')

  await page.getByRole('tab', { name: /Inventory/ }).click()
  await page.getByTestId('inventory-inventory:healing-potion-decrement').click()
  await expect(page.getByTestId('inventory-inventory:healing-potion-quantity')).toHaveText('1')

  await expectFixtureRoster(page, roomContext.roomId, beta.campaign, 'P2-F Beta')
  await openFixtureSheet(page, roomContext.roomId)
  await expect(page.getByTestId('header-hp')).toHaveText('61')

  await page.getByRole('tab', { name: /Spells/ }).click()
  await expect(
    page
      .getByRole('heading', { name: 'Magic Missile' })
      .locator('xpath=ancestor::article')
      .getByText('Unprepared', { exact: true }),
  ).toBeVisible()
  await expect(page.getByTestId('spell-slot-1-counter')).toHaveText('2 / 4')

  await page.getByRole('tab', { name: /Inventory/ }).click()
  await expect(page.getByTestId('inventory-inventory:healing-potion-quantity')).toHaveText('1')
})

test('P2-F Journey 8 shows a localized browser conflict for cross-Campaign active Character collision', async ({
  page,
  request,
  roomContext,
}) => {
  await resetFixture(request)
  const alpha = await createCampaignWithFixture(
    request,
    roomContext.roomId,
    'P2-F Collision Alpha',
    { withSeats: true },
  )
  const beta = await createCampaignWithFixture(
    request,
    roomContext.roomId,
    'P2-F Collision Beta',
    { withSeats: true },
  )

  await json(await request.post(`/api/rooms/${roomContext.roomId}/campaigns/${alpha.campaign.id}/select`))
  await page.goto(`/rooms/${roomContext.roomId}/campaigns/${alpha.campaign.id}/lobby`)
  await page.getByRole('button', { name: 'Start Session' }).click()
  await expect(page).toHaveURL(/\/sessions\/[0-9a-fA-F-]{36}\/?$/)
  const alphaSessionUrl = page.url()
  await expect(page.getByRole('heading', { name: 'Active Session', level: 1 })).toBeVisible()

  await json(await request.post(`/api/rooms/${roomContext.roomId}/campaigns/${beta.campaign.id}/select`))
  await page.goto(`/rooms/${roomContext.roomId}/campaigns/${beta.campaign.id}/lobby`)
  await expect(page.getByRole('button', { name: 'Start Session' })).toBeVisible()
  await page.getByRole('button', { name: 'Start Session' }).click()

  const conflict = page.locator('.error-banner')
  await expect(conflict).toHaveText(
    'At least one selected Character is already in another active Session.',
  )
  await expect(conflict).not.toContainText('409')
  await expect(conflict).not.toContainText('character_already_in_active_session')
  await expect(page).toHaveURL(new RegExp(`/campaigns/${beta.campaign.id}/lobby/?$`))

  await json(await request.post(`/api/rooms/${roomContext.roomId}/campaigns/${alpha.campaign.id}/select`))
  await page.goto(alphaSessionUrl)
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByRole('button', { name: 'End Session' }).click()
  await expect(page.getByText('Ended', { exact: true })).toBeVisible()
})
