import { useLocale } from './LocaleProvider'
import { useUiCopy } from './useUiCopy'

export function LocaleSwitcher() {
  const { locale, setLocale } = useLocale()
  const { t } = useUiCopy()

  return (
    <div
      className="locale-switcher"
      role="group"
      aria-label={t('locale.group')}
      data-testid="locale-switcher"
    >
      <button
        type="button"
        className={locale === 'zh-TW' ? 'is-active' : ''}
        aria-pressed={locale === 'zh-TW'}
        aria-label={t('locale.zh')}
        title={t('locale.zh')}
        data-testid="locale-option-zh-TW"
        onClick={() => setLocale('zh-TW')}
      >
        繁中
      </button>
      <button
        type="button"
        className={locale === 'en' ? 'is-active' : ''}
        aria-pressed={locale === 'en'}
        aria-label={t('locale.en')}
        title={t('locale.en')}
        data-testid="locale-option-en"
        onClick={() => setLocale('en')}
      >
        EN
      </button>
    </div>
  )
}
