import { describe, expect, it } from 'vitest'

import { protectedCapabilityForPath } from './routes'


describe('multiplayer capability route boundary', () => {
  it('maps multiplayer URLs to their server-advertised capability', () => {
    expect(protectedCapabilityForPath('/rooms')).toBe('room')
    expect(protectedCapabilityForPath('/rooms/abc')).toBe('room')
    expect(protectedCapabilityForPath('/campaigns/abc')).toBe('campaign')
    expect(protectedCapabilityForPath('/sessions/abc')).toBe('session')
    expect(protectedCapabilityForPath('/seats/abc')).toBe('seat')
    expect(protectedCapabilityForPath('/combat/abc')).toBe('combat')
    expect(protectedCapabilityForPath('/timeline')).toBe('timeline')
    expect(protectedCapabilityForPath('/ai-actors/abc')).toBe('ai_actor')
  })

  it('uses the Seat gate specifically for a Room-scoped Lobby route', () => {
    const roomId = '10000000-0000-4000-8000-000000000001'
    const campaignId = '20000000-0000-4000-8000-000000000001'

    expect(protectedCapabilityForPath(`/rooms/${roomId}/campaigns`)).toBe('campaign')
    expect(protectedCapabilityForPath(`/rooms/${roomId}/campaigns/${campaignId}`)).toBe('campaign')
    expect(protectedCapabilityForPath(`/rooms/${roomId}/campaigns/${campaignId}/lobby`)).toBe('seat')
    expect(protectedCapabilityForPath(`/rooms/${roomId}/characters`)).toBe('room')
  })

  it('leaves character routes outside the multiplayer gate', () => {
    expect(protectedCapabilityForPath('/characters')).toBeNull()
    expect(protectedCapabilityForPath('/character-builder/abc')).toBeNull()
  })
})
