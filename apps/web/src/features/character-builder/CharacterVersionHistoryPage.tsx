import { useQuery } from '@tanstack/react-query'

import {
  getCharacterVersion,
  listCharacterVersions,
} from '../../api/characterVersions'
import './builder.css'

const KIND_LABELS: Record<string, string> = {
  legacy: 'Legacy',
  create: 'Create',
  level_up: 'Level Up',
  build_edit: 'Build Edit',
  correction: 'Correction',
}

export function CharacterVersionHistoryPage({
  characterId,
  versionNo,
}: {
  characterId: string
  versionNo?: number | null
}) {
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
            <a href="/characters" className="builder-back">← Character Workshop</a>
            <p className="eyebrow">P1-G · Build History</p>
            <h1>Character Versions</h1>
            <p>這裡只記錄 immutable Build history，不是假裝成當時的 HP、Inventory 或其他 Current State 存檔。</p>
          </div>
          <a className="button secondary" href={`/characters/${characterId}`}>
            Open Current Sheet
          </a>
        </header>

        {versions.isLoading ? <p className="builder-muted">Loading version history…</p> : null}
        {versions.error ? <div className="error-banner">{versions.error.message}</div> : null}

        <section className="workshop-section">
          <div className="workshop-section__heading">
            <div>
              <span>IMMUTABLE</span>
              <h2>Build Versions</h2>
            </div>
            <small>{versions.data?.length ?? 0} versions</small>
          </div>
          <div className="version-history-list">
            {versions.data?.map((version) => (
              <article className={`version-history-card ${version.is_current ? 'is-current' : ''}`} key={version.id}>
                <div className="version-history-card__top">
                  <div>
                    <span className="workshop-card__mark">{KIND_LABELS[version.version_kind] ?? version.version_kind}</span>
                    <h3>Version {version.version_no}</h3>
                  </div>
                  {version.is_current ? <strong className="version-current-badge">CURRENT</strong> : null}
                </div>
                <p>{version.class_summary} · LV {version.character_level}</p>
                <div className="workshop-card__meta">
                  <span>{new Date(version.created_at).toLocaleString()}</span>
                  <span>{version.parent_version_id ? 'Has parent' : 'Root version'}</span>
                  {version.superseded_by_version_id ? <span>Superseded by correction</span> : null}
                </div>
                {version.change_note ? <p className="builder-hint">{version.change_note}</p> : null}
                <a className="button secondary full" href={`/characters/${characterId}/versions/${version.version_no}`}>
                  View Build Snapshot →
                </a>
              </article>
            ))}
          </div>
        </section>

        {typeof versionNo === 'number' ? (
          <section className="workshop-section version-detail-section">
            <div className="workshop-section__heading">
              <div>
                <span>SNAPSHOT</span>
                <h2>Version {versionNo}</h2>
              </div>
              <a className="button secondary" href={`/characters/${characterId}/versions`}>Close detail</a>
            </div>
            {detail.isLoading ? <p className="builder-muted">Loading Build snapshot…</p> : null}
            {detail.error ? <div className="error-banner">{detail.error.message}</div> : null}
            {detail.data ? (
              <>
                <div className="builder-field-grid">
                  <div className="builder-rule-card">
                    <span>Kind</span>
                    <strong>{KIND_LABELS[detail.data.version_kind] ?? detail.data.version_kind}</strong>
                    <small>{detail.data.is_current ? 'Current Build' : 'Historical Build'}</small>
                  </div>
                  <div className="builder-rule-card">
                    <span>Character Level</span>
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
