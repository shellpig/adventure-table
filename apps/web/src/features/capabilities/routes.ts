import type { CapabilityKey } from './types'

const ROOM_CAMPAIGN_ROUTE = /^\/rooms\/[0-9a-fA-F-]{36}\/campaigns(?:\/|$)/

const PROTECTED_PREFIXES: ReadonlyArray<readonly [string, CapabilityKey]> = [
  ['/rooms', 'room'],
  ['/campaigns', 'campaign'],
  ['/sessions', 'session'],
  ['/seats', 'seat'],
  ['/combat', 'combat'],
  ['/timeline', 'timeline'],
  ['/ai-actors', 'ai_actor'],
]

export function protectedCapabilityForPath(pathname: string): CapabilityKey | null {
  if (ROOM_CAMPAIGN_ROUTE.test(pathname)) return 'campaign'

  for (const [prefix, capability] of PROTECTED_PREFIXES) {
    if (pathname === prefix || pathname.startsWith(`${prefix}/`)) return capability
  }
  return null
}
