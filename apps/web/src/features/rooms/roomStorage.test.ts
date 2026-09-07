import { describe, expect, it } from 'vitest'

import type { RoomAccessGrant } from '../../api/rooms'
import {
  forgetRecentRoom,
  RECENT_ROOMS_STORAGE_KEY,
  persistRoomGrant,
  readRecentRooms,
  type RoomStorage,
} from './roomStorage'

function memoryStorage(): RoomStorage & { values: Map<string, string> } {
  const values = new Map<string, string>()
  return {
    values,
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => {
      values.set(key, value)
    },
  }
}

const GRANT: RoomAccessGrant = {
  room: {
    id: '22222222-2222-4222-8222-222222222222',
    code: '0123456789',
    name: 'Sunday Table',
    created_at: '2026-09-06T08:00:00Z',
    updated_at: '2026-09-06T08:00:00Z',
  },
  authority: 'owner',
  access_session_id: '33333333-3333-4333-8333-333333333333',
  access_token: 'opaque-access-token',
  owner_key: 'raw-owner-key-must-not-persist',
  dm_key: 'raw-dm-key-must-not-persist',
}

describe('P2 recent Room storage', () => {
  it('persists only Room convenience data and opaque access token', () => {
    const storage = memoryStorage()
    persistRoomGrant(GRANT, storage)

    expect(readRecentRooms(storage)).toEqual([
      {
        roomId: GRANT.room.id,
        code: GRANT.room.code,
        name: GRANT.room.name,
        accessToken: GRANT.access_token,
        authority: 'owner',
      },
    ])

    const raw = storage.values.get(RECENT_ROOMS_STORAGE_KEY) ?? ''
    expect(raw).not.toContain(GRANT.owner_key ?? '')
    expect(raw).not.toContain(GRANT.dm_key ?? '')
    expect(raw).not.toContain('password')
    expect(raw).not.toContain(GRANT.access_session_id)
  })

  it('deduplicates a Room and keeps the latest access token', () => {
    const storage = memoryStorage()
    persistRoomGrant(GRANT, storage)
    persistRoomGrant({ ...GRANT, authority: 'member', access_token: 'new-token' }, storage)

    expect(readRecentRooms(storage)).toHaveLength(1)
    expect(readRecentRooms(storage)[0]).toMatchObject({
      roomId: GRANT.room.id,
      authority: 'member',
      accessToken: 'new-token',
    })
  })

  it('forgets a Room after Owner hard delete', () => {
    const storage = memoryStorage()
    persistRoomGrant(GRANT, storage)

    forgetRecentRoom(GRANT.room.id, storage)

    expect(readRecentRooms(storage)).toEqual([])
  })
})
