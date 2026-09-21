import { expect, test, type APIRequestContext } from './support/roomTest'
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

type AdventureDefinition = { id: string; name: string }
type AdventureEntry = { id: string; title: string | null }
type AttachedAdventure = { adventure_id: string }
type RuntimeEntry = {
  id: string
  kind: string
  title: string | null
  body: string | null
  visibility: string
  revision: number
  [key: string]: unknown
}

async function createSceneAdventure(
  request: APIRequestContext,
  roomId: string,
  name: string,
  sceneTitle: string,
): Promise<{ adventure: AdventureDefinition; scene: AdventureEntry }> {
  const adventure = await json<AdventureDefinition>(await request.post(
    `/api/rooms/${roomId}/adventures`,
    { data: { name } },
  ))
  const scene = await json<AdventureEntry>(await request.post(
    `/api/rooms/${roomId}/adventures/${adventure.id}/entries`,
    {
      data: {
        kind: 'scene',
        title: sceneTitle,
        body: 'A baseline scene that Runtime must never rewrite.',
        data: { kind: 'scene', read_aloud: 'Cold mist curls over the old stones.' },
        visibility: 'public',
      },
    },
  ))
  await json(await request.post(`/api/rooms/${roomId}/adventures/${adventure.id}/finalize`))
  return { adventure, scene }
}

async function createActiveRuntimeEntry(
  request: APIRequestContext,
  prefix: string,
  input: {
    key: string
    kind: 'scene' | 'quest' | 'fact' | 'secret'
    title: string
    body: string
    visibility: 'public' | 'dm_only' | 'character'
    characterIds?: string[]
    dmNotes?: string
  },
): Promise<RuntimeEntry> {
  return json<RuntimeEntry>(await request.post(`${prefix}/runtime/entries`, {
    data: {
      idempotency_key: input.key,
      kind: input.kind,
      title: input.title,
      body: input.body,
      state: { kind: input.kind },
      visibility: input.visibility,
      character_recipient_ids: input.characterIds ?? [],
      dm_notes: input.dmNotes ?? null,
      needs_review: false,
      provenance_json: null,
    },
  }))
}

test('P6-B Campaign Changes: override and Current Scene both block detach until cleared', async ({
  page,
  request,
  roomContext,
}) => {
  test.setTimeout(120_000)
  const { roomId } = roomContext
  const adventureName = 'P6-B Detach Blocker Adventure'
  const sceneTitle = 'P6-B Blocker Scene'
  const { adventure, scene } = await createSceneAdventure(
    request,
    roomId,
    adventureName,
    sceneTitle,
  )
  const campaign = await createCampaign(request, roomId, 'P6-B Blocker Campaign')
  await json(await request.post(`/api/rooms/${roomId}/campaigns/${campaign.id}/adventures`, {
    data: { adventure_id: adventure.id },
  }))

  await page.goto(`/rooms/${roomId}/campaigns/${campaign.id}/changes`)
  await expect(page.getByRole('heading', { name: 'Campaign Changes', level: 1 })).toBeVisible()

  const overlayCard = page.locator('.adventure-entry').filter({ hasText: sceneTitle })
  await expect(overlayCard).toBeVisible()
  await overlayCard.getByRole('button', { name: 'Add Override' }).click()
  const overrideForm = page.getByRole('heading', { name: 'New Adventure Override' })
    .locator('..')
  await overrideForm.getByRole('textbox', { name: 'Override State JSON (top-level object)' })
    .fill('{"dm_summary":"The arch has collapsed."}')
  await overrideForm.getByRole('textbox', { name: 'Note' }).fill('P6-B override blocker')
  await overrideForm.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(overlayCard.getByText('Active Override', { exact: true })).toBeVisible()

  const contextCard = page.locator('.runtime-context-card')
  await contextCard.getByRole('button', { name: 'Edit Context' }).click()
  await contextCard.getByRole('combobox', { name: 'Current Scene' })
    .selectOption(`adventure:${scene.id}`)
  await contextCard.getByRole('textbox', { name: 'Current Situation' })
    .fill('The party is examining the collapsed arch.')
  await contextCard.getByRole('button', { name: 'Save Context' }).click()
  await expect(contextCard).toContainText('The party is examining the collapsed arch.')

  const adventureBlock = page.locator('.attached-adventure-block').filter({ hasText: adventureName })
  await expect(adventureBlock).toContainText('active overrides')
  await expect(adventureBlock).toContainText('current scene is set to a scene from this adventure')

  await page.goto(`/rooms/${roomId}/campaigns/${campaign.id}`)
  const adventureCard = page.locator('.adventure-card').filter({ hasText: adventureName })
  page.once('dialog', (dialog) => dialog.accept())
  await adventureCard.getByRole('button', { name: 'Detach' }).click()
  await expect(page.getByText(
    'Cannot detach this Adventure because it has active overrides or is the active scene.',
  )).toBeVisible()
  await expect(adventureCard).toBeVisible()

  await page.goto(`/rooms/${roomId}/campaigns/${campaign.id}/changes`)
  const refreshedOverlay = page.locator('.adventure-entry').filter({ hasText: sceneTitle })
  page.once('dialog', (dialog) => dialog.accept())
  await refreshedOverlay.getByRole('button', { name: 'Clear Override' }).click()
  await expect(refreshedOverlay.getByText('No override active', { exact: false })).toBeVisible()
  const refreshedContext = page.locator('.runtime-context-card')
  page.once('dialog', (dialog) => dialog.accept())
  await refreshedContext.getByRole('button', { name: 'Clear Context' }).click()
  await expect(refreshedContext).toContainText('Current Scene: None')

  await page.goto(`/rooms/${roomId}/campaigns/${campaign.id}`)
  const detachableCard = page.locator('.adventure-card').filter({ hasText: adventureName })
  page.once('dialog', (dialog) => dialog.accept())
  await detachableCard.getByRole('button', { name: 'Detach' }).click()
  await expect(detachableCard).toHaveCount(0)
  expect(await json<AttachedAdventure[]>(await request.get(
    `/api/rooms/${roomId}/campaigns/${campaign.id}/adventures`,
  ))).toEqual([])
})

test('P6-B active Session: empty-Campaign Quick Add, context, Player Journal secrecy and reload', async ({
  browser,
  page,
  request,
  roomContext,
}) => {
  test.setTimeout(180_000)
  const { roomId } = roomContext
  const campaign = await createCampaign(request, roomId, 'P6-B Empty Runtime Campaign')
  expect(await json<AttachedAdventure[]>(await request.get(
    `/api/rooms/${roomId}/campaigns/${campaign.id}/adventures`,
  ))).toEqual([])

  const lobby = await json<Lobby>(await request.get(
    `/api/rooms/${roomId}/campaigns/${campaign.id}/lobby`,
  ))
  expect(lobby.caller_access_session_id).not.toBeNull()
  await addSeat(request, roomId, campaign.id, 'dm', lobby.caller_access_session_id!, 'P6-B')

  const playerOne = await enterAsMember(request, roomContext, 'P6-B Player One')
  const playerTwo = await enterAsMember(request, roomContext, 'P6-B Player Two')
  const characterOne = await importCharacter(request)
  const characterTwo = await importCharacter(request)
  await addPlayerSeat(
    request,
    roomId,
    campaign.id,
    characterOne,
    playerOne.access_session_id,
    'P6-B One',
  )
  await addPlayerSeat(
    request,
    roomId,
    campaign.id,
    characterTwo,
    playerTwo.access_session_id,
    'P6-B Two',
  )

  const sessionId = await startSession(page, roomId, campaign.id)
  const sessionUrl = `/rooms/${roomId}/campaigns/${campaign.id}/sessions/${sessionId}`
  const activePrefix = `/api/rooms/${roomId}/campaigns/${campaign.id}/sessions/${sessionId}`
  const player = await openSessionAs(browser, playerOne, roomContext, sessionUrl)
  const playerRuntimeRequests: string[] = []
  player.page.on('request', (req) => {
    if (req.url().includes('/runtime/')) playerRuntimeRequests.push(req.url())
  })

  try {
    const journal = player.page.locator('.session-journal-panel')
    await expect(journal).toBeVisible()
    await expect(journal).toContainText('No public quests or facts recorded yet.')
    await expect(journal).toContainText('No character knowledge recorded yet.')
    await expect(player.page.locator('.session-world-panel')).toHaveCount(0)

    const worldPanel = page.locator('.session-world-panel')
    await expect(worldPanel).toBeVisible()
    await expect(page.locator('.session-journal-panel')).toHaveCount(0)
    await worldPanel.getByRole('button', { name: 'Quick Add' }).click()
    const quickForm = worldPanel.locator('form')
    await expect(quickForm.getByRole('combobox', { name: 'Kind', exact: true }).locator('option'))
      .toHaveText(['Scene', 'NPC', 'Fact'])
    await quickForm.getByRole('combobox', { name: 'Kind', exact: true }).selectOption('fact')
    await quickForm.getByRole('textbox', { name: 'Description / Body' })
      .fill('The old bridge is unsafe after sunset.')
    const factCreated = page.waitForResponse((response) => (
      response.request().method() === 'POST'
      && response.url().endsWith(`/sessions/${sessionId}/runtime/entries`)
    ))
    await quickForm.getByRole('button', { name: 'Create Entry' }).click()
    await responseJson(await factCreated)
    await expect(journal).toContainText('The old bridge is unsafe after sunset.')

    const contextCard = worldPanel.locator('.runtime-context-card')
    await contextCard.getByRole('button', { name: 'Edit Context' }).click()
    await contextCard.getByRole('textbox', { name: 'Current Situation' })
      .fill('The party pauses beside the old bridge.')
    const contextUpdated = page.waitForResponse((response) => (
      response.request().method() === 'PATCH'
      && response.url().endsWith(`/sessions/${sessionId}/runtime/context`)
    ))
    await contextCard.getByRole('button', { name: 'Save Context' }).click()
    await responseJson(await contextUpdated)
    await expect(contextCard).toContainText('The party pauses beside the old bridge.')

    await createActiveRuntimeEntry(request, activePrefix, {
      key: `p6b-public-quest-${sessionId}`,
      kind: 'quest',
      title: 'Recover the Bell of Dawn',
      body: 'The villagers openly ask the party to recover the bell.',
      visibility: 'public',
    })
    await createActiveRuntimeEntry(request, activePrefix, {
      key: `p6b-public-scene-${sessionId}`,
      kind: 'scene',
      title: 'Public Scene Outside Journal',
      body: 'Visible Runtime, but the Journal only lists public quests and facts.',
      visibility: 'public',
    })
    await createActiveRuntimeEntry(request, activePrefix, {
      key: `p6b-dm-secret-${sessionId}`,
      kind: 'secret',
      title: 'DM Only Bell Curse',
      body: 'This must never reach the Player browser.',
      visibility: 'dm_only',
      dmNotes: 'P6-B private DM note',
    })
    await createActiveRuntimeEntry(request, activePrefix, {
      key: `p6b-own-knowledge-${sessionId}`,
      kind: 'secret',
      title: 'Your Character Knows the Bell Sign',
      body: 'The sign matches a memory from your character history.',
      visibility: 'character',
      characterIds: [characterOne.id],
    })
    await createActiveRuntimeEntry(request, activePrefix, {
      key: `p6b-other-knowledge-${sessionId}`,
      kind: 'secret',
      title: 'Other Character Knows the Hidden Name',
      body: 'Only the other active Character may know this.',
      visibility: 'character',
      characterIds: [characterTwo.id],
    })

    await expect(journal).toContainText('Recover the Bell of Dawn')
    await expect(journal).toContainText('Your Character Knows the Bell Sign')
    await expect(journal).not.toContainText('Public Scene Outside Journal')
    await expect(journal).not.toContainText('DM Only Bell Curse')
    await expect(journal).not.toContainText('P6-B private DM note')
    await expect(journal).not.toContainText('Other Character Knows the Hidden Name')

    const playerEntries = await json<RuntimeEntry[]>(await request.get(
      `${activePrefix}/runtime/entries`,
      { headers: { Authorization: `Bearer ${playerOne.access_token}` } },
    ))
    expect(playerEntries.map((entry) => entry.title)).toEqual(expect.arrayContaining([
      'Recover the Bell of Dawn',
      'Your Character Knows the Bell Sign',
    ]))
    expect(playerEntries.map((entry) => entry.title)).not.toContain('DM Only Bell Curse')
    expect(playerEntries.map((entry) => entry.title)).not.toContain(
      'Other Character Knows the Hidden Name',
    )
    for (const entry of playerEntries) {
      expect(entry).not.toHaveProperty('dm_notes')
      expect(entry).not.toHaveProperty('character_recipient_ids')
      expect(entry).not.toHaveProperty('needs_review')
      expect(entry).not.toHaveProperty('provenance_json')
    }

    expect(playerRuntimeRequests.some((url) => url.endsWith('/runtime/entries'))).toBe(true)
    expect(playerRuntimeRequests.some((url) => url.includes('/runtime/context'))).toBe(false)
    expect(playerRuntimeRequests.some((url) => url.includes('/runtime/overrides'))).toBe(false)
    expect(playerRuntimeRequests.some((url) => url.includes('/adventure'))).toBe(false)

    await player.page.reload()
    await expect(player.page.locator('.session-journal-panel')).toContainText(
      'Your Character Knows the Bell Sign',
    )
    await expect(player.page.locator('.session-journal-panel')).not.toContainText(
      'Other Character Knows the Hidden Name',
    )

    await page.reload()
    await expect(page.locator('.session-world-panel .runtime-context-card')).toContainText(
      'The party pauses beside the old bridge.',
    )
  } finally {
    await player.context.close()
  }
})
