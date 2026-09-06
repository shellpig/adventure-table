import { readFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { test as base, type APIRequestContext } from '@playwright/test'

import { openCharacterWorkshop, type E2ERoomContext } from './room'

export { expect } from '@playwright/test'
export type * from '@playwright/test'
export { openCharacterWorkshop }

const RECENT_ROOMS_STORAGE_KEY = 'adventure-table.recent-rooms.v1'
const ACTIVE_ROOM_STORAGE_KEY = 'adventure-table.active-room.v1'
const ROOM_CONTEXT_PATH = resolve(
  dirname(fileURLToPath(import.meta.url)),
  '..',
  '..',
  'test-results',
  'p2-room-context.json',
)
const HTTP_METHODS = new Set(['delete', 'fetch', 'get', 'head', 'patch', 'post', 'put'])

type RequestOptions = {
  headers?: Record<string, string>
  [key: string]: unknown
}

async function readRoomContext(): Promise<E2ERoomContext> {
  const raw = await readFile(ROOM_CONTEXT_PATH, 'utf8')
  return JSON.parse(raw) as E2ERoomContext
}

function scopeApiUrl(url: unknown, roomId: string): unknown {
  if (typeof url !== 'string') return url
  if (url === '/api/characters' || url.startsWith('/api/characters/') || url.startsWith('/api/characters?')) {
    return `/api/rooms/${roomId}${url.slice('/api'.length)}`
  }
  if (
    url === '/api/character-builder'
    || url.startsWith('/api/character-builder/')
    || url.startsWith('/api/character-builder?')
  ) {
    return `/api/rooms/${roomId}${url.slice('/api'.length)}`
  }
  return url
}

function roomRequestProxy(request: APIRequestContext, room: E2ERoomContext): APIRequestContext {
  return new Proxy(request, {
    get(target, property, receiver) {
      const value = Reflect.get(target, property, receiver)
      if (typeof property !== 'string' || !HTTP_METHODS.has(property) || typeof value !== 'function') {
        return typeof value === 'function' ? value.bind(target) : value
      }
      return (url: unknown, options: RequestOptions = {}) => {
        const headers = {
          Authorization: `Bearer ${room.accessToken}`,
          ...(options.headers ?? {}),
        }
        return value.call(target, scopeApiUrl(url, room.roomId), { ...options, headers })
      }
    },
  }) as APIRequestContext
}

export const test = base.extend<{ roomContext: E2ERoomContext }>({
  roomContext: [
    async ({ page }, use) => {
      const roomContext = await readRoomContext()
      await page.goto('/')
      await page.evaluate(
        ({ recentKey, activeKey, room }) => {
          window.localStorage.setItem(recentKey, JSON.stringify([room]))
          window.sessionStorage.setItem(activeKey, room.roomId)
        },
        {
          recentKey: RECENT_ROOMS_STORAGE_KEY,
          activeKey: ACTIVE_ROOM_STORAGE_KEY,
          room: roomContext,
        },
      )
      await use(roomContext)
    },
    { auto: true },
  ],
  request: async ({ request, roomContext }, use) => {
    await use(roomRequestProxy(request, roomContext))
  },
})
