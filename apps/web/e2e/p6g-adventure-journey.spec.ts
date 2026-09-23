import { expect, test } from './support/roomTest'
import {
  addPlayerSeat,
  addQuickEnemy,
  addSeat,
  advanceUntilTurn,
  combatantCard,
  combatantOf,
  combatStage,
  createCampaign,
  endCombat,
  enterAsMember,
  entryNamed,
  importCharacter,
  initiativeRow,
  json,
  openSessionAs,
  playerAttack,
  readDetail,
  responseJson,
  startSession,
  type AttackResolution,
  type CombatDetail,
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

type CampaignAdventureOverride = {
  id: string
  campaign_id: string
  adventure_entry_id: string
  state_json: Record<string, unknown>
  note: string | null
  needs_review: boolean
  revision: number
  created_at: string
  updated_at: string
}

type RuntimeEntry = {
  id: string
  kind: string
  title: string | null
  body: string | null
  visibility: string
  dm_notes?: string | null
  revision: number
  [key: string]: unknown
}

type SessionHistoryLink = {
  session_id: string
  previous_session: { id: string; status: string } | null
  previous_last_event_seq: number
}

type MonsterInstance = {
  id: string
  name: string
  current_hp: number | null
  max_hp: number | null
}

test('P6-G G2b-3: Adventure-driven journey through exploration, combat, write-back, and next Session continuity', async ({
  browser,
  page,
  request,
  roomContext,
}) => {
  test.setTimeout(300_000)
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
  const activePrefix = `/api/rooms/${roomId}/campaigns/${campaign.id}/sessions/${sessionId}`

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

    // 20. Quick Combat: DM starts combat in Adventure session with Stage visible; Player lacks start button
    await expect(player.page.getByRole('button', { name: 'Start Combat' })).toHaveCount(0)
    await page.getByRole('button', { name: 'Start Combat' }).click()
    await expect(combatStage(page)).toBeVisible()
    await expect(combatStage(player.page)).toBeVisible()

    let detail = await readDetail(request, activePrefix)
    expect(detail.status).toBe('initiative_pending')
    const heroEntry = entryNamed(detail, character.name)
    expect(heroEntry.character_id).toBe(character.id)
    await expect(initiativeRow(page, heroEntry.id)).toContainText(character.name)
    await expect(initiativeRow(player.page, heroEntry.id)).toContainText(character.name)

    // 21. Stage image remains visible during Combat; Zero Tactical geometry/map
    await expect(dmStageImg).toBeVisible()
    await expect(dmStageImg).toHaveAttribute('src', /^blob:/)
    await expect(playerStageImg).toBeVisible()
    await expect(playerStageImg).toHaveAttribute('src', /^blob:/)
    await expect(page.locator('.tactical-grid, .battle-map, [data-tactical-map]')).toHaveCount(0)
    await expect(player.page.locator('.tactical-grid, .battle-map, [data-tactical-map]')).toHaveCount(0)

    // 22. Add legal Quick Enemy: Player lacks enemy controls; DM specifies AC 1 for deterministic attack
    await expect(player.page.getByRole('button', { name: 'Quick Enemy' })).toHaveCount(0)
    await expect(player.page.getByRole('button', { name: 'Add to Combat' })).toHaveCount(0)
    await expect(player.page.getByRole('combobox', { name: 'Choose Monster' })).toHaveCount(0)

    const QUICK_ENEMY = {
      name: 'Sunken Temple Guardian',
      ac: 1,
      maxHp: 30,
      positionNote: 'Submerged near the broken altar',
    }
    await addQuickEnemy(page, QUICK_ENEMY)

    await expect(page.locator('.session-combat__initiative-row', { hasText: QUICK_ENEMY.name })).toBeVisible()
    await expect(player.page.locator('.session-combat__initiative-row', { hasText: QUICK_ENEMY.name })).toBeVisible()

    detail = await readDetail(request, activePrefix)
    expect(detail.entries).toHaveLength(2)
    const enemyEntry = entryNamed(detail, QUICK_ENEMY.name)
    expect(combatantOf(detail, enemyEntry.id).projection.armor_class).toBe(QUICK_ENEMY.ac)
    await expect(combatantCard(page, enemyEntry.id)).toContainText(`Position Note:${QUICK_ENEMY.positionNote}`)

    // 23. Initiative: DM requests, Player rolls own initiative, DM rolls enemy, DM finalizes
    await expect(player.page.getByRole('button', { name: 'Request Initiative' })).toHaveCount(0)
    await expect(player.page.getByRole('button', { name: 'Finalize Initiative' })).toHaveCount(0)

    await page.getByRole('button', { name: 'Request Initiative' }).click()
    const playerInitiativeButton = initiativeRow(player.page, heroEntry.id).getByRole('button', {
      name: 'Roll Initiative',
    })
    await expect(playerInitiativeButton).toBeVisible()
    await expect(initiativeRow(player.page, enemyEntry.id).getByRole('button')).toHaveCount(0)
    await playerInitiativeButton.click()
    await expect(initiativeRow(player.page, heroEntry.id).locator('.session-combat__initiative-total')).toBeVisible()

    await initiativeRow(page, enemyEntry.id).getByRole('button', { name: 'Roll Initiative' }).click()
    await expect(initiativeRow(page, enemyEntry.id).locator('.session-combat__initiative-total')).toBeVisible()

    await page.getByRole('button', { name: 'Finalize Initiative' }).click()
    await expect(combatStage(page).locator('.session-combat__round-badge')).toHaveText('Round 1')
    await expect(combatStage(player.page).locator('.session-combat__round-badge')).toHaveText('Round 1')
    detail = await readDetail(request, activePrefix)
    expect(detail.status).toBe('running')

    // 24. Enemy secrecy: Player sees no exact HP/AC in UI or API; DM sees full projection
    await expect(combatantCard(player.page, enemyEntry.id)).toHaveAttribute('data-hostile', 'true')
    await expect(combatantCard(player.page, enemyEntry.id)).not.toContainText('HP:')
    await expect(combatantCard(player.page, enemyEntry.id)).not.toContainText('AC:')
    await expect(combatantCard(page, enemyEntry.id)).toContainText('HP:')
    await expect(combatantCard(page, enemyEntry.id)).toContainText('AC:')

    const playerCombatDetail = await json<CombatDetail>(
      await request.get(`${activePrefix}/combat/detail`, {
        headers: { Authorization: `Bearer ${playerGrant.access_token}` },
      }),
    )
    const playerEnemyCombatant = combatantOf(playerCombatDetail, enemyEntry.id)
    expect(playerEnemyCombatant.projection.current_hp ?? null).toBeNull()
    expect(playerEnemyCombatant.projection.armor_class ?? null).toBeNull()

    // 25. Resolve attack causing actual HP damage via official playerAttack helper
    const MAX_ATTACK_ROUNDS = 6
    let resolution: AttackResolution | null = null
    for (let round = 0; round < MAX_ATTACK_ROUNDS && !resolution?.hit; round += 1) {
      await advanceUntilTurn(page, request, activePrefix, heroEntry.id)
      await expect(combatStage(player.page).locator('.session-combat__your-turn-badge')).toBeVisible()
      resolution = await playerAttack(page, player.page, sessionId, QUICK_ENEMY.name)
    }
    expect(resolution?.hit, 'attack should hit guardian with AC 1').toBe(true)
    const hit = resolution!
    expect(hit.damage_total).toBeGreaterThan(0)
    expect(hit.after_hp ?? null).toBeNull()

    await expect(player.page.locator('[data-attack-result="true"]')).toContainText(`Damage ${hit.damage_total}`)
    await expect(player.page.locator('[data-attack-result="true"]')).not.toContainText('HP:')

    // 26. Assert Player cannot access DM-only adjudication
    await expect(player.page.locator('[data-adjudication-id]')).toHaveCount(0)
    const rejectedAdjudicate = await request.post(`${activePrefix}/combat/attacks/adjudicate`, {
      headers: { Authorization: `Bearer ${playerGrant.access_token}` },
      data: {
        action_id: '00000000-0000-0000-0000-000000000001',
        in_range: true,
      },
    })
    expect(rejectedAdjudicate.status()).toBe(403)

    const rejectedResolve = await request.post(
      `${activePrefix}/combat/adjudications/00000000-0000-0000-0000-000000000001/resolve`,
      {
        headers: { Authorization: `Bearer ${playerGrant.access_token}` },
        data: { trigger: true },
      },
    )
    expect(rejectedResolve.status()).toBe(403)

    // 27. Verify persisted combat resolution and enemy HP reduction via real API
    detail = await readDetail(request, activePrefix)
    const enemyAfter = combatantOf(detail, enemyEntry.id).projection
    expect(enemyAfter.current_hp).toBe(QUICK_ENEMY.maxHp - hit.damage_total)
    await expect(combatantCard(page, enemyEntry.id)).toContainText(`HP:${enemyAfter.current_hp}/${QUICK_ENEMY.maxHp}`)
    await expect(combatantCard(player.page, enemyEntry.id)).not.toContainText('HP:')

    // Verify Player Character Current State via real API (hero was not attacked, stays at 12 HP)
    const heroSheet = await json<{ current_hp: number; max_hp: number }>(
      await request.get(`/api/characters/${character.id}/sheet`),
    )
    expect(heroSheet.current_hp).toBe(12)
    expect(heroSheet.max_hp).toBe(12)

    // 28. Verify attack roll resolution event persistence and secrecy
    const combatEvents = await json<EventPage>(
      await request.get(`${activePrefix}/events?after=0&limit=100`),
    )
    const dmAttackEvent = combatEvents.events.find(
      (e) => e.kind === 'roll.resolved' && Boolean(e.payload.attack_resolution),
    )
    expect(dmAttackEvent).toBeDefined()
    const dmResolution = dmAttackEvent!.payload.attack_resolution as {
      attack: { target_ac: number }
      damage: { adjusted_total: number; after: { current_hp: number } }
    }
    expect(dmResolution.attack.target_ac).toBe(QUICK_ENEMY.ac)
    expect(dmResolution.damage.adjusted_total).toBe(hit.damage_total)
    expect(dmResolution.damage.after.current_hp).toBe(QUICK_ENEMY.maxHp - hit.damage_total)

    const playerCombatEvents = await json<EventPage>(
      await request.get(`${activePrefix}/events?after=0&limit=100`, {
        headers: { Authorization: `Bearer ${playerGrant.access_token}` },
      }),
    )
    const playerAttackEvent = playerCombatEvents.events.find(
      (e) => e.kind === 'roll.resolved' && Boolean(e.payload.attack_resolution),
    )
    expect(playerAttackEvent).toBeDefined()
    const playerResolution = playerAttackEvent!.payload.attack_resolution as {
      attack: Record<string, unknown>
      damage: Record<string, unknown>
    }
    expect(playerResolution.attack).not.toHaveProperty('target_ac')
    expect(playerResolution.damage).not.toHaveProperty('before')
    expect(playerResolution.damage).not.toHaveProperty('after')
    expect(playerResolution.damage).not.toHaveProperty('before_hp')
    expect(playerResolution.damage).not.toHaveProperty('after_hp')

    // 29. End Combat: Player cannot end combat; DM ends combat, stage cleared and state persisted
    await expect(player.page.getByRole('button', { name: 'End Combat' })).toHaveCount(0)
    const rejectedEndCombat = await request.post(`${activePrefix}/combat/end`, {
      headers: { Authorization: `Bearer ${playerGrant.access_token}` },
      data: {},
    })
    expect(rejectedEndCombat.status()).toBe(403)

    const endView = await endCombat(page, sessionId)
    expect(endView.status).toBe('ended')
    expect(endView.round_number).toBeNull()
    expect(endView.current_turn_entry_id).toBeNull()

    await expect(combatStage(page)).toHaveCount(0)
    await expect(combatStage(player.page)).toHaveCount(0)

    // Verify active combat is now null via real API
    const endedDetail = await json<CombatDetail | null>(
      await request.get(`${activePrefix}/combat/detail`),
    )
    expect(endedDetail).toBeNull()

    // Verify combat.ended event is persisted in table events
    const finalEvents = await json<EventPage>(
      await request.get(`${activePrefix}/events?after=0&limit=100`),
    )
    expect(finalEvents.events.map((e) => e.kind)).toContain('combat.ended')

    // Verify Character Current State still persists after combat end
    const postCombatSheet = await json<{ current_hp: number; max_hp: number }>(
      await request.get(`/api/characters/${character.id}/sheet`),
    )
    expect(postCombatSheet.current_hp).toBe(12)
    expect(postCombatSheet.max_hp).toBe(12)

    // 30. Post-Combat Adventure baseline, Stage, and Context assertions
    // Stage image remains visible for both DM and Player after Combat ends
    await expect(dmStageImg).toBeVisible()
    await expect(dmStageImg).toHaveAttribute('src', /^blob:/)
    await expect(playerStageImg).toBeVisible()
    await expect(playerStageImg).toHaveAttribute('src', /^blob:/)

    // Zero tactical map/geometry
    await expect(page.locator('.tactical-grid, .battle-map, [data-tactical-map]')).toHaveCount(0)
    await expect(player.page.locator('.tactical-grid, .battle-map, [data-tactical-map]')).toHaveCount(0)

    // Current Scene and Situation remain intact in runtime context
    const currentContext = await json<RuntimeContext>(
      await request.get(`${activePrefix}/runtime/context`),
    )
    expect(currentContext.current_adventure_scene_entry_id).toBe(sceneEntry.id)
    expect(currentContext.current_runtime_scene_entry_id).toBeNull()
    expect(currentContext.current_situation).toBe(
      'The party reaches the flooded courtyard of the sunken temple.',
    )

    // Adventure definition baseline is unmodified
    const definitionFinal = await json<AdventureDefinition>(
      await request.get(`/api/rooms/${roomId}/adventures/${adventure.id}`),
    )
    expect(definitionFinal.status).toBe('finalized')
    expect(definitionFinal.name).toBe('P6-G Sunken Temple')

    const entriesFinal = await json<AdventureEntry[]>(
      await request.get(`/api/rooms/${roomId}/adventures/${adventure.id}/entries`),
    )
    expect(entriesFinal).toHaveLength(3)

    // Player cannot directly read Adventure, secrets, or DM notes after combat
    const playerAdvResp3 = await request.get(
      `/api/rooms/${roomId}/adventures/${adventure.id}`,
      { headers: { Authorization: `Bearer ${playerGrant.access_token}` } },
    )
    expect(playerAdvResp3.status()).toBe(404)

    const playerFinalHtml = await player.page.content()
    expect(playerFinalHtml).not.toContain('Submerged Relic Vault')
    expect(playerFinalHtml).not.toContain('hidden pressure plate beneath the altar')
    expect(playerFinalHtml).not.toContain('DM Tactics and Traps')
    expect(playerFinalHtml).not.toContain('Triggering the false floor drops players into stagnant pool')
    expect(playerFinalHtml).not.toContain('vault-key.png')
    expect(playerFinalHtml).not.toContain(secretAsset.id)
    expect(playerFinalHtml).not.toContain('/assets/')

    // 31. In the SAME active Session: update Current Situation via official DM UI
    const postCombatContextCard = worldPanel.locator('.runtime-context-card')
    await postCombatContextCard.getByRole('button', { name: 'Edit Context' }).click()
    const UPDATED_SITUATION =
      'The temple guardian has fallen; courtyard waters recede down ancient floor drains.'
    await postCombatContextCard.getByRole('textbox', { name: 'Current Situation' }).fill(UPDATED_SITUATION)
    const contextUpdatedPromise = page.waitForResponse(
      (resp) => resp.request().method() === 'PATCH' && resp.url().endsWith(`/sessions/${sessionId}/runtime/context`),
    )
    await postCombatContextCard.getByRole('button', { name: 'Save Context' }).click()
    await responseJson(await contextUpdatedPromise)
    await expect(postCombatContextCard).toContainText(UPDATED_SITUATION)

    // 32. Persist a Fact via official DM UI Quick Add
    await worldPanel.getByRole('button', { name: 'Quick Add' }).click()
    const factForm = worldPanel.locator('form')
    await expect(factForm).toBeVisible()
    await factForm.getByRole('combobox', { name: 'Kind', exact: true }).selectOption('fact')
    const FACT_TITLE = 'Receded Temple Waters'
    const FACT_BODY =
      'With the guardian destroyed, the dark waters drained away to reveal mossy stone stairs descending into the crypt.'
    await factForm.getByRole('textbox', { name: 'Title / Name' }).fill(FACT_TITLE)
    await factForm.getByRole('textbox', { name: 'Description / Body' }).fill(FACT_BODY)
    const factCreatedPromise = page.waitForResponse(
      (resp) => resp.request().method() === 'POST' && resp.url().endsWith(`/sessions/${sessionId}/runtime/entries`),
    )
    await factForm.getByRole('button', { name: 'Create Entry' }).click()
    await responseJson(await factCreatedPromise)

    await expect(worldPanel).toContainText(FACT_TITLE)
    await expect(player.page.locator('.session-journal-panel')).toContainText(FACT_BODY)

    // 33. Persist an explicit Adventure Override via official backend service
    const OVERRIDE_NOTE = 'Courtyard altered: water drained and mossy stairs exposed after combat'
    const OVERRIDE_STATE = {
      read_aloud: 'The courtyard stands drained and damp; shattered guardian stones surround a revealed stairwell.',
      dm_summary: 'Guardian defeated; water drained, revealed crypt entrance stairs.',
    }
    const override = await json<CampaignAdventureOverride>(
      await request.post(`${activePrefix}/runtime/overrides`, {
        data: {
          idempotency_key: `p6g-adventure-override-${sessionId}`,
          adventure_entry_id: sceneEntry.id,
          state: OVERRIDE_STATE,
          note: OVERRIDE_NOTE,
          needs_review: false,
        },
      }),
    )
    expect(override.adventure_entry_id).toBe(sceneEntry.id)
    expect(override.note).toBe(OVERRIDE_NOTE)
    expect(override.revision).toBe(1)

    // Reload DM page to verify review list displays the overridden scene entry
    await page.reload()
    await expect(page.locator('.session-world-panel')).toBeVisible()
    await expect(page.locator('.session-world-review')).toContainText('Sunken Temple Courtyard')
    await expect(page.locator('.runtime-context-card')).toContainText(UPDATED_SITUATION)

    // 34. Assert write-back in AT API/UI: Narration alone must not be the only record
    const POST_COMBAT_NARRATION =
      'The shattered guardian crumbles into the mire; a low grinding sound echoes as the dark waters rush down newly opened floor vents.'
    await page.getByRole('combobox', { name: 'Type', exact: true }).selectOption('narration')
    await page.getByPlaceholder(/Type here/).fill(POST_COMBAT_NARRATION)
    const postNarrationPromise = page.waitForResponse(
      (resp) => resp.request().method() === 'POST' && resp.url().includes(`/sessions/${sessionId}/exploration`),
    )
    await page.getByRole('button', { name: 'Send' }).click()
    await responseJson(await postNarrationPromise)
    await expect(page.getByText(POST_COMBAT_NARRATION, { exact: true })).toBeVisible()
    await player.page.getByRole('button', { name: 'Chat', exact: true }).click()
    await expect(player.page.getByText(POST_COMBAT_NARRATION, { exact: true })).toBeVisible()

    // Assert AT API write-back: durable world state is queryable through REST services
    const session1Context = await json<RuntimeContext>(
      await request.get(`${activePrefix}/runtime/context`),
    )
    expect(session1Context.current_situation).toBe(UPDATED_SITUATION)
    expect(session1Context.current_adventure_scene_entry_id).toBe(sceneEntry.id)

    const session1Overrides = await json<CampaignAdventureOverride[]>(
      await request.get(`${activePrefix}/runtime/overrides`),
    )
    expect(session1Overrides).toHaveLength(1)
    expect(session1Overrides[0].adventure_entry_id).toBe(sceneEntry.id)
    expect(session1Overrides[0].note).toBe(OVERRIDE_NOTE)

    const session1Entries = await json<RuntimeEntry[]>(
      await request.get(`${activePrefix}/runtime/entries`),
    )
    const storedFact = session1Entries.find((e) => e.kind === 'fact' && e.title === FACT_TITLE)
    expect(storedFact).toBeDefined()
    expect(storedFact!.body).toBe(FACT_BODY)

    // Verify session events include context change, entry creation, and override creation
    const sessionEvents = await json<EventPage>(
      await request.get(`${activePrefix}/events?after=0&limit=100`),
    )
    const sessionEventKinds = sessionEvents.events.map((e) => e.kind)
    expect(sessionEventKinds).toContain('world.context_changed')
    expect(sessionEventKinds).toContain('world.entry.created')
    expect(sessionEventKinds).toContain('world.override.created')

    // 35. Secrecy & Player projection filtering in Session 1
    // Player event stream does not receive DM-only world events
    const playerEvents1 = await json<EventPage>(
      await request.get(`${activePrefix}/events?after=0&limit=100`, {
        headers: { Authorization: `Bearer ${playerGrant.access_token}` },
      }),
    )
    const playerEventKinds = playerEvents1.events.map((e) => e.kind)
    expect(playerEventKinds).not.toContain('world.override.created')
    expect(playerEventKinds).not.toContain('world.context_changed')

    // Player direct API access to overrides and context is forbidden
    const playerOverrideResp = await request.get(`${activePrefix}/runtime/overrides`, {
      headers: { Authorization: `Bearer ${playerGrant.access_token}` },
    })
    expect(playerOverrideResp.status()).toBe(403)

    const playerContextResp = await request.get(`${activePrefix}/runtime/context`, {
      headers: { Authorization: `Bearer ${playerGrant.access_token}` },
    })
    expect(playerContextResp.status()).toBe(403)

    const playerCreateOverrideResp = await request.post(`${activePrefix}/runtime/overrides`, {
      headers: { Authorization: `Bearer ${playerGrant.access_token}` },
      data: {
        idempotency_key: 'forbidden-override',
        adventure_entry_id: sceneEntry.id,
        state: {},
      },
    })
    expect(playerCreateOverrideResp.status()).toBe(403)

    // Player UI does not leak internal override state or note
    const playerHtmlMid = await player.page.content()
    expect(playerHtmlMid).not.toContain(OVERRIDE_NOTE)

    // Original Adventure Definition baseline is unmodified by the override
    const defEntriesMid = await json<AdventureEntry[]>(
      await request.get(`/api/rooms/${roomId}/adventures/${adventure.id}/entries`),
    )
    const baselineSceneMid = defEntriesMid.find((e) => e.id === sceneEntry.id)!
    expect(baselineSceneMid.title).toBe('Sunken Temple Courtyard')
    expect(baselineSceneMid.body).toBe('Ancient stone archway overgrown with vines.')

    // 36. End first Session via official UI
    page.once('dialog', (dialog) => dialog.accept())
    const endSessionPromise = page.waitForResponse(
      (resp) => resp.request().method() === 'POST' && resp.url().includes(`/sessions/${sessionId}/end`),
    )
    await page.getByRole('button', { name: 'End Session' }).click()
    await responseJson(await endSessionPromise)
    await expect(page.getByText('Ended', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'End Session' })).toHaveCount(0)

    // 37. Management Check on Campaign Changes page (/changes)
    await page.goto(`/rooms/${roomId}/campaigns/${campaign.id}/changes`)
    await expect(page.getByRole('heading', { name: 'Campaign Changes', level: 1 })).toBeVisible()

    const changesOverlay = page.locator('.adventure-entry').filter({ hasText: 'Sunken Temple Courtyard' })
    await expect(changesOverlay).toBeVisible()
    await expect(changesOverlay.getByText('Active Override', { exact: true })).toBeVisible()
    await expect(changesOverlay).toContainText(OVERRIDE_NOTE)

    const changesContext = page.locator('.runtime-context-card')
    await expect(changesContext).toContainText('Sunken Temple Courtyard')
    await expect(changesContext).toContainText(UPDATED_SITUATION)

    await expect(page.locator('.runtime-entry-card').filter({ hasText: FACT_TITLE })).toBeVisible()

    // 38. Return to Lobby, start second Session, and assert continuity of updated world truth
    await page.goto(`/rooms/${roomId}/campaigns/${campaign.id}/lobby`)
    await expect(page.getByRole('heading', { name: 'Lobby & Seats', level: 1 })).toBeVisible()

    await expect(page.locator('article.seat-card').filter({ hasText: 'P6-G DM' })).toBeVisible()
    const playerSeatCard = page.locator('article.seat-card').filter({ hasText: 'P6-G Player' })
    await expect(playerSeatCard).toBeVisible()
    await expect(playerSeatCard).toContainText(character.name)

    await page.getByRole('button', { name: 'Start Session' }).click()
    await expect(page).toHaveURL(
      new RegExp(`/rooms/${roomId}/campaigns/${campaign.id}/sessions/[0-9a-fA-F-]{36}/?$`),
    )
    await expect(page.getByRole('heading', { name: 'Active Session', level: 1 })).toBeVisible()

    const nextSessionMatch = page.url().match(/\/sessions\/([0-9a-fA-F-]{36})/)
    expect(nextSessionMatch).not.toBeNull()
    const nextSessionId = nextSessionMatch![1]
    expect(nextSessionId).not.toBe(sessionId)
    const nextActivePrefix = `/api/rooms/${roomId}/campaigns/${campaign.id}/sessions/${nextSessionId}`
    const nextSessionUrl = `/rooms/${roomId}/campaigns/${campaign.id}/sessions/${nextSessionId}`

    // Note on AI DM context check boundary:
    // P3-D authority requires an AI DM controller grant binding on the Seat to call
    // MCP get_session_context or AI retrieval tools. Because this journey tests a
    // Human DM on the DM Seat, faking an AI grant token or bypassing controller
    // authority would violate the core security contract. Real AI DM context retrieval
    // with actual token grant is verified in G4 (P6-G_steps/G4.md).

    // DM UI in Session 2: Current Scene, Updated Situation, Fact, and Review List persist
    const nextWorldPanel = page.locator('.session-world-panel')
    await expect(nextWorldPanel).toBeVisible()

    const nextContextCard = nextWorldPanel.locator('.runtime-context-card')
    await expect(nextContextCard).toContainText('Sunken Temple Courtyard')
    await expect(nextContextCard).toContainText(UPDATED_SITUATION)

    await expect(nextWorldPanel).toContainText(FACT_TITLE)
    await expect(nextWorldPanel.locator('.session-world-review')).toContainText('Sunken Temple Courtyard')

    // DM sets Stage Image from Current Scene in Session 2
    await nextWorldPanel.getByRole('button', { name: 'Set Stage Image' }).click()
    const nextStageSelect = nextWorldPanel.getByRole('combobox', { name: 'Select Stage image source' })
    await expect(nextStageSelect).toBeVisible()
    await nextStageSelect.selectOption({ label: 'Sunken Temple Courtyard — sunken-temple.png' })

    const nextStagePromise = page.waitForResponse(
      (resp) => resp.request().method() === 'PUT' && resp.url().endsWith(`/sessions/${nextSessionId}/stage/image-source`),
    )
    await nextWorldPanel.getByRole('button', { name: 'Set as Stage Image' }).click()
    await responseJson(await nextStagePromise)

    const dmNextStageImg = page.locator('.session-stage img')
    await expect(dmNextStageImg).toBeVisible()
    await expect(dmNextStageImg).toHaveAttribute('src', /^blob:/)

    // DM API assertions in Session 2
    const nextContext = await json<RuntimeContext>(
      await request.get(`${nextActivePrefix}/runtime/context`),
    )
    expect(nextContext.current_adventure_scene_entry_id).toBe(sceneEntry.id)
    expect(nextContext.current_runtime_scene_entry_id).toBeNull()
    expect(nextContext.current_situation).toBe(UPDATED_SITUATION)

    const nextOverrides = await json<CampaignAdventureOverride[]>(
      await request.get(`${nextActivePrefix}/runtime/overrides`),
    )
    expect(nextOverrides).toHaveLength(1)
    expect(nextOverrides[0].adventure_entry_id).toBe(sceneEntry.id)
    expect(nextOverrides[0].note).toBe(OVERRIDE_NOTE)
    expect(nextOverrides[0].revision).toBeGreaterThanOrEqual(1)

    const nextDmEntries = await json<RuntimeEntry[]>(
      await request.get(`${nextActivePrefix}/runtime/entries`),
    )
    const nextFact = nextDmEntries.find((e) => e.kind === 'fact' && e.title === FACT_TITLE)
    expect(nextFact).toBeDefined()
    expect(nextFact!.body).toBe(FACT_BODY)

    // Assert Original Adventure Definition baseline is STILL Unmodified
    const defAfter = await json<AdventureDefinition>(
      await request.get(`/api/rooms/${roomId}/adventures/${adventure.id}`),
    )
    expect(defAfter.status).toBe('finalized')
    expect(defAfter.name).toBe('P6-G Sunken Temple')

    const defEntriesAfter = await json<AdventureEntry[]>(
      await request.get(`/api/rooms/${roomId}/adventures/${adventure.id}/entries`),
    )
    expect(defEntriesAfter).toHaveLength(3)

    const sceneDef = defEntriesAfter.find((e) => e.id === sceneEntry.id)!
    expect(sceneDef.title).toBe('Sunken Temple Courtyard')
    expect(sceneDef.body).toBe('Ancient stone archway overgrown with vines.')
    expect(sceneDef.visibility).toBe('public')

    const secretDef = defEntriesAfter.find((e) => e.id === secretEntry.id)!
    expect(secretDef.title).toBe('Submerged Relic Vault')
    expect(secretDef.body).toBe('A hidden pressure plate beneath the altar opens the flooded crypt.')
    expect(secretDef.visibility).toBe('dm_only')

    const dmNoteDef = defEntriesAfter.find((e) => e.id === dmNoteEntry.id)!
    expect(dmNoteDef.title).toBe('DM Tactics and Traps')
    expect(dmNoteDef.body).toBe('Triggering the false floor drops players into stagnant pool.')
    expect(dmNoteDef.visibility).toBe('dm_only')

    // Reconnect Player to Next Session & Assert Secrecy
    await player.page.goto(nextSessionUrl)
    await expect(player.page.getByRole('heading', { name: 'Active Session', level: 1 })).toBeVisible()

    const playerNextStageImg = player.page.locator('.session-stage img')
    await expect(playerNextStageImg).toBeVisible()
    await expect(playerNextStageImg).toHaveAttribute('src', /^blob:/)

    const playerNextHtml = await player.page.content()
    expect(playerNextHtml).not.toContain(sceneAsset.id)
    expect(playerNextHtml).not.toContain('/assets/')
    expect(playerNextHtml).not.toContain('Submerged Relic Vault')
    expect(playerNextHtml).not.toContain('hidden pressure plate beneath the altar')
    expect(playerNextHtml).not.toContain('DM Tactics and Traps')
    expect(playerNextHtml).not.toContain('Triggering the false floor drops players into stagnant pool')
    expect(playerNextHtml).not.toContain(OVERRIDE_NOTE)
    expect(playerNextHtml).not.toContain(secretAsset.id)

    const nextJournal = player.page.locator('.session-journal-panel')
    await expect(nextJournal).toBeVisible()
    await expect(nextJournal).toContainText(FACT_BODY)
    await expect(player.page.locator('.session-world-panel')).toHaveCount(0)
    await expect(player.page.getByRole('button', { name: 'Quick Add' })).toHaveCount(0)
    await expect(player.page.getByRole('button', { name: 'Start Combat' })).toHaveCount(0)
    await expect(combatStage(player.page)).toHaveCount(0)

    // Player API projection filtering in Session 2
    const playerNextEntries = await json<RuntimeEntry[]>(
      await request.get(`${nextActivePrefix}/runtime/entries`, {
        headers: { Authorization: `Bearer ${playerGrant.access_token}` },
      }),
    )
    expect(playerNextEntries.some((e) => e.title === FACT_TITLE)).toBe(true)
    for (const entry of playerNextEntries) {
      expect(entry).not.toHaveProperty('dm_notes')
      expect(entry).not.toHaveProperty('character_recipient_ids')
      expect(entry).not.toHaveProperty('needs_review')
      expect(entry).not.toHaveProperty('provenance_json')
    }

    const playerNextOverrides = await request.get(`${nextActivePrefix}/runtime/overrides`, {
      headers: { Authorization: `Bearer ${playerGrant.access_token}` },
    })
    expect(playerNextOverrides.status()).toBe(403)

    const playerNextContext = await request.get(`${nextActivePrefix}/runtime/context`, {
      headers: { Authorization: `Bearer ${playerGrant.access_token}` },
    })
    expect(playerNextContext.status()).toBe(403)

    const playerNextAdv = await request.get(`/api/rooms/${roomId}/adventures/${adventure.id}`, {
      headers: { Authorization: `Bearer ${playerGrant.access_token}` },
    })
    expect(playerNextAdv.status()).toBe(404)

    const playerNextSecretAsset = await request.get(`/api/rooms/${roomId}/assets/${secretAsset.id}`, {
      headers: { Authorization: `Bearer ${playerGrant.access_token}` },
    })
    expect(playerNextSecretAsset.status()).toBe(404)

    // Character sheet HP remains 12 across sessions
    const nextHeroSheet = await json<{ current_hp: number; max_hp: number }>(
      await request.get(`/api/characters/${character.id}/sheet`),
    )
    expect(nextHeroSheet.current_hp).toBe(12)
    expect(nextHeroSheet.max_hp).toBe(12)

    // Active combat is null in Session 2
    const nextCombatDetail = await json<CombatDetail | null>(
      await request.get(`${nextActivePrefix}/combat/detail`),
    )
    expect(nextCombatDetail).toBeNull()

    // Recorded ended Combat outcome remains inspectable via previous link
    const prevLink = await json<SessionHistoryLink>(
      await request.get(`${nextActivePrefix}/previous`),
    )
    expect(prevLink.previous_session).not.toBeNull()
    expect(prevLink.previous_session!.id).toBe(sessionId)
    expect(prevLink.previous_session!.status).toBe('ended')

    const prevMonsters = await json<MonsterInstance[]>(
      await request.get(`/api/rooms/${roomId}/campaigns/${campaign.id}/sessions/${sessionId}/monster-instances`),
    )
    const recordedGuardian = prevMonsters.find((m) => m.name === QUICK_ENEMY.name)
    expect(recordedGuardian).toBeDefined()
    expect(recordedGuardian!.current_hp).toBe(QUICK_ENEMY.maxHp - hit.damage_total)
  } finally {
    await player.context.close()
  }
})
