import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import App from './App'

describe('App shell', () => {
  it('renders the Adventure Table P0-A shell', () => {
    const html = renderToStaticMarkup(<App />)

    expect(html).toContain('Adventure Table')
    expect(html).toContain('專案地基已啟動')
  })
})
