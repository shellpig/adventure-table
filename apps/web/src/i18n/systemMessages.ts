import { isSupportedLocale, type Locale } from './locale'

type MessageParams = Record<string, unknown>
type MessageFormatter = string | ((params: MessageParams) => string)
type LocalizedMessage = Record<Locale, MessageFormatter>

const BUILDER_ISSUE_MESSAGES: Record<string, LocalizedMessage> = {
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
  duplicate_choice_option: {
    'zh-TW': '同一個選項不能在此選擇中重複。',
    en: 'The same option cannot be selected more than once for this choice.',
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
  multiclass_prerequisite_not_met: {
    'zh-TW': '目前能力值不符合兼職所需的先決條件。',
    en: 'The current ability scores do not meet the multiclass prerequisites.',
  },
  subclass_selected_too_early: {
    'zh-TW': '目前等級尚未到達可選擇子職業的時點。',
    en: 'The subclass was selected before the class reaches its subclass choice level.',
  },
  missing_subclass_at_timing: {
    'zh-TW': '此職業已到達子職業選擇等級，必須選擇子職業。',
    en: 'This class has reached its subclass choice level and requires a subclass selection.',
  },
  invalid_manual_hp_roll: {
    'zh-TW': '手動輸入的生命值擲骰結果超出此職業生命骰允許範圍。',
    en: 'The manually entered HP roll is outside the class hit-die range.',
  },
  stale_build_version: {
    'zh-TW': '此角色建構版本已不是最新版本，請重新載入後再操作。',
    en: 'This character build version is stale. Reload before continuing.',
  },
  stale_equipment_choice: {
    'zh-TW': '先前的起始裝備選擇已不再符合目前規則，請重新選擇。',
    en: 'A previous starting equipment selection is no longer valid. Please choose again.',
  },
  misplaced_equipment_choice: {
    'zh-TW': '偵測到放在舊位置的起始裝備選擇；系統已忽略該值，請在裝備步驟重新選擇。',
    en: 'A starting equipment selection is stored in the old location and is ignored. Choose it again in the equipment step.',
  },
  invalid_equipment_choice: {
    'zh-TW': '起始裝備選擇不符合目前規則。',
    en: 'The starting equipment selection is not valid for the current rules.',
  },
  invalid_spell_choice: {
    'zh-TW': '法術選擇包含目前無法選取的法術。',
    en: 'The spell selection contains a spell that is not currently eligible.',
  },
  spell_selection_count_mismatch: {
    'zh-TW': '目前選取的法術數量不符合此角色應選數量。',
    en: 'The selected spell count does not match the required count.',
  },
  prepared_spell_limit_exceeded: {
    'zh-TW': '已準備法術數量超過目前可準備的上限。',
    en: 'The prepared spell selection exceeds the current preparation limit.',
  },
  duplicate_spell_choice: {
    'zh-TW': '同一個法術不能在同一份法術選擇中重複。',
    en: 'The same spell cannot be selected more than once in the same spell selection.',
  },
  structural_rules_data_error: {
    'zh-TW': '角色結構規則資料有誤，暫時無法完成此建構。',
    en: 'The structural rules data is invalid, so this build cannot currently be completed.',
  },
  origin_rules_data_error: {
    'zh-TW': '角色出身規則資料有誤，暫時無法完成此建構。',
    en: 'The origin rules data is invalid, so this build cannot currently be completed.',
  },
  spellcasting_rules_data_error: {
    'zh-TW': '施法規則資料有誤，暫時無法完成此建構。',
    en: 'The spellcasting rules data is invalid, so this build cannot currently be completed.',
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

const DISABLED_REASON_MESSAGES: Record<string, LocalizedMessage> = {
  multiclass_ability_scores_incomplete: {
    'zh-TW': '兼職前請先完成能力值。',
    en: 'Complete ability scores before multiclassing.',
  },
  multiclass_prerequisite_not_met: {
    'zh-TW': ({ requirements }) => requirements
      ? `兼職需要符合：${String(requirements)}。`
      : '目前能力值不符合兼職所需的先決條件。',
    en: ({ requirements }) => requirements
      ? `Requires ${String(requirements)} to multiclass.`
      : 'The multiclass prerequisites are not met.',
  },
  feat_ability_scores_incomplete: {
    'zh-TW': '選擇專長前請先完成能力值。',
    en: 'Complete ability scores before choosing this feat.',
  },
  feat_prerequisite_not_met: {
    'zh-TW': ({ requirements }) => requirements
      ? `此專長需要符合：${String(requirements)}。`
      : '目前能力值不符合此專長的先決條件。',
    en: ({ requirements }) => requirements
      ? `Requires ${String(requirements)}.`
      : 'The feat prerequisites are not met.',
  },
  unsupported_feat_prerequisite: {
    'zh-TW': '此專長使用目前尚未支援的先決條件格式。',
    en: 'This feat uses a prerequisite shape that is not currently supported.',
  },
  spell_choices_future_step: {
    'zh-TW': '法術選擇需在法術步驟中完成。',
    en: 'Spell choices are completed in the spell step.',
  },
  starting_equipment_future_step: {
    'zh-TW': '起始裝備需在裝備步驟中完成。',
    en: 'Starting equipment choices are completed in the equipment step.',
  },
  ability_score_cap_reached: {
    'zh-TW': '此能力值已達一般規則允許的上限。',
    en: 'This ability score has reached the normal rules cap.',
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

function formatLocalizedMessage(
  table: Record<string, LocalizedMessage>,
  code: string | undefined,
  locale: Locale,
  params: MessageParams = {},
): string | undefined {
  if (!code) return undefined
  const formatter = table[code]?.[locale]
  if (!formatter) return undefined
  return typeof formatter === 'function' ? formatter(params) : formatter
}

function messageParams(value: unknown): MessageParams {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as MessageParams
    : {}
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
  params: MessageParams = {},
): string {
  const translated = formatLocalizedMessage(BUILDER_ISSUE_MESSAGES, code, locale, params)
  if (translated) return translated
  if (locale === 'en') return originalMessage || 'The character data has a rules problem that needs attention.'
  // M02 contract: an untranslated server message must never leak English into
  // normal zh-TW UI. Structured code + params is the long-term detail channel.
  return '目前的角色資料有一項需要修正的規則問題。'
}

export function localizedDisabledReason(
  originalMessage: string,
  locale: Locale = currentSystemLocale(),
  code?: string,
  params: MessageParams = {},
): string {
  const translated = formatLocalizedMessage(DISABLED_REASON_MESSAGES, code, locale, params)
  if (translated) return translated
  if (locale === 'en') return originalMessage || 'This option is unavailable.'
  return '此選項目前無法選擇；請先完成相關條件。'
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
  return `要求失敗（HTTP ${status}），請稍後再試。`
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

function installDynamicMessage(
  target: Record<string, unknown>,
  property: 'message' | 'disabled_reason',
  original: string,
): void {
  Object.defineProperty(target, property, {
    configurable: true,
    enumerable: true,
    get: () => property === 'message'
      ? localizedBuilderIssueMessage(
          String(target.code ?? ''),
          original,
          currentSystemLocale(),
          messageParams(target.message_params),
        )
      : localizedDisabledReason(
          original,
          currentSystemLocale(),
          typeof target.disabled_reason_code === 'string' ? target.disabled_reason_code : undefined,
          messageParams(target.disabled_reason_params),
        ),
  })
}

/**
 * Keep machine codes/paths locale-neutral while presenting system-owned strings
 * from the current locale. New parameterized server messages should send
 * `message_params`, or `disabled_reason_code` + `disabled_reason_params`, rather
 * than interpolating canonical English rules names into `message`.
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
