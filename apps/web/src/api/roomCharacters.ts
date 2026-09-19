import type { CharacterListItem } from './characterBuilder'

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
  const response = await fetch(`/api/rooms/${roomId}${path}`, {
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
  return roomRequest(roomId, accessToken, '/characters/legacy')
}

export function claimLegacyCharacterData(
  roomId: string,
  accessToken: string,
): Promise<LegacyCharacterDataClaimResult> {
  return roomRequest(roomId, accessToken, '/characters/legacy/claim', { method: 'POST' })
}

export function listRoomCharacters(
  roomId: string,
  accessToken: string,
  options?: { archived?: boolean },
): Promise<CharacterListItem[]> {
  const query = options?.archived ? '?archived=true' : ''
  return roomRequest(roomId, accessToken, `/characters${query}`)
}

export async function listRoomDraftCount(
  roomId: string,
  accessToken: string,
): Promise<number> {
  const drafts = await roomRequest<unknown[]>(roomId, accessToken, '/character-builder/drafts')
  return drafts.length
}
