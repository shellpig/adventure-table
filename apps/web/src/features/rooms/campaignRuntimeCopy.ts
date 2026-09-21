import {
  CampaignRuntimeApiError,
  type RuntimeEntryKind,
  type RuntimeItemHolderKind,
  type RuntimeVisibility,
} from '../../api/campaignRuntime'
import type { Locale } from '../../i18n/locale'

const COPY = {
  en: {
    changesTitle: 'Campaign Changes',
    changesIntro: 'Review mutable world entries, adventure overrides, and the current situation for this Campaign.',
    backCampaign: '← Back to Campaign',
    loading: 'Loading Campaign changes…',
    emptyState: 'No runtime entries, overrides, or current situation recorded yet.',
    missingAccess: 'This browser does not have access to this Room. Enter the Room again.',
    entriesHeading: 'Runtime Entries',
    overridesHeading: 'Adventure Overrides',
    contextHeading: 'Current Context',
    currentSituationLabel: 'Current Situation',
    currentSceneLabel: 'Current Scene',
    noCurrentScene: 'None',
    entryCountLabel: 'Active entries',
    overrideCountLabel: 'Active overrides',
    requestFailed: 'Campaign runtime request failed.',
    errCampaignRuntimeForbidden: 'You do not have permission to manage runtime world state for this Campaign.',
    errCampaignRuntimeNotFound: 'Requested runtime entry, override, or Campaign was not found.',
    errCampaignRuntimeArchived: 'This runtime entry or Campaign is archived and cannot be modified.',
    errCampaignRuntimeActiveSession: 'An active Session is currently in progress; manage world changes through the active Session.',
    errCampaignRuntimeSessionNotActive: 'The Session is not active or has ended.',
    errCampaignRuntimeIdempotencyConflict: 'An operation with this request key was already processed with different parameters.',
    errCampaignRuntimeRevisionConflict: 'Runtime world state was modified by another action. Please refresh and try again.',
    errCampaignRuntimeOverrideExists: 'An override already exists for this adventure entry.',
    errCampaignRuntimeInvalid: 'Invalid runtime world state data or parameters.',
    createEntryButton: 'Add Runtime Entry',
    editEntryButton: 'Edit',
    archiveEntryButton: 'Archive',
    confirmArchive: 'Are you sure you want to archive this runtime entry?',
    cancelButton: 'Cancel',
    saveButton: 'Save',
    submitCreate: 'Create Entry',
    submitUpdate: 'Update Entry',
    submitting: 'Saving…',
    archiving: 'Archiving…',
    formTitleCreate: 'New Runtime Entry',
    formTitleEdit: 'Edit Runtime Entry',
    kindLabel: 'Kind',
    titleLabel: 'Title / Name',
    bodyLabel: 'Description / Body',
    visibilityLabel: 'Visibility',
    visibilityPublic: 'Public',
    visibilityDmOnly: 'DM Only',
    visibilityCharacter: 'Character Specific',
    recipientsLabel: 'Character Recipients',
    noCharactersAvailable: 'No room characters available',
    dmNotesLabel: 'DM Notes',
    needsReviewLabel: 'Needs Review',
    needsReviewBadge: 'Needs Review',
    provenanceJsonLabel: 'Provenance JSON',
    sourceAdventureEntryLabel: 'Source Adventure Entry ID',
    readOnlyProvenance: 'Source Adventure Entry',
    revisionLabel: 'Revision',
    kindScene: 'Scene',
    kindNpc: 'NPC',
    kindItem: 'Item',
    kindQuest: 'Quest',
    kindFact: 'Fact',
    kindSecret: 'Secret',
    kindHazard: 'Hazard',
    kindOther: 'Other',
    monsterInstanceIdLabel: 'Monster Instance ID',
    monsterTemplateRefLabel: 'Monster Template Reference',
    itemHolderKindLabel: 'Item Holder',
    itemHolderNone: 'None',
    itemHolderScene: 'Scene',
    itemHolderNpc: 'NPC',
    itemHolderCharacter: 'Character',
    itemHolderParty: 'Party',
    itemHolderUnknown: 'Unknown',
    itemHolderTargetLabel: 'Holder Target',
    noTargetOptions: 'No valid targets available',
    otherDataLabel: 'Data JSON (scalar key-values only)',
    errNpcTitleRequired: 'NPC requires a nonblank title or name.',
    errFactBodyRequired: 'Fact requires nonblank body text.',
    errSceneRequired: 'Scene requires at least a nonblank title or description.',
    errCharacterRecipientsRequired: 'Character visibility requires at least one character recipient.',
    errItemHolderTargetRequired: 'Selected item holder requires a target.',
    errOtherDataInvalidJson: 'Other data must be a valid JSON object.',
    errOtherDataScalarOnly: 'Other data values must be strings, numbers, or booleans only.',
    errProvenanceInvalidJson: 'Provenance must be a valid JSON object.',
    noneLabel: 'None',
    emptyValue: '(None)',
    unnamedEntry: '(Unnamed)',
    recipientsNone: 'None',
    committedReloadWarning:
      'The change was saved, but the latest state could not be loaded. Please refresh before making another change.',
  },
  'zh-TW': {
    changesTitle: 'Campaign 變更',
    changesIntro: '檢視此 Campaign 的動態世界項目、冒險覆寫與目前情境。',
    backCampaign: '← 回 Campaign',
    loading: '正在載入 Campaign 變更…',
    emptyState: '目前尚未記錄任何執行期項目、覆寫或目前情境。',
    missingAccess: '這個瀏覽器沒有此 Room 的存取權，請重新進入 Room。',
    entriesHeading: '執行期項目',
    overridesHeading: '冒險覆寫',
    contextHeading: '目前情境',
    currentSituationLabel: '目前情境摘要',
    currentSceneLabel: '目前場景',
    noCurrentScene: '無',
    entryCountLabel: '使用中項目',
    overrideCountLabel: '使用中覆寫',
    requestFailed: 'Campaign 世界狀態請求失敗。',
    errCampaignRuntimeForbidden: '您沒有在此 Campaign 管理世界狀態的權限。',
    errCampaignRuntimeNotFound: '找不到指定的執行期項目、覆寫或 Campaign。',
    errCampaignRuntimeArchived: '此執行期項目或 Campaign 已封存，無法修改。',
    errCampaignRuntimeActiveSession: '目前已有進行中的 Session，請透過進行中的 Session 進行世界狀態變更。',
    errCampaignRuntimeSessionNotActive: 'Session 目前非進行中或已結束。',
    errCampaignRuntimeIdempotencyConflict: '此請求索引鍵先前已以不同參數處理過。',
    errCampaignRuntimeRevisionConflict: '世界狀態已被其他動作修改，請重新整理後再試一次。',
    errCampaignRuntimeOverrideExists: '此冒險項目已存在覆寫。',
    errCampaignRuntimeInvalid: '執行期世界狀態資料或參數無效。',
    createEntryButton: '新增執行期項目',
    editEntryButton: '編輯',
    archiveEntryButton: '封存',
    confirmArchive: '確定要封存此執行期項目嗎？',
    cancelButton: '取消',
    saveButton: '儲存',
    submitCreate: '建立項目',
    submitUpdate: '更新項目',
    submitting: '儲存中…',
    archiving: '封存中…',
    formTitleCreate: '新增執行期項目',
    formTitleEdit: '編輯執行期項目',
    kindLabel: '類型',
    titleLabel: '標題／名稱',
    bodyLabel: '說明／內容',
    visibilityLabel: '可見度',
    visibilityPublic: '公開',
    visibilityDmOnly: '僅 DM',
    visibilityCharacter: '指定角色',
    recipientsLabel: '指定角色',
    noCharactersAvailable: '無可用的 Room 角色',
    dmNotesLabel: 'DM 備忘',
    needsReviewLabel: '待審核',
    needsReviewBadge: '待審核',
    provenanceJsonLabel: '來源資訊 JSON',
    sourceAdventureEntryLabel: '來源冒險項目 ID',
    readOnlyProvenance: '來源冒險項目',
    revisionLabel: '修訂版號',
    kindScene: '場景',
    kindNpc: 'NPC',
    kindItem: '物品',
    kindQuest: '任務',
    kindFact: '世界事實',
    kindSecret: '秘密',
    kindHazard: '危害',
    kindOther: '其他',
    monsterInstanceIdLabel: '怪物實例 ID',
    monsterTemplateRefLabel: '怪物範本參照',
    itemHolderKindLabel: '持有者類型',
    itemHolderNone: '無',
    itemHolderScene: '場景',
    itemHolderNpc: 'NPC',
    itemHolderCharacter: '角色',
    itemHolderParty: '全隊',
    itemHolderUnknown: '未知',
    itemHolderTargetLabel: '持有者對象',
    noTargetOptions: '無可用的對象',
    otherDataLabel: '資料 JSON（僅限純量鍵值）',
    errNpcTitleRequired: 'NPC 必須提供非空白名稱或標題。',
    errFactBodyRequired: '世界事實必須提供非空白內容文字。',
    errSceneRequired: '場景必須至少提供非空白標題或說明。',
    errCharacterRecipientsRequired: '指定角色可見度必須至少選擇一位角色。',
    errItemHolderTargetRequired: '選取的持有者類型必須指定對象。',
    errOtherDataInvalidJson: '其他資料必須是有效的 JSON 物件。',
    errOtherDataScalarOnly: '其他資料的值只能是字串、數字或布林值。',
    errProvenanceInvalidJson: '來源資訊必須是有效的 JSON 物件。',
    noneLabel: '無',
    emptyValue: '（無）',
    unnamedEntry: '（未命名）',
    recipientsNone: '無',
    committedReloadWarning:
      '變更已成功儲存，但無法載入最新狀態。請在進行下一次變更前重新整理。',
  },
} as const satisfies Record<Locale, Record<string, string>>

export type CampaignRuntimeCopy = Record<keyof (typeof COPY)['en'], string>

export function campaignRuntimeCopy(locale: Locale): CampaignRuntimeCopy {
  return COPY[locale]
}

export function entryKindLabel(kind: RuntimeEntryKind, copy: CampaignRuntimeCopy): string {
  switch (kind) {
    case 'scene':
      return copy.kindScene
    case 'npc':
      return copy.kindNpc
    case 'item':
      return copy.kindItem
    case 'quest':
      return copy.kindQuest
    case 'fact':
      return copy.kindFact
    case 'secret':
      return copy.kindSecret
    case 'hazard':
      return copy.kindHazard
    case 'other':
      return copy.kindOther
    default:
      return kind
  }
}

export function visibilityLabel(visibility: RuntimeVisibility, copy: CampaignRuntimeCopy): string {
  switch (visibility) {
    case 'public':
      return copy.visibilityPublic
    case 'dm_only':
      return copy.visibilityDmOnly
    case 'character':
      return copy.visibilityCharacter
    default:
      return visibility
  }
}

export function itemHolderKindLabel(
  holderKind: RuntimeItemHolderKind | '',
  copy: CampaignRuntimeCopy,
): string {
  switch (holderKind) {
    case 'scene':
      return copy.itemHolderScene
    case 'npc':
      return copy.itemHolderNpc
    case 'character':
      return copy.itemHolderCharacter
    case 'party':
      return copy.itemHolderParty
    case 'unknown':
      return copy.itemHolderUnknown
    case '':
      return copy.itemHolderNone
    default:
      return holderKind
  }
}

export function campaignRuntimeErrorMessage(error: unknown, copy: CampaignRuntimeCopy): string {
  const code =
    error instanceof CampaignRuntimeApiError
      ? error.code
      : typeof error === 'object' && error !== null && 'code' in error
        ? String((error as { code: unknown }).code)
        : null

  switch (code) {
    case 'campaign_runtime_forbidden':
      return copy.errCampaignRuntimeForbidden
    case 'campaign_runtime_not_found':
      return copy.errCampaignRuntimeNotFound
    case 'campaign_runtime_archived':
      return copy.errCampaignRuntimeArchived
    case 'campaign_runtime_active_session':
      return copy.errCampaignRuntimeActiveSession
    case 'campaign_runtime_session_not_active':
      return copy.errCampaignRuntimeSessionNotActive
    case 'campaign_runtime_idempotency_conflict':
      return copy.errCampaignRuntimeIdempotencyConflict
    case 'campaign_runtime_revision_conflict':
      return copy.errCampaignRuntimeRevisionConflict
    case 'campaign_runtime_override_exists':
      return copy.errCampaignRuntimeOverrideExists
    case 'campaign_runtime_invalid':
      return copy.errCampaignRuntimeInvalid
    default:
      return copy.requestFailed
  }
}
