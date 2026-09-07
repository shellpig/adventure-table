export type LegacyCharacterDataStatus = {
  character_count: number
  draft_count: number
  available: boolean
}

export type LegacyCharacterDataClaimResult = {
  claimed_character_count: number
  claimed_draft_count: number
}

async function roomRequest<T>(
  roomId: string,
  accessToken: string,
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(`/api/rooms/${roomId}/characters${path}`, {
    ...init,
    headers: {
      ...init?.headers,
      Authorization: `Bearer ${accessToken}`,
    },
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    const message = payload?.error?.message ?? `Room Character request failed (${response.status})`
    throw new Error(message)
  }
  return response.json() as Promise<T>
}

export function getLegacyCharacterDataStatus(
  roomId: string,
  accessToken: string,
): Promise<LegacyCharacterDataStatus> {
  return roomRequest(roomId, accessToken, '/legacy')
}

export function claimLegacyCharacterData(
  roomId: string,
  accessToken: string,
): Promise<LegacyCharacterDataClaimResult> {
  return roomRequest(roomId, accessToken, '/legacy/claim', { method: 'POST' })
}
