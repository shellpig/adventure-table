import { characterIoEn } from './copy/character-io.en'
import { characterIoZhTw } from './copy/character-io.zh-TW'
import { useLocale } from './LocaleProvider'

/** Structural, not literal: both locales share the key set, never the strings. */
export type CharacterIoCopy = Record<keyof typeof characterIoEn, string>

export const CHARACTER_IO_COPY: Record<'en' | 'zh-TW', CharacterIoCopy> = {
  en: characterIoEn,
  'zh-TW': characterIoZhTw,
}

export function useCharacterIoCopy(): CharacterIoCopy {
  const { locale } = useLocale()
  return CHARACTER_IO_COPY[locale]
}
