import { describe, expect, it } from 'vitest'

import { RoomApiError } from '../../api/rooms'
import { isStaleRecentRoom } from './RoomWorkspacePage'

describe('Room workspace stale Recent Rooms detection', () => {
  it.each([
    new RoomApiError(404, 'room_not_found', 'room not found'),
    // Room hard delete cascades its access sessions, so the stored token is simply unknown.
    new RoomApiError(403, 'room_access_denied', 'Room credentials were rejected'),
  ])('forgets the entry for %o', (cause) => {
    expect(isStaleRecentRoom(cause)).toBe(true)
  })

  it.each([
    new RoomApiError(401, 'room_access_revoked', 'revoked'),
    new RoomApiError(403, 'room_scope_mismatch', 'other room'),
    new RoomApiError(429, 'room_access_throttled', 'slow down'),
    new RoomApiError(500, 'internal_error', 'boom'),
    new Error('network'),
    null,
  ])('keeps the entry for %o', (cause) => {
    expect(isStaleRecentRoom(cause)).toBe(false)
  })
})
