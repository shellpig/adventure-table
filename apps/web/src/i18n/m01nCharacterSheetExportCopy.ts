import type { Locale } from './locale'

export type CharacterSheetExportCopy = {
  button: string
  scopeLabel: string
  buildScope: string
  snapshotScope: string
  documentTitle: string
  buildVersion: string
  exportedAt: string
  maxHp: string
  total: string
  capacity: string
  preparedLimit: string
  acNote: string
  quantity: string
}

const COPY: Record<Locale, CharacterSheetExportCopy> = {
  en: {
    button: 'Export HTML',
    scopeLabel: 'Export scope',
    buildScope: 'Build only',
    snapshotScope: 'Current snapshot',
    documentTitle: 'Character Sheet',
    buildVersion: 'Build Version',
    exportedAt: 'Exported at',
    maxHp: 'Max HP',
    total: 'Total',
    capacity: 'Capacity',
    preparedLimit: 'Prepared limit',
    acNote: 'AC includes currently equipped items.',
    quantity: 'Quantity',
  },
  'zh-TW': {
    button: '匯出 HTML',
    scopeLabel: '輸出範圍',
    buildScope: '角色配置',
    snapshotScope: '當前快照',
    documentTitle: '角色卡',
    buildVersion: '角色版本',
    exportedAt: '輸出時間',
    maxHp: '最大 HP',
    total: '總量',
    capacity: '容量',
    preparedLimit: '準備上限',
    acNote: 'AC 依目前已裝備物品計算。',
    quantity: '數量',
  },
}

export function characterSheetExportCopy(locale: Locale): CharacterSheetExportCopy {
  return COPY[locale]
}
