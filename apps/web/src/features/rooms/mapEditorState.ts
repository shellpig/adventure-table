import type {
  BattleMap,
  BattleMapDoorInput,
  BattleMapTerrainInput,
  BattleMapWallInput,
} from '../../api/battleMaps'

export type WorkingState = {
  walls: BattleMapWallInput[]
  doors: BattleMapDoorInput[]
  terrain: BattleMapTerrainInput[]
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
  }
}

export function addWall(state: WorkingState, wall: BattleMapWallInput): WorkingState {
  return { ...state, walls: [...state.walls, wall] }
}

export function addDoor(state: WorkingState, door: BattleMapDoorInput): WorkingState {
  return { ...state, doors: [...state.doors, door] }
}

export function setTerrain(
  state: WorkingState,
  terrain: BattleMapTerrainInput,
): WorkingState {
  const filtered = state.terrain.filter((t) => !(t.x === terrain.x && t.y === terrain.y))
  return { ...state, terrain: [...filtered, terrain] }
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
  }
}

export function deleteById(state: WorkingState, id: string): WorkingState {
  return {
    walls: state.walls.filter((w) => w.id !== id),
    doors: state.doors.filter((d) => d.id !== id),
    terrain: state.terrain,
  }
}

export function findAt(
  state: WorkingState,
  x: number,
  y: number,
): { kind: 'wall' | 'door'; id: string } | null {
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
  return null
}
