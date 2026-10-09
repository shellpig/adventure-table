import { readFile } from 'node:fs/promises'

import { expect, test, type APIRequestContext } from './support/roomTest'
import {
  ACTIVE_ROOM_STORAGE_KEY,
  addPlayerSeat,
  addSeat,
  createCampaign,
  IMPORT_FIXTURE,
  json,
  LOCALE_STORAGE_KEY,
  pickSrdMonster,
  PLAYWRIGHT_BASE_URL,
  RECENT_ROOMS_STORAGE_KEY,
  type CharacterSummary,
  type Lobby,
  type RoomGrant,
} from './support/quickCombat'
import { mapPanel } from './support/tactical'

test.use({ actionTimeout: 15_000 })

type Headers = Record<string, string>

async function createRoom(
  request: APIRequestContext,
  name: string,
  password: string,
): Promise<{
  roomId: string
  code: string
  name: string
  ownerHeaders: Headers
}> {
  const created = await json<{
    room: { id: string; code: string; name: string }
    access_token: string
  }>(
    await request.post('/api/rooms', {
      data: { name, password, display_name: 'M07-D Owner' },
    }),
  )
  return {
    roomId: created.room.id,
    code: created.room.code,
    name: created.room.name,
    ownerHeaders: { Authorization: `Bearer ${created.access_token}` },
  }
}

test('M07-D member current DM reads session libraries while players are rejected', async ({
  browser,
  request,
}) => {
  test.setTimeout(240_000)
  // A fresh Room: the Owner authors a custom template and a blank map through
  // the management routes before any Session exists.
  const room = await createRoom(request, 'E2E M07D Session Room', 'm07d-room-pass')
  const { ownerHeaders } = room

  const customName = 'E2E M07D Session Horror'
  const template = await json<{ ref: string; revision: number }>(
    await request.post(`/api/rooms/${room.roomId}/monster-library/custom`, {
      headers: ownerHeaders,
      data: { name: customName, armor_class: 13, max_hp: 20, size: 'Medium' },
    }),
  )
  expect(template.ref.startsWith('custom:')).toBe(true)

  const createdMap = await json<{ id: string }>(
    await request.post(`/api/rooms/${room.roomId}/battle-maps`, {
      headers: ownerHeaders,
      data: { name: 'E2E M07D Session Map', source_kind: 'blank', width_cells: 12, height_cells: 10 },
    }),
  )
  const mapName = 'E2E M07D Session Map'
  const mapId = createdMap.id
  expect(mapId).toBeTruthy()

  const campaign = await createCampaign(request, room.roomId, 'M07-D Session Library Campaign', ownerHeaders)
  const lobby = await json<Lobby>(
    await request.get(`/api/rooms/${room.roomId}/campaigns/${campaign.id}/lobby`, {
      headers: ownerHeaders,
    }),
  )
  expect(lobby.caller_access_session_id).not.toBeNull()

  // The future DM enters with NO elevated key: plain member Room authority.
  // The Owner then assigns that member to the DM Seat via the public API
  // (Owner-only DM assignment; the target's member authority is kept).
  const memberDm = await json<RoomGrant>(
    await request.post('/api/rooms/enter', {
      data: { code: room.code, password: 'm07d-room-pass', display_name: 'M07-D Member DM' },
    }),
  )
  expect(memberDm.authority).toBe('member')
  await addSeat(
    request,
    room.roomId,
    campaign.id,
    'dm',
    memberDm.access_session_id,
    'M07-D',
    ownerHeaders,
  )

  // A plain member holds a Player Seat: in-Session but never the DM.
  const watcher = await json<RoomGrant>(
    await request.post('/api/rooms/enter', {
      data: { code: room.code, password: 'm07d-room-pass', display_name: 'M07-D Watcher' },
    }),
  )
  expect(watcher.authority).toBe('member')
  const envelope = await readFile(IMPORT_FIXTURE, 'utf8')
  const imported = await json<{ character_id: string | null; character_preview: { name: string } }>(
    await request.post(`/api/rooms/${room.roomId}/characters/import`, {
      headers: { ...ownerHeaders, 'Content-Type': 'application/json' },
      data: envelope,
    }),
  )
  expect(imported.character_id).not.toBeNull()
  const watcherCharacter: CharacterSummary = {
    id: imported.character_id!,
    name: imported.character_preview.name,
  }
  await addPlayerSeat(
    request,
    room.roomId,
    campaign.id,
    watcherCharacter,
    watcher.access_session_id,
    'M07-D',
    ownerHeaders,
  )

  // The member DM (member Room authority, current DM Seat controller) starts
  // the Session from the lobby on their own page: the Start control is
  // reachable because it follows the DM Seat binding, not Room authority.
  const dmContext = await browser.newContext({ baseURL: PLAYWRIGHT_BASE_URL })
  const dmPage = await dmContext.newPage()
  const libraryUrls: string[] = []
  dmPage.on('response', (response) => {
    const url = response.url()
    if (url.includes('/libraries/')) libraryUrls.push(url)
  })
  await dmPage.goto('/')
  await dmPage.evaluate(
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
        roomId: room.roomId,
        code: room.code,
        name: room.name,
        accessToken: memberDm.access_token,
        authority: memberDm.authority,
      },
    },
  )
  await dmPage.goto(`/rooms/${room.roomId}/campaigns/${campaign.id}/lobby`)
  await expect(dmPage.getByRole('heading', { name: 'Lobby & Seats', level: 1 })).toBeVisible()
  await dmPage.getByRole('button', { name: 'Start Session' }).click()
  await expect(dmPage).toHaveURL(
    new RegExp(`/rooms/${room.roomId}/campaigns/${campaign.id}/sessions/[0-9a-fA-F-]{36}/?$`),
  )
  await expect(dmPage.getByRole('heading', { name: 'Active Session', level: 1 })).toBeVisible()
  const sessionId = dmPage.url().match(/\/sessions\/([0-9a-fA-F-]{36})\/?$/)?.[1]
  expect(sessionId).toBeTruthy()
  const sessionBase =
    `/api/rooms/${room.roomId}/campaigns/${campaign.id}/sessions/${sessionId}/libraries`
  try {
    await dmPage.getByTestId('tactical-start-open').click()
    // The Room map library is visible through the Session read-only route.
    await expect(dmPage.locator('.tactical-setup__map-list', { hasText: mapName })).toBeVisible()

    // No authoring controls for a member-authority DM inside the Session.
    await expect(dmPage.getByTestId('tactical-create-map')).not.toBeVisible()
    await expect(dmPage.getByTestId(`tactical-edit-map-${mapId}`)).not.toBeVisible()

    // Start from the library map (map-only): the board then reads the map
    // definition through the Session route as well.
    await dmPage.getByRole('radio', { name: new RegExp(mapName) }).check()
    await dmPage.getByTestId('tactical-start-confirm').click()
    await expect(mapPanel(dmPage)).toBeVisible()
    // Custom templates are selectable through the Session read-only route.
    await pickSrdMonster(dmPage, customName)
  } finally {
    await dmContext.close()
  }

  // Every library request the Session UI made went through the Session
  // read-only routes, never the management routes (which never contain the
  // `/sessions/{sid}/libraries/` segment).
  expect(libraryUrls.length).toBeGreaterThan(0)
  for (const url of libraryUrls) {
    expect(url, url).toContain(`/sessions/${sessionId}/libraries/`)
  }
  expect(libraryUrls.some((url) => url.includes('/libraries/battle-maps'))).toBe(true)
  expect(libraryUrls.some((url) => url.includes('/libraries/monster-library'))).toBe(true)

  // The member DM reads all four Session routes (list + detail, maps and
  // monsters) with real IDs, including the built-in detail path.
  const dmHeaders = { Authorization: `Bearer ${memberDm.access_token}` }
  const mapList = await json<Array<{ id: string }>>(
    await request.get(`${sessionBase}/battle-maps`, { headers: dmHeaders }),
  )
  expect(mapList.map((item) => item.id)).toContain(mapId)
  const mapDetail = await json<{ id: string; name: string; width_cells: number; height_cells: number }>(
    await request.get(`${sessionBase}/battle-maps/${mapId}`, { headers: dmHeaders }),
  )
  expect(mapDetail.id).toBe(mapId)
  expect(mapDetail.name).toBe(mapName)
  expect(mapDetail.width_cells).toBe(12)
  expect(mapDetail.height_cells).toBe(10)
  const monsterList = await json<Array<{ ref: string }>>(
    await request.get(`${sessionBase}/monster-library`, {
      headers: dmHeaders,
      params: { source: 'custom' },
    }),
  )
  expect(monsterList.map((item) => item.ref)).toContain(template.ref)
  const customDetail = await json<{ ref: string; name: string }>(
    await request.get(`${sessionBase}/monster-library/${encodeURIComponent(template.ref)}`, {
      headers: dmHeaders,
    }),
  )
  expect(customDetail.ref).toBe(template.ref)
  expect(customDetail.name).toBe(customName)
  const builtinDetail = await json<{ ref: string; source_kind: string }>(
    await request.get(
      `${sessionBase}/monster-library/${encodeURIComponent('srd5.1:monster:goblin')}`,
      { headers: dmHeaders },
    ),
  )
  expect(builtinDetail.source_kind).toBe('builtin')

  // The member DM's Room authority was NOT promoted: every management
  // read/write stays rejected (battle-map routes hide existence with 404).
  // POST bodies are valid so the requests reach the permission check.
  const forbiddenCalls = [
    {
      method: 'GET' as const,
      url: `/api/rooms/${room.roomId}/monster-library`,
      body: undefined,
      expected: 403,
      code: 'monster_library_forbidden',
    },
    {
      method: 'POST' as const,
      url: `/api/rooms/${room.roomId}/monster-library/custom`,
      body: { name: 'E2E M07D Forbidden', armor_class: 10, max_hp: 10 },
      expected: 403,
      code: 'monster_library_forbidden',
    },
    {
      method: 'GET' as const,
      url: `/api/rooms/${room.roomId}/battle-maps`,
      body: undefined,
      expected: 404,
      code: 'battle_map_not_found',
    },
    {
      method: 'POST' as const,
      url: `/api/rooms/${room.roomId}/battle-maps`,
      body: { name: 'E2E M07D Forbidden', source_kind: 'blank', width_cells: 8, height_cells: 8 },
      expected: 404,
      code: 'battle_map_not_found',
    },
  ]
  for (const call of forbiddenCalls) {
    const response =
      call.method === 'GET'
        ? await request.get(call.url, { headers: dmHeaders })
        : await request.post(call.url, { headers: dmHeaders, data: call.body })
    expect(response.status(), `${call.method} ${call.url}`).toBe(call.expected)
    expect((await response.json())['error']['code'], `${call.method} ${call.url}`).toBe(call.code)
  }

  // Room library pages show the member DM no data and no authoring entries.
  const roomContext = await browser.newContext({ baseURL: PLAYWRIGHT_BASE_URL })
  const roomPage = await roomContext.newPage()
  await roomPage.goto('/')
  await roomPage.evaluate(
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
        roomId: room.roomId,
        code: room.code,
        name: room.name,
        accessToken: memberDm.access_token,
        authority: memberDm.authority,
      },
    },
  )
  try {
    await roomPage.goto(`/rooms/${room.roomId}`)
    await expect(roomPage.getByRole('link', { name: 'Open Monster Library' })).not.toBeVisible()
    await expect(roomPage.getByRole('link', { name: 'Open Map Library' })).not.toBeVisible()
    await roomPage.goto(`/rooms/${room.roomId}/monster-library`)
    await expect(
      roomPage.getByText('Only the Room owner or DM can manage the monster library.'),
    ).toBeVisible()
    await expect(roomPage.getByRole('button', { name: 'Create Custom Monster' })).not.toBeVisible()
    await roomPage.goto(`/rooms/${room.roomId}/battle-maps`)
    await expect(roomPage.getByTestId('map-library-forbidden')).toBeVisible()
    await expect(roomPage.getByRole('button', { name: 'Create Blank Map' })).not.toBeVisible()
  } finally {
    await roomContext.close()
  }

  // A Player-Seat member (in-Session but never the DM) learns nothing from
  // the Session library routes: every read is rejected with 403, using the
  // real map/template IDs.
  const memberHeaders = { Authorization: `Bearer ${watcher.access_token}` }
  for (const url of [
    `${sessionBase}/battle-maps`,
    `${sessionBase}/battle-maps/${mapId}`,
    `${sessionBase}/monster-library`,
    `${sessionBase}/monster-library/${encodeURIComponent(template.ref)}`,
  ]) {
    const response = await request.get(url, { headers: memberHeaders })
    expect(response.status(), url).toBe(403)
    expect((await response.json())['error']['code'], url).toBe('table_actor_unauthorized')
    expect(await response.text(), url).not.toContain(mapName)
    expect(await response.text(), url).not.toContain(customName)
  }
})
