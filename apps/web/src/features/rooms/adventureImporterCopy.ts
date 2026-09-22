import {
  AdventureImportApiError,
  type DraftProvenance,
  type ImportStatus,
  type SourceKind,
} from '../../api/adventureImports'
import { RoomAssetApiError } from '../../api/roomAssets'
import type { Locale } from '../../i18n/locale'

const COPY = {
  en: {
    importerTitle: 'Adventure Importer',
    importerIntro:
      'Import adventure sources into a draft and review before finalizing; accessible to Room owner and DM.',
    createImportTitle: 'New Import',
    createImportAction: 'Create Import',
    importNameLabel: 'Import Name',
    importListTitle: 'Imports',
    emptyImports: 'No imports yet.',
    selectImport: 'Select',
    selectedBadge: 'Active',
    reloadImport: 'Reload',
    statusLabel: 'Status',
    revisionLabel: 'Revision',
    statusSource: 'Source',
    statusDrafting: 'Drafting',
    statusReview: 'Review',
    statusFinalized: 'Finalized',
    statusCancelled: 'Cancelled',
    sourceKindPaste: 'Pasted text',
    sourceKindTxt: 'Plain text (.txt)',
    sourceKindMarkdown: 'Markdown (.md)',
    sourceKindPdf: 'PDF document',
    sourceKindDocx: 'Word document (.docx)',
    sourceKindUrl: 'URL reference',
    provenanceSourceDocument: 'Source document',
    provenanceUserExplicit: 'User explicit',
    provenanceUserApproximation: 'User approximation',
    provenanceAiGenerated: 'AI generated',
    sourcesTitle: 'Sources',
    emptySources: 'No sources added to this import yet.',
    sourceTabPaste: 'Paste Text',
    sourceTabUpload: 'Upload File',
    sourceTabAsset: 'From Room Asset',
    sourceTabUrl: 'URL Reference',
    pasteTextLabel: 'Pasted text content',
    pasteFilenameLabel: 'Source label / filename (optional)',
    uploadFileLabel: 'File (.txt, .md, .pdf, .docx)',
    selectAssetLabel: 'Select a Room document asset',
    noAssetsAvailable: 'No source documents found in this Room.',
    urlLabel: 'Source URL',
    urlContentLabel: 'Pasted web content (optional)',
    urlTitleLabel: 'Page title (optional)',
    addSourceAction: 'Add Source',
    uploadAction: 'Upload & Add Source',
    textLengthLabel: 'Text length',
    metaPageCount: 'Pages',
    metaLineCount: 'Lines',
    metaByteCount: 'Bytes',
    metaCharCount: 'Characters',
    metaMediaType: 'Media type',
    metaTitle: 'Title',
    metaContentProvided: 'Content provided',
    metaYes: 'Yes',
    metaNo: 'No',
    viewTextAction: 'View text',
    closeChunkView: 'Close',
    chunkOffsetLabel: 'Offset',
    chunkTotalLabel: 'Total length',
    prevChunk: 'Previous',
    nextChunk: 'Next',
    loadingChunk: 'Loading text chunk…',
    draftTitle: 'Import Draft',
    draftRevisionLabel: 'Draft Revision',
    warningsTitle: 'Warnings',
    noWarnings: 'No warnings.',
    draftEntriesTitle: 'Draft Entries',
    emptyDraftEntries: 'No draft entries yet.',
    addDraftEntryTitle: 'Add Draft Entry',
    editDraftEntryTitle: 'Edit Draft Entry',
    entryKindLabel: 'Kind',
    parentEntryLabel: 'Parent section (optional)',
    parentEntryNone: '(None)',
    provenanceLabel: 'Provenance',
    sourceRefLabel: 'Source reference',
    sourceRefNone: '(None)',
    noteLabel: 'Note (optional)',
    addDraftEntryAction: 'Add to Draft',
    updateDraftEntryAction: 'Update Entry',
    cancelEditAction: 'Cancel',
    editEntryAction: 'Edit',
    deleteEntryAction: 'Delete',
    deleteEntryConfirm: 'Delete this draft entry?',
    staleDraftConflict:
      'Draft revision conflict. Someone else modified this draft, or local state is stale. Please reload.',
    reloadDraftAction: 'Reload Draft',
    errUnsupportedFileType: 'Unsupported file type. Please upload a .txt, .md, .pdf, or .docx file.',
    errImportNotFound: 'Adventure import not found.',
    errImportRevisionConflict: 'Adventure import revision conflict. Please reload.',
    errAssetTooLarge: 'The uploaded file exceeds the allowed size limit.',
    errInvalidSource: 'Invalid source data.',
    errAuthorityRequired: 'Only the Room owner or DM can manage adventure imports.',
    requestFailed: 'Adventure import request failed.',
  },
  'zh-TW': {
    importerTitle: '冒險模組匯入',
    importerIntro: '將外部來源匯入為草稿並於定稿前編修；僅 Room Owner 與 DM 可操作。',
    createImportTitle: '建立新匯入',
    createImportAction: '建立匯入',
    importNameLabel: '匯入名稱',
    importListTitle: '匯入項目',
    emptyImports: '目前沒有匯入項目。',
    selectImport: '選取',
    selectedBadge: '使用中',
    reloadImport: '重新載入',
    statusLabel: '狀態',
    revisionLabel: '版本',
    statusSource: '來源整理中',
    statusDrafting: '草稿編輯中',
    statusReview: '審閱中',
    statusFinalized: '已定稿',
    statusCancelled: '已取消',
    sourceKindPaste: '貼上文字',
    sourceKindTxt: '純文字檔 (.txt)',
    sourceKindMarkdown: 'Markdown 文件 (.md)',
    sourceKindPdf: 'PDF 文件',
    sourceKindDocx: 'Word 文件 (.docx)',
    sourceKindUrl: '網址參照',
    provenanceSourceDocument: '來源文件',
    provenanceUserExplicit: '使用者手動建立',
    provenanceUserApproximation: '使用者估算',
    provenanceAiGenerated: 'AI 產生',
    sourcesTitle: '資料來源',
    emptySources: '此匯入項目尚未加入任何來源。',
    sourceTabPaste: '貼上文字',
    sourceTabUpload: '上傳檔案',
    sourceTabAsset: '從 Room 素材選取',
    sourceTabUrl: '網址參照',
    pasteTextLabel: '貼上之文字內容',
    pasteFilenameLabel: '來源標籤／檔名（選填）',
    uploadFileLabel: '選擇檔案 (.txt, .md, .pdf, .docx)',
    selectAssetLabel: '選取 Room 文件素材',
    noAssetsAvailable: '此 Room 中沒有可用的文件素材。',
    urlLabel: '來源網址 (URL)',
    urlContentLabel: '貼上網頁文字內容（選填）',
    urlTitleLabel: '網頁標題（選填）',
    addSourceAction: '新增來源',
    uploadAction: '上傳並新增來源',
    textLengthLabel: '文字長度',
    metaPageCount: '頁數',
    metaLineCount: '行數',
    metaByteCount: '位元組',
    metaCharCount: '字元數',
    metaMediaType: '媒體類型',
    metaTitle: '標題',
    metaContentProvided: '已提供內容',
    metaYes: '是',
    metaNo: '否',
    viewTextAction: '檢視文字',
    closeChunkView: '關閉檢視',
    chunkOffsetLabel: '位移',
    chunkTotalLabel: '總長度',
    prevChunk: '上一頁',
    nextChunk: '下一頁',
    loadingChunk: '正在載入文字區塊…',
    draftTitle: '匯入草稿',
    draftRevisionLabel: '草稿版本',
    warningsTitle: '警告與提醒',
    noWarnings: '目前無警告。',
    draftEntriesTitle: '草稿 Entry 列表',
    emptyDraftEntries: '草稿中目前沒有 Entry。',
    addDraftEntryTitle: '新增草稿 Entry',
    editDraftEntryTitle: '編輯草稿 Entry',
    entryKindLabel: '類型',
    parentEntryLabel: '上層章節（選填）',
    parentEntryNone: '（無）',
    provenanceLabel: '來源歷程',
    sourceRefLabel: '來源參照',
    sourceRefNone: '（無）',
    noteLabel: '備註（選填）',
    addDraftEntryAction: '加入草稿',
    updateDraftEntryAction: '更新 Entry',
    cancelEditAction: '取消',
    editEntryAction: '編輯',
    deleteEntryAction: '刪除',
    deleteEntryConfirm: '確定要刪除此草稿 Entry 嗎？',
    staleDraftConflict:
      '草稿版本衝突（已有其他變更或本地狀態過期）。請重新載入最新內容。',
    reloadDraftAction: '重新載入草稿',
    errUnsupportedFileType: '不支援的檔案類型，請上傳 .txt、.md、.pdf 或 .docx 檔案。',
    errImportNotFound: '找不到此匯入項目。',
    errImportRevisionConflict: '匯入版本衝突，請重新載入。',
    errAssetTooLarge: '上傳檔案超過大小限制。',
    errInvalidSource: '無效的來源資料。',
    errAuthorityRequired: '只有 Room Owner 或 DM 可以管理冒險匯入。',
    requestFailed: '冒險匯入請求失敗。',
  },
} as const satisfies Record<Locale, Record<string, string>>

export type AdventureImporterCopy = Record<keyof (typeof COPY)['en'], string>

export function adventureImporterCopy(locale: Locale): AdventureImporterCopy {
  return COPY[locale]
}

export function importStatusLabel(status: ImportStatus, copy: AdventureImporterCopy): string {
  switch (status) {
    case 'source':
      return copy.statusSource
    case 'drafting':
      return copy.statusDrafting
    case 'review':
      return copy.statusReview
    case 'finalized':
      return copy.statusFinalized
    case 'cancelled':
      return copy.statusCancelled
  }
}

export function sourceKindLabel(kind: SourceKind, copy: AdventureImporterCopy): string {
  switch (kind) {
    case 'paste':
      return copy.sourceKindPaste
    case 'txt':
      return copy.sourceKindTxt
    case 'markdown':
      return copy.sourceKindMarkdown
    case 'pdf':
      return copy.sourceKindPdf
    case 'docx':
      return copy.sourceKindDocx
    case 'url':
      return copy.sourceKindUrl
  }
}

export function draftProvenanceLabel(
  provenance: DraftProvenance,
  copy: AdventureImporterCopy,
): string {
  switch (provenance) {
    case 'source_document':
      return copy.provenanceSourceDocument
    case 'user_explicit':
      return copy.provenanceUserExplicit
    case 'user_approximation':
      return copy.provenanceUserApproximation
    case 'ai_generated':
      return copy.provenanceAiGenerated
  }
}

export function importerErrorMessage(error: unknown, copy: AdventureImporterCopy): string {
  const code =
    error instanceof AdventureImportApiError || error instanceof RoomAssetApiError
      ? error.code
      : typeof error === 'object' && error !== null && 'code' in error
        ? String((error as { code: unknown }).code)
        : null

  switch (code) {
    case 'adventure_import_not_found':
      return copy.errImportNotFound
    case 'adventure_import_revision_conflict':
      return copy.errImportRevisionConflict
    case 'asset_too_large':
      return copy.errAssetTooLarge
    case 'adventure_import_invalid':
    case 'adventure_import_source_invalid':
      return copy.errInvalidSource
    case 'adventure_import_authority_required':
      return copy.errAuthorityRequired
    default:
      return copy.requestFailed
  }
}
