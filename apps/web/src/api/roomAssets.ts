export type RoomAssetKind = 'image' | 'source_document'
export type RoomAssetVisibility = 'room' | 'dm_only'

export type RoomAsset = {
  id: string
  room_id: string
  kind: RoomAssetKind
  original_filename: string
  mime_type: string
  size_bytes: number
  sha256: string
  visibility: RoomAssetVisibility
  created_at: string
}

type ApiErrorPayload = { error?: { code?: string; message?: string } }

export class RoomAssetApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message)
  }
}

async function apiError(response: Response): Promise<RoomAssetApiError> {
  let payload: ApiErrorPayload = {}
  try {
    payload = (await response.json()) as ApiErrorPayload
  } catch {
    // Preserve a stable fallback for non-JSON intermediaries.
  }
  return new RoomAssetApiError(
    response.status,
    payload.error?.code ?? 'room_asset_request_failed',
    payload.error?.message ?? `Room asset request failed (${response.status})`,
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

const base = (roomId: string) => `/api/rooms/${roomId}/assets`

export type UploadRoomAssetInput = {
  kind: RoomAssetKind
  filename: string
  visibility?: RoomAssetVisibility
  file: Blob
}

export async function uploadRoomAsset(
  roomId: string,
  token: string,
  input: UploadRoomAssetInput,
): Promise<RoomAsset> {
  const params = new URLSearchParams({
    kind: input.kind,
    filename: input.filename,
  })
  if (input.visibility) {
    params.set('visibility', input.visibility)
  }
  const url = `${base(roomId)}?${params.toString()}`
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
  return (await response.json()) as RoomAsset
}

export function listRoomAssets(
  roomId: string,
  token: string,
  kind?: RoomAssetKind,
): Promise<RoomAsset[]> {
  const url = kind ? `${base(roomId)}?kind=${encodeURIComponent(kind)}` : base(roomId)
  return request(url, token)
}

export function getRoomAsset(
  roomId: string,
  assetId: string,
  token: string,
): Promise<RoomAsset> {
  return request(`${base(roomId)}/${assetId}`, token)
}

export function deleteRoomAsset(
  roomId: string,
  assetId: string,
  token: string,
): Promise<void> {
  return request(`${base(roomId)}/${assetId}`, token, { method: 'DELETE' })
}

// Browser <img> tags send no Authorization header; serving authenticated media is a known limitation.
export function roomAssetContentUrl(roomId: string, assetId: string): string {
  return `/api/rooms/${roomId}/assets/${assetId}/content`
}
