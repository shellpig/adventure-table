import {
  CAPABILITY_KEYS,
  type CapabilityFlags,
  type CapabilitySnapshot,
  type DistributionChannel,
} from './types'

function isChannel(value: unknown): value is DistributionChannel {
  return value === 'web' || value === 'standalone'
}

function parseFlags(value: unknown): CapabilityFlags {
  if (!value || typeof value !== 'object') {
    throw new Error('capabilities payload is missing capability flags')
  }
  const record = value as Record<string, unknown>
  const flags = {} as CapabilityFlags
  for (const key of CAPABILITY_KEYS) {
    if (typeof record[key] !== 'boolean') {
      throw new Error(`capabilities payload has invalid ${key}`)
    }
    flags[key] = record[key]
  }
  return flags
}

export function parseCapabilitySnapshot(value: unknown): CapabilitySnapshot {
  if (!value || typeof value !== 'object') {
    throw new Error('capabilities payload is not an object')
  }
  const record = value as Record<string, unknown>
  if (!isChannel(record.channel)) {
    throw new Error('capabilities payload has invalid channel')
  }
  if (record.database_path !== null && record.database_path !== undefined && typeof record.database_path !== 'string') {
    throw new Error('capabilities payload has invalid database_path')
  }
  return {
    channel: record.channel,
    capabilities: parseFlags(record.capabilities),
    database_path: typeof record.database_path === 'string' ? record.database_path : null,
  }
}

export async function fetchCapabilities(): Promise<CapabilitySnapshot> {
  const response = await fetch('/api/meta/capabilities', {
    headers: { Accept: 'application/json' },
  })
  if (!response.ok) {
    throw new Error(`capabilities request failed: ${response.status}`)
  }
  return parseCapabilitySnapshot(await response.json())
}
