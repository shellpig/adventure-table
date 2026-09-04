import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

import App, {
  P0_FIXTURE_ID,
  builderDraftIdFromPath,
  characterIdFromPath,
  characterVersionsFromPath,
} from './App'
import { CapabilityProvider } from './features/capabilities/CapabilityProvider'
import type { CapabilitySnapshot } from './features/capabilities/types'
import { LocaleProvider } from './i18n/LocaleProvider'
import { LOCALE_STORAGE_KEY, type LocaleStorage } from './i18n/locale'

const DRAFT_ID = '11111111-1111-4111-8111-111111111111'
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
  database_path: 'C:/Adventure Table/adventure-table.sqlite3',
}

function englishStorage(): LocaleStorage {
  return {
    getItem: (key) => (key === LOCALE_STORAGE_KEY ? 'en' : null),
    setItem: () => undefined,
  }
}

function renderApp(snapshot?: CapabilitySnapshot) {
  const app = snapshot ? (
    <CapabilityProvider initialSnapshot={snapshot}><App /></CapabilityProvider>
  ) : <App />
  return renderToStaticMarkup(
    <LocaleProvider storage={englishStorage()} documentTarget={null}>
      {app}
    </LocaleProvider>,
  )
}

describe('Adventure Table routes', () => {
  it('renders the localized web landing page and workshop entry', () => {
    const html = renderApp()

    expect(html).toContain('Adventure Table')
    expect(html).toContain('M02-B')
    expect(html).toContain('Open Character Workshop')
    expect(html).toContain('/characters')
    expect(html).toContain(`/characters/${P0_FIXTURE_ID}`)
  })

  it('shows the concrete SQLite path without exposing the web-only P0 fixture on standalone', () => {
    const html = renderApp(STANDALONE)

    expect(html).toContain('Local character database')
    expect(html).toContain('C:/Adventure Table/adventure-table.sqlite3')
    expect(html).not.toContain(`/characters/${P0_FIXTURE_ID}`)
  })

  it('renders capability_disabled presentation for a manually entered disabled route', () => {
    vi.stubGlobal('window', { location: { pathname: '/rooms/demo' } })
    try {
      const html = renderApp(STANDALONE)
      expect(html).toContain('This feature is not available here')
      expect(html).toContain('Open Character Workshop')
      expect(html).not.toContain('href="/rooms')
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it('parses character sheet, version history and builder draft routes independently', () => {
    expect(characterIdFromPath(`/characters/${P0_FIXTURE_ID}`)).toBe(P0_FIXTURE_ID)
    expect(characterIdFromPath('/characters/not-a-uuid')).toBeNull()
    expect(characterIdFromPath(`/character-builder/${DRAFT_ID}`)).toBeNull()
    expect(characterIdFromPath(`/characters/${P0_FIXTURE_ID}/versions`)).toBeNull()

    expect(builderDraftIdFromPath(`/character-builder/${DRAFT_ID}`)).toBe(DRAFT_ID)
    expect(builderDraftIdFromPath(`/characters/${P0_FIXTURE_ID}`)).toBeNull()
    expect(builderDraftIdFromPath('/character-builder/not-a-uuid')).toBeNull()

    expect(characterVersionsFromPath(`/characters/${P0_FIXTURE_ID}/versions`)).toEqual({
      characterId: P0_FIXTURE_ID,
      versionNo: null,
    })
    expect(characterVersionsFromPath(`/characters/${P0_FIXTURE_ID}/versions/2`)).toEqual({
      characterId: P0_FIXTURE_ID,
      versionNo: 2,
    })
    expect(characterVersionsFromPath(`/characters/${P0_FIXTURE_ID}/versions/not-a-number`)).toBeNull()
  })
})
