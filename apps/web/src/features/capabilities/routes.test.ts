import { describe, expect, it } from 'vitest'

import { protectedCapabilityForPath } from './routes'


describe('M03-E capability route boundary', () => {
  it('maps multiplayer URLs to their server-advertised capability', () => {
    expect(protectedCapabilityForPath('/rooms')).toBe('room')
    expect(protectedCapabilityForPath('/rooms/abc')).toBe('room')
    expect(protectedCapabilityForPath('/campaigns/abc')).toBe('campaign')
    expect(protectedCapabilityForPath('/sessions/abc')).toBe('session')
    expect(protectedCapabilityForPath('/combat/abc')).toBe('combat')
    expect(protectedCapabilityForPath('/timeline')).toBe('timeline')
    expect(protectedCapabilityForPath('/ai-actors/abc')).toBe('ai_actor')
  })

  it('leaves character routes outside the multiplayer gate', () => {
    expect(protectedCapabilityForPath('/characters')).toBeNull()
    expect(protectedCapabilityForPath('/character-builder/abc')).toBeNull()
  })
})
