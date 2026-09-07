export type CampaignStatus = 'draft' | 'active' | 'completed' | 'archived'
export type RosterStatus = 'active' | 'inactive' | 'retired' | 'dead'

export type Campaign = {
  id: string
  room_id: string
  name: string
  ruleset: string
  status: CampaignStatus
  created_at: string
  updated_at: string
}

export type RosterEntry = {
  campaign_id: string
  character_id: string
  status: RosterStatus
  added_at: string
  updated_at: string
}

export type RoomCharacterSummary = {
  id: string
  name: string
  level: number
  class_summary: string
  version_no: number
}

type ApiErrorPayload = { error?: { code?: string; message?: string } }

export class CampaignApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message)
  }
}

async function apiError(response: Response): Promise<CampaignApiError> {
  let payload: ApiErrorPayload = {}
  try {
    payload = (await response.json()) as ApiErrorPayload
  } catch {
    // Preserve a stable fallback for non-JSON intermediaries.
  }
  return new CampaignApiError(
    response.status,
    payload.error?.code ?? 'campaign_request_failed',
    payload.error?.message ?? `Campaign request failed (${response.status})`,
  )
}

function headers(accessToken: string): HeadersInit {
  return {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${accessToken}`,
  }
}

async function request<T>(url: string, accessToken: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: { ...headers(accessToken), ...(init?.headers ?? {}) },
  })
  if (!response.ok) throw await apiError(response)
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

const base = (roomId: string) => `/api/rooms/${roomId}/campaigns`

export function listCampaigns(roomId: string, token: string): Promise<Campaign[]> {
  return request(base(roomId), token)
}

export function createCampaign(
  roomId: string,
  token: string,
  input: { name: string; ruleset: string },
): Promise<Campaign> {
  return request(base(roomId), token, {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function getCampaign(roomId: string, campaignId: string, token: string): Promise<Campaign> {
  return request(`${base(roomId)}/${campaignId}`, token)
}

export function setCampaignStatus(
  roomId: string,
  campaignId: string,
  token: string,
  status: CampaignStatus,
): Promise<Campaign> {
  return request(`${base(roomId)}/${campaignId}/status`, token, {
    method: 'PATCH',
    body: JSON.stringify({ status }),
  })
}

export function selectCampaign(roomId: string, campaignId: string, token: string): Promise<Campaign> {
  return request(`${base(roomId)}/${campaignId}/select`, token, { method: 'POST' })
}

export function clearCampaignSelection(roomId: string, token: string): Promise<void> {
  return request(`${base(roomId)}/selection`, token, { method: 'DELETE' })
}

export function deleteCampaign(roomId: string, campaignId: string, token: string): Promise<void> {
  return request(`${base(roomId)}/${campaignId}`, token, { method: 'DELETE' })
}

export function listRoster(roomId: string, campaignId: string, token: string): Promise<RosterEntry[]> {
  return request(`${base(roomId)}/${campaignId}/roster`, token)
}

export function addRosterCharacter(
  roomId: string,
  campaignId: string,
  characterId: string,
  token: string,
): Promise<RosterEntry> {
  return request(`${base(roomId)}/${campaignId}/roster`, token, {
    method: 'POST',
    body: JSON.stringify({ character_id: characterId, status: 'active' }),
  })
}

export function setRosterStatus(
  roomId: string,
  campaignId: string,
  characterId: string,
  token: string,
  status: RosterStatus,
): Promise<RosterEntry> {
  return request(`${base(roomId)}/${campaignId}/roster/${characterId}`, token, {
    method: 'PATCH',
    body: JSON.stringify({ status }),
  })
}

export function removeRosterCharacter(
  roomId: string,
  campaignId: string,
  characterId: string,
  token: string,
): Promise<void> {
  return request(`${base(roomId)}/${campaignId}/roster/${characterId}`, token, {
    method: 'DELETE',
  })
}

export function listRoomCharacters(roomId: string, token: string): Promise<RoomCharacterSummary[]> {
  return request(`/api/rooms/${roomId}/characters`, token)
}
