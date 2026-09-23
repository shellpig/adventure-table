import { useEffect, useState } from 'react'

import {
  createAdventureImport,
  getAdventureImportDraft,
  listAdventureImports,
  listAdventureImportSources,
  readSourceChunk,
  type AdventureImport,
  type AdventureImportDraft,
  type AdventureImportSource,
  type DraftSourceRef,
  type SourceChunk,
} from '../../api/adventureImports'
import type { AdventureDefinition } from '../../api/adventures'
import { useLocale } from '../../i18n/LocaleProvider'
import { AdventureImportReviewSection, DraftPayloadSummary } from './AdventureImportReviewSection'
import { AdventureImportSourceSection, WhitelistedSourceMetadata } from './AdventureImportSourceSection'
import {
  CHUNK_LIMIT,
  buildDraftMutationInput,
  computeChunkPagination,
  formatWhitelistedMetadata,
  inferSourceKindFromFilename,
  normalizeSourceFile,
  parseSourceLocatorOffset,
  type ChunkPagination,
  type DraftMutationAction,
  type ExactUpdateImportDraftInput,
  type NormalizedSourceFileInput,
} from './adventureImportHelpers'
import {
  adventureImporterCopy,
  importerErrorMessage,
  importStatusLabel,
} from './adventureImporterCopy'
import { adventuresCopy } from './adventuresCopy'
import './rooms.css'

// Re-export helper functions and types for consumer & test backward compatibility
export {
  CHUNK_LIMIT,
  buildDraftMutationInput,
  computeChunkPagination,
  formatWhitelistedMetadata,
  inferSourceKindFromFilename,
  normalizeSourceFile,
  parseSourceLocatorOffset,
  DraftPayloadSummary,
  WhitelistedSourceMetadata,
}
export type {
  ChunkPagination,
  DraftMutationAction,
  ExactUpdateImportDraftInput,
  NormalizedSourceFileInput,
}

export type AdventureImporterPanelProps = {
  roomId: string
  token: string
  canAuthor?: boolean
  onFinalized?: (adventure: AdventureDefinition) => void
}

export function AdventureImporterPanel({
  roomId,
  token,
  canAuthor = true,
  onFinalized,
}: AdventureImporterPanelProps) {
  const { locale } = useLocale()
  const copy = adventureImporterCopy(locale)
  const editorCopy = adventuresCopy(locale)

  const [imports, setImports] = useState<AdventureImport[]>([])
  const [selectedImportId, setSelectedImportId] = useState<string | null>(null)
  const [newImportName, setNewImportName] = useState('')
  const [sources, setSources] = useState<AdventureImportSource[]>([])
  const [draft, setDraft] = useState<AdventureImportDraft | null>(null)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [staleError, setStaleError] = useState(false)

  // Chunk viewer state
  const [chunkViewer, setChunkViewer] = useState<{
    sourceId: string
    chunk: SourceChunk | null
    offset: number
    loading: boolean
  } | null>(null)

  const selectedImport = imports.find((item) => item.id === selectedImportId) ?? null

  const reloadImportList = async () => {
    const list = await listAdventureImports(roomId, token)
    setImports(list)
  }

  const reloadSelectedImport = async (importId: string) => {
    setPending(true)
    setError(null)
    setStaleError(false)
    try {
      const [srcList, draftData, impList] = await Promise.all([
        listAdventureImportSources(roomId, importId, token),
        getAdventureImportDraft(roomId, importId, token),
        listAdventureImports(roomId, token),
      ])
      setSources(srcList)
      setDraft(draftData)
      setImports(impList)
    } catch (cause) {
      setError(importerErrorMessage(cause, copy))
    } finally {
      setPending(false)
    }
  }

  // Initial load: reset state and set selection deterministically to first returned import or null
  useEffect(() => {
    if (!canAuthor) return
    let active = true
    setSources([])
    setDraft(null)
    setChunkViewer(null)
    setError(null)
    setStaleError(false)

    void listAdventureImports(roomId, token)
      .then((list) => {
        if (!active) return
        setImports(list)
        setSelectedImportId(list.length > 0 ? list[0].id : null)
      })
      .catch((cause) => {
        if (active) {
          setImports([])
          setSelectedImportId(null)
          setError(importerErrorMessage(cause, copy))
        }
      })

    return () => {
      active = false
    }
  }, [canAuthor, copy, roomId, token])

  // When selectedImportId changes, reload sources and draft
  useEffect(() => {
    if (!selectedImportId || !canAuthor) {
      setSources([])
      setDraft(null)
      setChunkViewer(null)
      return
    }
    void reloadSelectedImport(selectedImportId)
  }, [selectedImportId, canAuthor, roomId, token])

  const handleCreateImport = async (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = newImportName.trim()
    if (!trimmed || !canAuthor) return
    setPending(true)
    setError(null)
    try {
      const created = await createAdventureImport(roomId, token, { name: trimmed })
      setNewImportName('')
      await reloadImportList()
      setSelectedImportId(created.id)
    } catch (cause) {
      setError(importerErrorMessage(cause, copy))
    } finally {
      setPending(false)
    }
  }

  const handleOpenChunk = async (sourceId: string, offset = 0) => {
    if (!selectedImportId) return
    setChunkViewer({ sourceId, chunk: null, offset, loading: true })
    try {
      const chunk = await readSourceChunk(roomId, selectedImportId, sourceId, token, {
        offset,
        limit: CHUNK_LIMIT,
      })
      setChunkViewer({ sourceId, chunk, offset, loading: false })
    } catch (cause) {
      setError(importerErrorMessage(cause, copy))
      setChunkViewer(null)
    }
  }

  const handleViewSource = async (sourceRef: DraftSourceRef) => {
    const source = sources.find((item) => item.id === sourceRef.source_id)
    const offset = parseSourceLocatorOffset(sourceRef, source?.metadata_json ?? {})
    await handleOpenChunk(sourceRef.source_id, offset)
  }

  const handleFinalizedSuccess = (adv: AdventureDefinition) => {
    if (onFinalized) {
      onFinalized(adv)
    } else {
      window.location.assign(`/rooms/${roomId}/adventures/${adv.id}`)
    }
  }

  // Player / Member sees zero importer controls
  if (!canAuthor) {
    return null
  }

  return (
    <section className="adventure-importer-panel" data-testid="adventure-importer-panel">
      <h2>{copy.importerTitle}</h2>
      <p className="room-card-description">{copy.importerIntro}</p>

      {error ? <div className="form-error">{error}</div> : null}

      {/* 1. Create Import Form */}
      <div className="importer-section">
        <h3>{copy.createImportTitle}</h3>
        <form className="room-form" onSubmit={handleCreateImport}>
          <label className="room-field">
            <span>{copy.importNameLabel}</span>
            <input
              disabled={pending}
              required
              type="text"
              value={newImportName}
              onChange={(e) => setNewImportName(e.target.value)}
            />
          </label>
          <button
            className="button primary room-form-submit"
            disabled={pending || !newImportName.trim()}
            type="submit"
          >
            {copy.createImportAction}
          </button>
        </form>
      </div>

      {/* 2. Import List & Selected Import Overview */}
      <div className="importer-section">
        <h3>{copy.importListTitle}</h3>
        {imports.length === 0 ? (
          <p className="room-empty-text">{copy.emptyImports}</p>
        ) : (
          <div className="importer-card-grid">
            {imports.map((item) => {
              const isSelected = item.id === selectedImportId
              return (
                <div
                  className={`importer-item-card${isSelected ? ' importer-item-card--active' : ''}`}
                  key={item.id}
                  data-testid={`importer-card-${item.id}`}
                >
                  <div>
                    <strong>{item.name}</strong>
                    <div className="importer-meta-row">
                      <span>
                        {copy.statusLabel}: {importStatusLabel(item.status, copy)}
                      </span>
                      <span>
                        {copy.revisionLabel}: {item.revision}
                      </span>
                    </div>
                    {item.target_adventure_id ? (
                      <div className="importer-meta-row" style={{ marginTop: '4px' }}>
                        <a
                          className="button secondary"
                          href={`/rooms/${roomId}/adventures/${item.target_adventure_id}`}
                        >
                          {copy.openTargetAdventure}
                        </a>
                      </div>
                    ) : null}
                  </div>
                  <div className="adventure-card__actions">
                    {isSelected ? (
                      <span className="campaign-card__selected">{copy.selectedBadge}</span>
                    ) : (
                      <button
                        className="button secondary"
                        disabled={pending}
                        type="button"
                        onClick={() => setSelectedImportId(item.id)}
                      >
                        {copy.selectImport}
                      </button>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}

        {selectedImport ? (
          <div className="importer-meta-row" style={{ marginTop: '12px' }}>
            <span>
              <strong>{selectedImport.name}</strong> — {copy.statusLabel}:{' '}
              {importStatusLabel(selectedImport.status, copy)}, {copy.revisionLabel}:{' '}
              {selectedImport.revision}
            </span>
            {selectedImport.target_adventure_id ? (
              <a
                className="button primary"
                href={`/rooms/${roomId}/adventures/${selectedImport.target_adventure_id}`}
              >
                {copy.openTargetAdventure}
              </a>
            ) : null}
            <button
              className="button secondary"
              disabled={pending}
              type="button"
              onClick={() => reloadSelectedImport(selectedImport.id)}
            >
              {copy.reloadImport}
            </button>
          </div>
        ) : null}
      </div>

      {/* Selected Import Content: Sources and Draft/Review */}
      {selectedImport && selectedImport.status !== 'cancelled' ? (
        <>
          <AdventureImportSourceSection
            key={`source-${selectedImport.id}`}
            canAuthor={canAuthor}
            chunkViewer={chunkViewer}
            copy={copy}
            importId={selectedImport.id}
            isFinalized={selectedImport.status === 'finalized'}
            pending={pending}
            roomId={roomId}
            setChunkViewer={setChunkViewer}
            setPending={setPending}
            sources={sources}
            token={token}
            onError={setError}
            onOpenChunk={handleOpenChunk}
            onSourceAdded={() => reloadSelectedImport(selectedImport.id)}
          />

          <AdventureImportReviewSection
            key={`review-${selectedImport.id}`}
            canAuthor={canAuthor}
            copy={copy}
            draft={draft}
            editorCopy={editorCopy}
            importId={selectedImport.id}
            isFinalized={selectedImport.status === 'finalized'}
            pending={pending}
            roomId={roomId}
            selectedImport={selectedImport}
            setPending={setPending}
            setStaleError={setStaleError}
            staleError={staleError}
            token={token}
            onDraftUpdated={(updatedDraft) => setDraft(updatedDraft)}
            onError={setError}
            onFinalized={handleFinalizedSuccess}
            onImportReload={() => reloadSelectedImport(selectedImport.id)}
            onViewSource={handleViewSource}
          />
        </>
      ) : null}
    </section>
  )
}
