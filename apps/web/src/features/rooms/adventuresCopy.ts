import { AdventureApiError } from '../../api/adventures'
import { RoomAssetApiError } from '../../api/roomAssets'
import type { Locale } from '../../i18n/locale'

const COPY = {
  en: {
    title: 'Adventures',
    intro: 'Adventures are reusable world and adventure data packs that a Campaign may attach; Players never see them directly.',
    createTitle: 'Create Adventure',
    nameLabel: 'Adventure name',
    summaryLabel: 'Summary (optional)',
    createAction: 'Create Adventure',
    open: 'Open',
    finalize: 'Finalize',
    archive: 'Archive',
    delete: 'Delete',
    deleteConfirm: 'Delete this Adventure permanently? This action cannot be undone.',
    archiveConfirm: 'Archive this Adventure? Archived Adventures cannot be attached to new Campaigns.',
    statusLabel: 'Status',
    statusDraft: 'Draft',
    statusFinalized: 'Finalized',
    statusArchived: 'Archived',
    empty: 'No Adventures yet.',
    loading: 'Loading Adventures…',
    missingAccess: 'This browser does not have access to this Room. Enter the Room again.',
    requestFailed: 'Adventure request failed.',
    noAuthority: 'Only the Room owner or DM can manage Adventures.',
    backRoom: '← Back to Room workspace',
    backAdventures: '← Back to Adventures',
    editorTitle: 'Adventure Editor',
    definitionTitle: 'Adventure Details',
    saveDefinition: 'Save Details',
    entriesTitle: 'Adventure Entries',
    entriesEmpty: 'No entries yet.',
    addEntryTitle: 'Add Entry',
    editEntryTitle: 'Edit Entry',
    entryKindLabel: 'Kind',
    entryTitleLabel: 'Title (optional)',
    entryBodyLabel: 'Body (optional)',
    entryVisibilityLabel: 'Visibility',
    visibilityPublic: 'Public (DM may narrate)',
    visibilityDmOnly: 'DM only',
    entryParentLabel: 'Parent section (optional)',
    entryParentNone: '(None)',
    saveEntry: 'Save Entry',
    addEntry: 'Add Entry',
    cancelEdit: 'Cancel',
    editEntry: 'Edit',
    deleteEntry: 'Delete',
    entryDeleteConfirm: 'Delete this entry permanently? This action cannot be undone.',
    moveUp: 'Move up',
    moveDown: 'Move down',
    readOnlyNotice: 'This Adventure is archived and read-only.',
    fieldReadAloud: 'Read aloud text',
    fieldDmSummary: 'DM summary',
    fieldRole: 'Role',
    fieldDisposition: 'Disposition',
    fieldRarity: 'Rarity',
    fieldValueGp: 'Value (gp)',
    fieldIsMagic: 'Magic item',
    fieldMonsterTemplateRef: 'Monster template reference',
    fieldCount: 'Count',
    fieldNotes: 'Notes',
    fieldObjective: 'Objective',
    fieldReward: 'Reward',
    fieldRevealCondition: 'Reveal condition',
    fieldAbility: 'Ability',
    fieldSkill: 'Skill (optional)',
    fieldDc: 'DC',
    fieldOnSuccess: 'On success',
    fieldOnFailure: 'On failure',
    fieldCaption: 'Caption',
    fieldTopic: 'Topic',
    dispositionFriendly: 'Friendly',
    dispositionNeutral: 'Neutral',
    dispositionHostile: 'Hostile',
    dispositionUnknown: 'Unknown',
    abilityStr: 'Strength',
    abilityDex: 'Dexterity',
    abilityCon: 'Constitution',
    abilityInt: 'Intelligence',
    abilityWis: 'Wisdom',
    abilityCha: 'Charisma',
    kindSection: 'Section',
    kindScene: 'Scene',
    kindNpc: 'NPC',
    kindItem: 'Item',
    kindMonsterRef: 'Monster Reference',
    kindQuest: 'Quest',
    kindSecret: 'Secret',
    kindDmNote: 'DM Note',
    kindSuggestedCheck: 'Suggested Check',
    kindMap: 'Map',
    kindLore: 'Lore',
    kindOther: 'Other',
    errAdventureNotFound: 'Adventure not found.',
    errAdventureArchived: 'This Adventure is archived and cannot be modified.',
    errAdventureStatusConflict: 'Adventure status conflict.',
    errAdventureAttachedUseArchive: 'This Adventure is attached to one or more Campaigns. Archive it instead of deleting.',
    errAdventureNotFinalized: 'Only finalized Adventures can be attached to a Campaign.',
    errAdventureAlreadyAttached: 'This Adventure is already attached to this Campaign.',
    errAdventureEntryPayloadInvalid: 'Entry fields are invalid; check required fields and numbers.',
    errAdventureEntryParentInvalid: 'Parent entry is invalid (missing or would create a cycle).',
    errAdventureEntryNotFound: 'Adventure entry not found.',
    errAssetVisibilityNotAllowed: 'Asset visibility is not allowed.',
    errAssetInUse: 'Asset is currently in use and cannot be deleted.',
    errAssetMediaTypeNotSupported: 'Asset media type is not supported.',
    errAssetTooLarge: 'Asset file is too large.',
  },
  'zh-TW': {
    title: 'Adventures',
    intro: 'Adventure 是可重複使用的世界與冒險資料包，可供 Campaign 附加；Player 無法直接看見。',
    createTitle: '建立 Adventure',
    nameLabel: 'Adventure 名稱',
    summaryLabel: '摘要（選填）',
    createAction: '建立 Adventure',
    open: '開啟',
    finalize: '定稿',
    archive: '封存',
    delete: '刪除',
    deleteConfirm: '要永久刪除此 Adventure 嗎？此動作無法復原。',
    archiveConfirm: '要封存此 Adventure 嗎？已封存的 Adventure 無法附加至新的 Campaign。',
    statusLabel: '狀態',
    statusDraft: '草稿',
    statusFinalized: '已定稿',
    statusArchived: '已封存',
    empty: '目前還沒有 Adventure。',
    loading: '正在載入 Adventure…',
    missingAccess: '這個瀏覽器沒有此 Room 的存取權，請重新進入 Room。',
    requestFailed: 'Adventure 請求失敗。',
    noAuthority: '只有 Room Owner 或 DM 可以管理 Adventure。',
    backRoom: '← 回 Room 工作區',
    backAdventures: '← 回 Adventure 列表',
    editorTitle: 'Adventure 編輯器',
    definitionTitle: 'Adventure 詳細資訊',
    saveDefinition: '儲存詳細資訊',
    entriesTitle: 'Adventure Entries',
    entriesEmpty: '目前還沒有 Entry。',
    addEntryTitle: '新增 Entry',
    editEntryTitle: '編輯 Entry',
    entryKindLabel: '類型',
    entryTitleLabel: '標題（選填）',
    entryBodyLabel: '內容（選填）',
    entryVisibilityLabel: '可見度',
    visibilityPublic: '公開（DM 可直接敘事）',
    visibilityDmOnly: '僅 DM',
    entryParentLabel: '上層章節（選填）',
    entryParentNone: '（無）',
    saveEntry: '儲存 Entry',
    addEntry: '新增 Entry',
    cancelEdit: '取消',
    editEntry: '編輯',
    deleteEntry: '刪除',
    entryDeleteConfirm: '要永久刪除此 entry 嗎？此動作無法復原。',
    moveUp: '上移',
    moveDown: '下移',
    readOnlyNotice: '此 Adventure 已封存，僅供檢視。',
    fieldReadAloud: '朗讀文字',
    fieldDmSummary: 'DM 摘要',
    fieldRole: '角色',
    fieldDisposition: '態度',
    fieldRarity: '稀有度',
    fieldValueGp: '價值（gp）',
    fieldIsMagic: '魔法物品',
    fieldMonsterTemplateRef: '怪物範本參照',
    fieldCount: '數量',
    fieldNotes: '備註',
    fieldObjective: '目標',
    fieldReward: '獎勵',
    fieldRevealCondition: '揭露條件',
    fieldAbility: '屬性',
    fieldSkill: '技能（選填）',
    fieldDc: 'DC',
    fieldOnSuccess: '成功時',
    fieldOnFailure: '失敗時',
    fieldCaption: '說明',
    fieldTopic: '主題',
    dispositionFriendly: '友善',
    dispositionNeutral: '中立',
    dispositionHostile: '敵對',
    dispositionUnknown: '未知',
    abilityStr: '力量',
    abilityDex: '敏捷',
    abilityCon: '體質',
    abilityInt: '智力',
    abilityWis: '感知',
    abilityCha: '魅力',
    kindSection: '章節',
    kindScene: '場景',
    kindNpc: 'NPC',
    kindItem: '道具',
    kindMonsterRef: '怪物參照',
    kindQuest: '任務',
    kindSecret: '秘密',
    kindDmNote: 'DM 筆記',
    kindSuggestedCheck: '建議檢定',
    kindMap: '地圖',
    kindLore: '背景知識',
    kindOther: '其他',
    errAdventureNotFound: '找不到此 Adventure。',
    errAdventureArchived: '此 Adventure 已封存，無法修改。',
    errAdventureStatusConflict: 'Adventure 狀態衝突。',
    errAdventureAttachedUseArchive: '此 Adventure 已附加至一個或多個 Campaign，請改用封存而非刪除。',
    errAdventureNotFinalized: '只有已定稿的 Adventure 才能附加至 Campaign。',
    errAdventureAlreadyAttached: '此 Adventure 已附加至此 Campaign。',
    errAdventureEntryPayloadInvalid: 'Entry 欄位無效，請檢查必填欄位與數字。',
    errAdventureEntryParentInvalid: '上層 entry 無效（不存在或會形成循環）。',
    errAdventureEntryNotFound: '找不到此 Adventure entry。',
    errAssetVisibilityNotAllowed: '不允許的素材可見度。',
    errAssetInUse: '素材目前正在使用中，無法刪除。',
    errAssetMediaTypeNotSupported: '不支援的素材檔案類型。',
    errAssetTooLarge: '素材檔案過大。',
  },
} as const satisfies Record<Locale, Record<string, string>>

export function adventuresCopy(locale: Locale) {
  return COPY[locale]
}

export function adventureErrorMessage(
  error: unknown,
  copy: ReturnType<typeof adventuresCopy>,
): string {
  const code =
    error instanceof AdventureApiError || error instanceof RoomAssetApiError
      ? error.code
      : typeof error === 'object' && error !== null && 'code' in error
        ? String((error as { code: unknown }).code)
        : null

  switch (code) {
    case 'adventure_not_found':
      return copy.errAdventureNotFound
    case 'adventure_archived':
      return copy.errAdventureArchived
    case 'adventure_status_conflict':
      return copy.errAdventureStatusConflict
    case 'adventure_attached_use_archive':
      return copy.errAdventureAttachedUseArchive
    case 'adventure_not_finalized':
      return copy.errAdventureNotFinalized
    case 'adventure_already_attached':
      return copy.errAdventureAlreadyAttached
    case 'adventure_entry_payload_invalid':
      return copy.errAdventureEntryPayloadInvalid
    case 'adventure_entry_parent_invalid':
      return copy.errAdventureEntryParentInvalid
    case 'adventure_entry_not_found':
      return copy.errAdventureEntryNotFound
    case 'asset_visibility_not_allowed':
      return copy.errAssetVisibilityNotAllowed
    case 'asset_in_use':
      return copy.errAssetInUse
    case 'asset_media_type_not_supported':
      return copy.errAssetMediaTypeNotSupported
    case 'asset_too_large':
      return copy.errAssetTooLarge
    default:
      return copy.requestFailed
  }
}
