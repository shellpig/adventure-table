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
  reveal?: {
    armor_class: boolean
    description: boolean
    position_note: boolean
  } | null
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

export type FormalRollInput = {
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

export type MonsterOutcome = 'dead' | 'unconscious' | 'surrendered' | 'fled' | 'other'

export type MonsterOutcomeInput = {
  outcome: MonsterOutcome
  note?: string | null
  idempotency_key: string
}

export type MonsterRevealPatch = {
  armor_class?: boolean
  description?: boolean
  position_note?: boolean
}

export type MonsterInstancePatchInput = {
  name?: string
  visibility?: 'public' | 'hidden'
  position_note?: string | null
  reveal?: MonsterRevealPatch
  idempotency_key: string
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

export type AttackRequestInput = {
  attacker_entry_id: string
  target_entry_id: string
  source_ref: string
  modifier_mode?: 'normal' | 'advantage' | 'disadvantage'
  range_confirmed?: boolean | null
  idempotency_key?: string | null
}

export type AttackAdjudicationInput = {
  action_id: string
  in_range: boolean
  roll_mode?: 'normal' | 'advantage' | 'disadvantage' | null
  note?: string | null
  idempotency_key?: string | null
}

export type AttackDefinitionView = {
  source_ref: string
  name: string
  attack_bonus: number
  attack_kind: string
  damage_parts: Array<Record<string, unknown>>
  modifier_sources: Array<Record<string, unknown>>
  notes: string[]
  content_ref?: string | null
  presentation_field?: string | null
}

export type CastableSpellView = {
  spell_ref: string
  name: string
  level: number
  profile_id: string | null
  concentration: boolean
  targeting: 'single' | 'self' | 'aoe'
  cast_mode: 'attack' | 'save' | 'heal' | 'utility'
  castable_slot_levels: number[]
}

export type SpellCastView = {
  action_id: string
  combat_id: string
  caster_entry_id: string
  target_entry_id: string | null
  spell_ref: string
  cast_mode: string
  status: string
  roll_request_id: string | null
  roll_result_id: string | null
  resolution_result?: Record<string, unknown> | null
}

export type AoeSpellProposalView = {
  action_id: string
  combat_id: string
  caster_entry_id: string
  spell_ref: string
  status: string
  proposed_target_ids: string[]
}

export type AoeSpellResolutionView = {
  action_id: string
  combat_id: string
  caster_entry_id: string
  spell_ref: string
  status: string
  confirmed_target_ids: string[]
  resolution_result?: Record<string, unknown> | null
}

export type CastSpellInput = {
  caster_entry_id: string
  target_entry_id?: string | null
  spell_ref: string
  slot_level?: number | null
  profile_id?: string | null
  attack_mode?: 'normal' | 'advantage' | 'disadvantage'
  idempotency_key?: string | null
}

export type ProposeAoeSpellInput = {
  caster_entry_id: string
  spell_ref: string
  slot_level?: number | null
  profile_id?: string | null
  proposed_target_ids: string[]
  idempotency_key?: string | null
}

export type ResolveAoeSpellInput = {
  action_id: string
  confirmed_target_ids: string[]
  idempotency_key?: string | null
}

export type AttackRequestView = {
  action_id: string
  combat_id: string
  attacker_entry_id: string
  target_entry_id: string
  roll_request_id: string | null
  source_ref: string
  name: string
  modifier_mode: string
  attack_bonus: number
  target_ac: number
  status: string
  in_range?: boolean | null
  resolution_result?: Record<string, unknown> | null
}

export type AttackResolutionView = {
  action_id: string
  roll_request_id: string
  roll_result_id: string
  attacker_entry_id: string
  target_entry_id: string
  hit: boolean
  critical: boolean
  attack_total: number
  target_ac?: number | null
  damage_total: number
  before_hp?: number | null
  after_hp?: number | null
  target_is_hostile?: boolean
  target_injury_level?: string | null
  resolution_result: Record<string, unknown>
}

export type SavingThrowResultView = {
  result_id: string
  roll_request_id: string
  target_entry_id: string
  total: number
  succeeded: boolean
}

export type DeathSaveResultView = {
  combat_action_id: string
  result_id: string
  roll_request_id: string
  entry_id: string
  d20: number
  current_hp: number
  successes: number
  failures: number
  stable: boolean
  dead: boolean
  natural_20_recovery: boolean
}

export type ConcentrationCheckResultView = {
  result_id: string
  roll_request_id: string
  target_entry_id: string
  d20: number
  modifier: number
  total: number
  dc: number
  succeeded: boolean
  linked_effect_ids: string[]
  linked_effects_removed_from: Array<Record<string, unknown>>
}

export type SpecialAttackView = {
  action_id: string
  combat_id: string
  attacker_entry_id: string
  target_entry_id: string
  kind: 'grapple' | 'shove'
  status: string
  in_reach: boolean | null
  attacker_roll_request_id: string | null
  defender_roll_request_id: string | null
  attacker_skill: string
  defender_skill: string
  resolution_result: Record<string, unknown> | null
}

export type SpecialAttackRequestInput = {
  attacker_entry_id: string
  target_entry_id: string
  kind: 'grapple' | 'shove'
  attacker_modifier_mode?: 'normal' | 'advantage' | 'disadvantage'
  defender_modifier_mode?: 'normal' | 'advantage' | 'disadvantage'
  idempotency_key?: string | null
}

export type SpecialAttackAdjudicationInput = {
  action_id: string
  in_reach: boolean
  idempotency_key?: string | null
}

export type ReactionKind =
  'opportunity_attack' | 'shield' | 'counterspell' | 'ready' | 'legendary_action' | 'other'

export type ReactionWindowView = {
  window_id: string
  entry_id: string
  kind: ReactionKind
  reason: string
  source_entry_id: string | null
  status: string
  eligible_entry_ids: string[]
  target_entry_id: string | null
  safe_payload: Record<string, unknown> | null
}

export type ResolveReactionInput = {
  owner_entry_id: string
  actor_entry_id?: string | null
  accept: boolean
  idempotency_key?: string | null
}

export type ReactionResolutionView = {
  combat_id: string
  entry_id: string
  actor_entry_id: string
  accepted: boolean
  status: string
  window_id: string
  kind: ReactionKind
}

export type CombatAdjudicationView = {
  action_id: string
  kind: 'range' | 'reach' | 'affected_targets' | 'opportunity_attack' | 'special'
  status: 'pending' | 'resolved' | 'cancelled'
  subject_entry_id: string
  subject_seat_id: string | null
  proposed_target_entry_ids: string[]
  question?: string | null
  decision?: Record<string, unknown> | null
  note?: string | null
  dm_hints?: Record<string, unknown> | null
  created_at: string
}

export type OpportunityAttackRequestInput = {
  mover_entry_id: string
  reactor_entry_id: string
  question?: string | null
  idempotency_key?: string | null
}

export type SpecialAdjudicationRequestInput = {
  subject_entry_id: string
  target_entry_ids?: string[]
  question: string
  idempotency_key?: string | null
}

export type AdjudicationDecisionInput = {
  trigger?: boolean | null
  ruling?: string | null
  idempotency_key?: string | null
}

export type CombatPendingRollView = {
  id: string
  roll_group_id: string | null
  label: string | null
  request_type: string
  target_entry_id: string
  target_seat_id: string | null
  ability_ref: string | null
  dc: number | null
  modifier_mode: 'normal' | 'advantage' | 'disadvantage'
  status: string
}

const combatBase = (roomId: string, campaignId: string, sessionId: string) =>
  `${tableBase(roomId, campaignId, sessionId)}/combat`

const specialAttacksBase = (roomId: string, campaignId: string, sessionId: string) =>
  `${combatBase(roomId, campaignId, sessionId)}/special-attacks`

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
  body: FormalRollInput,
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

export function listAttacks(
  roomId: string,
  campaignId: string,
  sessionId: string,
  entryId: string,
  token: string,
): Promise<AttackDefinitionView[]> {
  return request(`${combatBase(roomId, campaignId, sessionId)}/entries/${entryId}/attacks`, token)
}

export function listCastableSpells(
  roomId: string,
  campaignId: string,
  sessionId: string,
  entryId: string,
  token: string,
): Promise<CastableSpellView[]> {
  return request(`${combatBase(roomId, campaignId, sessionId)}/entries/${entryId}/spells`, token)
}

export function castSpell(
  roomId: string,
  campaignId: string,
  sessionId: string,
  body: CastSpellInput,
  token: string,
): Promise<SpellCastView> {
  return request(`${combatBase(roomId, campaignId, sessionId)}/spells/cast`, token, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function proposeAoeSpell(
  roomId: string,
  campaignId: string,
  sessionId: string,
  body: ProposeAoeSpellInput,
  token: string,
): Promise<AoeSpellProposalView> {
  return request(`${combatBase(roomId, campaignId, sessionId)}/spells/aoe/propose`, token, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function resolveAoeSpell(
  roomId: string,
  campaignId: string,
  sessionId: string,
  body: ResolveAoeSpellInput,
  token: string,
): Promise<AoeSpellResolutionView> {
  return request(`${combatBase(roomId, campaignId, sessionId)}/spells/aoe/resolve`, token, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function requestAttack(
  roomId: string,
  campaignId: string,
  sessionId: string,
  body: AttackRequestInput,
  token: string,
): Promise<AttackRequestView> {
  return request(`${combatBase(roomId, campaignId, sessionId)}/attacks/request`, token, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function rollAttack(
  roomId: string,
  campaignId: string,
  sessionId: string,
  body: FormalRollInput,
  token: string,
): Promise<AttackResolutionView> {
  return request(`${combatBase(roomId, campaignId, sessionId)}/attacks/roll`, token, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function rollSavingThrow(
  roomId: string,
  campaignId: string,
  sessionId: string,
  body: FormalRollInput,
  token: string,
): Promise<SavingThrowResultView> {
  return request(`${combatBase(roomId, campaignId, sessionId)}/saving-throws/roll`, token, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function rollDeathSave(
  roomId: string,
  campaignId: string,
  sessionId: string,
  body: FormalRollInput,
  token: string,
): Promise<DeathSaveResultView> {
  return request(`${combatBase(roomId, campaignId, sessionId)}/death-saves/roll`, token, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function rollConcentration(
  roomId: string,
  campaignId: string,
  sessionId: string,
  body: FormalRollInput,
  token: string,
): Promise<ConcentrationCheckResultView> {
  return request(`${combatBase(roomId, campaignId, sessionId)}/concentration/roll`, token, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function rollSpecialAttack(
  roomId: string,
  campaignId: string,
  sessionId: string,
  body: FormalRollInput,
  token: string,
): Promise<SpecialAttackView> {
  return request(`${specialAttacksBase(roomId, campaignId, sessionId)}/roll`, token, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function requestSpecialAttack(
  roomId: string,
  campaignId: string,
  sessionId: string,
  body: SpecialAttackRequestInput,
  token: string,
): Promise<SpecialAttackView> {
  return request(`${specialAttacksBase(roomId, campaignId, sessionId)}/request`, token, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function adjudicateSpecialAttack(
  roomId: string,
  campaignId: string,
  sessionId: string,
  body: SpecialAttackAdjudicationInput,
  token: string,
): Promise<SpecialAttackView> {
  return request(`${specialAttacksBase(roomId, campaignId, sessionId)}/adjudicate`, token, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function getReactionWindow(
  roomId: string,
  campaignId: string,
  sessionId: string,
  entryId: string,
  token: string,
): Promise<ReactionWindowView | null> {
  return request(`${combatBase(roomId, campaignId, sessionId)}/entries/${entryId}/reaction`, token)
}

export function resolveReaction(
  roomId: string,
  campaignId: string,
  sessionId: string,
  body: ResolveReactionInput,
  token: string,
): Promise<ReactionResolutionView> {
  return request(`${combatBase(roomId, campaignId, sessionId)}/reactions/resolve`, token, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function adjudicateAttackRange(
  roomId: string,
  campaignId: string,
  sessionId: string,
  body: AttackAdjudicationInput,
  token: string,
): Promise<AttackRequestView> {
  return request(`${combatBase(roomId, campaignId, sessionId)}/attacks/adjudicate`, token, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function listAdjudications(
  roomId: string,
  campaignId: string,
  sessionId: string,
  token: string,
): Promise<CombatAdjudicationView[]> {
  return request(`${combatBase(roomId, campaignId, sessionId)}/adjudications`, token)
}

export function listPendingCombatRolls(
  roomId: string,
  campaignId: string,
  sessionId: string,
  token: string,
): Promise<CombatPendingRollView[]> {
  return request(`${combatBase(roomId, campaignId, sessionId)}/pending-rolls`, token)
}

export function requestOpportunityAttack(
  roomId: string,
  campaignId: string,
  sessionId: string,
  body: OpportunityAttackRequestInput,
  token: string,
): Promise<CombatAdjudicationView> {
  return request(
    `${combatBase(roomId, campaignId, sessionId)}/adjudications/opportunity-attack`,
    token,
    { method: 'POST', body: JSON.stringify(body) },
  )
}

export function requestSpecialAdjudication(
  roomId: string,
  campaignId: string,
  sessionId: string,
  body: SpecialAdjudicationRequestInput,
  token: string,
): Promise<CombatAdjudicationView> {
  return request(`${combatBase(roomId, campaignId, sessionId)}/adjudications/special`, token, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function resolveAdjudication(
  roomId: string,
  campaignId: string,
  sessionId: string,
  actionId: string,
  body: AdjudicationDecisionInput,
  token: string,
): Promise<CombatAdjudicationView> {
  return request(
    `${combatBase(roomId, campaignId, sessionId)}/adjudications/${actionId}/resolve`,
    token,
    { method: 'POST', body: JSON.stringify(body) },
  )
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

export function setMonsterOutcome(
  roomId: string,
  campaignId: string,
  sessionId: string,
  entryId: string,
  body: MonsterOutcomeInput,
  token: string,
): Promise<CombatView> {
  return request(`${combatBase(roomId, campaignId, sessionId)}/entries/${entryId}/outcome`, token, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function updateMonsterInstance(
  roomId: string,
  campaignId: string,
  sessionId: string,
  instanceId: string,
  body: MonsterInstancePatchInput,
  token: string,
): Promise<MonsterInstanceView> {
  return request(`${monsterInstancesBase(roomId, campaignId, sessionId)}/${instanceId}`, token, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}
