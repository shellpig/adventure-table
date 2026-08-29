export type BuilderMode = 'create' | 'level_up' | 'build_edit' | 'correction'
export type BuilderIssueSeverity = 'blocking_error' | 'warning' | 'non_standard'
export type AbilityGenerationMethod = 'standard_array' | 'point_buy' | 'manual'
export type BuilderHPMethod = 'first_level' | 'fixed_average' | 'manual_rolled'
export type BuilderSpellAccessModel = 'known' | 'prepared' | 'spellbook'
export type BuilderSpellResourcePoolType = 'normal_multiclass_slots' | 'pact_magic'
export type BuilderOptionKind =
  | 'reference'
  | 'counted_reference'
  | 'nested_choice'
  | 'category_filter'
  | 'branch'

export type BuilderBasicInput = {
  name?: string | null
  ruleset?: 'dnd5e-2014'
}

export type BuilderReferenceSelection = {
  reference_id: string
  source_ref?: string | null
}

export type BuilderAbilityScores = {
  strength: number
  dexterity: number
  constitution: number
  intelligence: number
  wisdom: number
  charisma: number
}

export type BuilderAbilityGenerationInput = {
  method: AbilityGenerationMethod
  scores: BuilderAbilityScores
  provenance?: string | null
}

export type BuilderLevelChoice = {
  character_level: number
  class_ref: string
  hp_method: BuilderHPMethod
  hp_base_gain: number
  subclass_ref?: string | null
}

export type AbilityGenerationRules = {
  standard_array: number[]
  point_buy_budget: number
  point_buy_costs: Record<string, number>
  manual_standard_min: number
  manual_standard_max: number
  hard_min: number
  hard_max: number
}

export type BuilderChoiceSelection = {
  choice_id: string
  selected_option_ids?: string[]
  source_ref?: string | null
  provenance_path?: string | null
}

export type BuilderSpellChoiceInput = {
  cantrip_keys?: string[]
  known_spell_keys?: string[]
  spellbook_spell_keys?: string[]
  prepared_spell_keys?: string[]
}

export type BuilderDraftPayload = {
  basic?: BuilderBasicInput | null
  target_level?: number | null
  race_selection?: BuilderReferenceSelection | null
  subrace_selection?: BuilderReferenceSelection | null
  background_selection?: BuilderReferenceSelection | null
  alignment_selection?: BuilderReferenceSelection | null
  ability_generation?: BuilderAbilityGenerationInput | null
  level_choices?: BuilderLevelChoice[]
  choice_selections?: Record<string, BuilderChoiceSelection>
  spell_choices?: Record<string, BuilderSpellChoiceInput>
  starting_equipment_choices?: Record<string, unknown>
  roleplay_profile?: Record<string, unknown>
  numeric_overrides?: { key: string; value: number }[]
  initial_state_seed?: Record<string, unknown>
}

export type BuilderDraft = {
  id: string
  mode: BuilderMode
  character_id?: string | null
  base_version_id?: string | null
  revision: number
  draft_payload: BuilderDraftPayload
  created_at: string
  updated_at: string
}

export type BuilderIssue = {
  code: string
  severity: BuilderIssueSeverity
  path: string
  message: string
  related_refs: string[]
}

export type BuilderValidationResult = {
  issues: BuilderIssue[]
  can_confirm: boolean
  non_standard_count: number
}

export type BuilderChoiceOption = {
  option_id: string
  label: string
  kind: BuilderOptionKind
  reference_id?: string | null
  count?: number | null
  category?: string | null
  nested_choice_id?: string | null
  branch_key?: string | null
  disabled_reason?: string | null
  hit_die_size?: number | null
  fixed_hp_gain?: number | null
}

export type BuilderChoice = {
  choice_id: string
  label: string
  source_ref?: string | null
  required: boolean
  choose_count: number
  option_source?: string | null
  options: BuilderChoiceOption[]
  selected_option_ids: string[]
  disabled_reason?: string | null
  allow_duplicates: boolean
}

export type BuilderGrantSummary = {
  label: string
  kind: string
  source_ref: string
  reference_id?: string | null
}

export type BuilderAbilityScoreSummary = {
  ability: string
  base: number
  permanent_bonus: number
  resolved: number
  effective: number
  overridden: boolean
}

export type BuilderProgressionNodeSummary = {
  character_level: number
  class_ref: string
  class_name: string
  class_level: number
  starting_class: boolean
  multiclass_entry: boolean
  hit_die_size: number
  fixed_hp_gain: number
  hp_method: BuilderHPMethod
  hp_base_gain: number
  subclass_required: boolean
  subclass_ref?: string | null
  subclass_name?: string | null
  automatic_feature_refs: string[]
}

export type BuilderSpellOptionSummary = {
  spell_key: string
  name: string
  level: number
}

export type BuilderSpellcastingProfileSummary = {
  profile_id: string
  source_type: string
  source_key: string
  source_name: string
  class_ref: string
  ability: string
  access_model: BuilderSpellAccessModel
  class_level: number
  max_spell_level: number
  cantrip_count: number
  known_spell_count: number
  spellbook_count: number
  prepared_limit?: number | null
  resource_pool_type: BuilderSpellResourcePoolType
  available_spells: BuilderSpellOptionSummary[]
  selected_cantrip_keys: string[]
  selected_known_spell_keys: string[]
  selected_spellbook_spell_keys: string[]
  selected_prepared_spell_keys: string[]
}

export type BuilderSpellSlotCapacity = {
  level: number
  count: number
}

export type BuilderSpellResourcePoolSummary = {
  pool_id: string
  pool_type: BuilderSpellResourcePoolType
  source_profile_id?: string | null
  slots: BuilderSpellSlotCapacity[]
}

export type BuilderResolvedSummary = {
  name?: string | null
  target_level?: number | null
  race_name?: string | null
  subrace_name?: string | null
  background_name?: string | null
  alignment_name?: string | null
  starting_class_name?: string | null
  class_summary?: string | null
  selected_reference_count: number
  choice_selection_count: number
  grants: BuilderGrantSummary[]
  ability_scores: BuilderAbilityScoreSummary[]
  progression: BuilderProgressionNodeSummary[]
  spellcasting_profiles: BuilderSpellcastingProfileSummary[]
  spell_resource_pools: BuilderSpellResourcePoolSummary[]
}

export type BuilderView = {
  draft: BuilderDraft
  resolved_summary: BuilderResolvedSummary
  choices: BuilderChoice[]
  validation: BuilderValidationResult
}

export type BuilderEquipmentSummary = {
  entry_id: string
  item_ref: string
  name: string
  quantity: number
  source_ref: string
}

export type BuilderInitialStatePreview = {
  current_hp: number
  temporary_hp: number
  conditions: unknown[]
  prepared_spell_entry_ids: string[]
  prepared_spells: unknown[]
  spell_slots: Record<string, { used: number; remaining: number }>
  resources: Record<string, { used: number; remaining: number }>
  hit_dice_state: Record<string, number>
  inventory_state: {
    entry_id: string
    item_ref: string
    quantity: number
    equipped: boolean
    carried: boolean
  }[]
}

export type BuilderReviewDTO = {
  draft_id: string
  resolved_summary: BuilderResolvedSummary
  build_candidate?: unknown | null
  initial_state?: BuilderInitialStatePreview | null
  starting_equipment: BuilderEquipmentSummary[]
  issues: BuilderIssue[]
  can_confirm: boolean
  non_standard_count: number
}

export type BuilderConfirmResult = {
  character_id: string
  current_version_id: string
  version_no: number
  character_path: string
}

export type CharacterListItem = {
  id: string
  name: string
  level: number
  class_summary: string
  version_no: number
}

type APIErrorPayload = {
  error?: { code?: string; message?: string }
}

type BuilderPatchQueue = {
  tail: Promise<void>
  latestRevision?: number
}

// Builder drafts use optimistic revision checks on the server. React can dispatch
// a second interaction before the first mutation's pending state has rendered,
// so serialize PATCHes per draft and carry the revision returned by the previous
// write into the next queued write. This keeps rapid level-rail edits lossless
// without weakening the server's conflict protection against other clients.
const builderPatchQueues = new Map<string, BuilderPatchQueue>()

async function builderRequest<T>(input: RequestInfo | URL, init?: RequestInit): Promise<T> {
  const response = await fetch(input, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!response.ok) {
    let message = `Request failed (${response.status})`
    try {
      const payload = (await response.json()) as APIErrorPayload
      message = payload.error?.message ?? message
    } catch {
      // Keep the HTTP fallback when the body is not JSON.
    }
    throw new Error(message)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export function listCharacters(): Promise<CharacterListItem[]> {
  return builderRequest<CharacterListItem[]>('/api/characters')
}

export function getAbilityGenerationRules(): Promise<AbilityGenerationRules> {
  return builderRequest<AbilityGenerationRules>('/api/character-builder/rules/ability-generation')
}

export function createBuilderDraft(draftPayload: BuilderDraftPayload = {}): Promise<BuilderView> {
  return builderRequest<BuilderView>('/api/character-builder/drafts', {
    method: 'POST',
    body: JSON.stringify({ mode: 'create', draft_payload: draftPayload }),
  })
}

export function listCreateBuilderDrafts(): Promise<BuilderView[]> {
  return builderRequest<BuilderView[]>('/api/character-builder/drafts')
}

export function getBuilderDraft(draftId: string): Promise<BuilderView> {
  return builderRequest<BuilderView>(`/api/character-builder/drafts/${draftId}`)
}

export function patchBuilderDraft(
  draftId: string,
  expectedRevision: number,
  draftPayload: BuilderDraftPayload,
): Promise<BuilderView> {
  let queue = builderPatchQueues.get(draftId)
  if (!queue) {
    queue = { tail: Promise.resolve(), latestRevision: expectedRevision }
    builderPatchQueues.set(draftId, queue)
  }

  const run = queue.tail
    .catch(() => undefined)
    .then(async () => {
      const revision = Math.max(expectedRevision, queue?.latestRevision ?? expectedRevision)
      const view = await builderRequest<BuilderView>(`/api/character-builder/drafts/${draftId}`, {
        method: 'PATCH',
        body: JSON.stringify({ expected_revision: revision, draft_payload: draftPayload }),
      })
      if (queue) queue.latestRevision = view.draft.revision
      return view
    })

  queue.tail = run.then(
    () => undefined,
    () => undefined,
  )
  return run
}

export function validateBuilderDraft(draftId: string): Promise<BuilderValidationResult> {
  return builderRequest<BuilderValidationResult>(
    `/api/character-builder/drafts/${draftId}/validate`,
    { method: 'POST' },
  )
}

export function getBuilderReview(draftId: string): Promise<BuilderReviewDTO> {
  return builderRequest<BuilderReviewDTO>(
    `/api/character-builder/drafts/${draftId}/review`,
  )
}

export function confirmBuilderDraft(draftId: string): Promise<BuilderConfirmResult> {
  return builderRequest<BuilderConfirmResult>(
    `/api/character-builder/drafts/${draftId}/confirm`,
    { method: 'POST' },
  ).then((result) => {
    builderPatchQueues.delete(draftId)
    return result
  })
}

export function cancelBuilderDraft(draftId: string): Promise<void> {
  builderPatchQueues.delete(draftId)
  return builderRequest<void>(`/api/character-builder/drafts/${draftId}`, { method: 'DELETE' })
}
