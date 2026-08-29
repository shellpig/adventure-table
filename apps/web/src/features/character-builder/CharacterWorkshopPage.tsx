import { useMutation, useQuery } from '@tanstack/react-query'

import {
  createBuilderDraft,
  listCharacters,
  listCreateBuilderDrafts,
} from '../../api/characterBuilder'
import './builder.css'

export function CharacterWorkshopPage() {
  const characters = useQuery({ queryKey: ['character-list'], queryFn: listCharacters })
  const drafts = useQuery({ queryKey: ['builder-drafts', 'create'], queryFn: listCreateBuilderDrafts })
  const createDraft = useMutation({
    mutationFn: () => createBuilderDraft(),
    onSuccess: (view) => {
      window.location.assign(`/character-builder/${view.draft.id}`)
    },
  })

  return (
    <main className="workshop-page">
      <div className="workshop-shell">
        <header className="workshop-hero">
          <div>
            <p className="eyebrow">P1-B · Character Workshop</p>
            <h1>Character Workshop</h1>
            <p>建立、繼續編輯，或打開既有角色卡。草稿與正式角色保持分離。</p>
          </div>
          <button
            type="button"
            className="button primary"
            disabled={createDraft.isPending}
            onClick={() => createDraft.mutate()}
          >
            {createDraft.isPending ? '建立中…' : '+ Create Character'}
          </button>
        </header>

        {createDraft.error ? <div className="error-banner">{createDraft.error.message}</div> : null}

        <section className="workshop-section">
          <div className="workshop-section__heading">
            <div>
              <span>UNFINISHED</span>
              <h2>Creation Drafts</h2>
            </div>
            <small>{drafts.data?.length ?? 0} drafts</small>
          </div>
          {drafts.isLoading ? <p className="builder-muted">Loading drafts…</p> : null}
          {drafts.error ? <div className="error-banner">{drafts.error.message}</div> : null}
          <div className="workshop-grid">
            {drafts.data?.map((view) => (
              <article className="workshop-card draft-card" key={view.draft.id}>
                <div className="workshop-card__mark">DRAFT</div>
                <h3>{view.resolved_summary.name?.trim() || 'Unnamed character'}</h3>
                <p>
                  {view.resolved_summary.race_name ?? 'Race not selected'} ·{' '}
                  {view.resolved_summary.background_name ?? 'Background not selected'}
                </p>
                <div className="workshop-card__meta">
                  <span>Revision {view.draft.revision}</span>
                  <span>
                    {view.validation.issues.filter((issue) => issue.severity === 'blocking_error').length}{' '}
                    blockers
                  </span>
                </div>
                <a className="button secondary full" href={`/character-builder/${view.draft.id}`}>
                  Resume Draft →
                </a>
              </article>
            ))}
            {!drafts.isLoading && drafts.data?.length === 0 ? (
              <div className="workshop-empty">沒有未完成的創角草稿。</div>
            ) : null}
          </div>
        </section>

        <section className="workshop-section">
          <div className="workshop-section__heading">
            <div>
              <span>CHARACTERS</span>
              <h2>Existing Characters</h2>
            </div>
            <small>{characters.data?.length ?? 0} characters</small>
          </div>
          {characters.isLoading ? <p className="builder-muted">Loading characters…</p> : null}
          {characters.error ? <div className="error-banner">{characters.error.message}</div> : null}
          <div className="workshop-grid">
            {characters.data?.map((character) => (
              <article className="workshop-card" key={character.id}>
                <div className="workshop-card__level">LV {character.level}</div>
                <h3>{character.name}</h3>
                <p>{character.class_summary}</p>
                <div className="workshop-card__meta">
                  <span>Build v{character.version_no}</span>
                  <span>Ready</span>
                </div>
                <a className="button secondary full" href={`/characters/${character.id}`}>
                  Open Character Sheet →
                </a>
              </article>
            ))}
          </div>
        </section>
      </div>
    </main>
  )
}
