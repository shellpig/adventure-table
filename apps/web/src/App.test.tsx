import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import App, { P0_FIXTURE_ID, characterIdFromPath } from './App'

describe('Adventure Table routes', () => {
  it('renders the P0-E landing page and fixture link', () => {
    const html = renderToStaticMarkup(<App />)

    expect(html).toContain('Adventure Table')
    expect(html).toContain('P0-E')
    expect(html).toContain(`/characters/${P0_FIXTURE_ID}`)
  })

  it('parses only the character sheet route', () => {
    expect(characterIdFromPath(`/characters/${P0_FIXTURE_ID}`)).toBe(P0_FIXTURE_ID)
    expect(characterIdFromPath('/characters/not-a-uuid')).toBeNull()
  })
})
