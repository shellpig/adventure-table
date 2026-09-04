import { currentSystemLocale } from './systemMessages'
import type { Locale } from './locale'

export const CHARACTER_IMPORT_REQUEST_CODE_MESSAGES: Record<string, Record<Locale, string>> = {
  invalid_envelope_shape: {
    'zh-TW': '匯入檔案的外層格式無效，請確認這是 Adventure Table 匯出的角色 JSON。',
    en: 'The import envelope is invalid. Use an Adventure Table character JSON export.',
  },
  invalid_payload_shape: {
    'zh-TW': '匯入檔案的角色內容格式無效。',
    en: 'The character payload in this import is invalid.',
  },
  unsupported_schema_status: {
    'zh-TW': '這份匯入檔使用目前不支援的 Schema 狀態。',
    en: 'This import uses a schema status that is not supported.',
  },
  unsupported_ruleset: {
    'zh-TW': '這份角色使用目前未啟用或不支援的規則集。',
    en: 'This character uses a ruleset that is not enabled or supported here.',
  },
  ruleset_mismatch: {
    'zh-TW': '匯入檔中的規則集資訊彼此不一致。',
    en: 'The ruleset declarations in this import do not agree.',
  },
  version_chain_gap: {
    'zh-TW': '版本歷史有缺號，無法安全匯入。',
    en: 'The Version History has a gap and cannot be imported safely.',
  },
  version_chain_out_of_order: {
    'zh-TW': '版本歷史順序不正確。',
    en: 'The Version History is out of order.',
  },
  current_state_version_missing: {
    'zh-TW': '目前狀態指向不存在的角色版本。',
    en: 'Current State points to a Version that is not present.',
  },
  version_lineage_invalid: {
    'zh-TW': '版本歷史引用了不存在的版本。',
    en: 'The Version History references a Version that is not present.',
  },
  version_lineage_self_reference: {
    'zh-TW': '版本歷史包含指向自己的版本關係。',
    en: 'The Version History contains a self-reference.',
  },
  version_lineage_direction_invalid: {
    'zh-TW': '版本歷史的前後關係方向不正確。',
    en: 'The Version History contains an invalid parent or superseded direction.',
  },
  version_lineage_cycle: {
    'zh-TW': '版本歷史包含循環關係，無法匯入。',
    en: 'The Version History contains a cycle and cannot be imported.',
  },
  invalid_version_kind: {
    'zh-TW': '匯入檔包含不支援的版本類型。',
    en: 'The import contains an unsupported Version kind.',
  },
  invalid_build_shape: {
    'zh-TW': '某個版本的角色 Build 格式無效。',
    en: 'A Version contains an invalid character Build.',
  },
  invalid_builder_provenance: {
    'zh-TW': '某個版本的 Builder 建構來源資料格式無效。',
    en: 'A Version contains invalid Builder provenance.',
  },
  state_shape_invalid: {
    'zh-TW': '目前狀態資料格式無效。',
    en: 'Current State has an invalid shape.',
  },
  build_references_invalid: {
    'zh-TW': '角色 Build 的內容引用不符合目前資料集或規則。',
    en: 'The character Build references are invalid for the current content and rules.',
  },
  state_inconsistent_with_build: {
    'zh-TW': '目前狀態與目前角色 Build 不一致。',
    en: 'Current State is inconsistent with the current character Build.',
  },
  draft_reconstruction_unavailable: {
    'zh-TW': '本機缺少部分內容，而且匯入檔沒有足夠的 Builder 資料可建立待補完草稿。',
    en: 'Some content is unavailable and the import does not contain enough Builder provenance to reconstruct a Draft.',
  },
  payload_too_large: {
    'zh-TW': '匯入檔超過 5 MB 上限。',
    en: 'The import exceeds the 5 MB limit.',
  },
}

export function localizedCharacterImportRequestMessage(
  code: string | undefined,
  status: number,
  originalMessage: string,
  locale: Locale = currentSystemLocale(),
): string {
  if (code && CHARACTER_IMPORT_REQUEST_CODE_MESSAGES[code]) {
    return CHARACTER_IMPORT_REQUEST_CODE_MESSAGES[code][locale]
  }
  if (locale === 'en') return originalMessage || `Request failed (${status})`
  return `要求失敗（HTTP ${status}），請稍後再試。`
}

export function createLocalizedCharacterImportRequestError(
  code: string | undefined,
  status: number,
  originalMessage: string,
  locale?: Locale,
): Error {
  return new Error(
    localizedCharacterImportRequestMessage(
      code,
      status,
      originalMessage,
      locale ?? currentSystemLocale(),
    ),
  )
}
