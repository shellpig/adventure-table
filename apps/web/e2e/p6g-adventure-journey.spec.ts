import { expect, test } from './support/roomTest'
import {
  addPlayerSeat,
  addSeat,
  createCampaign,
  enterAsMember,
  importCharacter,
  json,
  openSessionAs,
  responseJson,
  startSession,
  type Lobby,
} from './support/quickCombat'

const ONE_PIXEL_PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Zl1sAAAAASUVORK5CYII=',
  'base64',
)

type AdventureDefinition = {
  id: string
  name: string
  status: string
  ruleset?: string
  summary?: string | null
}

type AdventureEntry = {
  id: string
  kind: string
  title: string | null
  body: string | null
  visibility: string
  assets?: Array<{ role: string; asset: { id: string; visibility: string } }>
}

type AttachedAdventure = {
  adventure_id: string
  name?: string
}

type RuntimeContext = {
  current_situation: string | null
  current_adventure_scene_entry_id: string | null
  current_runtime_scene_entry_id: string | null
  revision: number
}

test('P6-G G2a: Adventure-driven journey from definition and attach to official DM Current Scene and Stage image', async ({
  browser,
  page,
  request,
  roomContext,
}) => {
  test.setTimeout(180_000)
  const { roomId } = roomContext

  // 1. Fresh Room & Campaign with initially 0 attached Adventures
  const campaign = await createCampaign(request, roomId, 'P6-G Adventure Campaign')
  const initialAttached = await json<AttachedAdventure[]>(
    await request.get(`/api/rooms/${roomId}/campaigns/${campaign.id}/adventures`),
  )
  expect(initialAttached).toHaveLength(0)

  // 2. Create manual Adventure with public Scene, DM-only secret, DM note, and image assets
  const adventure = await json<AdventureDefinition>(
    await request.post(`/api/rooms/${roomId}/adventures`, {
      data: { name: 'P6-G Sunken Temple' },
    }),
  )
  expect(adventure.status).toBe('draft')

  const sceneEntry = await json<AdventureEntry>(
    await request.post(`/api/rooms/${roomId}/adventures/${adventure.id}/entries`, {
      data: {
        kind: 'scene',
        title: 'Sunken Temple Courtyard',
        body: 'Ancient stone archway overgrown with vines.',
        data: { kind: 'scene', read_aloud: 'Water gently laps against moss-covered stone pillars.' },
        visibility: 'public',
      },
    }),
  )

  const secretEntry = await json<AdventureEntry>(
    await request.post(`/api/rooms/${roomId}/adventures/${adventure.id}/entries`, {
      data: {
        kind: 'secret',
        title: 'Submerged Relic Vault',
        body: 'A hidden pressure plate beneath the altar opens the flooded crypt.',
        data: { kind: 'secret' },
        visibility: 'dm_only',
      },
    }),
  )

  const dmNoteEntry = await json<AdventureEntry>(
    await request.post(`/api/rooms/${roomId}/adventures/${adventure.id}/entries`, {
      data: {
        kind: 'dm_note',
        title: 'DM Tactics and Traps',
        body: 'Triggering the false floor drops players into stagnant pool.',
        data: { kind: 'dm_note' },
        visibility: 'dm_only',
      },
    }),
  )

  // Upload room-visible image asset and attach to public scene entry
  const sceneAssetUploadUrl = `/api/rooms/${roomId}/assets?kind=image&filename=sunken-temple.png&visibility=room`
  const sceneAsset = await json<{ id: string }>(
    await request.post(sceneAssetUploadUrl, {
      headers: { 'Content-Type': 'image/png' },
      data: ONE_PIXEL_PNG,
    }),
  )
  await json(
    await request.post(`/api/rooms/${roomId}/adventures/${adventure.id}/entries/${sceneEntry.id}/assets`, {
      data: {
        asset_id: sceneAsset.id,
        role: 'image',
      },
    }),
  )

  // Upload DM-only asset and attach to secret entry
  const secretAssetUploadUrl = `/api/rooms/${roomId}/assets?kind=image&filename=vault-key.png&visibility=dm_only`
  const secretAsset = await json<{ id: string }>(
    await request.post(secretAssetUploadUrl, {
      headers: { 'Content-Type': 'image/png' },
      data: ONE_PIXEL_PNG,
    }),
  )
  await json(
    await request.post(`/api/rooms/${roomId}/adventures/${adventure.id}/entries/${secretEntry.id}/assets`, {
      data: {
        asset_id: secretAsset.id,
        role: 'image',
      },
    }),
  )

  // 3. Finalize Adventure and attach to Campaign
  const finalized = await json<AdventureDefinition>(
    await request.post(`/api/rooms/${roomId}/adventures/${adventure.id}/finalize`),
  )
  expect(finalized.status).toBe('finalized')

  await json(
    await request.post(`/api/rooms/${roomId}/campaigns/${campaign.id}/adventures`, {
      data: { adventure_id: adventure.id },
    }),
  )

  // Assert Campaign attached Adventure count via API
  const attachedAdventures = await json<AttachedAdventure[]>(
    await request.get(`/api/rooms/${roomId}/campaigns/${campaign.id}/adventures`),
  )
  expect(attachedAdventures).toHaveLength(1)
  expect(attachedAdventures[0].adventure_id).toBe(adventure.id)

  // 4. Create DM Seat and Player Seat with imported Character
  const lobby = await json<Lobby>(
    await request.get(`/api/rooms/${roomId}/campaigns/${campaign.id}/lobby`),
  )
  expect(lobby.caller_access_session_id).not.toBeNull()
  await addSeat(request, roomId, campaign.id, 'dm', lobby.caller_access_session_id!, 'P6-G')

  const character = await importCharacter(request)
  const playerGrant = await enterAsMember(request, roomContext, 'P6-G Player')
  await addPlayerSeat(request, roomId, campaign.id, character, playerGrant.access_session_id, 'P6-G')

  // 5. Start Session through official UI as DM
  const sessionId = await startSession(page, roomId, campaign.id)
  const sessionUrl = `/rooms/${roomId}/campaigns/${campaign.id}/sessions/${sessionId}`

  // 6. Open Session as Player in separate browser context
  const player = await openSessionAs(browser, playerGrant, roomContext, sessionUrl)

  try {
    // DM verifies world panel is visible; Player verifies Journal is visible and world panel absent
    const worldPanel = page.locator('.session-world-panel')
    await expect(worldPanel).toBeVisible()
    await expect(player.page.locator('.session-journal-panel')).toBeVisible()
    await expect(player.page.locator('.session-world-panel')).toHaveCount(0)
    await expect(player.page.getByRole('button', { name: 'Set Stage Image' })).toHaveCount(0)
    await expect(player.page.getByRole('button', { name: 'Quick Add' })).toHaveCount(0)

    // 7. DM sets Current Scene and Current Situation through official DM UI
    const contextCard = worldPanel.locator('.runtime-context-card')
    await expect(contextCard).toBeVisible()
    await contextCard.getByRole('button', { name: 'Edit Context' }).click()

    const sceneSelect = contextCard.getByRole('combobox', { name: 'Current Scene' })
    await expect(sceneSelect).toBeVisible()
    await sceneSelect.selectOption(`adventure:${sceneEntry.id}`)
    await contextCard.getByRole('textbox', { name: 'Current Situation' })
      .fill('The party reaches the flooded courtyard of the sunken temple.')

    const contextUpdated = page.waitForResponse(
      (resp) => resp.request().method() === 'PATCH' && resp.url().endsWith(`/sessions/${sessionId}/runtime/context`),
    )
    await contextCard.getByRole('button', { name: 'Save Context' }).click()
    await responseJson(await contextUpdated)

    await expect(contextCard).toContainText('Sunken Temple Courtyard')
    await expect(contextCard).toContainText('The party reaches the flooded courtyard of the sunken temple.')

    // 8. DM sets Stage Image through official DM UI
    await worldPanel.getByRole('button', { name: 'Set Stage Image' }).click()
    const stageSelect = worldPanel.getByRole('combobox', { name: 'Select Stage image source' })
    await expect(stageSelect).toBeVisible()
    await stageSelect.selectOption({ label: 'Sunken Temple Courtyard — sunken-temple.png' })

    const stagePromise = page.waitForResponse(
      (resp) => resp.request().method() === 'PUT' && resp.url().endsWith(`/sessions/${sessionId}/stage/image-source`),
    )
    await worldPanel.getByRole('button', { name: 'Set as Stage Image' }).click()
    await responseJson(await stagePromise)

    // 9. Stage image renders to DM and Player through authenticated projection
    const dmStageImg = page.locator('.session-stage img')
    await expect(dmStageImg).toBeVisible()
    await expect(dmStageImg).toHaveAttribute('src', /^blob:/)

    const playerStageImg = player.page.locator('.session-stage img')
    await expect(playerStageImg).toBeVisible()
    await expect(playerStageImg).toHaveAttribute('src', /^blob:/)

    // Player HTML does not leak raw asset ID or direct /assets/ paths
    const playerHtml = await player.page.content()
    expect(playerHtml).not.toContain(sceneAsset.id)
    expect(playerHtml).not.toContain('/assets/')

    // 10. Assert persisted current context via API (not just UI text)
    const persistedContext = await json<RuntimeContext>(
      await request.get(`/api/rooms/${roomId}/campaigns/${campaign.id}/sessions/${sessionId}/runtime/context`),
    )
    expect(persistedContext.current_adventure_scene_entry_id).toBe(sceneEntry.id)
    expect(persistedContext.current_runtime_scene_entry_id).toBeNull()
    expect(persistedContext.current_situation).toBe(
      'The party reaches the flooded courtyard of the sunken temple.',
    )

    // 11. Verify Adventure definition baseline is NOT mutated by Runtime context
    const definitionAfter = await json<AdventureDefinition>(
      await request.get(`/api/rooms/${roomId}/adventures/${adventure.id}`),
    )
    expect(definitionAfter.id).toBe(adventure.id)
    expect(definitionAfter.name).toBe('P6-G Sunken Temple')
    expect(definitionAfter.status).toBe('finalized')

    const entriesAfter = await json<AdventureEntry[]>(
      await request.get(`/api/rooms/${roomId}/adventures/${adventure.id}/entries`),
    )
    expect(entriesAfter).toHaveLength(3)

    const sceneAfter = entriesAfter.find((e) => e.id === sceneEntry.id)!
    expect(sceneAfter.title).toBe('Sunken Temple Courtyard')
    expect(sceneAfter.body).toBe('Ancient stone archway overgrown with vines.')
    expect(sceneAfter.visibility).toBe('public')

    const secretAfter = entriesAfter.find((e) => e.id === secretEntry.id)!
    expect(secretAfter.title).toBe('Submerged Relic Vault')
    expect(secretAfter.body).toBe('A hidden pressure plate beneath the altar opens the flooded crypt.')
    expect(secretAfter.visibility).toBe('dm_only')

    const dmNoteAfter = entriesAfter.find((e) => e.id === dmNoteEntry.id)!
    expect(dmNoteAfter.title).toBe('DM Tactics and Traps')
    expect(dmNoteAfter.body).toBe('Triggering the false floor drops players into stagnant pool.')
    expect(dmNoteAfter.visibility).toBe('dm_only')

    // 12. Secrecy assertions: Player cannot direct-read Adventure entries or secret asset/DM notes
    // API direct-reads with Player token are rejected
    const playerAdvResp = await request.get(
      `/api/rooms/${roomId}/adventures/${adventure.id}`,
      { headers: { Authorization: `Bearer ${playerGrant.access_token}` } },
    )
    expect(playerAdvResp.status()).toBe(404)

    const playerEntriesResp = await request.get(
      `/api/rooms/${roomId}/adventures/${adventure.id}/entries`,
      { headers: { Authorization: `Bearer ${playerGrant.access_token}` } },
    )
    expect(playerEntriesResp.status()).toBe(404)

    const playerSecretAssetResp = await request.get(
      `/api/rooms/${roomId}/assets/${secretAsset.id}`,
      { headers: { Authorization: `Bearer ${playerGrant.access_token}` } },
    )
    expect(playerSecretAssetResp.status()).toBe(404)

    const playerSecretContentResp = await request.get(
      `/api/rooms/${roomId}/assets/${secretAsset.id}/content`,
      { headers: { Authorization: `Bearer ${playerGrant.access_token}` } },
    )
    expect(playerSecretContentResp.status()).toBe(404)

    // Player UI content contains no secret entry, secret body, DM note, or secret asset details
    expect(playerHtml).not.toContain('Submerged Relic Vault')
    expect(playerHtml).not.toContain('hidden pressure plate beneath the altar')
    expect(playerHtml).not.toContain('DM Tactics and Traps')
    expect(playerHtml).not.toContain('Triggering the false floor drops players into stagnant pool')
    expect(playerHtml).not.toContain('vault-key.png')
    expect(playerHtml).not.toContain(secretAsset.id)
  } finally {
    await player.context.close()
  }
})
