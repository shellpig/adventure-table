import { useEffect, useState } from 'react'

import {
  addJsonSource,
  addSourceFromAsset,
  uploadRawSource,
  type AdventureImportSource,
  type SourceChunk,
} from '../../api/adventureImports'
import { listRoomAssets, type RoomAsset } from '../../api/roomAssets'
import { FilePicker } from '../../components/FilePicker'
import {
  formatWhitelistedMetadata,
  normalizeSourceFile,
  computeChunkPagination,
  CHUNK_LIMIT,
} from './adventureImportHelpers'
import {
  importerErrorMessage,
  sourceKindLabel,
  type AdventureImporterCopy,
} from './adventureImporterCopy'

export function WhitelistedSourceMetadata({
  metadata,
  copy,
}: {
  metadata: Record<string, unknown>
  copy: AdventureImporterCopy
}) {
  const items = formatWhitelistedMetadata(metadata, copy)
  if (items.length === 0) return null

  return (
    <div className="importer-meta-row">
      {items.map((item) => (
        <span key={item.label}>
          <strong>{item.label}:</strong> {item.value}
        </span>
      ))}
    </div>
  )
}

export type AdventureImportSourceSectionProps = {
  roomId: string
  token: string
  importId: string
  sources: AdventureImportSource[]
  canAuthor: boolean
  isFinalized: boolean
  pending: boolean
  copy: AdventureImporterCopy
  chunkViewer: {
    sourceId: string
    chunk: SourceChunk | null
    offset: number
    loading: boolean
  } | null
  setChunkViewer: (
    viewer: {
      sourceId: string
      chunk: SourceChunk | null
      offset: number
      loading: boolean
    } | null,
  ) => void
  onOpenChunk: (sourceId: string, offset?: number) => Promise<void>
  onSourceAdded: () => Promise<void>
  onError: (err: string) => void
  setPending: (pending: boolean) => void
}

export function AdventureImportSourceSection({
  roomId,
  token,
  importId,
  sources,
  canAuthor,
  isFinalized,
  pending,
  copy,
  chunkViewer,
  setChunkViewer,
  onOpenChunk,
  onSourceAdded,
  onError,
  setPending,
}: AdventureImportSourceSectionProps) {
  // Source input tab state: 'paste' | 'upload' | 'asset' | 'url'
  const [activeSourceTab, setActiveSourceTab] = useState<'paste' | 'upload' | 'asset' | 'url'>('paste')
  const [pasteText, setPasteText] = useState('')
  const [pasteFilename, setPasteFilename] = useState('')
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [fileInputKey, setFileInputKey] = useState(0)
  const [roomAssets, setRoomAssets] = useState<RoomAsset[]>([])
  const [selectedAssetId, setSelectedAssetId] = useState('')
  const [urlInput, setUrlInput] = useState('')
  const [urlContent, setUrlContent] = useState('')
  const [urlTitle, setUrlTitle] = useState('')

  // When switching to asset tab, load Room source_document assets
  useEffect(() => {
    if (activeSourceTab !== 'asset' || !canAuthor || isFinalized) return
    let active = true
    void listRoomAssets(roomId, token, 'source_document')
      .then((assets) => {
        if (!active) return
        setRoomAssets(assets)
        if (assets.length > 0 && !selectedAssetId) {
          setSelectedAssetId(assets[0].id)
        }
      })
      .catch((cause) => {
        if (active) onError(importerErrorMessage(cause, copy))
      })
    return () => {
      active = false
    }
  }, [activeSourceTab, canAuthor, copy, isFinalized, onError, roomId, selectedAssetId, token])

  const handleAddPasteSource = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!importId || !canAuthor || isFinalized) return
    const text = pasteText.trim()
    if (!text) return
    setPending(true)
    try {
      await addJsonSource(roomId, importId, token, {
        source_kind: 'paste',
        text,
        filename: pasteFilename.trim() || undefined,
      })
      setPasteText('')
      setPasteFilename('')
      await onSourceAdded()
    } catch (cause) {
      onError(importerErrorMessage(cause, copy))
    } finally {
      setPending(false)
    }
  }

  const handleUploadSource = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!importId || !uploadFile || !canAuthor || isFinalized) return
    const normalized = normalizeSourceFile(uploadFile)
    if (!normalized) {
      onError(copy.errUnsupportedFileType)
      return
    }
    setPending(true)
    try {
      await uploadRawSource(roomId, importId, token, {
        source_kind: normalized.sourceKind,
        filename: normalized.filename,
        file: normalized.normalizedFile,
      })
      setUploadFile(null)
      setFileInputKey((k) => k + 1)
      await onSourceAdded()
    } catch (cause) {
      onError(importerErrorMessage(cause, copy))
    } finally {
      setPending(false)
    }
  }

  const handleAddFromAsset = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!importId || !selectedAssetId || !canAuthor || isFinalized) return
    setPending(true)
    try {
      await addSourceFromAsset(roomId, importId, token, { asset_id: selectedAssetId })
      await onSourceAdded()
    } catch (cause) {
      onError(importerErrorMessage(cause, copy))
    } finally {
      setPending(false)
    }
  }

  const handleAddUrlSource = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!importId || !canAuthor || isFinalized) return
    const url = urlInput.trim()
    if (!url) return
    setPending(true)
    try {
      await addJsonSource(roomId, importId, token, {
        source_kind: 'url',
        url,
        text: urlContent.trim() || undefined,
        title: urlTitle.trim() || undefined,
      })
      setUrlInput('')
      setUrlContent('')
      setUrlTitle('')
      await onSourceAdded()
    } catch (cause) {
      onError(importerErrorMessage(cause, copy))
    } finally {
      setPending(false)
    }
  }

  return (
    <div className="importer-section" data-testid="importer-source-section">
      <h3>{copy.sourcesTitle}</h3>

      {/* Source Input Tabs (DM/author only, when not finalized) */}
      {canAuthor && !isFinalized ? (
        <>
          <div className="importer-tabs">
            <button
              className={`button ${activeSourceTab === 'paste' ? 'primary' : 'secondary'}`}
              type="button"
              onClick={() => setActiveSourceTab('paste')}
            >
              {copy.sourceTabPaste}
            </button>
            <button
              className={`button ${activeSourceTab === 'upload' ? 'primary' : 'secondary'}`}
              type="button"
              onClick={() => setActiveSourceTab('upload')}
            >
              {copy.sourceTabUpload}
            </button>
            <button
              className={`button ${activeSourceTab === 'asset' ? 'primary' : 'secondary'}`}
              type="button"
              onClick={() => setActiveSourceTab('asset')}
            >
              {copy.sourceTabAsset}
            </button>
            <button
              className={`button ${activeSourceTab === 'url' ? 'primary' : 'secondary'}`}
              type="button"
              onClick={() => setActiveSourceTab('url')}
            >
              {copy.sourceTabUrl}
            </button>
          </div>

          {/* Paste Text Form */}
          {activeSourceTab === 'paste' ? (
            <form className="room-form" onSubmit={handleAddPasteSource}>
              <label className="room-field">
                <span>{copy.pasteFilenameLabel}</span>
                <input
                  disabled={pending}
                  type="text"
                  value={pasteFilename}
                  onChange={(e) => setPasteFilename(e.target.value)}
                />
              </label>
              <label className="room-field">
                <span>{copy.pasteTextLabel}</span>
                <textarea
                  disabled={pending}
                  required
                  value={pasteText}
                  onChange={(e) => setPasteText(e.target.value)}
                />
              </label>
              <button
                className="button primary room-form-submit"
                disabled={pending || !pasteText.trim()}
                type="submit"
              >
                {copy.addSourceAction}
              </button>
            </form>
          ) : null}

          {/* Upload File Form */}
          {activeSourceTab === 'upload' ? (
            <form className="room-form" onSubmit={handleUploadSource}>
              <label className="room-field">
                <span>{copy.uploadFileLabel}</span>
                <FilePicker
                  accept=".txt,.md,.markdown,.pdf,.docx"
                  disabled={pending}
                  key={fileInputKey}
                  onFileChange={setUploadFile}
                />
              </label>
              <button
                className="button primary room-form-submit"
                disabled={pending || !uploadFile}
                type="submit"
              >
                {copy.uploadAction}
              </button>
            </form>
          ) : null}

          {/* From Room Asset Form */}
          {activeSourceTab === 'asset' ? (
            <form className="room-form" onSubmit={handleAddFromAsset}>
              {roomAssets.length === 0 ? (
                <p className="room-empty-text">{copy.noAssetsAvailable}</p>
              ) : (
                <>
                  <label className="room-field">
                    <span>{copy.selectAssetLabel}</span>
                    <select
                      disabled={pending}
                      value={selectedAssetId}
                      onChange={(e) => setSelectedAssetId(e.target.value)}
                    >
                      {roomAssets.map((asset) => (
                        <option key={asset.id} value={asset.id}>
                          {asset.original_filename} ({asset.size_bytes} bytes)
                        </option>
                      ))}
                    </select>
                  </label>
                  <button
                    className="button primary room-form-submit"
                    disabled={pending || !selectedAssetId}
                    type="submit"
                  >
                    {copy.addSourceAction}
                  </button>
                </>
              )}
            </form>
          ) : null}

          {/* URL Source Form */}
          {activeSourceTab === 'url' ? (
            <form className="room-form" onSubmit={handleAddUrlSource}>
              <label className="room-field">
                <span>{copy.urlLabel}</span>
                <input
                  disabled={pending}
                  placeholder="https://..."
                  required
                  type="url"
                  value={urlInput}
                  onChange={(e) => setUrlInput(e.target.value)}
                />
              </label>
              <label className="room-field">
                <span>{copy.urlTitleLabel}</span>
                <input
                  disabled={pending}
                  type="text"
                  value={urlTitle}
                  onChange={(e) => setUrlTitle(e.target.value)}
                />
              </label>
              <label className="room-field">
                <span>{copy.urlContentLabel}</span>
                <textarea
                  disabled={pending}
                  value={urlContent}
                  onChange={(e) => setUrlContent(e.target.value)}
                />
              </label>
              <button
                className="button primary room-form-submit"
                disabled={pending || !urlInput.trim()}
                type="submit"
              >
                {copy.addSourceAction}
              </button>
            </form>
          ) : null}
        </>
      ) : null}

      {/* Source List Display */}
      {sources.length === 0 ? (
        <p className="room-empty-text">{copy.emptySources}</p>
      ) : (
        <div className="importer-card-grid" style={{ marginTop: '16px' }}>
          {sources.map((src) => {
            const filename =
              (src.metadata_json?.filename as string | undefined) ??
              (src.metadata_json?.original_filename as string | undefined) ??
              null
            return (
              <div className="importer-item-card" key={src.id}>
                <div>
                  <strong>{sourceKindLabel(src.source_kind, copy)}</strong>
                  {filename ? <p style={{ margin: '4px 0' }}>{filename}</p> : null}
                  {src.source_url ? (
                    <p style={{ margin: '4px 0', wordBreak: 'break-all' }}>{src.source_url}</p>
                  ) : null}
                  <div className="importer-meta-row">
                    <span>
                      {copy.textLengthLabel}: {src.text_length}
                    </span>
                  </div>
                  <WhitelistedSourceMetadata copy={copy} metadata={src.metadata_json} />
                </div>
                <div className="adventure-card__actions">
                  <button
                    className="button secondary"
                    disabled={pending}
                    type="button"
                    onClick={() => onOpenChunk(src.id, 0)}
                  >
                    {copy.viewTextAction}
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Bounded Chunk Viewer */}
      {chunkViewer ? (
        <div className="importer-chunk-viewer" data-testid="importer-chunk-viewer">
          <div className="importer-chunk-nav">
            <span>
              {copy.chunkOffsetLabel}: {chunkViewer.offset} / {copy.chunkTotalLabel}:{' '}
              {chunkViewer.chunk?.total_length ?? 0}
            </span>
            <button
              className="button secondary"
              type="button"
              onClick={() => setChunkViewer(null)}
            >
              {copy.closeChunkView}
            </button>
          </div>

          {chunkViewer.loading ? (
            <p>{copy.loadingChunk}</p>
          ) : (
            <pre>{chunkViewer.chunk?.text ?? ''}</pre>
          )}

          {chunkViewer.chunk ? (
            (() => {
              const pagination = computeChunkPagination(
                chunkViewer.offset,
                CHUNK_LIMIT,
                chunkViewer.chunk.total_length,
                chunkViewer.chunk.next_offset,
              )
              return (
                <div className="importer-chunk-nav">
                  <button
                    className="button secondary"
                    disabled={!pagination.hasPrev || chunkViewer.loading}
                    type="button"
                    onClick={() => onOpenChunk(chunkViewer.sourceId, pagination.prevOffset)}
                  >
                    {copy.prevChunk}
                  </button>
                  <button
                    className="button secondary"
                    disabled={!pagination.hasNext || chunkViewer.loading}
                    type="button"
                    onClick={() =>
                      pagination.nextOffset !== null &&
                      onOpenChunk(chunkViewer.sourceId, pagination.nextOffset)
                    }
                  >
                    {copy.nextChunk}
                  </button>
                </div>
              )
            })()
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
