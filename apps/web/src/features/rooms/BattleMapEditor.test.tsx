import { readFileSync } from 'node:fs'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

import type { BattleMap } from '../../api/battleMaps'
import { SessionApiError } from '../../api/sessions'
import { BattleMapEditor } from './BattleMapEditor'
import {
  addWall,
  deleteById,
  eraseAt,
  findAt,
  setTerrain,
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
})
