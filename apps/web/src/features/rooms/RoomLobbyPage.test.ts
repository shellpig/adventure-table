import { describe, expect, it } from 'vitest'

import { roomLobbyRouteFromPath } from './RoomLobbyPage'
import { lobbyCopy } from './lobbyCopy'

const ROOM_ID = '10000000-0000-4000-8000-000000000001'
const CAMPAIGN_ID = '20000000-0000-4000-8000-000000000001'

describe('P2-D Lobby route and presentation', () => {
  it('recognizes only the Campaign Lobby route', () => {
    expect(roomLobbyRouteFromPath(`/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/lobby`)).toEqual({
      roomId: ROOM_ID,
      campaignId: CAMPAIGN_ID,
    })
    expect(roomLobbyRouteFromPath(`/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}`)).toBeNull()
    expect(roomLobbyRouteFromPath(`/rooms/${ROOM_ID}/sessions`)).toBeNull()
  })

  it('keeps internal phase names out of both locales', () => {
    for (const locale of ['zh-TW', 'en'] as const) {
      const rendered = JSON.stringify(lobbyCopy(locale))
      expect(rendered).not.toContain('P2-D')
      expect(rendered).not.toContain('P2D')
    }
  })
})
