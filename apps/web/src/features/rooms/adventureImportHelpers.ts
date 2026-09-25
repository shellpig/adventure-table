import type {
  AdventureImportDraft,
  DraftEntryInput,
  DraftProvenance,
  DraftQuestionInput,
  DraftSourceRef,
  DraftWarningInput,
  ReviewStatus,
} from '../../api/adventureImports'
import type {
  AdventureEntryKind,
  AdventureEntryPayload,
  AdventureEntryVisibility,
} from '../../api/adventures'
import type { AdventureImporterCopy } from './adventureImporterCopy'

export const CHUNK_LIMIT = 5000

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
        provenance?: DraftProvenance
        review_status?: ReviewStatus
        asset_ids?: string[]
        title?: string | null
        body?: string | null
        visibility?: AdventureEntryVisibility
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
        provenance?: DraftProvenance
        review_status?: ReviewStatus
        asset_ids?: string[]
        title?: string | null
        body?: string | null
        visibility?: AdventureEntryVisibility
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
  let nextEntries: DraftEntryInput[]

  if (action.type === 'add') {
    const newEntry: DraftEntryInput = {
      entry_id: action.entryId ?? crypto.randomUUID(),
      entry_kind: action.entry.entry_kind,
      payload: action.entry.payload,
      parent_entry_id: action.entry.parent_entry_id,
      provenance: action.entry.provenance ?? 'user_explicit',
      source_ref: null,
      note: action.entry.note,
      review_status: action.entry.review_status ?? 'pending',
      asset_ids: action.entry.asset_ids ?? [],
      title: action.entry.title ?? null,
      body: action.entry.body ?? null,
      visibility: action.entry.visibility ?? 'dm_only',
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
            provenance: action.entry.provenance ?? item.provenance,
            review_status: action.entry.review_status ?? item.review_status,
            asset_ids: action.entry.asset_ids ?? item.asset_ids,
            title: action.entry.title !== undefined ? action.entry.title : item.title,
            body: action.entry.body !== undefined ? action.entry.body : item.body,
            visibility: action.entry.visibility ?? item.visibility,
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
      resolved: w.resolved,
      resolution: w.resolution,
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
        review_status: e.review_status,
        asset_ids: e.asset_ids,
        title: e.title,
        body: e.body,
        visibility: e.visibility,
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

export function parseSourceLocatorOffset(
  sourceRef: DraftSourceRef,
  metadata: Record<string, unknown>,
): number {
  const locator = sourceRef.locator?.trim().toLowerCase()
  const match = locator?.match(/^(offset|page|page_index|paragraph|paragraph_index|heading_index):(\d+)$/)
  if (!match) return 0
  const index = Number(match[2])
  if (match[1] === 'offset') return index

  const key = match[1].replace(/^(page|paragraph)$/, '$1_index')
  const sectionIndex = match[1] === 'page' || match[1] === 'paragraph' ? index - 1 : index
  const sections = metadata.sections
  if (!Array.isArray(sections)) return 0
  const section = sections.find(
    (item) => typeof item === 'object' && item !== null && item[key] === sectionIndex,
  )
  return typeof section?.start_offset === 'number' ? section.start_offset : 0
}
