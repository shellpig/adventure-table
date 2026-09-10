import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { CapabilityLink } from './CapabilityLink'
import { CapabilityProvider, useCapabilities } from './CapabilityProvider'
import {
  CAPABILITY_FETCH_FALLBACK,
  DEFAULT_WEB_CAPABILITIES,
  type CapabilitySnapshot,
} from './types'

const STANDALONE: CapabilitySnapshot = {
  channel: 'standalone',
  capabilities: {
    character_builder: true,
    character_import_export: true,
    room: false,
    campaign: false,
    session: false,
    seat: false,
    table_runtime: false,
    roll_check: false,
    combat: false,
    timeline: false,
    ai_actor: false,
  },
  database_path: 'C:\\Adventure Table\\adventure-table.sqlite3',
}

function Probe() {
  const { snapshot } = useCapabilities()
  return <output>{`${snapshot.channel}|${snapshot.database_path}`}</output>
}

describe('capability provider', () => {
  it('uses an injected bootstrap snapshot without changing its channel or database path', () => {
    const html = renderToStaticMarkup(
      <CapabilityProvider initialSnapshot={STANDALONE}>
        <Probe />
      </CapabilityProvider>,
    )

    expect(html).toContain('standalone|C:\\Adventure Table\\adventure-table.sqlite3')
  })

  it('does not render a navigation link when its capability is false', () => {
    const html = renderToStaticMarkup(
      <CapabilityProvider initialSnapshot={STANDALONE}>
        <CapabilityLink capability="room" href="/rooms">Rooms</CapabilityLink>
        <CapabilityLink capability="character_builder" href="/characters">Characters</CapabilityLink>
      </CapabilityProvider>,
    )

    expect(html).not.toContain('href="/rooms"')
    expect(html).toContain('href="/characters"')
  })

  it('keeps conservative bootstrap/fetch fallbacks fail-closed for P3 table runtime', () => {
    expect(DEFAULT_WEB_CAPABILITIES.capabilities.room).toBe(true)
    expect(DEFAULT_WEB_CAPABILITIES.capabilities.campaign).toBe(true)
    expect(DEFAULT_WEB_CAPABILITIES.capabilities.seat).toBe(false)
    expect(DEFAULT_WEB_CAPABILITIES.capabilities.session).toBe(false)
    expect(DEFAULT_WEB_CAPABILITIES.capabilities.table_runtime).toBe(false)
    expect(DEFAULT_WEB_CAPABILITIES.capabilities.roll_check).toBe(false)
    expect(CAPABILITY_FETCH_FALLBACK.capabilities.character_builder).toBe(true)
    expect(CAPABILITY_FETCH_FALLBACK.capabilities.character_import_export).toBe(true)
    for (const capability of [
      'room',
      'campaign',
      'session',
      'seat',
      'table_runtime',
      'roll_check',
      'combat',
      'timeline',
      'ai_actor',
    ] as const) {
      expect(CAPABILITY_FETCH_FALLBACK.capabilities[capability]).toBe(false)
    }
  })
})
