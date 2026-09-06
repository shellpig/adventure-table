import { expect, type Page } from '@playwright/test'
import { randomUUID } from 'node:crypto'

const RECENT_ROOMS_STORAGE_KEY = 'adventure-table.recent-rooms.v1'
const LOCALE_STORAGE_KEY = 'adventure-table.locale'
const E2E_ROOM_PASSWORD = 'p2-e2e-room-pass'

export type E2ERoomContext = {
  roomId: string
  code: string
  name: string
  accessToken: string
  authority: 'member' | 'dm' | 'owner'
}

type RoomGrant = {
  room: {
    id: string
    code: string
    name: string
  }
  authority: E2ERoomContext['authority']
  access_token: string
}

type StoredRoomContext = {
  roomId: string
  code: string
  name: string
  accessToken: string
  authority: E2ERoomContext['authority']
}

async function readStoredRoomContext(page: Page): Promise<E2ERoomContext | null> {
  return page.evaluate((storageKey) => {
    const parsed = JSON.parse(window.localStorage.getItem(storageKey) ?? '[]') as StoredRoomContext[]
    return parsed[0] ?? null
  }, RECENT_ROOMS_STORAGE_KEY)
}

export async function enterRoom(
  page: Page,
  options: { name?: string; displayName?: string } = {},
): Promise<E2ERoomContext> {
  const name = options.name ?? `E2E Room ${randomUUID().slice(0, 8)}`

  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Adventure Table' })).toBeVisible()

  const storedLocale = await page.evaluate(
    (storageKey) => window.localStorage.getItem(storageKey),
    LOCALE_STORAGE_KEY,
  )
  if (!storedLocale) {
    await page.getByTestId('locale-option-en').click()
    await expect(page.locator('html')).toHaveAttribute('lang', 'en')
  }

  await expect(page.getByRole('heading', { name: /^(Start at the table|先進入跑團房間)$/ })).toBeVisible()
  await page.getByLabel(/^(Room name|Room 名稱)$/).fill(name)
  await page.getByLabel(/^(Room password|Room 密碼)$/).first().fill(E2E_ROOM_PASSWORD)
  if (options.displayName) {
    await page.getByLabel(/^(Display name \(optional\)|顯示名稱（選填）)$/).first().fill(options.displayName)
  }

  const responsePromise = page.waitForResponse((response) => {
    const url = new URL(response.url())
    return url.pathname === '/api/rooms' && response.request().method() === 'POST'
  })
  await page.getByRole('button', { name: /^(Create Room|建立 Room)$/ }).click()
  const response = await responsePromise
  if (!response.ok()) {
    throw new Error(`Room bootstrap failed: ${response.status()} ${await response.text()}`)
  }
  const grant = (await response.json()) as RoomGrant

  await expect(page.getByRole('heading', { name: /^(Room created|Room 已建立)$/ })).toBeVisible()
  const stored = await readStoredRoomContext(page)
  expect(stored?.roomId).toBe(grant.room.id)
  expect(stored?.accessToken).toBe(grant.access_token)

  return {
    roomId: grant.room.id,
    code: grant.room.code,
    name: grant.room.name,
    accessToken: grant.access_token,
    authority: grant.authority,
  }
}

export async function openCharacterWorkshop(
  page: Page,
  roomContext?: E2ERoomContext,
): Promise<void> {
  const context = roomContext ?? await readStoredRoomContext(page)
  expect(context).not.toBeNull()

  const hasRoomContext = await page.evaluate(
    ({ storageKey, roomId, accessToken }) => {
      const parsed = JSON.parse(window.localStorage.getItem(storageKey) ?? '[]') as StoredRoomContext[]
      return parsed.some(
        (room) => room.roomId === roomId && room.accessToken === accessToken,
      )
    },
    {
      storageKey: RECENT_ROOMS_STORAGE_KEY,
      roomId: context!.roomId,
      accessToken: context!.accessToken,
    },
  )
  expect(hasRoomContext).toBe(true)

  // P2-A compatibility seam. P2-B changes this one route to
  // /rooms/{roomId}/characters when Character APIs become Room-scoped.
  await page.goto('/characters')
  await expect(page).toHaveURL(/\/characters\/?$/)
}
