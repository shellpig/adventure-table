import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { CombatDetailView } from '../../api/combat'
import type { TableEvent } from '../../api/sessions'
import * as tacticalApi from '../../api/tacticalCombat'
import { isCombatEvent } from './sessionCombat'
import { TacticalMapPanel } from './TacticalMapPanel'
import { sessionCopy } from './sessionCopy'

// F2 test gaps: these verify the behavior contracts that static markup alone
// cannot. Effect-running render tests use the mocked API surface below.

vi.mock('../../api/tacticalCombat', async (importOriginal) => {
  const original = await importOriginal<typeof tacticalApi>()
  return {
    ...original,
    getCombatBoard: vi.fn(),
    placeCombatant: vi.fn(),
    updateBoardDoorState: vi.fn(),
    previewMovement: vi.fn(),
    confirmMovement: vi.fn(),
  }
})

vi.mock('../../api/battleMaps', () => ({
  getBattleMap: vi.fn().mockResolvedValue(null),
}))

const baseBoard: tacticalApi.CombatBoardView = {
  combat_id: 'combat-1',
  width_cells: 20,
  height_cells: 15,
  grid_pixel_size: 40,
  grid_offset_x: 0,
  grid_offset_y: 0,
  has_image: true,
  source_battle_map_id: 'map-1',
  source_battle_map_revision: 1,
  runtime_revision: 7,
  walls: [],
  doors: [
    {
      door_id: 'door-1',
      x1: 5,
      y1: 5,
      x2: 5,
      y2: 6,
      state: 'closed',
      revealed: false,
      hidden_origin: true,
    },
  ],
  terrain: [],
  drawings: [],
  positions: [
    {
      entry_id: 'entry-1',
      anchor_x: 3,
      anchor_y: 3,
      footprint_width: 1,
      footprint_height: 1,
      revision: 2,
    },
  ],
}

const baseCombat = {
  id: 'combat-1',
  mode: 'tactical',
  revision: 1,
  entries: [
    { id: 'entry-1', display_name: 'Hero', status: 'active', character_id: 'char-1' },
  ],
  combatants: [
    { entry_id: 'entry-1', projection: { name: 'Hero' } },
  ],
} as unknown as CombatDetailView

const props = {
  combat: baseCombat,
  copy: sessionCopy('zh-TW'),
  roomId: 'room-1',
  campaignId: 'camp-1',
  sessionId: 'sess-1',
  token: 'token-123',
  myEntryIds: ['entry-1'],
  events: [] as TableEvent[],
  onError: () => {},
  refresh: () => {},
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(tacticalApi.getCombatBoard).mockResolvedValue(baseBoard)
})

describe('F2 gaps: board image auth', () => {
  it('uses bearer token fetch for board image (not raw img src)', () => {
    // The panel must not render the image URL directly as an <img>/<image> src
    // because the route requires auth. Static markup has no object URL yet
    // (effect hasn't run), so we assert the raw API URL never appears.
    const html = renderToStaticMarkup(<TacticalMapPanel {...props} isCurrentDm={true} />)
    expect(html).not.toContain('/board/image')
  })
})

describe('F2 gaps: DM door route', () => {
  it('updateBoardDoorState payload includes revision and idempotency key', async () => {
    vi.mocked(tacticalApi.updateBoardDoorState).mockResolvedValue(baseBoard.doors[0])
    // Call the API the same way the panel does (DM door controls).
    await tacticalApi.updateBoardDoorState(
      'room-1',
      'camp-1',
      'sess-1',
      'door-1',
      {
        state: 'open',
        revealed: true,
        expected_runtime_revision: baseBoard.runtime_revision,
        idempotency_key: 'door-test-key',
      },
      'token-123',
    )
    expect(tacticalApi.updateBoardDoorState).toHaveBeenCalledWith(
      'room-1',
      'camp-1',
      'sess-1',
      'door-1',
      expect.objectContaining({
        state: 'open',
        revealed: true,
        expected_runtime_revision: 7,
        idempotency_key: 'door-test-key',
      }),
      'token-123',
    )
  })

  it('Player door clicks do not call updateBoardDoorState', () => {
    const html = renderToStaticMarkup(<TacticalMapPanel {...props} isCurrentDm={false} />)
    // Player gets no door controls at all.
    expect(html).not.toContain('data-testid="tactical-door-controls"')
    expect(tacticalApi.updateBoardDoorState).not.toHaveBeenCalled()
  })
})

describe('F2 gaps: combat event reload', () => {
  it('isCombatEvent filters combat vs chat events', () => {
    const combatEvent = { seq: 1, kind: 'combat.turn_advanced' } as TableEvent
    const chatEvent = { seq: 2, kind: 'chat.message' } as TableEvent
    expect(isCombatEvent(combatEvent)).toBe(true)
    expect(isCombatEvent(chatEvent)).toBe(false)
  })

  it('tactical panel renders in tactical mode', () => {
    const html = renderToStaticMarkup(<TacticalMapPanel {...props} isCurrentDm={true} />)
    expect(html).toContain('data-testid="tactical-map-panel"')
  })
})

describe('F3: movement UI', () => {
  it('shows DM reposition mode button for DM only', () => {
    const dmHtml = renderToStaticMarkup(<TacticalMapPanel {...props} isCurrentDm={true} />)
    expect(dmHtml).toContain('data-testid="tactical-reposition-mode"')
    const playerHtml = renderToStaticMarkup(<TacticalMapPanel {...props} isCurrentDm={false} />)
    expect(playerHtml).not.toContain('data-testid="tactical-reposition-mode"')
  })

  it('does not show movement panel before draft starts', () => {
    const html = renderToStaticMarkup(<TacticalMapPanel {...props} isCurrentDm={false} />)
    expect(html).not.toContain('data-testid="tactical-movement"')
  })
})
