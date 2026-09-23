import type {
  AdventureDefinition,
  AdventureEntryKind,
  AdventureEntryPayload,
  AdventureEntryVisibility,
} from './adventures'

export type ImportStatus = 'source' | 'drafting' | 'review' | 'finalized' | 'cancelled'
export type SourceKind = 'paste' | 'txt' | 'markdown' | 'pdf' | 'docx' | 'url'
export type DraftProvenance =
  | 'source_document'
  | 'user_explicit'
  | 'user_approximation'
  | 'ai_generated'
export type WarningLevel = 'info' | 'warning' | 'blocking'
export type ReviewStatus = 'pending' | 'accepted' | 'ignored' | 'uncertain'

export type AdventureImport = {
  id: string
  room_id: string
  name: string
  status: ImportStatus
  target_adventure_id: string | null
  revision: number
  created_at: string
  updated_at: string
}

export type AdventureImportSource = {
  id: string
  import_id: string
  asset_id: string | null
  source_kind: SourceKind
  source_url: string | null
  metadata_json: Record<string, unknown>
  sha256: string
  text_length: number
  created_at: string
}

export type SourceChunk = {
  source_id: string
  offset: number
  text: string
  total_length: number
  next_offset: number | null
}

export type DraftSourceRef = {
  source_id: string
  locator: string | null
}

export type DraftEntry = {
  entry_id: string
  entry_kind: AdventureEntryKind
  payload: AdventureEntryPayload
  parent_entry_id: string | null
  provenance: DraftProvenance
  source_ref: DraftSourceRef | null
  note: string | null
  review_status: ReviewStatus
  asset_ids: string[]
  title: string | null
  body: string | null
  visibility: AdventureEntryVisibility
}

export type DraftWarning = {
  warning_id: string
  level: WarningLevel
  code: string
  message: string
  entry_id: string | null
  source_id: string | null
  resolved: boolean
  resolution: string | null
}

export type DraftQuestion = {
  question_id: string
  message: string
  entry_id: string | null
  answer: string | null
}

export type ImportDraft = {
  schema_version: 1
  entries: DraftEntry[]
  questions: DraftQuestion[]
}

export type AdventureImportDraft = {
  import_id: string
  draft: ImportDraft
  warnings: DraftWarning[]
  revision: number
  updated_at: string
}

export type CreateAdventureImportInput = {
  name: string
}

export type CancelAdventureImportInput = {
  expected_revision: number
}

export type PasteSourceInput = {
  source_kind: 'paste'
  text: string
  filename?: string | null
  media_type?: string | null
}

export type UrlSourceInput = {
  source_kind: 'url'
  url: string
  text?: string | null
  excerpt?: string | null
  title?: string | null
}

export type JsonSourceInput = PasteSourceInput | UrlSourceInput

export type RawUploadSourceInput = {
  source_kind: 'txt' | 'markdown' | 'pdf' | 'docx'
  filename: string
  file: Blob
}

export type AddSourceFromAssetInput = {
  asset_id: string
}

export type DraftSourceRefInput = {
  source_id: string
  locator?: string | null
}

export type DraftEntryInput = {
  entry_id: string
  entry_kind: AdventureEntryKind
  payload: AdventureEntryPayload
  parent_entry_id?: string | null
  provenance?: DraftProvenance
  source_ref?: DraftSourceRefInput | null
  note?: string | null
  review_status?: ReviewStatus
  asset_ids?: string[]
  title?: string | null
  body?: string | null
  visibility?: AdventureEntryVisibility
}

export type DraftWarningInput = {
  warning_id: string
  level: WarningLevel
  code: string
  message: string
  entry_id?: string | null
  source_id?: string | null
  resolved?: boolean
  resolution?: string | null
}

export type DraftQuestionInput = {
  question_id: string
  message: string
  entry_id?: string | null
  answer?: string | null
}

export type ImportDraftInput = {
  schema_version?: 1
  entries?: DraftEntryInput[]
  questions?: DraftQuestionInput[]
}

export type UpdateImportDraftInput = {
  draft: ImportDraftInput
  warnings?: DraftWarningInput[]
  expected_revision: number
}

export type SetEntryReviewInput = {
  review_status: ReviewStatus
  expected_revision: number
}

export type ResolveWarningInput = {
  resolution?: string | null
  expected_revision: number
}

export type AnswerQuestionInput = {
  answer: string
  expected_revision: number
}

export type FinalizeAdventureImportInput = {
  name: string
  summary?: string | null
  expected_revision: number
}

type ApiErrorPayload = { error?: { code?: string; message?: string } }

export class AdventureImportApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message)
  }
}

async function apiError(response: Response): Promise<AdventureImportApiError> {
  let payload: ApiErrorPayload = {}
  try {
    payload = (await response.json()) as ApiErrorPayload
  } catch {
    // Preserve a stable fallback for non-JSON intermediaries.
  }
  return new AdventureImportApiError(
    response.status,
    payload.error?.code ?? 'adventure_import_request_failed',
    payload.error?.message ?? `Adventure import request failed (${response.status})`,
  )
}

function authHeaders(accessToken: string): HeadersInit {
  return {
    Authorization: `Bearer ${accessToken}`,
  }
}

async function request<T>(url: string, accessToken: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: {
      ...authHeaders(accessToken),
      ...(init?.headers ?? {}),
    },
  })
  if (!response.ok) throw await apiError(response)
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

const base = (roomId: string) => `/api/rooms/${roomId}/adventure-imports`

export function createAdventureImport(
  roomId: string,
  token: string,
  input: CreateAdventureImportInput,
): Promise<AdventureImport> {
  return request(base(roomId), token, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
}

export function listAdventureImports(
  roomId: string,
  token: string,
): Promise<AdventureImport[]> {
  return request(base(roomId), token)
}

export function getAdventureImport(
  roomId: string,
  importId: string,
  token: string,
): Promise<AdventureImport> {
  return request(`${base(roomId)}/${importId}`, token)
}

export function cancelAdventureImport(
  roomId: string,
  importId: string,
  token: string,
  input: CancelAdventureImportInput,
): Promise<AdventureImport> {
  return request(`${base(roomId)}/${importId}/cancel`, token, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
}

export function addJsonSource(
  roomId: string,
  importId: string,
  token: string,
  input: JsonSourceInput,
): Promise<AdventureImportSource> {
  return request(`${base(roomId)}/${importId}/sources`, token, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
}

export async function uploadRawSource(
  roomId: string,
  importId: string,
  token: string,
  input: RawUploadSourceInput,
): Promise<AdventureImportSource> {
  const params = new URLSearchParams({
    source_kind: input.source_kind,
    filename: input.filename,
  })
  const url = `${base(roomId)}/${importId}/sources?${params.toString()}`
  const contentType = input.file.type || 'application/octet-stream'

  const response = await fetch(url, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': contentType,
    },
    body: input.file,
  })
  if (!response.ok) throw await apiError(response)
  return (await response.json()) as AdventureImportSource
}

export function listAdventureImportSources(
  roomId: string,
  importId: string,
  token: string,
): Promise<AdventureImportSource[]> {
  return request(`${base(roomId)}/${importId}/sources`, token)
}

export function addSourceFromAsset(
  roomId: string,
  importId: string,
  token: string,
  input: AddSourceFromAssetInput,
): Promise<AdventureImportSource> {
  return request(`${base(roomId)}/${importId}/sources/from-asset`, token, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
}

export function readSourceChunk(
  roomId: string,
  importId: string,
  sourceId: string,
  token: string,
  params?: { offset?: number; limit?: number },
): Promise<SourceChunk> {
  const query = new URLSearchParams()
  query.set('offset', String(params?.offset ?? 0))
  if (params?.limit !== undefined) {
    query.set('limit', String(params.limit))
  }
  const url = `${base(roomId)}/${importId}/sources/${encodeURIComponent(sourceId)}/chunk?${query.toString()}`
  return request(url, token)
}

export function getAdventureImportDraft(
  roomId: string,
  importId: string,
  token: string,
): Promise<AdventureImportDraft> {
  return request(`${base(roomId)}/${importId}/draft`, token)
}

export function updateAdventureImportDraft(
  roomId: string,
  importId: string,
  token: string,
  input: UpdateImportDraftInput,
): Promise<AdventureImportDraft> {
  return request(`${base(roomId)}/${importId}/draft`, token, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
}

export function setAdventureImportEntryReview(
  roomId: string,
  importId: string,
  entryId: string,
  token: string,
  input: SetEntryReviewInput,
): Promise<AdventureImportDraft> {
  return request(
    `${base(roomId)}/${importId}/draft/entries/${encodeURIComponent(entryId)}/review`,
    token,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    },
  )
}

export function resolveAdventureImportWarning(
  roomId: string,
  importId: string,
  warningId: string,
  token: string,
  input: ResolveWarningInput,
): Promise<AdventureImportDraft> {
  return request(
    `${base(roomId)}/${importId}/warnings/${encodeURIComponent(warningId)}/resolve`,
    token,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    },
  )
}

export function answerAdventureImportQuestion(
  roomId: string,
  importId: string,
  questionId: string,
  token: string,
  input: AnswerQuestionInput,
): Promise<AdventureImportDraft> {
  return request(
    `${base(roomId)}/${importId}/questions/${encodeURIComponent(questionId)}/answer`,
    token,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    },
  )
}

export function finalizeAdventureImport(
  roomId: string,
  importId: string,
  token: string,
  input: FinalizeAdventureImportInput,
): Promise<AdventureDefinition> {
  return request(`${base(roomId)}/${importId}/finalize`, token, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
}
