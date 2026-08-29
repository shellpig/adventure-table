export type BuilderMode = 'create' | 'level_up' | 'build_edit' | 'correction'
export type BuilderIssueSeverity = 'blocking_error' | 'warning' | 'non_standard'

export type BuilderBasicInput = {
  name?: string | null
  ruleset?: 'dnd5e-2014'
}

export type BuilderReferenceSelection = {
  reference_id: string
  source_ref?: string | null
}

export type BuilderChoiceSelection = {
  choice_id: string
  selected_option_ids?: string[]
  source_ref?: string | null
  provenance_path?: string | null
}

export type BuilderDraftPayload = {
  basic?: BuilderBasicInput | null
  target_level?: number | null
  race_selection?: BuilderReferenceSelection | null
  background_selection?: BuilderReferenceSelection | null
  ability_generation?: Record<string, unknown> | null
  level_choices?: Record<string, unknown>[]
  choice_selections?: Record<string, BuilderChoiceSelection>
  spell_choices?: Record<string, unknown>
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

export type BuilderChoice = {
  choice_id: string
  label: string
  source_ref?: string | null
  required: boolean
  choose_count: number
  option_source?: string | null
  selected_option_ids: string[]
  disabled_reason?: string | null
}

export type BuilderView = {
  draft: BuilderDraft
  resolved_summary: {
    name?: string | null
    target_level?: number | null
    selected_reference_count: number
    choice_selection_count: number
  }
  choices: BuilderChoice[]
  validation: BuilderValidationResult
}

type APIErrorPayload = {
  error?: {
    code?: string
    message?: string
  }
}

async function builderRequest<T>(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<T> {
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

  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

export function createBuilderDraft(
  draftPayload: BuilderDraftPayload = {},
): Promise<BuilderView> {
  return builderRequest<BuilderView>('/api/character-builder/drafts', {
    method: 'POST',
    body: JSON.stringify({
      mode: 'create',
      draft_payload: draftPayload,
    }),
  })
}

export function getBuilderDraft(draftId: string): Promise<BuilderView> {
  return builderRequest<BuilderView>(`/api/character-builder/drafts/${draftId}`)
}

export function patchBuilderDraft(
  draftId: string,
  expectedRevision: number,
  draftPayload: BuilderDraftPayload,
): Promise<BuilderView> {
  return builderRequest<BuilderView>(`/api/character-builder/drafts/${draftId}`, {
    method: 'PATCH',
    body: JSON.stringify({
      expected_revision: expectedRevision,
      draft_payload: draftPayload,
    }),
  })
}

export function validateBuilderDraft(
  draftId: string,
): Promise<BuilderValidationResult> {
  return builderRequest<BuilderValidationResult>(
    `/api/character-builder/drafts/${draftId}/validate`,
    { method: 'POST' },
  )
}

export function cancelBuilderDraft(draftId: string): Promise<void> {
  return builderRequest<void>(`/api/character-builder/drafts/${draftId}`, {
    method: 'DELETE',
  })
}
