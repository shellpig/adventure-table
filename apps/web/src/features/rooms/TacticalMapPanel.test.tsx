import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { CombatDetailView } from '../../api/combat'
import type { TableEvent } from '../../api/sessions'
import * as tacticalApi from '../../api/tacticalCombat'
import { TacticalMapPanel, doorIsHidden } from './TacticalMapPanel'
import { sessionCopy } from './sessionCopy'

vi.mock('../../api/tacticalCombat', async (importOriginal) => {
  const original = await importOriginal<typeof tacticalApi>()
  return {
    ...original,
    getCombatBoard: vi.fn(),
    placeCombatant: vi.fn(),
    updateBoardDoorState: vi.fn(),
  }
})

vi.mock('../../api/battleMaps', () => ({
  getBattleMap: vi.fn().mockResolvedValue(null),
}))

const baseCombat = {
  id: 'combat-1',
  mode: 'tactical',
  status: 'active',
  round_number: 1,
  current_turn_entry_id: 'entry-1',
  revision: 1,
  entries: [
    {
      id: 'entry-1',
      display_name: 'Goblin',
      status: 'active',
      turn_order: 1,
    },
  ],
} as unknown as CombatDetailView

const baseBoard: tacticalApi.CombatBoardView = {
  combat_id: 'combat-1',
  width_cells: 10,
  height_cells: 10,
  grid_pixel_size: 40,
  grid_offset_x: 0,
  grid_offset_y: 0,
  has_image: false,
  source_battle_map_id: null,
  source_battle_map_revision: null,
  runtime_revision: 5,
  walls: [],
  doors: [],
  terrain: [],
  drawings: [],
  positions: [],
}

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

describe('TacticalMapPanel', () => {
  it('renders map panel without combat header/initiative/log duplication', () => {
    // Static render: board loads async, so we check the shell structure.
    const html = renderToStaticMarkup(<TacticalMapPanel {...props} isCurrentDm={true} />)
    expect(html).toContain('data-testid="tactical-map-panel"')
    expect(html).toContain('data-testid="tactical-board-wrap"')
    // No duplicate combat chrome: TacticalStage is gone.
    expect(html).not.toContain('data-testid="tactical-stage"')
    expect(html).not.toContain('data-testid="tactical-combat-log"')
    expect(html).not.toContain('data-testid="tactical-initiative-row"')
  })

  it('shows Token tool for DM', () => {
    const html = renderToStaticMarkup(<TacticalMapPanel {...props} isCurrentDm={true} />)
    expect(html).toContain('data-testid="tactical-token-mode"')
  })

  it('hides Token tool and placement for Player', () => {
    const html = renderToStaticMarkup(<TacticalMapPanel {...props} isCurrentDm={false} />)
    expect(html).not.toContain('data-testid="tactical-token-mode"')
    expect(html).not.toContain('data-testid="tactical-placement"')
  })

  it('doorIsHidden uses board hidden_origin for DM (real board shape)', () => {
    // Real board shape from server DM projection.
    const hiddenDoor: tacticalApi.BoardDoorView = {
      door_id: 'door-hidden-1',
      x1: 2,
      y1: 2,
      x2: 2,
      y2: 3,
      state: 'closed',
      revealed: false,
      hidden_origin: true,
    }
    const publicDoor: tacticalApi.BoardDoorView = {
      door_id: 'door-public-1',
      x1: 5,
      y1: 5,
      x2: 5,
      y2: 6,
      state: 'open',
      revealed: true,
      hidden_origin: false,
    }
    expect(doorIsHidden(hiddenDoor, null)).toBe(true)
    expect(doorIsHidden(publicDoor, null)).toBe(false)
  })

  it('doorIsHidden falls back to battle map definition when hidden_origin absent', () => {
    const door: tacticalApi.BoardDoorView = {
      door_id: 'door-1',
      x1: 2,
      y1: 2,
      x2: 2,
      y2: 3,
      state: 'closed',
      revealed: false,
    }
    const battleMap = {
      doors: [{ id: 'door-1', visibility: 'hidden' }],
    } as never
    expect(doorIsHidden(door, battleMap)).toBe(true)
    expect(doorIsHidden(door, null)).toBe(false)
  })
})
