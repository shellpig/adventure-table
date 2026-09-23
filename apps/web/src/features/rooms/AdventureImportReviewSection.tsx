import { useState } from 'react'

import {
  answerAdventureImportQuestion,
  finalizeAdventureImport,
  resolveAdventureImportWarning,
  setAdventureImportEntryReview,
  updateAdventureImportDraft,
  AdventureImportApiError,
  type AdventureImport,
  type AdventureImportDraft,
  type DraftEntry,
  type DraftSourceRef,
  type ReviewStatus,
  type WarningLevel,
} from '../../api/adventureImports'
import type {
  AdventureDefinition,
  AdventureEntryKind,
  AdventureEntryPayload,
} from '../../api/adventures'
import {
  AdventureEntryPayloadFields,
  ENTRY_KIND_FIELDS,
  entryFieldsFromPayload,
  entryKindLabel,
  entryPayloadFromForm,
  fieldLabel,
} from './AdventureEntryPayloadFields'
import {
  buildDraftMutationInput,
  type DraftMutationAction,
} from './adventureImportHelpers'
import {
  draftProvenanceLabel,
  importerErrorMessage,
  reviewStatusLabel,
  warningLevelLabel,
  type AdventureImporterCopy,
} from './adventureImporterCopy'
import { adventuresCopy } from './adventuresCopy'

export function DraftPayloadSummary({
  payload,
  copy,
}: {
  payload: AdventureEntryPayload
  copy: ReturnType<typeof adventuresCopy>
}) {
  const fields = entryFieldsFromPayload(payload)
  const entries = Object.entries(fields).filter(([, v]) => v !== '')
  if (entries.length === 0) return null

  return (
    <div className="importer-meta-row">
      {entries.map(([field, value]) => (
        <span key={field}>
          <strong>{fieldLabel(field, copy)}:</strong> {value}
        </span>
      ))}
    </div>
  )
}

type DraftEntryFormState = {
  entryKind: AdventureEntryKind
  parentEntryId: string
  note: string
  fields: Record<string, string>
}

function initialDraftEntryFormState(kind: AdventureEntryKind = 'scene'): DraftEntryFormState {
  return {
    entryKind: kind,
    parentEntryId: '',
    note: '',
    fields: {},
  }
}

export type AdventureImportReviewSectionProps = {
  roomId: string
  token: string
  importId: string
  selectedImport: AdventureImport
  draft: AdventureImportDraft | null
  canAuthor: boolean
  isFinalized: boolean
  pending: boolean
  staleError: boolean
  copy: AdventureImporterCopy
  editorCopy: ReturnType<typeof adventuresCopy>
  onDraftUpdated: (draft: AdventureImportDraft) => void
  onImportReload: () => Promise<void>
  onViewSource: (sourceRef: DraftSourceRef) => void
  onFinalized: (adv: AdventureDefinition) => void
  onError: (err: string) => void
  setPending: (pending: boolean) => void
  setStaleError: (stale: boolean) => void
}

export function AdventureImportReviewSection({
  roomId,
  token,
  importId,
  selectedImport,
  draft,
  canAuthor,
  isFinalized,
  pending,
  staleError,
  copy,
  editorCopy,
  onDraftUpdated,
  onImportReload,
  onViewSource,
  onFinalized,
  onError,
  setPending,
  setStaleError,
}: AdventureImportReviewSectionProps) {
  // Draft entry add/edit form state
  const [editMode, setEditMode] = useState<
    { kind: 'create' } | { kind: 'edit'; entry: DraftEntry }
  >({ kind: 'create' })
  const [entryForm, setEntryForm] = useState<DraftEntryFormState>(initialDraftEntryFormState('scene'))

  // Warning resolution inputs: { [warning_id]: resolution_text }
  const [resolutionInputs, setResolutionInputs] = useState<Record<string, string>>({})

  // Question answer inputs: { [question_id]: answer_text }
  const [questionInputs, setQuestionInputs] = useState<Record<string, string>>({})

  // Finalize form inputs
  const [finalizeName, setFinalizeName] = useState(selectedImport.name)
  const [finalizeSummary, setFinalizeSummary] = useState('')

  if (!draft) return null

  // Group warnings by level
  const blockingWarnings = draft.warnings.filter((w) => w.level === 'blocking')
  const warningLevelWarnings = draft.warnings.filter((w) => w.level === 'warning')
  const infoWarnings = draft.warnings.filter((w) => w.level === 'info')
  const unresolvedBlockers = blockingWarnings.filter((w) => !w.resolved)
  const hasUnresolvedBlocking = unresolvedBlockers.length > 0

  const handleSetReview = async (entryId: string, reviewStatus: ReviewStatus) => {
    if (!canAuthor || isFinalized) return
    setPending(true)
    onError('')
    setStaleError(false)
    try {
      const updated = await setAdventureImportEntryReview(roomId, importId, entryId, token, {
        review_status: reviewStatus,
        expected_revision: draft.revision,
      })
      onDraftUpdated(updated)
    } catch (cause) {
      if (
        cause instanceof AdventureImportApiError &&
        cause.code === 'adventure_import_revision_conflict'
      ) {
        setStaleError(true)
        onError(copy.staleDraftConflict)
      } else {
        onError(importerErrorMessage(cause, copy))
      }
    } finally {
      setPending(false)
    }
  }

  const handleResolveWarning = async (warningId: string) => {
    if (!canAuthor || isFinalized) return
    setPending(true)
    onError('')
    setStaleError(false)
    const resolution = resolutionInputs[warningId]?.trim() || null
    try {
      const updated = await resolveAdventureImportWarning(roomId, importId, warningId, token, {
        resolution,
        expected_revision: draft.revision,
      })
      onDraftUpdated(updated)
      setResolutionInputs((prev) => {
        const next = { ...prev }
        delete next[warningId]
        return next
      })
    } catch (cause) {
      if (
        cause instanceof AdventureImportApiError &&
        cause.code === 'adventure_import_revision_conflict'
      ) {
        setStaleError(true)
        onError(copy.staleDraftConflict)
      } else {
        onError(importerErrorMessage(cause, copy))
      }
    } finally {
      setPending(false)
    }
  }

  const handleAnswerQuestion = async (questionId: string) => {
    if (!canAuthor || isFinalized) return
    const answer = questionInputs[questionId]?.trim()
    if (!answer) return
    setPending(true)
    onError('')
    setStaleError(false)
    try {
      const updated = await answerAdventureImportQuestion(roomId, importId, questionId, token, {
        answer,
        expected_revision: draft.revision,
      })
      onDraftUpdated(updated)
      setQuestionInputs((prev) => {
        const next = { ...prev }
        delete next[questionId]
        return next
      })
    } catch (cause) {
      if (
        cause instanceof AdventureImportApiError &&
        cause.code === 'adventure_import_revision_conflict'
      ) {
        setStaleError(true)
        onError(copy.staleDraftConflict)
      } else {
        onError(importerErrorMessage(cause, copy))
      }
    } finally {
      setPending(false)
    }
  }

  const handleSaveDraftEntry = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!canAuthor || isFinalized) return
    setPending(true)
    onError('')
    setStaleError(false)

    try {
      const action: DraftMutationAction =
        editMode.kind === 'edit'
          ? {
              type: 'edit',
              entryId: editMode.entry.entry_id,
              entry: {
                entry_kind: entryForm.entryKind,
                payload: entryPayloadFromForm({
                  kind: entryForm.entryKind,
                  fields: entryForm.fields,
                }),
                parent_entry_id: entryForm.parentEntryId.trim() || null,
                note: entryForm.note.trim() || null,
                provenance: editMode.entry.provenance,
                review_status: editMode.entry.review_status,
                asset_ids: editMode.entry.asset_ids,
                title: editMode.entry.title,
                body: editMode.entry.body,
                visibility: editMode.entry.visibility,
              },
            }
          : {
              type: 'add',
              entry: {
                entry_kind: entryForm.entryKind,
                payload: entryPayloadFromForm({
                  kind: entryForm.entryKind,
                  fields: entryForm.fields,
                }),
                parent_entry_id: entryForm.parentEntryId.trim() || null,
                note: entryForm.note.trim() || null,
                provenance: 'user_explicit',
                review_status: 'pending',
                asset_ids: [],
                title: null,
                body: null,
                visibility: 'dm_only',
              },
            }

      const input = buildDraftMutationInput(draft, action)
      const updatedDraft = await updateAdventureImportDraft(roomId, importId, token, input)

      onDraftUpdated(updatedDraft)
      setEditMode({ kind: 'create' })
      setEntryForm(initialDraftEntryFormState(entryForm.entryKind))
      await onImportReload()
    } catch (cause) {
      if (
        cause instanceof AdventureImportApiError &&
        cause.code === 'adventure_import_revision_conflict'
      ) {
        setStaleError(true)
        onError(copy.staleDraftConflict)
      } else {
        onError(importerErrorMessage(cause, copy))
      }
    } finally {
      setPending(false)
    }
  }

  const handleDeleteDraftEntry = async (entryId: string) => {
    if (!canAuthor || isFinalized) return
    if (!window.confirm(copy.deleteEntryConfirm)) return
    setPending(true)
    onError('')
    setStaleError(false)

    try {
      const input = buildDraftMutationInput(draft, { type: 'delete', entryId })
      const updatedDraft = await updateAdventureImportDraft(roomId, importId, token, input)

      onDraftUpdated(updatedDraft)
      if (editMode.kind === 'edit' && editMode.entry.entry_id === entryId) {
        setEditMode({ kind: 'create' })
        setEntryForm(initialDraftEntryFormState(entryForm.entryKind))
      }
      await onImportReload()
    } catch (cause) {
      if (
        cause instanceof AdventureImportApiError &&
        cause.code === 'adventure_import_revision_conflict'
      ) {
        setStaleError(true)
        onError(copy.staleDraftConflict)
      } else {
        onError(importerErrorMessage(cause, copy))
      }
    } finally {
      setPending(false)
    }
  }

  const handleFinalize = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!canAuthor || isFinalized || hasUnresolvedBlocking) return
    const nameTrimmed = finalizeName.trim()
    if (!nameTrimmed) return
    setPending(true)
    onError('')
    try {
      const adv = await finalizeAdventureImport(roomId, importId, token, {
        name: nameTrimmed,
        summary: finalizeSummary.trim() || null,
        expected_revision: draft.revision,
      })
      await onImportReload()
      onFinalized(adv)
    } catch (cause) {
      onError(importerErrorMessage(cause, copy))
    } finally {
      setPending(false)
    }
  }

  const handleFieldChange = (field: string, value: string) => {
    setEntryForm((prev) => ({
      ...prev,
      fields: {
        ...prev.fields,
        [field]: value,
      },
    }))
  }

  return (
    <div className="importer-section" data-testid="importer-review-section">
      <h3>{copy.draftTitle}</h3>
      <div className="importer-meta-row">
        <span>
          {copy.draftRevisionLabel}: {draft.revision}
        </span>
        {staleError ? (
          <button
            className="button primary"
            type="button"
            onClick={() => onImportReload()}
          >
            {copy.reloadDraftAction}
          </button>
        ) : null}
      </div>

      {/* 1. Warnings Section Grouped by Level */}
      <div className="importer-warnings-group" data-testid="importer-warnings-group">
        <h4>{copy.warningsTitle}</h4>

        {draft.warnings.length === 0 ? (
          <p className="room-card-hint">{copy.noWarnings}</p>
        ) : (
          <>
            {hasUnresolvedBlocking ? (
              <div className="importer-blocking-notice" data-testid="importer-blocking-notice">
                {copy.blockingWarningsNotice}
              </div>
            ) : null}

            {/* Blocking Warnings */}
            {blockingWarnings.length > 0 ? (
              <div className="importer-warning-category" data-testid="warnings-blocking">
                <h5>{copy.warningsBlockingTitle}</h5>
                <div className="importer-warning-list">
                  {blockingWarnings.map((w) => (
                    <div
                      className={`importer-warning-card importer-warning-card--blocking${w.resolved ? ' importer-warning-card--resolved' : ''}`}
                      key={w.warning_id}
                    >
                      <div className="importer-warning-header">
                        <span className="importer-warning-badge importer-warning-badge--blocking">
                          {warningLevelLabel(w.level, copy)}
                        </span>
                        <span className="importer-warning-message">{w.message}</span>
                      </div>
                      <div className="importer-meta-row">
                        <span>{copy.warningCodeLabel}: {w.code}</span>
                        {w.entry_id ? <span>{copy.warningEntryLabel}: {w.entry_id}</span> : null}
                        {w.resolved ? (
                          <span className="importer-resolved-badge">
                            {copy.resolvedBadge}
                            {w.resolution ? ` (${copy.resolutionLabel}: ${w.resolution})` : ''}
                          </span>
                        ) : null}
                      </div>
                      {!w.resolved && canAuthor && !isFinalized ? (
                        <div className="importer-warning-resolve-bar">
                          <input
                            disabled={pending}
                            placeholder={copy.resolutionPlaceholder}
                            type="text"
                            value={resolutionInputs[w.warning_id] ?? ''}
                            onChange={(e) =>
                              setResolutionInputs((prev) => ({
                                ...prev,
                                [w.warning_id]: e.target.value,
                              }))
                            }
                          />
                          <button
                            className="button secondary"
                            disabled={pending}
                            type="button"
                            onClick={() => handleResolveWarning(w.warning_id)}
                          >
                            {copy.resolveWarningAction}
                          </button>
                        </div>
                      ) : null}
                    </div>
                  ))}
                </div>
              </div>
            ) : null}

            {/* Warning Level Warnings */}
            {warningLevelWarnings.length > 0 ? (
              <div className="importer-warning-category" data-testid="warnings-warning">
                <h5>{copy.warningsWarningTitle}</h5>
                <div className="importer-warning-list">
                  {warningLevelWarnings.map((w) => (
                    <div
                      className={`importer-warning-card importer-warning-card--warning${w.resolved ? ' importer-warning-card--resolved' : ''}`}
                      key={w.warning_id}
                    >
                      <div className="importer-warning-header">
                        <span className="importer-warning-badge importer-warning-badge--warning">
                          {warningLevelLabel(w.level, copy)}
                        </span>
                        <span className="importer-warning-message">{w.message}</span>
                      </div>
                      <div className="importer-meta-row">
                        <span>{copy.warningCodeLabel}: {w.code}</span>
                        {w.entry_id ? <span>{copy.warningEntryLabel}: {w.entry_id}</span> : null}
                        {w.resolved ? (
                          <span className="importer-resolved-badge">
                            {copy.resolvedBadge}
                            {w.resolution ? ` (${copy.resolutionLabel}: ${w.resolution})` : ''}
                          </span>
                        ) : null}
                      </div>
                      {!w.resolved && canAuthor && !isFinalized ? (
                        <div className="importer-warning-resolve-bar">
                          <input
                            disabled={pending}
                            placeholder={copy.resolutionPlaceholder}
                            type="text"
                            value={resolutionInputs[w.warning_id] ?? ''}
                            onChange={(e) =>
                              setResolutionInputs((prev) => ({
                                ...prev,
                                [w.warning_id]: e.target.value,
                              }))
                            }
                          />
                          <button
                            className="button secondary"
                            disabled={pending}
                            type="button"
                            onClick={() => handleResolveWarning(w.warning_id)}
                          >
                            {copy.resolveWarningAction}
                          </button>
                        </div>
                      ) : null}
                    </div>
                  ))}
                </div>
              </div>
            ) : null}

            {/* Info Level Warnings */}
            {infoWarnings.length > 0 ? (
              <div className="importer-warning-category" data-testid="warnings-info">
                <h5>{copy.warningsInfoTitle}</h5>
                <div className="importer-warning-list">
                  {infoWarnings.map((w) => (
                    <div
                      className={`importer-warning-card importer-warning-card--info${w.resolved ? ' importer-warning-card--resolved' : ''}`}
                      key={w.warning_id}
                    >
                      <div className="importer-warning-header">
                        <span className="importer-warning-badge importer-warning-badge--info">
                          {warningLevelLabel(w.level, copy)}
                        </span>
                        <span className="importer-warning-message">{w.message}</span>
                      </div>
                      <div className="importer-meta-row">
                        <span>{copy.warningCodeLabel}: {w.code}</span>
                        {w.entry_id ? <span>{copy.warningEntryLabel}: {w.entry_id}</span> : null}
                        {w.resolved ? (
                          <span className="importer-resolved-badge">
                            {copy.resolvedBadge}
                            {w.resolution ? ` (${copy.resolutionLabel}: ${w.resolution})` : ''}
                          </span>
                        ) : null}
                      </div>
                      {!w.resolved && canAuthor && !isFinalized ? (
                        <div className="importer-warning-resolve-bar">
                          <input
                            disabled={pending}
                            placeholder={copy.resolutionPlaceholder}
                            type="text"
                            value={resolutionInputs[w.warning_id] ?? ''}
                            onChange={(e) =>
                              setResolutionInputs((prev) => ({
                                ...prev,
                                [w.warning_id]: e.target.value,
                              }))
                            }
                          />
                          <button
                            className="button secondary"
                            disabled={pending}
                            type="button"
                            onClick={() => handleResolveWarning(w.warning_id)}
                          >
                            {copy.resolveWarningAction}
                          </button>
                        </div>
                      ) : null}
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </>
        )}
      </div>

      {/* 2. Questions Section */}
      {draft.draft.questions.length > 0 ? (
        <div className="importer-questions-group" data-testid="importer-questions-group" style={{ marginTop: '16px' }}>
          <h4>{copy.questionsTitle}</h4>
          <div className="importer-question-list">
            {draft.draft.questions.map((q) => (
              <div className="importer-question-card" key={q.question_id}>
                <p><strong>{q.message}</strong></p>
                {q.answer ? (
                  <div className="importer-meta-row">
                    <span className="importer-resolved-badge">{copy.answeredBadge}</span>
                    <span>{copy.answerLabel}: {q.answer}</span>
                  </div>
                ) : null}
                {canAuthor && !isFinalized ? (
                  <div className="importer-question-answer-bar">
                    <input
                      disabled={pending}
                      placeholder={copy.questionAnswerPlaceholder}
                      type="text"
                      value={questionInputs[q.question_id] ?? ''}
                      onChange={(e) =>
                        setQuestionInputs((prev) => ({
                          ...prev,
                          [q.question_id]: e.target.value,
                        }))
                      }
                    />
                    <button
                      className="button secondary"
                      disabled={pending || !questionInputs[q.question_id]?.trim()}
                      type="button"
                      onClick={() => handleAnswerQuestion(q.question_id)}
                    >
                      {copy.answerQuestionAction}
                    </button>
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {/* 3. Draft Entries List */}
      <div style={{ marginTop: '20px' }}>
        <h4>{copy.draftEntriesTitle}</h4>
        {draft.draft.entries.length === 0 ? (
          <p className="room-empty-text">{copy.emptyDraftEntries}</p>
        ) : (
          <div className="adventure-entry-list">
            {draft.draft.entries.map((entry) => (
              <article className="adventure-entry" key={entry.entry_id} data-testid={`draft-entry-${entry.entry_id}`}>
                <div className="adventure-entry__content">
                  <div className="adventure-entry__meta">
                    <span className="adventure-entry__kind">
                      {entryKindLabel(entry.entry_kind, editorCopy)}
                    </span>
                    <span className={`importer-review-status-badge importer-review-status-badge--${entry.review_status}`}>
                      {copy.reviewStatusLabel}: {reviewStatusLabel(entry.review_status, copy)}
                    </span>
                    <span className="adventure-entry__visibility">
                      {copy.provenanceLabel}: {draftProvenanceLabel(entry.provenance, copy)}
                    </span>
                    {entry.source_ref ? (
                      <span className="adventure-card__status">
                        {copy.sourceRefLabel}: {entry.source_ref.locator ?? entry.source_ref.source_id}
                      </span>
                    ) : null}
                  </div>
                  {entry.note ? <p className="adventure-entry__body">{entry.note}</p> : null}
                  <DraftPayloadSummary copy={editorCopy} payload={entry.payload} />
                </div>
                <div className="adventure-entry__actions">
                  {/* P6-F Review Action Controls (DM/author only, when not finalized) */}
                  {canAuthor && !isFinalized ? (
                    <>
                      <button
                        className="button secondary"
                        disabled={pending || entry.review_status === 'accepted'}
                        type="button"
                        onClick={() => handleSetReview(entry.entry_id, 'accepted')}
                      >
                        {copy.acceptEntryAction}
                      </button>
                      <button
                        className="button secondary"
                        disabled={pending || entry.review_status === 'ignored'}
                        type="button"
                        onClick={() => handleSetReview(entry.entry_id, 'ignored')}
                      >
                        {copy.ignoreEntryAction}
                      </button>
                      <button
                        className="button secondary"
                        disabled={pending || entry.review_status === 'uncertain'}
                        type="button"
                        onClick={() => handleSetReview(entry.entry_id, 'uncertain')}
                      >
                        {copy.markUncertainAction}
                      </button>
                      {/* View source: ONLY visible when entry.source_ref exists */}
                      {entry.source_ref ? (
                        <button
                          className="button secondary"
                          disabled={pending}
                          type="button"
                          onClick={() => onViewSource(entry.source_ref!)}
                        >
                          {copy.viewSourceAction}
                        </button>
                      ) : null}
                      <button
                        className="button secondary"
                        disabled={pending}
                        type="button"
                        onClick={() => {
                          setEditMode({ kind: 'edit', entry })
                          setEntryForm({
                            entryKind: entry.entry_kind,
                            parentEntryId: entry.parent_entry_id ?? '',
                            note: entry.note ?? '',
                            fields: entryFieldsFromPayload(entry.payload),
                          })
                        }}
                      >
                        {copy.editEntryAction}
                      </button>
                      <button
                        className="button danger"
                        disabled={pending}
                        type="button"
                        onClick={() => handleDeleteDraftEntry(entry.entry_id)}
                      >
                        {copy.deleteEntryAction}
                      </button>
                    </>
                  ) : null}
                </div>
              </article>
            ))}
          </div>
        )}
      </div>

      {/* 4. Add / Edit Draft Entry Form (DM/author only, when not finalized) */}
      {canAuthor && !isFinalized ? (
        <div style={{ marginTop: '20px' }}>
          <h4>
            {editMode.kind === 'edit'
              ? copy.editDraftEntryTitle
              : copy.addDraftEntryTitle}
          </h4>
          <form className="room-form" onSubmit={handleSaveDraftEntry}>
            <label className="room-field">
              <span>{copy.entryKindLabel}</span>
              <select
                disabled={pending}
                value={entryForm.entryKind}
                onChange={(e) => {
                  const nextKind = e.target.value as AdventureEntryKind
                  setEntryForm((prev) => ({
                    ...prev,
                    entryKind: nextKind,
                    fields: {},
                  }))
                }}
              >
                {(Object.keys(ENTRY_KIND_FIELDS) as AdventureEntryKind[]).map((kind) => (
                  <option key={kind} value={kind}>
                    {entryKindLabel(kind, editorCopy)}
                  </option>
                ))}
              </select>
            </label>

            <label className="room-field">
              <span>{copy.parentEntryLabel}</span>
              <select
                disabled={pending}
                value={entryForm.parentEntryId}
                onChange={(e) =>
                  setEntryForm((prev) => ({ ...prev, parentEntryId: e.target.value }))
                }
              >
                <option value="">{copy.parentEntryNone}</option>
                {draft.draft.entries
                  .filter(
                    (e) =>
                      e.entry_kind === 'section' &&
                      (editMode.kind !== 'edit' || e.entry_id !== editMode.entry.entry_id),
                  )
                  .map((sec) => (
                    <option key={sec.entry_id} value={sec.entry_id}>
                      {sec.entry_id} {sec.note ? `(${sec.note})` : ''}
                    </option>
                  ))}
              </select>
            </label>

            <label className="room-field">
              <span>{copy.noteLabel}</span>
              <input
                disabled={pending}
                type="text"
                value={entryForm.note}
                onChange={(e) => setEntryForm((prev) => ({ ...prev, note: e.target.value }))}
              />
            </label>

            {/* Reused Kind-Specific Payload Fields */}
            <AdventureEntryPayloadFields
              copy={editorCopy}
              disabled={pending}
              fields={entryForm.fields}
              kind={entryForm.entryKind}
              onChange={handleFieldChange}
            />

            {editMode.kind === 'edit' ? (
              <div className="importer-meta-row">
                <span>
                  {copy.provenanceLabel}:{' '}
                  {draftProvenanceLabel(editMode.entry.provenance, copy)}
                </span>
                <span>
                  {copy.sourceRefLabel}:{' '}
                  {editMode.entry.source_ref
                    ? editMode.entry.source_ref.locator ?? editMode.entry.source_ref.source_id
                    : copy.sourceRefNone}
                </span>
              </div>
            ) : null}

            <div className="adventure-card__actions">
              <button className="button primary" disabled={pending} type="submit">
                {editMode.kind === 'edit'
                  ? copy.updateDraftEntryAction
                  : copy.addDraftEntryAction}
              </button>
              {editMode.kind === 'edit' ? (
                <button
                  className="button secondary"
                  disabled={pending}
                  type="button"
                  onClick={() => {
                    setEditMode({ kind: 'create' })
                    setEntryForm(initialDraftEntryFormState(entryForm.entryKind))
                  }}
                >
                  {copy.cancelEditAction}
                </button>
              ) : null}
            </div>
          </form>
        </div>
      ) : null}

      {/* 5. Finalize Section */}
      <div className="importer-finalize-section" data-testid="importer-finalize-section" style={{ marginTop: '28px', borderTop: '1px solid var(--line-soft)', paddingTop: '20px' }}>
        <h4>{copy.finalizeSectionTitle}</h4>

        {isFinalized ? (
          <div>
            <p>{copy.importAlreadyFinalized}</p>
            {selectedImport.target_adventure_id ? (
              <a
                className="button primary"
                href={`/rooms/${roomId}/adventures/${selectedImport.target_adventure_id}`}
              >
                {copy.openTargetAdventure}
              </a>
            ) : null}
          </div>
        ) : canAuthor ? (
          <form className="room-form" onSubmit={handleFinalize}>
            <label className="room-field">
              <span>{copy.finalizeNameLabel}</span>
              <input
                disabled={pending}
                maxLength={160}
                required
                type="text"
                value={finalizeName}
                onChange={(e) => setFinalizeName(e.target.value)}
              />
            </label>

            <label className="room-field">
              <span>{copy.finalizeSummaryLabel}</span>
              <input
                disabled={pending}
                type="text"
                value={finalizeSummary}
                onChange={(e) => setFinalizeSummary(e.target.value)}
              />
            </label>

            {hasUnresolvedBlocking ? (
              <div className="importer-blocking-reason" data-testid="finalize-blocked-reason">
                {copy.finalizeBlockedReason}
              </div>
            ) : null}

            <button
              className="button primary room-form-submit"
              disabled={pending || hasUnresolvedBlocking || !finalizeName.trim()}
              type="submit"
            >
              {copy.finalizeAdventureAction}
            </button>
          </form>
        ) : null}
      </div>
    </div>
  )
}
