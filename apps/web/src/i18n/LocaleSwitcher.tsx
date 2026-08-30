import { useLocale } from './LocaleProvider'

const COPY = {
  'zh-TW': {
    groupLabel: '語言',
    zhLabel: '繁體中文',
    enLabel: 'English',
  },
  en: {
    groupLabel: 'Language',
    zhLabel: '繁體中文',
    enLabel: 'English',
  },
} as const

export function LocaleSwitcher() {
  const { locale, setLocale } = useLocale()
  const copy = COPY[locale]

  return (
    <div className="locale-switcher" role="group" aria-label={copy.groupLabel} data-testid="locale-switcher">
      <button
        type="button"
        className={locale === 'zh-TW' ? 'is-active' : ''}
        aria-pressed={locale === 'zh-TW'}
        aria-label={copy.zhLabel}
        title={copy.zhLabel}
        data-testid="locale-option-zh-TW"
        onClick={() => setLocale('zh-TW')}
      >
        繁中
      </button>
      <button
        type="button"
        className={locale === 'en' ? 'is-active' : ''}
        aria-pressed={locale === 'en'}
        aria-label={copy.enLabel}
        title={copy.enLabel}
        data-testid="locale-option-en"
        onClick={() => setLocale('en')}
      >
        EN
      </button>
    </div>
  )
}
