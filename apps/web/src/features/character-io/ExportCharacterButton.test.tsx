import { readFileSync } from 'node:fs'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { LocaleProvider } from '../../i18n/LocaleProvider'
import { LOCALE_STORAGE_KEY, type LocaleStorage } from '../../i18n/locale'
import type { Locale } from '../../i18n/locale'
import { CHARACTER_IO_COPY } from '../../i18n/useCharacterIoCopy'
import { ExportCharacterButton } from './ExportCharacterButton'

function storage(locale: Locale): LocaleStorage {
  return {
    getItem: (key) => (key === LOCALE_STORAGE_KEY ? locale : null),
    setItem: () => undefined,
  }
}

function render(locale: Locale, placement: 'inline' | 'sheet') {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <LocaleProvider storage={storage(locale)} documentTarget={null}>
        <ExportCharacterButton characterId="00000000-0000-4000-8000-0000000000e0" placement={placement} />
      </LocaleProvider>
    </QueryClientProvider>,
  )
}

describe('M03-B export button', () => {
  it.each(['en', 'zh-TW'] as const)('renders %s label, aria-label and tooltip', (locale) => {
    const markup = render(locale, 'inline')
    const copy = CHARACTER_IO_COPY[locale]
    expect(markup).toContain(copy.exportLabel)
    expect(markup).toContain(`aria-label="${copy.exportAria}"`)
    expect(markup).toContain(`title="${copy.exportTooltip}"`)
  })

  it.each(['inline', 'sheet'] as const)(
    'renders in its own tree for %s placement, with no fixed overlay',
    (placement) => {
      // A DOM-querying portal silently rendered nothing when the sheet had not
      // mounted yet; the button must never depend on a mount point it does not own.
      const markup = render('en', placement)
      expect(markup).toContain('<button')
      expect(markup).toContain('character-export-action')
    },
  )

  it('wraps sheet placement so the sheet header can lay it out', () => {
    expect(render('en', 'sheet')).toContain('character-export-sheet-action')
    expect(render('en', 'inline')).not.toContain('character-export-sheet-action')
  })
})

describe('M03-B export mounting', () => {
  it('is wired into the sheet header by the sheet page itself', () => {
    // Guards the regression where the button was mounted from App.tsx and
    // portalled into a `.character-hero` that had not rendered yet.
    const source = readFileSync(
      new URL('../character-sheet/CharacterSheetPage.tsx', import.meta.url),
      'utf8',
    )
    expect(source).toContain('headerActions={<ExportCharacterButton')

    const app = readFileSync(new URL('../../App.tsx', import.meta.url), 'utf8')
    expect(app).not.toContain('ExportCharacterButton')
  })

  it('never reaches outside its own tree for a mount point', () => {
    const source = readFileSync(
      new URL('./ExportCharacterButton.tsx', import.meta.url),
      'utf8',
    )
    expect(source).not.toContain('createPortal')
    expect(source).not.toContain('querySelector')
  })
})
