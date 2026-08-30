import { useMutation, useQuery } from '@tanstack/react-query'

import {
  createBuilderDraft,
  listCharacters,
  listCreateBuilderDrafts,
} from '../../api/characterBuilder'
import {
  createCharacterVersionDraft,
  type VersionedBuilderMode,
} from '../../api/characterVersions'
import { useUiCopy } from '../../i18n/useUiCopy'
import './builder.css'

export function CharacterWorkshopPage() {
  const { t } = useUiCopy()
  const characters = useQuery({ queryKey: ['character-list'], queryFn: listCharacters })
  const drafts = useQuery({ queryKey: ['builder-drafts', 'create'], queryFn: listCreateBuilderDrafts })
  const createDraft = useMutation({
    mutationFn: () => createBuilderDraft(),
    onSuccess: (view) => {
      window.location.assign(`/character-builder/${view.draft.id}`)
    },
  })
  const versionDraft = useMutation({
    mutationFn: ({ characterId, mode }: { characterId: string; mode: VersionedBuilderMode }) =>
      createCharacterVersionDraft(characterId, mode),
    onSuccess: (view) => {
      window.location.assign(`/character-builder/${view.draft.id}`)
    },
  })

  return (
    <main className="workshop-page">
      <div className="workshop-shell">
        <header className="workshop-hero">
          <div>
            <p className="eyebrow">{t('workshop.eyebrow')}</p>
            <h1>{t('workshop.title')}</h1>
            <p>{t('workshop.description')}</p>
          </div>
          <button
            type="button"
            className="button primary"
            disabled={createDraft.isPending || versionDraft.isPending}
            onClick={() => createDraft.mutate()}
          >
            {createDraft.isPending ? t('workshop.creating') : t('workshop.create')}
          </button>
        </header>

        {createDraft.error ? <div className="error-banner">{createDraft.error.message}</div> : null}
        {versionDraft.error ? <div className="error-banner">{versionDraft.error.message}</div> : null}

        <section className="workshop-section">
          <div className="workshop-section__heading">
            <div>
              <span>{t('workshop.unfinished')}</span>
              <h2>{t('workshop.creationDrafts')}</h2>
            </div>
            <small>{t('workshop.draftCount', { count: drafts.data?.length ?? 0 })}</small>
          </div>
          {drafts.isLoading ? <p className="builder-muted">{t('workshop.loadingDrafts')}</p> : null}
          {drafts.error ? <div className="error-banner">{drafts.error.message}</div> : null}
          <div className="workshop-grid">
            {drafts.data?.map((view) => (
              <article className="workshop-card draft-card" key={view.draft.id}>
                <div className="workshop-card__mark">{t('workshop.draftBadge')}</div>
                <h3>{view.resolved_summary.name?.trim() || t('workshop.unnamedCharacter')}</h3>
                <p>
                  {view.resolved_summary.race_name ?? t('workshop.raceNotSelected')} ·{' '}
                  {view.resolved_summary.background_name ?? t('workshop.backgroundNotSelected')}
                </p>
                <div className="workshop-card__meta">
                  <span>{t('workshop.revision', { revision: view.draft.revision })}</span>
                  <span>
                    {t('workshop.blockers', {
                      count: view.validation.issues.filter((issue) => issue.severity === 'blocking_error').length,
                    })}
                  </span>
                </div>
                <a className="button secondary full" href={`/character-builder/${view.draft.id}`}>
                  {t('workshop.resumeDraft')}
                </a>
              </article>
            ))}
            {!drafts.isLoading && drafts.data?.length === 0 ? (
              <div className="workshop-empty">{t('workshop.noDrafts')}</div>
            ) : null}
          </div>
        </section>

        <section className="workshop-section">
          <div className="workshop-section__heading">
            <div>
              <span>{t('workshop.charactersBadge')}</span>
              <h2>{t('workshop.existingCharacters')}</h2>
            </div>
            <small>{t('workshop.characterCount', { count: characters.data?.length ?? 0 })}</small>
          </div>
          {characters.isLoading ? <p className="builder-muted">{t('workshop.loadingCharacters')}</p> : null}
          {characters.error ? <div className="error-banner">{characters.error.message}</div> : null}
          <div className="workshop-grid">
            {characters.data?.map((character) => (
              <article className="workshop-card" key={character.id}>
                <div className="workshop-card__level">{t('workshop.level', { level: character.level })}</div>
                <h3>{character.name}</h3>
                <p>{character.class_summary}</p>
                <div className="workshop-card__meta">
                  <span>{t('workshop.buildVersion', { version: character.version_no })}</span>
                  <span>{character.level >= 20 ? t('workshop.maxLevel') : t('workshop.ready')}</span>
                </div>
                <div className="workshop-card__actions">
                  <a className="button secondary full" href={`/characters/${character.id}`}>
                    {t('workshop.openSheet')}
                  </a>
                  <button
                    type="button"
                    className="button primary full"
                    disabled={versionDraft.isPending || character.level >= 20}
                    onClick={() =>
                      versionDraft.mutate({ characterId: character.id, mode: 'level_up' })
                    }
                  >
                    {t('workshop.levelUp')}
                  </button>
                  <div className="workshop-card__split-actions">
                    <button
                      type="button"
                      className="button secondary"
                      disabled={versionDraft.isPending}
                      onClick={() =>
                        versionDraft.mutate({ characterId: character.id, mode: 'build_edit' })
                      }
                    >
                      {t('workshop.editBuild')}
                    </button>
                    <button
                      type="button"
                      className="button secondary"
                      disabled={versionDraft.isPending}
                      onClick={() =>
                        versionDraft.mutate({ characterId: character.id, mode: 'correction' })
                      }
                    >
                      {t('workshop.correctBuild')}
                    </button>
                  </div>
                  <a className="button secondary full" href={`/characters/${character.id}/versions`}>
                    {t('workshop.versionHistory')}
                  </a>
                </div>
              </article>
            ))}
          </div>
        </section>
      </div>
    </main>
  )
}
