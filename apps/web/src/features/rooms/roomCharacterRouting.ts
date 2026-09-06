import { recentRoomForId } from './roomStorage'

export const ACTIVE_ROOM_STORAGE_KEY = 'adventure-table.active-room.v1'
const UUID_PATTERN = '[0-9a-fA-F-]{36}'

export function roomContextIdFromPath(pathname: string): string | null {
  const match = pathname.match(new RegExp(`^/rooms/(${UUID_PATTERN})(?:/|$)`))
  return match?.[1] ?? null
}

export function roomScopedApiPath(pathname: string, roomId: string): string | null {
  if (pathname === '/api/characters' || pathname.startsWith('/api/characters/')) {
    return `/api/rooms/${roomId}${pathname.slice('/api'.length)}`
  }
  if (
    pathname === '/api/character-builder' ||
    pathname.startsWith('/api/character-builder/')
  ) {
    return `/api/rooms/${roomId}${pathname.slice('/api'.length)}`
  }
  return null
}

export function roomScopedFrontendPath(pathname: string, roomId: string): string | null {
  if (pathname === '/characters' || pathname.startsWith('/characters/')) {
    return `/rooms/${roomId}${pathname}`
  }
  if (pathname === '/character-builder' || pathname.startsWith('/character-builder/')) {
    return `/rooms/${roomId}${pathname}`
  }
  return null
}

function safeSessionStorage(): Storage | undefined {
  if (typeof window === 'undefined') return undefined
  try {
    return window.sessionStorage
  } catch {
    return undefined
  }
}

export function rememberActiveRoom(
  roomId: string,
  storage: Storage | undefined = safeSessionStorage(),
): void {
  try {
    storage?.setItem(ACTIVE_ROOM_STORAGE_KEY, roomId)
  } catch {
    // Losing the navigation convenience must never lose Room access itself.
  }
}

export function activeRoomId(
  storage: Storage | undefined = safeSessionStorage(),
): string | null {
  try {
    return storage?.getItem(ACTIVE_ROOM_STORAGE_KEY) ?? null
  } catch {
    return null
  }
}

export function legacyWebRoomRedirectPath(pathname: string): string {
  const roomId = activeRoomId()
  return roomId ? roomScopedFrontendPath(pathname, roomId) ?? '/' : '/'
}

let installed = false

export function installRoomCharacterRouting(): void {
  if (installed || typeof window === 'undefined') return
  installed = true

  const currentRoomId = roomContextIdFromPath(window.location.pathname)
  if (currentRoomId) rememberActiveRoom(currentRoomId)

  const originalFetch = window.fetch.bind(window)
  window.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const roomId = roomContextIdFromPath(window.location.pathname)
    if (!roomId || typeof input !== 'string') return originalFetch(input, init)

    const source = new URL(input, window.location.origin)
    if (source.origin !== window.location.origin) return originalFetch(input, init)
    const scopedPath = roomScopedApiPath(source.pathname, roomId)
    if (!scopedPath) return originalFetch(input, init)

    const recent = recentRoomForId(roomId)
    const headers = new Headers(init?.headers)
    if (recent?.accessToken && !headers.has('Authorization')) {
      headers.set('Authorization', `Bearer ${recent.accessToken}`)
    }
    const target = `${scopedPath}${source.search}${source.hash}`
    return originalFetch(target, { ...init, headers })
  }) as typeof window.fetch

  document.addEventListener('click', (event) => {
    if (
      event.defaultPrevented ||
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    ) {
      return
    }
    const target = event.target
    if (!(target instanceof Element)) return
    const anchor = target.closest<HTMLAnchorElement>('a[href]')
    if (!anchor || anchor.target || anchor.hasAttribute('download')) return

    const roomId = roomContextIdFromPath(window.location.pathname)
    if (!roomId) return
    const url = new URL(anchor.href, window.location.origin)
    if (url.origin !== window.location.origin) return
    const scoped = roomScopedFrontendPath(url.pathname, roomId)
    if (!scoped) return

    event.preventDefault()
    window.location.assign(`${scoped}${url.search}${url.hash}`)
  })
}
