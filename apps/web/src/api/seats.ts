export type SeatRole = 'dm' | 'player' | 'spectator'
export type ControllerKind = 'human' | 'ai' | 'none'
export type PresenceStatus = 'connected' | 'offline' | 'not_applicable'
export type RoomAuthority = 'member' | 'dm' | 'owner'

export type CampaignSeat = {
  id: string
  campaign_id: string
  role: SeatRole
  label: string | null
  controller_kind: ControllerKind
  controller_access_session_id: string | null
  controller_display_name: string | null
  controller_authority: RoomAuthority | null
  presence: PresenceStatus
  selected_character_id: string | null
  archived_at: string | null
  created_at: string
  updated_at: string
}

export type LobbyController = {
  access_session_id: string
  authority: RoomAuthority
  display_name: string | null
  presence: PresenceStatus
}

export type LobbySnapshot = {
  room_id: string
  campaign_id: string
  caller_access_session_id: string | null
  seats: CampaignSeat[]
  controllers: LobbyController[]
}

type ApiErrorPayload = { error?: { code?: string; message?: string } }

export class SeatApiError extends Error {
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
    throw new SeatApiError(
      response.status,
      payload.error?.code ?? 'seat_request_failed',
      payload.error?.message ?? `Seat request failed (${response.status})`,
    )
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

const base = (roomId: string, campaignId: string) => `/api/rooms/${roomId}/campaigns/${campaignId}`

export function getLobby(roomId: string, campaignId: string, token: string): Promise<LobbySnapshot> {
  return request(`${base(roomId, campaignId)}/lobby`, token)
}

export function createSeat(
  roomId: string,
  campaignId: string,
  token: string,
  input: { role: SeatRole; label?: string | null },
): Promise<CampaignSeat> {
  return request(`${base(roomId, campaignId)}/seats`, token, {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function setSeatController(
  roomId: string,
  campaignId: string,
  seatId: string,
  token: string,
  input: { controller_kind: 'human' | 'none'; controller_access_session_id?: string | null },
): Promise<CampaignSeat> {
  return request(`${base(roomId, campaignId)}/seats/${seatId}/controller`, token, {
    method: 'PATCH',
    body: JSON.stringify(input),
  })
}

export function setSeatCharacter(
  roomId: string,
  campaignId: string,
  seatId: string,
  token: string,
  selectedCharacterId: string | null,
): Promise<CampaignSeat> {
  return request(`${base(roomId, campaignId)}/seats/${seatId}/character`, token, {
    method: 'PATCH',
    body: JSON.stringify({ selected_character_id: selectedCharacterId }),
  })
}

export function archiveSeat(roomId: string, campaignId: string, seatId: string, token: string): Promise<CampaignSeat> {
  return request(`${base(roomId, campaignId)}/seats/${seatId}/archive`, token, { method: 'POST' })
}

export function deleteSeat(roomId: string, campaignId: string, seatId: string, token: string): Promise<void> {
  return request(`${base(roomId, campaignId)}/seats/${seatId}`, token, { method: 'DELETE' })
}
