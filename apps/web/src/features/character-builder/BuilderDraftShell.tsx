import type { PropsWithChildren } from 'react'

import type { BuilderView } from '../../api/characterBuilder'

type BuilderDraftShellProps = PropsWithChildren<{
  view: BuilderView
}>

export function BuilderDraftShell({ view, children }: BuilderDraftShellProps) {
  const blockingCount = view.validation.issues.filter(
    (issue) => issue.severity === 'blocking_error',
  ).length

  return (
    <section className="character-builder-shell" aria-label="Character Builder draft">
      <header>
        <p className="eyebrow">P1-A · Builder Draft</p>
        <h1>{view.resolved_summary.name?.trim() || 'Unnamed character'}</h1>
        <p>
          Draft revision {view.draft.revision}
          {view.resolved_summary.target_level
            ? ` · Target level ${view.resolved_summary.target_level}`
            : ''}
        </p>
      </header>

      <div className="character-builder-shell__content">{children}</div>

      <aside aria-label="Builder validation summary">
        <strong>
          {blockingCount === 0
            ? 'No blocking draft issues'
            : `${blockingCount} blocking draft issue${blockingCount === 1 ? '' : 's'}`}
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
