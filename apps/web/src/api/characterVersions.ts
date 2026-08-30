import type { BuilderMode, BuilderView } from './characterBuilder'

export type VersionedBuilderMode = Exclude<BuilderMode, 'create'>

export type CharacterVersionSummary = {
  id: string
  character_id: string
  version_no: number
  version_kind: 'legacy' | 'create' | 'level_up' | 'build_edit' | 'correction'
  parent_version_id?: string | null
  superseded_by_version_id?: string | null
  change_note?: string | null
  created_at: string
  is_current: boolean
  character_level: number
  class_summary: string
}

export type CharacterVersionDetail = CharacterVersionSummary & {
  build: unknown
}

export type StateReconciliationChange = {
  path: string
  kind: string
  before: string
  after: string
  message: string
}

export type StateReconciliationIssue = {
  code: string
  severity: 'blocking_error' | 'warning' | 'non_standard'
  path: string
  message: string
  related_refs: string[]
}

export type StateReconciliationPreview = {
  proposed_state: {
    current_hp: number
    temporary_hp: number
    conditions: unknown[]
    prepared_spell_entry_ids: string[]
    prepared_spells: unknown[]
    spell_slots: Record<string, { used: number; remaining: number }>
    resources: Record<string, { used: number; remaining: number }>
    hit_dice_state: Record<string, number>
    inventory_state: unknown[]
  }
  changes: StateReconciliationChange[]
  blocking_issues: StateReconciliationIssue[]
  warnings: StateReconciliationIssue[]
  can_apply: boolean
}

type APIErrorPayload = {
  error?: { code?: string; message?: string }
}

async function request<T>(input: RequestInfo | URL, init?: RequestInit): Promise<T> {
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
      // Keep the HTTP fallback when the response is not JSON.
    }
    throw new Error(message)
  }
  return (await response.json()) as T
}

export function createCharacterVersionDraft(
  characterId: string,
  mode: VersionedBuilderMode,
): Promise<BuilderView> {
  return request<BuilderView>(`/api/character-builder/characters/${characterId}/drafts`, {
    method: 'POST',
    body: JSON.stringify({ mode }),
  })
}

export function listCharacterVersions(characterId: string): Promise<CharacterVersionSummary[]> {
  return request<CharacterVersionSummary[]>(`/api/characters/${characterId}/versions`)
}

export function getCharacterVersion(
  characterId: string,
  versionNo: number,
): Promise<CharacterVersionDetail> {
  return request<CharacterVersionDetail>(`/api/characters/${characterId}/versions/${versionNo}`)
}
