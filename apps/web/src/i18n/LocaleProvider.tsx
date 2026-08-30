import {
  createContext,
  type PropsWithChildren,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react'

import {
  applyDocumentLocale,
  getBrowserLocaleDocument,
  getBrowserLocaleStorage,
  type Locale,
  type LocaleDocument,
  type LocaleStorage,
  persistLocalePreference,
  readLocalePreference,
} from './locale'

type LocaleContextValue = {
  locale: Locale
  setLocale: (locale: Locale) => void
}

type LocaleProviderProps = PropsWithChildren<{
  storage?: LocaleStorage | null
  documentTarget?: LocaleDocument | null
}>

const LocaleContext = createContext<LocaleContextValue | null>(null)

export function LocaleProvider({ children, storage, documentTarget }: LocaleProviderProps) {
  const [runtimeStorage] = useState<LocaleStorage | null | undefined>(() =>
    storage === undefined ? getBrowserLocaleStorage() : storage,
  )
  const [runtimeDocument] = useState<LocaleDocument | null | undefined>(() =>
    documentTarget === undefined ? getBrowserLocaleDocument() : documentTarget,
  )
  const [locale, setLocaleState] = useState<Locale>(() => readLocalePreference(runtimeStorage))

  useEffect(() => {
    applyDocumentLocale(locale, runtimeDocument)
    persistLocalePreference(locale, runtimeStorage)
  }, [locale, runtimeDocument, runtimeStorage])

  const setLocale = useCallback((nextLocale: Locale) => {
    setLocaleState(nextLocale)
  }, [])

  const value = useMemo(() => ({ locale, setLocale }), [locale, setLocale])

  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>
}

export function useLocale(): LocaleContextValue {
  const context = useContext(LocaleContext)
  if (!context) throw new Error('useLocale must be used within LocaleProvider')
  return context
}
