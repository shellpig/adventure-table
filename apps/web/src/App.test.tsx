import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import App, { P0_FIXTURE_ID, builderDraftIdFromPath, characterIdFromPath } from './App'

const DRAFT_ID = '11111111-1111-4111-8111-111111111111'

describe('Adventure Table routes', () => {
  it('renders the P1-B landing page and workshop entry', () => {
    const html = renderToStaticMarkup(<App />)

    expect(html).toContain('Adventure Table')
    expect(html).toContain('P1-B')
    expect(html).toContain('/characters')
    expect(html).toContain(`/characters/${P0_FIXTURE_ID}`)
  })

  it('parses character sheet and builder draft routes independently', () => {
    expect(characterIdFromPath(`/characters/${P0_FIXTURE_ID}`)).toBe(P0_FIXTURE_ID)
    expect(characterIdFromPath('/characters/not-a-uuid')).toBeNull()
    expect(characterIdFromPath(`/character-builder/${DRAFT_ID}`)).toBeNull()

    expect(builderDraftIdFromPath(`/character-builder/${DRAFT_ID}`)).toBe(DRAFT_ID)
    expect(builderDraftIdFromPath(`/characters/${P0_FIXTURE_ID}`)).toBeNull()
    expect(builderDraftIdFromPath('/character-builder/not-a-uuid')).toBeNull()
  })
})
