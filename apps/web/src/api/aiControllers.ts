export type AIControllerGrantView = {
  grant_id: string
  seat_id: string
  role: 'dm' | 'player'
  session_id: string | null
  generation: number
  token: string
  token_hint: string
  expires_at: string | null
}

type ApiErrorPayload = { error?: { code?: string; message?: string } }

export class AIControllerApiError extends Error {
  constructor(readonly status: number, readonly code: string, message: string) {
    super(message)
  }
}

async function apiError(response: Response): Promise<AIControllerApiError> {
  let payload: ApiErrorPayload = {}
  try { payload = (await response.json()) as ApiErrorPayload } catch { /* fallback below */ }
  return new AIControllerApiError(
    response.status,
    payload.error?.code ?? 'ai_controller_request_failed',
    payload.error?.message ?? `AI controller request failed (${response.status})`,
  )
}

async function request<T>(url: string, roomToken: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${roomToken}`,
      ...(init?.headers ?? {}),
    },
  })
  if (!response.ok) throw await apiError(response)
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

const base = (roomId: string, campaignId: string) =>
  `/api/rooms/${roomId}/campaigns/${campaignId}`

export function letAiControlPlayer(
  roomId: string,
  campaignId: string,
  sessionId: string,
  seatId: string,
  roomToken: string,
  temporaryInstruction: string | null,
): Promise<AIControllerGrantView> {
  return request(
    `${base(roomId, campaignId)}/sessions/${sessionId}/seats/${seatId}/ai-control`,
    roomToken,
    {
      method: 'POST',
      body: JSON.stringify({ temporary_instruction: temporaryInstruction }),
    },
  )
}

export function takeBackPlayer(
  roomId: string,
  campaignId: string,
  sessionId: string,
  seatId: string,
  roomToken: string,
): Promise<void> {
  return request(
    `${base(roomId, campaignId)}/sessions/${sessionId}/seats/${seatId}/take-back`,
    roomToken,
    { method: 'POST' },
  )
}

export function administrativelyReassignPlayer(
  roomId: string,
  campaignId: string,
  sessionId: string,
  seatId: string,
  roomToken: string,
  targetAccessSessionId: string,
): Promise<void> {
  return request(
    `${base(roomId, campaignId)}/sessions/${sessionId}/seats/${seatId}/reassign-human`,
    roomToken,
    {
      method: 'POST',
      body: JSON.stringify({ target_access_session_id: targetAccessSessionId }),
    },
  )
}

export function configurePreSessionAiDm(
  roomId: string,
  campaignId: string,
  seatId: string,
  roomToken: string,
): Promise<AIControllerGrantView> {
  return request(
    `${base(roomId, campaignId)}/seats/${seatId}/ai-dm-grant`,
    roomToken,
    { method: 'POST' },
  )
}

export function revokePreSessionAiDm(
  roomId: string,
  campaignId: string,
  seatId: string,
  roomToken: string,
): Promise<void> {
  return request(
    `${base(roomId, campaignId)}/seats/${seatId}/ai-dm-grant`,
    roomToken,
    { method: 'DELETE' },
  )
}

export type McpPublicOriginView = { public_origin: string | null }

// Deployment setting (ADVENTURE_TABLE_MCP_PUBLIC_ORIGIN) the AI Join Kit prints
// as the remote URL. Unauthenticated: it only reveals the public entry point.
export async function fetchMcpPublicOrigin(): Promise<string | null> {
  const response = await fetch('/api/mcp/public-origin')
  if (!response.ok) throw await apiError(response)
  const payload = (await response.json()) as McpPublicOriginView
  return payload.public_origin
}
