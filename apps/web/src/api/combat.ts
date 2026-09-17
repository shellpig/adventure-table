import { request, tableBase } from './sessions'

export type ConditionOrEffectItem =
  | string
  | {
      condition_ref?: string
      tag?: string
      effect_id?: string | null
    }

export function conditionLabel(entry: ConditionOrEffectItem): string {
  if (typeof entry === 'string') return entry
  return entry.condition_ref ?? entry.tag ?? ''
}

export type CombatEntryView = {
  id: string
  subject_kind: string
  character_id: string | null
  monster_instance_id: string | null
  display_name: string
  status: string
  initiative_group_key: string | null
  initiative_roll_request_id: string | null
  initiative_roll_result_id: string | null
  initiative_total: number | null
  turn_order: number | null
  surprised: boolean
  action_available: boolean
  bonus_action_available: boolean
  reaction_available: boolean
  attacks_allowed: number
  attacks_used: number
  ready_state: Record<string, unknown>
  pending_reaction_state: Record<string, unknown>
}

export type CombatView = {
  id: string
  campaign_id: string
  mode: string
  status: string
  round_number: number | null
  current_turn_entry_id: string | null
  revision: number
  entries: CombatEntryView[]
  warnings?: string[]
}

export type CombatantProjection = {
  id: string
  kind: string
  name: string
  combat_status: string
  conditions: ConditionOrEffectItem[]
  effects: ConditionOrEffectItem[]
  armor_class?: number | null
  max_hp?: number | null
  current_hp?: number | null
  temp_hp?: number | null
  injury_level?: string | null
  speed?: Record<string, unknown> | null
  initiative?: number | null
  visibility?: string | null
  resources?: Record<string, unknown> | null
  reaction_available?: boolean | null
  position_note?: string | null
  description?: string | null
  dm_notes?: string | null
  concentration?: Record<string, unknown> | null
  death_saves?: Record<string, unknown> | null
  exhaustion_level?: number | null
  traits?: Array<Record<string, unknown>> | null
  actions?: Array<Record<string, unknown>> | null
  bonus_actions?: Array<Record<string, unknown>> | null
  reactions?: Array<Record<string, unknown>> | null
  legendary_actions?: Array<Record<string, unknown>> | null
}

export type CombatantDetailView = {
  entry_id: string
  subject_kind: string
  is_hostile: boolean
  projection: CombatantProjection
}

export type CombatDetailView = CombatView & {
  combatants: CombatantDetailView[]
}

export function getActiveCombatDetail(
  roomId: string,
  campaignId: string,
  sessionId: string,
  token: string,
): Promise<CombatDetailView | null> {
  return request<CombatDetailView | null>(
    `${tableBase(roomId, campaignId, sessionId)}/combat/detail`,
    token,
  )
}

export type StartCombatInput = {
  include_active_party?: boolean
  idempotency_key: string
}

export type CombatMutationInput = {
  idempotency_key: string
}

export type AddMonsterInput = {
  monster_instance_id: string
  surprised?: boolean
  initiative_group_key?: string | null
  idempotency_key: string
}

export type RequestInitiativeInput = {
  entry_ids?: string[]
  modifier_mode?: 'normal' | 'advantage' | 'disadvantage'
  idempotency_key: string
}

export type RollInitiativeInput = {
  roll_request_id: string
  source: 'server'
  idempotency_key: string
}

export type FinalizeInitiativeInput = {
  ordered_entry_ids: string[]
  idempotency_key: string
}

export type CreateMonsterFromContentInput = {
  content_key: string
  name?: string | null
  visibility?: 'public' | 'hidden'
  position_note?: string | null
  idempotency_key: string
}

export type QuickEnemyAttackInput = {
  name: string
  attack_bonus?: number | null
  damage: string
  attack_kind?: string | null
}

export type CreateQuickEnemyInput = {
  name: string
  armor_class: number
  max_hp: number
  speed?: Record<string, string>
  attack?: QuickEnemyAttackInput | null
  visibility?: 'public' | 'hidden'
  position_note?: string | null
  idempotency_key: string
}

export type MonsterInstanceView = {
  id: string
  campaign_id: string
  name: string
  current_hp: number
  max_hp: number
  armor_class?: number | null
  visibility: string
  position_note?: string | null
}

export type InitiativeRequestView = {
  id: string
  roll_group_id: string
  target_seat_id: string | null
  target_character_id: string | null
  target_combat_entry_id: string
  request_type: string
  ability_ref: string | null
  modifier_mode: string
  flat_adjustment: number
  status: string
  grouped_entry_ids: string[]
}

export type InitiativeRequestResponse = {
  roll_group_id: string
  requests: InitiativeRequestView[]
}

export type InitiativeRollResponse = {
  result_id: string
  roll_request_id: string
  total: number
  combat_entry_ids: string[]
}

const combatBase = (roomId: string, campaignId: string, sessionId: string) =>
  `${tableBase(roomId, campaignId, sessionId)}/combat`

const monsterInstancesBase = (roomId: string, campaignId: string, sessionId: string) =>
  `${tableBase(roomId, campaignId, sessionId)}/monster-instances`

export function startCombat(
  roomId: string,
  campaignId: string,
  sessionId: string,
  body: StartCombatInput,
  token: string,
): Promise<CombatView> {
  return request(`${combatBase(roomId, campaignId, sessionId)}/start`, token, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function endCombat(
  roomId: string,
  campaignId: string,
  sessionId: string,
  body: CombatMutationInput,
  token: string,
): Promise<CombatView> {
  return request(`${combatBase(roomId, campaignId, sessionId)}/end`, token, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function addMonsterToCombat(
  roomId: string,
  campaignId: string,
  sessionId: string,
  body: AddMonsterInput,
  token: string,
): Promise<CombatView> {
  return request(`${combatBase(roomId, campaignId, sessionId)}/entries/monsters`, token, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function requestInitiative(
  roomId: string,
  campaignId: string,
  sessionId: string,
  body: RequestInitiativeInput,
  token: string,
): Promise<InitiativeRequestResponse> {
  return request(`${combatBase(roomId, campaignId, sessionId)}/initiative/request`, token, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function rollInitiative(
  roomId: string,
  campaignId: string,
  sessionId: string,
  body: RollInitiativeInput,
  token: string,
): Promise<InitiativeRollResponse> {
  return request(`${combatBase(roomId, campaignId, sessionId)}/initiative/roll`, token, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function getSuggestedInitiativeOrder(
  roomId: string,
  campaignId: string,
  sessionId: string,
  token: string,
): Promise<string[]> {
  return request(`${combatBase(roomId, campaignId, sessionId)}/initiative/suggested-order`, token)
}

export function finalizeInitiative(
  roomId: string,
  campaignId: string,
  sessionId: string,
  body: FinalizeInitiativeInput,
  token: string,
): Promise<CombatView> {
  return request(`${combatBase(roomId, campaignId, sessionId)}/initiative/finalize`, token, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function advanceTurn(
  roomId: string,
  campaignId: string,
  sessionId: string,
  body: CombatMutationInput,
  token: string,
): Promise<CombatView> {
  return request(`${combatBase(roomId, campaignId, sessionId)}/turn/advance`, token, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function createMonsterFromContent(
  roomId: string,
  campaignId: string,
  sessionId: string,
  body: CreateMonsterFromContentInput,
  token: string,
): Promise<MonsterInstanceView> {
  return request(`${monsterInstancesBase(roomId, campaignId, sessionId)}/from-content`, token, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function createQuickEnemy(
  roomId: string,
  campaignId: string,
  sessionId: string,
  body: CreateQuickEnemyInput,
  token: string,
): Promise<MonsterInstanceView> {
  return request(`${monsterInstancesBase(roomId, campaignId, sessionId)}/quick-enemy`, token, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

