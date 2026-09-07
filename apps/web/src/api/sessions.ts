import type { Campaign } from './campaigns'
import type { RoomSummary } from './rooms'
import type { CampaignSeat } from './seats'

export type SessionStatus = 'active' | 'ended' | 'abandoned'

export type SessionParticipantSnapshot = {
  id: string
  seat_id: string
  role: 'dm' | 'player' | 'spectator'
  controller_kind_at_join: 'human' | 'ai' | 'none'
  controller_access_session_id_at_join: string | null
  active_character_id: string | null
}

export type SessionSnapshot = {
  id: string
  campaign_id: string
  status: SessionStatus
  dm_seat_id: string
  dm_controller_access_session_id: string | null
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

export type SessionResume = {
  room_id: string
  campaign_id: string
  room: RoomSummary
  campaign: Campaign
  active_session: SessionSnapshot | null
  participants: SessionParticipantSnapshot[]
  seats: CampaignSeat[]
  active_characters: SessionResumeCharacterSummary[]
}

type ApiErrorPayload = { error?: { code?: string; message?: string } }

export class SessionApiError extends Error {
  constructor(readonly status: number, readonly code: string, message: string) {
    super(message)
  }
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
  if (!response.ok) {
    let payload: ApiErrorPayload = {}
    try { payload = (await response.json()) as ApiErrorPayload } catch { /* fallback below */ }
    throw new SessionApiError(
      response.status,
      payload.error?.code ?? 'session_request_failed',
      payload.error?.message ?? `Session request failed (${response.status})`,
    )
  }
  return (await response.json()) as T
}

const base = (roomId: string, campaignId: string) =>
  `/api/rooms/${roomId}/campaigns/${campaignId}/sessions`

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
  return request(`${base(roomId, campaignId)}/${sessionId}`, token)
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
  return request(`${base(roomId, campaignId)}/${sessionId}/late-join`, token, {
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
  return request(`${base(roomId, campaignId)}/${sessionId}/end`, token, { method: 'POST' })
}

export function abandonSession(
  roomId: string,
  campaignId: string,
  sessionId: string,
  token: string,
): Promise<SessionSnapshot> {
  return request(`${base(roomId, campaignId)}/${sessionId}/abandon`, token, { method: 'POST' })
}
