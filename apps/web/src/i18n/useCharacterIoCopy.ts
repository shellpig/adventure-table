import { characterIoEn } from './copy/character-io.en'
import { characterIoZhTw } from './copy/character-io.zh-TW'
import { useLocale } from './LocaleProvider'

export type CharacterIoCopy = typeof characterIoEn

export const CHARACTER_IO_COPY: Record<'en' | 'zh-TW', CharacterIoCopy> = {
  en: characterIoEn,
  'zh-TW': characterIoZhTw,
}

export function useCharacterIoCopy(): CharacterIoCopy {
  const { locale } = useLocale()
  return CHARACTER_IO_COPY[locale]
}
