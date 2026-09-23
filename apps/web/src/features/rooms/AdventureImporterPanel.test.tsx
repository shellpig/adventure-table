import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

import {
  AdventureImportApiError,
  type AdventureImport,
  type AdventureImportDraft,
  type DraftEntry,
  type DraftProvenance,
  type DraftWarning,
  type ImportStatus,
  type ReviewStatus,
  type SourceKind,
  type WarningLevel,
} from '../../api/adventureImports'
import {
  AdventureImporterPanel,
  buildDraftMutationInput,
  computeChunkPagination,
  formatWhitelistedMetadata,
  inferSourceKindFromFilename,
  normalizeSourceFile,
} from './AdventureImporterPanel'
import { AdventureImportReviewSection } from './AdventureImportReviewSection'
import {
  ENTRY_KIND_FIELDS,
  entryKindLabel,
} from './AdventureEntryPayloadFields'
import {
  adventureImporterCopy,
  draftProvenanceLabel,
  importerErrorMessage,
  importStatusLabel,
  reviewStatusLabel,
  sourceKindLabel,
  warningLevelLabel,
} from './adventureImporterCopy'
import { adventuresCopy } from './adventuresCopy'
import { adventurePermissions } from './RoomAdventuresPage'
import { LocaleProvider } from '../../i18n/LocaleProvider'

describe('Adventure Importer Panel & Helper tests', () => {
  it('proves add, edit, and delete draft mutations preserve warnings, questions, review_status, asset_ids, visibility, resolved/resolution, and do not mutate import revision', () => {
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
          level: 'blocking',
          code: 'url_no_content',
          message: 'URL has no content',
          entry_id: null,
          source_id: 's1',
          resolved: true,
          resolution: 'Manual text supplied',
        },
      ],
      draft: {
        schema_version: 1,
        questions: [
          {
            question_id: 'q1',
            message: 'What is the DC?',
            entry_id: 'e1',
            answer: 'DC 15',
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
            review_status: 'accepted',
            asset_ids: ['asset-uuid-1'],
            title: 'Entry Title 1',
            body: 'Entry Body 1',
            visibility: 'dm_only',
          },
          {
            entry_id: 'e2',
            entry_kind: 'section',
            payload: { kind: 'section' },
            parent_entry_id: null,
            provenance: 'user_explicit',
            source_ref: null,
            note: null,
            review_status: 'uncertain',
            asset_ids: [],
            title: null,
            body: null,
            visibility: 'dm_only',
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
    // Warning resolved & resolution preserved
    expect(addInput.warnings).toEqual([
      expect.objectContaining({
        warning_id: 'w1',
        message: 'URL has no content',
        resolved: true,
        resolution: 'Manual text supplied',
      }),
    ])
    expect(addInput.draft.questions).toEqual([
      expect.objectContaining({ question_id: 'q1', message: 'What is the DC?', answer: 'DC 15' }),
    ])
    expect(addInput.draft.entries).toHaveLength(3)
    // Existing entry fields preserved
    expect(addInput.draft.entries[0]).toEqual(
      expect.objectContaining({
        entry_id: 'e1',
        provenance: 'source_document',
        source_ref: { source_id: 's1', locator: 'p.1' },
        review_status: 'accepted',
        asset_ids: ['asset-uuid-1'],
        title: 'Entry Title 1',
        body: 'Entry Body 1',
        visibility: 'dm_only',
      }),
    )
    // New entry defaults
    expect(addInput.draft.entries[2]).toEqual({
      entry_id: 'e3',
      entry_kind: 'npc',
      payload: { kind: 'npc', role: 'Guard', disposition: 'neutral' },
      parent_entry_id: null,
      provenance: 'user_explicit',
      source_ref: null,
      note: 'new note',
      review_status: 'pending',
      asset_ids: [],
      title: null,
      body: null,
      visibility: 'dm_only',
    })

    // 2. EDIT mutation: regression test verifying review_status, asset_ids, title/body/visibility preservation
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
    expect(editInput.warnings[0]).toEqual(
      expect.objectContaining({
        warning_id: 'w1',
        resolved: true,
        resolution: 'Manual text supplied',
      }),
    )
    expect(editInput.draft.entries).toHaveLength(2)
    expect(editInput.draft.entries[0]).toEqual({
      entry_id: 'e1',
      entry_kind: 'scene',
      payload: { kind: 'scene', dm_summary: 'Updated Hall' },
      parent_entry_id: 'e2',
      provenance: 'source_document',
      source_ref: { source_id: 's1', locator: 'p.1' },
      note: 'edited note',
      review_status: 'accepted', // PRESERVED!
      asset_ids: ['asset-uuid-1'], // PRESERVED!
      title: 'Entry Title 1', // PRESERVED!
      body: 'Entry Body 1', // PRESERVED!
      visibility: 'dm_only', // PRESERVED!
    })

    // 3. DELETE mutation
    const deleteInput = buildDraftMutationInput(sampleDraft, {
      type: 'delete',
      entryId: 'e1',
    })
    expect(deleteInput.expected_revision).toBe(5)
    expect(deleteInput.warnings[0].resolved).toBe(true)
    expect(deleteInput.draft.entries).toHaveLength(1)
    expect(deleteInput.draft.entries[0].entry_id).toBe('e2')
    expect(deleteInput.draft.entries[0].review_status).toBe('uncertain')

    // 4. Assert no draft helper mutated AdventureImport.revision
    expect(sampleImport.revision).toBe(2)
  })

  it('computes chunk pagination and validates/normalizes source files', () => {
    // Pagination table
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

    // Filename extension inference table
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

    // Normalization
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

  it('maintains bilingual copy parity, error mapping, and localized label mappings including P6-F review/warning/finalize', () => {
    const en = adventureImporterCopy('en')
    const zh = adventureImporterCopy('zh-TW')

    // Key parity
    expect(Object.keys(en).sort()).toEqual(Object.keys(zh).sort())

    // No internal P6 in values
    for (const key of Object.keys(en)) {
      expect(en[key as keyof typeof en]).not.toContain('P6')
      expect(zh[key as keyof typeof zh]).not.toContain('P6')
    }

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

    // Review status label mapping
    const reviewStatuses: ReviewStatus[] = ['pending', 'accepted', 'ignored', 'uncertain']
    for (const rs of reviewStatuses) {
      expect(reviewStatusLabel(rs, en)).toBeTruthy()
      expect(reviewStatusLabel(rs, zh)).toBeTruthy()
    }

    // Warning level label mapping
    const warningLevels: WarningLevel[] = ['info', 'warning', 'blocking']
    for (const wl of warningLevels) {
      expect(warningLevelLabel(wl, en)).toBeTruthy()
      expect(warningLevelLabel(wl, zh)).toBeTruthy()
    }

    // Error message mapping
    const errorCodes = [
      { code: 'adventure_import_not_found', expectedKey: 'errImportNotFound' },
      { code: 'adventure_import_revision_conflict', expectedKey: 'errImportRevisionConflict' },
      { code: 'asset_too_large', expectedKey: 'errAssetTooLarge' },
      { code: 'adventure_import_invalid', expectedKey: 'errInvalidSource' },
      { code: 'adventure_import_authority_required', expectedKey: 'errAuthorityRequired' },
      { code: 'adventure_import_blocking_warnings', expectedKey: 'errBlockingWarnings' },
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
    }

    // Whitelisted source metadata
    const metaWithByteSize = {
      byte_size: 2048,
      page_count: 12,
    }
    expect(formatWhitelistedMetadata(metaWithByteSize, en)).toEqual([
      { label: en.metaPageCount, value: '12' },
      { label: en.metaByteCount, value: '2048' },
    ])
    expect(formatWhitelistedMetadata(metaWithByteSize, zh)).toEqual([
      { label: zh.metaPageCount, value: '12' },
      { label: zh.metaByteCount, value: '2048' },
    ])
  })

function testStorage(locale: 'en' | 'zh-TW') {
  return {
    getItem: (key: string) => (key === 'adventure-table.locale' ? locale : null),
    setItem: () => undefined,
  }
}

  it('verifies permission guards and proves player cannot see importer controls', () => {
    expect(adventurePermissions('owner')).toEqual({ canAuthor: true })
    expect(adventurePermissions('dm')).toEqual({ canAuthor: true })
    expect(adventurePermissions('member')).toEqual({ canAuthor: false })
    expect(adventurePermissions(null)).toEqual({ canAuthor: false })
    expect(adventurePermissions(undefined)).toEqual({ canAuthor: false })

    // When canAuthor is false, AdventureImporterPanel renders null
    const playerHtml = renderToStaticMarkup(
      <LocaleProvider storage={testStorage('en')} documentTarget={null}>
        <AdventureImporterPanel canAuthor={false} roomId="r1" token="t1" />
      </LocaleProvider>,
    )
    expect(playerHtml).toBe('')
  })

  // Parametrized test suite for blocking gate, Accept not mandatory, and review actions
  describe.each([
    {
      label: 'unresolved blocking warning disables finalize and shows blocking notice',
      warnings: [
        {
          warning_id: 'w-block',
          level: 'blocking' as const,
          code: 'bad_struct',
          message: 'Structure missing',
          entry_id: null,
          source_id: null,
          resolved: false,
          resolution: null,
        },
      ],
      reviewStatus: 'accepted' as const,
      expectFinalizeDisabled: true,
      expectBlockingNotice: true,
    },
    {
      label: 'resolved blocking warning enables finalize',
      warnings: [
        {
          warning_id: 'w-block',
          level: 'blocking' as const,
          code: 'bad_struct',
          message: 'Structure missing',
          entry_id: null,
          source_id: null,
          resolved: true,
          resolution: 'Fixed by user',
        },
      ],
      reviewStatus: 'accepted' as const,
      expectFinalizeDisabled: false,
      expectBlockingNotice: false,
    },
    {
      label: 'warning level warning does not disable finalize',
      warnings: [
        {
          warning_id: 'w-warn',
          level: 'warning' as const,
          code: 'maybe_typo',
          message: 'Possible typo',
          entry_id: null,
          source_id: null,
          resolved: false,
          resolution: null,
        },
      ],
      reviewStatus: 'accepted' as const,
      expectFinalizeDisabled: false,
      expectBlockingNotice: false,
    },
    {
      label: 'info level warning does not disable finalize',
      warnings: [
        {
          warning_id: 'w-info',
          level: 'info' as const,
          code: 'note',
          message: 'General notice',
          entry_id: null,
          source_id: null,
          resolved: false,
          resolution: null,
        },
      ],
      reviewStatus: 'accepted' as const,
      expectFinalizeDisabled: false,
      expectBlockingNotice: false,
    },
    {
      label: 'Accept is not mandatory: pending entry review_status allows finalize',
      warnings: [],
      reviewStatus: 'pending' as const,
      expectFinalizeDisabled: false,
      expectBlockingNotice: false,
    },
    {
      label: 'Accept is not mandatory: ignored entry review_status allows finalize',
      warnings: [],
      reviewStatus: 'ignored' as const,
      expectFinalizeDisabled: false,
      expectBlockingNotice: false,
    },
    {
      label: 'Accept is not mandatory: uncertain entry review_status allows finalize',
      warnings: [],
      reviewStatus: 'uncertain' as const,
      expectFinalizeDisabled: false,
      expectBlockingNotice: false,
    },
  ])(
    'Blocking Gate & Accept Not Mandatory: $label',
    ({
      warnings,
      reviewStatus,
      expectFinalizeDisabled,
      expectBlockingNotice,
    }) => {
      it('correctly evaluates finalize button state and blocking notice', () => {
        const copy = adventureImporterCopy('en')
        const editorCopy = adventuresCopy('en')

        const sampleImport: AdventureImport = {
          id: 'imp-1',
          room_id: 'r1',
          name: 'Test Import',
          status: 'drafting',
          target_adventure_id: null,
          revision: 1,
          created_at: '2026-09-23T00:00:00Z',
          updated_at: '2026-09-23T00:00:00Z',
        }

        const draft: AdventureImportDraft = {
          import_id: 'imp-1',
          revision: 1,
          updated_at: '2026-09-23T00:00:00Z',
          warnings,
          draft: {
            schema_version: 1,
            questions: [],
            entries: [
              {
                entry_id: 'e1',
                entry_kind: 'scene',
                payload: { kind: 'scene', dm_summary: 'Test Scene' },
                parent_entry_id: null,
                provenance: 'user_explicit',
                source_ref: null,
                note: null,
                review_status: reviewStatus,
                asset_ids: [],
                title: null,
                body: null,
                visibility: 'dm_only',
              },
            ],
          },
        }

        const html = renderToStaticMarkup(
          <AdventureImportReviewSection
            canAuthor={true}
            copy={copy}
            draft={draft}
            editorCopy={editorCopy}
            importId={sampleImport.id}
            isFinalized={false}
            pending={false}
            roomId="r1"
            selectedImport={sampleImport}
            setPending={vi.fn()}
            setStaleError={vi.fn()}
            staleError={false}
            token="token1"
            onDraftUpdated={vi.fn()}
            onError={vi.fn()}
            onFinalized={vi.fn()}
            onImportReload={vi.fn().mockResolvedValue(undefined)}
            onViewSource={vi.fn()}
          />,
        )

        if (expectBlockingNotice) {
          expect(html).toContain(copy.blockingWarningsNotice)
          expect(html).toContain(copy.finalizeBlockedReason)
        } else {
          expect(html).not.toContain(copy.blockingWarningsNotice)
          expect(html).not.toContain(copy.finalizeBlockedReason)
        }

        if (expectFinalizeDisabled) {
          // Finalize button has disabled attribute
          expect(html).toMatch(/<button[^>]*class="[^"]*room-form-submit[^"]*"[^>]*disabled=""/)
        } else {
          // Finalize button is NOT disabled
          expect(html).toMatch(/<button[^>]*class="[^"]*room-form-submit[^"]*"/)
          expect(html).not.toMatch(/<button[^>]*class="[^"]*room-form-submit[^"]*"[^>]*disabled=""/)
        }
      })
    },
  )

  it('renders entry review status, action buttons, and conditionally renders View source only when source_ref exists', () => {
    const copy = adventureImporterCopy('en')
    const editorCopy = adventuresCopy('en')

    const sampleImport: AdventureImport = {
      id: 'imp-1',
      room_id: 'r1',
      name: 'Test Import',
      status: 'drafting',
      target_adventure_id: null,
      revision: 1,
      created_at: '2026-09-23T00:00:00Z',
      updated_at: '2026-09-23T00:00:00Z',
    }

    const draftWithBoth: AdventureImportDraft = {
      import_id: 'imp-1',
      revision: 1,
      updated_at: '2026-09-23T00:00:00Z',
      warnings: [],
      draft: {
        schema_version: 1,
        questions: [
          {
            question_id: 'q1',
            message: 'Is this door locked?',
            entry_id: 'e1',
            answer: null,
          },
        ],
        entries: [
          {
            entry_id: 'entry-with-source',
            entry_kind: 'scene',
            payload: { kind: 'scene', dm_summary: 'Scene with source' },
            parent_entry_id: null,
            provenance: 'source_document',
            source_ref: { source_id: 'src-1', locator: 'p.14' },
            note: null,
            review_status: 'pending',
            asset_ids: [],
            title: null,
            body: null,
            visibility: 'dm_only',
          },
          {
            entry_id: 'entry-without-source',
            entry_kind: 'scene',
            payload: { kind: 'scene', dm_summary: 'Scene without source' },
            parent_entry_id: null,
            provenance: 'user_explicit',
            source_ref: null,
            note: null,
            review_status: 'accepted',
            asset_ids: [],
            title: null,
            body: null,
            visibility: 'dm_only',
          },
        ],
      },
    }

    const html = renderToStaticMarkup(
      <AdventureImportReviewSection
        canAuthor={true}
        copy={copy}
        draft={draftWithBoth}
        editorCopy={editorCopy}
        importId={sampleImport.id}
        isFinalized={false}
        pending={false}
        roomId="r1"
        selectedImport={sampleImport}
        setPending={vi.fn()}
        setStaleError={vi.fn()}
        staleError={false}
        token="token1"
        onDraftUpdated={vi.fn()}
        onError={vi.fn()}
        onFinalized={vi.fn()}
        onImportReload={vi.fn().mockResolvedValue(undefined)}
        onViewSource={vi.fn()}
      />,
    )

    // Check review status labels rendered on cards
    expect(html).toContain(`${copy.reviewStatusLabel}: ${copy.reviewStatusPending}`)
    expect(html).toContain(`${copy.reviewStatusLabel}: ${copy.reviewStatusAccepted}`)

    // Check action buttons exist
    expect(html).toContain(copy.acceptEntryAction)
    expect(html).toContain(copy.ignoreEntryAction)
    expect(html).toContain(copy.markUncertainAction)

    // View source: only 1 occurrence, corresponding to the entry with source_ref!
    const viewSourceMatches = html.match(new RegExp(`>${copy.viewSourceAction}<`, 'g'))
    expect(viewSourceMatches).toHaveLength(1)

    // Check question rendered with answer control
    expect(html).toContain('Is this door locked?')
    expect(html).toContain(copy.answerQuestionAction)
  })
})
