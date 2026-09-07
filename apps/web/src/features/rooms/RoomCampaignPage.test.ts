import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

import { campaignCopy } from './campaignCopy'
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

  it('keeps Campaign presentation copy product-facing and localized', () => {
    const en = campaignCopy('en')
    const zhTw = campaignCopy('zh-TW')

    expect(Object.values(en).join(' ')).not.toContain('P2-C')
    expect(Object.values(zhTw).join(' ')).not.toContain('P2-C')
    expect(en.levelLabel).toBe('Level')
    expect(zhTw.levelLabel).toBe('等級')
    expect(en.removeConfirm).not.toBe(zhTw.removeConfirm)
  })

  it('requires confirmation before deleting a roster entry', () => {
    const source = readFileSync(new URL('./RoomCampaignPage.tsx', import.meta.url), 'utf8')

    expect(source).toContain('window.confirm(copy.removeConfirm)')
    expect(source).not.toContain('· Lv{character.level}')
  })
})
