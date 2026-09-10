import type { Campaign } from './campaigns'
import type { PendingActionView, RollRequestView } from './p3c'
import type { RoomSummary } from './rooms'
import type { CampaignSeat } from './seats'

export type SessionStatus = 'active' | 'ended' | 'abandoned'

export type SessionParticipantSnapshot = {
  id: string
  seat_id: string
  role: 'dm' | 'player' | 'spectator'
  controller_kind_at_join: 'human' | 'ai' | 'none'
  controller_access_session_id_at_join: string | null
  controller_ai_grant_id_at_join?: string | null
  controller_generation_at_join?: number | null
  active_character_id: string | null
}

export type SessionSnapshot = {
  id: string
  campaign_id: string
  status: SessionStatus
  dm_seat_id: string
  dm_controller_kind?: 'human' | 'ai' | 'none'
  dm_controller_access_session_id: string | null
  dm_controller_ai_grant_id?: string | null
  dm_controller_generation?: number | null
  started_at: string
  ended_at: string | null
  participants: SessionParticipantSnapshot[]
}

export type SessionResumeCharacterClass = {
  class_ref: string
  level: number
}

export type SessionResumeCharacterSummary = {
  id: string
  name: string
  level: number
  classes: SessionResumeCharacterClass[]
  version_no: number
}

export type TableEventVisibility = 'public' | 'dm_only' | 'actor_and_dm' | 'seat_private'
export type TableExecutionMode = 'self' | 'dm_proxy' | 'system'

export type TableRuntimeCursor = {
  session_id: string
  revision: number
  last_event_seq: number
}

export type TableEvent = {
  id: string
  session_id: string
  seq: number
  kind: string
  acting_seat_id: string | null
  subject_seat_id: string | null
  subject_character_id: string | null
  execution_mode: TableExecutionMode | null
  visibility: TableEventVisibility
  recipient_seat_ids: string[]
  payload_version: number
  payload: Record<string, unknown>
  created_at: string
}

export type TableEventPage = {
  session_id: string
  after_seq: number
  cursor: number
  current_seq: number
  has_more: boolean
  events: TableEvent[]
}

export type StageState = {
  session_id: string
  revision: number
  text: string | null
  image_id: string | null
  image_media_type: string | null
  image_filename: string | null
}

export type StageImageUpload = {
  media_type: 'image/png' | 'image/jpeg' | 'image/webp'
  filename?: string | null
  data_base64: string
}

export type StageUpdateRequest = {
  expected_revision: number
  text?: string | null
  image_id?: string | null
  image?: StageImageUpload | null
  idempotency_key?: string | null
}

export type ExplorationInputKind = 'dialogue' | 'action' | 'ooc' | 'whisper_dm' | 'narration'

export type ExplorationInputRequest = {
  kind: ExplorationInputKind
  text: string
  subject_seat_id?: string | null
  source_command?: 'search' | null
  idempotency_key?: string | null
}

export type SessionResume = {
  room_id: string
  campaign_id: string
  room: RoomSummary
  campaign: Campaign
  active_session: SessionSnapshot | null
  participants: SessionParticipantSnapshot[]
  seats: CampaignSeat[]
  active_characters: SessionResumeCharacterSummary[]
  caller_access_session_id: string | null
  table_runtime?: TableRuntimeCursor | null
  recent_events?: TableEventPage | null
  stage?: StageState | null
  roll_requests?: RollRequestView[]
  pending_actions?: PendingActionView[]
}

type ApiErrorPayload = { error?: { code?: string; message?: string } }

export class SessionApiError extends Error {
  constructor(readonly status: number, readonly code: string, message: string) {
    super(message)
  }
}

async function apiError(response: Response): Promise<SessionApiError> {
  let payload: ApiErrorPayload = {}
  try { payload = (await response.json()) as ApiErrorPayload } catch { /* fallback below */ }
  return new SessionApiError(
    response.status,
    payload.error?.code ?? 'session_request_failed',
    payload.error?.message ?? `Session request failed (${response.status})`,
  )
}

async function request<T>(url: string, token: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
      ...(init?.headers ?? {}),
    },
  })
  if (!response.ok) throw await apiError(response)
  return (await response.json()) as T
}

const base = (roomId: string, campaignId: string) =>
  `/api/rooms/${roomId}/campaigns/${campaignId}/sessions`

const tableBase = (roomId: string, campaignId: string, sessionId: string) =>
  `${base(roomId, campaignId)}/${sessionId}`

export function getActiveSession(
  roomId: string,
  campaignId: string,
  token: string,
): Promise<SessionResume> {
  return request(`${base(roomId, campaignId)}/active`, token)
}

export function getSession(
  roomId: string,
  campaignId: string,
  sessionId: string,
  token: string,
): Promise<SessionSnapshot> {
  return request(tableBase(roomId, campaignId, sessionId), token)
}

export function listSessionEvents(
  roomId: string,
  campaignId: string,
  sessionId: string,
  afterSeq: number,
  token: string,
  limit = 100,
): Promise<TableEventPage> {
  const query = new URLSearchParams({ after: String(afterSeq), limit: String(limit) })
  return request(`${tableBase(roomId, campaignId, sessionId)}/events?${query}`, token)
}

export function waitSessionEvents(
  roomId: string,
  campaignId: string,
  sessionId: string,
  afterSeq: number,
  token: string,
  options: { limit?: number; timeout?: number; signal?: AbortSignal } = {},
): Promise<TableEventPage> {
  const query = new URLSearchParams({
    after: String(afterSeq),
    limit: String(options.limit ?? 100),
    timeout: String(options.timeout ?? 30),
  })
  return request(`${tableBase(roomId, campaignId, sessionId)}/events/wait?${query}`, token, {
    signal: options.signal,
  })
}

export function replaceSessionStage(
  roomId: string,
  campaignId: string,
  sessionId: string,
  update: StageUpdateRequest,
  token: string,
): Promise<StageState> {
  return request(`${tableBase(roomId, campaignId, sessionId)}/stage`, token, {
    method: 'PUT',
    body: JSON.stringify(update),
  })
}

export async function getSessionStageImage(
  roomId: string,
  campaignId: string,
  sessionId: string,
  imageId: string,
  token: string,
): Promise<Blob> {
  const response = await fetch(
    `${tableBase(roomId, campaignId, sessionId)}/stage/images/${imageId}`,
    { headers: { Authorization: `Bearer ${token}` } },
  )
  if (!response.ok) throw await apiError(response)
  return response.blob()
}

export function sendExplorationInput(
  roomId: string,
  campaignId: string,
  sessionId: string,
  input: ExplorationInputRequest,
  token: string,
): Promise<TableEvent> {
  return request(`${tableBase(roomId, campaignId, sessionId)}/exploration`, token, {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function startSession(
  roomId: string,
  campaignId: string,
  token: string,
): Promise<SessionSnapshot> {
  return request(base(roomId, campaignId), token, { method: 'POST' })
}

export function lateJoinSession(
  roomId: string,
  campaignId: string,
  sessionId: string,
  seatId: string,
  token: string,
): Promise<SessionSnapshot> {
  return request(`${tableBase(roomId, campaignId, sessionId)}/late-join`, token, {
    method: 'POST',
    body: JSON.stringify({ seat_id: seatId }),
  })
}

export function endSession(
  roomId: string,
  campaignId: string,
  sessionId: string,
  token: string,
): Promise<SessionSnapshot> {
  return request(`${tableBase(roomId, campaignId, sessionId)}/end`, token, { method: 'POST' })
}

export function abandonSession(
  roomId: string,
  campaignId: string,
  sessionId: string,
  token: string,
): Promise<SessionSnapshot> {
  return request(`${tableBase(roomId, campaignId, sessionId)}/abandon`, token, { method: 'POST' })
}
