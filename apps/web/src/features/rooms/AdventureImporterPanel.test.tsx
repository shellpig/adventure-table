import { describe, expect, it } from 'vitest'

import {
  AdventureImportApiError,
  type AdventureImport,
  type AdventureImportDraft,
  type DraftProvenance,
  type ImportStatus,
  type SourceKind,
} from '../../api/adventureImports'
import {
  buildDraftMutationInput,
  computeChunkPagination,
  formatWhitelistedMetadata,
  inferSourceKindFromFilename,
  normalizeSourceFile,
} from './AdventureImporterPanel'
import {
  ENTRY_KIND_FIELDS,
  entryKindLabel,
} from './AdventureEntryPayloadFields'
import {
  adventureImporterCopy,
  draftProvenanceLabel,
  importerErrorMessage,
  importStatusLabel,
  sourceKindLabel,
} from './adventureImporterCopy'
import { adventuresCopy } from './adventuresCopy'
import { adventurePermissions } from './RoomAdventuresPage'

describe('Adventure Importer Panel & Helper tests', () => {
  it('proves add, edit, and delete draft mutations preserve warnings, questions, id/provenance/source_ref, and do not mutate import revision', () => {
    const sampleImport: AdventureImport = {
      id: 'imp-1',
      room_id: 'room-1',
      name: 'Tomb Import',
      status: 'drafting',
      target_adventure_id: null,
      revision: 2,
      created_at: '2026-09-22T00:00:00Z',
      updated_at: '2026-09-22T00:00:00Z',
    }

    const sampleDraft: AdventureImportDraft = {
      import_id: 'imp-1',
      revision: 5,
      updated_at: '2026-09-22T00:00:00Z',
      warnings: [
        {
          warning_id: 'w1',
          level: 'warning',
          code: 'url_no_content',
          message: 'URL has no content',
          entry_id: null,
          source_id: 's1',
        },
      ],
      draft: {
        schema_version: 1,
        questions: [
          {
            question_id: 'q1',
            message: 'What is the DC?',
            entry_id: 'e1',
            answer: null,
          },
        ],
        entries: [
          {
            entry_id: 'e1',
            entry_kind: 'scene',
            payload: { kind: 'scene', dm_summary: 'Hall' },
            parent_entry_id: null,
            provenance: 'source_document',
            source_ref: { source_id: 's1', locator: 'p.1' },
            note: 'original note',
          },
          {
            entry_id: 'e2',
            entry_kind: 'section',
            payload: { kind: 'section' },
            parent_entry_id: null,
            provenance: 'user_explicit',
            source_ref: null,
            note: null,
          },
        ],
      },
    }

    // 1. ADD mutation
    const addInput = buildDraftMutationInput(sampleDraft, {
      type: 'add',
      entryId: 'e3',
      entry: {
        entry_kind: 'npc',
        payload: { kind: 'npc', role: 'Guard', disposition: 'neutral' },
        parent_entry_id: null,
        note: 'new note',
      },
    })
    expect(addInput.expected_revision).toBe(5)
    expect(addInput.warnings).toEqual([
      expect.objectContaining({ warning_id: 'w1', message: 'URL has no content' }),
    ])
    expect(addInput.draft.questions).toEqual([
      expect.objectContaining({ question_id: 'q1', message: 'What is the DC?' }),
    ])
    expect(addInput.draft.entries).toHaveLength(3)
    expect(addInput.draft.entries[0]).toEqual(
      expect.objectContaining({
        entry_id: 'e1',
        provenance: 'source_document',
        source_ref: { source_id: 's1', locator: 'p.1' },
      }),
    )
    expect(addInput.draft.entries[2]).toEqual({
      entry_id: 'e3',
      entry_kind: 'npc',
      payload: { kind: 'npc', role: 'Guard', disposition: 'neutral' },
      parent_entry_id: null,
      provenance: 'user_explicit',
      source_ref: null,
      note: 'new note',
    })

    // 2. EDIT mutation
    const editInput = buildDraftMutationInput(sampleDraft, {
      type: 'edit',
      entryId: 'e1',
      entry: {
        entry_kind: 'scene',
        payload: { kind: 'scene', dm_summary: 'Updated Hall' },
        parent_entry_id: 'e2',
        note: 'edited note',
      },
    })
    expect(editInput.expected_revision).toBe(5)
    expect(editInput.warnings).toHaveLength(1)
    expect(editInput.draft.questions).toHaveLength(1)
    expect(editInput.draft.entries).toHaveLength(2)
    expect(editInput.draft.entries[0]).toEqual({
      entry_id: 'e1',
      entry_kind: 'scene',
      payload: { kind: 'scene', dm_summary: 'Updated Hall' },
      parent_entry_id: 'e2',
      provenance: 'source_document', // preserved!
      source_ref: { source_id: 's1', locator: 'p.1' }, // preserved!
      note: 'edited note',
    })
    expect(editInput.draft.entries[1]).toEqual(
      expect.objectContaining({ entry_id: 'e2', entry_kind: 'section' }),
    )

    // 3. DELETE mutation
    const deleteInput = buildDraftMutationInput(sampleDraft, {
      type: 'delete',
      entryId: 'e1',
    })
    expect(deleteInput.expected_revision).toBe(5)
    expect(deleteInput.warnings).toHaveLength(1)
    expect(deleteInput.draft.questions).toHaveLength(1)
    expect(deleteInput.draft.entries).toHaveLength(1)
    expect(deleteInput.draft.entries[0].entry_id).toBe('e2')

    // 4. Assert no draft helper mutated AdventureImport.revision
    expect(sampleImport.revision).toBe(2)
  })

  it('computes chunk pagination and validates/normalizes source files', () => {
    // 1. Pagination table
    const paginationCases = [
      {
        offset: 0,
        limit: 100,
        total: 250,
        nextOffset: 100,
        expected: { hasPrev: false, hasNext: true, prevOffset: 0, nextOffset: 100 },
      },
      {
        offset: 100,
        limit: 100,
        total: 250,
        nextOffset: 200,
        expected: { hasPrev: true, hasNext: true, prevOffset: 0, nextOffset: 200 },
      },
      {
        offset: 200,
        limit: 100,
        total: 250,
        nextOffset: null,
        expected: { hasPrev: true, hasNext: false, prevOffset: 100, nextOffset: null },
      },
      {
        offset: 50,
        limit: 100,
        total: 150,
        nextOffset: 150,
        expected: { hasPrev: true, hasNext: false, prevOffset: 0, nextOffset: 150 },
      },
    ]
    for (const c of paginationCases) {
      expect(computeChunkPagination(c.offset, c.limit, c.total, c.nextOffset)).toEqual(c.expected)
    }

    // 2. Filename extension inference table
    const extensionCases = [
      { filename: 'dungeon.txt', expected: 'txt' },
      { filename: 'chapter.MD', expected: 'markdown' },
      { filename: 'notes.markdown', expected: 'markdown' },
      { filename: 'handout.pdf', expected: 'pdf' },
      { filename: 'script.docx', expected: 'docx' },
      { filename: 'image.png', expected: null },
      { filename: 'tool.exe', expected: null },
    ]
    for (const c of extensionCases) {
      expect(inferSourceKindFromFilename(c.filename)).toBe(c.expected)
    }

    // 3. Normalization
    const pdfFile = new File(['pdf'], 'module.pdf', { type: 'application/pdf' })
    const normalizedPdf = normalizeSourceFile(pdfFile)
    expect(normalizedPdf).not.toBeNull()
    expect(normalizedPdf?.sourceKind).toBe('pdf')
    expect(normalizedPdf?.normalizedFile.type).toBe('application/pdf')

    const txtFile = new File(['text'], 'notes.txt', { type: '' })
    const normalizedTxt = normalizeSourceFile(txtFile)
    expect(normalizedTxt).not.toBeNull()
    expect(normalizedTxt?.sourceKind).toBe('txt')
    expect(normalizedTxt?.normalizedFile.type).toBe('text/plain')

    const exeFile = new File(['binary'], 'run.exe', { type: 'application/octet-stream' })
    expect(normalizeSourceFile(exeFile)).toBeNull()
  })

  it('maintains bilingual copy parity, error mapping, and localized label mappings without P6 or P6-F actions', () => {
    const en = adventureImporterCopy('en')
    const zh = adventureImporterCopy('zh-TW')

    // Key parity
    expect(Object.keys(en).sort()).toEqual(Object.keys(zh).sort())

    // No internal P6 in values
    for (const key of Object.keys(en)) {
      expect(en[key as keyof typeof en]).not.toContain('P6')
      expect(zh[key as keyof typeof zh]).not.toContain('P6')
    }

    // Prohibited P6-F action words check
    const prohibitedWords = ['Accept', 'Ignore', 'Mark uncertain', 'Finalize', '定稿']
    for (const word of prohibitedWords) {
      expect(JSON.stringify(en)).not.toContain(`"${word}"`)
    }
    expect(en).not.toHaveProperty('acceptEntry')
    expect(en).not.toHaveProperty('ignoreEntry')
    expect(en).not.toHaveProperty('markUncertain')
    expect(en).not.toHaveProperty('finalizeImport')

    // Status label mapping
    const statuses: ImportStatus[] = ['source', 'drafting', 'review', 'finalized', 'cancelled']
    for (const s of statuses) {
      expect(importStatusLabel(s, en)).toBeTruthy()
      expect(importStatusLabel(s, zh)).toBeTruthy()
    }

    // Source kind label mapping
    const kinds: SourceKind[] = ['paste', 'txt', 'markdown', 'pdf', 'docx', 'url']
    for (const k of kinds) {
      expect(sourceKindLabel(k, en)).toBeTruthy()
      expect(sourceKindLabel(k, zh)).toBeTruthy()
    }

    // Provenance label mapping
    const provenances: DraftProvenance[] = [
      'source_document',
      'user_explicit',
      'user_approximation',
      'ai_generated',
    ]
    for (const p of provenances) {
      expect(draftProvenanceLabel(p, en)).toBeTruthy()
      expect(draftProvenanceLabel(p, zh)).toBeTruthy()
    }

    // Error message mapping
    const errorCodes = [
      { code: 'adventure_import_not_found', expectedKey: 'errImportNotFound' },
      { code: 'adventure_import_revision_conflict', expectedKey: 'errImportRevisionConflict' },
      { code: 'asset_too_large', expectedKey: 'errAssetTooLarge' },
      { code: 'adventure_import_invalid', expectedKey: 'errInvalidSource' },
      { code: 'adventure_import_authority_required', expectedKey: 'errAuthorityRequired' },
    ]
    for (const ec of errorCodes) {
      const err = new AdventureImportApiError(400, ec.code, 'Error')
      expect(importerErrorMessage(err, en)).toBe(en[ec.expectedKey as keyof typeof en])
      expect(importerErrorMessage(err, zh)).toBe(zh[ec.expectedKey as keyof typeof zh])
    }
    expect(importerErrorMessage(new Error('unknown'), en)).toBe(en.requestFailed)

    // Localized entry-kind labels
    const advEn = adventuresCopy('en')
    const advZh = adventuresCopy('zh-TW')
    for (const kind of Object.keys(ENTRY_KIND_FIELDS) as (keyof typeof ENTRY_KIND_FIELDS)[]) {
      const enLabel = entryKindLabel(kind, advEn)
      const zhLabel = entryKindLabel(kind, advZh)
      expect(enLabel).toBeTruthy()
      expect(zhLabel).toBeTruthy()
      if (kind === 'monster_ref') {
        expect(enLabel).toBe('Monster Reference')
        expect(zhLabel).toBe('怪物參照')
      } else if (kind === 'dm_note') {
        expect(enLabel).toBe('DM Note')
        expect(zhLabel).toBe('DM 筆記')
      }
    }

    // Whitelisted source metadata displays byte_size with localized label
    const metaWithByteSize = {
      byte_size: 2048,
      page_count: 12,
      raw_internal_hash: 'abcdef',
    }
    const enMeta = formatWhitelistedMetadata(metaWithByteSize, en)
    expect(enMeta).toEqual([
      { label: en.metaPageCount, value: '12' },
      { label: en.metaByteCount, value: '2048' },
    ])
    const zhMeta = formatWhitelistedMetadata(metaWithByteSize, zh)
    expect(zhMeta).toEqual([
      { label: zh.metaPageCount, value: '12' },
      { label: zh.metaByteCount, value: '2048' },
    ])
  })

  it('verifies permission guards and component rendering structure', () => {
    // Permission guard check
    expect(adventurePermissions('owner')).toEqual({ canAuthor: true })
    expect(adventurePermissions('dm')).toEqual({ canAuthor: true })
    expect(adventurePermissions('member')).toEqual({ canAuthor: false })
    expect(adventurePermissions(null)).toEqual({ canAuthor: false })
    expect(adventurePermissions(undefined)).toEqual({ canAuthor: false })
  })
})
