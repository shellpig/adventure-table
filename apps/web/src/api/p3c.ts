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
