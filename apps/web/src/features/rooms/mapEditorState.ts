import type {
  BattleMap,
  BattleMapDoorInput,
  BattleMapDrawingInput,
  BattleMapTerrainInput,
  BattleMapWallInput,
} from '../../api/battleMaps'

/**
 * Free Drawing payload shape:
 * {
 *   kind: 'freehand',
 *   points: Array<[number, number]>, // [x, y] in map cell units (floats rounded to 0.05 cell)
 *   color?: string,                  // one of DRAWING_COLORS; absent on older drawings
 *   width?: number,                  // stroke width in map pixels (DRAWING_WIDTH_MIN..MAX)
 * }
 * Purely visual annotation on the map; does not affect movement, targeting, or rules.
 * Color and pen style carry no rule meaning.
 */
export type FreehandDrawingPayload = {
  kind: 'freehand'
  points: Array<[number, number]>
  color?: string
  width?: number
}

export const DRAWING_COLORS = [
  { key: 'white', hex: '#f2efe8' },
  { key: 'black', hex: '#111111' },
  { key: 'red', hex: '#e05252' },
  { key: 'orange', hex: '#f08c3a' },
  { key: 'yellow', hex: '#f2d04b' },
  { key: 'green', hex: '#5cc26a' },
  { key: 'blue', hex: '#4a90e2' },
  { key: 'purple', hex: '#a066d3' },
] as const

export type DrawingColorKey = (typeof DRAWING_COLORS)[number]['key']

export const DRAWING_WIDTH_MIN = 1
export const DRAWING_WIDTH_MAX = 12
export const DRAWING_WIDTH_DEFAULT = 3

/** Stroke colour and width for a freehand payload; older drawings without them get the defaults. */
export function freehandStroke(payload: Record<string, unknown>): { color: string; width: number } {
  const color =
    typeof payload.color === 'string' && /^#[0-9a-f]{6}$/i.test(payload.color)
      ? payload.color
      : DRAWING_COLORS[0].hex
  const width =
    typeof payload.width === 'number' && Number.isFinite(payload.width)
      ? Math.min(DRAWING_WIDTH_MAX, Math.max(DRAWING_WIDTH_MIN, payload.width))
      : DRAWING_WIDTH_DEFAULT
  return { color, width }
}

export const EDITOR_CANVAS_HEIGHT_DEFAULT = 520
export const EDITOR_CANVAS_HEIGHT_MIN = 320

/**
 * Canvas height that reaches the bottom of the viewport from the canvas top,
 * leaving room for the resize handle and page padding below it. Never shorter
 * than the default, so small screens keep the previous editor size.
 */
export function viewportFillCanvasHeight(canvasTop: number, viewportHeight: number): number {
  const bottomReserve = 72
  return Math.max(EDITOR_CANVAS_HEIGHT_DEFAULT, Math.round(viewportHeight - canvasTop - bottomReserve))
}

/** Editor canvas height after dragging the bottom handle by deltaY pixels. */
export function resizedCanvasHeight(startHeight: number, deltaY: number): number {
  return Math.max(EDITOR_CANVAS_HEIGHT_MIN, Math.round(startHeight + deltaY))
}

export type WorkingState = {
  walls: BattleMapWallInput[]
  doors: BattleMapDoorInput[]
  terrain: BattleMapTerrainInput[]
  drawings: BattleMapDrawingInput[]
}

export function toWorkingState(map: BattleMap): WorkingState {
  return {
    walls: map.walls.map((w) => ({
      id: w.id,
      x1: w.x1,
      y1: w.y1,
      x2: w.x2,
      y2: w.y2,
      visibility: w.visibility,
    })),
    doors: map.doors.map((d) => ({
      id: d.id,
      x1: d.x1,
      y1: d.y1,
      x2: d.x2,
      y2: d.y2,
      default_state: d.default_state,
      visibility: d.visibility,
    })),
    terrain: map.terrain.map((t) => ({ x: t.x, y: t.y, terrain_kind: t.terrain_kind })),
    drawings: (map.drawings ?? []).map((d) => ({
      id: d.id,
      payload: d.payload,
    })),
  }
}

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

/**
 * Objects to send in a replace request. Objects added in the editor carry local ids
 * (`wall-local-1`, ...) that the server rejects; send them with a null id so the server
 * assigns one. Objects loaded from the map keep their UUIDs.
 */
export function toReplaceObjects(state: WorkingState): WorkingState {
  const serverId = (id: string | null | undefined) => (id && UUID_PATTERN.test(id) ? id : null)
  return {
    walls: state.walls.map((w) => ({ ...w, id: serverId(w.id) })),
    doors: state.doors.map((d) => ({ ...d, id: serverId(d.id) })),
    terrain: state.terrain,
    drawings: state.drawings.map((d) => ({ ...d, id: serverId(d.id) })),
  }
}

export function addWall(state: WorkingState, wall: BattleMapWallInput): WorkingState {
  return { ...state, walls: [...state.walls, wall] }
}

export function addDoor(state: WorkingState, door: BattleMapDoorInput): WorkingState {
  return { ...state, doors: [...state.doors, door] }
}

export function addDrawing(
  state: WorkingState,
  drawing: BattleMapDrawingInput,
): WorkingState {
  return { ...state, drawings: [...state.drawings, drawing] }
}

export function setTerrain(
  state: WorkingState,
  terrain: BattleMapTerrainInput,
): WorkingState {
  const filtered = state.terrain.filter((t) => !(t.x === terrain.x && t.y === terrain.y))
  return { ...state, terrain: [...filtered, terrain] }
}

export function roundCellCoord(val: number): number {
  return Number((Math.round(val * 20) / 20).toFixed(2))
}

export function thinDrawingPoints(
  points: Array<[number, number]>,
  minDistance = 0.1,
): Array<[number, number]> {
  if (points.length <= 1) {
    return points.map(([x, y]) => [roundCellCoord(x), roundCellCoord(y)])
  }
  const result: Array<[number, number]> = []
  let lastX = -Infinity
  let lastY = -Infinity

  for (let i = 0; i < points.length; i++) {
    const rx = roundCellCoord(points[i][0])
    const ry = roundCellCoord(points[i][1])
    const isFirst = i === 0
    const isLast = i === points.length - 1

    if (isFirst) {
      result.push([rx, ry])
      lastX = rx
      lastY = ry
    } else if (isLast) {
      if (rx !== lastX || ry !== lastY) {
        result.push([rx, ry])
      }
    } else {
      const dist = Math.hypot(rx - lastX, ry - lastY)
      if (dist >= minDistance) {
        result.push([rx, ry])
        lastX = rx
        lastY = ry
      }
    }
  }

  return result
}

export function segmentIntersectsCell(
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  cx: number,
  cy: number,
): boolean {
  const minX = cx
  const maxX = cx + 1
  const minY = cy
  const maxY = cy + 1

  // 1. Quick check: endpoints inside cell
  if (x1 >= minX && x1 <= maxX && y1 >= minY && y1 <= maxY) return true
  if (x2 >= minX && x2 <= maxX && y2 >= minY && y2 <= maxY) return true

  // 2. Bounding box disjoint
  if (Math.max(x1, x2) < minX || Math.min(x1, x2) > maxX) return false
  if (Math.max(y1, y2) < minY || Math.min(y1, y2) > maxY) return false

  const dx = x2 - x1
  const dy = y2 - y1

  // 3. Intersect with left boundary x = minX
  if (dx !== 0) {
    const t = (minX - x1) / dx
    if (t >= 0 && t <= 1) {
      const y = y1 + t * dy
      if (y >= minY && y <= maxY) return true
    }
  }

  // 4. Intersect with right boundary x = maxX
  if (dx !== 0) {
    const t = (maxX - x1) / dx
    if (t >= 0 && t <= 1) {
      const y = y1 + t * dy
      if (y >= minY && y <= maxY) return true
    }
  }

  // 5. Intersect with top boundary y = minY
  if (dy !== 0) {
    const t = (minY - y1) / dy
    if (t >= 0 && t <= 1) {
      const x = x1 + t * dx
      if (x >= minX && x <= maxX) return true
    }
  }

  // 6. Intersect with bottom boundary y = maxY
  if (dy !== 0) {
    const t = (maxY - y1) / dy
    if (t >= 0 && t <= 1) {
      const x = x1 + t * dx
      if (x >= minX && x <= maxX) return true
    }
  }

  return false
}

export function drawingCrossesCell(
  drawing: BattleMapDrawingInput,
  cx: number,
  cy: number,
): boolean {
  const payload = drawing.payload
  if (
    !payload ||
    typeof payload !== 'object' ||
    payload.kind !== 'freehand' ||
    !Array.isArray(payload.points)
  ) {
    return false
  }
  const points = payload.points as Array<[number, number]>
  if (points.length === 0) return false
  if (points.length === 1) {
    const [px, py] = points[0]
    return px >= cx && px <= cx + 1 && py >= cy && py <= cy + 1
  }
  for (let i = 0; i < points.length - 1; i++) {
    if (segmentIntersectsCell(points[i][0], points[i][1], points[i + 1][0], points[i + 1][1], cx, cy)) {
      return true
    }
  }
  return false
}

export function eraseAt(state: WorkingState, x: number, y: number): WorkingState {
  const hitWall = (w: BattleMapWallInput) =>
    Math.min(w.x1, w.x2) <= x &&
    x <= Math.max(w.x1, w.x2) &&
    Math.min(w.y1, w.y2) <= y &&
    y <= Math.max(w.y1, w.y2)
  const hitDoor = (d: BattleMapDoorInput) =>
    Math.min(d.x1, d.x2) <= x &&
    x <= Math.max(d.x1, d.x2) &&
    Math.min(d.y1, d.y2) <= y &&
    y <= Math.max(d.y1, d.y2)
  return {
    walls: state.walls.filter((w) => !hitWall(w)),
    doors: state.doors.filter((d) => !hitDoor(d)),
    terrain: state.terrain.filter((t) => !(t.x === x && t.y === y)),
    drawings: state.drawings.filter((d) => !drawingCrossesCell(d, x, y)),
  }
}

export function toggleHidden(state: WorkingState, id: string): WorkingState {
  return {
    walls: state.walls.map((w) =>
      w.id === id
        ? { ...w, visibility: w.visibility === 'hidden' ? 'public' : 'hidden' }
        : w,
    ),
    doors: state.doors.map((d) =>
      d.id === id
        ? { ...d, visibility: d.visibility === 'hidden' ? 'public' : 'hidden' }
        : d,
    ),
    terrain: state.terrain,
    drawings: state.drawings,
  }
}

export function deleteById(state: WorkingState, id: string): WorkingState {
  return {
    walls: state.walls.filter((w) => w.id !== id),
    doors: state.doors.filter((d) => d.id !== id),
    terrain: state.terrain,
    drawings: state.drawings.filter((d) => d.id !== id),
  }
}

export function findAt(
  state: WorkingState,
  x: number,
  y: number,
): { kind: 'wall' | 'door' | 'drawing'; id: string } | null {
  const wall = state.walls.find(
    (w) =>
      Math.min(w.x1, w.x2) <= x &&
      x <= Math.max(w.x1, w.x2) &&
      Math.min(w.y1, w.y2) <= y &&
      y <= Math.max(w.y1, w.y2),
  )
  if (wall?.id) return { kind: 'wall', id: wall.id }
  const door = state.doors.find(
    (d) =>
      Math.min(d.x1, d.x2) <= x &&
      x <= Math.max(d.x1, d.x2) &&
      Math.min(d.y1, d.y2) <= y &&
      y <= Math.max(d.y1, d.y2),
  )
  if (door?.id) return { kind: 'door', id: door.id }
  const drawing = state.drawings.find((d) => drawingCrossesCell(d, x, y))
  if (drawing?.id) return { kind: 'drawing', id: drawing.id }
  return null
}

export type CellPoint = { cellX: number; cellY: number }
export type GridSegment = { x1: number; y1: number; x2: number; y2: number }

export function snapToVertex(
  cellX: number,
  cellY: number,
  widthCells: number,
  heightCells: number,
): { x: number; y: number } {
  const clampedX = Math.max(0, Math.min(widthCells, cellX))
  const clampedY = Math.max(0, Math.min(heightCells, cellY))
  return {
    x: Math.round(clampedX),
    y: Math.round(clampedY),
  }
}

export function nearestGridSegment(
  cellX: number,
  cellY: number,
  widthCells: number,
  heightCells: number,
): GridSegment {
  const clampedX = Math.max(0, Math.min(widthCells, cellX))
  const clampedY = Math.max(0, Math.min(heightCells, cellY))

  const cx = Math.floor(Math.min(widthCells - 1, clampedX))
  const cy = Math.floor(Math.min(heightCells - 1, clampedY))

  const u = clampedX - cx
  const v = clampedY - cy

  const dLeft = u
  const dRight = 1 - u
  const dTop = v
  const dBottom = 1 - v

  const minD = Math.min(dLeft, dRight, dTop, dBottom)

  if (minD === dLeft) {
    return { x1: cx, y1: cy, x2: cx, y2: cy + 1 }
  }
  if (minD === dRight) {
    return { x1: cx + 1, y1: cy, x2: cx + 1, y2: cy + 1 }
  }
  if (minD === dTop) {
    return { x1: cx, y1: cy, x2: cx + 1, y2: cy }
  }
  return { x1: cx, y1: cy + 1, x2: cx + 1, y2: cy + 1 }
}

/**
 * The wall/door a pointer gesture places: a drag places the line between its snapped vertices;
 * a click without dragging places the one-cell edge that was under the pointer.
 */
export function placementLine(
  start: { x: number; y: number },
  end: { x: number; y: number },
  clicked: GridSegment | null,
): GridSegment | null {
  if (start.x !== end.x || start.y !== end.y) {
    return { x1: start.x, y1: start.y, x2: end.x, y2: end.y }
  }
  return clicked
}

export function shouldTriggerEditorUndo(event: {
  ctrlKey?: boolean
  metaKey?: boolean
  key: string
  shiftKey?: boolean
  target?: unknown
}): boolean {
  if (!event.ctrlKey && !event.metaKey) return false
  if (event.shiftKey) return false
  if (event.key !== 'z' && event.key !== 'Z') return false

  const target = event.target as
    | { tagName?: string; isContentEditable?: boolean }
    | null
    | undefined
  const tag = target?.tagName?.toLowerCase()
  if (tag === 'input' || tag === 'textarea' || tag === 'select' || target?.isContentEditable) {
    return false
  }
  return true
}

