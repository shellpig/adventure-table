import { expect, test } from './support/roomTest'
import {
  addPlayerSeat,
  addSeat,
  createCampaign,
  enterAsMember,
  importCharacter,
  json,
  openSessionAs,
  startSession,
  type Lobby,
} from './support/quickCombat'

const ONE_PIXEL_PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Zl1sAAAAASUVORK5CYII=',
  'base64',
)

test('P6-D Stage bridge and needs_review: DM sets Stage image to Player without leaking asset ID; marks needs_review without exposing to Player Journal', async ({
  page,
  browser,
  request,
  roomContext,
}) => {
  test.setTimeout(120_000)
  const { roomId } = roomContext

  // 1. Owner creates Campaign and Adventure with a scene entry
  const campaign = await createCampaign(request, roomId, 'P6-D Stage Campaign')
  const adventure = await json<{ id: string }>(await request.post(`/api/rooms/${roomId}/adventures`, {
    data: { name: 'P6-D Stage Adventure' },
  }))

  const sceneEntry = await json<{ id: string }>(await request.post(
    `/api/rooms/${roomId}/adventures/${adventure.id}/entries`,
    {
      data: {
        kind: 'scene',
        title: 'Echo Cavern',
        body: 'A cavern humming with ancient echoes.',
        data: { kind: 'scene' },
        visibility: 'public',
      },
    },
  ))

  // 2. Upload PNG asset via API and link it to the entry with role image
  const uploadUrl = `/api/rooms/${roomId}/assets?kind=image&filename=cavern.png&visibility=room`
  const asset = await json<{ id: string }>(await request.post(uploadUrl, {
    headers: { 'Content-Type': 'image/png' },
    data: ONE_PIXEL_PNG,
  }))

  await json(await request.post(
    `/api/rooms/${roomId}/adventures/${adventure.id}/entries/${sceneEntry.id}/assets`,
    {
      data: {
        asset_id: asset.id,
        role: 'image',
      },
    },
  ))

  // Finalize Adventure and attach to Campaign
  await json(await request.post(`/api/rooms/${roomId}/adventures/${adventure.id}/finalize`))
  await json(await request.post(`/api/rooms/${roomId}/campaigns/${campaign.id}/adventures`, {
    data: { adventure_id: adventure.id },
  }))

  // 3. Owner takes the DM seat; add a Player seat and character
  const lobby = await json<Lobby>(await request.get(
    `/api/rooms/${roomId}/campaigns/${campaign.id}/lobby`,
  ))
  await addSeat(request, roomId, campaign.id, 'dm', lobby.caller_access_session_id!, 'P6-D')
  const character = await importCharacter(request)
  const playerOne = await enterAsMember(request, roomContext, 'Player One')
  await addPlayerSeat(request, roomId, campaign.id, character, playerOne.access_session_id, 'P6-D')

  // 4. Start Session as DM
  const sessionId = await startSession(page, roomId, campaign.id)
  const sessionUrl = `/rooms/${roomId}/campaigns/${campaign.id}/sessions/${sessionId}`

  // 5. Open Session as Player in a separate browser context
  const player = await openSessionAs(browser, playerOne, roomContext, sessionUrl)

  try {
    // Player verifies initial state: stage is present, no DM panel, no Set Stage button, no review toggles
    await expect(player.page.locator('.session-stage')).toBeVisible()
    await expect(player.page.locator('.session-world-panel')).toHaveCount(0)
    await expect(player.page.getByRole('button', { name: 'Set Stage Image' })).toHaveCount(0)
    await expect(player.page.getByRole('button', { name: 'Mark Needs Review' })).toHaveCount(0)
    await expect(player.page.getByRole('button', { name: 'Clear Needs Review' })).toHaveCount(0)

    // DM verifies world panel is visible
    const worldPanel = page.locator('.session-world-panel')
    await expect(worldPanel).toBeVisible()

    // 6. DM opens Set Stage image -> picks Adventure entry image -> submits
    await worldPanel.getByRole('button', { name: 'Set Stage Image' }).click()
    const stageSelect = worldPanel.getByRole('combobox', { name: 'Select Stage image source' })
    await expect(stageSelect).toBeVisible()
    await stageSelect.selectOption({ label: 'Echo Cavern — cavern.png' })
    await worldPanel.getByRole('button', { name: 'Set as Stage Image' }).click()

    // 7. Assert DM page and Player page both show stage image
    await expect(page.locator('.session-stage img')).toBeVisible()
    await expect(player.page.locator('.session-stage img')).toBeVisible()

    // 8. Assert Player page HTML contains neither the raw asset id nor /assets/
    const playerHtml = await player.page.content()
    expect(playerHtml).not.toContain(asset.id)
    expect(playerHtml).not.toContain('/assets/')

    // 9. DM quick-adds a runtime entry
    await worldPanel.getByRole('button', { name: 'Quick Add' }).click()
    const quickForm = worldPanel.locator('.session-world-quick-add-form-wrapper form')
    await quickForm.getByRole('combobox', { name: 'Kind', exact: true }).selectOption('fact')
    await quickForm.getByRole('textbox', { name: 'Description / Body' }).fill('The cave walls glow softly.')
    await quickForm.getByRole('button', { name: 'Create Entry' }).click()

    // 10. DM marks the runtime entry as needs_review in the review block
    const reviewBlock = worldPanel.locator('.session-world-review')
    await expect(reviewBlock).toBeVisible()
    const markBtn = reviewBlock.getByRole('button', { name: 'Mark Needs Review' }).first()
    await markBtn.click()

    // Assert DM sees the Needs Review badge
    await expect(reviewBlock.locator('.runtime-entry__badge')).toContainText('Needs Review')

    // 11. Assert Player Journal displays the fact but shows NO needs_review badge
    const playerJournal = player.page.locator('.session-journal-panel')
    await expect(playerJournal).toBeVisible()
    await expect(playerJournal).toContainText('The cave walls glow softly.')
    await expect(playerJournal.locator('.runtime-entry__badge')).toHaveCount(0)
    await expect(playerJournal).not.toContainText('Needs Review')
  } finally {
    await player.context.close()
  }
})
