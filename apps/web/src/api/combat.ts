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
