import { expect, type Page } from '@playwright/test'
import { randomUUID } from 'node:crypto'

const RECENT_ROOMS_STORAGE_KEY = 'adventure-table.recent-rooms.v1'
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

export async function enterRoom(
  page: Page,
  options: { name?: string; displayName?: string } = {},
): Promise<E2ERoomContext> {
  const name = options.name ?? `E2E Room ${randomUUID().slice(0, 8)}`

  await page.addInitScript(() => {
    window.localStorage.setItem('adventure-table.locale', 'en')
  })
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Adventure Table' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Start at the table' })).toBeVisible()

  await page.getByLabel('Room name').fill(name)
  await page.getByLabel('Room password').first().fill(E2E_ROOM_PASSWORD)
  if (options.displayName) {
    await page.getByLabel('Display name (optional)').first().fill(options.displayName)
  }

  const responsePromise = page.waitForResponse((response) => {
    const url = new URL(response.url())
    return url.pathname === '/api/rooms' && response.request().method() === 'POST'
  })
  await page.getByRole('button', { name: 'Create Room', exact: true }).click()
  const response = await responsePromise
  if (!response.ok()) {
    throw new Error(`Room bootstrap failed: ${response.status()} ${await response.text()}`)
  }
  const grant = (await response.json()) as RoomGrant

  await expect(page.getByRole('heading', { name: 'Room created' })).toBeVisible()
  const stored = await page.evaluate(
    ({ storageKey, roomId }) => {
      const parsed = JSON.parse(window.localStorage.getItem(storageKey) ?? '[]') as Array<{
        roomId?: string
        accessToken?: string
      }>
      return parsed.find((room) => room.roomId === roomId) ?? null
    },
    { storageKey: RECENT_ROOMS_STORAGE_KEY, roomId: grant.room.id },
  )
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
  roomContext: E2ERoomContext,
): Promise<void> {
  const hasRoomContext = await page.evaluate(
    ({ storageKey, roomId, accessToken }) => {
      const parsed = JSON.parse(window.localStorage.getItem(storageKey) ?? '[]') as Array<{
        roomId?: string
        accessToken?: string
      }>
      return parsed.some(
        (room) => room.roomId === roomId && room.accessToken === accessToken,
      )
    },
    {
      storageKey: RECENT_ROOMS_STORAGE_KEY,
      roomId: roomContext.roomId,
      accessToken: roomContext.accessToken,
    },
  )
  expect(hasRoomContext).toBe(true)

  // P2-A compatibility seam. P2-B changes this one route to
  // /rooms/{roomId}/characters when Character APIs become Room-scoped.
  await page.goto('/characters')
  await expect(page).toHaveURL(/\/characters\/?$/)
}
