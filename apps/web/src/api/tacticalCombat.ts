import { request, tableBase } from './sessions'

export type TacticalStartInput = {
  battle_map_id?: string | null
  blank_width_cells?: number | null
  blank_height_cells?: number | null
  include_active_party?: boolean
  idempotency_key?: string | null
}

export type BoardPositionView = {
  entry_id: string
  anchor_x: number
  anchor_y: number
  footprint_width: number
  footprint_height: number
  revision: number
}

export type BoardWallView = {
  x1: number
  y1: number
  x2: number
  y2: number
  visibility?: 'public' | 'hidden'
}

export type BoardDoorView = {
  door_id: string | null
  x1: number
  y1: number
  x2: number
  y2: number
  state: string
  revealed: boolean
  // Present on DM projection when the server includes it; absent otherwise.
  hidden_origin?: boolean | null
}

export type BoardTerrainView = {
  x: number
  y: number
  terrain_kind: string
}

export type CombatBoardView = {
  combat_id: string
  width_cells: number
  height_cells: number
  grid_pixel_size: number | null
  grid_offset_x: number | null
  grid_offset_y: number | null
  has_image: boolean
  source_battle_map_id: string | null
  source_battle_map_revision: number | null
  runtime_revision: number
  walls: BoardWallView[]
  doors: BoardDoorView[]
  terrain: BoardTerrainView[]
  drawings: Array<Record<string, unknown>>
  positions: BoardPositionView[]
}

export type PlaceCombatantInput = {
  anchor_x: number
  anchor_y: number
  idempotency_key?: string | null
}

export type UpdateDoorStateInput = {
  state: 'open' | 'closed' | 'locked' | 'broken'
  revealed?: boolean | null
  expected_runtime_revision?: number | null
  idempotency_key?: string | null
}

const tacticalBase = (roomId: string, campaignId: string, sessionId: string) =>
  `${tableBase(roomId, campaignId, sessionId)}/combat`

export function startTacticalCombat(
  roomId: string,
  campaignId: string,
  sessionId: string,
  body: TacticalStartInput,
  token: string,
): Promise<import('./combat').CombatView> {
  return request(`${tacticalBase(roomId, campaignId, sessionId)}/tactical-start`, token, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function getCombatBoard(
  roomId: string,
  campaignId: string,
  sessionId: string,
  token: string,
): Promise<CombatBoardView> {
  return request(`${tacticalBase(roomId, campaignId, sessionId)}/board`, token)
}

export function getCombatBoardImageUrl(
  roomId: string,
  campaignId: string,
  sessionId: string,
): string {
  return `${tacticalBase(roomId, campaignId, sessionId)}/board/image`
}

export function placeCombatant(
  roomId: string,
  campaignId: string,
  sessionId: string,
  entryId: string,
  body: PlaceCombatantInput,
  token: string,
): Promise<BoardPositionView> {
  return request(`${tacticalBase(roomId, campaignId, sessionId)}/board/positions/${entryId}`, token, {
    method: 'PUT',
    body: JSON.stringify(body),
  })
}

export function updateBoardDoorState(
  roomId: string,
  campaignId: string,
  sessionId: string,
  doorId: string,
  body: UpdateDoorStateInput,
  token: string,
): Promise<BoardDoorView> {
  return request(`${tacticalBase(roomId, campaignId, sessionId)}/board/doors/${doorId}`, token, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}
