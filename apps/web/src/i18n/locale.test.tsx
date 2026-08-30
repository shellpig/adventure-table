import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { LocaleProvider } from './LocaleProvider'
import { LocaleSwitcher } from './LocaleSwitcher'
import {
  applyDocumentLocale,
  DEFAULT_LOCALE,
  LOCALE_STORAGE_KEY,
  persistLocalePreference,
  readLocalePreference,
  type LocaleStorage,
} from './locale'

function memoryStorage(initial: Record<string, string> = {}): LocaleStorage & { values: Record<string, string> } {
  const values = { ...initial }
  return {
    values,
    getItem: (key) => values[key] ?? null,
    setItem: (key, value) => {
      values[key] = value
    },
  }
}

describe('M02-A locale foundation', () => {
  it('defaults to zh-TW when no preference exists', () => {
    expect(readLocalePreference(memoryStorage())).toBe(DEFAULT_LOCALE)
  })

  it('initializes from a supported browser preference', () => {
    expect(readLocalePreference(memoryStorage({ [LOCALE_STORAGE_KEY]: 'en' }))).toBe('en')
  })

  it('rejects an invalid stored locale and returns the safe default', () => {
    expect(readLocalePreference(memoryStorage({ [LOCALE_STORAGE_KEY]: 'ja' }))).toBe('zh-TW')
  })

  it('persists only the runtime locale preference outside domain state', () => {
    const storage = memoryStorage()
    persistLocalePreference('en', storage)
    expect(storage.values).toEqual({ [LOCALE_STORAGE_KEY]: 'en' })
  })

  it('updates document language metadata', () => {
    const target = { documentElement: { lang: 'zh-TW' } }
    applyDocumentLocale('en', target)
    expect(target.documentElement.lang).toBe('en')
  })

  it('renders the global switcher from the provider locale', () => {
    const storage = memoryStorage({ [LOCALE_STORAGE_KEY]: 'en' })
    const html = renderToStaticMarkup(
      <LocaleProvider storage={storage} documentTarget={null}>
        <LocaleSwitcher />
      </LocaleProvider>,
    )

    expect(html).toContain('data-testid="locale-switcher"')
    expect(html).toContain('data-testid="locale-option-en"')
    expect(html).toContain('aria-pressed="true"')
    expect(html).toContain('Language')
  })
})
