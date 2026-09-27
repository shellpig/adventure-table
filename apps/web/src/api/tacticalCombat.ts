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

// --- Movement (P5-B/E) ---

export type MovementAnchor = { x: number; y: number }

export type PreviewMovementInput = {
  entry_id: string
  path: MovementAnchor[]
  drag_entry_id?: string | null
}

export type MovementStepView = {
  anchor_x: number
  anchor_y: number
  cost_feet: number
  difficult: boolean
  warnings: string[]
}

export type PreviewMovementView = {
  entry_id: string
  valid: boolean
  failure: string | null
  steps: MovementStepView[]
  used_feet: number
  remaining_feet: number
  budget_feet: number
  diagonal_steps_used: number
  position_revision: number
  board_revision: number
}

export type ConfirmMovementInput = {
  entry_id: string
  path: MovementAnchor[]
  expected_position_revision: number
  expected_board_revision: number
  idempotency_key?: string | null
  drag_entry_id?: string | null
}

export type ConfirmMovementView = {
  entry_id: string
  outcome: 'committed' | 'interrupted' | 'paused'
  anchor_x: number
  anchor_y: number
  used_feet: number
  remaining_feet: number
  budget_feet: number
  diagonal_steps_used: number
  position_revision: number
  board_revision: number
  pending_revision: number
  pending_window_ids: string[]
  boundary_reactor_ids: string[]
}

export type ResumeMovementInput = {
  entry_id: string
  expected_pending_revision: number
  idempotency_key?: string | null
}

export type ResumeMovementView = {
  entry_id: string
  outcome: 'resumed' | 'paused' | 'stopped'
  anchor_x: number
  anchor_y: number
  used_feet: number
  remaining_feet: number
  budget_feet: number
  diagonal_steps_used: number
  position_revision: number
  board_revision: number
  pending_revision: number
  pending_window_ids: string[]
  boundary_reactor_ids: string[]
}

export type CancelPendingMovementInput = {
  entry_id: string
  reason: string
  idempotency_key?: string | null
}

export type CancelPendingMovementView = {
  entry_id: string
  cancelled: boolean
  anchor_x: number
  anchor_y: number
  position_revision: number
  board_revision: number
}

export type RepositionInput = {
  entry_id: string
  anchor_x: number
  anchor_y: number
  reason: string
  expected_position_revision: number
  idempotency_key?: string | null
}

export type RepositionView = {
  entry_id: string
  anchor_x: number
  anchor_y: number
  position_revision: number
  board_revision: number
}

export function previewMovement(
  roomId: string,
  campaignId: string,
  sessionId: string,
  body: PreviewMovementInput,
  token: string,
): Promise<PreviewMovementView> {
  return request(`${tacticalBase(roomId, campaignId, sessionId)}/board/movement/preview`, token, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function confirmMovement(
  roomId: string,
  campaignId: string,
  sessionId: string,
  body: ConfirmMovementInput,
  token: string,
): Promise<ConfirmMovementView> {
  return request(`${tacticalBase(roomId, campaignId, sessionId)}/board/movement/confirm`, token, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function resumeMovement(
  roomId: string,
  campaignId: string,
  sessionId: string,
  body: ResumeMovementInput,
  token: string,
): Promise<ResumeMovementView> {
  return request(`${tacticalBase(roomId, campaignId, sessionId)}/board/movement/resume`, token, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function cancelPendingMovement(
  roomId: string,
  campaignId: string,
  sessionId: string,
  body: CancelPendingMovementInput,
  token: string,
): Promise<CancelPendingMovementView> {
  return request(
    `${tacticalBase(roomId, campaignId, sessionId)}/board/movement/cancel-pending`,
    token,
    {
      method: 'POST',
      body: JSON.stringify(body),
    },
  )
}

export function repositionCombatant(
  roomId: string,
  campaignId: string,
  sessionId: string,
  body: RepositionInput,
  token: string,
): Promise<RepositionView> {
  return request(`${tacticalBase(roomId, campaignId, sessionId)}/board/reposition`, token, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

// --- Target check (P5-C) ---

export type TargetCheckInput = {
  source_entry_id: string
  target_entry_id: string
  attack_source_ref?: string | null
  spell_ref?: string | null
}

export type TargetCheckResult = {
  source_entry_id: string
  target_entry_id: string
  kind: 'attack' | 'spell'
  ref: string
  legal: boolean
  in_range: boolean
  distance_feet: number | null
  range_band: string
  blocked: boolean
  blocker_kind: string | null
  requires_dm_adjudication: boolean
  is_long_range: boolean
  target_within_5ft: boolean
}

export function checkTarget(
  roomId: string,
  campaignId: string,
  sessionId: string,
  body: TargetCheckInput,
  token: string,
): Promise<TargetCheckResult> {
  return request(`${tacticalBase(roomId, campaignId, sessionId)}/board/target-check`, token, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

// --- AoE preview (P5-D) ---

export type AoeTemplateInput = {
  shape: 'circle' | 'square' | 'cone' | 'line'
  size_feet: number
  origin_x: number
  origin_y: number
  aim_x?: number | null
  aim_y?: number | null
}

export type AoeCell = { x: number; y: number }

export type AoePreviewCandidate = {
  entry_id: string
  display_name: string
  subject_kind: string
}

export type AoeTemplateView = {
  shape: string
  size_feet: number
  origin_x: number
  origin_y: number
  aim_x: number | null
  aim_y: number | null
  direction: string | null
}

export type AoeSpellPreviewView = {
  combat_id: string
  caster_entry_id: string
  spell_ref: string
  board_revision: number
  template: AoeTemplateView
  affected_cells: AoeCell[]
  candidates: AoePreviewCandidate[]
}

export function previewAoeSpell(
  roomId: string,
  campaignId: string,
  sessionId: string,
  body: { caster_entry_id: string; spell_ref: string; template: AoeTemplateInput },
  token: string,
): Promise<AoeSpellPreviewView> {
  return request(`${tacticalBase(roomId, campaignId, sessionId)}/spells/aoe/preview`, token, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}
