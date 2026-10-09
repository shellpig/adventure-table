export type MonsterSourceKind = 'builtin' | 'custom'

export type MonsterLibrarySummaryView = {
  ref: string
  name: string
  names: Record<string, string>
  name_is_custom: boolean
  source_kind: MonsterSourceKind
  source_key?: string | null
  size?: string | null
  type?: string | null
  alignment?: string | null
  armor_class?: number | null
  max_hp?: number | null
  challenge_rating?: number | null
  walk_speed?: number | null
  archived_at?: string | null
  revision?: number | null
}

export type MonsterAbilityScores = {
  strength: number
  dexterity: number
  constitution: number
  intelligence: number
  wisdom: number
  charisma: number
}

export type MonsterTrait = {
  name: string
  desc?: string | null
}

export type MonsterActionItem = {
  name: string
  desc?: string | null
  attack_bonus?: number | null
  damage_dice?: string | null
  damage_type?: string | null
}

export type MonsterRules = {
  name: string
  armor_class: number
  max_hp: number
  size: string
  type: string
  alignment: string
  speed: string | Record<string, string>
  ability_scores: MonsterAbilityScores
  hit_dice?: string | null
  hit_points_roll?: string | null
  challenge_rating?: number | null
  xp?: number | null
  proficiencies?: Array<Record<string, unknown>>
  damage_vulnerabilities?: string[]
  damage_resistances?: string[]
  damage_immunities?: string[]
  condition_immunities?: string[]
  senses?: Record<string, unknown> | null
  languages?: string | null
  traits?: MonsterTrait[]
  actions?: MonsterActionItem[]
  bonus_actions?: MonsterActionItem[]
  reactions?: MonsterActionItem[]
  legendary_actions?: MonsterActionItem[]
  description?: string | null
}

export type MonsterPresentation = {
  names?: Record<string, string>
  name_is_custom?: boolean
  desc_is_english?: boolean
  ability_names?: Record<string, Array<{ en: string; 'zh-TW'?: string }>>
}

export type MonsterLibraryDetailView = {
  ref: string
  name: string
  names: Record<string, string>
  name_is_custom: boolean
  source_kind: MonsterSourceKind
  source_key?: string | null
  rules: MonsterRules
  presentation: MonsterPresentation
  revision?: number | null
  archived_at?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export type CustomMonsterTraitInput = {
  name: string
  desc?: string | null
  description?: string | null
  attack_bonus?: number | null
  damage?: Array<Record<string, unknown>> | null
  dc?: Record<string, unknown> | null
  usage?: Record<string, unknown> | null
  spellcasting?: Record<string, unknown> | null
  desc_is_english?: boolean | null
  is_english_source?: boolean | null
  names?: Record<string, string> | null
}

export type CustomMonsterActionInput = {
  name: string
  names?: Record<string, string> | null
  desc?: string | null
  description?: string | null
  kind?: 'attack' | 'save' | 'utility' | 'other' | null
  attack_kind?:
    | 'melee_weapon'
    | 'ranged_weapon'
    | 'melee_spell'
    | 'ranged_spell'
    | 'melee'
    | 'ranged'
    | null
  attack_bonus?: number | null
  target?: string | null
  range_normal?: number | null
  range_long?: number | null
  reach?: number | null
  damage_dice?: string | null
  damage_type?: string | null
  damage_parts?: Array<Record<string, unknown>> | null
  save_ability?: string | null
  save_dc?: number | null
  automation_level?: 'structured' | 'partial' | 'dm_adjudication' | null
}

export type PatchCustomMonsterTraitInput = CustomMonsterTraitInput & {
  source_index?: number | null
}

export type PatchCustomMonsterActionInput = CustomMonsterActionInput & {
  source_index?: number | null
}

export type CreateCustomMonsterInput = {
  name: string
  armor_class: number
  max_hp: number
  speed?: Record<string, string> | string
  size?: string
  type?: string
  alignment?: string
  hit_dice?: string | null
  hit_points_roll?: string | null
  ability_scores?: Record<string, number> | null
  proficiencies?: Array<Record<string, unknown>> | null
  damage_vulnerabilities?: string[] | null
  damage_resistances?: string[] | null
  damage_immunities?: string[] | null
  condition_immunities?: Array<Record<string, unknown> | string> | null
  senses?: Record<string, unknown> | null
  languages?: string | null
  challenge_rating?: number
  xp?: number
  traits?: CustomMonsterTraitInput[] | null
  actions?: CustomMonsterActionInput[] | null
  bonus_actions?: CustomMonsterActionInput[] | null
  reactions?: CustomMonsterActionInput[] | null
  legendary_actions?: CustomMonsterActionInput[] | null
  description?: string | null
}

export type CreateCustomMonsterFromContentInput = {
  content_key: string
  name?: string | null
}

export type CreateCustomMonsterFromInstanceInput = {
  instance_id: string
  name?: string | null
}

export type CopyCustomMonsterInput = {
  expected_revision: number
  name?: string | null
}

export type PatchCustomMonsterInput = {
  expected_revision: number
  name?: string | null
  armor_class?: number | null
  max_hp?: number | null
  speed?: Record<string, string> | string | null
  size?: string | null
  type?: string | null
  alignment?: string | null
  ability_scores?: Record<string, number> | null
  proficiencies?: Array<Record<string, unknown>> | null
  damage_vulnerabilities?: string[] | null
  damage_resistances?: string[] | null
  damage_immunities?: string[] | null
  condition_immunities?: Array<Record<string, unknown> | string> | null
  senses?: Record<string, unknown> | null
  languages?: string | null
  challenge_rating?: number | null
  xp?: number | null
  traits?: PatchCustomMonsterTraitInput[] | null
  actions?: PatchCustomMonsterActionInput[] | null
  bonus_actions?: PatchCustomMonsterActionInput[] | null
  reactions?: PatchCustomMonsterActionInput[] | null
  legendary_actions?: PatchCustomMonsterActionInput[] | null
  description?: string | null
}

export type ArchiveCustomMonsterInput = {
  expected_revision: number
}

export type MonsterLibrarySortField =
  | 'name'
  | 'armor_class'
  | 'max_hp'
  | 'challenge_rating'
  | 'walk_speed'

export type MonsterLibrarySortOrder = 'asc' | 'desc'

export type MonsterLibraryListOptions = {
  query?: string
  include_archived?: boolean
  limit?: number
  offset?: number
  source?: 'all' | 'builtin' | 'custom' | string
  sort?: MonsterLibrarySortField | string
  order?: MonsterLibrarySortOrder | string
  size?: string
  type?: string
  cr_eq?: number
  cr_min?: number
  cr_max?: number
}

type ApiErrorPayload = { error?: { code?: string; message?: string } }

export class MonsterLibraryApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message)
  }
}

async function apiError(response: Response): Promise<MonsterLibraryApiError> {
  let payload: ApiErrorPayload = {}
  try {
    payload = (await response.json()) as ApiErrorPayload
  } catch {
    // Preserve fallback for non-JSON response
  }
  return new MonsterLibraryApiError(
    response.status,
    payload.error?.code ?? 'monster_library_request_failed',
    payload.error?.message ?? `Monster library request failed (${response.status})`,
  )
}

function headers(accessToken: string): HeadersInit {
  return {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${accessToken}`,
  }
}

async function request<T>(url: string, accessToken: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: { ...headers(accessToken), ...(init?.headers ?? {}) },
  })
  if (!response.ok) throw await apiError(response)
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

const base = (roomId: string) => `/api/rooms/${roomId}/monster-library`

function appendLibraryListParams(params: URLSearchParams, options?: MonsterLibraryListOptions) {
  if (options?.query) params.set('query', options.query)
  if (options?.include_archived !== undefined) {
    params.set('include_archived', String(options.include_archived))
  }
  if (options?.limit !== undefined) params.set('limit', String(options.limit))
  if (options?.offset !== undefined) params.set('offset', String(options.offset))
  if (options?.source) params.set('source', options.source)
  if (options?.sort) params.set('sort', options.sort)
  if (options?.order) params.set('order', options.order)
  if (options?.size) params.set('size', options.size)
  if (options?.type) params.set('type', options.type)
  if (options?.cr_eq !== undefined) params.set('cr_eq', String(options.cr_eq))
  if (options?.cr_min !== undefined) params.set('cr_min', String(options.cr_min))
  if (options?.cr_max !== undefined) params.set('cr_max', String(options.cr_max))
}

export function listMonsterLibrary(
  roomId: string,
  token: string,
  options?: MonsterLibraryListOptions,
): Promise<MonsterLibrarySummaryView[]> {
  const params = new URLSearchParams()
  appendLibraryListParams(params, options)
  const qs = params.toString()
  return request(qs ? `${base(roomId)}?${qs}` : base(roomId), token)
}

export function getMonsterLibraryEntry(
  roomId: string,
  ref: string,
  token: string,
): Promise<MonsterLibraryDetailView> {
  return request(`${base(roomId)}/${encodeURIComponent(ref)}`, token)
}

const sessionLibrariesBase = (
  roomId: string,
  campaignId: string,
  sessionId: string,
) => `/api/rooms/${roomId}/campaigns/${campaignId}/sessions/${sessionId}/libraries`

function sessionMonsterLibraryQuery(options?: MonsterLibraryListOptions): string {
  const params = new URLSearchParams()
  appendLibraryListParams(params, options)
  return params.toString()
}

/**
 * M07-D D2 (F14): Session-scoped read-only monster library reads for the
 * current DM. Same response models as the management routes; usable by a
 * non-Owner Human sitting on the current DM Seat.
 */
export function listSessionMonsterLibrary(
  roomId: string,
  campaignId: string,
  sessionId: string,
  token: string,
  options?: MonsterLibraryListOptions,
): Promise<MonsterLibrarySummaryView[]> {
  const qs = sessionMonsterLibraryQuery(options)
  const url = `${sessionLibrariesBase(roomId, campaignId, sessionId)}/monster-library`
  return request(qs ? `${url}?${qs}` : url, token)
}

export function getSessionMonsterLibraryEntry(
  roomId: string,
  campaignId: string,
  sessionId: string,
  ref: string,
  token: string,
): Promise<MonsterLibraryDetailView> {
  return request(
    `${sessionLibrariesBase(roomId, campaignId, sessionId)}/monster-library/${encodeURIComponent(ref)}`,
    token,
  )
}

export function createCustomMonster(
  roomId: string,
  token: string,
  input: CreateCustomMonsterInput,
): Promise<MonsterLibraryDetailView> {
  return request(`${base(roomId)}/custom`, token, {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function createCustomMonsterFromContent(
  roomId: string,
  token: string,
  input: CreateCustomMonsterFromContentInput,
): Promise<MonsterLibraryDetailView> {
  return request(`${base(roomId)}/custom/from-content`, token, {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function createCustomMonsterFromInstance(
  roomId: string,
  token: string,
  input: CreateCustomMonsterFromInstanceInput,
): Promise<MonsterLibraryDetailView> {
  return request(`${base(roomId)}/custom/from-instance`, token, {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function copyCustomMonster(
  roomId: string,
  templateId: string,
  token: string,
  input: CopyCustomMonsterInput,
): Promise<MonsterLibraryDetailView> {
  return request(`${base(roomId)}/custom/${encodeURIComponent(templateId)}/copy`, token, {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function patchCustomMonster(
  roomId: string,
  templateId: string,
  token: string,
  input: PatchCustomMonsterInput,
): Promise<MonsterLibraryDetailView> {
  return request(`${base(roomId)}/custom/${encodeURIComponent(templateId)}`, token, {
    method: 'PATCH',
    body: JSON.stringify(input),
  })
}

export function archiveCustomMonster(
  roomId: string,
  templateId: string,
  token: string,
  input: ArchiveCustomMonsterInput,
): Promise<MonsterLibraryDetailView> {
  return request(`${base(roomId)}/custom/${encodeURIComponent(templateId)}/archive`, token, {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function deleteCustomMonster(
  roomId: string,
  templateId: string,
  token: string,
  expectedRevision: number,
): Promise<void> {
  return request(
    `${base(roomId)}/custom/${encodeURIComponent(templateId)}?expected_revision=${expectedRevision}`,
    token,
    { method: 'DELETE' },
  )
}
