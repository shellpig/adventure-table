import {
  AdventureImportApiError,
  type DraftProvenance,
  type ImportStatus,
  type ReviewStatus,
  type SourceKind,
  type WarningLevel,
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

    // P6-F Review status
    reviewStatusLabel: 'Review status',
    reviewStatusPending: 'Pending',
    reviewStatusAccepted: 'Accepted',
    reviewStatusIgnored: 'Ignored',
    reviewStatusUncertain: 'Uncertain',

    // P6-F Review actions
    acceptEntryAction: 'Accept',
    ignoreEntryAction: 'Ignore',
    markUncertainAction: 'Mark uncertain',
    viewSourceAction: 'View source',

    // P6-F Warnings
    warningLevelInfo: 'Info',
    warningLevelWarning: 'Warning',
    warningLevelBlocking: 'Blocking',
    warningsInfoTitle: 'Information',
    warningsWarningTitle: 'Warnings',
    warningsBlockingTitle: 'Blocking Warnings',
    resolvedBadge: 'Resolved',
    warningCodeLabel: 'Code',
    warningEntryLabel: 'Entry',
    resolutionLabel: 'Resolution',
    resolutionPlaceholder: 'Resolution notes (optional)',
    resolveWarningAction: 'Resolve',
    blockingWarningsNotice: 'Unresolved blocking warnings must be resolved before finalizing.',

    // P6-F Questions
    questionsTitle: 'Questions',
    noQuestions: 'No questions.',
    answeredBadge: 'Answered',
    answerLabel: 'Answer',
    questionAnswerPlaceholder: 'Enter answer…',
    answerQuestionAction: 'Submit Answer',

    // P6-F Finalize
    finalizeSectionTitle: 'Finalize Adventure',
    finalizeNameLabel: 'Adventure Name',
    finalizeSummaryLabel: 'Summary (optional)',
    finalizeAdventureAction: 'Finalize',
    finalizeBlockedReason: 'Cannot finalize: unresolved blocking warnings exist.',
    importAlreadyFinalized: 'This import has been finalized.',
    openTargetAdventure: 'Open Adventure',
    targetAdventureLabel: 'Target Adventure',

    // Error messages
    errUnsupportedFileType: 'Unsupported file type. Please upload a .txt, .md, .pdf, or .docx file.',
    errImportNotFound: 'Adventure import not found.',
    errImportRevisionConflict: 'Adventure import revision conflict. Please reload.',
    errAssetTooLarge: 'The uploaded file exceeds the allowed size limit.',
    errInvalidSource: 'Invalid source data.',
    errAuthorityRequired: 'Only the Room owner or DM can manage adventure imports.',
    errBlockingWarnings: 'Cannot finalize: there are unresolved blocking warnings.',
    warningIdsLabel: 'Warning IDs',
    requestFailed: 'Adventure import request failed.',
  },
  'zh-TW': {
    importerTitle: '冒險故事匯入',
    importerIntro: '將外部來源匯入為草稿並於定稿前編修；僅房間 Owner 與 DM 可操作。',
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
    sourceTabAsset: '從房間素材選取',
    sourceTabUrl: '網址參照',
    pasteTextLabel: '貼上之文字內容',
    pasteFilenameLabel: '來源標籤／檔名（選填）',
    uploadFileLabel: '選擇檔案 (.txt, .md, .pdf, .docx)',
    selectAssetLabel: '選取房間文件素材',
    noAssetsAvailable: '此房間中沒有可用的文件素材。',
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
    draftEntriesTitle: '草稿資料包列表',
    emptyDraftEntries: '草稿中目前沒有資料包。',
    addDraftEntryTitle: '新增草稿資料包',
    editDraftEntryTitle: '編輯草稿資料包',
    entryKindLabel: '類型',
    parentEntryLabel: '上層章節（選填）',
    parentEntryNone: '（無）',
    provenanceLabel: '來源歷程',
    sourceRefLabel: '來源參照',
    sourceRefNone: '（無）',
    noteLabel: '備註（選填）',
    addDraftEntryAction: '加入草稿',
    updateDraftEntryAction: '更新資料包',
    cancelEditAction: '取消',
    editEntryAction: '編輯',
    deleteEntryAction: '刪除',
    deleteEntryConfirm: '確定要刪除此草稿資料包嗎？',
    staleDraftConflict:
      '草稿版本衝突（已有其他變更或本地狀態過期）。請重新載入最新內容。',
    reloadDraftAction: '重新載入草稿',

    // P6-F Review status
    reviewStatusLabel: '審閱狀態',
    reviewStatusPending: '待審閱',
    reviewStatusAccepted: '已接受',
    reviewStatusIgnored: '已略過',
    reviewStatusUncertain: '存疑',

    // P6-F Review actions
    acceptEntryAction: '接受',
    ignoreEntryAction: '略過',
    markUncertainAction: '標記為存疑',
    viewSourceAction: '檢視來源',

    // P6-F Warnings
    warningLevelInfo: '提示',
    warningLevelWarning: '警告',
    warningLevelBlocking: '阻礙性警告',
    warningsInfoTitle: '一般提示',
    warningsWarningTitle: '一般警告',
    warningsBlockingTitle: '阻礙性警告',
    resolvedBadge: '已解決',
    warningCodeLabel: '代碼',
    warningEntryLabel: '項目',
    resolutionLabel: '處理方式',
    resolutionPlaceholder: '處理備註（選填）',
    resolveWarningAction: '解決警告',
    blockingWarningsNotice: '尚有未解決的阻礙性警告，必須全部解決後方可定稿。',

    // P6-F Questions
    questionsTitle: '待確認問題',
    noQuestions: '目前無問題。',
    answeredBadge: '已回答',
    answerLabel: '回答',
    questionAnswerPlaceholder: '輸入回答…',
    answerQuestionAction: '提交回答',

    // P6-F Finalize
    finalizeSectionTitle: '定稿為冒險故事',
    finalizeNameLabel: '冒險故事名稱',
    finalizeSummaryLabel: '摘要（選填）',
    finalizeAdventureAction: '確認定稿',
    finalizeBlockedReason: '無法定稿：尚有未解決的阻礙性警告。',
    importAlreadyFinalized: '此匯入項目已定稿。',
    openTargetAdventure: '開啟冒險故事',
    targetAdventureLabel: '目標冒險故事',

    // Error messages
    errUnsupportedFileType: '不支援的檔案類型，請上傳 .txt、.md、.pdf 或 .docx 檔案。',
    errImportNotFound: '找不到此匯入項目。',
    errImportRevisionConflict: '匯入版本衝突，請重新載入。',
    errAssetTooLarge: '上傳檔案超過大小限制。',
    errInvalidSource: '無效的來源資料。',
    errAuthorityRequired: '只有房間 Owner 或 DM 可以管理冒險匯入。',
    errBlockingWarnings: '無法定稿：尚有未解決的阻礙性警告。',
    warningIdsLabel: '警告 ID',
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

export function reviewStatusLabel(
  status: ReviewStatus,
  copy: AdventureImporterCopy,
): string {
  switch (status) {
    case 'pending':
      return copy.reviewStatusPending
    case 'accepted':
      return copy.reviewStatusAccepted
    case 'ignored':
      return copy.reviewStatusIgnored
    case 'uncertain':
      return copy.reviewStatusUncertain
  }
}

export function warningLevelLabel(
  level: WarningLevel,
  copy: AdventureImporterCopy,
): string {
  switch (level) {
    case 'info':
      return copy.warningLevelInfo
    case 'warning':
      return copy.warningLevelWarning
    case 'blocking':
      return copy.warningLevelBlocking
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
    case 'adventure_import_blocking_warnings':
      if (error instanceof AdventureImportApiError && error.params?.warning_ids?.length) {
        return `${copy.errBlockingWarnings} ${copy.warningIdsLabel}: ${error.params.warning_ids.join(', ')}`
      }
      return copy.errBlockingWarnings
    default:
      return copy.requestFailed
  }
}
