import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

import { campaignCopy } from './campaignCopy'
import { campaignPermissions, roomCampaignRouteFromPath } from './RoomCampaignPage'

const ROOM_ID = '10000000-0000-4000-8000-000000000001'
const CAMPAIGN_ID = '20000000-0000-4000-8000-000000000001'

describe('Room Campaign routes', () => {
  it('parses Room-scoped Campaign list and detail paths without swallowing Lobby', () => {
    expect(roomCampaignRouteFromPath(`/rooms/${ROOM_ID}/campaigns`)).toEqual({
      roomId: ROOM_ID,
      campaignId: null,
    })
    expect(roomCampaignRouteFromPath(`/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}`)).toEqual({
      roomId: ROOM_ID,
      campaignId: CAMPAIGN_ID,
    })
    expect(roomCampaignRouteFromPath(`/rooms/${ROOM_ID}/campaigns/${CAMPAIGN_ID}/lobby`)).toBeNull()
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

    for (const phase of ['P2-C', 'P2-D', 'P2C', 'P2D']) {
      expect(Object.values(en).join(' ')).not.toContain(phase)
      expect(Object.values(zhTw).join(' ')).not.toContain(phase)
    }
    expect(en.levelLabel).toBe('Level')
    expect(zhTw.levelLabel).toBe('等級')
    expect(en.openLobby).toBe('Open Lobby')
    expect(zhTw.openLobby).toBe('進入大廳')
    expect(en.removeConfirm).not.toBe(zhTw.removeConfirm)
    expect(zhTw.statusActionActive).toBe('開始進行')
    expect(zhTw.statusActionCompleted).toBe('設為已完成')
    expect(zhTw.statusActionArchived).toBe('設為已封存')
    expect(en.statusActionActive).toBe('Start Campaign')
    expect(en.statusActionCompleted).toBe('Mark as Completed')
    expect(en.statusActionArchived).toBe('Archive')
  })

  it('requires confirmation before deleting a roster entry and gates Lobby entry to the current active Campaign', () => {
    const source = readFileSync(new URL('./RoomCampaignPage.tsx', import.meta.url), 'utf8')

    expect(source).toContain('window.confirm(copy.removeConfirm)')
    expect(source).toContain("campaign.status === 'active' && room?.active_campaign_id === campaign.id")
    expect(source).toContain('/lobby`}>{copy.openLobby}')
    expect(source).not.toContain('· Lv{character.level}')
  })
})
