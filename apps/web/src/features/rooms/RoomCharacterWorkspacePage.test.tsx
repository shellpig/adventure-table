import { describe, expect, it } from 'vitest'

import { canPermanentlyDeleteRoomCharacters } from './RoomCharacterWorkspacePage'

describe('Room Character workspace delete authority', () => {
  it('allows permanent delete only for the owner', () => {
    expect(canPermanentlyDeleteRoomCharacters('owner')).toBe(true)
  })

  it.each(['member', 'dm', null, undefined] as const)(
    'denies permanent delete for %s',
    (authority) => {
      expect(canPermanentlyDeleteRoomCharacters(authority)).toBe(false)
    },
  )
})
