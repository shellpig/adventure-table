import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

import { TacticalSetupPanel } from './TacticalSetupPanel'
import { sessionCopy } from './sessionCopy'

import { recentRoomForId } from './roomStorage'

vi.mock('./roomStorage', () => ({
  recentRoomForId: vi.fn(),
}))

vi.mock('../../api/battleMaps', () => ({
  createBattleMap: vi.fn(),
  getBattleMap: vi.fn(),
  getSessionBattleMap: vi.fn().mockResolvedValue(null),
  listBattleMaps: vi.fn().mockResolvedValue([
    {
      id: 'map-1',
      room_id: 'room-1',
      name: 'Dungeon',
      source_kind: 'blank',
      image_asset_id: null,
      width_cells: 20,
      height_cells: 20,
      revision: 1,
      created_at: '2026-10-04T00:00:00Z',
      updated_at: '2026-10-04T00:00:00Z',
      archived_at: null,
    },
  ]),
  listSessionBattleMaps: vi.fn().mockResolvedValue([
    {
      id: 'map-1',
      room_id: 'room-1',
      name: 'Dungeon',
      source_kind: 'blank',
      image_asset_id: null,
      width_cells: 20,
      height_cells: 20,
      revision: 1,
      created_at: '2026-10-04T00:00:00Z',
      updated_at: '2026-10-04T00:00:00Z',
      archived_at: null,
    },
  ]),
}))

vi.mock('../../api/tacticalCombat', () => ({
  startTacticalCombat: vi.fn(),
}))

const defaultProps = {
  roomId: 'room-1',
  campaignId: 'camp-1',
  sessionId: 'sess-1',
  token: 'test-token',
  onError: vi.fn(),
  refresh: vi.fn(),
  onClose: vi.fn(),
}

describe('TacticalSetupPanel', () => {
  it('provides accessible aria-label on the close button', () => {
    vi.mocked(recentRoomForId).mockReturnValue({
      roomId: 'room-1',
      code: 'R1',
      name: 'Room 1',
      authority: 'owner',
      accessToken: 'test-token',
    })

    for (const locale of ['zh-TW', 'en'] as const) {
      const copy = sessionCopy(locale)
      const html = renderToStaticMarkup(
        <TacticalSetupPanel
          {...defaultProps}
          copy={copy}
          locale={locale}
        />,
      )

      expect(html).toContain(`aria-label="${copy.close}"`)
    }
  })

  it('hides create and edit controls for non-authority while retaining start control', () => {
    vi.mocked(recentRoomForId).mockReturnValue({
      roomId: 'room-1',
      code: 'R1',
      name: 'Room 1',
      authority: 'member',
      accessToken: 'test-token',
    })

    const copy = sessionCopy('en')
    const html = renderToStaticMarkup(
      <TacticalSetupPanel
        {...defaultProps}
        copy={copy}
        locale="en"
      />,
    )

    // Edit and create controls hidden
    expect(html).not.toContain('data-testid="tactical-create-map"')
    expect(html).not.toContain('tactical-edit-map-')

    // Start controls still present
    expect(html).toContain('data-testid="tactical-start-confirm"')
    expect(html).toContain(copy.tacticalStartBlank)
  })

  it('shows create and edit controls for owner/dm authority', () => {
    vi.mocked(recentRoomForId).mockReturnValue({
      roomId: 'room-1',
      code: 'R1',
      name: 'Room 1',
      authority: 'dm',
      accessToken: 'test-token',
    })

    const copy = sessionCopy('en')
    const html = renderToStaticMarkup(
      <TacticalSetupPanel
        {...defaultProps}
        copy={copy}
        locale="en"
      />,
    )

    expect(html).toContain('data-testid="tactical-create-map"')
    expect(html).toContain('data-testid="tactical-start-confirm"')
  })

  it('M07-D F14: lists and reads maps through the session read-only routes', async () => {
    const { readFileSync } = await import('node:fs')
    const source = readFileSync(new URL('./TacticalSetupPanel.tsx', import.meta.url), 'utf8')
    expect(source).toContain('listSessionBattleMaps(roomId, campaignId, sessionId, token)')
    expect(source).toContain('getSessionBattleMap(roomId, campaignId, sessionId, mapId, token)')
    expect(source).not.toContain('listBattleMaps(roomId, token)')
    expect(source).not.toContain('getBattleMap(roomId, mapId, token)')
  })
})
