export const SUPPORTED_LOCALES = ['zh-TW', 'en'] as const

export type Locale = (typeof SUPPORTED_LOCALES)[number]

export const DEFAULT_LOCALE: Locale = 'zh-TW'
export const LOCALE_STORAGE_KEY = 'adventure-table.locale'

export type LocaleStorage = {
  getItem: (key: string) => string | null
  setItem: (key: string, value: string) => void
}

export type LocaleDocument = {
  documentElement: {
    lang: string
  }
}

export function isSupportedLocale(value: unknown): value is Locale {
  return typeof value === 'string' && SUPPORTED_LOCALES.includes(value as Locale)
}

export function readLocalePreference(storage?: LocaleStorage | null): Locale {
  if (!storage) return DEFAULT_LOCALE

  try {
    const storedLocale = storage.getItem(LOCALE_STORAGE_KEY)
    return isSupportedLocale(storedLocale) ? storedLocale : DEFAULT_LOCALE
  } catch {
    return DEFAULT_LOCALE
  }
}

export function persistLocalePreference(locale: Locale, storage?: LocaleStorage | null): void {
  if (!storage) return

  try {
    storage.setItem(LOCALE_STORAGE_KEY, locale)
  } catch {
    // Browser privacy modes can make localStorage unavailable. Runtime locale
    // still works for the current page even when persistence cannot be written.
  }
}

export function applyDocumentLocale(locale: Locale, target?: LocaleDocument | null): void {
  if (!target) return
  target.documentElement.lang = locale
}

export function getBrowserLocaleStorage(): LocaleStorage | undefined {
  if (typeof window === 'undefined') return undefined

  try {
    return window.localStorage
  } catch {
    return undefined
  }
}

export function getBrowserLocaleDocument(): LocaleDocument | undefined {
  return typeof document === 'undefined' ? undefined : document
}
