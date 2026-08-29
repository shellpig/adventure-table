export type ResourceCounter = {
  used: number
  remaining: number
}

export type ConditionState = {
  condition_ref: string
  note?: string | null
}

export type InventoryStateEntry = {
  entry_id: string
  item_ref: string
  quantity: number
  equipped: boolean
  carried: boolean
}

export type CharacterStatePatch = {
  current_hp?: number
  temporary_hp?: number
  conditions?: ConditionState[]
  prepared_spell_entry_ids?: string[]
  spell_slots?: Record<string, ResourceCounter>
  resources?: Record<string, ResourceCounter>
  hit_dice_state?: Record<string, number>
  inventory_state?: InventoryStateEntry[]
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
  access_type: 'known' | 'spellbook' | 'always_prepared' | 'granted'
  prepared: boolean
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
  initiative_modifier: number
  armor_class: number
  max_hp: number
  current_hp: number
  temporary_hp: number
  hit_dice: HitDieDTO[]
  features: NamedReferenceDTO[]
  conditions: ConditionDTO[]
  spells: SpellAccessDTO[]
  spellcasting: SpellcastingDTO[]
  spell_slots: Record<string, ResourceCounter>
  resources: Record<string, ResourceCounter>
  inventory: InventoryDTO[]
  roleplay_profile: RoleplayProfile
}

export type ContentEntry = {
  key: string
  index: string
  name: string
  source: string
  ruleset: string
  license: string
  data: Record<string, unknown>
}

type APIErrorPayload = {
  error?: {
    code?: string
    message?: string
  }
}

async function apiRequest<T>(input: RequestInfo | URL, init?: RequestInit): Promise<T> {
  const response = await fetch(input, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
    },
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

  return (await response.json()) as T
}

export function getCharacterSheet(characterId: string): Promise<CharacterSheetDTO> {
  return apiRequest<CharacterSheetDTO>(`/api/characters/${characterId}/sheet`)
}

export function patchCharacterState(
  characterId: string,
  patch: CharacterStatePatch,
): Promise<CharacterSheetDTO> {
  return apiRequest<CharacterSheetDTO>(`/api/characters/${characterId}/state`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  })
}

export function listContent(category: string): Promise<ContentEntry[]> {
  return apiRequest<ContentEntry[]>(`/api/rules/content/${category}`)
}
