import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { CapabilityLink } from './CapabilityLink'
import { CapabilityProvider, useCapabilities } from './CapabilityProvider'
import type { CapabilitySnapshot } from './types'

const STANDALONE: CapabilitySnapshot = {
  channel: 'standalone',
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
  database_path: 'C:\\Adventure Table\\adventure-table.sqlite3',
}

function Probe() {
  const { snapshot } = useCapabilities()
  return <output>{`${snapshot.channel}|${snapshot.database_path}`}</output>
}

describe('M03-E capability provider', () => {
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
})
