import { useRef, useState } from 'react'

import { useLocale } from '../../i18n/LocaleProvider'
import { useCharacterIoCopy } from '../../i18n/useCharacterIoCopy'
import {
  commitCharacterImport,
  previewCharacterImport,
  type CharacterImportLandingMode,
  type CharacterImportResult,
} from './api'
import './character-io.css'


type ImportCharacterDialogProps = {
  className?: string
}

function format(template: string, values: Record<string, string | number>): string {
  return Object.entries(values).reduce(
    (result, [key, value]) => result.replaceAll(`{${key}}`, String(value)),
    template,
  )
}

export function ImportCharacterDialog({
  className = 'button secondary',
}: ImportCharacterDialogProps) {
  const copy = useCharacterIoCopy()
  const { locale } = useLocale()
  const fileInput = useRef<HTMLInputElement>(null)
  const [open, setOpen] = useState(false)
  const [documentText, setDocumentText] = useState('')
  const [preview, setPreview] = useState<CharacterImportResult | null>(null)
  const [pending, setPending] = useState<'preview' | 'commit' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [historyConfirmed, setHistoryConfirmed] = useState(false)

  const resetPreview = (nextText: string) => {
    setDocumentText(nextText)
    setPreview(null)
    setHistoryConfirmed(false)
    setError(null)
  }

  const modeLabel = (mode: CharacterImportLandingMode): string => {
    if (mode === 'character') return copy.importModeCharacter
    if (mode === 'draft_with_history_loss') return copy.importModeDraftHistoryLoss
    return copy.importModeDraft
  }

  const latestImportLabel = (value: string | null | undefined): string => {
    if (!value) return copy.importDuplicateUnknownDate
    const parsed = new Date(value)
    if (Number.isNaN(parsed.getTime())) return copy.importDuplicateUnknownDate
    return new Intl.DateTimeFormat(locale, {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(parsed)
  }

  const close = () => {
    if (pending) return
    setOpen(false)
  }

  return (
    <>
      <button
        type="button"
        className={className}
        aria-label={copy.importAria}
        onClick={() => setOpen(true)}
      >
        {copy.importLabel}
      </button>

      {open ? (
        <div className="character-import-backdrop" role="presentation">
          <section
            className="character-import-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="character-import-title"
          >
            <header className="character-import-dialog__header">
              <div>
                <h2 id="character-import-title">{copy.importTitle}</h2>
                <p>{copy.importDescription}</p>
              </div>
              <button
                type="button"
                className="character-import-dialog__close"
                aria-label={copy.importClose}
                disabled={Boolean(pending)}
                onClick={close}
              >
                ×
              </button>
            </header>

            <div className="character-import-dialog__body">
              <input
                ref={fileInput}
                className="character-import-file-input"
                type="file"
                accept="application/json,.json"
                onChange={async (event) => {
                  const file = event.target.files?.[0]
                  if (!file) return
                  try {
                    resetPreview(await file.text())
                  } catch (caught) {
                    setError(caught instanceof Error ? caught.message : String(caught))
                  } finally {
                    event.target.value = ''
                  }
                }}
              />
              <button
                type="button"
                className="button secondary"
                disabled={Boolean(pending)}
                onClick={() => fileInput.current?.click()}
              >
                {copy.importChooseFile}
              </button>

              <label className="character-import-editor">
                <span>{copy.importPasteLabel}</span>
                <textarea
                  value={documentText}
                  placeholder={copy.importPastePlaceholder}
                  spellCheck={false}
                  disabled={Boolean(pending)}
                  onChange={(event) => resetPreview(event.target.value)}
                />
              </label>

              {error ? (
                <div className="error-banner" role="alert">
                  {error}
                </div>
              ) : null}

              {preview ? (
                <div className="character-import-preview">
                  <div className="character-import-preview__character">
                    <div>
                      <strong>{preview.character_preview.name}</strong>
                      <span>{preview.character_preview.class_summary}</span>
                    </div>
                    <b>{format(copy.importLevel, { level: preview.character_preview.level })}</b>
                  </div>
                  <div className="character-import-preview__stats">
                    <span>
                      {format(copy.importResolved, { count: preview.resolved_ref_count })}
                    </span>
                    <span>
                      {format(copy.importUnresolved, { count: preview.unresolved_ref_count })}
                    </span>
                    <span>
                      {format(copy.importLandingMode, {
                        mode: modeLabel(preview.landing_mode),
                      })}
                    </span>
                  </div>

                  {preview.duplicate_hint ? (
                    <div className="character-import-warning">
                      {format(copy.importDuplicate, {
                        count: preview.duplicate_hint.count,
                        latest: latestImportLabel(preview.duplicate_hint.latest_imported_at),
                      })}
                    </div>
                  ) : null}

                  {preview.unresolved_refs.length ? (
                    <details className="character-import-unresolved">
                      <summary>{copy.importUnresolvedDetails}</summary>
                      <ul>
                        {preview.unresolved_refs.map((item, index) => (
                          <li key={`${item.origin}-${item.version_no ?? 'state'}-${item.stable_key}-${index}`}>
                            <code>{item.stable_key}</code>
                            <span>
                              {item.origin === 'build'
                                ? copy.importOriginBuild
                                : copy.importOriginState}
                              {item.version_no
                                ? ` · ${format(copy.importVersion, { version: item.version_no })}`
                                : ''}
                            </span>
                          </li>
                        ))}
                      </ul>
                    </details>
                  ) : null}

                  {preview.landing_mode === 'draft_with_history_loss' ? (
                    <div className="character-import-loss">
                      <strong>{copy.importHistoryLoss}</strong>
                      <label>
                        <input
                          type="checkbox"
                          checked={historyConfirmed}
                          disabled={Boolean(pending)}
                          onChange={(event) => setHistoryConfirmed(event.target.checked)}
                        />
                        <span>{copy.importHistoryConfirm}</span>
                      </label>
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>

            <footer className="character-import-dialog__footer">
              <button
                type="button"
                className="button secondary"
                disabled={Boolean(pending)}
                onClick={close}
              >
                {copy.importCancel}
              </button>
              {preview ? (
                <button
                  type="button"
                  className="button primary"
                  disabled={
                    Boolean(pending) ||
                    (preview.landing_mode === 'draft_with_history_loss' && !historyConfirmed)
                  }
                  onClick={async () => {
                    setPending('commit')
                    setError(null)
                    try {
                      const result = await commitCharacterImport(documentText)
                      const destination = result.character_path ?? result.draft_path
                      if (!destination) throw new Error(copy.importPreviewRequired)
                      window.location.assign(destination)
                    } catch (caught) {
                      setError(caught instanceof Error ? caught.message : String(caught))
                      setPending(null)
                    }
                  }}
                >
                  {pending === 'commit' ? copy.importCommitting : copy.importContinue}
                </button>
              ) : (
                <button
                  type="button"
                  className="button primary"
                  disabled={Boolean(pending)}
                  onClick={async () => {
                    if (!documentText.trim()) {
                      setError(copy.importEmpty)
                      return
                    }
                    setPending('preview')
                    setError(null)
                    try {
                      setPreview(await previewCharacterImport(documentText))
                    } catch (caught) {
                      setError(caught instanceof Error ? caught.message : String(caught))
                    } finally {
                      setPending(null)
                    }
                  }}
                >
                  {pending === 'preview' ? copy.importPreviewing : copy.importPreview}
                </button>
              )}
            </footer>
          </section>
        </div>
      ) : null}
    </>
  )
}
