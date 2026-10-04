import { expect, test, type APIRequestContext, type Page } from './support/roomTest'
import {
  ACTIVE_ROOM_STORAGE_KEY,
  addPlayerSeat,
  addSeat,
  createCampaign,
  enterAsMember,
  importCharacter,
  json,
  LOCALE_STORAGE_KEY,
  PLAYWRIGHT_BASE_URL,
  RECENT_ROOMS_STORAGE_KEY,
  startSession,
  type Lobby,
} from './support/quickCombat'
import { mapPanel, token, type Board } from './support/tactical'

const CELL_SIZE = 40
// NOTE: the library-editor template menu loads one page of 50 templates, so
// Test 1 searches for off-first-page templates (e.g. Goblin, ~#150) through
// the menu search box instead of relying on menu order.
const GOBLIN_REF = 'srd5.1:monster:goblin'
const ACOLYTE_REF = 'srd5.1:monster:acolyte'

type CombatEntry = {
  id: string
  subject_kind: string
  display_name: string
  monster_instance_id: string | null
}

type CombatDetail = {
  entries: CombatEntry[]
  combatants: Array<{ entry_id: string }>
}

test.use({ actionTimeout: 15_000 })

type MonsterTemplate = {
  ref: string
  revision: number
  name: string
}

type MapPlacement = {
  id: string
  template_key: string | null
  custom_template_id: string | null
  anchor_x: number
  anchor_y: number
  visibility: 'public' | 'hidden'
  sort_order: number
}

type BattleMapDetail = {
  id: string
  revision: number
  monster_placements: MapPlacement[]
}

type BattleMapSummary = {
  id: string
  name: string
}

async function mapPoint(page: Page, x: number, y: number) {
  return page
    .getByTestId('map-editor-canvas')
    .locator('svg[data-testid="battle-map"]')
    .evaluate(
      (svg, [cx, cy, size]) => {
        const point = new DOMPoint(cx * size, cy * size).matrixTransform(
          (svg as SVGSVGElement).getScreenCTM()!,
        )
        return { x: point.x, y: point.y }
      },
      [x, y, CELL_SIZE] as const,
    )
}

function editorTokens(page: Page, extra = '') {
  return page.getByTestId('map-editor-canvas').locator(`[data-testid="battle-map-token"]${extra}`)
}

async function createCustomTemplate(
  request: APIRequestContext,
  roomId: string,
  name: string,
  size: string,
): Promise<MonsterTemplate> {
  return json<MonsterTemplate>(
    await request.post(`/api/rooms/${roomId}/monster-library/custom`, {
      data: { name, armor_class: 13, max_hp: 20, size },
    }),
  )
}

async function createBlankMap(
  request: APIRequestContext,
  roomId: string,
  name: string,
  width: number,
  height: number,
): Promise<{ id: string; revision: number }> {
  return json<{ id: string; revision: number }>(
    await request.post(`/api/rooms/${roomId}/battle-maps`, {
      data: { name, source_kind: 'blank', width_cells: width, height_cells: height },
    }),
  )
}

async function putPlacements(
  request: APIRequestContext,
  roomId: string,
  mapId: string,
  expectedRevision: number,
  placements: Array<{
    template_key?: string | null
    custom_template_id?: string | null
    anchor_x: number
    anchor_y: number
    visibility: 'public' | 'hidden'
  }>,
): Promise<BattleMapDetail> {
  return json<BattleMapDetail>(
    await request.put(`/api/rooms/${roomId}/battle-maps/${mapId}/monster-placements`, {
      data: {
        expected_revision: expectedRevision,
        placements: placements.map((p, index) => ({
          id: null,
          template_key: p.template_key ?? null,
          custom_template_id: p.custom_template_id ?? null,
          anchor_x: p.anchor_x,
          anchor_y: p.anchor_y,
          visibility: p.visibility,
          sort_order: index,
        })),
      },
    }),
  )
}

async function openLibraryEditor(page: Page, roomId: string, mapName: string) {
  await page.goto(`/rooms/${roomId}/battle-maps`)
  await expect(page.getByRole('heading', { name: 'Map Library', level: 1 })).toBeVisible()
  const card = page.locator('.battle-map-card', { hasText: mapName })
  await expect(card).toBeVisible()
  await card.getByRole('button', { name: 'Edit Map' }).click()
  await expect(page.getByTestId('map-editor-canvas')).toBeVisible()
}

async function enterMonsterMode(page: Page) {
  await page.getByTestId('map-editor-tool-monster').click()
  await expect(page.getByTestId('monster-placement-panel')).toBeVisible()
  const picker = page.getByTestId('monster-placement-template-picker')
  await expect
    .poll(async () => picker.locator('option').count(), { timeout: 15_000 })
    .toBeGreaterThan(1)
}

async function searchTemplate(page: Page, text: string) {
  const search = page.getByTestId('monster-placement-template-search')
  await expect(search).toBeVisible()
  await search.fill(text)
}

async function placeTemplateAt(
  page: Page,
  ref: string,
  visibility: 'public' | 'hidden',
  x: number,
  y: number,
) {
  const picker = page.getByTestId('monster-placement-template-picker')
  await expect(picker.locator(`option[value="${ref}"]`)).toHaveCount(1)
  await picker.selectOption(ref)
  await page.getByTestId('monster-placement-visibility-picker').selectOption(visibility)
  await page.getByTestId('map-editor-canvas').scrollIntoViewIfNeeded()
  const at = await mapPoint(page, x + 0.5, y + 0.5)
  await page.mouse.click(at.x, at.y)
}

async function savePlacements(page: Page) {
  await page.getByTestId('monster-placement-save').click()
  await expect(page.getByTestId('monster-placement-save-message')).toHaveText(
    'Monster placements saved.',
  )
}

async function readDetailOrNull(
  request: APIRequestContext,
  prefix: string,
): Promise<CombatDetail | null> {
  const response = await request.get(`${prefix}/combat/detail`)
  expect(response.ok()).toBe(true)
  return (await response.json()) as CombatDetail | null
}

test('M07-C editor places a public built-in and a hidden custom monster, saves, and reopens with both', async ({
  page,
  request,
  roomContext,
}) => {
  test.setTimeout(180_000)
  const { roomId } = roomContext
  const customName = 'E2E M07C Hidden Horror A'
  const template = await createCustomTemplate(request, roomId, customName, 'Medium')
  expect(template.ref.startsWith('custom:')).toBe(true)

  const mapName = 'E2E M07C Lair A'
  await createBlankMap(request, roomId, mapName, 12, 10)

  // DM finds both monsters through the template search and places them.
  await openLibraryEditor(page, roomId, mapName)
  await enterMonsterMode(page)
  await searchTemplate(page, 'Goblin')
  await placeTemplateAt(page, GOBLIN_REF, 'public', 5, 2)
  await expect(editorTokens(page)).toHaveCount(1)
  await searchTemplate(page, 'Hidden Horror')
  await placeTemplateAt(page, template.ref, 'hidden', 4, 2)
  await expect(editorTokens(page)).toHaveCount(2)
  await expect(editorTokens(page, '[data-hidden="true"]')).toHaveCount(1)
  await savePlacements(page)

  // The saved placements carry the right source, position, and visibility.
  const listed = await json<BattleMapSummary[]>(
    await request.get(`/api/rooms/${roomId}/battle-maps`),
  )
  const mapId = listed.find((m) => m.name === mapName)!.id
  const saved = await json<BattleMapDetail>(
    await request.get(`/api/rooms/${roomId}/battle-maps/${mapId}`),
  )
  expect(saved.monster_placements).toHaveLength(2)
  const goblinPlacement = saved.monster_placements.find((p) => p.template_key === GOBLIN_REF)!
  expect(goblinPlacement).toMatchObject({ anchor_x: 5, anchor_y: 2, visibility: 'public' })
  const customPlacement = saved.monster_placements.find(
    (p) => p.custom_template_id === template.ref.replace(/^custom:/, ''),
  )!
  expect(customPlacement).toMatchObject({ anchor_x: 4, anchor_y: 2, visibility: 'hidden' })

  // Reopening the editor still shows both monsters, and the built-in is named.
  await page.getByTestId('editor-back-link').click()
  await expect(page.getByRole('heading', { name: 'Map Library', level: 1 })).toBeVisible()
  await openLibraryEditor(page, roomId, mapName)
  await enterMonsterMode(page)
  await expect(editorTokens(page)).toHaveCount(2)
  await editorTokens(page, `[data-entry-id="${goblinPlacement.id}"]`).click()
  const selection = page.getByTestId('monster-placement-selection')
  await expect(selection).toHaveAttribute('data-placement-id', goblinPlacement.id)
  await expect(selection).toContainText('Goblin')

  // Saved placements resolve even when off the menu front page: the fresh
  // menu does not offer Goblin until searched, and a template grown to Large
  // after saving still renders its 2x2 footprint on reopen.
  const picker = page.getByTestId('monster-placement-template-picker')
  await expect(picker.locator(`option[value="${GOBLIN_REF}"]`)).toHaveCount(0)
  await searchTemplate(page, 'Goblin')
  await expect(picker.locator(`option[value="${GOBLIN_REF}"]`)).toHaveCount(1)
  await json(
    await request.patch(
      `/api/rooms/${roomId}/monster-library/custom/${template.ref.replace(/^custom:/, '')}`,
      { data: { expected_revision: template.revision, size: 'Large' } },
    ),
  )
  await openLibraryEditor(page, roomId, mapName)
  await enterMonsterMode(page)
  await expect(editorTokens(page)).toHaveCount(2)
  const grownRect = editorTokens(page, `[data-entry-id="${customPlacement.id}"] rect`)
  await expect(grownRect).toHaveAttribute('width', String(2 * CELL_SIZE))
  await expect(grownRect).toHaveAttribute('height', String(2 * CELL_SIZE))
})

test('M07-C grown template blocks load-with-monsters until the DM fixes the placement in the editor', async ({
  page,
  request,
  roomContext,
}) => {
  test.setTimeout(240_000)
  const { roomId } = roomContext
  const customName = 'AA E2E M07C Conflict Horror B'
  const template = await createCustomTemplate(request, roomId, customName, 'Medium')
  const templateId = template.ref.replace(/^custom:/, '')

  const mapName = 'E2E M07C Lair B'
  const created = await createBlankMap(request, roomId, mapName, 12, 10)
  await putPlacements(request, roomId, created.id, created.revision, [
    { template_key: GOBLIN_REF, anchor_x: 5, anchor_y: 2, visibility: 'public' },
    { custom_template_id: templateId, anchor_x: 4, anchor_y: 2, visibility: 'hidden' },
  ])

  // The custom template grows to Large after the placements were saved, so its
  // 2x2 footprint now overlaps the Goblin at (5, 2).
  const grown = await json<MonsterTemplate>(
    await request.patch(`/api/rooms/${roomId}/monster-library/custom/${templateId}`, {
      data: { expected_revision: template.revision, size: 'Large' },
    }),
  )
  expect(grown.revision).toBeGreaterThan(template.revision)

  const campaign = await createCampaign(request, roomId, 'M07-C Conflict Campaign')
  const lobby = await json<Lobby>(
    await request.get(`/api/rooms/${roomId}/campaigns/${campaign.id}/lobby`),
  )
  await addSeat(request, roomId, campaign.id, 'dm', lobby.caller_access_session_id!, 'M07-C')
  const sessionId = await startSession(page, roomId, campaign.id)
  const prefix = `/api/rooms/${roomId}/campaigns/${campaign.id}/sessions/${sessionId}`

  // DM tries "Load with monsters": the panel lists the DM-only problem, no combat starts.
  await page.getByTestId('tactical-start-open').click()
  await page.getByTestId(`tactical-map-${created.id}`).getByRole('radio').check()
  await expect(page.getByTestId('tactical-load-with-monsters')).not.toBeChecked()
  await page.getByTestId('tactical-load-with-monsters').check()
  await page.getByTestId('tactical-start-confirm').click()
  const problems = page.getByTestId('tactical-load-problems')
  await expect(problems).toBeVisible()
  await expect(problems.getByRole('heading', { name: 'Monster placement problems (DM only)' })).toBeVisible()
  await expect
    .poll(async () => problems.locator('li[data-problem-code="overlapping_placement"]').count())
    .toBeGreaterThan(0)
  expect(await readDetailOrNull(request, prefix)).toBeNull()
  await expect(mapPanel(page)).toHaveCount(0)
  await expect(page.getByTestId('tactical-start-confirm')).toBeVisible()

  // DM fixes the placement inside the session editor UI: move the grown custom
  // monster to (8, 2) and save.
  const before = await json<BattleMapDetail>(
    await request.get(`/api/rooms/${roomId}/battle-maps/${created.id}`),
  )
  const customPlacement = before.monster_placements.find(
    (p) => p.custom_template_id === templateId,
  )!
  await page.getByTestId(`tactical-edit-map-${created.id}`).click()
  await expect(page.getByTestId('map-editor-canvas')).toBeVisible()
  await enterMonsterMode(page)
  await editorTokens(page, `[data-entry-id="${customPlacement.id}"]`).click()
  await expect(page.getByTestId('monster-placement-selection')).toHaveAttribute(
    'data-placement-id',
    customPlacement.id,
  )
  await page.getByTestId('map-editor-canvas').scrollIntoViewIfNeeded()
  const target = await mapPoint(page, 8.5, 2.5)
  await page.mouse.click(target.x, target.y)
  await savePlacements(page)
  await page.getByRole('button', { name: 'Close' }).click()

  // Retrying "Load with monsters" now starts combat with both monsters on the DM board.
  await expect(page.getByTestId('tactical-load-with-monsters')).toBeChecked()
  await page.getByTestId('tactical-start-confirm').click()
  await expect(mapPanel(page)).toBeVisible()
  const detail = await readDetailOrNull(request, prefix)
  expect(detail).not.toBeNull()
  expect(detail!.entries).toHaveLength(2)
  for (const entry of detail!.entries) {
    await expect(token(page, entry.id)).toBeVisible()
  }
})

test('M07-C players never see hidden map monsters in DOM, network, or API until revealed', async ({
  browser,
  page,
  request,
  roomContext,
}) => {
  test.setTimeout(240_000)
  const { roomId } = roomContext
  const hiddenName = 'AA E2E M07C Veiled Horror C'
  const template = await createCustomTemplate(request, roomId, hiddenName, 'Medium')
  const templateId = template.ref.replace(/^custom:/, '')

  const mapName = 'E2E M07C Lair C'
  const created = await createBlankMap(request, roomId, mapName, 12, 10)
  await putPlacements(request, roomId, created.id, created.revision, [
    { template_key: GOBLIN_REF, anchor_x: 2, anchor_y: 2, visibility: 'public' },
    { custom_template_id: templateId, anchor_x: 6, anchor_y: 2, visibility: 'hidden' },
  ])

  const campaign = await createCampaign(request, roomId, 'M07-C Secrecy Campaign')
  const lobby = await json<Lobby>(
    await request.get(`/api/rooms/${roomId}/campaigns/${campaign.id}/lobby`),
  )
  await addSeat(request, roomId, campaign.id, 'dm', lobby.caller_access_session_id!, 'M07-C')
  // Seats (DM + Player) are fixed before the Session starts, mirroring a real
  // table: a seat added after Start cannot see the Session until Late Join.
  const playerGrant = await enterAsMember(request, roomContext, 'M07-C Watcher')
  const character = await importCharacter(request)
  await addPlayerSeat(request, roomId, campaign.id, character, playerGrant.access_session_id)
  const sessionId = await startSession(page, roomId, campaign.id)
  const prefix = `/api/rooms/${roomId}/campaigns/${campaign.id}/sessions/${sessionId}`
  const sessionUrl = `/rooms/${roomId}/campaigns/${campaign.id}/sessions/${sessionId}`

  // A second browser context watches every session GET the Player client makes.
  const playerContext = await browser.newContext({ baseURL: PLAYWRIGHT_BASE_URL })
  const playerPage = await playerContext.newPage()
  await playerPage.goto('/')
  await playerPage.evaluate(
    ({ recentKey, activeKey, localeKey, room }) => {
      window.localStorage.setItem(recentKey, JSON.stringify([room]))
      window.localStorage.setItem(localeKey, 'en')
      window.sessionStorage.setItem(activeKey, room.roomId)
    },
    {
      recentKey: RECENT_ROOMS_STORAGE_KEY,
      activeKey: ACTIVE_ROOM_STORAGE_KEY,
      localeKey: LOCALE_STORAGE_KEY,
      room: {
        roomId,
        code: roomContext.code,
        name: roomContext.name,
        accessToken: playerGrant.access_token,
        authority: playerGrant.authority,
      },
    },
  )
  const playerGets: Array<{ url: string; body: string }> = []
  playerPage.on('response', (response) => {
    void (async () => {
      try {
        if (response.request().method() !== 'GET') return
        const url = new URL(response.url())
        if (!url.pathname.includes(`/sessions/${sessionId}/`)) return
        if (!url.pathname.includes('/combat') && !url.pathname.includes('/events')) return
        playerGets.push({ url: url.pathname, body: await response.text() })
      } catch {
        // Non-text or failed responses carry no monster data to assert on.
      }
    })()
  })
  await playerPage.goto(sessionUrl)
  await expect(playerPage.getByRole('heading', { name: 'Active Session', level: 1 })).toBeVisible()
  await expect(playerPage.getByText('Session not found.')).toHaveCount(0)

  try {
    // DM starts with monsters through the real setup UI.
    await page.getByTestId('tactical-start-open').click()
    await page.getByTestId(`tactical-map-${created.id}`).getByRole('radio').check()
    await page.getByTestId('tactical-load-with-monsters').check()
    await page.getByTestId('tactical-start-confirm').click()
    await expect(mapPanel(page)).toBeVisible()

    const dmDetail = await readDetailOrNull(request, prefix)
    expect(dmDetail).not.toBeNull()
    const dmMonsters = dmDetail!.entries.filter((e) => e.subject_kind === 'monster')
    expect(dmMonsters).toHaveLength(2)
    const hiddenEntry = dmDetail!.entries.find((e) => e.display_name === hiddenName)!
    const publicEntry = dmDetail!.entries.find((e) => e.id !== hiddenEntry.id && e.subject_kind === 'monster')!
    expect(publicEntry.display_name).toBe('Goblin')
    const hiddenInstanceId = hiddenEntry.monster_instance_id!
    expect(hiddenInstanceId).toBeTruthy()
    await expect(token(page, hiddenEntry.id)).toBeVisible()
    await expect(token(page, publicEntry.id)).toBeVisible()

    // Fresh Player polls after combat started carry only the public monster.
    await playerPage.reload()
    await expect(playerPage.getByRole('heading', { name: 'Active Session', level: 1 })).toBeVisible()
    await expect(mapPanel(playerPage)).toBeVisible()
    await expect(mapPanel(playerPage).getByTestId('battle-map-token')).toHaveCount(1)
    await expect(token(playerPage, publicEntry.id)).toBeVisible()
    await expect(token(playerPage, hiddenEntry.id)).toHaveCount(0)
    // The Player sees their own hero plus exactly one monster (the public Goblin).
    await expect(playerPage.locator('.session-combat__card')).toHaveCount(2)
    await expect(
      playerPage.locator('.session-combat__card', { hasText: 'Goblin' }),
    ).toBeVisible()
    await expect(
      playerPage.locator('.session-combat__card', { hasText: hiddenName }),
    ).toHaveCount(0)
    await expect(playerPage.getByText(hiddenName)).toHaveCount(0)

    const urls = playerGets.map((entry) => entry.url)
    expect(urls.some((u) => u.endsWith('/combat/detail'))).toBe(true)
    expect(urls.some((u) => u.endsWith('/combat/board'))).toBe(true)
    expect(playerGets.length).toBeGreaterThan(0)
    for (const entry of playerGets) {
      expect(entry.body, entry.url).not.toContain(hiddenEntry.id)
      expect(entry.body, entry.url).not.toContain(hiddenInstanceId)
      expect(entry.body, entry.url).not.toContain(hiddenName)
    }

    const playerHeaders = { Authorization: `Bearer ${playerGrant.access_token}` }
    const playerDetail = await json<CombatDetail>(
      await request.get(`${prefix}/combat/detail`, { headers: playerHeaders }),
    )
    const playerMonsters = playerDetail.entries.filter((e) => e.subject_kind === 'monster')
    expect(playerMonsters).toHaveLength(1)
    expect(playerMonsters[0].display_name).toBe('Goblin')
    expect(playerDetail.combatants).toHaveLength(2)
    expect(playerDetail.combatants.some((c) => c.entry_id === hiddenEntry.id)).toBe(false)
    const playerBoard = await json<Board>(
      await request.get(`${prefix}/combat/board`, { headers: playerHeaders }),
    )
    expect(playerBoard.positions).toHaveLength(1)
    expect(playerBoard.positions[0].entry_id).toBe(publicEntry.id)

    // DM reveals the hidden monster through the real combat UI; the Player sees it.
    const revealButton = page.locator(
      `[data-monster-controls="${hiddenEntry.id}"] [data-monster-visibility]`,
    )
    await expect(revealButton).toHaveText('Show to Players')
    await revealButton.click()
    await expect(revealButton).toHaveText('Hide from Players')
    await expect
      .poll(async () => {
        const after = await json<CombatDetail>(
          await request.get(`${prefix}/combat/detail`, { headers: playerHeaders }),
        )
        return after.entries.filter((e) => e.subject_kind === 'monster').length
      })
      .toBe(2)
    await expect(token(playerPage, hiddenEntry.id)).toBeVisible()
    await expect(
      playerPage.locator('.session-combat__card', { hasText: hiddenName }),
    ).toBeVisible()
  } finally {
    await playerContext.close()
  }
})

test('M07-C loading map only starts combat without any monsters', async ({
  page,
  request,
  roomContext,
}) => {
  test.setTimeout(240_000)
  const { roomId } = roomContext
  const template = await createCustomTemplate(request, roomId, 'AA E2E M07C Unused Horror D', 'Medium')

  const mapName = 'E2E M07C Lair D'
  const created = await createBlankMap(request, roomId, mapName, 12, 10)
  await putPlacements(request, roomId, created.id, created.revision, [
    { template_key: GOBLIN_REF, anchor_x: 2, anchor_y: 2, visibility: 'public' },
    {
      custom_template_id: template.ref.replace(/^custom:/, ''),
      anchor_x: 6,
      anchor_y: 2,
      visibility: 'hidden',
    },
  ])

  const campaign = await createCampaign(request, roomId, 'M07-C Map Only Campaign')
  const lobby = await json<Lobby>(
    await request.get(`/api/rooms/${roomId}/campaigns/${campaign.id}/lobby`),
  )
  await addSeat(request, roomId, campaign.id, 'dm', lobby.caller_access_session_id!, 'M07-C')
  const sessionId = await startSession(page, roomId, campaign.id)
  const prefix = `/api/rooms/${roomId}/campaigns/${campaign.id}/sessions/${sessionId}`

  // Map-only is the default; starting this way must not spawn any monster.
  await page.getByTestId('tactical-start-open').click()
  await page.getByTestId(`tactical-map-${created.id}`).getByRole('radio').check()
  await expect(page.getByTestId('tactical-load-map-only')).toBeChecked()
  await page.getByTestId('tactical-start-confirm').click()
  await expect(mapPanel(page)).toBeVisible()

  const detail = await readDetailOrNull(request, prefix)
  expect(detail).not.toBeNull()
  expect(detail!.entries).toHaveLength(0)
  const board = await json<Board>(await request.get(`${prefix}/combat/board`))
  expect(board.positions).toHaveLength(0)
})

test('M07-C built-in monster names follow the UI locale in the placement picker', async ({
  page,
  request,
  roomContext,
}) => {
  test.setTimeout(180_000)
  const { roomId } = roomContext
  const mapName = 'E2E M07C Lair E'
  await createBlankMap(request, roomId, mapName, 12, 10)

  const setLocale = async (locale: string) => {
    await page.goto('/')
    await page.evaluate(
      ({ room, nextLocale }) => {
        window.localStorage.setItem('adventure-table.recent-rooms.v1', JSON.stringify([room]))
        window.localStorage.setItem('adventure-table.locale', nextLocale)
        window.sessionStorage.setItem('adventure-table.active-room.v1', room.roomId)
      },
      {
        room: {
          roomId,
          code: roomContext.code,
          name: roomContext.name,
          accessToken: roomContext.accessToken,
          authority: roomContext.authority,
        },
        nextLocale: locale,
      },
    )
  }

  const openPicker = async (editLabel: string, heading: string) => {
    await page.goto(`/rooms/${roomId}/battle-maps`)
    await expect(page.getByRole('heading', { name: heading, level: 1 })).toBeVisible()
    const card = page.locator('.battle-map-card', { hasText: mapName })
    await expect(card).toBeVisible()
    await card.getByRole('button', { name: editLabel }).click()
    await expect(page.getByTestId('map-editor-canvas')).toBeVisible()
    await enterMonsterMode(page)
  }

  await setLocale('zh-TW')
  await openPicker('編輯地圖', '地圖庫')
  await expect(
    page.getByTestId('monster-placement-template-picker').locator(`option[value="${ACOLYTE_REF}"]`),
  ).toHaveText('侍僧')

  await setLocale('en')
  await openPicker('Edit Map', 'Map Library')
  await expect(
    page.getByTestId('monster-placement-template-picker').locator(`option[value="${ACOLYTE_REF}"]`),
  ).toHaveText('Acolyte')
})
