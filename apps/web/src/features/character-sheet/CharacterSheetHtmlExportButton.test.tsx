import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { LocaleProvider } from '../../i18n/LocaleProvider'
import { LOCALE_STORAGE_KEY, type Locale, type LocaleStorage } from '../../i18n/locale'
import { CharacterSheetHtmlExportButton } from './CharacterSheetHtmlExportButton'

function storage(locale: Locale): LocaleStorage {
  return {
    getItem: (key) => (key === LOCALE_STORAGE_KEY ? locale : null),
    setItem: () => undefined,
  }
}

function renderExportButton(locale: Locale): string {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <LocaleProvider storage={storage(locale)} documentTarget={null}>
        <CharacterSheetHtmlExportButton characterId="00000000-0000-4000-8000-0000000000e0" />
      </LocaleProvider>
    </QueryClientProvider>,
  )
}

describe('M01-N Character Sheet HTML export action', () => {
  it('offers build-only and current-snapshot scopes in English', () => {
    const markup = renderExportButton('en')
    expect(markup).toContain('Export scope')
    expect(markup).toContain('<option value="build"')
    expect(markup).toContain('Build only</option>')
    expect(markup).toContain('<option value="snapshot"')
    expect(markup).toContain('Current snapshot</option>')
    expect(markup).toContain('Export HTML')
    expect(markup).toContain('data-testid="character-html-export-button"')
  })

  it('renders the same independent export action in Traditional Chinese', () => {
    const markup = renderExportButton('zh-TW')
    expect(markup).toContain('輸出範圍')
    expect(markup).toContain('角色配置')
    expect(markup).toContain('當前快照')
    expect(markup).toContain('匯出 HTML')
  })
})
