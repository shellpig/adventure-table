import { useEffect, useState } from 'react'

import {
  addJsonSource,
  addSourceFromAsset,
  AdventureImportApiError,
  createAdventureImport,
  getAdventureImportDraft,
  listAdventureImports,
  listAdventureImportSources,
  readSourceChunk,
  updateAdventureImportDraft,
  uploadRawSource,
  type AdventureImport,
  type AdventureImportDraft,
  type AdventureImportSource,
  type DraftEntry,
  type DraftEntryInput,
  type DraftQuestionInput,
  type DraftWarningInput,
  type SourceChunk,
  type SourceKind,
  type UpdateImportDraftInput,
} from '../../api/adventureImports'
import type {
  AdventureEntryKind,
  AdventureEntryPayload,
} from '../../api/adventures'
import { listRoomAssets, type RoomAsset } from '../../api/roomAssets'
import { useLocale } from '../../i18n/LocaleProvider'
import {
  AdventureEntryPayloadFields,
  ENTRY_KIND_FIELDS,
  entryFieldsFromPayload,
  entryPayloadFromForm,
  entryKindLabel,
  fieldLabel,
} from './AdventureEntryPayloadFields'
import {
  adventureImporterCopy,
  draftProvenanceLabel,
  importerErrorMessage,
  importStatusLabel,
  sourceKindLabel,
  type AdventureImporterCopy,
} from './adventureImporterCopy'
import { adventuresCopy } from './adventuresCopy'
import './rooms.css'

const CHUNK_LIMIT = 5000

export type ChunkPagination = {
  hasPrev: boolean
  hasNext: boolean
  prevOffset: number
  nextOffset: number | null
}

export function computeChunkPagination(
  offset: number,
  limit: number,
  totalLength: number,
  nextOffset: number | null,
): ChunkPagination {
  return {
    hasPrev: offset > 0,
    hasNext: nextOffset !== null && nextOffset < totalLength,
    prevOffset: Math.max(0, offset - limit),
    nextOffset,
  }
}

export function inferSourceKindFromFilename(
  filename: string,
): 'txt' | 'markdown' | 'pdf' | 'docx' | null {
  const lower = filename.toLowerCase()
  if (lower.endsWith('.txt')) return 'txt'
  if (lower.endsWith('.md') || lower.endsWith('.markdown')) return 'markdown'
  if (lower.endsWith('.pdf')) return 'pdf'
  if (lower.endsWith('.docx')) return 'docx'
  return null
}

export const EXPECTED_MIME_TYPES: Record<'txt' | 'markdown' | 'pdf' | 'docx', string> = {
  txt: 'text/plain',
  markdown: 'text/markdown',
  pdf: 'application/pdf',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
}

export type NormalizedSourceFileInput = {
  sourceKind: 'txt' | 'markdown' | 'pdf' | 'docx'
  normalizedFile: Blob
  filename: string
}

export function normalizeSourceFile(file: File): NormalizedSourceFileInput | null {
  const kind = inferSourceKindFromFilename(file.name)
  if (!kind) return null
  const expectedMime = EXPECTED_MIME_TYPES[kind]
  const normalizedBlob =
    file.type === expectedMime ? file : new Blob([file], { type: expectedMime })
  return {
    sourceKind: kind,
    normalizedFile: normalizedBlob,
    filename: file.name,
  }
}

export type DraftMutationAction =
  | {
      type: 'add'
      entry: {
        entry_kind: AdventureEntryKind
        payload: AdventureEntryPayload
        parent_entry_id: string | null
        note: string | null
      }
      entryId?: string
    }
  | {
      type: 'edit'
      entryId: string
      entry: {
        entry_kind: AdventureEntryKind
        payload: AdventureEntryPayload
        parent_entry_id: string | null
        note: string | null
      }
    }
  | {
      type: 'delete'
      entryId: string
    }

export type ExactUpdateImportDraftInput = {
  expected_revision: number
  warnings: DraftWarningInput[]
  draft: {
    schema_version: 1
    questions: DraftQuestionInput[]
    entries: DraftEntryInput[]
  }
}

export function buildDraftMutationInput(
  currentDraft: AdventureImportDraft,
  action: DraftMutationAction,
): ExactUpdateImportDraftInput {
  let nextEntries: DraftEntry[]

  if (action.type === 'add') {
    const newEntry: DraftEntry = {
      entry_id: action.entryId ?? crypto.randomUUID(),
      entry_kind: action.entry.entry_kind,
      payload: action.entry.payload,
      parent_entry_id: action.entry.parent_entry_id,
      provenance: 'user_explicit',
      source_ref: null,
      note: action.entry.note,
    }
    nextEntries = [...currentDraft.draft.entries, newEntry]
  } else if (action.type === 'edit') {
    nextEntries = currentDraft.draft.entries.map((item) =>
      item.entry_id === action.entryId
        ? {
            ...item,
            entry_kind: action.entry.entry_kind,
            payload: action.entry.payload,
            parent_entry_id: action.entry.parent_entry_id,
            note: action.entry.note,
          }
        : item,
    )
  } else {
    nextEntries = currentDraft.draft.entries.filter((item) => item.entry_id !== action.entryId)
  }

  return {
    expected_revision: currentDraft.revision,
    warnings: currentDraft.warnings.map((w) => ({
      warning_id: w.warning_id,
      level: w.level,
      code: w.code,
      message: w.message,
      entry_id: w.entry_id,
      source_id: w.source_id,
    })),
    draft: {
      schema_version: 1,
      questions: currentDraft.draft.questions.map((q) => ({
        question_id: q.question_id,
        message: q.message,
        entry_id: q.entry_id,
        answer: q.answer,
      })),
      entries: nextEntries.map((e) => ({
        entry_id: e.entry_id,
        entry_kind: e.entry_kind,
        payload: e.payload,
        parent_entry_id: e.parent_entry_id,
        provenance: e.provenance,
        source_ref: e.source_ref
          ? {
              source_id: e.source_ref.source_id,
              locator: e.source_ref.locator,
            }
          : null,
        note: e.note,
      })),
    },
  }
}

export function formatWhitelistedMetadata(
  metadata: Record<string, unknown>,
  copy: AdventureImporterCopy,
): { label: string; value: string }[] {
  const items: { label: string; value: string }[] = []

  if (typeof metadata.title === 'string' && metadata.title.trim()) {
    items.push({ label: copy.metaTitle, value: metadata.title.trim() })
  }
  if (typeof metadata.page_count === 'number') {
    items.push({ label: copy.metaPageCount, value: String(metadata.page_count) })
  }
  if (typeof metadata.line_count === 'number') {
    items.push({ label: copy.metaLineCount, value: String(metadata.line_count) })
  }
  if (typeof metadata.char_count === 'number') {
    items.push({ label: copy.metaCharCount, value: String(metadata.char_count) })
  }
  const byteSize =
    typeof metadata.byte_size === 'number'
      ? metadata.byte_size
      : typeof metadata.byte_count === 'number'
        ? metadata.byte_count
        : null
  if (byteSize !== null) {
    items.push({ label: copy.metaByteCount, value: String(byteSize) })
  }
  if (typeof metadata.media_type === 'string' && metadata.media_type.trim()) {
    items.push({ label: copy.metaMediaType, value: metadata.media_type.trim() })
  }
  if (typeof metadata.content_provided === 'boolean') {
    items.push({
      label: copy.metaContentProvided,
      value: metadata.content_provided ? copy.metaYes : copy.metaNo,
    })
  }
  return items
}

function WhitelistedSourceMetadata({
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

function DraftPayloadSummary({
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

export type AdventureImporterPanelProps = {
  roomId: string
  token: string
}

export function AdventureImporterPanel({ roomId, token }: AdventureImporterPanelProps) {
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

  // Chunk viewer state
  const [chunkViewer, setChunkViewer] = useState<{
    sourceId: string
    chunk: SourceChunk | null
    offset: number
    loading: boolean
  } | null>(null)

  // Draft entry form state
  const [editMode, setEditMode] = useState<
    { kind: 'create' } | { kind: 'edit'; entry: DraftEntry }
  >({ kind: 'create' })
  const [entryForm, setEntryForm] = useState<DraftEntryFormState>(initialDraftEntryFormState('scene'))

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
    let active = true
    setSources([])
    setDraft(null)
    setChunkViewer(null)
    setEditMode({ kind: 'create' })
    setEntryForm(initialDraftEntryFormState('scene'))
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
  }, [roomId, token])

  // When selectedImportId changes, reload sources and draft
  useEffect(() => {
    if (!selectedImportId) {
      setSources([])
      setDraft(null)
      setChunkViewer(null)
      setEditMode({ kind: 'create' })
      setEntryForm(initialDraftEntryFormState('scene'))
      return
    }
    void reloadSelectedImport(selectedImportId)
  }, [selectedImportId, roomId, token])

  // When switching to asset tab, load Room source_document assets
  useEffect(() => {
    if (activeSourceTab !== 'asset') return
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
        if (active) setError(importerErrorMessage(cause, copy))
      })
    return () => {
      active = false
    }
  }, [activeSourceTab, roomId, token])

  const handleCreateImport = async (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = newImportName.trim()
    if (!trimmed) return
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

  const handleAddPasteSource = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedImportId) return
    const text = pasteText.trim()
    if (!text) return
    setPending(true)
    setError(null)
    try {
      await addJsonSource(roomId, selectedImportId, token, {
        source_kind: 'paste',
        text,
        filename: pasteFilename.trim() || undefined,
      })
      setPasteText('')
      setPasteFilename('')
      await reloadSelectedImport(selectedImportId)
    } catch (cause) {
      setError(importerErrorMessage(cause, copy))
    } finally {
      setPending(false)
    }
  }

  const handleUploadSource = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedImportId || !uploadFile) return
    const normalized = normalizeSourceFile(uploadFile)
    if (!normalized) {
      setError(copy.errUnsupportedFileType)
      return
    }
    setPending(true)
    setError(null)
    try {
      await uploadRawSource(roomId, selectedImportId, token, {
        source_kind: normalized.sourceKind,
        filename: normalized.filename,
        file: normalized.normalizedFile,
      })
      setUploadFile(null)
      setFileInputKey((k) => k + 1)
      await reloadSelectedImport(selectedImportId)
    } catch (cause) {
      setError(importerErrorMessage(cause, copy))
    } finally {
      setPending(false)
    }
  }

  const handleAddFromAsset = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedImportId || !selectedAssetId) return
    setPending(true)
    setError(null)
    try {
      await addSourceFromAsset(roomId, selectedImportId, token, { asset_id: selectedAssetId })
      await reloadSelectedImport(selectedImportId)
    } catch (cause) {
      setError(importerErrorMessage(cause, copy))
    } finally {
      setPending(false)
    }
  }

  const handleAddUrlSource = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedImportId) return
    const url = urlInput.trim()
    if (!url) return
    setPending(true)
    setError(null)
    try {
      await addJsonSource(roomId, selectedImportId, token, {
        source_kind: 'url',
        url,
        text: urlContent.trim() || undefined,
        title: urlTitle.trim() || undefined,
      })
      setUrlInput('')
      setUrlContent('')
      setUrlTitle('')
      await reloadSelectedImport(selectedImportId)
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

  const handleSaveDraftEntry = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedImportId || !draft) return
    setPending(true)
    setError(null)
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
              },
            }

      const input = buildDraftMutationInput(draft, action)
      const updatedDraft = await updateAdventureImportDraft(roomId, selectedImportId, token, input)

      setDraft(updatedDraft)
      setEditMode({ kind: 'create' })
      setEntryForm(initialDraftEntryFormState(entryForm.entryKind))
      await reloadImportList()
    } catch (cause) {
      if (
        cause instanceof AdventureImportApiError &&
        cause.code === 'adventure_import_revision_conflict'
      ) {
        setStaleError(true)
        setError(copy.staleDraftConflict)
      } else {
        setError(importerErrorMessage(cause, copy))
      }
    } finally {
      setPending(false)
    }
  }

  const handleDeleteDraftEntry = async (entryId: string) => {
    if (!selectedImportId || !draft) return
    if (!window.confirm(copy.deleteEntryConfirm)) return
    setPending(true)
    setError(null)
    setStaleError(false)

    try {
      const input = buildDraftMutationInput(draft, { type: 'delete', entryId })
      const updatedDraft = await updateAdventureImportDraft(roomId, selectedImportId, token, input)

      setDraft(updatedDraft)
      if (editMode.kind === 'edit' && editMode.entry.entry_id === entryId) {
        setEditMode({ kind: 'create' })
        setEntryForm(initialDraftEntryFormState(entryForm.entryKind))
      }
      await reloadImportList()
    } catch (cause) {
      if (
        cause instanceof AdventureImportApiError &&
        cause.code === 'adventure_import_revision_conflict'
      ) {
        setStaleError(true)
        setError(copy.staleDraftConflict)
      } else {
        setError(importerErrorMessage(cause, copy))
      }
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

      {/* Selected Import Content: Sources and Draft */}
      {selectedImport && selectedImport.status !== 'cancelled' ? (
        <>
          {/* 3. Source Management Area */}
          <div className="importer-section">
            <h3>{copy.sourcesTitle}</h3>

            {/* Source Input Tabs */}
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

            {/* 3.1 Paste Text Form */}
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

            {/* 3.2 Upload File Form */}
            {activeSourceTab === 'upload' ? (
              <form className="room-form" onSubmit={handleUploadSource}>
                <label className="room-field">
                  <span>{copy.uploadFileLabel}</span>
                  <input
                    accept=".txt,.md,.markdown,.pdf,.docx"
                    disabled={pending}
                    key={fileInputKey}
                    required
                    type="file"
                    onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)}
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

            {/* 3.3 From Room Asset Form */}
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

            {/* 3.4 URL Source Form */}
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
                          onClick={() => handleOpenChunk(src.id, 0)}
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
              <div className="importer-chunk-viewer">
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
                          onClick={() => handleOpenChunk(chunkViewer.sourceId, pagination.prevOffset)}
                        >
                          {copy.prevChunk}
                        </button>
                        <button
                          className="button secondary"
                          disabled={!pagination.hasNext || chunkViewer.loading}
                          type="button"
                          onClick={() =>
                            pagination.nextOffset !== null &&
                            handleOpenChunk(chunkViewer.sourceId, pagination.nextOffset)
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

          {/* 4. Draft Area */}
          {draft ? (
            <div className="importer-section">
              <h3>{copy.draftTitle}</h3>
              <div className="importer-meta-row">
                <span>
                  {copy.draftRevisionLabel}: {draft.revision}
                </span>
                {staleError ? (
                  <button
                    className="button primary"
                    type="button"
                    onClick={() => reloadSelectedImport(selectedImport.id)}
                  >
                    {copy.reloadDraftAction}
                  </button>
                ) : null}
              </div>

              {/* Warnings List (plain list, no severity/review buttons) */}
              <div className="importer-warnings">
                <h4>{copy.warningsTitle}</h4>
                {draft.warnings.length === 0 ? (
                  <p className="room-card-hint">{copy.noWarnings}</p>
                ) : (
                  <ul className="importer-warnings-list">
                    {draft.warnings.map((w) => (
                      <li key={w.warning_id}>{w.message}</li>
                    ))}
                  </ul>
                )}
              </div>

              {/* Draft Entries List */}
              <div style={{ marginTop: '16px' }}>
                <h4>{copy.draftEntriesTitle}</h4>
                {draft.draft.entries.length === 0 ? (
                  <p className="room-empty-text">{copy.emptyDraftEntries}</p>
                ) : (
                  <div className="adventure-entry-list">
                    {draft.draft.entries.map((entry) => (
                      <article className="adventure-entry" key={entry.entry_id}>
                        <div className="adventure-entry__content">
                          <div className="adventure-entry__meta">
                            <span className="adventure-entry__kind">
                              {entryKindLabel(entry.entry_kind, editorCopy)}
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
                        </div>
                      </article>
                    ))}
                  </div>
                )}
              </div>

              {/* Draft Entry Add / Edit Form */}
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
            </div>
          ) : null}
        </>
      ) : null}
    </section>
  )
}
