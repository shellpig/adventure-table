import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { CombatDetailView } from '../../api/combat'
import type { TableEvent } from '../../api/sessions'
import type { TargetCheckResult } from '../../api/tacticalCombat'
import * as tacticalApi from '../../api/tacticalCombat'
import {
  aoeShapeNeedsAim,
  appendAnchor,
  cellClickAction,
  doorClickAction,
  dragCellsToAnchors,
  isLatestPreview,
  shouldReloadOnEvents,
  targetCheckBand,
  tokenClickAction,
} from './tacticalLogic'
import { TacticalMapPanel } from './TacticalMapPanel'
import { sessionCopy } from './sessionCopy'

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
  getSessionBattleMap: vi.fn().mockResolvedValue(null),
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

function targetCheckResult(overrides: Partial<TargetCheckResult>): TargetCheckResult {
  return {
    source_entry_id: 'entry-1',
    target_entry_id: 'entry-2',
    kind: 'attack',
    ref: 'longbow',
    legal: true,
    in_range: true,
    distance_feet: 60,
    range_band: 'normal',
    blocked: false,
    blocker_kind: null,
    requires_dm_adjudication: false,
    is_long_range: false,
    target_within_5ft: false,
    ...overrides,
  }
}

describe('tacticalLogic: cellClickAction', () => {
  it('placement mode places', () => {
    expect(cellClickAction({ kind: 'placement', entryId: 'e1' }, 3, 4)).toEqual({
      action: 'place',
      x: 3,
      y: 4,
    })
  })
  it('move mode adds an anchor', () => {
    expect(cellClickAction({ kind: 'move', entryId: 'e1' }, 3, 4)).toEqual({
      action: 'add-anchor',
      x: 3,
      y: 4,
    })
  })
  it('reposition mode sets the reposition target', () => {
    expect(cellClickAction({ kind: 'reposition' }, 3, 4)).toEqual({
      action: 'set-reposition-target',
      x: 3,
      y: 4,
    })
  })
  it('aoe modes set origin then aim', () => {
    expect(cellClickAction({ kind: 'aoe-origin' }, 3, 4)).toEqual({
      action: 'set-aoe-origin',
      x: 3,
      y: 4,
    })
    expect(cellClickAction({ kind: 'aoe-aim' }, 5, 6)).toEqual({
      action: 'set-aoe-aim',
      x: 5,
      y: 6,
    })
  })
  it('idle mode does nothing', () => {
    expect(cellClickAction({ kind: 'idle' }, 3, 4)).toEqual({ action: 'none' })
  })
})

describe('tacticalLogic: anchors', () => {
  it('appendAnchor appends a new cell', () => {
    expect(appendAnchor([{ x: 1, y: 1 }], 2, 1)).toEqual([
      { x: 1, y: 1 },
      { x: 2, y: 1 },
    ])
  })
  it('appendAnchor drops consecutive duplicates', () => {
    const prev = [{ x: 1, y: 1 }]
    expect(appendAnchor(prev, 1, 1)).toBe(prev)
  })
  it('dragCellsToAnchors dedups a drag path in order', () => {
    expect(
      dragCellsToAnchors([
        { x: 3, y: 3 },
        { x: 3, y: 3 },
        { x: 4, y: 3 },
        { x: 4, y: 4 },
        { x: 4, y: 4 },
      ]),
    ).toEqual([
      { x: 3, y: 3 },
      { x: 4, y: 3 },
      { x: 4, y: 4 },
    ])
  })
})

describe('tacticalLogic: doorClickAction', () => {
  it('DM click selects a door; clicking again deselects', () => {
    expect(doorClickAction(true, 'door-1', null)).toEqual({
      kind: 'select',
      doorId: 'door-1',
    })
    expect(doorClickAction(true, 'door-1', 'door-1')).toEqual({
      kind: 'select',
      doorId: null,
    })
  })
  it('Player clicks and null doors are ignored', () => {
    expect(doorClickAction(false, 'door-1', null)).toEqual({ kind: 'ignore' })
    expect(doorClickAction(true, null, null)).toEqual({ kind: 'ignore' })
  })
})

describe('tacticalLogic: tokenClickAction', () => {
  const base = {
    isDm: false,
    repositionMode: false,
    placing: false,
    moveEntryId: null as string | null,
    canMove: true,
  }
  it('DM in reposition mode selects the token for reposition', () => {
    expect(
      tokenClickAction('entry-1', { ...base, isDm: true, repositionMode: true }),
    ).toEqual({ kind: 'select-reposition', entryId: 'entry-1' })
  })
  it('movable token starts a move draft', () => {
    expect(tokenClickAction('entry-1', base)).toEqual({
      kind: 'start-move',
      entryId: 'entry-1',
    })
  })
  it('clicking the token already being moved is ignored', () => {
    expect(tokenClickAction('entry-1', { ...base, moveEntryId: 'entry-1' })).toEqual({
      kind: 'ignore',
    })
  })
  it('non-movable token falls back to selection', () => {
    expect(tokenClickAction('entry-9', { ...base, canMove: false })).toEqual({
      kind: 'select',
      entryId: 'entry-9',
    })
  })
  it('placement mode suppresses move start', () => {
    expect(tokenClickAction('entry-1', { ...base, placing: true })).toEqual({
      kind: 'select',
      entryId: 'entry-1',
    })
  })
})

describe('tacticalLogic: shouldReloadOnEvents', () => {
  const combatEvent = { seq: 3, kind: 'combat.turn_advanced' } as TableEvent
  const chatEvent = { seq: 4, kind: 'chat.message' } as TableEvent
  it('reloads on unseen combat events and advances the seq', () => {
    expect(shouldReloadOnEvents([combatEvent], 2)).toEqual({
      reload: true,
      newLastSeq: 3,
    })
  })
  it('does not reload on non-combat events but still advances the seq', () => {
    expect(shouldReloadOnEvents([chatEvent], 2)).toEqual({
      reload: false,
      newLastSeq: 4,
    })
  })
  it('ignores already-seen events', () => {
    expect(shouldReloadOnEvents([combatEvent], 5)).toEqual({
      reload: false,
      newLastSeq: 5,
    })
  })
})

describe('tacticalLogic: targetCheckBand', () => {
  it('maps server range bands to display bands', () => {
    expect(targetCheckBand(targetCheckResult({ range_band: 'reach' }))).toBe('in-range')
    expect(targetCheckBand(targetCheckResult({ range_band: 'normal' }))).toBe('in-range')
    expect(targetCheckBand(targetCheckResult({ range_band: 'long' }))).toBe('long-range')
    expect(targetCheckBand(targetCheckResult({ range_band: 'out_of_range' }))).toBe(
      'out-of-range',
    )
    expect(targetCheckBand(targetCheckResult({ range_band: 'unknown' }))).toBe('out-of-range')
  })
  it('blocked wins over any range band', () => {
    expect(
      targetCheckBand(targetCheckResult({ range_band: 'normal', blocked: true })),
    ).toBe('blocked')
  })
})

describe('tacticalLogic: preview race', () => {
  it('only the latest preview request is adopted', () => {
    expect(isLatestPreview(1, 2)).toBe(false)
    expect(isLatestPreview(2, 2)).toBe(true)
  })
})

describe('tacticalLogic: aoeShapeNeedsAim', () => {
  it('cone and line need an aim click', () => {
    expect(aoeShapeNeedsAim('cone')).toBe(true)
    expect(aoeShapeNeedsAim('line')).toBe(true)
  })
  it('circle and square preview on origin click', () => {
    expect(aoeShapeNeedsAim('circle')).toBe(false)
    expect(aoeShapeNeedsAim('square')).toBe(false)
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

  it('renders the AoE template panel when placement is requested', () => {
    const html = renderToStaticMarkup(
      <TacticalMapPanel
        {...props}
        isCurrentDm={false}
        aoePlacement={{
          spell_ref: 'srd5.1:spell:fireball',
          shape: 'circle',
          size_feet: 20,
          caster_entry_id: 'entry-1',
          slot_level: 3,
        }}
        onAoePlacementEnd={() => {}}
      />,
    )
    expect(html).toContain('data-testid="tactical-aoe"')
    expect(html).toContain('data-testid="tactical-aoe-hint"')
  })
})
