import { describe, expect, it } from 'vitest'

import { parseCapabilitySnapshot } from './api'

const flags = {
  character_builder: true,
  character_import_export: true,
  room: false,
  campaign: false,
  session: false,
  seat: false,
  table_runtime: false,
  combat: false,
  timeline: false,
  ai_actor: false,
}

describe('capability API contract', () => {
  it('parses the web/standalone server payload without inventing build-time flags', () => {
    expect(parseCapabilitySnapshot({
      channel: 'standalone',
      capabilities: flags,
      database_path: 'C:/table/adventure-table.sqlite3',
    })).toEqual({
      channel: 'standalone',
      capabilities: flags,
      database_path: 'C:/table/adventure-table.sqlite3',
    })
  })

  it('requires the P3 table_runtime flag so backend/frontend capability contracts cannot drift', () => {
    const { table_runtime: _missing, ...incomplete } = flags
    expect(() => parseCapabilitySnapshot({
      channel: 'web',
      capabilities: incomplete,
      database_path: null,
    })).toThrow(/table_runtime/)
  })

  it('rejects an incomplete capability table so existing server keys cannot silently disappear', () => {
    expect(() => parseCapabilitySnapshot({
      channel: 'web',
      capabilities: { character_builder: true },
      database_path: null,
    })).toThrow(/character_import_export/)
  })
})
