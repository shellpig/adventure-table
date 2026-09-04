import type { CapabilityKey } from './types'

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
  for (const [prefix, capability] of PROTECTED_PREFIXES) {
    if (pathname === prefix || pathname.startsWith(`${prefix}/`)) return capability
  }
  return null
}
