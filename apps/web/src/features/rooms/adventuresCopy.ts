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
    editorPlaceholder: 'Adventure Editor will be available here.',
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
    editorPlaceholder: 'Adventure 編輯器將在此提供。',
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
