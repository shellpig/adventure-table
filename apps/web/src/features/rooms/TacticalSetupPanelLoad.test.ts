import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

import { tacticalStartBody } from './TacticalSetupPanel'

const source = readFileSync(new URL('./TacticalSetupPanel.tsx', import.meta.url), 'utf8')

describe('M07-C tactical start load option', () => {
  it('builds a with-monsters body only for an explicit library-map opt-in', () => {
    expect(
      tacticalStartBody(
        { kind: 'library-map', mapId: 'map-1', loadMonsters: true },
        'key-1',
      ),
    ).toEqual({
      battle_map_id: 'map-1',
      include_active_party: true,
      load_map_monsters: true,
      idempotency_key: 'key-1',
    })
  })

  it('defaults a library-map start to map-only', () => {
    const body = tacticalStartBody(
      { kind: 'library-map', mapId: 'map-1', loadMonsters: false },
      'key-2',
    )
    expect(body.load_map_monsters).toBe(false)
    expect(body).not.toHaveProperty('blank_width_cells')
    expect(body).toHaveProperty('battle_map_id', 'map-1')
  })

  it('never sets load_map_monsters for a blank start', () => {
    expect(
      tacticalStartBody({ kind: 'blank', width: 20, height: 20 }, 'key-3'),
    ).toEqual({
      blank_width_cells: 20,
      blank_height_cells: 20,
      include_active_party: true,
      load_map_monsters: false,
      idempotency_key: 'key-3',
    })
  })

  it('omitting the flag would behave map-only, so an explicit false is required', () => {
    // Guards against a future edit that drops the field for map sources: the
    // server default is map-only, but the panel must state its choice.
    expect(source).toContain('loadMonsters')
    expect(source).toContain('load_map_monsters: selection.loadMonsters')
  })
})

describe('M07-C TacticalSetupPanel wiring', () => {
  it('offers the load option only for a selected library map, defaulting to map-only', () => {
    expect(source).toContain('const [loadMonsters, setLoadMonsters] = useState(false)')
    expect(source).toContain('selectedMapId && !useBlank')
    expect(source).toContain('data-testid="tactical-load-monsters-option"')
    expect(source).toContain('data-testid="tactical-load-map-only"')
    expect(source).toContain('data-testid="tactical-load-with-monsters"')
  })

  it('routes the start through tacticalStartBody with the panel selection', () => {
    expect(source).toContain(
      "{ kind: 'library-map', mapId: selectedMapId, loadMonsters }",
    )
    expect(source).toContain('tacticalStartBody({ kind: ')
  })

  it('shows the DM-only 409 problem list and stays open for retry', () => {
    expect(source).toContain("cause.code === 'map_monster_placement_invalid'")
    expect(source).toContain('setLoadProblems(extractPlacementProblems(cause))')
    expect(source).toContain('data-testid="tactical-load-problems"')
    // Success still closes the panel; the 409 branch never calls onClose.
    const startBlock = source.slice(source.indexOf('const handleStart'))
    const problemsIdx = startBlock.indexOf('setLoadProblems(extractPlacementProblems(cause))')
    const closeIdx = startBlock.indexOf('onClose()')
    expect(problemsIdx).toBeGreaterThan(-1)
    expect(closeIdx).toBeGreaterThan(-1)
    expect(closeIdx).toBeLessThan(problemsIdx)
  })
})
