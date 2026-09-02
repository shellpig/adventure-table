import type { Locale } from './locale'

const PASSIVE_INVESTIGATION: Record<Locale, string> = {
  en: 'Passive Investigation',
  'zh-TW': '被動調查',
}

/** M01-K exposes passive Investigation as a first-class derived sheet value. */
export function passiveInvestigationLabel(locale: Locale): string {
  return PASSIVE_INVESTIGATION[locale]
}
