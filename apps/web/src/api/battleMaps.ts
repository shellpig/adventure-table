import { request } from './sessions'

export type BattleMapWallVisibility = 'public' | 'hidden'
export type BattleMapDoorState = 'open' | 'closed' | 'locked' | 'broken'
export type BattleMapTerrainKind = string
export type BattleMapSourceKind = 'blank' | 'image'

export type BattleMapWall = {
  id: string
  x1: number
  y1: number
  x2: number
  y2: number
  visibility: BattleMapWallVisibility
}

export type BattleMapDoor = {
  id: string
  x1: number
  y1: number
  x2: number
  y2: number
  default_state: BattleMapDoorState
  visibility: BattleMapWallVisibility
}

export type BattleMapTerrain = {
  x: number
  y: number
  terrain_kind: BattleMapTerrainKind
}

export type BattleMapDrawing = {
  id: string
  payload: Record<string, unknown>
}

export type BattleMap = {
  id: string
  room_id: string
  name: string
  source_kind: BattleMapSourceKind
  image_asset_id: string | null
  width_cells: number
  height_cells: number
  grid_pixel_size: number | null
  grid_offset_x: number | null
  grid_offset_y: number | null
  revision: number
  created_at: string
  updated_at: string
  walls: BattleMapWall[]
  doors: BattleMapDoor[]
  terrain: BattleMapTerrain[]
  drawings: BattleMapDrawing[]
}

export type BattleMapSummary = {
  id: string
  room_id: string
  name: string
  source_kind: BattleMapSourceKind
  image_asset_id: string | null
  width_cells: number
  height_cells: number
  revision: number
  created_at: string
  updated_at: string
}

export type BattleMapCreateInput = {
  name: string
  source_kind: BattleMapSourceKind
  image_asset_id?: string | null
  width_cells: number
  height_cells: number
  grid_pixel_size?: number | null
  grid_offset_x?: number | null
  grid_offset_y?: number | null
}

export type BattleMapPatchInput = {
  expected_revision: number
  name?: string | null
  width_cells?: number | null
  height_cells?: number | null
  grid_pixel_size?: number | null
  grid_offset_x?: number | null
  grid_offset_y?: number | null
}

export type BattleMapWallInput = {
  id?: string | null
  x1: number
  y1: number
  x2: number
  y2: number
  visibility?: BattleMapWallVisibility
}

export type BattleMapDoorInput = {
  id?: string | null
  x1: number
  y1: number
  x2: number
  y2: number
  default_state?: BattleMapDoorState
  visibility?: BattleMapWallVisibility
}

export type BattleMapTerrainInput = {
  x: number
  y: number
  terrain_kind: BattleMapTerrainKind
}

export type BattleMapDrawingInput = {
  id?: string | null
  payload: Record<string, unknown>
}

export type BattleMapObjectsReplaceInput = {
  expected_revision: number
  walls?: BattleMapWallInput[]
  doors?: BattleMapDoorInput[]
  terrain?: BattleMapTerrainInput[]
  drawings?: BattleMapDrawingInput[]
}

const battleMapsBase = (roomId: string) => `/api/rooms/${roomId}/battle-maps`

export function listBattleMaps(roomId: string, token: string): Promise<BattleMapSummary[]> {
  return request(battleMapsBase(roomId), token)
}

export function createBattleMap(
  roomId: string,
  body: BattleMapCreateInput,
  token: string,
): Promise<BattleMap> {
  return request(battleMapsBase(roomId), token, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function getBattleMap(
  roomId: string,
  mapId: string,
  token: string,
): Promise<BattleMap> {
  return request(`${battleMapsBase(roomId)}/${mapId}`, token)
}

export function patchBattleMap(
  roomId: string,
  mapId: string,
  body: BattleMapPatchInput,
  token: string,
): Promise<BattleMap> {
  return request(`${battleMapsBase(roomId)}/${mapId}`, token, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

export function replaceBattleMapObjects(
  roomId: string,
  mapId: string,
  body: BattleMapObjectsReplaceInput,
  token: string,
): Promise<BattleMap> {
  return request(`${battleMapsBase(roomId)}/${mapId}/objects`, token, {
    method: 'PUT',
    body: JSON.stringify(body),
  })
}
