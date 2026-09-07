import { describe, expect, it } from 'vitest'

import { roomCharacterRouteFromPath } from '../../App'
import {
  roomContextIdFromPath,
  roomScopedApiPath,
  roomScopedFrontendPath,
} from './roomCharacterRouting'

const ROOM_ID = '22222222-2222-4222-8222-222222222222'
const CHARACTER_ID = '33333333-3333-4333-8333-333333333333'
const DRAFT_ID = '44444444-4444-4444-8444-444444444444'

describe('P2-B Room Character routing', () => {
  it('parses the Room context from every nested Character surface', () => {
    expect(roomContextIdFromPath(`/rooms/${ROOM_ID}`)).toBe(ROOM_ID)
    expect(roomContextIdFromPath(`/rooms/${ROOM_ID}/characters`)).toBe(ROOM_ID)
    expect(roomContextIdFromPath(`/characters/${CHARACTER_ID}`)).toBeNull()
  })

  it('rewrites only neutral Character and Builder API paths into the current Room', () => {
    expect(roomScopedApiPath('/api/characters', ROOM_ID)).toBe(
      `/api/rooms/${ROOM_ID}/characters`,
    )
    expect(roomScopedApiPath(`/api/characters/${CHARACTER_ID}/sheet`, ROOM_ID)).toBe(
      `/api/rooms/${ROOM_ID}/characters/${CHARACTER_ID}/sheet`,
    )
    expect(roomScopedApiPath(`/api/character-builder/drafts/${DRAFT_ID}`, ROOM_ID)).toBe(
      `/api/rooms/${ROOM_ID}/character-builder/drafts/${DRAFT_ID}`,
    )
    expect(roomScopedApiPath('/api/rules/content/spells', ROOM_ID)).toBeNull()
  })

  it('keeps frontend Character navigation inside the current Room', () => {
    expect(roomScopedFrontendPath('/characters', ROOM_ID)).toBe(
      `/rooms/${ROOM_ID}/characters`,
    )
    expect(roomScopedFrontendPath(`/characters/${CHARACTER_ID}/versions/2`, ROOM_ID)).toBe(
      `/rooms/${ROOM_ID}/characters/${CHARACTER_ID}/versions/2`,
    )
    expect(roomScopedFrontendPath(`/character-builder/${DRAFT_ID}`, ROOM_ID)).toBe(
      `/rooms/${ROOM_ID}/character-builder/${DRAFT_ID}`,
    )
  })

  it('parses scoped Workshop, Sheet, Version and Builder routes', () => {
    expect(roomCharacterRouteFromPath(`/rooms/${ROOM_ID}/characters`)).toEqual({
      kind: 'workshop',
      roomId: ROOM_ID,
    })
    expect(roomCharacterRouteFromPath(`/rooms/${ROOM_ID}/characters/${CHARACTER_ID}`)).toEqual({
      kind: 'character',
      roomId: ROOM_ID,
      characterId: CHARACTER_ID,
    })
    expect(
      roomCharacterRouteFromPath(`/rooms/${ROOM_ID}/characters/${CHARACTER_ID}/versions/3`),
    ).toEqual({
      kind: 'versions',
      roomId: ROOM_ID,
      characterId: CHARACTER_ID,
      versionNo: 3,
    })
    expect(roomCharacterRouteFromPath(`/rooms/${ROOM_ID}/character-builder/${DRAFT_ID}`)).toEqual({
      kind: 'builder',
      roomId: ROOM_ID,
      draftId: DRAFT_ID,
    })
  })
})
