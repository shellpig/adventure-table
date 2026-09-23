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

test('P6-G G1a: empty Campaign from start through DM narration, quick-add, exploration, and player roll', async ({
  browser,
  page,
  request,
  roomContext,
}) => {
  test.setTimeout(180_000)
  const { roomId } = roomContext

  // 1. Campaign with ZERO attached Adventures
  const campaign = await createCampaign(request, roomId, 'P6-G Empty Campaign')
  const attachedAdventures = await json<unknown[]>(
    await request.get(`/api/rooms/${roomId}/campaigns/${campaign.id}/adventures`),
  )
  expect(attachedAdventures).toEqual([])

  // 2. DM Seat and Player Seat with Character
  const lobby = await json<Lobby>(
    await request.get(`/api/rooms/${roomId}/campaigns/${campaign.id}/lobby`),
  )
  expect(lobby.caller_access_session_id).not.toBeNull()
  await addSeat(request, roomId, campaign.id, 'dm', lobby.caller_access_session_id!, 'P6-G DM')

  const playerGrant = await enterAsMember(request, roomContext, 'P6-G Player')
  const character = await importCharacter(request)
  const playerSeat = await addPlayerSeat(
    request,
    roomId,
    campaign.id,
    character,
    playerGrant.access_session_id,
    'P6-G Player',
  )

  // 3. Start Session through official UI
  const sessionId = await startSession(page, roomId, campaign.id)
  const sessionUrl = `/rooms/${roomId}/campaigns/${campaign.id}/sessions/${sessionId}`
  const activePrefix = `/api/rooms/${roomId}/campaigns/${campaign.id}/sessions/${sessionId}`

  const player = await openSessionAs(browser, playerGrant, roomContext, sessionUrl)

  try {
    // Assert initial layout & secrecy:
    // DM sees session-world-panel; Player sees session-journal-panel and NOT session-world-panel
    const worldPanel = page.locator('.session-world-panel')
    await expect(worldPanel).toBeVisible()
    await expect(page.locator('.session-journal-panel')).toHaveCount(0)

    const journalPanel = player.page.locator('.session-journal-panel')
    await expect(journalPanel).toBeVisible()
    await expect(player.page.locator('.session-world-panel')).toHaveCount(0)
    await expect(player.page.getByRole('button', { name: 'Quick Add' })).toHaveCount(0)

    // 4. DM narration through UI
    const NARRATION_TEXT = 'The sun sets behind the craggy ridge as darkness settles over the empty hills.'
    await page.getByRole('combobox', { name: 'Type', exact: true }).selectOption('narration')
    await page.getByPlaceholder(/Type here/).fill(NARRATION_TEXT)
    const narrationPromise = page.waitForResponse(
      (resp) => resp.request().method() === 'POST' && resp.url().includes(`/sessions/${sessionId}/exploration`),
    )
    await page.getByRole('button', { name: 'Send' }).click()
    await responseJson(await narrationPromise)

    await expect(page.getByText(NARRATION_TEXT, { exact: true })).toBeVisible()
    await expect(player.page.getByText(NARRATION_TEXT, { exact: true })).toBeVisible()

    // 5. Quick Add NPC and Fact through production UI
    // 5a. Quick Add NPC
    await worldPanel.getByRole('button', { name: 'Quick Add' }).click()
    const npcForm = worldPanel.locator('form')
    await expect(npcForm).toBeVisible()
    await npcForm.getByRole('combobox', { name: 'Kind', exact: true }).selectOption('npc')
    await npcForm.getByRole('textbox', { name: 'Title / Name' }).fill('Old Ben')
    await npcForm.getByRole('textbox', { name: 'Description / Body' }).fill('A wandering hermit who knows the hills.')
    await npcForm.getByRole('textbox', { name: 'DM Notes' }).fill('Secretly a retired ranger spying on goblin bands.')
    const npcCreatedPromise = page.waitForResponse(
      (resp) => resp.request().method() === 'POST' && resp.url().endsWith(`/sessions/${sessionId}/runtime/entries`),
    )
    await npcForm.getByRole('button', { name: 'Create Entry' }).click()
    await responseJson(await npcCreatedPromise)

    // Verify NPC appears in DM's panel
    await expect(worldPanel).toContainText('Old Ben')

    // 5b. Quick Add Fact
    await worldPanel.getByRole('button', { name: 'Quick Add' }).click()
    const factForm = worldPanel.locator('form')
    await expect(factForm).toBeVisible()
    await factForm.getByRole('combobox', { name: 'Kind', exact: true }).selectOption('fact')
    const FACT_TITLE = 'Night Moors'
    const FACT_TEXT = 'A cold wind carries the distant howl of wolves.'
    await factForm.getByRole('textbox', { name: 'Title / Name' }).fill(FACT_TITLE)
    await factForm.getByRole('textbox', { name: 'Description / Body' }).fill(FACT_TEXT)
    const factCreatedPromise = page.waitForResponse(
      (resp) => resp.request().method() === 'POST' && resp.url().endsWith(`/sessions/${sessionId}/runtime/entries`),
    )
    await factForm.getByRole('button', { name: 'Create Entry' }).click()
    await responseJson(await factCreatedPromise)

    // Verify Fact in DM panel and Player Journal
    await expect(worldPanel).toContainText(FACT_TITLE)
    await expect(journalPanel).toContainText(FACT_TEXT)

    // Player secrecy assertions:
    // Player does NOT see DM Notes in Journal or anywhere in DOM
    await expect(player.page.locator('body')).not.toContainText('Secretly a retired ranger')

    // Direct Adventure read check:
    // UI: player navigating to adventures page gets permission denied
    const playerAdventuresPage = await player.context.newPage()
    await playerAdventuresPage.goto(`/rooms/${roomId}/adventures`)
    await expect(playerAdventuresPage.getByText('Only the Room owner or DM can manage Adventures.')).toBeVisible()
    await playerAdventuresPage.close()

    // API: player direct read to /adventures is 404
    const playerDirectAdventuresResp = await request.get(`/api/rooms/${roomId}/adventures`, {
      headers: { Authorization: `Bearer ${playerGrant.access_token}` },
    })
    expect(playerDirectAdventuresResp.status()).toBe(404)

    // 6. Player exploration action through UI
    await player.page.getByRole('combobox', { name: 'Type', exact: true }).selectOption('action')
    await player.page.getByRole('combobox', { name: 'Character', exact: true }).selectOption(playerSeat.id)
    const ACTION_TEXT = 'I listen intently to identify how close the howling is.'
    await player.page.getByPlaceholder(/Type here/).fill(ACTION_TEXT)
    const actionPromise = player.page.waitForResponse(
      (resp) => resp.request().method() === 'POST' && resp.url().includes(`/sessions/${sessionId}/exploration`),
    )
    await player.page.getByRole('button', { name: 'Send' }).click()
    await responseJson(await actionPromise)

    await expect(page.getByText(ACTION_TEXT, { exact: true })).toBeVisible()
    await expect(player.page.getByText(ACTION_TEXT, { exact: true })).toBeVisible()

    // 7. DM formal Request Check
    await page.getByRole('button', { name: 'Dice', exact: true }).click()
    const targetCheckbox = page.getByRole('checkbox', { name: new RegExp(character.name) })
    await expect(targetCheckbox).toBeChecked()
    await page.getByRole('combobox', { name: 'Check type' }).selectOption('skill')
    await page.getByRole('combobox', { name: 'Skill' }).selectOption('srd5.1:skill:perception')
    await page.getByLabel('DC (optional)', { exact: true }).fill('12')
    await page.getByRole('combobox', { name: 'Roll mode' }).selectOption('normal')
    await page.getByRole('combobox', { name: 'Result visibility' }).selectOption('public')
    await page.getByLabel('Label', { exact: true }).fill('Listen for wolves')

    const checkPromise = page.waitForResponse(
      (resp) => resp.request().method() === 'POST' && resp.url().includes(`/sessions/${sessionId}/checks`),
    )
    await page.getByRole('button', { name: 'Create Check' }).click()
    const checkResponse = await responseJson<RequestCheckResponse>(await checkPromise)
    expect(checkResponse.requests).toHaveLength(1)
    const rollRequestId = checkResponse.requests[0].id
    expect(checkResponse.requests[0]).toMatchObject({
      target_seat_id: playerSeat.id,
      dc: 12,
      status: 'pending',
    })

    const rollPrompt = `The DM asks ${character.name} to make Perception (Skill Check): Listen for wolves.`
    await expect(player.page.getByText(rollPrompt, { exact: true })).toBeVisible()

    // DM sees pending request with DC 12
    const dmRequestCard = page.locator('.session-roll-request').first()
    await expect(dmRequestCard).toHaveAttribute('data-roll-request-status', 'pending')
    await expect(dmRequestCard.getByText('DC 12', { exact: true })).toBeVisible()

    // 8. Player completes roll
    await player.page.getByRole('button', { name: 'Dice', exact: true }).click()
    const playerRequestCard = player.page.locator('.session-roll-request').first()
    await expect(playerRequestCard).toHaveAttribute('data-roll-request-status', 'pending')
    await expect(playerRequestCard.getByText('Waiting to roll', { exact: true })).toBeVisible()
    // Player does NOT see DC (secrecy)
    await expect(playerRequestCard.getByText('DC 12', { exact: true })).toHaveCount(0)

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

    // Player and DM see resolved status
    await expect(playerRequestCard).toHaveAttribute('data-roll-request-status', 'resolved')
    await expect(dmRequestCard).toHaveAttribute('data-roll-request-status', 'resolved')

    // 9. Assert persisted AT events & Runtime state
    // Check persisted events via API
    const eventPage = await json<EventPage>(
      await request.get(`${activePrefix}/events?after=0&limit=100`),
    )
    const eventKinds = eventPage.events.map((e) => e.kind)
    expect(eventKinds).toContain('exploration.narration')
    expect(eventKinds).toContain('world.entry.created')
    expect(eventKinds).toContain('exploration.action')
    expect(eventKinds).toContain('roll.requested')
    expect(eventKinds).toContain('roll.resolved')

    const narrationEvent = eventPage.events.find((e) => e.kind === 'exploration.narration')!
    expect(narrationEvent.payload.text).toBe(NARRATION_TEXT)

    const actionEvent = eventPage.events.find((e) => e.kind === 'exploration.action')!
    expect(actionEvent.payload.text).toBe(ACTION_TEXT)
    const speakerSeat = actionEvent.acting_seat_id ?? actionEvent.subject_seat_id
    expect(speakerSeat).toBe(playerSeat.id)

    // Check persisted Runtime state
    const dmEntries = await json<RuntimeEntry[]>(
      await request.get(`${activePrefix}/runtime/entries`),
    )
    expect(dmEntries.length).toBeGreaterThanOrEqual(2)
    const npcEntry = dmEntries.find((e) => e.kind === 'npc')
    expect(npcEntry).toBeDefined()
    expect(npcEntry!.title).toBe('Old Ben')
    expect(npcEntry!.dm_notes).toBe('Secretly a retired ranger spying on goblin bands.')

    const factEntry = dmEntries.find((e) => e.kind === 'fact')
    expect(factEntry).toBeDefined()
    expect(factEntry!.title).toBe(FACT_TITLE)
    expect(factEntry!.body).toBe(FACT_TEXT)

    // Check player-scoped runtime entries projection
    const playerEntries = await json<RuntimeEntry[]>(
      await request.get(`${activePrefix}/runtime/entries`, {
        headers: { Authorization: `Bearer ${playerGrant.access_token}` },
      }),
    )
    for (const entry of playerEntries) {
      expect(entry).not.toHaveProperty('dm_notes')
      expect(entry).not.toHaveProperty('character_recipient_ids')
      expect(entry).not.toHaveProperty('needs_review')
      expect(entry).not.toHaveProperty('provenance_json')
    }
  } finally {
    await player.context.close()
  }
})
