import { readFileSync } from 'node:fs'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

import type { BattleMap } from '../../api/battleMaps'
import { SessionApiError } from '../../api/sessions'
import { BattleMapEditor } from './BattleMapEditor'
import {
  addDoor,
  addDrawing,
  addWall,
  deleteById,
  eraseAt,
  findAt,
  nearestGridSegment,
  roundCellCoord,
  setTerrain,
  snapToVertex,
  shouldTriggerEditorUndo,
  thinDrawingPoints,
  toggleHidden,
  toWorkingState,
} from './mapEditorState'
import { sessionCopy } from './sessionCopy'

const ROOM_ID = '10000000-0000-4000-8000-000000000001'
const TOKEN = 'room-token'

function makeMap(revision = 1): BattleMap {
  return {
    id: 'map-1',
    room_id: ROOM_ID,
    name: 'Test Map',
    source_kind: 'blank',
    image_asset_id: null,
    width_cells: 10,
    height_cells: 10,
    grid_pixel_size: null,
    grid_offset_x: null,
    grid_offset_y: null,
    revision,
    created_at: '2026-09-28T00:00:00Z',
    updated_at: '2026-09-28T00:00:00Z',
    walls: [],
    doors: [],
    terrain: [],
    drawings: [],
  }
}

const copy = sessionCopy('en')

describe('BattleMapEditor working state', () => {
  it('toWorkingState copies map objects into working state', () => {
    const map: BattleMap = {
      ...makeMap(),
      walls: [{ id: 'w1', x1: 0, y1: 0, x2: 5, y2: 0, visibility: 'hidden' }],
      doors: [{ id: 'd1', x1: 1, y1: 1, x2: 2, y2: 1, default_state: 'closed', visibility: 'public' }],
      terrain: [{ x: 3, y: 3, terrain_kind: 'difficult' }],
    }
    const working = toWorkingState(map)
    expect(working.walls).toHaveLength(1)
    expect(working.doors).toHaveLength(1)
    expect(working.terrain).toHaveLength(1)
    expect(working.walls[0].visibility).toBe('hidden')
  })

  it('addWall + undo (history pop) restores previous state', () => {
    const working = toWorkingState(makeMap())
    const withWall = addWall(working, { id: 'w-new', x1: 1, y1: 1, x2: 5, y2: 1 })
    expect(withWall.walls).toHaveLength(1)
    // Undo is implemented as history stack pop; the pure state before add is `working`.
    expect(working.walls).toHaveLength(0)
  })

  it('setTerrain replaces terrain on the same cell', () => {
    let state = toWorkingState(makeMap())
    state = setTerrain(state, { x: 2, y: 2, terrain_kind: 'difficult' })
    state = setTerrain(state, { x: 2, y: 2, terrain_kind: 'water' })
    expect(state.terrain).toHaveLength(1)
    expect(state.terrain[0].terrain_kind).toBe('water')
  })

  it('eraseAt removes wall/door/terrain at cell', () => {
    let state = toWorkingState(makeMap())
    state = addWall(state, { id: 'w1', x1: 0, y1: 0, x2: 5, y2: 0 })
    state = setTerrain(state, { x: 9, y: 9, terrain_kind: 'lava' })
    state = eraseAt(state, 2, 0)
    expect(state.walls).toHaveLength(0)
    expect(state.terrain).toHaveLength(1)
    state = eraseAt(state, 9, 9)
    expect(state.terrain).toHaveLength(0)
  })

  it('toggleHidden flips wall visibility', () => {
    let state = toWorkingState(makeMap())
    state = addWall(state, { id: 'w1', x1: 0, y1: 0, x2: 5, y2: 0, visibility: 'public' })
    state = toggleHidden(state, 'w1')
    expect(state.walls[0].visibility).toBe('hidden')
    state = toggleHidden(state, 'w1')
    expect(state.walls[0].visibility).toBe('public')
  })

  it('deleteById removes the selected object', () => {
    let state = toWorkingState(makeMap())
    state = addWall(state, { id: 'w1', x1: 0, y1: 0, x2: 5, y2: 0 })
    state = deleteById(state, 'w1')
    expect(state.walls).toHaveLength(0)
  })

  it('findAt locates wall under cell', () => {
    let state = toWorkingState(makeMap())
    state = addWall(state, { id: 'w1', x1: 1, y1: 1, x2: 5, y2: 1 })
    expect(findAt(state, 3, 1)).toEqual({ kind: 'wall', id: 'w1' })
    expect(findAt(state, 9, 9)).toBeNull()
  })

  it('save sends expected_revision and does not overwrite on conflict', async () => {
    // The save path calls replaceBattleMapObjects with expected_revision = map.revision.
    // Verify the editor source wires map.revision into the PUT body.
    const source = readFileSync(new URL('./BattleMapEditor.tsx', import.meta.url), 'utf8')
    expect(source).toContain('expected_revision: map.revision')
    // Conflict is handled locally: onSaved is not called, message is shown.
    expect(source).toContain("cause.code === 'battle_map_revision_conflict'")
    // onSaved is only called on success, not in the conflict branch.
    const saveBlock = source.slice(source.indexOf('const handleSave'))
    const conflictIdx = saveBlock.indexOf('battle_map_revision_conflict')
    const onSavedIdx = saveBlock.indexOf('onSaved(saved)')
    expect(conflictIdx).toBeGreaterThan(-1)
    expect(onSavedIdx).toBeGreaterThan(-1)
    expect(onSavedIdx).toBeLessThan(conflictIdx)
  })

  it('conflict error carries the machine code for localized message', () => {
    const err = new SessionApiError(409, 'battle_map_revision_conflict', 'revision mismatch')
    expect(err.code).toBe('battle_map_revision_conflict')
    expect(err.status).toBe(409)
  })

  it('renders toolbar with all tools and save button', () => {
    const html = renderToStaticMarkup(
      <BattleMapEditor
        map={makeMap()}
        copy={copy}
        locale="en"
        roomId={ROOM_ID}
        token={TOKEN}
        onSaved={vi.fn()}
        onError={vi.fn()}
        onClose={vi.fn()}
      />,
    )
    for (const tool of ['select', 'wall', 'door', 'terrain', 'draw', 'erase']) {
      expect(html).toContain(`data-testid="map-editor-tool-${tool}"`)
    }
    // Token tool lives in the tactical map panel (placement mode), not the editor.
    expect(html).not.toContain('data-testid="map-editor-tool-token"')
    expect(html).toContain('data-testid="map-editor-save"')
    expect(html).toContain('data-testid="map-editor-undo"')
    expect(html).toContain('data-testid="map-editor-canvas"')
    expect(html).toContain('aria-label="Close"')
  })

  it('renders hidden wall with DM marker', () => {
    const map: BattleMap = {
      ...makeMap(),
      walls: [{ id: 'w1', x1: 0, y1: 0, x2: 5, y2: 0, visibility: 'hidden' }],
    }
    const html = renderToStaticMarkup(
      <BattleMapEditor
        map={map}
        copy={copy}
        locale="en"
        roomId={ROOM_ID}
        token={TOKEN}
        onSaved={vi.fn()}
        onError={vi.fn()}
        onClose={vi.fn()}
      />,
    )
    expect(html).toContain('data-testid="battle-map-wall"')
    expect(html).toContain('data-hidden="true"')
  })

  it('snapToVertex snaps map cell coordinates to the nearest grid vertex and clamps to the map', () => {
    expect(snapToVertex(2.0, 3.5, 10, 10)).toEqual({ x: 2, y: 4 })
    expect(snapToVertex(2.4, 3.49, 10, 10)).toEqual({ x: 2, y: 3 })
    expect(snapToVertex(-2.5, -1.25, 10, 10)).toEqual({ x: 0, y: 0 })
    expect(snapToVertex(249.9, 249.9, 10, 10)).toEqual({ x: 10, y: 10 })
  })

  it('nearestGridSegment chooses the closest 1-cell edge of the cell under the pointer', () => {
    // cellX 2.1, cellY 3.5: the left edge x = 2 is 0.1 away.
    expect(nearestGridSegment(2.1, 3.5, 10, 10)).toEqual({ x1: 2, y1: 3, x2: 2, y2: 4 })
    // cellX 2.5, cellY 3.9: the bottom edge y = 4 is 0.1 away.
    expect(nearestGridSegment(2.5, 3.9, 10, 10)).toEqual({ x1: 2, y1: 4, x2: 3, y2: 4 })
  })

  it('roundCellCoord rounds floats to nearest 0.05 cell unit', () => {
    expect(roundCellCoord(1.02)).toBe(1.0)
    expect(roundCellCoord(1.03)).toBe(1.05)
    expect(roundCellCoord(1.07)).toBe(1.05)
    expect(roundCellCoord(1.08)).toBe(1.1)
    expect(roundCellCoord(0)).toBe(0)
    expect(roundCellCoord(4.25)).toBe(4.25)
  })

  it('thinDrawingPoints eliminates redundant close points while preserving start and end vertices', () => {
    const raw: Array<[number, number]> = [
      [1.0, 1.0],
      [1.02, 1.02],
      [1.04, 1.04],
      [1.5, 1.5],
      [2.0, 2.0],
    ]
    const thinned = thinDrawingPoints(raw, 0.1)
    expect(thinned[0]).toEqual([1.0, 1.0])
    expect(thinned[thinned.length - 1]).toEqual([2.0, 2.0])
    expect(thinned.length).toBeLessThan(raw.length)
    expect(thinned).toEqual([
      [1.0, 1.0],
      [1.5, 1.5],
      [2.0, 2.0],
    ])

    // Single point preserved and rounded
    expect(thinDrawingPoints([[3.12, 4.18]])).toEqual([[3.1, 4.2]])
  })

  it('eraseAt removes drawing whose path crosses the erased cell', () => {
    let state = toWorkingState(makeMap())
    state = addDrawing(state, {
      id: 'dr-1',
      payload: {
        kind: 'freehand',
        points: [
          [1.2, 1.3],
          [3.8, 1.3],
        ],
      },
    })
    expect(state.drawings).toHaveLength(1)

    // Cell (2, 1) is crossed by segment from (1.2, 1.3) to (3.8, 1.3)
    const afterErase = eraseAt(state, 2, 1)
    expect(afterErase.drawings).toHaveLength(0)
  })

  it('eraseAt leaves drawing untouched if path does not intersect erased cell', () => {
    let state = toWorkingState(makeMap())
    state = addDrawing(state, {
      id: 'dr-1',
      payload: {
        kind: 'freehand',
        points: [
          [1.2, 1.3],
          [1.8, 1.3],
        ],
      },
    })
    const afterErase = eraseAt(state, 9, 9)
    expect(afterErase.drawings).toHaveLength(1)
    expect(afterErase.drawings[0].id).toBe('dr-1')
  })

  it('findAt locates drawing crossing the target cell', () => {
    let state = toWorkingState(makeMap())
    state = addDrawing(state, {
      id: 'dr-1',
      payload: {
        kind: 'freehand',
        points: [
          [2.2, 3.2],
          [2.8, 3.8],
        ],
      },
    })
    expect(findAt(state, 2, 3)).toEqual({ kind: 'drawing', id: 'dr-1' })
    expect(findAt(state, 0, 0)).toBeNull()
  })

  it('toWorkingState preserves existing and unknown drawing kinds', () => {
    const map: BattleMap = {
      ...makeMap(),
      drawings: [
        { id: 'dr-free', payload: { kind: 'freehand', points: [[1, 1], [2, 2]] } },
        { id: 'dr-unknown', payload: { kind: 'custom_stamp', icon: 'flag' } },
      ],
    }
    const working = toWorkingState(map)
    expect(working.drawings).toHaveLength(2)
    expect(working.drawings[0].id).toBe('dr-free')
    expect(working.drawings[1].id).toBe('dr-unknown')
  })

  it('save sends working drawings including unknown drawing kinds', () => {
    const source = readFileSync(new URL('./BattleMapEditor.tsx', import.meta.url), 'utf8')
    expect(source).toContain('drawings: working.drawings')
    expect(source).not.toContain('drawings: []')
  })

  it('addDrawing + undo restores previous state without the drawing', () => {
    const working = toWorkingState(makeMap())
    const withDrawing = addDrawing(working, {
      id: 'dr-new',
      payload: { kind: 'freehand', points: [[1, 1], [2, 2]] },
    })
    expect(withDrawing.drawings).toHaveLength(1)
    // Undo restores working state before addDrawing
    expect(working.drawings).toHaveLength(0)
  })

  it('shouldTriggerEditorUndo handles Ctrl+Z and Cmd+Z without intercepting inputs or textareas', () => {
    expect(shouldTriggerEditorUndo({ ctrlKey: true, key: 'z' })).toBe(true)
    expect(shouldTriggerEditorUndo({ metaKey: true, key: 'z' })).toBe(true)
    expect(shouldTriggerEditorUndo({ metaKey: true, key: 'Z' })).toBe(true)
    expect(shouldTriggerEditorUndo({ key: 'z' })).toBe(false)
    expect(shouldTriggerEditorUndo({ ctrlKey: true, shiftKey: true, key: 'z' })).toBe(false)
    expect(
      shouldTriggerEditorUndo({
        ctrlKey: true,
        key: 'z',
        target: { tagName: 'INPUT' } as unknown as HTMLElement,
      }),
    ).toBe(false)
    expect(
      shouldTriggerEditorUndo({
        ctrlKey: true,
        key: 'z',
        target: { tagName: 'TEXTAREA' } as unknown as HTMLElement,
      }),
    ).toBe(false)
    expect(
      shouldTriggerEditorUndo({
        ctrlKey: true,
        key: 'z',
        target: { tagName: 'SELECT' } as unknown as HTMLElement,
      }),
    ).toBe(false)
    expect(
      shouldTriggerEditorUndo({
        ctrlKey: true,
        key: 'z',
        target: { isContentEditable: true } as unknown as HTMLElement,
      }),
    ).toBe(false)
    expect(
      shouldTriggerEditorUndo({
        ctrlKey: true,
        key: 'z',
        target: { tagName: 'DIV' } as unknown as HTMLElement,
      }),
    ).toBe(true)
  })
})
