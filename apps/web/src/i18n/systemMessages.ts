import { isSupportedLocale, type Locale } from './locale'

const BUILDER_ISSUE_MESSAGES: Record<string, Record<Locale, string>> = {
  unknown_reference: {
    'zh-TW': '先前選取的規則項目已不存在，請重新選擇。',
    en: 'The previously selected rules entry no longer exists. Please choose again.',
  },
  wrong_reference_kind: {
    'zh-TW': '選取的規則項目類型不正確，請重新選擇。',
    en: 'The selected rules entry has the wrong type. Please choose again.',
  },
  missing_ability_generation: {
    'zh-TW': '確認角色前必須完成能力值產生方式。',
    en: 'Ability generation is required before Confirm.',
  },
  invalid_standard_array_assignment: {
    'zh-TW': '標準陣列的每個數值都必須剛好使用一次。',
    en: 'Every Standard Array value must be assigned exactly once.',
  },
  point_buy_score_out_of_range: {
    'zh-TW': '購點能力值超出允許範圍。',
    en: 'A Point Buy score is outside the allowed range.',
  },
  point_buy_budget_exceeded: {
    'zh-TW': '購點使用的點數超過可用預算。',
    en: 'The Point Buy selection exceeds the available budget.',
  },
  manual_ability_outside_standard_generation: {
    'zh-TW': '手動能力值含有一般擲骰範圍外的數值；系統會保留並標示為非標準。',
    en: 'Manual ability scores include values outside the normal roll range; they are preserved as non-standard.',
  },
  invalid_choice_count: {
    'zh-TW': '此選擇尚未選滿要求的項目數量。',
    en: 'This choice does not yet contain the required number of selections.',
  },
  invalid_choice_option: {
    'zh-TW': '此選擇包含目前已不符合資格的項目，請重新選擇。',
    en: 'This choice contains an option that is no longer eligible. Please choose again.',
  },
  duplicate_starting_choice: {
    'zh-TW': '同一個起始項目不能重複選取。',
    en: 'The same starting option cannot be selected more than once.',
  },
  missing_character_name: {
    'zh-TW': '確認角色前必須填寫角色名稱。',
    en: 'Character name is required before Confirm.',
  },
  name_whitespace_will_be_trimmed: {
    'zh-TW': '角色名稱前後的空白會在儲存時移除。',
    en: 'Leading or trailing whitespace in the character name will be trimmed.',
  },
  missing_target_level: {
    'zh-TW': '確認角色前必須設定目標等級。',
    en: 'Target character level is required before Confirm.',
  },
  missing_race: {
    'zh-TW': '確認角色前必須選擇種族。',
    en: 'Race selection is required before Confirm.',
  },
  missing_subrace: {
    'zh-TW': '目前選擇的種族需要再選擇一個亞種。',
    en: 'The selected race requires a subrace selection.',
  },
  subrace_requires_race: {
    'zh-TW': '必須先選擇種族，才能選擇亞種。',
    en: 'A race must be selected before choosing a subrace.',
  },
  subrace_race_mismatch: {
    'zh-TW': '目前選擇的亞種不屬於所選種族。',
    en: 'The selected subrace does not belong to the selected race.',
  },
  missing_background: {
    'zh-TW': '確認角色前必須選擇背景。',
    en: 'Background selection is required before Confirm.',
  },
  incomplete_level_progression: {
    'zh-TW': '每個目標角色等級都必須有一筆依序的職業升級選擇。',
    en: 'Every target character level must have one ordered class progression choice.',
  },
  duplicate_numeric_override: {
    'zh-TW': '同一個數值覆寫項目只能設定一次。',
    en: 'Each numeric override key may only be configured once.',
  },
  numeric_override: {
    'zh-TW': '此數值已使用手動覆寫，並取代系統計算結果。',
    en: 'This value uses a manual override instead of the calculated result.',
  },
}

const REQUEST_CODE_MESSAGES: Record<string, Record<Locale, string>> = {
  not_found: {
    'zh-TW': '找不到要求的資料，可能已被刪除或變更。',
    en: 'The requested data could not be found. It may have been removed or changed.',
  },
  revision_conflict: {
    'zh-TW': '資料已在其他操作中更新，請重新載入後再試一次。',
    en: 'The data changed in another operation. Reload and try again.',
  },
  validation_error: {
    'zh-TW': '送出的資料未通過驗證，請檢查目前選擇。',
    en: 'The submitted data did not pass validation. Check the current selections.',
  },
  invalid_request: {
    'zh-TW': '這次要求無法處理，請檢查目前資料後再試一次。',
    en: 'This request could not be processed. Check the current data and try again.',
  },
}

export function currentSystemLocale(): Locale {
  if (typeof document !== 'undefined' && isSupportedLocale(document.documentElement.lang)) {
    return document.documentElement.lang
  }
  return 'zh-TW'
}

export function localizedBuilderIssueMessage(
  code: string,
  originalMessage: string,
  locale: Locale = currentSystemLocale(),
): string {
  const translated = BUILDER_ISSUE_MESSAGES[code]?.[locale]
  if (translated) return translated
  if (locale === 'en') return originalMessage
  return originalMessage.trim()
    ? `規則問題：${originalMessage}`
    : '目前的角色資料有一項需要修正的規則問題。'
}

export function localizedDisabledReason(
  originalMessage: string,
  locale: Locale = currentSystemLocale(),
): string {
  if (locale === 'en') return originalMessage

  const message = originalMessage.trim()
  if (message === 'Complete ability scores before multiclassing.') {
    return '兼職前請先完成能力值。'
  }
  const scopedMulticlass = message.match(/^(.+): Requires (.+) to multiclass\.$/)
  if (scopedMulticlass) {
    return `${scopedMulticlass[1]}：兼職需要 ${scopedMulticlass[2]}。`
  }
  const multiclass = message.match(/^Requires (.+) to multiclass\.$/)
  if (multiclass) {
    return `兼職需要 ${multiclass[1]}。`
  }
  if (message === 'Spell choices are completed in P1-E.') {
    return '法術選擇需在法術步驟中完成。'
  }
  if (message === 'Starting equipment choices are completed in P1-F.') {
    return '起始裝備需在裝備步驟中完成。'
  }
  return message ? `目前無法選擇：${message}` : '此選項目前無法選擇。'
}

export function localizedRequestErrorMessage(
  code: string | undefined,
  status: number,
  originalMessage: string,
  locale: Locale = currentSystemLocale(),
): string {
  if (code && REQUEST_CODE_MESSAGES[code]) return REQUEST_CODE_MESSAGES[code][locale]
  if (status === 404) return REQUEST_CODE_MESSAGES.not_found[locale]
  if (status === 409) return REQUEST_CODE_MESSAGES.revision_conflict[locale]
  if (locale === 'en') return originalMessage || `Request failed (${status})`
  return originalMessage.trim()
    ? `要求失敗（HTTP ${status}）：${originalMessage}`
    : `要求失敗（HTTP ${status}），請稍後再試。`
}

export function createLocalizedRequestError(
  code: string | undefined,
  status: number,
  originalMessage: string,
  locale?: Locale,
): Error {
  const error = new Error()
  Object.defineProperty(error, 'message', {
    configurable: true,
    enumerable: false,
    get: () => localizedRequestErrorMessage(code, status, originalMessage, locale ?? currentSystemLocale()),
  })
  return error
}

function installDynamicMessage(target: Record<string, unknown>, property: 'message' | 'disabled_reason', original: string): void {
  Object.defineProperty(target, property, {
    configurable: true,
    enumerable: true,
    get: () => property === 'message'
      ? localizedBuilderIssueMessage(String(target.code ?? ''), original)
      : localizedDisabledReason(original),
  })
}

/**
 * Keep machine codes/paths locale-neutral while presenting system-owned strings
 * from the current locale. Getters intentionally resolve locale at render time,
 * so switching locale updates already-cached React Query data without mutating
 * the draft or forcing a network refetch.
 */
export function installDynamicLocalizedBuilderPayload<T>(value: T): T {
  const visit = (current: unknown): void => {
    if (Array.isArray(current)) {
      current.forEach(visit)
      return
    }
    if (!current || typeof current !== 'object') return
    const record = current as Record<string, unknown>

    if (
      typeof record.code === 'string' &&
      typeof record.path === 'string' &&
      typeof record.message === 'string'
    ) {
      installDynamicMessage(record, 'message', record.message)
    }
    if (
      typeof record.disabled_reason === 'string' &&
      (typeof record.option_id === 'string' || typeof record.choice_id === 'string')
    ) {
      installDynamicMessage(record, 'disabled_reason', record.disabled_reason)
    }

    for (const child of Object.values(record)) visit(child)
  }

  visit(value)
  return value
}
