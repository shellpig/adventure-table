import { MonsterLibraryApiError, type MonsterPresentation } from '../../api/monsterLibrary'
import type { Locale } from '../../i18n/locale'

const COPY = {
  en: {
    title: 'Monster Library',
    intro: 'Manage reusable built-in and custom monster templates for encounters and combat.',
    backRoom: '← Back to Room workspace',
    searchPlaceholder: 'Search by monster name, type, or subtype…',
    filterAll: 'All Sources',
    filterBuiltin: 'Built-in',
    filterCustom: 'Custom',
    showArchived: 'Show archived',
    sourceBuiltin: 'Built-in',
    sourceCustom: 'Custom',
    badgeArchived: 'Archived',
    createAction: 'Create Custom Monster',
    createFromContentAction: 'Create custom monster from this',
    copyAction: 'Copy',
    archiveAction: 'Archive',
    deleteAction: 'Delete',
    saveAction: 'Save Changes',
    savingAction: 'Saving…',
    creatingAction: 'Creating…',
    copyingAction: 'Copying…',
    archivingAction: 'Archiving…',
    deletingAction: 'Deleting…',
    refreshAction: 'Refresh',
    loadMore: 'Load more',
    loadingMore: 'Loading…',
    cancel: 'Cancel',
    emptyList: 'No monster templates found.',
    loadingList: 'Loading monster templates…',
    loadingDetail: 'Loading monster details…',
    selectPrompt: 'Select a monster from the list to view or edit details.',
    englishOriginal: 'English original',
    englishOriginalNotice: 'Built-in descriptions are shown in their English original.',
    readOnlyNotice: 'Built-in monsters are read-only. Create a custom monster from this template to edit stats and abilities.',
    archivedNotice: 'This monster template is archived and will not appear in new combat menus.',
    deleteConfirm: 'Delete this custom monster template permanently? This action cannot be undone.',
    archiveConfirm: 'Archive this custom monster template? Archived templates will no longer appear in new combat menus.',
    inUseErrorHint: 'This template is referenced elsewhere. Archive it instead of deleting.',

    // Sections
    coreStatsHeading: 'Core Statistics',
    abilitiesHeading: 'Ability Scores',
    traitsHeading: 'Traits',
    actionsHeading: 'Actions',
    bonusActionsHeading: 'Bonus Actions',
    reactionsHeading: 'Reactions',
    legendaryActionsHeading: 'Legendary Actions',
    descriptionHeading: 'Description & Notes',

    // Fields
    fieldName: 'Name',
    fieldArmorClass: 'Armor Class (AC)',
    fieldMaxHp: 'Max Hit Points (HP)',
    fieldChallengeRating: 'Challenge Rating (CR)',
    fieldSize: 'Size',
    fieldType: 'Type',
    fieldAlignment: 'Alignment',
    fieldSpeed: 'Speed',
    fieldWalkSpeed: 'Walk speed',
    fieldStr: 'STR',
    fieldDex: 'DEX',
    fieldCon: 'CON',
    fieldInt: 'INT',
    fieldWis: 'WIS',
    fieldCha: 'CHA',
    fieldDescription: 'Description',
    fieldSenses: 'Senses',
    fieldLanguages: 'Languages',
    fieldDamageImmunities: 'Damage Immunities',
    fieldDamageResistances: 'Damage Resistances',
    fieldDamageVulnerabilities: 'Damage Vulnerabilities',
    fieldConditionImmunities: 'Condition Immunities',
    fieldXp: 'XP',

    // Items within traits/actions
    noTraits: 'No traits.',
    noActions: 'No actions.',
    traitName: 'Trait name',
    traitDesc: 'Trait description',
    actionName: 'Action name',
    actionDesc: 'Action description',
    addTrait: '+ Add Trait',
    addAction: '+ Add Action',
    remove: 'Remove',
    unsetOption: 'Not set',
    revisionLabel: 'Revision',

    // Modals / dialogs
    createModalTitle: 'Create Custom Monster',
    copyModalTitle: 'Copy Custom Monster',
    fromContentModalTitle: 'Create Custom Monster from Built-in',
    modalNameOptional: 'New template name (optional)',
    modalNameRequired: 'Monster name',
    submitCreate: 'Create',
    submitCopy: 'Copy Monster',

    // Errors
    missingAccess: 'This browser does not have access to this Room. Enter the Room again.',
    requestFailed: 'Monster library request failed.',
    errMonsterTemplateNotFound: 'Monster template not found.',
    errMonsterLibraryForbidden: 'Only the Room owner or DM can manage the monster library.',
    errMonsterTemplateReadOnly: 'Built-in monster templates are read-only and cannot be modified or deleted.',
    errMonsterTemplateRevisionConflict: 'Monster template revision conflict. Another update occurred; please reload and try again.',
    errMonsterTemplateReferenced: 'This monster template is in use (referenced by map placements, campaigns, or history) and cannot be deleted; archive it instead.',
    errMonsterTemplateArchived: 'This monster template is archived and cannot be used for this action.',
    errInvalidMonsterTemplateRef: 'Invalid monster template reference or invalid rules data.',
  },
  'zh-TW': {
    title: '怪物庫',
    intro: '管理房間內可重複使用的內建與自訂怪物範本，供跑團與戰鬥快速加入。',
    backRoom: '← 回房間工作區',
    searchPlaceholder: '搜尋怪物名稱、類型或子類型…',
    filterAll: '全部來源',
    filterBuiltin: '內建怪物',
    filterCustom: '自訂怪物',
    showArchived: '顯示已封存',
    sourceBuiltin: '內建',
    sourceCustom: '自訂',
    badgeArchived: '已封存',
    createAction: '從零建立自訂怪物',
    createFromContentAction: '以此建立自訂怪物',
    copyAction: '複製',
    archiveAction: '封存',
    deleteAction: '刪除',
    saveAction: '儲存變更',
    savingAction: '正在儲存…',
    creatingAction: '正在建立…',
    copyingAction: '正在複製…',
    archivingAction: '正在封存…',
    deletingAction: '正在刪除…',
    refreshAction: '重新整理',
    loadMore: '載入更多',
    loadingMore: '載入中…',
    cancel: '取消',
    emptyList: '找不到符合條件的怪物範本。',
    loadingList: '正在載入怪物範本…',
    loadingDetail: '正在載入怪物詳細資料…',
    selectPrompt: '請從左側清單選擇怪物以檢視或編輯詳細資料。',
    englishOriginal: '英文原文',
    englishOriginalNotice: '內建怪物的能力說明以英文原文顯示。',
    readOnlyNotice: '內建怪物為唯讀資料；您可以選取「以此建立自訂怪物」來修改數值與能力。',
    archivedNotice: '此怪物範本已封存，不會出現在新戰鬥的新增選單中。',
    deleteConfirm: '要永久刪除此自訂怪物範本嗎？此動作無法復原。',
    archiveConfirm: '要封存此自訂怪物範本嗎？已封存的範本將無法於新戰鬥中建立。',
    inUseErrorHint: '此範本已被地圖配置、戰役或歷史紀錄引用，無法刪除；請改用封存。',

    // Sections
    coreStatsHeading: '核心數值',
    abilitiesHeading: '屬性值',
    traitsHeading: '特性',
    actionsHeading: '動作',
    bonusActionsHeading: '附贈動作',
    reactionsHeading: '反應',
    legendaryActionsHeading: '傳奇動作',
    descriptionHeading: '描述與備註',

    // Fields
    fieldName: '名稱',
    fieldArmorClass: '護甲等級 (AC)',
    fieldMaxHp: '最大生命值 (HP)',
    fieldChallengeRating: '挑戰等級 (CR)',
    fieldSize: '體型',
    fieldType: '類型',
    fieldAlignment: '陣營',
    fieldSpeed: '速度',
    fieldWalkSpeed: '步行速度',
    fieldStr: '力量 (STR)',
    fieldDex: '敏捷 (DEX)',
    fieldCon: '體質 (CON)',
    fieldInt: '智力 (INT)',
    fieldWis: '感知 (WIS)',
    fieldCha: '魅力 (CHA)',
    fieldDescription: '描述',
    fieldSenses: '感官',
    fieldLanguages: '語言',
    fieldDamageImmunities: '傷害免疫',
    fieldDamageResistances: '傷害抗性',
    fieldDamageVulnerabilities: '傷害易傷',
    fieldConditionImmunities: '狀態免疫',
    fieldXp: '經驗值 (XP)',

    // Items within traits/actions
    noTraits: '無特殊特性。',
    noActions: '無動作。',
    traitName: '特性名稱',
    traitDesc: '特性說明',
    actionName: '動作名稱',
    actionDesc: '動作說明',
    addTrait: '+ 新增特性',
    addAction: '+ 新增動作',
    remove: '移除',
    unsetOption: '未設定',
    revisionLabel: '版本',

    // Modals / dialogs
    createModalTitle: '建立自訂怪物',
    copyModalTitle: '複製自訂怪物',
    fromContentModalTitle: '從內建建立自訂怪物',
    modalNameOptional: '新範本名稱（選填）',
    modalNameRequired: '怪物名稱',
    submitCreate: '建立',
    submitCopy: '複製怪物',

    // Errors
    missingAccess: '這個瀏覽器沒有此房間的存取權，請重新進入房間。',
    requestFailed: '怪物庫請求失敗。',
    errMonsterTemplateNotFound: '找不到此怪物範本。',
    errMonsterLibraryForbidden: '只有房間 Owner 或 DM 可以管理怪物庫。',
    errMonsterTemplateReadOnly: '內建怪物範本為唯讀，無法直接修改或刪除。',
    errMonsterTemplateRevisionConflict: '怪物範本版本衝突；已有其他修改完成，請重新整理頁面後再試。',
    errMonsterTemplateReferenced: '此怪物範本已被地圖配置、戰役或歷史引用，無法刪除；請改用封存。',
    errMonsterTemplateArchived: '此怪物範本已封存，無法在此操作中使用。',
    errInvalidMonsterTemplateRef: '怪物範本參照格式或數值無效。',
  },
} as const satisfies Record<Locale, Record<string, string>>

export type MonsterLibraryCopy = (typeof COPY)[Locale]

export function monsterLibraryCopy(locale: Locale): MonsterLibraryCopy {
  return COPY[locale]
}

export function monsterLibraryErrorMessage(
  error: unknown,
  copy: MonsterLibraryCopy,
): string {
  const code =
    error instanceof MonsterLibraryApiError
      ? error.code
      : typeof error === 'object' && error !== null && 'code' in error
        ? String((error as { code: unknown }).code)
        : null

  switch (code) {
    case 'monster_template_not_found':
      return copy.errMonsterTemplateNotFound
    case 'monster_library_forbidden':
      return copy.errMonsterLibraryForbidden
    case 'monster_template_read_only':
      return copy.errMonsterTemplateReadOnly
    case 'monster_template_revision_conflict':
      return copy.errMonsterTemplateRevisionConflict
    case 'monster_template_referenced':
      return copy.errMonsterTemplateReferenced
    case 'monster_template_archived':
      return copy.errMonsterTemplateArchived
    case 'invalid_monster_template_ref':
      return copy.errInvalidMonsterTemplateRef
    default:
      return copy.requestFailed
  }
}

export function formatMonsterName(
  monster: {
    name: string
    names?: Record<string, string>
    name_is_custom: boolean
  },
  locale: string,
): string {
  if (!monster.name_is_custom) {
    if (monster.names && monster.names[locale]) {
      return monster.names[locale]
    }
    if (monster.names && monster.names['en']) {
      return monster.names['en']
    }
  }
  return monster.name
}

export function formatAbilityName(
  ability: { name: string },
  idx: number,
  group: 'traits' | 'actions' | 'bonus_actions' | 'reactions' | 'legendary_actions',
  presentation: MonsterPresentation | undefined,
  locale: string,
): string {
  const meta = presentation?.ability_names?.[group]?.[idx]
  if (meta) {
    if (locale === 'zh-TW' && meta['zh-TW']) {
      return meta['zh-TW']
    }
    if (meta.en) {
      return meta.en
    }
  }
  return ability.name
}

export const SRD_SIZES = [
  'Tiny',
  'Small',
  'Medium',
  'Large',
  'Huge',
  'Gargantuan',
] as const

export type SrdSize = (typeof SRD_SIZES)[number]

export const SRD_TYPES = [
  'aberration',
  'beast',
  'celestial',
  'construct',
  'dragon',
  'elemental',
  'fey',
  'fiend',
  'giant',
  'humanoid',
  'monstrosity',
  'ooze',
  'plant',
  'swarm of Tiny beasts',
  'undead',
] as const

export type SrdType = (typeof SRD_TYPES)[number]

export const SRD_ALIGNMENTS = [
  'any alignment',
  'any chaotic alignment',
  'any evil alignment',
  'any non-good alignment',
  'any non-lawful alignment',
  'chaotic evil',
  'chaotic good',
  'chaotic neutral',
  'lawful evil',
  'lawful good',
  'lawful neutral',
  'neutral',
  'neutral evil',
  'neutral good',
  'neutral good (50%) or neutral evil (50%)',
  'unaligned',
] as const

export type SrdAlignment = (typeof SRD_ALIGNMENTS)[number]

export type MonsterRuleField = 'size' | 'type' | 'alignment'

export const RULE_FIELD_LABELS: Record<
  Locale,
  {
    size: Record<string, string>
    type: Record<string, string>
    alignment: Record<string, string>
  }
> = {
  en: {
    size: {
      Tiny: 'Tiny',
      Small: 'Small',
      Medium: 'Medium',
      Large: 'Large',
      Huge: 'Huge',
      Gargantuan: 'Gargantuan',
    },
    type: {
      aberration: 'aberration',
      beast: 'beast',
      celestial: 'celestial',
      construct: 'construct',
      dragon: 'dragon',
      elemental: 'elemental',
      fey: 'fey',
      fiend: 'fiend',
      giant: 'giant',
      humanoid: 'humanoid',
      monstrosity: 'monstrosity',
      ooze: 'ooze',
      plant: 'plant',
      'swarm of Tiny beasts': 'swarm of Tiny beasts',
      undead: 'undead',
    },
    alignment: {
      'any alignment': 'any alignment',
      'any chaotic alignment': 'any chaotic alignment',
      'any evil alignment': 'any evil alignment',
      'any non-good alignment': 'any non-good alignment',
      'any non-lawful alignment': 'any non-lawful alignment',
      'chaotic evil': 'chaotic evil',
      'chaotic good': 'chaotic good',
      'chaotic neutral': 'chaotic neutral',
      'lawful evil': 'lawful evil',
      'lawful good': 'lawful good',
      'lawful neutral': 'lawful neutral',
      neutral: 'neutral',
      'neutral evil': 'neutral evil',
      'neutral good': 'neutral good',
      'neutral good (50%) or neutral evil (50%)':
        'neutral good (50%) or neutral evil (50%)',
      unaligned: 'unaligned',
    },
  },
  'zh-TW': {
    size: {
      Tiny: '微型',
      Small: '小型',
      Medium: '中型',
      Large: '大型',
      Huge: '巨型',
      Gargantuan: '超巨型',
    },
    type: {
      aberration: '異怪',
      beast: '野獸',
      celestial: '天界生物',
      construct: '構裝生物',
      dragon: '龍',
      elemental: '元素生物',
      fey: '妖精',
      fiend: '邪魔',
      giant: '巨人',
      humanoid: '人形生物',
      monstrosity: '怪獸',
      ooze: '泥怪',
      plant: '植物',
      'swarm of Tiny beasts': '微型野獸集群',
      undead: '不死生物',
    },
    alignment: {
      'any alignment': '任何陣營',
      'any chaotic alignment': '任何混亂陣營',
      'any evil alignment': '任何邪惡陣營',
      'any non-good alignment': '任何非善良陣營',
      'any non-lawful alignment': '任何非守序陣營',
      'chaotic evil': '混亂邪惡',
      'chaotic good': '混亂善良',
      'chaotic neutral': '混亂中立',
      'lawful evil': '守序邪惡',
      'lawful good': '守序善良',
      'lawful neutral': '守序中立',
      neutral: '絕對中立',
      'neutral evil': '中立邪惡',
      'neutral good': '中立善良',
      'neutral good (50%) or neutral evil (50%)':
        '中立善良 (50%) 或中立邪惡 (50%)',
      unaligned: '無陣營',
    },
  },
}

export function formatMonsterRuleField(
  field: MonsterRuleField,
  value: string | null | undefined,
  locale: Locale | string,
): string {
  if (value === null || value === undefined || value === '') return ''
  const loc: Locale = locale === 'zh-TW' ? 'zh-TW' : 'en'
  const fieldDict = RULE_FIELD_LABELS[loc][field]
  if (fieldDict[value]) {
    return fieldDict[value]
  }
  const lower = value.toLowerCase()
  for (const [k, v] of Object.entries(fieldDict)) {
    if (k.toLowerCase() === lower) {
      return v
    }
  }
  return value
}

