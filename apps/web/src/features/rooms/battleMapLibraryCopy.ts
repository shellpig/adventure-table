import { RoomAssetApiError } from '../../api/roomAssets'
import { SessionApiError } from '../../api/sessions'
import type { Locale } from '../../i18n/locale'

const COPY = {
  en: {
    title: 'Map Library',
    intro: 'Manage reusable battle maps for encounters and combat boards.',
    backRoom: '← Back to Room workspace',
    showArchived: 'Show archived',
    badgeArchived: 'Archived',
    sourceBlank: 'Blank grid',
    sourceImage: 'Image map',
    gridDimensions: '{width}×{height} cells',
    revisionLabel: 'Revision',
    emptyList: 'No battle maps found.',
    loadingList: 'Loading battle maps…',
    refreshAction: 'Refresh',
    cancel: 'Cancel',

    // Actions
    createBlankAction: 'Create Blank Map',
    createImageAction: 'Upload Image Map',
    editAction: 'Edit Map',
    copyAction: 'Copy',
    archiveAction: 'Archive',
    deleteAction: 'Delete',

    // In-flight status
    creatingAction: 'Creating…',
    uploadingAction: 'Uploading…',
    copyingAction: 'Copying…',
    archivingAction: 'Archiving…',
    deletingAction: 'Deleting…',

    // Modals
    createBlankModalTitle: 'Create Blank Map',
    createImageModalTitle: 'Upload Image Map',
    copyModalTitle: 'Copy Battle Map',
    modalMapName: 'Map name',
    modalCopyNameOptional: 'New map name (optional)',
    modalWidthCells: 'Width (cells)',
    modalHeightCells: 'Height (cells)',
    modalImageFile: 'Map image file',
    submitCreate: 'Create Map',
    submitUpload: 'Upload & Create',
    submitCopy: 'Copy Map',

    // Confirmations
    archiveConfirm: 'Archive this battle map? Archived maps will no longer appear in new combat menus.',
    deleteConfirm: 'Delete this battle map permanently? This action cannot be undone.',

    // Permissions & notices
    forbidden: 'Only the Room owner or DM can manage the battle map library.',
    missingAccess: 'This browser does not have access to this Room. Enter the Room again.',

    // Errors
    requestFailed: 'Map library request failed.',
    errBattleMapNotFound: 'Battle map not found.',
    errBattleMapRevisionConflict: 'This map was changed elsewhere; please reload and try again.',
    errBattleMapReferenced: 'This map is used by a combat and cannot be deleted; archive it instead.',
    errBattleMapArchived: 'This battle map is archived and cannot be used for this action.',
    errBattleMapInvalid: 'Invalid map parameters or dimensions.',
    errBattleMapAssetInvalid: 'Invalid image asset.',
    errMapMonsterPlacementInvalid: 'Some monster placements are invalid. Fix the highlighted placements and save again.',
    errMonsterPlacementReferenceNotFound: 'A referenced monster template no longer exists in this Room.',
    errMonsterPlacementInvalidSource: 'A monster placement has an invalid template source.',

    // Monster placements (M07-C library editor)
    monsterPlacementsTool: 'Monsters',
    monsterPlacementsHeading: 'Monster placements',
    monsterPlacementsHint: 'Pick a template, then click a cell to place it. Click a placed monster to select it; click another cell to move it.',
    monsterTemplatePickerLabel: 'Monster template',
    monsterTemplatePickerPlaceholder: 'Choose a template…',
    monsterPlacementVisibilityLabel: 'Visibility',
    monsterVisibilityPublic: 'Public',
    monsterVisibilityHidden: 'Hidden',
    monsterPlacementArchivedBadge: 'Archived template',
    monsterPlacementUnknownTemplate: 'Unknown template',
    monsterPlacementRemove: 'Remove',
    monsterPlacementSave: 'Save monster placements',
    monsterPlacementSaving: 'Saving placements…',
    monsterPlacementSaved: 'Monster placements saved.',
    monsterPlacementProblemsHeading: 'Placement problems (DM only)',
    monsterPlacementRetryHint: 'Fix the placements above, then save again.',
    monsterPlacementLoadingTemplates: 'Loading monster templates…',

    // Placement problem codes (server validator, DM only)
    placementProblemOutOfBounds: 'is outside the map.',
    placementProblemBlockedTerrain: 'stands on blocked terrain.',
    placementProblemWallOrDoorBlocked: 'is cut through by a wall or a closed door.',
    placementProblemOverlappingPlacement: 'overlaps another monster placement.',
    placementProblemTemplateArchived: 'uses an archived template and cannot be added again.',
    placementProblemInvalidSize: 'has an unreadable monster size.',
  },
  'zh-TW': {
    title: '地圖庫',
    intro: '管理房間內可重複使用的戰鬥地圖，供遭遇戰與戰術戰鬥調用。',
    backRoom: '← 回房間工作區',
    showArchived: '顯示已封存',
    badgeArchived: '已封存',
    sourceBlank: '空白格線',
    sourceImage: '圖片地圖',
    gridDimensions: '{width}×{height} 格',
    revisionLabel: '版本',
    emptyList: '找不到符合條件的戰鬥地圖。',
    loadingList: '正在載入戰鬥地圖…',
    refreshAction: '重新整理',
    cancel: '取消',

    // Actions
    createBlankAction: '建立空白地圖',
    createImageAction: '上傳圖片建立地圖',
    editAction: '編輯地圖',
    copyAction: '複製',
    archiveAction: '封存',
    deleteAction: '刪除',

    // In-flight status
    creatingAction: '正在建立…',
    uploadingAction: '正在上傳…',
    copyingAction: '正在複製…',
    archivingAction: '正在封存…',
    deletingAction: '正在刪除…',

    // Modals
    createBlankModalTitle: '建立空白地圖',
    createImageModalTitle: '上傳圖片建立地圖',
    copyModalTitle: '複製戰鬥地圖',
    modalMapName: '地圖名稱',
    modalCopyNameOptional: '新地圖名稱（選填）',
    modalWidthCells: '寬度（格數）',
    modalHeightCells: '高度（格數）',
    modalImageFile: '地圖底圖檔案',
    submitCreate: '建立地圖',
    submitUpload: '上傳並建立',
    submitCopy: '複製地圖',

    // Confirmations
    archiveConfirm: '確定要封存此戰鬥地圖嗎？已封存的地圖將無法於新戰鬥中選用。',
    deleteConfirm: '確定要永久刪除此戰鬥地圖嗎？此動作無法復原。',

    // Permissions & notices
    forbidden: '只有房間 Owner 或 DM 可以管理地圖庫。',
    missingAccess: '這個瀏覽器沒有此房間的存取權，請重新進入房間。',

    // Errors
    requestFailed: '地圖庫請求失敗。',
    errBattleMapNotFound: '找不到此戰鬥地圖。',
    errBattleMapRevisionConflict: '地圖已被他人修改，請重新整理頁面後再試。',
    errBattleMapReferenced: '此地圖已被戰鬥引用，無法刪除；請改用封存。',
    errBattleMapArchived: '此地圖已封存，無法在此操作中使用。',
    errBattleMapInvalid: '地圖參數或尺寸無效。',
    errBattleMapAssetInvalid: '地圖底圖資源無效。',
    errMapMonsterPlacementInvalid: '部分怪物配置無效，請修正標示的配置後再儲存。',
    errMonsterPlacementReferenceNotFound: '引用的怪物範本已不存在於此房間。',
    errMonsterPlacementInvalidSource: '某筆怪物配置的範本來源無效。',

    // Monster placements (M07-C library editor)
    monsterPlacementsTool: '怪物',
    monsterPlacementsHeading: '怪物配置',
    monsterPlacementsHint: '選擇範本後點空格子放置；點已放置的怪物可選取，再點其他格子可移動。',
    monsterTemplatePickerLabel: '怪物範本',
    monsterTemplatePickerPlaceholder: '選擇範本…',
    monsterPlacementVisibilityLabel: '可見性',
    monsterVisibilityPublic: '公開',
    monsterVisibilityHidden: '隱藏',
    monsterPlacementArchivedBadge: '已封存範本',
    monsterPlacementUnknownTemplate: '未知範本',
    monsterPlacementRemove: '移除',
    monsterPlacementSave: '儲存怪物配置',
    monsterPlacementSaving: '正在儲存配置…',
    monsterPlacementSaved: '怪物配置已儲存。',
    monsterPlacementProblemsHeading: '配置問題（僅 DM 可見）',
    monsterPlacementRetryHint: '修正上方配置後再儲存一次。',
    monsterPlacementLoadingTemplates: '正在載入怪物範本…',

    // Placement problem codes (server validator, DM only)
    placementProblemOutOfBounds: '超出地圖範圍。',
    placementProblemBlockedTerrain: '站在阻擋地形上。',
    placementProblemWallOrDoorBlocked: '被牆或關閉的門切過。',
    placementProblemOverlappingPlacement: '與另一隻怪物的配置重疊。',
    placementProblemTemplateArchived: '使用了已封存的範本，無法再新增。',
    placementProblemInvalidSize: '怪物體型無法判讀。',
  },
} as const satisfies Record<Locale, Record<string, string>>

export type BattleMapLibraryCopy = (typeof COPY)[Locale]

export function battleMapLibraryCopy(locale: Locale): BattleMapLibraryCopy {
  return COPY[locale]
}

export function battleMapLibraryErrorMessage(
  error: unknown,
  copy: BattleMapLibraryCopy,
): string {
  const code =
    error instanceof SessionApiError || error instanceof RoomAssetApiError ? error.code : null

  switch (code) {
    case 'battle_map_not_found':
      return copy.errBattleMapNotFound
    case 'battle_map_revision_conflict':
      return copy.errBattleMapRevisionConflict
    case 'battle_map_referenced':
      return copy.errBattleMapReferenced
    case 'battle_map_archived':
      return copy.errBattleMapArchived
    case 'battle_map_invalid':
      return copy.errBattleMapInvalid
    case 'battle_map_asset_invalid':
      return copy.errBattleMapAssetInvalid
    case 'map_monster_placement_invalid':
      return copy.errMapMonsterPlacementInvalid
    case 'monster_placement_reference_not_found':
      return copy.errMonsterPlacementReferenceNotFound
    case 'monster_placement_invalid_source':
      return copy.errMonsterPlacementInvalidSource
    default:
      return copy.requestFailed
  }
}

/**
 * Human sentence for one placement problem code (M07-C validator, DM only).
 * Unknown codes fall back to the raw code so new server codes stay visible.
 */
export function monsterPlacementProblemMessage(
  code: string,
  copy: BattleMapLibraryCopy,
): string {
  switch (code) {
    case 'out_of_bounds':
      return copy.placementProblemOutOfBounds
    case 'blocked_terrain':
      return copy.placementProblemBlockedTerrain
    case 'wall_or_door_blocked':
      return copy.placementProblemWallOrDoorBlocked
    case 'overlapping_placement':
      return copy.placementProblemOverlappingPlacement
    case 'template_archived':
      return copy.placementProblemTemplateArchived
    case 'invalid_size':
      return copy.placementProblemInvalidSize
    default:
      return code
  }
}
