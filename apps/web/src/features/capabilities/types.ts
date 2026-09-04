export const CAPABILITY_KEYS = [
  'character_builder',
  'character_import_export',
  'room',
  'campaign',
  'session',
  'seat',
  'combat',
  'timeline',
  'ai_actor',
] as const

export type CapabilityKey = (typeof CAPABILITY_KEYS)[number]
export type DistributionChannel = 'web' | 'standalone'
export type CapabilityFlags = Record<CapabilityKey, boolean>

export type CapabilitySnapshot = {
  channel: DistributionChannel
  capabilities: CapabilityFlags
  database_path: string | null
}

export const DEFAULT_WEB_CAPABILITIES: CapabilitySnapshot = {
  channel: 'web',
  capabilities: {
    character_builder: true,
    character_import_export: true,
    room: false,
    campaign: false,
    session: false,
    seat: false,
    combat: false,
    timeline: false,
    ai_actor: false,
  },
  database_path: null,
}
