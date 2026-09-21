import type { AdventureEntryKind, AttachedAdventure } from '../../api/adventures'
import {
  clearOverride,
  clearRuntimeContext,
  type CampaignAdventureEntryOverlayView,
  type CampaignAdventureOverride,
  type CampaignRuntimeContext,
  type ClearCampaignAdventureOverrideRequest,
  type ClearCampaignRuntimeContextRequest,
  type CreateCampaignAdventureOverrideRequest,
  type RuntimeWorldEntryDmView,
  type UpdateCampaignAdventureOverrideRequest,
  type UpdateCampaignRuntimeContextRequest,
} from '../../api/campaignRuntime'
import type { CampaignRuntimeCopy } from './campaignRuntimeCopy'
import { executeRuntimeMutation } from './campaignRuntimeForm'

export type CreateOverrideFormState = {
  mode: 'create'
  adventureId: string
  adventureEntryId: string
  entryTitle: string | null
  entryKind: AdventureEntryKind
  stateJson: string
  note: string
  needsReview: boolean
}

export type EditOverrideFormState = {
  mode: 'edit'
  adventureId: string
  adventureEntryId: string
  entryTitle: string | null
  entryKind: AdventureEntryKind
  expectedOverrideId: string
  expectedRevision: number
  stateJson: string
  note: string
  needsReview: boolean
}

export type OverrideFormState = CreateOverrideFormState | EditOverrideFormState

export type OverrideValidationErrorKey = 'errOverrideStateInvalidJson'

export type OverrideValidationResult<T> =
  | { ok: true; value: T }
  | { ok: false; errorKey: OverrideValidationErrorKey }

export function validateAndParseOverrideState(
  rawJson: string,
): OverrideValidationResult<Record<string, unknown>> {
  const trimmed = rawJson.trim()
  if (!trimmed) {
    return { ok: true, value: {} }
  }
  let parsed: unknown
  try {
    parsed = JSON.parse(trimmed)
  } catch {
    return { ok: false, errorKey: 'errOverrideStateInvalidJson' }
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    return { ok: false, errorKey: 'errOverrideStateInvalidJson' }
  }
  return { ok: true, value: parsed as Record<string, unknown> }
}

export function buildCreateOverrideRequest(
  form: CreateOverrideFormState,
  idempotencyKey: string,
): OverrideValidationResult<CreateCampaignAdventureOverrideRequest> {
  const stateResult = validateAndParseOverrideState(form.stateJson)
  if (!stateResult.ok) {
    return stateResult
  }
  const note = form.note.trim() || null
  return {
    ok: true,
    value: {
      idempotency_key: idempotencyKey,
      adventure_entry_id: form.adventureEntryId,
      state: stateResult.value,
      note,
      needs_review: form.needsReview,
    },
  }
}

export function buildUpdateOverrideRequest(
  form: EditOverrideFormState,
  idempotencyKey: string,
): OverrideValidationResult<UpdateCampaignAdventureOverrideRequest> {
  const stateResult = validateAndParseOverrideState(form.stateJson)
  if (!stateResult.ok) {
    return stateResult
  }
  const note = form.note.trim() || null
  return {
    ok: true,
    value: {
      idempotency_key: idempotencyKey,
      expected_override_id: form.expectedOverrideId,
      expected_revision: form.expectedRevision,
      state: stateResult.value,
      note,
      needs_review: form.needsReview,
    },
  }
}

export function buildClearOverrideRequest(
  expectedOverrideId: string,
  expectedRevision: number,
  idempotencyKey: string,
): ClearCampaignAdventureOverrideRequest {
  return {
    idempotency_key: idempotencyKey,
    expected_override_id: expectedOverrideId,
    expected_revision: expectedRevision,
  }
}

export function overlayToOverrideFormState(
  overlay: CampaignAdventureEntryOverlayView,
): OverrideFormState {
  if (!overlay.override) {
    return {
      mode: 'create',
      adventureId: overlay.adventure_id,
      adventureEntryId: overlay.id,
      entryTitle: overlay.title,
      entryKind: overlay.kind,
      stateJson: '',
      note: '',
      needsReview: false,
    }
  }
  return {
    mode: 'edit',
    adventureId: overlay.adventure_id,
    adventureEntryId: overlay.id,
    entryTitle: overlay.title,
    entryKind: overlay.kind,
    expectedOverrideId: overlay.override.id,
    expectedRevision: overlay.override.revision,
    stateJson: JSON.stringify(overlay.override.state_json, null, 2),
    note: overlay.override.note ?? '',
    needsReview: overlay.override.needs_review,
  }
}

export type DetachBlockerStatus = {
  hasActiveOverrides: boolean
  hasActiveContextScene: boolean
  overrideCount: number
  isBlocked: boolean
}

export function computeDetachBlockers(
  adventureId: string,
  overlays: CampaignAdventureEntryOverlayView[],
  context: CampaignRuntimeContext | null,
): DetachBlockerStatus {
  const advOverlays = overlays.filter((o) => o.adventure_id === adventureId)
  const overrideCount = advOverlays.filter((o) => o.override !== null).length
  const hasActiveOverrides = overrideCount > 0
  const hasActiveContextScene = Boolean(
    context?.current_adventure_scene_entry_id &&
      advOverlays.some((o) => o.id === context.current_adventure_scene_entry_id),
  )
  return {
    hasActiveOverrides,
    hasActiveContextScene,
    overrideCount,
    isBlocked: hasActiveOverrides || hasActiveContextScene,
  }
}

export type SceneSelection =
  | { type: 'none' }
  | { type: 'adventure'; sceneEntryId: string }
  | { type: 'runtime'; sceneEntryId: string }

export type ContextFormState = {
  sceneSelection: SceneSelection
  situation: string
  expectedRevision: number
}

export function contextToFormState(context: CampaignRuntimeContext | null): ContextFormState {
  let sceneSelection: SceneSelection = { type: 'none' }
  if (context?.current_adventure_scene_entry_id) {
    sceneSelection = {
      type: 'adventure',
      sceneEntryId: context.current_adventure_scene_entry_id,
    }
  } else if (context?.current_runtime_scene_entry_id) {
    sceneSelection = {
      type: 'runtime',
      sceneEntryId: context.current_runtime_scene_entry_id,
    }
  }
  return {
    sceneSelection,
    situation: context?.current_situation ?? '',
    expectedRevision: context?.revision ?? 0,
  }
}

export function encodeSceneSelection(selection: SceneSelection): string {
  if (selection.type === 'adventure') {
    return `adventure:${selection.sceneEntryId}`
  }
  if (selection.type === 'runtime') {
    return `runtime:${selection.sceneEntryId}`
  }
  return ''
}

export function parseSceneSelection(value: string): SceneSelection {
  if (!value) return { type: 'none' }
  if (value.startsWith('adventure:')) {
    const sceneEntryId = value.slice('adventure:'.length)
    return sceneEntryId ? { type: 'adventure', sceneEntryId } : { type: 'none' }
  }
  if (value.startsWith('runtime:')) {
    const sceneEntryId = value.slice('runtime:'.length)
    return sceneEntryId ? { type: 'runtime', sceneEntryId } : { type: 'none' }
  }
  return { type: 'none' }
}

export function buildUpdateContextRequest(
  form: ContextFormState,
  idempotencyKey: string,
): UpdateCampaignRuntimeContextRequest {
  const trimmedSituation = form.situation.trim() || null
  let current_adventure_scene_entry_id: string | null = null
  let current_runtime_scene_entry_id: string | null = null

  if (form.sceneSelection.type === 'adventure') {
    current_adventure_scene_entry_id = form.sceneSelection.sceneEntryId
    current_runtime_scene_entry_id = null
  } else if (form.sceneSelection.type === 'runtime') {
    current_adventure_scene_entry_id = null
    current_runtime_scene_entry_id = form.sceneSelection.sceneEntryId
  } else {
    current_adventure_scene_entry_id = null
    current_runtime_scene_entry_id = null
  }

  return {
    idempotency_key: idempotencyKey,
    expected_revision: form.expectedRevision,
    current_adventure_scene_entry_id,
    current_runtime_scene_entry_id,
    current_situation: trimmedSituation,
  }
}

export function buildClearContextRequest(
  expectedRevision: number,
  idempotencyKey: string,
): ClearCampaignRuntimeContextRequest {
  return {
    idempotency_key: idempotencyKey,
    expected_revision: expectedRevision,
  }
}

export type ClearOverrideOptions = {
  roomId: string
  campaignId: string
  adventureEntryId: string
  expectedOverrideId: string
  expectedRevision: number
  token: string
  idempotencyKey: string
  confirmFn?: () => boolean
  onStart?: () => void
  onCancel?: () => void
  clearFn?: (
    roomId: string,
    campaignId: string,
    adventureEntryId: string,
    token: string,
    request: ClearCampaignAdventureOverrideRequest,
  ) => Promise<CampaignAdventureOverride>
  onReload: () => Promise<void>
  onSuccess?: () => void
  onError: (errorMessage: string) => void
  onCommittedReloadError: (errorMessage: string) => void
  copy: CampaignRuntimeCopy
}

export async function handleClearOverride(options: ClearOverrideOptions): Promise<boolean> {
  const confirmFn =
    options.confirmFn ??
    (() => (typeof window !== 'undefined' ? window.confirm(options.copy.confirmClearOverride) : true))

  if (!confirmFn()) {
    options.onCancel?.()
    return false
  }

  options.onStart?.()
  const clearFn = options.clearFn ?? clearOverride
  return executeRuntimeMutation({
    action: () =>
      clearFn(
        options.roomId,
        options.campaignId,
        options.adventureEntryId,
        options.token,
        buildClearOverrideRequest(
          options.expectedOverrideId,
          options.expectedRevision,
          options.idempotencyKey,
        ),
      ),
    onReload: options.onReload,
    onSuccess: options.onSuccess,
    onError: options.onError,
    onCommittedReloadError: options.onCommittedReloadError,
    copy: options.copy,
  })
}

export type ClearContextOptions = {
  roomId: string
  campaignId: string
  expectedRevision: number
  token: string
  idempotencyKey: string
  confirmFn?: () => boolean
  onStart?: () => void
  onCancel?: () => void
  clearFn?: (
    roomId: string,
    campaignId: string,
    token: string,
    request: ClearCampaignRuntimeContextRequest,
  ) => Promise<CampaignRuntimeContext>
  onReload: () => Promise<void>
  onSuccess?: () => void
  onError: (errorMessage: string) => void
  onCommittedReloadError: (errorMessage: string) => void
  copy: CampaignRuntimeCopy
}

export async function handleClearContext(options: ClearContextOptions): Promise<boolean> {
  const confirmFn =
    options.confirmFn ??
    (() => (typeof window !== 'undefined' ? window.confirm(options.copy.confirmClearContext) : true))

  if (!confirmFn()) {
    options.onCancel?.()
    return false
  }

  options.onStart?.()
  const clearFn = options.clearFn ?? clearRuntimeContext
  return executeRuntimeMutation({
    action: () =>
      clearFn(
        options.roomId,
        options.campaignId,
        options.token,
        buildClearContextRequest(options.expectedRevision, options.idempotencyKey),
      ),
    onReload: options.onReload,
    onSuccess: options.onSuccess,
    onError: options.onError,
    onCommittedReloadError: options.onCommittedReloadError,
    copy: options.copy,
  })
}

export type ReviewQueueItem =
  | {
      type: 'runtime'
      entry: RuntimeWorldEntryDmView
    }
  | {
      type: 'override'
      overlay: CampaignAdventureEntryOverlayView
      adventureName: string
    }

export function collectReviewQueueItems(
  entries: RuntimeWorldEntryDmView[] = [],
  overlays: CampaignAdventureEntryOverlayView[] = [],
  attachedAdventures: AttachedAdventure[] = [],
): ReviewQueueItem[] {
  const items: ReviewQueueItem[] = []
  for (const entry of entries) {
    if (!entry.archived_at && entry.needs_review) {
      items.push({ type: 'runtime', entry })
    }
  }
  const adventureMap = new Map(attachedAdventures.map((a) => [a.adventure_id, a.name]))
  for (const overlay of overlays) {
    if (overlay.override && overlay.override.needs_review) {
      items.push({
        type: 'override',
        overlay,
        adventureName: adventureMap.get(overlay.adventure_id) || overlay.adventure_id,
      })
    }
  }
  return items
}
