import { expect, test, type APIRequestContext, type Page } from './support/roomTest'

type Campaign = { id: string }
type CharacterSummary = { id: string; name: string }
type Seat = { id: string }
type Lobby = { caller_access_session_id: string | null }

async function json<T>(response: Awaited<ReturnType<APIRequestContext['get']>>): Promise<T> {
  expect(response.ok(), await response.text()).toBe(true)
  return response.json() as Promise<T>
}

async function createSessionReadyCampaign(
  request: APIRequestContext,
  roomId: string,
  name: string,
  options: { selectPlayerCharacter: boolean },
) {
  const characters = await json<CharacterSummary[]>(await request.get('/api/characters'))
  expect(characters.length).toBeGreaterThan(0)
  const character = characters[0]

  const campaign = await json<Campaign>(await request.post(`/api/rooms/${roomId}/campaigns`, {
    data: { name, ruleset: 'dnd5e-2014' },
  }))
  await json(await request.patch(`/api/rooms/${roomId}/campaigns/${campaign.id}/status`, {
    data: { status: 'active' },
  }))
  await json(await request.post(`/api/rooms/${roomId}/campaigns/${campaign.id}/select`))
  await json(await request.post(`/api/rooms/${roomId}/campaigns/${campaign.id}/roster`, {
    data: { character_id: character.id, status: 'active' },
  }))

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
  ))
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

  if (options.selectPlayerCharacter) {
    await json(await request.patch(
      `/api/rooms/${roomId}/campaigns/${campaign.id}/seats/${playerSeat.id}/character`,
      { data: { selected_character_id: character.id } },
    ))
  }

  return { campaign, character, playerSeat }
}

async function startFromLobby(page: Page, roomId: string, campaignId: string) {
  await page.goto(`/rooms/${roomId}/campaigns/${campaignId}/lobby`)
  await expect(page.getByRole('heading', { name: 'Lobby & Seats', level: 1 })).toBeVisible()
  await page.getByRole('button', { name: 'Start Session' }).click()
  await expect(page).toHaveURL(
    new RegExp(`/rooms/${roomId}/campaigns/${campaignId}/sessions/[0-9a-fA-F-]{36}/?$`),
  )
  await expect(page.getByRole('heading', { name: 'Active Session', level: 1 })).toBeVisible()
}

async function endFromSession(page: Page) {
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByRole('button', { name: 'End Session' }).click()
  await expect(page.getByText('Ended', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'End Session' })).toHaveCount(0)
}

test('P2-F Journey 5 starts and ends a real Session from the browser', async ({
  page,
  request,
  roomContext,
}) => {
  const setup = await createSessionReadyCampaign(
    request,
    roomContext.roomId,
    'P2-F Start End',
    { selectPlayerCharacter: true },
  )

  await startFromLobby(page, roomContext.roomId, setup.campaign.id)

  const participant = page.locator('article').filter({
    has: page.getByRole('heading', { name: 'P2-F Start End Player', exact: true }),
  })
  await expect(participant).toContainText(setup.character.name)

  await endFromSession(page)
  await page.getByRole('link', { name: 'Back to Lobby' }).click()
  await expect(page.getByRole('button', { name: 'Start Session' })).toBeVisible()
})

test('P2-F Journey 6 selects a Character after Start and Late Joins through the browser', async ({
  page,
  request,
  roomContext,
}) => {
  const setup = await createSessionReadyCampaign(
    request,
    roomContext.roomId,
    'P2-F Late Join',
    { selectPlayerCharacter: false },
  )

  await startFromLobby(page, roomContext.roomId, setup.campaign.id)
  await page.getByRole('link', { name: 'Back to Lobby' }).click()

  const playerSeat = page.locator('article').filter({
    has: page.getByRole('heading', { name: 'P2-F Late Join Player', exact: true }),
  })
  await playerSeat.getByLabel('Active character').selectOption(setup.character.id)
  await expect(playerSeat.getByLabel('Active character')).toHaveValue(setup.character.id)

  await page.getByRole('link', { name: 'Resume Session' }).click()
  await expect(page.getByRole('heading', { name: 'Late Join', level: 2 })).toBeVisible()
  await page.getByLabel('Choose Player Seat').selectOption(setup.playerSeat.id)
  await page.getByRole('button', { name: 'Join Session' }).click()

  const participant = page.locator('article').filter({
    has: page.getByRole('heading', { name: 'P2-F Late Join Player', exact: true }),
  })
  await expect(participant).toContainText(setup.character.name)
  await expect(page.getByText('No Player Seat is currently eligible to join.')).toBeVisible()

  await endFromSession(page)
})
