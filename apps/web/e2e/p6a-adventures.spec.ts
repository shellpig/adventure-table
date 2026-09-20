import { expect, test, type APIRequestContext, type Page } from './support/roomTest'
import {
  addPlayerSeat,
  addSeat,
  createCampaign,
  enterAsMember,
  importCharacter,
  json,
  startSession,
  type Lobby,
} from './support/quickCombat'

const ONE_PIXEL_PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Zl1sAAAAASUVORK5CYII=',
  'base64',
)
const NARRATION = 'P6-A: the empty Campaign still narrates without any Adventure.'

type AdventureDefinition = { id: string; name: string; status: string }
type AdventureEntry = {
  id: string
  kind: string
  title: string | null
  visibility: string
  assets: { role: string; asset: { id: string; visibility: string } }[]
}
type AttachedAdventure = { adventure_id: string; name: string }
type TableEvent = { id: string }
type RollRequestResponse = { requests: unknown[] } | Record<string, unknown>
type CombatView = { id: string; status: string }

async function createFinalizedAdventure(
  request: APIRequestContext,
  roomId: string,
  name: string,
): Promise<AdventureDefinition> {
  const created = await json<AdventureDefinition>(await request.post(`/api/rooms/${roomId}/adventures`, {
    data: { name },
  }))
  return json<AdventureDefinition>(await request.post(
    `/api/rooms/${roomId}/adventures/${created.id}/finalize`,
  ))
}

function entryRow(page: Page, title: string) {
  return page.locator('.adventure-entry').filter({ hasText: title })
}

// The create/edit entry form; each entry row also carries an upload form with its own
// Visibility select, so the entry form is scoped by its Kind select.
function entryForm(page: Page) {
  return page.locator('form.room-form').filter({ has: page.getByRole('combobox', { name: 'Kind', exact: true }) })
}

async function addEntry(
  page: Page,
  options: { kind: string; title: string; visibility?: 'public' | 'dm_only'; readAloud?: string },
) {
  const form = entryForm(page)
  await form.getByRole('combobox', { name: 'Kind', exact: true }).selectOption(options.kind)
  await form.getByRole('textbox', { name: 'Title (optional)', exact: true }).fill(options.title)
  if (options.visibility) {
    await form.getByRole('combobox', { name: 'Visibility', exact: true }).selectOption(options.visibility)
  }
  if (options.readAloud) {
    await form.getByRole('textbox', { name: 'Read aloud text', exact: true }).fill(options.readAloud)
  }
  await form.getByRole('button', { name: 'Add Entry', exact: true }).click()
  await expect(entryRow(page, options.title)).toBeVisible()
}

test('P6-A Journey: manual Adventure with entries and image, finalize, multi-attach, detach, empty-Campaign regression', async ({
  page,
  request,
  roomContext,
}) => {
  test.setTimeout(180_000)
  const { roomId } = roomContext

  // A.1 Room workspace → Adventures → create with only a Name.
  await page.goto(`/rooms/${roomId}`)
  await page.getByRole('link', { name: 'Open Adventures' }).click()
  await expect(page).toHaveURL(new RegExp(`/rooms/${roomId}/adventures/?$`))
  await page.getByRole('textbox', { name: 'Adventure name' }).fill('P6-A Crypt of Echoes')
  await page.getByRole('button', { name: 'Create Adventure' }).click()
  const card = page.locator('.adventure-card').filter({ hasText: 'P6-A Crypt of Echoes' })
  await expect(card).toContainText('Draft')

  // Editor: scene (public, read-aloud), secret (dm_only), suggested check.
  await card.getByRole('link', { name: 'Open' }).click()
  await expect(page.getByRole('heading', { name: 'P6-A Crypt of Echoes', level: 1 })).toBeVisible()
  await addEntry(page, { kind: 'scene', title: 'Entrance Hall', readAloud: 'Dust hangs in the torchlight.' })
  await addEntry(page, { kind: 'secret', title: 'Hidden lever', visibility: 'dm_only' })
  const form = entryForm(page)
  await form.getByRole('combobox', { name: 'Kind', exact: true }).selectOption('suggested_check')
  await form.getByRole('textbox', { name: 'Title (optional)', exact: true }).fill('Notice the draft')
  await form.getByRole('spinbutton', { name: 'DC', exact: true }).fill('13')
  await form.getByRole('button', { name: 'Add Entry', exact: true }).click()
  await expect(entryRow(page, 'Notice the draft')).toBeVisible()
  await expect(entryRow(page, 'Hidden lever')).toContainText('DM only')

  // A.4 image upload → link → thumbnail through the authenticated blob fetch (no bare <img src>).
  const hall = entryRow(page, 'Entrance Hall')
  await hall.getByLabel('Image file (PNG / JPEG / WebP, max 20 MiB)').setInputFiles({
    name: 'hall.png',
    mimeType: 'image/png',
    buffer: ONE_PIXEL_PNG,
  })
  await hall.getByRole('button', { name: 'Upload & attach' }).click()
  const thumb = hall.locator('img.adventure-asset-thumb')
  await expect(thumb).toBeVisible()
  await expect(thumb).toHaveAttribute('src', /^blob:/)
  await expect(hall).toContainText('DM only')

  const listUrl = `/api/rooms/${roomId}/adventures`
  const adventures = await json<AdventureDefinition[]>(await request.get(listUrl))
  const crypt = adventures.find((item) => item.name === 'P6-A Crypt of Echoes')!
  const entries = await json<AdventureEntry[]>(await request.get(`${listUrl}/${crypt.id}/entries`))
  expect(entries.map((entry) => entry.kind)).toEqual(['scene', 'secret', 'suggested_check'])
  const hallEntry = entries.find((entry) => entry.title === 'Entrance Hall')!
  expect(hallEntry.assets).toHaveLength(1)
  expect(hallEntry.assets[0].role).toBe('image')
  expect(hallEntry.assets[0].asset.visibility).toBe('dm_only')

  // Finalize from the editor; finalized stays editable.
  await page.getByRole('button', { name: 'Finalize' }).click()
  await expect(page.getByText('Status: Finalized')).toBeVisible()
  await expect(entryForm(page).getByRole('button', { name: 'Add Entry', exact: true })).toBeVisible()

  // A.2 Campaign attaches two finalized Adventures, lists both, detaches one.
  const second = await createFinalizedAdventure(request, roomId, 'P6-A Second Adventure')
  const draft = await json<AdventureDefinition>(await request.post(listUrl, { data: { name: 'P6-A Draft Only' } }))
  const campaign = await createCampaign(request, roomId, 'P6-A Attached Campaign')
  await page.goto(`/rooms/${roomId}/campaigns/${campaign.id}`)
  await expect(page.getByRole('heading', { name: 'Attached Adventures' })).toBeVisible()
  const picker = page.getByRole('combobox', { name: 'Attach a finalized Adventure' })
  await expect(picker.locator('option')).not.toContainText(['P6-A Draft Only'])
  await picker.selectOption({ label: 'P6-A Crypt of Echoes' })
  await page.getByRole('button', { name: 'Attach', exact: true }).click()
  await expect(page.locator('.adventure-card').filter({ hasText: 'P6-A Crypt of Echoes' })).toBeVisible()
  await picker.selectOption({ label: 'P6-A Second Adventure' })
  await page.getByRole('button', { name: 'Attach', exact: true }).click()
  await expect(page.locator('.adventure-card').filter({ hasText: 'P6-A Second Adventure' })).toBeVisible()

  const attachUrl = `/api/rooms/${roomId}/campaigns/${campaign.id}/adventures`
  let attached = await json<AttachedAdventure[]>(await request.get(attachUrl))
  expect(attached.map((item) => item.adventure_id).sort()).toEqual([crypt.id, second.id].sort())
  const draftAttach = await request.post(attachUrl, { data: { adventure_id: draft.id } })
  expect(draftAttach.status()).toBe(409)
  const duplicate = await request.post(attachUrl, { data: { adventure_id: crypt.id } })
  expect(duplicate.status()).toBe(409)

  page.once('dialog', (dialog) => dialog.accept())
  await page.locator('.adventure-card').filter({ hasText: 'P6-A Crypt of Echoes' })
    .getByRole('button', { name: 'Detach' }).click()
  await expect(page.locator('.adventure-card').filter({ hasText: 'P6-A Crypt of Echoes' })).toHaveCount(0)
  await expect(page.locator('.adventure-card').filter({ hasText: 'P6-A Second Adventure' })).toBeVisible()
  attached = await json<AttachedAdventure[]>(await request.get(attachUrl))
  expect(attached.map((item) => item.adventure_id)).toEqual([second.id])
  const deleteAttached = await request.delete(`${listUrl}/${second.id}`)
  expect(deleteAttached.status()).toBe(409)

  // A.3 A Campaign with zero Adventures still runs: Start Session, narration, action, Check, Combat.
  const empty = await createCampaign(request, roomId, 'P6-A Empty Campaign')
  expect(await json<AttachedAdventure[]>(await request.get(
    `/api/rooms/${roomId}/campaigns/${empty.id}/adventures`,
  ))).toEqual([])
  const lobby = await json<Lobby>(await request.get(`/api/rooms/${roomId}/campaigns/${empty.id}/lobby`))
  expect(lobby.caller_access_session_id).not.toBeNull()
  await addSeat(request, roomId, empty.id, 'dm', lobby.caller_access_session_id!, 'P6-A')
  const playerGrant = await enterAsMember(request, roomContext, 'P6-A Player')
  const character = await importCharacter(request)
  const playerSeat = await addPlayerSeat(request, roomId, empty.id, character, playerGrant.access_session_id, 'P6-A')
  const sessionId = await startSession(page, roomId, empty.id)
  const prefix = `/api/rooms/${roomId}/campaigns/${empty.id}/sessions/${sessionId}`
  await page.getByRole('combobox', { name: 'Type', exact: true }).selectOption('narration')
  await page.getByPlaceholder(/Type here/).fill(NARRATION)
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.getByText(NARRATION, { exact: true })).toBeVisible()
  await json<TableEvent>(await request.post(`${prefix}/exploration`, {
    headers: { Authorization: `Bearer ${playerGrant.access_token}` },
    data: { kind: 'action', text: 'The Player pokes the empty world.', subject_seat_id: playerSeat.id },
  }))
  await json<RollRequestResponse>(await request.post(`${prefix}/checks`, {
    data: { target_seat_ids: [playerSeat.id], request_type: 'ability', ability_ref: 'wis', dc: 10 },
  }))
  const combat = await json<CombatView>(await request.post(`${prefix}/combat/start`, {
    data: { include_active_party: true, idempotency_key: `p6a-empty-${sessionId}` },
  }))
  expect(combat.status).toBe('initiative_pending')
})

test('P6-A member sees no Adventures authority in the UI and the API hides them', async ({
  browser,
  request,
  roomContext,
}) => {
  const { roomId } = roomContext
  const adventure = await createFinalizedAdventure(request, roomId, 'P6-A Member Blind')
  const member = await enterAsMember(request, roomContext, 'P6-A Member')
  const memberHeaders = { Authorization: `Bearer ${member.access_token}` }
  const bare = request as APIRequestContext

  const listed = await bare.get(`/api/rooms/${roomId}/adventures`, { headers: memberHeaders })
  expect(listed.status()).toBe(404)
  const entries = await bare.get(`/api/rooms/${roomId}/adventures/${adventure.id}/entries`, { headers: memberHeaders })
  expect(entries.status()).toBe(404)

  const context = await browser.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL ?? 'http://127.0.0.1:4173' })
  const memberPage = await context.newPage()
  await memberPage.goto('/')
  await memberPage.evaluate(
    ({ room }) => {
      window.localStorage.setItem('adventure-table.recent-rooms.v1', JSON.stringify([room]))
      window.localStorage.setItem('adventure-table.locale', 'en')
      window.sessionStorage.setItem('adventure-table.active-room.v1', room.roomId)
    },
    {
      room: {
        roomId,
        code: roomContext.code,
        name: roomContext.name,
        accessToken: member.access_token,
        authority: member.authority,
      },
    },
  )
  const requests: string[] = []
  memberPage.on('request', (req) => {
    if (req.url().includes('/api/rooms/')) requests.push(req.url())
  })
  await memberPage.goto(`/rooms/${roomId}/adventures`)
  await expect(memberPage.getByText('Only the Room owner or DM can manage Adventures.')).toBeVisible()
  await memberPage.goto(`/rooms/${roomId}/adventures/${adventure.id}`)
  await expect(memberPage.getByText('Only the Room owner or DM can manage Adventures.')).toBeVisible()
  expect(requests.filter((url) => url.includes('/adventures'))).toEqual([])
  await context.close()
})
