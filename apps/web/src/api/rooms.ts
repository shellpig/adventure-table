export type RoomAuthority = 'member' | 'dm' | 'owner'

export type RoomSummary = {
  id: string
  code: string
  name: string
  created_at: string
  updated_at: string
}

export type RoomAccessGrant = {
  room: RoomSummary
  authority: RoomAuthority
  access_session_id: string
  access_token: string
  owner_key: string | null
  dm_key: string | null
}

type ApiErrorPayload = {
  error?: {
    code?: string
    message?: string
  }
}

export class RoomApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message)
  }
}

async function roomError(response: Response): Promise<RoomApiError> {
  let payload: ApiErrorPayload = {}
  try {
    payload = (await response.json()) as ApiErrorPayload
  } catch {
    // Stable fallback when an intermediary returns non-JSON.
  }
  return new RoomApiError(
    response.status,
    payload.error?.code ?? 'room_request_failed',
    payload.error?.message ?? `Room request failed (${response.status})`,
  )
}

async function jsonRequest<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) throw await roomError(response)
  return (await response.json()) as T
}

function jsonHeaders(token?: string): HeadersInit {
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }
}

export function createRoom(input: {
  name: string
  password: string
  displayName?: string
}): Promise<RoomAccessGrant> {
  return jsonRequest('/api/rooms', {
    method: 'POST',
    headers: jsonHeaders(),
    body: JSON.stringify({
      name: input.name,
      password: input.password,
      display_name: input.displayName || null,
    }),
  })
}

export function enterRoom(input: {
  code: string
  password: string
  elevatedKey?: string
  displayName?: string
}): Promise<RoomAccessGrant> {
  return jsonRequest('/api/rooms/enter', {
    method: 'POST',
    headers: jsonHeaders(),
    body: JSON.stringify({
      code: input.code,
      password: input.password,
      elevated_key: input.elevatedKey || null,
      display_name: input.displayName || null,
    }),
  })
}

export function getRoom(roomId: string, accessToken: string): Promise<RoomSummary> {
  return jsonRequest(`/api/rooms/${roomId}`, {
    headers: jsonHeaders(accessToken),
  })
}

export async function heartbeatRoom(roomId: string, accessToken: string): Promise<void> {
  await jsonRequest(`/api/rooms/${roomId}/access/heartbeat`, {
    method: 'POST',
    headers: jsonHeaders(accessToken),
  })
}

export async function deleteRoom(roomId: string, accessToken: string): Promise<void> {
  const response = await fetch(`/api/rooms/${roomId}`, {
    method: 'DELETE',
    headers: jsonHeaders(accessToken),
  })
  if (!response.ok) throw await roomError(response)
}
