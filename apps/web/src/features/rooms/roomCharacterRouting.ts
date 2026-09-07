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
    // Losing navigation convenience must never lose Room access itself.
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
