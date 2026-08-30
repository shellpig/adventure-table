import type { PropsWithChildren } from 'react'

import type { BuilderView } from '../../api/characterBuilder'
import { useUiCopy } from '../../i18n/useUiCopy'

type BuilderDraftShellProps = PropsWithChildren<{
  view: BuilderView
}>

export function BuilderDraftShell({ view, children }: BuilderDraftShellProps) {
  const { t } = useUiCopy()
  const blockingCount = view.validation.issues.filter(
    (issue) => issue.severity === 'blocking_error',
  ).length

  return (
    <section className="character-builder-shell" aria-label={t('draftShell.aria')}>
      <header>
        <p className="eyebrow">{t('draftShell.eyebrow')}</p>
        <h1>{view.resolved_summary.name?.trim() || t('builder.unnamedCharacter')}</h1>
        <p>
          {t('builder.draftRevision', { revision: view.draft.revision })}
          {view.resolved_summary.target_level
            ? ` · ${t('draftShell.targetLevel', { level: view.resolved_summary.target_level })}`
            : ''}
        </p>
      </header>

      <div className="character-builder-shell__content">{children}</div>

      <aside aria-label={t('draftShell.validationAria')}>
        <strong>
          {blockingCount === 0
            ? t('draftShell.noBlocking')
            : t(blockingCount === 1 ? 'draftShell.blocking' : 'draftShell.blockingPlural', {
                count: blockingCount,
              })}
        </strong>
        <ul>
          {view.validation.issues.map((issue) => (
            <li key={`${issue.code}:${issue.path}`}>
              [{issue.severity}] {issue.message}
            </li>
          ))}
        </ul>
      </aside>
    </section>
  )
}
