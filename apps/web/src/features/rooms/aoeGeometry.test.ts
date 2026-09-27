import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

import { aoeCellsForTemplate, type AoeOutlineInput } from './aoeGeometry'

type GoldenCase = {
  name: string
  shape: {
    kind: 'circle' | 'square' | 'cone' | 'line'
    size_feet: number
    origin: [number, number]
    aim: [number, number] | null
    direction: 'ne' | 'nw' | 'se' | 'sw' | null
  }
  board: { width_cells: number; height_cells: number }
  affected_cells: Array<[number, number]>
}

function loadGolden(): GoldenCase[] {
  // apps/web/src/features/rooms -> repo root is ../../../..
  const here = dirname(fileURLToPath(import.meta.url))
  const path = join(here, '..', '..', '..', '..', '..', 'apps/server/tests/fixtures/p5d_aoe_golden.json')
  const raw = readFileSync(path, 'utf-8')
  return (JSON.parse(raw) as { cases: GoldenCase[] }).cases
}

describe('aoeGeometry aligns with p5d_aoe_golden.json', () => {
  const cases = loadGolden()

  for (const golden of cases) {
    it(`matches server cells for ${golden.name}`, () => {
      const input: AoeOutlineInput = {
        shape: golden.shape.kind,
        size_feet: golden.shape.size_feet,
        origin_x: golden.shape.origin[0],
        origin_y: golden.shape.origin[1],
        aim_x: golden.shape.aim?.[0] ?? null,
        aim_y: golden.shape.aim?.[1] ?? null,
        direction: golden.shape.direction,
      }
      const got = aoeCellsForTemplate(input)
        .filter(
          (c) => c.x >= 0 && c.x < golden.board.width_cells && c.y >= 0 && c.y < golden.board.height_cells,
        )
        .map((c) => `${c.x},${c.y}`)
        .sort()
      const want = golden.affected_cells.map(([x, y]) => `${x},${y}`).sort()
      expect(got).toEqual(want)
    })
  }
})
