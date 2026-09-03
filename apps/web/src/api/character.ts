import { createLocalizedRequestError } from '../i18n/systemMessages'

export type ResourceCounter = {
  used: number
  remaining: number
}

export type ConditionState = {
  condition_ref: string
  note?: string | null
}

export type PreparedSpellSelection = {
  spell_key: string
  source_profile_id: string
  source_access_entry_id?: string | null
}

export type InventoryStateEntry = {
  entry_id: string
  item_ref: string
  quantity: number
  equipped: boolean
  carried: boolean
}

export type ActiveInfusionState = {
  inventory_entry_id: string
  infusion_ref: string
  resource?: ResourceCounter | null
  arcane_armor_part?: 'armor' | 'boots' | 'helmet' | 'special_weapon' | null
}

export type SpellStoringItemState = {
  inventory_entry_id: string
  spell_ref: string
  remaining_uses: number
}

export type CharacterStatePatch = {
  expected_current_version_id?: string
  current_hp?: number
  temporary_hp?: number
  conditions?: ConditionState[]
  prepared_spell_entry_ids?: string[]
  prepared_spells?: PreparedSpellSelection[]
  spell_slots?: Record<string, ResourceCounter>
  resources?: Record<string, ResourceCounter>
  hit_dice_state?: Record<string, number>
  inventory_state?: InventoryStateEntry[]
  active_infusions?: ActiveInfusionState[]
  feature_modes?: Record<string, string>
  spell_storing_item?: SpellStoringItemState | null
}

export type AbilityDTO = {
  score: number
  modifier: number
}

export type ClassLevelDTO = {
  class_ref: string
  name: string
  level: number
}

export type HitDieDTO = {
  die: string
  total: number
  available: number
}

export type NamedReferenceDTO = {
  key: string
  name: string
}

export type ConditionDTO = {
  condition_ref: string
  name: string
  note?: string | null
}

export type SpellAccessDTO = {
  entry_id: string
  spell_key: string
  name: string
  source_type: string
  source_key: string
  access_type: 'known' | 'spellbook' | 'prepared' | 'always_prepared' | 'granted'
  prepared: boolean
  source_profile_id?: string | null
  source_access_entry_id?: string | null
  cast_at_level?: number | null
  waive_components?: string[]
  casting_modifiers?: string[]
  uses_spell_slot?: boolean | null
}

export type SpellcastingDTO = {
  source_key: string
  source_name: string
  ability: string
  save_dc: number
  attack_modifier: number
}

export type InventoryDTO = {
  entry_id: string
  item_ref: string
  name: string
  quantity: number
  equipped: boolean
  carried: boolean
  rules: Record<string, unknown>
}

export type FeatureModeDTO = {
  key: string
  source_feature_ref: string
  options: string[]
  default: string
  change_timing: string
}

export type ArtificerKnownInfusionDTO = {
  infusion_ref: string
  name: string
  minimum_artificer_level: number
  requires_attunement: boolean
  item_filters: string[]
  modifiers: Record<string, unknown>[]
  charge_capacity?: number | null
  replicates_item_ref?: string | null
  description: string
  manual_effects: string[]
}

export type ArtificerActiveInfusionDTO = {
  inventory_entry_id: string
  inventory_item_ref: string
  inventory_item_name: string
  infusion_ref: string
  infusion_name: string
  resource?: ResourceCounter | null
  arcane_armor_part?: string | null
  manual_effects: string[]
}

export type ArtificerTrackedResourceDTO = {
  resource_id: string
  feature_ref: string
  feature_name: string
  capacity: number
  used: number
  remaining: number
  recharge: string[]
  resolution: 'manual'
}

export type ArtificerSpellStoringItemDTO = {
  inventory_entry_id: string
  inventory_item_ref: string
  inventory_item_name: string
  spell_ref: string
  spell_name: string
  remaining_uses: number
  capacity: number
  cast_resolution: 'manual'
}

export type ArtificerManualFeatureDTO = {
  feature_ref: string
  feature_name: string
  runtime_kind: string
  resolution: 'manual' | 'state_tracked_effect_manual'
  metadata: Record<string, unknown>
}

export type ArtificerSummaryDTO = {
  artificer_level: number
  known_infusions: ArtificerKnownInfusionDTO[]
  known_infusion_limit: number
  active_infusions: ArtificerActiveInfusionDTO[]
  active_infusion_count: number
  active_infusion_base_capacity: number
  active_infusion_capacity_bonus: number
  active_infusion_capacity: number
  armor_modification_parts: string[]
  attunement_capacity: number
  attunement_requirement_bypasses: string[]
  tracked_resources: ArtificerTrackedResourceDTO[]
  armor_model?: string | null
  armor_model_options: string[]
  spell_storing_item_capacity: number
  spell_storing_item?: ArtificerSpellStoringItemDTO | null
  manual_features: ArtificerManualFeatureDTO[]
}

export type RoleplayProfile = {
  appearance?: string | null
  biography?: string | null
  personality_traits: string[]
  ideals: string[]
  bonds: string[]
  flaws: string[]
}

export type CharacterSheetDTO = {
  character_id: string
  current_version_id: string
  name: string
  ruleset: string
  version_no: number
  total_level: number
  classes: ClassLevelDTO[]
  proficiency_bonus: number
  abilities: Record<string, AbilityDTO>
  saving_throws: Record<string, number>
  skills: Record<string, number>
  passive_perception: number
  passive_investigation: number
  initiative_modifier: number
  armor_class: number
  walking_speed: number
  swim_speed?: number | null
  climb_speed?: number | null
  fly_speed?: number | null
  max_hp: number
  current_hp: number
  temporary_hp: number
  hit_dice: HitDieDTO[]
  features: NamedReferenceDTO[]
  feature_modes?: Record<string, string>
  feature_mode_definitions?: FeatureModeDTO[]
  conditions: ConditionDTO[]
  spells: SpellAccessDTO[]
  spellcasting: SpellcastingDTO[]
  spell_slots: Record<string, ResourceCounter>
  resources: Record<string, ResourceCounter>
  inventory: InventoryDTO[]
  artificer?: ArtificerSummaryDTO | null
  roleplay_profile: RoleplayProfile
}

export type ContentEntry = {
  key: string
  index: string
  name: string
  source: string
  ruleset: string
  license?: string | null
  data: Record<string, unknown>
}

type APIErrorPayload = {
  error?: {
    code?: string
    message?: string
  }
}

const characterVersionTokens = new Map<string, string>()

async function apiRequest<T>(input: RequestInfo | URL, init?: RequestInit): Promise<T> {
  const response = await fetch(input, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
    },
  })

  if (!response.ok) {
    let code: string | undefined
    let message = `Request failed (${response.status})`
    try {
      const payload = (await response.json()) as APIErrorPayload
      code = payload.error?.code
      message = payload.error?.message ?? message
    } catch {
      // Keep the HTTP fallback when the body is not JSON.
    }
    throw createLocalizedRequestError(code, response.status, message)
  }

  return (await response.json()) as T
}

export async function getCharacterSheet(characterId: string): Promise<CharacterSheetDTO> {
  const sheet = await apiRequest<CharacterSheetDTO>(`/api/characters/${characterId}/sheet`)
  characterVersionTokens.set(characterId, sheet.current_version_id)
  return sheet
}

export async function patchCharacterState(
  characterId: string,
  patch: CharacterStatePatch,
): Promise<CharacterSheetDTO> {
  const expectedVersion =
    patch.expected_current_version_id ?? characterVersionTokens.get(characterId)
  const body: CharacterStatePatch = expectedVersion
    ? { ...patch, expected_current_version_id: expectedVersion }
    : patch
  const sheet = await apiRequest<CharacterSheetDTO>(`/api/characters/${characterId}/state`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
  characterVersionTokens.set(characterId, sheet.current_version_id)
  return sheet
}

export function listContent(category: string): Promise<ContentEntry[]> {
  return apiRequest<ContentEntry[]>(`/api/rules/content/${category}`)
}