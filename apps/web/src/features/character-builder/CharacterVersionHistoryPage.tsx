import { useQuery } from '@tanstack/react-query'

import {
  getCharacterVersion,
  listCharacterVersions,
} from '../../api/characterVersions'
import type { UiCopyKey } from '../../i18n/uiCopy'
import { useUiCopy, type UiTranslator } from '../../i18n/useUiCopy'
import './builder.css'

const KIND_KEYS: Record<string, UiCopyKey> = {
  legacy: 'versions.kind.legacy',
  create: 'versions.kind.create',
  level_up: 'versions.kind.level_up',
  build_edit: 'versions.kind.build_edit',
  correction: 'versions.kind.correction',
}

function kindLabel(kind: string, t: UiTranslator) {
  const key = KIND_KEYS[kind]
  return key ? t(key) : kind
}

export function CharacterVersionHistoryPage({
  characterId,
  versionNo,
}: {
  characterId: string
  versionNo?: number | null
}) {
  const { locale, t } = useUiCopy()
  const versions = useQuery({
    queryKey: ['character-versions', characterId],
    queryFn: () => listCharacterVersions(characterId),
  })
  const detail = useQuery({
    queryKey: ['character-version', characterId, versionNo],
    queryFn: () => getCharacterVersion(characterId, versionNo as number),
    enabled: typeof versionNo === 'number',
  })

  return (
    <main className="workshop-page">
      <div className="workshop-shell">
        <header className="workshop-hero">
          <div>
            <a href="/characters" className="builder-back">{t('versions.backWorkshop')}</a>
            <p className="eyebrow">{t('versions.eyebrow')}</p>
            <h1>{t('versions.title')}</h1>
            <p>{t('versions.description')}</p>
          </div>
          <a className="button secondary" href={`/characters/${characterId}`}>
            {t('versions.openCurrent')}
          </a>
        </header>

        {versions.isLoading ? <p className="builder-muted">{t('versions.loading')}</p> : null}
        {versions.error ? <div className="error-banner">{versions.error.message}</div> : null}

        <section className="workshop-section">
          <div className="workshop-section__heading">
            <div>
              <span>{t('versions.immutable')}</span>
              <h2>{t('versions.buildVersions')}</h2>
            </div>
            <small>{t('versions.count', { count: versions.data?.length ?? 0 })}</small>
          </div>
          <div className="version-history-list">
            {versions.data?.map((version) => (
              <article
                className={`workshop-card version-history-card ${version.is_current ? 'is-current' : ''}`}
                key={version.id}
              >
                <div className="version-history-card__top">
                  <div>
                    <span className="workshop-card__mark">{kindLabel(version.version_kind, t)}</span>
                    <h3>{t('versions.version', { version: version.version_no })}</h3>
                  </div>
                  {version.is_current ? (
                    <strong className="version-current-badge quiet-pill">{t('versions.current')}</strong>
                  ) : null}
                </div>
                <p>{version.class_summary} · {t('versions.level', { level: version.character_level })}</p>
                <div className="workshop-card__meta">
                  <span>{new Date(version.created_at).toLocaleString(locale)}</span>
                  <span>{version.parent_version_id ? t('versions.hasParent') : t('versions.root')}</span>
                  {version.superseded_by_version_id ? <span>{t('versions.superseded')}</span> : null}
                </div>
                {version.change_note ? <p className="builder-hint">{version.change_note}</p> : null}
                <a className="button secondary full" href={`/characters/${characterId}/versions/${version.version_no}`}>
                  {t('versions.viewSnapshot')}
                </a>
              </article>
            ))}
          </div>
        </section>

        {typeof versionNo === 'number' ? (
          <section className="workshop-section version-detail-section">
            <div className="workshop-section__heading">
              <div>
                <span>{t('versions.snapshot')}</span>
                <h2>{t('versions.version', { version: versionNo })}</h2>
              </div>
              <a className="button secondary" href={`/characters/${characterId}/versions`}>
                {t('versions.closeDetail')}
              </a>
            </div>
            {detail.isLoading ? <p className="builder-muted">{t('versions.loadingSnapshot')}</p> : null}
            {detail.error ? <div className="error-banner">{detail.error.message}</div> : null}
            {detail.data ? (
              <>
                <div className="builder-field-grid">
                  <div className="builder-rule-card">
                    <span>{t('versions.kind')}</span>
                    <strong>{kindLabel(detail.data.version_kind, t)}</strong>
                    <small>{detail.data.is_current ? t('versions.currentBuild') : t('versions.historicalBuild')}</small>
                  </div>
                  <div className="builder-rule-card">
                    <span>{t('versions.characterLevel')}</span>
                    <strong>{detail.data.character_level}</strong>
                    <small>{detail.data.class_summary}</small>
                  </div>
                </div>
                <pre className="version-build-json">{JSON.stringify(detail.data.build, null, 2)}</pre>
              </>
            ) : null}
          </section>
        ) : null}
      </div>
    </main>
  )
}
