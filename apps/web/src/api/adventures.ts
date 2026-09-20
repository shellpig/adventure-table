import type { RoomAsset } from './roomAssets'

export type AdventureStatus = 'draft' | 'finalized' | 'archived'

export type AdventureEntryKind =
  | 'section'
  | 'scene'
  | 'npc'
  | 'item'
  | 'monster_ref'
  | 'quest'
  | 'secret'
  | 'dm_note'
  | 'suggested_check'
  | 'map'
  | 'lore'
  | 'other'

export type AdventureEntryVisibility = 'public' | 'dm_only'
export type AdventureEntryAssetRole = 'image' | 'map' | 'source' | 'attachment'

export type AdventureDefinition = {
  id: string
  room_id: string
  name: string
  summary: string | null
  ruleset: string
  status: AdventureStatus
  created_at: string
  updated_at: string
}

export type AdventureEntryAsset = {
  asset: RoomAsset
  role: AdventureEntryAssetRole
  sort_order: number
}

export type SectionPayload = {
  kind: 'section'
}

export type ScenePayload = {
  kind: 'scene'
  read_aloud?: string | null
  dm_summary?: string | null
  exits?: string[]
}

export type NpcPayload = {
  kind: 'npc'
  role?: string | null
  disposition?: 'friendly' | 'neutral' | 'hostile' | 'unknown'
  monster_template_ref?: string | null
}

export type ItemPayload = {
  kind: 'item'
  rarity?: string | null
  value_gp?: number | null
  is_magic?: boolean
}

export type MonsterRefPayload = {
  kind: 'monster_ref'
  monster_template_ref: string
  count?: number
  notes?: string | null
}

export type QuestPayload = {
  kind: 'quest'
  objective: string
  reward?: string | null
}

export type SecretPayload = {
  kind: 'secret'
  reveal_condition?: string | null
}

export type DmNotePayload = {
  kind: 'dm_note'
}

export type SuggestedCheckPayload = {
  kind: 'suggested_check'
  ability: 'str' | 'dex' | 'con' | 'int' | 'wis' | 'cha'
  skill?: string | null
  dc: number
  on_success?: string | null
  on_failure?: string | null
}

export type MapPayload = {
  kind: 'map'
  caption?: string | null
  region_labels?: string[]
}

export type LorePayload = {
  kind: 'lore'
  topic?: string | null
}

export type OtherPayload = {
  kind: 'other'
  data?: Record<string, string | number | boolean>
}

export type AdventureEntryPayload =
  | SectionPayload
  | ScenePayload
  | NpcPayload
  | ItemPayload
  | MonsterRefPayload
  | QuestPayload
  | SecretPayload
  | DmNotePayload
  | SuggestedCheckPayload
  | MapPayload
  | LorePayload
  | OtherPayload

export type AdventureEntry = {
  id: string
  adventure_id: string
  parent_entry_id: string | null
  kind: AdventureEntryKind
  title: string | null
  body: string | null
  data: AdventureEntryPayload
  visibility: AdventureEntryVisibility
  sort_order: number
  assets: AdventureEntryAsset[]
  provenance?: Record<string, unknown> | null
  source_ref?: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export type AdventureDefinitionCreate = {
  name: string
  summary?: string | null
  ruleset?: string
}

export type AdventureDefinitionPatch = {
  name?: string | null
  summary?: string | null
}

export type AdventureEntryCreate = {
  kind: AdventureEntryKind
  title?: string | null
  body?: string | null
  data?: Record<string, unknown>
  visibility?: AdventureEntryVisibility
  parent_entry_id?: string | null
  sort_order?: number | null
}

export type AdventureEntryPatch = {
  title?: string | null
  body?: string | null
  data?: Record<string, unknown> | null
  visibility?: AdventureEntryVisibility | null
  parent_entry_id?: string | null
}

export type AdventureEntryReorder = {
  entry_ids: string[]
}

export type AdventureEntryAssetLink = {
  asset_id: string
  role: AdventureEntryAssetRole
}

export type AttachedAdventure = {
  campaign_id: string
  adventure_id: string
  sort_order: number
  attached_at: string
  name: string
  summary: string | null
  status: AdventureStatus
}

type ApiErrorPayload = { error?: { code?: string; message?: string } }

export class AdventureApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message)
  }
}

async function apiError(response: Response): Promise<AdventureApiError> {
  let payload: ApiErrorPayload = {}
  try {
    payload = (await response.json()) as ApiErrorPayload
  } catch {
    // Preserve a stable fallback for non-JSON intermediaries.
  }
  return new AdventureApiError(
    response.status,
    payload.error?.code ?? 'adventure_request_failed',
    payload.error?.message ?? `Adventure request failed (${response.status})`,
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

const base = (roomId: string) => `/api/rooms/${roomId}/adventures`
const campaignBase = (roomId: string, campaignId: string) =>
  `/api/rooms/${roomId}/campaigns/${campaignId}/adventures`

export function listAdventures(roomId: string, token: string): Promise<AdventureDefinition[]> {
  return request(base(roomId), token)
}

export function createAdventure(
  roomId: string,
  token: string,
  input: AdventureDefinitionCreate,
): Promise<AdventureDefinition> {
  return request(base(roomId), token, {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function getAdventure(
  roomId: string,
  adventureId: string,
  token: string,
): Promise<AdventureDefinition> {
  return request(`${base(roomId)}/${adventureId}`, token)
}

export function patchAdventure(
  roomId: string,
  adventureId: string,
  token: string,
  input: AdventureDefinitionPatch,
): Promise<AdventureDefinition> {
  return request(`${base(roomId)}/${adventureId}`, token, {
    method: 'PATCH',
    body: JSON.stringify(input),
  })
}

export function deleteAdventure(
  roomId: string,
  adventureId: string,
  token: string,
): Promise<void> {
  return request(`${base(roomId)}/${adventureId}`, token, { method: 'DELETE' })
}

export function finalizeAdventure(
  roomId: string,
  adventureId: string,
  token: string,
): Promise<AdventureDefinition> {
  return request(`${base(roomId)}/${adventureId}/finalize`, token, { method: 'POST' })
}

export function archiveAdventure(
  roomId: string,
  adventureId: string,
  token: string,
): Promise<AdventureDefinition> {
  return request(`${base(roomId)}/${adventureId}/archive`, token, { method: 'POST' })
}

export function listAdventureEntries(
  roomId: string,
  adventureId: string,
  token: string,
): Promise<AdventureEntry[]> {
  return request(`${base(roomId)}/${adventureId}/entries`, token)
}

export function createAdventureEntry(
  roomId: string,
  adventureId: string,
  token: string,
  input: AdventureEntryCreate,
): Promise<AdventureEntry> {
  return request(`${base(roomId)}/${adventureId}/entries`, token, {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function getAdventureEntry(
  roomId: string,
  adventureId: string,
  entryId: string,
  token: string,
): Promise<AdventureEntry> {
  return request(`${base(roomId)}/${adventureId}/entries/${entryId}`, token)
}

export function patchAdventureEntry(
  roomId: string,
  adventureId: string,
  entryId: string,
  token: string,
  input: AdventureEntryPatch,
): Promise<AdventureEntry> {
  return request(`${base(roomId)}/${adventureId}/entries/${entryId}`, token, {
    method: 'PATCH',
    body: JSON.stringify(input),
  })
}

export function deleteAdventureEntry(
  roomId: string,
  adventureId: string,
  entryId: string,
  token: string,
): Promise<void> {
  return request(`${base(roomId)}/${adventureId}/entries/${entryId}`, token, {
    method: 'DELETE',
  })
}

export function reorderAdventureEntries(
  roomId: string,
  adventureId: string,
  token: string,
  input: AdventureEntryReorder,
): Promise<void> {
  return request(`${base(roomId)}/${adventureId}/entries/reorder`, token, {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function linkAdventureEntryAsset(
  roomId: string,
  adventureId: string,
  entryId: string,
  token: string,
  input: AdventureEntryAssetLink,
): Promise<AdventureEntry> {
  return request(`${base(roomId)}/${adventureId}/entries/${entryId}/assets`, token, {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function unlinkAdventureEntryAsset(
  roomId: string,
  adventureId: string,
  entryId: string,
  assetId: string,
  token: string,
): Promise<AdventureEntry> {
  return request(`${base(roomId)}/${adventureId}/entries/${entryId}/assets/${assetId}`, token, {
    method: 'DELETE',
  })
}

export function listCampaignAdventures(
  roomId: string,
  campaignId: string,
  token: string,
): Promise<AttachedAdventure[]> {
  return request(campaignBase(roomId, campaignId), token)
}

export function attachCampaignAdventure(
  roomId: string,
  campaignId: string,
  token: string,
  adventureId: string,
): Promise<AttachedAdventure> {
  return request(campaignBase(roomId, campaignId), token, {
    method: 'POST',
    body: JSON.stringify({ adventure_id: adventureId }),
  })
}

export function detachCampaignAdventure(
  roomId: string,
  campaignId: string,
  adventureId: string,
  token: string,
): Promise<void> {
  return request(`${campaignBase(roomId, campaignId)}/${adventureId}`, token, {
    method: 'DELETE',
  })
}
