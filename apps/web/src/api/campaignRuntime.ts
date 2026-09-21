import type {
  AdventureEntryKind,
  AdventureEntryPayload,
  AdventureEntryVisibility,
} from './adventures'

export type RuntimeEntryKind =
  | 'scene'
  | 'npc'
  | 'item'
  | 'quest'
  | 'fact'
  | 'secret'
  | 'hazard'
  | 'other'

export type RuntimeVisibility = 'public' | 'dm_only' | 'character'

export type RuntimeItemHolderKind = 'scene' | 'npc' | 'character' | 'party' | 'unknown'

export type RuntimeItemHolderRef = {
  kind: RuntimeItemHolderKind
  target_id: string | null
}

export type RuntimeScenePayload = {
  kind: 'scene'
}

export type RuntimeNpcPayload = {
  kind: 'npc'
  monster_instance_id: string | null
  monster_template_ref: string | null
}

export type RuntimeItemPayload = {
  kind: 'item'
  holder_ref: RuntimeItemHolderRef | null
}

export type RuntimeQuestPayload = {
  kind: 'quest'
}

export type RuntimeFactPayload = {
  kind: 'fact'
}

export type RuntimeSecretPayload = {
  kind: 'secret'
}

export type RuntimeHazardPayload = {
  kind: 'hazard'
}

export type RuntimeOtherPayload = {
  kind: 'other'
  data: Record<string, string | number | boolean>
}

export type RuntimeStatePayload =
  | RuntimeScenePayload
  | RuntimeNpcPayload
  | RuntimeItemPayload
  | RuntimeQuestPayload
  | RuntimeFactPayload
  | RuntimeSecretPayload
  | RuntimeHazardPayload
  | RuntimeOtherPayload

export type RuntimeEntryPayload = RuntimeStatePayload

export type RuntimeWorldEntryDmView = {
  id: string
  campaign_id: string
  kind: RuntimeEntryKind
  title: string | null
  body: string | null
  state: RuntimeStatePayload
  visibility: RuntimeVisibility
  dm_notes: string | null
  needs_review: boolean
  source_adventure_entry_id: string | null
  provenance_json: Record<string, unknown> | null
  character_recipient_ids: string[]
  revision: number
  created_by_actor_kind: string
  created_by_actor_id: string | null
  created_at: string
  updated_at: string
  archived_at: string | null
}

export type RuntimeWorldEntryPlayerView = {
  id: string
  campaign_id: string
  kind: RuntimeEntryKind
  title: string | null
  body: string | null
  state: RuntimeStatePayload
  visibility: RuntimeVisibility
  revision: number
  created_at: string
  updated_at: string
}

export type CampaignAdventureOverride = {
  id: string
  campaign_id: string
  adventure_entry_id: string
  state_json: Record<string, unknown>
  note: string | null
  needs_review: boolean
  revision: number
  created_at: string
  updated_at: string
}

export type CampaignRuntimeContext = {
  campaign_id: string
  current_adventure_scene_entry_id: string | null
  current_runtime_scene_entry_id: string | null
  current_situation: string | null
  revision: number
  created_at: string | null
  updated_at: string | null
}

export type CampaignAdventureEntryOverlayView = {
  id: string
  adventure_id: string
  parent_entry_id: string | null
  kind: AdventureEntryKind
  title: string | null
  body: string | null
  data: AdventureEntryPayload
  visibility: AdventureEntryVisibility
  sort_order: number
  override: CampaignAdventureOverride | null
}

export type CreateRuntimeWorldEntryRequest = {
  idempotency_key: string
  kind: RuntimeEntryKind
  title?: string | null
  body?: string | null
  state?: Record<string, unknown>
  visibility?: RuntimeVisibility
  character_recipient_ids?: string[]
  dm_notes?: string | null
  source_adventure_entry_id?: string | null
  provenance_json?: Record<string, unknown> | null
  needs_review?: boolean
}

export type UpdateRuntimeWorldEntryRequest = {
  idempotency_key: string
  expected_revision: number
  title?: string | null
  body?: string | null
  state?: Record<string, unknown>
  visibility?: RuntimeVisibility
  character_recipient_ids?: string[]
  dm_notes?: string | null
  source_adventure_entry_id?: string | null
  provenance_json?: Record<string, unknown> | null
  needs_review?: boolean
}

export type ArchiveRuntimeWorldEntryRequest = {
  expected_revision: number
  idempotency_key: string
}

export type CreateCampaignAdventureOverrideRequest = {
  idempotency_key: string
  adventure_entry_id: string
  state?: Record<string, unknown>
  note?: string | null
  needs_review?: boolean
}

export type UpdateCampaignAdventureOverrideRequest = {
  idempotency_key: string
  expected_override_id: string
  expected_revision: number
  state?: Record<string, unknown>
  note?: string | null
  needs_review?: boolean
}

export type ClearCampaignAdventureOverrideRequest = {
  idempotency_key: string
  expected_override_id: string
  expected_revision: number
}

export type UpdateCampaignRuntimeContextRequest = {
  idempotency_key: string
  expected_revision: number
  current_adventure_scene_entry_id?: string | null
  current_runtime_scene_entry_id?: string | null
  current_situation?: string | null
}

export type ClearCampaignRuntimeContextRequest = {
  idempotency_key: string
  expected_revision: number
}

type ApiErrorPayload = { error?: { code?: string; message?: string } }

export class CampaignRuntimeApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message)
  }
}

async function apiError(response: Response): Promise<CampaignRuntimeApiError> {
  let payload: ApiErrorPayload = {}
  try {
    payload = (await response.json()) as ApiErrorPayload
  } catch {
    // Preserve stable fallback for non-JSON intermediaries.
  }
  return new CampaignRuntimeApiError(
    response.status,
    payload.error?.code ?? 'campaign_runtime_request_failed',
    payload.error?.message ?? `Campaign runtime request failed (${response.status})`,
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

function runtimeUrl(
  basePath: string,
  subpath: string,
  options?: { includeArchived?: boolean },
): string {
  if (options?.includeArchived) {
    return `${basePath}${subpath}?include_archived=true`
  }
  return `${basePath}${subpath}`
}

function scopedRuntimeClient(basePath: string, token: string) {
  return {
    listEntries: <T = RuntimeWorldEntryDmView>(options?: { includeArchived?: boolean }) =>
      request<T[]>(runtimeUrl(basePath, '/entries', options), token),
    getEntry: <T = RuntimeWorldEntryDmView>(
      entryId: string,
      options?: { includeArchived?: boolean },
    ) => request<T>(runtimeUrl(basePath, `/entries/${entryId}`, options), token),
    createEntry: (input: CreateRuntimeWorldEntryRequest) =>
      request<RuntimeWorldEntryDmView>(`${basePath}/entries`, token, {
        method: 'POST',
        body: JSON.stringify(input),
      }),
    updateEntry: (entryId: string, input: UpdateRuntimeWorldEntryRequest) =>
      request<RuntimeWorldEntryDmView>(`${basePath}/entries/${entryId}`, token, {
        method: 'PATCH',
        body: JSON.stringify(input),
      }),
    archiveEntry: (entryId: string, input: ArchiveRuntimeWorldEntryRequest) =>
      request<RuntimeWorldEntryDmView>(`${basePath}/entries/${entryId}/archive`, token, {
        method: 'POST',
        body: JSON.stringify(input),
      }),
    listOverrides: () => request<CampaignAdventureOverride[]>(`${basePath}/overrides`, token),
    getOverride: (adventureEntryId: string) =>
      request<CampaignAdventureOverride>(`${basePath}/overrides/${adventureEntryId}`, token),
    createOverride: (input: CreateCampaignAdventureOverrideRequest) =>
      request<CampaignAdventureOverride>(`${basePath}/overrides`, token, {
        method: 'POST',
        body: JSON.stringify(input),
      }),
    updateOverride: (
      adventureEntryId: string,
      input: UpdateCampaignAdventureOverrideRequest,
    ) =>
      request<CampaignAdventureOverride>(`${basePath}/overrides/${adventureEntryId}`, token, {
        method: 'PATCH',
        body: JSON.stringify(input),
      }),
    clearOverride: (
      adventureEntryId: string,
      input: ClearCampaignAdventureOverrideRequest,
    ) =>
      request<CampaignAdventureOverride>(
        `${basePath}/overrides/${adventureEntryId}/clear`,
        token,
        {
          method: 'POST',
          body: JSON.stringify(input),
        },
      ),
    getContext: () => request<CampaignRuntimeContext>(`${basePath}/context`, token),
    updateContext: (input: UpdateCampaignRuntimeContextRequest) =>
      request<CampaignRuntimeContext>(`${basePath}/context`, token, {
        method: 'PATCH',
        body: JSON.stringify(input),
      }),
    clearContext: (input: ClearCampaignRuntimeContextRequest) =>
      request<CampaignRuntimeContext>(`${basePath}/context/clear`, token, {
        method: 'POST',
        body: JSON.stringify(input),
      }),
    getAdventureEntryOverlay: (adventureEntryId: string) =>
      request<CampaignAdventureEntryOverlayView>(
        `${basePath}/adventure-overlays/${adventureEntryId}`,
        token,
      ),
    listAdventureEntryOverlays: (adventureId: string) =>
      request<CampaignAdventureEntryOverlayView[]>(
        `${basePath}/adventures/${adventureId}/overlays`,
        token,
      ),
  }
}

const managementBase = (roomId: string, campaignId: string) =>
  `/api/rooms/${roomId}/campaigns/${campaignId}/runtime`

const activeBase = (roomId: string, campaignId: string, sessionId: string) =>
  `/api/rooms/${roomId}/campaigns/${campaignId}/sessions/${sessionId}/runtime`

export function listRuntimeEntries(
  roomId: string,
  campaignId: string,
  token: string,
  options?: { includeArchived?: boolean },
): Promise<RuntimeWorldEntryDmView[]> {
  return scopedRuntimeClient(managementBase(roomId, campaignId), token).listEntries(options)
}

export function getRuntimeEntry(
  roomId: string,
  campaignId: string,
  entryId: string,
  token: string,
  options?: { includeArchived?: boolean },
): Promise<RuntimeWorldEntryDmView> {
  return scopedRuntimeClient(managementBase(roomId, campaignId), token).getEntry(entryId, options)
}

export function createRuntimeEntry(
  roomId: string,
  campaignId: string,
  token: string,
  input: CreateRuntimeWorldEntryRequest,
): Promise<RuntimeWorldEntryDmView> {
  return scopedRuntimeClient(managementBase(roomId, campaignId), token).createEntry(input)
}

export function updateRuntimeEntry(
  roomId: string,
  campaignId: string,
  entryId: string,
  token: string,
  input: UpdateRuntimeWorldEntryRequest,
): Promise<RuntimeWorldEntryDmView> {
  return scopedRuntimeClient(managementBase(roomId, campaignId), token).updateEntry(entryId, input)
}

export function archiveRuntimeEntry(
  roomId: string,
  campaignId: string,
  entryId: string,
  token: string,
  input: ArchiveRuntimeWorldEntryRequest,
): Promise<RuntimeWorldEntryDmView> {
  return scopedRuntimeClient(managementBase(roomId, campaignId), token).archiveEntry(entryId, input)
}

export function listOverrides(
  roomId: string,
  campaignId: string,
  token: string,
): Promise<CampaignAdventureOverride[]> {
  return scopedRuntimeClient(managementBase(roomId, campaignId), token).listOverrides()
}

export function getOverride(
  roomId: string,
  campaignId: string,
  adventureEntryId: string,
  token: string,
): Promise<CampaignAdventureOverride> {
  return scopedRuntimeClient(managementBase(roomId, campaignId), token).getOverride(adventureEntryId)
}

export function createOverride(
  roomId: string,
  campaignId: string,
  token: string,
  input: CreateCampaignAdventureOverrideRequest,
): Promise<CampaignAdventureOverride> {
  return scopedRuntimeClient(managementBase(roomId, campaignId), token).createOverride(input)
}

export function updateOverride(
  roomId: string,
  campaignId: string,
  adventureEntryId: string,
  token: string,
  input: UpdateCampaignAdventureOverrideRequest,
): Promise<CampaignAdventureOverride> {
  return scopedRuntimeClient(managementBase(roomId, campaignId), token).updateOverride(adventureEntryId, input)
}

export function clearOverride(
  roomId: string,
  campaignId: string,
  adventureEntryId: string,
  token: string,
  input: ClearCampaignAdventureOverrideRequest,
): Promise<CampaignAdventureOverride> {
  return scopedRuntimeClient(managementBase(roomId, campaignId), token).clearOverride(adventureEntryId, input)
}

export function getRuntimeContext(
  roomId: string,
  campaignId: string,
  token: string,
): Promise<CampaignRuntimeContext> {
  return scopedRuntimeClient(managementBase(roomId, campaignId), token).getContext()
}

export function updateRuntimeContext(
  roomId: string,
  campaignId: string,
  token: string,
  input: UpdateCampaignRuntimeContextRequest,
): Promise<CampaignRuntimeContext> {
  return scopedRuntimeClient(managementBase(roomId, campaignId), token).updateContext(input)
}

export function clearRuntimeContext(
  roomId: string,
  campaignId: string,
  token: string,
  input: ClearCampaignRuntimeContextRequest,
): Promise<CampaignRuntimeContext> {
  return scopedRuntimeClient(managementBase(roomId, campaignId), token).clearContext(input)
}

export function getAdventureEntryOverlay(
  roomId: string,
  campaignId: string,
  adventureEntryId: string,
  token: string,
): Promise<CampaignAdventureEntryOverlayView> {
  return scopedRuntimeClient(managementBase(roomId, campaignId), token).getAdventureEntryOverlay(adventureEntryId)
}

export function listAdventureEntryOverlays(
  roomId: string,
  campaignId: string,
  adventureId: string,
  token: string,
): Promise<CampaignAdventureEntryOverlayView[]> {
  return scopedRuntimeClient(managementBase(roomId, campaignId), token).listAdventureEntryOverlays(adventureId)
}

export function listActiveRuntimeEntries(
  roomId: string,
  campaignId: string,
  sessionId: string,
  token: string,
  options?: { includeArchived?: boolean },
): Promise<(RuntimeWorldEntryDmView | RuntimeWorldEntryPlayerView)[]> {
  return scopedRuntimeClient(activeBase(roomId, campaignId, sessionId), token).listEntries(options)
}

export function getActiveRuntimeEntry(
  roomId: string,
  campaignId: string,
  sessionId: string,
  entryId: string,
  token: string,
  options?: { includeArchived?: boolean },
): Promise<RuntimeWorldEntryDmView | RuntimeWorldEntryPlayerView> {
  return scopedRuntimeClient(activeBase(roomId, campaignId, sessionId), token).getEntry(entryId, options)
}

export function createActiveRuntimeEntry(
  roomId: string,
  campaignId: string,
  sessionId: string,
  token: string,
  input: CreateRuntimeWorldEntryRequest,
): Promise<RuntimeWorldEntryDmView> {
  return scopedRuntimeClient(activeBase(roomId, campaignId, sessionId), token).createEntry(input)
}

export function updateActiveRuntimeEntry(
  roomId: string,
  campaignId: string,
  sessionId: string,
  entryId: string,
  token: string,
  input: UpdateRuntimeWorldEntryRequest,
): Promise<RuntimeWorldEntryDmView> {
  return scopedRuntimeClient(activeBase(roomId, campaignId, sessionId), token).updateEntry(entryId, input)
}

export function archiveActiveRuntimeEntry(
  roomId: string,
  campaignId: string,
  sessionId: string,
  entryId: string,
  token: string,
  input: ArchiveRuntimeWorldEntryRequest,
): Promise<RuntimeWorldEntryDmView> {
  return scopedRuntimeClient(activeBase(roomId, campaignId, sessionId), token).archiveEntry(entryId, input)
}

export function listActiveOverrides(
  roomId: string,
  campaignId: string,
  sessionId: string,
  token: string,
): Promise<CampaignAdventureOverride[]> {
  return scopedRuntimeClient(activeBase(roomId, campaignId, sessionId), token).listOverrides()
}

export function getActiveOverride(
  roomId: string,
  campaignId: string,
  sessionId: string,
  adventureEntryId: string,
  token: string,
): Promise<CampaignAdventureOverride> {
  return scopedRuntimeClient(activeBase(roomId, campaignId, sessionId), token).getOverride(adventureEntryId)
}

export function createActiveOverride(
  roomId: string,
  campaignId: string,
  sessionId: string,
  token: string,
  input: CreateCampaignAdventureOverrideRequest,
): Promise<CampaignAdventureOverride> {
  return scopedRuntimeClient(activeBase(roomId, campaignId, sessionId), token).createOverride(input)
}

export function updateActiveOverride(
  roomId: string,
  campaignId: string,
  sessionId: string,
  adventureEntryId: string,
  token: string,
  input: UpdateCampaignAdventureOverrideRequest,
): Promise<CampaignAdventureOverride> {
  return scopedRuntimeClient(activeBase(roomId, campaignId, sessionId), token).updateOverride(adventureEntryId, input)
}

export function clearActiveOverride(
  roomId: string,
  campaignId: string,
  sessionId: string,
  adventureEntryId: string,
  token: string,
  input: ClearCampaignAdventureOverrideRequest,
): Promise<CampaignAdventureOverride> {
  return scopedRuntimeClient(activeBase(roomId, campaignId, sessionId), token).clearOverride(adventureEntryId, input)
}

export function getActiveRuntimeContext(
  roomId: string,
  campaignId: string,
  sessionId: string,
  token: string,
): Promise<CampaignRuntimeContext> {
  return scopedRuntimeClient(activeBase(roomId, campaignId, sessionId), token).getContext()
}

export function updateActiveRuntimeContext(
  roomId: string,
  campaignId: string,
  sessionId: string,
  token: string,
  input: UpdateCampaignRuntimeContextRequest,
): Promise<CampaignRuntimeContext> {
  return scopedRuntimeClient(activeBase(roomId, campaignId, sessionId), token).updateContext(input)
}

export function clearActiveRuntimeContext(
  roomId: string,
  campaignId: string,
  sessionId: string,
  token: string,
  input: ClearCampaignRuntimeContextRequest,
): Promise<CampaignRuntimeContext> {
  return scopedRuntimeClient(activeBase(roomId, campaignId, sessionId), token).clearContext(input)
}

export function getActiveAdventureEntryOverlay(
  roomId: string,
  campaignId: string,
  sessionId: string,
  adventureEntryId: string,
  token: string,
): Promise<CampaignAdventureEntryOverlayView> {
  return scopedRuntimeClient(activeBase(roomId, campaignId, sessionId), token).getAdventureEntryOverlay(adventureEntryId)
}

export function listActiveAdventureEntryOverlays(
  roomId: string,
  campaignId: string,
  sessionId: string,
  adventureId: string,
  token: string,
): Promise<CampaignAdventureEntryOverlayView[]> {
  return scopedRuntimeClient(activeBase(roomId, campaignId, sessionId), token).listAdventureEntryOverlays(adventureId)
}
