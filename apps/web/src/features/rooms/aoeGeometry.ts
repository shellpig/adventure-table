/**
 * AoE template outline geometry for the Tactical map renderer.
 *
 * The server is the authority on affected cells (`spells/aoe/preview`
 * returns them); this module only draws the template *outline* so the
 * player's aim matches the golden geometry in
 * `apps/server/tests/fixtures/p5d_aoe_golden.json`. Boundaries are inclusive.
 *
 * Coordinates are in cells (integers). All shapes are defined on the same
 * 5 ft grid the server uses.
 */

export type AoeShapeKind = 'circle' | 'square' | 'cone' | 'line'

export type AoeOutlineInput = {
  shape: AoeShapeKind
  size_feet: number
  origin_x: number
  origin_y: number
  aim_x?: number | null
  aim_y?: number | null
  direction?: 'ne' | 'nw' | 'se' | 'sw' | null
}

/** Cells whose center is inside the template, per the golden fixture. */
export function aoeCellsForTemplate(input: AoeOutlineInput): Array<{ x: number; y: number }> {
  const radiusCells = input.size_feet / 5
  const cells: Array<{ x: number; y: number }> = []
  // Scan a bounding box and keep cells whose center satisfies the shape.
  const span = Math.ceil(radiusCells) + 1
  for (let y = input.origin_y - span; y <= input.origin_y + span; y++) {
    for (let x = input.origin_x - span; x <= input.origin_x + span; x++) {
      if (cellInTemplate(x, y, input, radiusCells)) {
        cells.push({ x, y })
      }
    }
  }
  return cells
}

function gridDistanceFeet(fromX: number, fromY: number, cellX: number, cellY: number): number {
  // Server vertex_cell_distance: 5/10-alternating from vertex to cell center.
  const stepsX = Math.ceil(Math.abs(cellX + 0.5 - fromX))
  const stepsY = Math.ceil(Math.abs(cellY + 0.5 - fromY))
  const diagonals = Math.min(stepsX, stepsY)
  const orthogonal = Math.max(stepsX, stepsY) - diagonals
  // Alternating 5/10: pairs cost 15.
  const pairs = Math.floor(diagonals / 2)
  const remainder = diagonals % 2
  return orthogonal * 5 + pairs * 15 + remainder * 5
}

function cellInTemplate(
  x: number,
  y: number,
  input: AoeOutlineInput,
  radiusCells: number,
): boolean {
  // Cell center in cell units relative to the origin cell's corner.
  // The server treats the origin as the cell corner; cell (ox, oy) center is
  // (ox + 0.5, oy + 0.5) relative to the origin corner.
  const cx = x + 0.5 - input.origin_x
  const cy = y + 0.5 - input.origin_y
  switch (input.shape) {
    case 'circle':
      return gridDistanceFeet(input.origin_x, input.origin_y, x, y) <= input.size_feet
    case 'square': {
      // Server: origin is one corner; direction picks the quadrant.
      const sideCells = radiusCells
      const dir = input.direction ?? 'se'
      const cx0 = x + 0.5
      const cy0 = y + 0.5
      const lowX = dir.includes('e') ? input.origin_x : input.origin_x - sideCells
      const highX = dir.includes('e') ? input.origin_x + sideCells : input.origin_x
      const lowY = dir.includes('s') ? input.origin_y : input.origin_y - sideCells
      const highY = dir.includes('s') ? input.origin_y + sideCells : input.origin_y
      return lowX <= cx0 + 1e-9 && cx0 <= highX + 1e-9 && lowY <= cy0 + 1e-9 && cy0 <= highY + 1e-9
    }
    case 'cone':
    case 'line': {
      const aimX = input.aim_x ?? input.origin_x + 1
      const aimY = input.aim_y ?? input.origin_y
      const dx = aimX - input.origin_x
      const dy = aimY - input.origin_y
      const len = Math.hypot(dx, dy)
      if (len < 1e-9) return false
      const ux = dx / len
      const uy = dy / len
      if (input.shape === 'line') {
        // Line: projection within length, perpendicular within 2.5 ft.
        const proj = cx * ux + cy * uy
        if (proj < 0 || proj > radiusCells + 1e-9) return false
        const perp = Math.abs(-cx * uy + cy * ux)
        return perp <= 0.5 + 1e-9
      }
      // Cone: must be in circle (5/10 distance) AND within atan(1/2) of axis.
      if (gridDistanceFeet(input.origin_x, input.origin_y, x, y) > input.size_feet) return false
      const dot = ux * cx + uy * cy
      if (dot <= 0) return false
      const cross = Math.abs(ux * cy - uy * cx)
      return 2.0 * cross <= dot + 1e-9
    }
  }
}
