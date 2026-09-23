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

type TableEvent = {
  seq: number
  kind: string
  acting_seat_id: string | null
  subject_seat_id: string | null
  payload: Record<string, unknown>
}

type EventPage = {
  events: TableEvent[]
}

type RollRequest = {
  id: string
  target_seat_id: string
  dc: number | null
  status: 'pending' | 'resolved' | 'cancelled'
}

type RequestCheckResponse = {
  roll_group_id: string
  requests: RollRequest[]
}

type RollResult = {
  id: string
  roll_request_id: string | null
  raw_dice: number[]
  kept_dice: number[]
  base_modifier: number
  flat_adjustment: number
  total: number
}

type RollSubmission = {
  result_id: string
  roll_request_id: string | null
  hidden: boolean
  result: RollResult | null
}

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

test('P6-G G2b-1: Adventure-driven journey through narration, exploration, and formal Check', async ({
  browser,
  page,
  request,
  roomContext,
}) => {
  test.setTimeout(240_000)
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
  const playerSeat = await addPlayerSeat(
    request,
    roomId,
    campaign.id,
    character,
    playerGrant.access_session_id,
    'P6-G',
  )

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

    // 13. DM posts narration grounded in the selected Scene
    const NARRATION_TEXT =
      'Murky water sloshes around your boots as the crumbling pillars cast long shadows across the sunken courtyard.'
    await page.getByRole('combobox', { name: 'Type', exact: true }).selectOption('narration')
    await page.getByPlaceholder(/Type here/).fill(NARRATION_TEXT)
    const narrationPromise = page.waitForResponse(
      (resp) => resp.request().method() === 'POST' && resp.url().includes(`/sessions/${sessionId}/exploration`),
    )
    await page.getByRole('button', { name: 'Send' }).click()
    await responseJson(await narrationPromise)

    await expect(page.getByText(NARRATION_TEXT, { exact: true })).toBeVisible()
    await expect(player.page.getByText(NARRATION_TEXT, { exact: true })).toBeVisible()

    // 14. Player posts an exploration action
    const ACTION_TEXT = 'I search the submerged stone pillars for ancient inscriptions or hidden mechanisms.'
    await player.page.getByRole('combobox', { name: 'Type', exact: true }).selectOption('action')
    await player.page.getByRole('combobox', { name: 'Character', exact: true }).selectOption(playerSeat.id)
    await player.page.getByPlaceholder(/Type here/).fill(ACTION_TEXT)
    const actionPromise = player.page.waitForResponse(
      (resp) => resp.request().method() === 'POST' && resp.url().includes(`/sessions/${sessionId}/exploration`),
    )
    await player.page.getByRole('button', { name: 'Send' }).click()
    await responseJson(await actionPromise)

    await expect(page.getByText(ACTION_TEXT, { exact: true })).toBeVisible()
    await expect(player.page.getByText(ACTION_TEXT, { exact: true })).toBeVisible()

    // 15. DM requests a formal Check
    await page.getByRole('button', { name: 'Dice', exact: true }).click()
    const targetCheckbox = page.getByRole('checkbox', { name: new RegExp(character.name) })
    await expect(targetCheckbox).toBeChecked()
    await page.getByRole('combobox', { name: 'Check type' }).selectOption('skill')
    await page.getByRole('combobox', { name: 'Skill' }).selectOption('srd5.1:skill:investigation')
    await page.getByLabel('DC (optional)', { exact: true }).fill('14')
    await page.getByRole('combobox', { name: 'Roll mode' }).selectOption('normal')
    await page.getByRole('combobox', { name: 'Result visibility' }).selectOption('public')
    await page.getByLabel('Label', { exact: true }).fill('Inspect courtyard carvings')

    const checkPromise = page.waitForResponse(
      (resp) => resp.request().method() === 'POST' && resp.url().includes(`/sessions/${sessionId}/checks`),
    )
    await page.getByRole('button', { name: 'Create Check' }).click()
    const checkResponse = await responseJson<RequestCheckResponse>(await checkPromise)
    expect(checkResponse.requests).toHaveLength(1)
    const rollRequestId = checkResponse.requests[0].id
    expect(checkResponse.requests[0]).toMatchObject({
      target_seat_id: playerSeat.id,
      dc: 14,
      status: 'pending',
    })

    const rollPrompt = `The DM asks ${character.name} to make Investigation (Skill Check): Inspect courtyard carvings.`
    await expect(player.page.getByText(rollPrompt, { exact: true })).toBeVisible()

    // DM sees pending request with DC 14
    const dmRequestCard = page.locator('.session-roll-request').first()
    await expect(dmRequestCard).toHaveAttribute('data-roll-request-status', 'pending')
    await expect(dmRequestCard.getByText('DC 14', { exact: true })).toBeVisible()

    // 16. Player rolls formally, and both sides see authorized results
    await player.page.getByRole('button', { name: 'Dice', exact: true }).click()
    const playerRequestCard = player.page.locator('.session-roll-request').first()
    await expect(playerRequestCard).toHaveAttribute('data-roll-request-status', 'pending')
    await expect(playerRequestCard.getByText('Waiting to roll', { exact: true })).toBeVisible()
    // Player does NOT see DC 14 (secrecy)
    await expect(playerRequestCard.getByText('DC 14', { exact: true })).toHaveCount(0)

    const rollPromise = player.page.waitForResponse(
      (resp) => resp.request().method() === 'POST' && resp.url().includes(`/sessions/${sessionId}/rolls/formal`),
    )
    await playerRequestCard.getByRole('button', { name: 'Roll formally' }).click()
    const rollSubmission = await responseJson<RollSubmission>(await rollPromise)
    expect(rollSubmission.roll_request_id).toBe(rollRequestId)
    expect(rollSubmission.result).not.toBeNull()
    expect(rollSubmission.result!.raw_dice).toHaveLength(1)
    expect(rollSubmission.result!.raw_dice[0]).toBeGreaterThanOrEqual(1)
    expect(rollSubmission.result!.raw_dice[0]).toBeLessThanOrEqual(20)

    // Both sides see resolved status and total
    await expect(playerRequestCard).toHaveAttribute('data-roll-request-status', 'resolved')
    await expect(dmRequestCard).toHaveAttribute('data-roll-request-status', 'resolved')
    await expect(playerRequestCard.getByText(`Total: ${rollSubmission.result!.total}`, { exact: true })).toBeVisible()
    await expect(dmRequestCard.getByText(`Total: ${rollSubmission.result!.total}`, { exact: true })).toBeVisible()
    await expect(dmRequestCard.getByText('DC 14', { exact: true })).toBeVisible()
    await expect(playerRequestCard.getByText('DC 14', { exact: true })).toHaveCount(0)

    // 17. Assert actual persisted AT events & result via API
    const eventPage = await json<EventPage>(
      await request.get(`/api/rooms/${roomId}/campaigns/${campaign.id}/sessions/${sessionId}/events?after=0&limit=100`),
    )
    const eventKinds = eventPage.events.map((e) => e.kind)
    expect(eventKinds).toContain('exploration.narration')
    expect(eventKinds).toContain('exploration.action')
    expect(eventKinds).toContain('roll.requested')
    expect(eventKinds).toContain('roll.resolved')

    const narrationEvent = eventPage.events.find((e) => e.kind === 'exploration.narration')!
    expect(narrationEvent.payload.text).toBe(NARRATION_TEXT)

    const actionEvent = eventPage.events.find((e) => e.kind === 'exploration.action')!
    expect(actionEvent.payload.text).toBe(ACTION_TEXT)
    const speakerSeat = actionEvent.acting_seat_id ?? actionEvent.subject_seat_id
    expect(speakerSeat).toBe(playerSeat.id)

    const rollRequestedEvent = eventPage.events.find((e) => e.kind === 'roll.requested')!
    expect(rollRequestedEvent.payload.request_type).toBe('skill')
    expect(rollRequestedEvent.payload.skill_ref).toBe('srd5.1:skill:investigation')
    expect(rollRequestedEvent.payload.label).toBe('Inspect courtyard carvings')
    // DC is secret-bearing and intentionally omitted from the public event payload
    expect(rollRequestedEvent.payload.dc).toBeUndefined()

    const rollResolvedEvent = eventPage.events.find((e) => e.kind === 'roll.resolved')!
    expect(rollResolvedEvent.payload.roll_request_id).toBe(rollRequestId)
    expect(rollResolvedEvent.payload.total).toBe(rollSubmission.result!.total)

    // 18. Stage image remains visible for both DM and Player
    await expect(dmStageImg).toBeVisible()
    await expect(dmStageImg).toHaveAttribute('src', /^blob:/)
    await expect(playerStageImg).toBeVisible()
    await expect(playerStageImg).toHaveAttribute('src', /^blob:/)

    // 19. Player still cannot directly read Adventure/secret/DM Note while Stage remains visible
    const playerAdvResp2 = await request.get(
      `/api/rooms/${roomId}/adventures/${adventure.id}`,
      { headers: { Authorization: `Bearer ${playerGrant.access_token}` } },
    )
    expect(playerAdvResp2.status()).toBe(404)

    const playerHtmlAfter = await player.page.content()
    expect(playerHtmlAfter).not.toContain('Submerged Relic Vault')
    expect(playerHtmlAfter).not.toContain('hidden pressure plate beneath the altar')
    expect(playerHtmlAfter).not.toContain('DM Tactics and Traps')
    expect(playerHtmlAfter).not.toContain('Triggering the false floor drops players into stagnant pool')
    expect(playerHtmlAfter).not.toContain('vault-key.png')
    expect(playerHtmlAfter).not.toContain(secretAsset.id)
    expect(playerHtmlAfter).not.toContain('/assets/')
  } finally {
    await player.context.close()
  }
})
