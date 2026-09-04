import { useLocale } from '../../i18n/LocaleProvider'
import { capabilityCopy } from './copy'

export function CapabilityDisabledPage() {
  const { locale } = useLocale()
  const copy = capabilityCopy(locale)

  return (
    <main className="landing-page">
      <section className="landing-card">
        <p className="eyebrow">{copy.disabledEyebrow}</p>
        <div className="landing-mark" aria-hidden="true">AT</div>
        <h1>{copy.disabledTitle}</h1>
        <p>{copy.disabledDescription}</p>
        <a className="button primary landing-action" href="/characters">
          {copy.backWorkshop}
        </a>
      </section>
    </main>
  )
}
