import { isSupportedLocale, type Locale } from './locale'

type MessageParams = Record<string, unknown>
type MessageFormatter = string | ((params: MessageParams) => string)
type LocalizedMessage = Record<Locale, MessageFormatter>

type AbilityRequirement = { ability: string; minimum_score: number }
type AbilityRequirementGroup = { choose: number; options: AbilityRequirement[] }

const ABILITY_LABELS: Record<Locale, Record<string, string>> = {
  'zh-TW': {
    strength: '力量',
    dexterity: '敏捷',
    constitution: '體質',
    intelligence: '智力',
    wisdom: '感知',
    charisma: '魅力',
  },
  en: {
    strength: 'Strength',
    dexterity: 'Dexterity',
    constitution: 'Constitution',
    intelligence: 'Intelligence',
    wisdom: 'Wisdom',
    charisma: 'Charisma',
  },
}

function abilityRequirement(value: unknown): AbilityRequirement | undefined {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined
  const record = value as Record<string, unknown>
  if (typeof record.ability !== 'string' || typeof record.minimum_score !== 'number') return undefined
  return { ability: record.ability, minimum_score: record.minimum_score }
}

function requirementGroup(value: unknown): AbilityRequirementGroup | undefined {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined
  const record = value as Record<string, unknown>
  if (typeof record.choose !== 'number' || !Array.isArray(record.options)) return undefined
  const options = record.options.map(abilityRequirement).filter((item): item is AbilityRequirement => Boolean(item))
  return options.length ? { choose: record.choose, options } : undefined
}

function formatAbilityRequirement(requirement: AbilityRequirement, locale: Locale): string {
  const label = ABILITY_LABELS[locale][requirement.ability] ?? requirement.ability
  return `${label} ${requirement.minimum_score}+`
}

function structuredRequirements(params: MessageParams, locale: Locale): string | undefined {
  const requirements = Array.isArray(params.requirements)
    ? params.requirements.map(abilityRequirement).filter((item): item is AbilityRequirement => Boolean(item))
    : []
  const groups = Array.isArray(params.requirement_groups)
    ? params.requirement_groups.map(requirementGroup).filter((item): item is AbilityRequirementGroup => Boolean(item))
    : []
  const parts = requirements.map((item) => formatAbilityRequirement(item, locale))
  for (const group of groups) {
    const labels = group.options.map((item) => formatAbilityRequirement(item, locale))
    if (group.choose === 1) {
      parts.push(labels.join(locale === 'zh-TW' ? ' 或 ' : ' or '))
    } else {
      parts.push(locale === 'zh-TW'
        ? `任選 ${group.choose} 項：${labels.join('、')}`
        : `choose ${group.choose}: ${labels.join(', ')}`)
    }
  }
  return parts.length ? parts.join(locale === 'zh-TW' ? '；' : '; ') : undefined
}

const BUILDER_ISSUE_MESSAGES: Record<string, LocalizedMessage> = {
  unknown_reference: { 'zh-TW': '先前選取的規則項目已不存在，請重新選擇。', en: 'The previously selected rules entry no longer exists. Please choose again.' },
  wrong_reference_kind: { 'zh-TW': '選取的規則項目類型不正確，請重新選擇。', en: 'The selected rules entry has the wrong type. Please choose again.' },
  missing_ability_generation: { 'zh-TW': '確認角色前必須完成能力值產生方式。', en: 'Ability generation is required before Confirm.' },
  invalid_standard_array_assignment: { 'zh-TW': '標準陣列的每個數值都必須剛好使用一次。', en: 'Every Standard Array value must be assigned exactly once.' },
  point_buy_score_out_of_range: { 'zh-TW': '購點能力值超出允許範圍。', en: 'A Point Buy score is outside the allowed range.' },
  point_buy_budget_exceeded: { 'zh-TW': '購點使用的點數超過可用預算。', en: 'The Point Buy selection exceeds the available budget.' },
  manual_ability_outside_standard_generation: { 'zh-TW': '手動能力值含有一般擲骰範圍外的數值；系統會保留並標示為非標準。', en: 'Manual ability scores include values outside the normal roll range; they are preserved as non-standard.' },
  invalid_choice_count: { 'zh-TW': '此選擇尚未選滿要求的項目數量。', en: 'This choice does not yet contain the required number of selections.' },
  invalid_choice_option: { 'zh-TW': '此選擇包含目前已不符合資格的項目，請重新選擇。', en: 'This choice contains an option that is no longer eligible. Please choose again.' },
  duplicate_choice_option: { 'zh-TW': '同一個選項不能在此選擇中重複。', en: 'The same option cannot be selected more than once for this choice.' },
  disabled_choice_option_selected: { 'zh-TW': '目前選取的項目有一項尚未符合先決條件，請重新選擇。', en: 'A selected option does not currently satisfy its prerequisite.' },
  duplicate_starting_choice: { 'zh-TW': '同一個起始項目不能重複選取。', en: 'The same starting option cannot be selected more than once.' },
  missing_character_name: { 'zh-TW': '確認角色前必須填寫角色名稱。', en: 'Character name is required before Confirm.' },
  name_whitespace_will_be_trimmed: { 'zh-TW': '角色名稱前後的空白會在儲存時移除。', en: 'Leading or trailing whitespace in the character name will be trimmed.' },
  missing_target_level: { 'zh-TW': '確認角色前必須設定目標等級。', en: 'Target character level is required before Confirm.' },
  missing_race: { 'zh-TW': '確認角色前必須選擇種族。', en: 'Race selection is required before Confirm.' },
  missing_subrace: { 'zh-TW': '目前選擇的種族需要再選擇一個亞種。', en: 'The selected race requires a subrace selection.' },
  subrace_requires_race: { 'zh-TW': '必須先選擇種族，才能選擇亞種。', en: 'A race must be selected before choosing a subrace.' },
  subrace_race_mismatch: { 'zh-TW': '目前選擇的亞種不屬於所選種族。', en: 'The selected subrace does not belong to the selected race.' },
  missing_background: { 'zh-TW': '確認角色前必須選擇背景。', en: 'Background selection is required before Confirm.' },
  incomplete_level_progression: { 'zh-TW': '每個目標角色等級都必須有一筆依序的職業升級選擇。', en: 'Every target character level must have one ordered class progression choice.' },
  unordered_character_level: { 'zh-TW': '職業升級節點的角色等級順序不正確。', en: 'A progression node has the wrong character-level position.' },
  invalid_class_reference: { 'zh-TW': '目前職業選擇指向不存在或無效的職業，請重新選擇。', en: 'The selected class reference is invalid.' },
  invalid_first_level_hp: { 'zh-TW': '角色 1 級必須使用起始職業生命骰的最大值作為基礎生命值。', en: 'Character level 1 must use the starting class maximum hit die.' },
  first_level_hp_only_at_character_level_one: { 'zh-TW': '只有角色 1 級可以使用首級最大生命值規則。', en: 'The first-level maximum HP rule only applies at character level 1.' },
  invalid_fixed_hp_gain: { 'zh-TW': '固定生命值增量與目前職業規則不符。', en: 'The fixed HP gain does not match the current class rules.' },
  invalid_manual_hp_roll: { 'zh-TW': '手動輸入的生命值擲骰結果超出此職業生命骰允許範圍。', en: 'The manually entered HP roll is outside the class hit-die range.' },
  invalid_subclass_reference: { 'zh-TW': '目前子職業選擇指向不存在或無效的子職業，請重新選擇。', en: 'The selected subclass reference is invalid.' },
  subclass_class_mismatch: { 'zh-TW': '目前選擇的子職業不屬於所選職業。', en: 'The selected subclass does not belong to the selected class.' },
  multiclass_prerequisite_not_met: {
    'zh-TW': (params) => structuredRequirements(params, 'zh-TW') ? `兼職需要符合：${structuredRequirements(params, 'zh-TW')}。` : '目前能力值不符合兼職所需的先決條件。',
    en: (params) => structuredRequirements(params, 'en') ? `Requires ${structuredRequirements(params, 'en')} to multiclass.` : 'The current ability scores do not meet the multiclass prerequisites.',
  },
  subclass_selected_too_early: { 'zh-TW': '目前等級尚未到達可選擇子職業的時點。', en: 'The subclass was selected before the class reaches its subclass choice level.' },
  missing_subclass_at_timing: { 'zh-TW': '此職業已到達子職業選擇等級，必須選擇子職業。', en: 'This class has reached its subclass choice level and requires a subclass selection.' },
  duplicate_subclass_selection: { 'zh-TW': '同一職業只能保留一個有效的子職業選擇。', en: 'A class must have exactly one subclass selection.' },
  subclass_selected_at_wrong_level: { 'zh-TW': '子職業必須在該職業規定的等級時點選擇。', en: 'The subclass must be selected at the class-defined level.' },
  invalid_spell_choice_count: { 'zh-TW': '目前選取的法術數量不符合此施法來源要求。', en: 'The selected spell count does not match this spellcasting source requirement.' },
  invalid_spell_reference: { 'zh-TW': '法術選擇包含不存在或無效的法術，請重新選擇。', en: 'The spell selection contains an invalid spell reference.' },
  spell_not_on_source_list: { 'zh-TW': '選取的法術不在此施法來源可用的法術列表中。', en: 'The selected spell is not on this spellcasting source list.' },
  invalid_spell_level: { 'zh-TW': '選取的法術等級不符合目前施法來源的可選範圍。', en: 'The selected spell level is not eligible for this spellcasting source.' },
  prepared_spell_limit_exceeded: { 'zh-TW': '已準備法術數量超過目前可準備的上限。', en: 'The prepared spell selection exceeds the current preparation limit.' },
  invalid_prepared_spell: { 'zh-TW': '已準備法術中有目前無法準備的法術。', en: 'The prepared spell selection contains an ineligible spell.' },
  prepared_spell_not_in_spellbook: { 'zh-TW': '法師只能準備目前法術書中已有的法術。', en: 'A Wizard can only prepare spells currently in the spellbook.' },
  impossible_spell_acquisition_order: { 'zh-TW': '最終法術清單無法由合法的逐級取得或替換流程產生，請調整選擇。', en: 'The final spell selection cannot be produced by legal level-by-level acquisition or replacement.' },
  spell_access_model_mismatch: { 'zh-TW': '目前法術選擇方式與此施法來源的法術存取模式不相容。', en: 'The spell selection does not match this spellcasting source access model.' },
  invalid_spell_profile: { 'zh-TW': '此法術選擇屬於目前角色職業進程中不存在的施法設定。', en: 'This spell selection belongs to a spellcasting profile that is not present in the current progression.' },
  equipment_rules_data_error: { 'zh-TW': '起始裝備規則資料有誤，暫時無法完成此裝備選擇。', en: 'The starting equipment rules data is invalid.' },
  invalid_equipment_choice_count: { 'zh-TW': '目前起始裝備的選取數量不符合規則要求。', en: 'The starting equipment choice has the wrong number of selections.' },
  invalid_equipment_option: { 'zh-TW': '起始裝備包含目前已無法選取的項目，請重新選擇。', en: 'The starting equipment choice contains an ineligible option.' },
  duplicate_equipment_option: { 'zh-TW': '同一個起始裝備選項不能重複選取。', en: 'The same starting equipment option cannot be selected more than once.' },
  stale_equipment_choice: { 'zh-TW': '先前的起始裝備選擇已不再符合目前規則，請重新選擇。', en: 'A previous starting equipment selection is no longer valid. Please choose again.' },
  equipment_entry_id_collision: { 'zh-TW': '起始裝備產生了重複的內部識別碼，暫時無法完成建構。', en: 'Starting equipment produced duplicate deterministic entry ids.' },
  misplaced_equipment_choice: { 'zh-TW': '偵測到放在舊位置的起始裝備選擇；系統已忽略該值，請在裝備步驟重新選擇。', en: 'A starting equipment selection is stored in the old location and is ignored. Choose it again in the equipment step.' },
  structural_rules_data_error: { 'zh-TW': '角色結構規則資料有誤，暫時無法完成此建構。', en: 'The structural rules data is invalid, so this build cannot currently be completed.' },
  origin_rules_data_error: { 'zh-TW': '角色出身規則資料有誤，暫時無法完成此建構。', en: 'The origin rules data is invalid, so this build cannot currently be completed.' },
  spellcasting_rules_data_error: { 'zh-TW': '施法規則資料有誤，暫時無法完成此建構。', en: 'The spellcasting rules data is invalid, so this build cannot currently be completed.' },
  resource_usage_clamped: { 'zh-TW': '既有資源使用量超過新版本容量，系統已將使用量限制在新容量內。', en: 'Existing resource usage exceeded the new capacity and was clamped.' },
  hp_damage_delta_clamped: { 'zh-TW': '保留既有傷害後會低於 0 HP，系統已將目前 HP 限制為 0。', en: 'Preserved damage would reduce current HP below zero, so current HP was clamped to zero.' },
  spell_slot_pool_removed: { 'zh-TW': '新角色版本已不再擁有這個法術位階，因此移除其法術位資源。', en: 'The new build no longer has this spell-slot level, so the resource was removed.' },
  spell_resource_pool_removed: { 'zh-TW': '新角色版本已不再擁有這個建構來源的資源池，因此已移除。', en: 'The new build no longer has this build-derived resource pool, so it was removed.' },
  hit_dice_usage_clamped: { 'zh-TW': '已消耗生命骰數量超過新版本可用總數，系統已將可用數量限制為 0。', en: 'Spent hit dice exceeded the new total and available hit dice were clamped to zero.' },
  hit_die_type_removed: { 'zh-TW': '新角色版本已不再擁有此種類生命骰，因此移除其即時狀態。', en: 'The new build no longer has this hit-die type, so its live counter was removed.' },
  state_reconciliation_invalid: { 'zh-TW': '目前角色狀態無法安全套用到新的角色版本，請先修正衝突。', en: 'The current character state cannot be safely reconciled to the proposed build.' },
  prepared_spell_reconciliation_required: { 'zh-TW': '目前已準備法術中有項目在新角色版本下不再合法，請先調整準備清單。', en: 'At least one currently prepared spell is no longer legal under the proposed build.' },
  stale_build_version: { 'zh-TW': '此角色建構版本已不是最新版本，請重新載入後再操作。', en: 'This character build version is stale. Reload before continuing.' },
  duplicate_numeric_override: { 'zh-TW': '同一個數值覆寫項目只能設定一次。', en: 'Each numeric override key may only be configured once.' },
  numeric_override: { 'zh-TW': '此數值已使用手動覆寫，並取代系統計算結果。', en: 'This value uses a manual override instead of the calculated result.' },
  invalid_version_target_level: { 'zh-TW': '此次操作的目標角色等級不正確，請重新載入後再試一次。', en: 'This draft does not target the expected character level.' },
  level_up_origin_changed: { 'zh-TW': '升級不能修改種族、背景或陣營；請改用重建或修正流程。', en: 'Level Up cannot rewrite race, background or alignment. Use Build Edit or Correction.' },
  level_up_historical_progression_changed: { 'zh-TW': '升級不能修改既有等級的職業選擇；請改用重建或修正流程。', en: 'Level Up cannot rewrite class choices from the base build. Use Build Edit or Correction.' },
  level_up_historical_hp_changed: { 'zh-TW': '升級不能修改既有等級的生命值歷程；請改用重建或修正流程。', en: 'Level Up cannot rewrite historical HP progression from the base build. Use Build Edit or Correction.' },
  level_up_starting_equipment_changed: { 'zh-TW': '升級必須保留原本的起始裝備，不能在此變更。', en: 'Level Up must preserve the original starting equipment.' },
  level_up_numeric_override_changed: { 'zh-TW': '數值覆寫不是升級可以調整的項目；請改用重建或修正流程。', en: 'Numeric overrides are not a Level Up choice. Use Build Edit or Correction.' },
  build_candidate_missing: { 'zh-TW': '伺服器無法從目前的草稿產生完整的角色建構，請檢查前面步驟是否還有未完成的選擇。', en: 'The server could not compile a final character build from this draft.' },
  initial_state_missing: { 'zh-TW': '伺服器無法建立這個角色的初始狀態，請檢查前面步驟是否還有未完成的選擇。', en: 'The server could not build the initial current state.' },
  final_character_validation_failed: { 'zh-TW': '最終角色驗證未通過，請檢查前面步驟的選擇是否互相衝突。', en: 'Final character validation failed.' },
}

const DISABLED_REASON_MESSAGES: Record<string, LocalizedMessage> = {
  multiclass_ability_scores_incomplete: { 'zh-TW': '兼職前請先完成能力值。', en: 'Complete ability scores before multiclassing.' },
  multiclass_prerequisite_not_met: {
    'zh-TW': (params) => structuredRequirements(params, 'zh-TW') ? `兼職需要符合：${structuredRequirements(params, 'zh-TW')}。` : '目前能力值不符合兼職所需的先決條件。',
    en: (params) => structuredRequirements(params, 'en') ? `Requires ${structuredRequirements(params, 'en')} to multiclass.` : 'The multiclass prerequisites are not met.',
  },
  feat_ability_scores_incomplete: { 'zh-TW': '選擇專長前請先完成能力值。', en: 'Complete ability scores before choosing this feat.' },
  feat_prerequisite_not_met: {
    'zh-TW': (params) => structuredRequirements(params, 'zh-TW') ? `此專長需要符合：${structuredRequirements(params, 'zh-TW')}。` : '目前能力值不符合此專長的先決條件。',
    en: (params) => structuredRequirements(params, 'en') ? `Requires ${structuredRequirements(params, 'en')}.` : 'The feat prerequisites are not met.',
  },
  unsupported_feat_prerequisite: { 'zh-TW': '此專長使用目前尚未支援的先決條件格式。', en: 'This feat uses a prerequisite shape that is not currently supported.' },
  nested_choice_parent_required: { 'zh-TW': '必須先選擇對應的上層選項，才能使用此子選擇。', en: 'Choose the corresponding parent option first.' },
  unsupported_equipment_option: { 'zh-TW': '此起始裝備選項格式目前尚未支援。', en: 'This starting equipment option shape is not currently supported.' },
  spell_choices_future_step: { 'zh-TW': '法術選擇需在法術步驟中完成。', en: 'Spell choices are completed in the spell step.' },
  starting_equipment_future_step: { 'zh-TW': '起始裝備需在裝備步驟中完成。', en: 'Starting equipment choices are completed in the equipment step.' },
  asi_ability_scores_incomplete: { 'zh-TW': '分配能力值提升前請先完成能力值。', en: 'Complete ability scores before assigning an Ability Score Improvement.' },
  asi_branch_required: { 'zh-TW': '請先選擇「能力值提升」，再分配能力值點數。', en: 'Choose Ability Score Improvement before assigning ability points.' },
  ability_score_cap_reached: {
    'zh-TW': ({ ability, maximum }) => typeof ability === 'string' && typeof maximum === 'number' ? `${ABILITY_LABELS['zh-TW'][ability] ?? ability} 不能超過 ${maximum}。` : '此能力值已達一般規則允許的上限。',
    en: ({ ability, maximum }) => typeof ability === 'string' && typeof maximum === 'number' ? `${ABILITY_LABELS.en[ability] ?? ability} cannot exceed ${maximum}.` : 'This ability score has reached the normal rules cap.',
  },
  class_progression_future_step: { 'zh-TW': '職業進程需在職業步驟中完成。', en: 'Class progression is completed in the class step.' },
}

const REQUEST_CODE_MESSAGES: Record<string, Record<Locale, string>> = {
  not_found: { 'zh-TW': '找不到要求的資料，可能已被刪除或變更。', en: 'The requested data could not be found. It may have been removed or changed.' },
  revision_conflict: { 'zh-TW': '資料已在其他操作中更新，請重新載入後再試一次。', en: 'The data changed in another operation. Reload and try again.' },
  validation_error: { 'zh-TW': '送出的資料未通過驗證，請檢查目前選擇。', en: 'The submitted data did not pass validation. Check the current selections.' },
  invalid_request: { 'zh-TW': '這次要求無法處理，請檢查目前資料後再試一次。', en: 'This request could not be processed. Check the current data and try again.' },
}

function formatLocalizedMessage(table: Record<string, LocalizedMessage>, code: string | undefined, locale: Locale, params: MessageParams = {}): string | undefined {
  if (!code) return undefined
  const formatter = table[code]?.[locale]
  if (!formatter) return undefined
  return typeof formatter === 'function' ? formatter(params) : formatter
}

function messageParams(value: unknown): MessageParams {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as MessageParams : {}
}

export function currentSystemLocale(): Locale {
  if (typeof document !== 'undefined' && isSupportedLocale(document.documentElement.lang)) return document.documentElement.lang
  return 'zh-TW'
}

export function localizedBuilderIssueMessage(code: string, originalMessage: string, locale: Locale = currentSystemLocale(), params: MessageParams = {}): string {
  const translated = formatLocalizedMessage(BUILDER_ISSUE_MESSAGES, code, locale, params)
  if (translated) return translated
  if (locale === 'en') return originalMessage || 'The character data has a rules problem that needs attention.'
  return '目前的角色資料有一項需要修正的規則問題。'
}

export function localizedDisabledReason(originalMessage: string, locale: Locale = currentSystemLocale(), code?: string, params: MessageParams = {}): string {
  const translated = formatLocalizedMessage(DISABLED_REASON_MESSAGES, code, locale, params)
  if (translated) return translated
  if (locale === 'en') return originalMessage || 'This option is unavailable.'
  return '此選項目前無法選擇；請先完成相關條件。'
}

export function localizedRequestErrorMessage(code: string | undefined, status: number, originalMessage: string, locale: Locale = currentSystemLocale()): string {
  if (code && REQUEST_CODE_MESSAGES[code]) return REQUEST_CODE_MESSAGES[code][locale]
  if (status === 404) return REQUEST_CODE_MESSAGES.not_found[locale]
  if (status === 409) return REQUEST_CODE_MESSAGES.revision_conflict[locale]
  if (locale === 'en') return originalMessage || `Request failed (${status})`
  return `要求失敗（HTTP ${status}），請稍後再試。`
}

export function createLocalizedRequestError(code: string | undefined, status: number, originalMessage: string, locale?: Locale): Error {
  const error = new Error()
  Object.defineProperty(error, 'message', { configurable: true, enumerable: false, get: () => localizedRequestErrorMessage(code, status, originalMessage, locale ?? currentSystemLocale()) })
  return error
}

function installDynamicMessage(target: Record<string, unknown>, property: 'message' | 'disabled_reason', original: string): void {
  Object.defineProperty(target, property, {
    configurable: true,
    enumerable: true,
    get: () => property === 'message'
      ? localizedBuilderIssueMessage(String(target.code ?? ''), original, currentSystemLocale(), messageParams(target.message_params))
      : localizedDisabledReason(original, currentSystemLocale(), typeof target.disabled_reason_code === 'string' ? target.disabled_reason_code : undefined, messageParams(target.disabled_reason_params)),
  })
}

/** Keep machine identity locale-neutral. Parameterized server messages should send
 * `message_params`, or `disabled_reason_code` + `disabled_reason_params`, rather
 * than interpolating canonical English rules names into prose.
 */
export function installDynamicLocalizedBuilderPayload<T>(value: T): T {
  const visit = (current: unknown): void => {
    if (Array.isArray(current)) { current.forEach(visit); return }
    if (!current || typeof current !== 'object') return
    const record = current as Record<string, unknown>
    if (typeof record.code === 'string' && typeof record.path === 'string' && typeof record.message === 'string') installDynamicMessage(record, 'message', record.message)
    if (typeof record.disabled_reason === 'string' && (typeof record.option_id === 'string' || typeof record.choice_id === 'string')) installDynamicMessage(record, 'disabled_reason', record.disabled_reason)
    for (const child of Object.values(record)) visit(child)
  }
  visit(value)
  return value
}
