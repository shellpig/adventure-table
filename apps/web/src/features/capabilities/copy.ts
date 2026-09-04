import type { Locale } from '../../i18n/locale'

const COPY = {
  en: {
    disabledEyebrow: 'Standalone capability boundary',
    disabledTitle: 'This feature is not available here',
    disabledDescription: 'This distribution does not provide that feature. Character tools remain available.',
    backWorkshop: 'Open Character Workshop →',
    dataPathLabel: 'Local character database',
    dataPathHint: 'Keep this file when moving to a newer standalone folder.',
  },
  'zh-TW': {
    disabledEyebrow: '單機版功能邊界',
    disabledTitle: '這個版本沒有提供此功能',
    disabledDescription: '目前的發行版本不提供這項功能；角色相關工具仍可正常使用。',
    backWorkshop: '開啟 Character Workshop →',
    dataPathLabel: '本機角色資料庫',
    dataPathHint: '搬到新版單機資料夾時，請保留並複製這個檔案。',
  },
} as const satisfies Record<Locale, Record<string, string>>

export type CapabilityCopy = (typeof COPY)[Locale]

export function capabilityCopy(locale: Locale): CapabilityCopy {
  return COPY[locale]
}
