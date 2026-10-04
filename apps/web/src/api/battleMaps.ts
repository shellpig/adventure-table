import { request } from './sessions'

export type BattleMapWallVisibility = 'public' | 'hidden'
export type BattleMapDoorState = 'open' | 'closed' | 'locked' | 'broken'
/** Server terrain kinds; normal is painted Normal terrain and has no rule effect. */
export type BattleMapTerrainKind = 'normal' | 'difficult' | 'blocked'
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

export type BattleMapMonsterPlacementVisibility = 'public' | 'hidden'

export type BattleMapMonsterPlacement = {
  id: string
  template_key: string | null
  custom_template_id: string | null
  anchor_x: number
  anchor_y: number
  visibility: BattleMapMonsterPlacementVisibility
  sort_order: number
}

export type MonsterPlacementInput = {
  id?: string | null
  template_key?: string | null
  custom_template_id?: string | null
  anchor_x: number
  anchor_y: number
  visibility?: BattleMapMonsterPlacementVisibility
  sort_order?: number
}

export type MonsterPlacementsReplaceInput = {
  expected_revision: number
  placements: MonsterPlacementInput[]
}

export type MonsterPlacementProblem = {
  placement_id: string
  code: string
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
  archived_at: string | null
  walls: BattleMapWall[]
  doors: BattleMapDoor[]
  terrain: BattleMapTerrain[]
  drawings: BattleMapDrawing[]
  monster_placements: BattleMapMonsterPlacement[]
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
  archived_at: string | null
}

export type BattleMapCopyInput = {
  expected_revision: number
  name?: string | null
}

export type BattleMapArchiveInput = {
  expected_revision: number
}

export type ListBattleMapsOptions = {
  includeArchived?: boolean
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

export function listBattleMaps(
  roomId: string,
  token: string,
  options?: ListBattleMapsOptions,
): Promise<BattleMapSummary[]> {
  const query = options?.includeArchived ? '?include_archived=true' : ''
  return request(`${battleMapsBase(roomId)}${query}`, token)
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

export function copyBattleMap(
  roomId: string,
  mapId: string,
  body: BattleMapCopyInput,
  token: string,
): Promise<BattleMap> {
  return request(`${battleMapsBase(roomId)}/${mapId}/copy`, token, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function archiveBattleMap(
  roomId: string,
  mapId: string,
  body: BattleMapArchiveInput,
  token: string,
): Promise<BattleMap> {
  return request(`${battleMapsBase(roomId)}/${mapId}/archive`, token, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function deleteBattleMap(
  roomId: string,
  mapId: string,
  expectedRevision: number,
  token: string,
): Promise<void> {
  return request(
    `${battleMapsBase(roomId)}/${mapId}?expected_revision=${expectedRevision}`,
    token,
    {
      method: 'DELETE',
    },
  )
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

export function replaceMonsterPlacements(
  roomId: string,
  mapId: string,
  body: MonsterPlacementsReplaceInput,
  token: string,
): Promise<BattleMap> {
  return request(`${battleMapsBase(roomId)}/${mapId}/monster-placements`, token, {
    method: 'PUT',
    body: JSON.stringify(body),
  })
}
