import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import App, {
  P0_FIXTURE_ID,
  builderDraftIdFromPath,
  characterIdFromPath,
  characterVersionsFromPath,
} from './App'

const DRAFT_ID = '11111111-1111-4111-8111-111111111111'

describe('Adventure Table routes', () => {
  it('renders the P1-G landing page and workshop entry', () => {
    const html = renderToStaticMarkup(<App />)

    expect(html).toContain('Adventure Table')
    expect(html).toContain('P1-G')
    expect(html).toContain('/characters')
    expect(html).toContain(`/characters/${P0_FIXTURE_ID}`)
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
