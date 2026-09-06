import type { RoomAccessGrant, RoomAuthority } from '../../api/rooms'

export const RECENT_ROOMS_STORAGE_KEY = 'adventure-table.recent-rooms.v1'
const MAX_RECENT_ROOMS = 5

export type RoomStorage = {
  getItem: (key: string) => string | null
  setItem: (key: string, value: string) => void
}

export type RecentRoom = {
  roomId: string
  code: string
  name: string
  accessToken: string
  authority: RoomAuthority
}

function isRecentRoom(value: unknown): value is RecentRoom {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Partial<RecentRoom>
  return (
    typeof candidate.roomId === 'string' &&
    typeof candidate.code === 'string' &&
    typeof candidate.name === 'string' &&
    typeof candidate.accessToken === 'string' &&
    ['member', 'dm', 'owner'].includes(candidate.authority ?? '')
  )
}

export function browserRoomStorage(): RoomStorage | undefined {
  if (typeof window === 'undefined') return undefined
  try {
    return window.localStorage
  } catch {
    return undefined
  }
}

export function readRecentRooms(storage: RoomStorage | undefined = browserRoomStorage()): RecentRoom[] {
  if (!storage) return []
  try {
    const parsed: unknown = JSON.parse(storage.getItem(RECENT_ROOMS_STORAGE_KEY) ?? '[]')
    if (!Array.isArray(parsed)) return []
    return parsed.filter(isRecentRoom).slice(0, MAX_RECENT_ROOMS)
  } catch {
    return []
  }
}

export function persistRoomGrant(
  grant: RoomAccessGrant,
  storage: RoomStorage | undefined = browserRoomStorage(),
): RecentRoom {
  const recent: RecentRoom = {
    roomId: grant.room.id,
    code: grant.room.code,
    name: grant.room.name,
    accessToken: grant.access_token,
    authority: grant.authority,
  }
  if (!storage) return recent

  const next = [
    recent,
    ...readRecentRooms(storage).filter((room) => room.roomId !== recent.roomId),
  ].slice(0, MAX_RECENT_ROOMS)
  try {
    storage.setItem(RECENT_ROOMS_STORAGE_KEY, JSON.stringify(next))
  } catch {
    // Private browsing / storage quota failures must not block Room entry.
  }
  return recent
}

export function recentRoomForId(
  roomId: string,
  storage: RoomStorage | undefined = browserRoomStorage(),
): RecentRoom | null {
  return readRecentRooms(storage).find((room) => room.roomId === roomId) ?? null
}
