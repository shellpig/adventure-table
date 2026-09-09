import { SessionApiError } from './sessions'

export type PendingActionStatus =
  | 'pending'
  | 'processing'
  | 'waiting_for_roll'
  | 'resolved'
  | 'cancelled'

export type PendingActionView = {
  id: string
  session_id: string
  acting_seat_id: string
  subject_seat_id: string
  subject_character_id: string | null
  execution_mode: 'self' | 'dm_proxy' | 'system'
  text: string | null
  intent_payload: Record<string, unknown> | null
  status: PendingActionStatus
  roll_request_id: string | null
  version: number
}

export type PendingActionCreateInput = {
  subject_seat_id: string
  text?: string | null
  intent_payload?: Record<string, unknown> | null
  idempotency_key?: string | null
}

export type RollVisibility = 'public' | 'roller_and_dm' | 'dm_only'
export type RollModifierMode = 'normal' | 'advantage' | 'disadvantage'
export type RollRequestType = 'ability' | 'skill' | 'saving_throw' | 'other'
export type FormalRollSource = 'server' | 'physical'

export type RollRequestView = {
  id: string
  session_id: string
  roll_group_id: string | null
  target_seat_id: string
  target_character_id: string | null
  request_type: RollRequestType
  ability_ref: string | null
  skill_ref: string | null
  dc: number | null
  modifier_mode: RollModifierMode
  flat_adjustment: number
  visibility: RollVisibility
  status: 'pending' | 'resolved' | 'cancelled'
  requested_by_seat_id: string
  version: number
}

export type RollResultView = {
  id: string
  roll_request_id: string | null
  session_id: string
  acting_seat_id: string
  subject_seat_id: string
  subject_character_id: string | null
  execution_mode: 'self' | 'dm_proxy' | 'system'
  source: 'server' | 'physical' | 'quick'
  formula: string
  raw_dice: number[]
  kept_dice: number[]
  base_modifier: number
  flat_adjustment: number
  total: number
  visibility: RollVisibility
}

export type RequestCheckInput = {
  target_seat_ids: string[]
  request_type: RollRequestType
  ability_ref?: string | null
  skill_ref?: string | null
  dc?: number | null
  modifier_mode?: RollModifierMode
  flat_adjustment?: number
  visibility?: RollVisibility
  label?: string | null
  idempotency_key?: string | null
}

export type RequestCheckResponse = {
  roll_group_id: string
  requests: RollRequestView[]
}

export type FormalRollInput = {
  roll_request_id: string
  source?: FormalRollSource
  raw_dice?: number[] | null
  idempotency_key?: string | null
}

export type QuickRollInput = {
  subject_seat_id: string
  dice_count?: number
  die_sides?: number
  flat_adjustment?: number
  visibility?: RollVisibility
  idempotency_key?: string | null
}

export type RollSubmissionResponse = {
  result_id: string
  roll_request_id: string | null
  hidden: boolean
  result: RollResultView | null
}

type ApiErrorPayload = { error?: { code?: string; message?: string } }

async function apiError(response: Response): Promise<SessionApiError> {
  let payload: ApiErrorPayload = {}
  try { payload = (await response.json()) as ApiErrorPayload } catch { /* fallback below */ }
  return new SessionApiError(
    response.status,
    payload.error?.code ?? 'p3c_request_failed',
    payload.error?.message ?? `P3-C request failed (${response.status})`,
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

const tableBase = (roomId: string, campaignId: string, sessionId: string) =>
  `/api/rooms/${roomId}/campaigns/${campaignId}/sessions/${sessionId}`

export function createPendingAction(
  roomId: string,
  campaignId: string,
  sessionId: string,
  input: PendingActionCreateInput,
  token: string,
): Promise<PendingActionView> {
  return request(`${tableBase(roomId, campaignId, sessionId)}/pending-actions`, token, {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function requestCheck(
  roomId: string,
  campaignId: string,
  sessionId: string,
  input: RequestCheckInput,
  token: string,
): Promise<RequestCheckResponse> {
  return request(`${tableBase(roomId, campaignId, sessionId)}/checks`, token, {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function listRollRequests(
  roomId: string,
  campaignId: string,
  sessionId: string,
  token: string,
): Promise<RollRequestView[]> {
  return request(`${tableBase(roomId, campaignId, sessionId)}/roll-requests`, token)
}

export function submitFormalRoll(
  roomId: string,
  campaignId: string,
  sessionId: string,
  input: FormalRollInput,
  token: string,
): Promise<RollSubmissionResponse> {
  return request(`${tableBase(roomId, campaignId, sessionId)}/rolls/formal`, token, {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function submitQuickRoll(
  roomId: string,
  campaignId: string,
  sessionId: string,
  input: QuickRollInput,
  token: string,
): Promise<RollSubmissionResponse> {
  return request(`${tableBase(roomId, campaignId, sessionId)}/rolls/quick`, token, {
    method: 'POST',
    body: JSON.stringify(input),
  })
}
