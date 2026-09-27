export function requestId(prefix: string): string {
  const random = globalThis.crypto?.randomUUID?.()
  return random ? `${prefix}-${random}` : `${prefix}-${Date.now()}-${Math.random()}`
}
