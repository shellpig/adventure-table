import { useCallback } from 'react'

import { useLocale } from './LocaleProvider'
import { translateUi, type UiCopyKey, type UiCopyParams } from './uiCopy'

export type UiTranslator = (key: UiCopyKey, params?: UiCopyParams) => string

export function useUiCopy() {
  const { locale } = useLocale()
  const t = useCallback<UiTranslator>(
    (key, params) => translateUi(locale, key, params),
    [locale],
  )

  return { locale, t }
}
