import { describe, expect, it } from 'vitest'

import { campaignPermissions, roomCampaignRouteFromPath } from './RoomCampaignPage'

const ROOM_ID = '10000000-0000-4000-8000-000000000001'
const CAMPAIGN_ID = '20000000-0000-4000-8000-000000000001'

describe('P2-C Room Campaign routes', () => {
  it('parses Room-scoped Campaign list and detail paths', () => {
    expect(roomCampaignRouteFromPath(`/rooms/${ROOM_ID}/campaigns`)).toEqual({
      roomId: ROOM_ID,
      campaignId: null,
    })
    expect(roomCampaignRouteFromPath(`/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}`)).toEqual({
      roomId: ROOM_ID,
      campaignId: CAMPAIGN_ID,
    })
    expect(roomCampaignRouteFromPath(`/rooms/${ROOM_ID}/characters`)).toBeNull()
  })

  it('keeps lifecycle Owner-only while allowing DM roster management', () => {
    expect(campaignPermissions('owner')).toEqual({ isOwner: true, canManageRoster: true })
    expect(campaignPermissions('dm')).toEqual({ isOwner: false, canManageRoster: true })
    expect(campaignPermissions('member')).toEqual({ isOwner: false, canManageRoster: false })
    expect(campaignPermissions(null)).toEqual({ isOwner: false, canManageRoster: false })
  })
})
