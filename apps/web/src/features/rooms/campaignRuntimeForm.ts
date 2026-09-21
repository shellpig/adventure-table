import {
  listCampaignAdventures,
  type AttachedAdventure,
} from '../../api/adventures'
import {
  archiveRuntimeEntry,
  CampaignRuntimeApiError,
  getRuntimeContext,
  listAdventureEntryOverlays,
  listOverrides,
  listRuntimeEntries,
  type ArchiveRuntimeWorldEntryRequest,
  type CampaignAdventureEntryOverlayView,
  type CampaignAdventureOverride,
  type CampaignRuntimeContext,
  type CreateRuntimeWorldEntryRequest,
  type RuntimeEntryKind,
  type RuntimeItemHolderKind,
  type RuntimeVisibility,
  type RuntimeWorldEntryDmView,
  type UpdateRuntimeWorldEntryRequest,
} from '../../api/campaignRuntime'
import {
  listRoomCharacters,
  type RoomCharacterSummary,
} from '../../api/campaigns'
import {
  campaignRuntimeErrorMessage,
  type CampaignRuntimeCopy,
} from './campaignRuntimeCopy'

export const EDITABLE_RUNTIME_ENTRY_KINDS = [
  'scene',
  'npc',
  'item',
  'quest',
  'fact',
  'secret',
  'other',
] as const

export type EditableRuntimeEntryKind = (typeof EDITABLE_RUNTIME_ENTRY_KINDS)[number]

export function isEditableRuntimeEntryKind(kind: string): kind is EditableRuntimeEntryKind {
  return (EDITABLE_RUNTIME_ENTRY_KINDS as readonly string[]).includes(kind)
}

export type CommonEntryFormState = {
  kind: EditableRuntimeEntryKind
  title: string
  body: string
  visibility: RuntimeVisibility
  characterRecipientIds: string[]
  dmNotes: string
  needsReview: boolean
  provenanceJson: string
  npcMonsterInstanceId: string
  npcMonsterTemplateRef: string
  itemHolderKind: '' | RuntimeItemHolderKind
  itemHolderTargetId: string
  otherDataJson: string
}

export type CreateRuntimeEntryFormState = CommonEntryFormState & {
  mode: 'create'
}

export type EditRuntimeEntryFormState = CommonEntryFormState & {
  mode: 'edit'
  entryId: string
  expectedRevision: number
  sourceAdventureEntryId: string | null
}

export type RuntimeEntryFormState = CreateRuntimeEntryFormState | EditRuntimeEntryFormState

export type ValidationErrorKey =
  | 'errNpcTitleRequired'
  | 'errFactBodyRequired'
  | 'errSceneRequired'
  | 'errCharacterRecipientsRequired'
  | 'errItemHolderTargetRequired'
  | 'errOtherDataInvalidJson'
  | 'errOtherDataScalarOnly'
  | 'errProvenanceInvalidJson'

export type ValidationResult<T> =
  | { ok: true; value: T }
  | { ok: false; errorKey: ValidationErrorKey }

export function createInitialEntryFormState(
  defaultKind: EditableRuntimeEntryKind = 'scene',
): CreateRuntimeEntryFormState {
  return {
    mode: 'create',
    kind: defaultKind,
    title: '',
    body: '',
    visibility: defaultKind === 'secret' ? 'dm_only' : 'public',
    characterRecipientIds: [],
    dmNotes: '',
    needsReview: false,
    provenanceJson: '',
    npcMonsterInstanceId: '',
    npcMonsterTemplateRef: '',
    itemHolderKind: '',
    itemHolderTargetId: '',
    otherDataJson: '',
  }
}

export function onFormKindChange(
  state: RuntimeEntryFormState,
  newKind: EditableRuntimeEntryKind,
): RuntimeEntryFormState {
  if (state.mode === 'edit') return state
  const nextVisibility =
    newKind === 'secret' && state.visibility === 'public'
      ? 'dm_only'
      : state.visibility
  return {
    ...state,
    kind: newKind,
    visibility: nextVisibility,
  }
}

export function onFormVisibilityChange<T extends RuntimeEntryFormState>(
  state: T,
  newVisibility: RuntimeVisibility,
): T {
  return {
    ...state,
    visibility: newVisibility,
    characterRecipientIds: newVisibility === 'character' ? state.characterRecipientIds : [],
  }
}

export function entryToFormState(
  entry: RuntimeWorldEntryDmView,
): EditRuntimeEntryFormState | null {
  if (!isEditableRuntimeEntryKind(entry.kind)) {
    return null
  }

  let npcMonsterInstanceId = ''
  let npcMonsterTemplateRef = ''
  let itemHolderKind: '' | RuntimeItemHolderKind = ''
  let itemHolderTargetId = ''
  let otherDataJson = ''

  if (entry.state.kind === 'npc') {
    npcMonsterInstanceId = entry.state.monster_instance_id ?? ''
    npcMonsterTemplateRef = entry.state.monster_template_ref ?? ''
  } else if (entry.state.kind === 'item') {
    if (entry.state.holder_ref) {
      itemHolderKind = entry.state.holder_ref.kind
      itemHolderTargetId = entry.state.holder_ref.target_id ?? ''
    }
  } else if (entry.state.kind === 'other') {
    otherDataJson =
      entry.state.data && Object.keys(entry.state.data).length > 0
        ? JSON.stringify(entry.state.data, null, 2)
        : ''
  }

  return {
    mode: 'edit',
    entryId: entry.id,
    expectedRevision: entry.revision,
    kind: entry.kind,
    title: entry.title ?? '',
    body: entry.body ?? '',
    visibility: entry.visibility,
    characterRecipientIds: [...entry.character_recipient_ids],
    dmNotes: entry.dm_notes ?? '',
    needsReview: entry.needs_review,
    provenanceJson: entry.provenance_json ? JSON.stringify(entry.provenance_json, null, 2) : '',
    sourceAdventureEntryId: entry.source_adventure_entry_id,
    npcMonsterInstanceId,
    npcMonsterTemplateRef,
    itemHolderKind,
    itemHolderTargetId,
    otherDataJson,
  }
}

export function validateEntryMinima(
  kind: RuntimeEntryKind,
  title: string,
  body: string,
): ValidationErrorKey | null {
  const titleNonblank = Boolean(title && title.trim())
  const bodyNonblank = Boolean(body && body.trim())

  if (kind === 'npc') {
    if (!titleNonblank) return 'errNpcTitleRequired'
  } else if (kind === 'fact') {
    if (!bodyNonblank) return 'errFactBodyRequired'
  } else if (kind === 'scene') {
    if (!titleNonblank && !bodyNonblank) return 'errSceneRequired'
  }
  return null
}

export function validateAndParseOtherData(
  rawJson: string,
): ValidationResult<Record<string, string | number | boolean>> {
  const trimmed = rawJson.trim()
  if (!trimmed) {
    return { ok: true, value: {} }
  }
  let parsed: unknown
  try {
    parsed = JSON.parse(trimmed)
  } catch {
    return { ok: false, errorKey: 'errOtherDataInvalidJson' }
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    return { ok: false, errorKey: 'errOtherDataInvalidJson' }
  }
  for (const [, val] of Object.entries(parsed)) {
    const valType = typeof val
    if (val === null || (valType !== 'string' && valType !== 'number' && valType !== 'boolean')) {
      return { ok: false, errorKey: 'errOtherDataScalarOnly' }
    }
  }
  return { ok: true, value: parsed as Record<string, string | number | boolean> }
}

export function validateAndParseProvenanceJson(
  rawJson: string,
): ValidationResult<Record<string, unknown> | null> {
  const trimmed = rawJson.trim()
  if (!trimmed) {
    return { ok: true, value: null }
  }
  let parsed: unknown
  try {
    parsed = JSON.parse(trimmed)
  } catch {
    return { ok: false, errorKey: 'errProvenanceInvalidJson' }
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    return { ok: false, errorKey: 'errProvenanceInvalidJson' }
  }
  return { ok: true, value: parsed as Record<string, unknown> }
}

export function buildTypedState(
  form: RuntimeEntryFormState,
): ValidationResult<Record<string, unknown>> {
  switch (form.kind) {
    case 'scene':
      return { ok: true, value: { kind: 'scene' } }
    case 'quest':
      return { ok: true, value: { kind: 'quest' } }
    case 'fact':
      return { ok: true, value: { kind: 'fact' } }
    case 'secret':
      return { ok: true, value: { kind: 'secret' } }
    case 'npc': {
      const instanceId = form.npcMonsterInstanceId.trim() || null
      const templateRef = form.npcMonsterTemplateRef.trim() || null
      return {
        ok: true,
        value: {
          kind: 'npc',
          monster_instance_id: instanceId,
          monster_template_ref: templateRef,
        },
      }
    }
    case 'item': {
      if (!form.itemHolderKind) {
        return { ok: true, value: { kind: 'item', holder_ref: null } }
      }
      const holderKind = form.itemHolderKind
      if (holderKind === 'party' || holderKind === 'unknown') {
        return {
          ok: true,
          value: {
            kind: 'item',
            holder_ref: {
              kind: holderKind,
              target_id: null,
            },
          },
        }
      }
      const targetId = form.itemHolderTargetId.trim()
      if (!targetId) {
        return { ok: false, errorKey: 'errItemHolderTargetRequired' }
      }
      return {
        ok: true,
        value: {
          kind: 'item',
          holder_ref: {
            kind: holderKind,
            target_id: targetId,
          },
        },
      }
    }
    case 'other': {
      const parsedOther = validateAndParseOtherData(form.otherDataJson)
      if (!parsedOther.ok) {
        return parsedOther
      }
      return {
        ok: true,
        value: {
          kind: 'other',
          data: parsedOther.value,
        },
      }
    }
  }
}

export function buildCreateEntryRequest(
  form: CreateRuntimeEntryFormState,
  idempotencyKey: string,
): ValidationResult<CreateRuntimeWorldEntryRequest> {
  const minimaError = validateEntryMinima(form.kind, form.title, form.body)
  if (minimaError) {
    return { ok: false, errorKey: minimaError }
  }

  if (form.visibility === 'character') {
    const recipients = [...new Set(form.characterRecipientIds.filter(Boolean))]
    if (recipients.length === 0) {
      return { ok: false, errorKey: 'errCharacterRecipientsRequired' }
    }
  }

  const typedStateResult = buildTypedState(form)
  if (!typedStateResult.ok) {
    return typedStateResult
  }

  const provenanceResult = validateAndParseProvenanceJson(form.provenanceJson)
  if (!provenanceResult.ok) {
    return provenanceResult
  }

  const recipients =
    form.visibility === 'character'
      ? [...new Set(form.characterRecipientIds.filter(Boolean))]
      : []

  const req: CreateRuntimeWorldEntryRequest = {
    idempotency_key: idempotencyKey,
    kind: form.kind,
    title: form.title.trim() || null,
    body: form.body.trim() || null,
    state: typedStateResult.value,
    visibility: form.visibility,
    character_recipient_ids: recipients,
    dm_notes: form.dmNotes.trim() || null,
    needs_review: form.needsReview,
    provenance_json: provenanceResult.value,
  }
  return { ok: true, value: req }
}

export function buildUpdateEntryRequest(
  form: EditRuntimeEntryFormState,
  idempotencyKey: string,
): ValidationResult<UpdateRuntimeWorldEntryRequest> {
  const minimaError = validateEntryMinima(form.kind, form.title, form.body)
  if (minimaError) {
    return { ok: false, errorKey: minimaError }
  }

  if (form.visibility === 'character') {
    const recipients = [...new Set(form.characterRecipientIds.filter(Boolean))]
    if (recipients.length === 0) {
      return { ok: false, errorKey: 'errCharacterRecipientsRequired' }
    }
  }

  const typedStateResult = buildTypedState(form)
  if (!typedStateResult.ok) {
    return typedStateResult
  }

  const provenanceResult = validateAndParseProvenanceJson(form.provenanceJson)
  if (!provenanceResult.ok) {
    return provenanceResult
  }

  const recipients =
    form.visibility === 'character'
      ? [...new Set(form.characterRecipientIds.filter(Boolean))]
      : []

  const req: UpdateRuntimeWorldEntryRequest = {
    idempotency_key: idempotencyKey,
    expected_revision: form.expectedRevision,
    title: form.title.trim() || null,
    body: form.body.trim() || null,
    state: typedStateResult.value,
    visibility: form.visibility,
    character_recipient_ids: recipients,
    dm_notes: form.dmNotes.trim() || null,
    needs_review: form.needsReview,
    provenance_json: provenanceResult.value,
  }
  return { ok: true, value: req }
}

export function generateRuntimeIdempotencyKey(prefix: string): string {
  const random = globalThis.crypto?.randomUUID?.()
  return random ? `${prefix}-${random}` : `${prefix}-${Date.now()}-${Math.random()}`
}

export type CampaignChangesSnapshot = {
  entries: RuntimeWorldEntryDmView[]
  overrides: CampaignAdventureOverride[]
  context: CampaignRuntimeContext
  characters: RoomCharacterSummary[]
  attachedAdventures: AttachedAdventure[]
  overlays: CampaignAdventureEntryOverlayView[]
}

export async function loadCampaignChanges(
  roomId: string,
  campaignId: string,
  token: string,
): Promise<CampaignChangesSnapshot> {
  const [entries, overrides, context, characters, attachedAdventures] = await Promise.all([
    listRuntimeEntries(roomId, campaignId, token),
    listOverrides(roomId, campaignId, token),
    getRuntimeContext(roomId, campaignId, token),
    listRoomCharacters(roomId, token),
    listCampaignAdventures(roomId, campaignId, token),
  ])

  let overlays: CampaignAdventureEntryOverlayView[] = []
  if (attachedAdventures.length > 0) {
    const overlayLists = await Promise.all(
      attachedAdventures.map((adv) =>
        listAdventureEntryOverlays(roomId, campaignId, adv.adventure_id, token),
      ),
    )
    overlays = overlayLists.flat()
  }

  return {
    entries,
    overrides,
    context,
    characters,
    attachedAdventures,
    overlays,
  }
}

export type ExecuteRuntimeMutationOptions<T> = {
  action: () => Promise<T>
  onReload: () => Promise<void>
  onSuccess?: (result: T) => void
  onError: (errorMessage: string) => void
  onConflict?: (errorMessage: string) => void
  onCommittedReloadError: (errorMessage: string) => void
  copy: CampaignRuntimeCopy
}

export async function executeRuntimeMutation<T>({
  action,
  onReload,
  onSuccess,
  onError,
  onConflict,
  onCommittedReloadError,
  copy,
}: ExecuteRuntimeMutationOptions<T>): Promise<boolean> {
  let result: T
  try {
    result = await action()
  } catch (err) {
    const isConflict =
      err instanceof CampaignRuntimeApiError
        ? err.code === 'campaign_runtime_revision_conflict'
        : typeof err === 'object' &&
          err !== null &&
          'code' in err &&
          (err as { code: unknown }).code === 'campaign_runtime_revision_conflict'

    if (isConflict) {
      try {
        await onReload()
        const message = campaignRuntimeErrorMessage(err, copy)
        if (onConflict) {
          onConflict(message)
        } else {
          onError(message)
        }
        return false
      } catch (reloadErr) {
        const reloadMessage = campaignRuntimeErrorMessage(reloadErr, copy)
        onError(reloadMessage)
        return false
      }
    }
    const message = campaignRuntimeErrorMessage(err, copy)
    onError(message)
    return false
  }

  try {
    await onReload()
  } catch (reloadErr) {
    const reloadMessage = campaignRuntimeErrorMessage(reloadErr, copy)
    onCommittedReloadError(reloadMessage)
    return false
  }

  onSuccess?.(result)
  return true
}

export type ArchiveRuntimeEntryOptions = {
  roomId: string
  campaignId: string
  entryId: string
  revision: number
  token: string
  idempotencyKey: string
  confirmFn?: () => boolean
  onStart?: () => void
  onCancel?: () => void
  archiveFn?: (
    roomId: string,
    campaignId: string,
    entryId: string,
    token: string,
    request: ArchiveRuntimeWorldEntryRequest,
  ) => Promise<RuntimeWorldEntryDmView>
  onReload: () => Promise<void>
  onSuccess?: () => void
  onError: (errorMessage: string) => void
  onCommittedReloadError: (errorMessage: string) => void
  copy: CampaignRuntimeCopy
}

export async function handleArchiveRuntimeEntry(
  options: ArchiveRuntimeEntryOptions,
): Promise<boolean> {
  const confirmFn =
    options.confirmFn ??
    (() => (typeof window !== 'undefined' ? window.confirm(options.copy.confirmArchive) : true))

  if (!confirmFn()) {
    options.onCancel?.()
    return false
  }

  options.onStart?.()
  const archiveFn = options.archiveFn ?? archiveRuntimeEntry
  return executeRuntimeMutation({
    action: () =>
      archiveFn(options.roomId, options.campaignId, options.entryId, options.token, {
        expected_revision: options.revision,
        idempotency_key: options.idempotencyKey,
      }),
    onReload: options.onReload,
    onSuccess: options.onSuccess,
    onError: options.onError,
    onCommittedReloadError: options.onCommittedReloadError,
    copy: options.copy,
  })
}
