import { currentSystemLocale } from './systemMessages'
import type { Locale } from './locale'

type MessageParams = Record<string, unknown>
type Requirement = Record<string, unknown>

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

const PROFICIENCY_LABELS: Record<Locale, Record<string, string>> = {
  'zh-TW': {
    'srd5.1:proficiency:light-armor': '輕甲熟練',
    'srd5.1:proficiency:medium-armor': '中甲熟練',
    'srd5.1:proficiency:heavy-armor': '重甲熟練',
    'srd5.1:proficiency:shields': '盾牌熟練',
    'srd5.1:proficiency:martial-weapons': '軍用武器熟練',
  },
  en: {
    'srd5.1:proficiency:light-armor': 'light armor proficiency',
    'srd5.1:proficiency:medium-armor': 'medium armor proficiency',
    'srd5.1:proficiency:heavy-armor': 'heavy armor proficiency',
    'srd5.1:proficiency:shields': 'shield proficiency',
    'srd5.1:proficiency:martial-weapons': 'martial weapon proficiency',
  },
}

const SIZE_LABELS: Record<Locale, Record<string, string>> = {
  'zh-TW': { tiny: '微型', small: '小型', medium: '中型', large: '大型' },
  en: { tiny: 'Tiny', small: 'Small', medium: 'Medium', large: 'Large' },
}

function requirementLabel(value: unknown, locale: Locale): string | undefined {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined
  const requirement = value as Requirement
  const type = requirement.type

  if (type === 'ability') {
    const ability = requirement.ability
    const minimum = requirement.minimum_score
    if (typeof ability !== 'string' || typeof minimum !== 'number') return undefined
    return `${ABILITY_LABELS[locale][ability] ?? ability} ${minimum}+`
  }

  if (type === 'ability_scores_incomplete') {
    const ability = requirement.ability
    const minimum = requirement.minimum_score
    if (typeof ability !== 'string' || typeof minimum !== 'number') return undefined
    const label = `${ABILITY_LABELS[locale][ability] ?? ability} ${minimum}+`
    return locale === 'zh-TW' ? `先完成能力值（需要 ${label}）` : `complete ability scores (${label} required)`
  }

  if (type === 'armor_proficiency') {
    const ref = requirement.proficiency_ref
    if (typeof ref !== 'string') return undefined
    return PROFICIENCY_LABELS[locale][ref] ?? ref
  }

  if (type === 'spellcasting') {
    return locale === 'zh-TW' ? '至少能施放一個法術' : 'the ability to cast at least one spell'
  }

  // M01-O origin / pool prerequisite atoms. Allowed refs stay in params for detail
  // surfaces; the inline label only names the kind of requirement.
  if (type === 'ancestry') {
    return locale === 'zh-TW' ? '特定種族' : 'a specific ancestry'
  }
  if (type === 'lineage') {
    return locale === 'zh-TW' ? '特定亞種或血脈' : 'a specific subrace or lineage'
  }
  if (type === 'size') {
    const sizes = Array.isArray(requirement.allowed_sizes)
      ? requirement.allowed_sizes.filter((item): item is string => typeof item === 'string')
      : []
    const labels = sizes.map((size) => SIZE_LABELS[locale][size] ?? size)
    if (!labels.length) return locale === 'zh-TW' ? '特定體型' : 'a specific size'
    return locale === 'zh-TW' ? `體型為${labels.join('或')}` : `${labels.join(' or ')} size`
  }
  if (type === 'proficiency') {
    const refs = Array.isArray(requirement.required_refs)
      ? requirement.required_refs.filter((item): item is string => typeof item === 'string')
      : []
    const labels = refs.map((ref) => PROFICIENCY_LABELS[locale][ref] ?? ref)
    if (!labels.length) return locale === 'zh-TW' ? '特定熟練' : 'a specific proficiency'
    return labels.join(locale === 'zh-TW' ? '或' : ' or ')
  }
  if (type === 'feature') {
    return locale === 'zh-TW' ? '特定職業特性' : 'a specific class feature'
  }
  if (type === 'ancestry_context_missing' || type === 'lineage_context_missing' || type === 'size_context_missing') {
    return locale === 'zh-TW' ? '先完成種族選擇' : 'choose your race first'
  }

  if (type === 'any_of') {
    const options = Array.isArray(requirement.options)
      ? requirement.options.map((item) => requirementLabel(item, locale)).filter((item): item is string => Boolean(item))
      : []
    if (!options.length) return undefined
    return locale === 'zh-TW'
      ? `以下任一：${options.join(' 或 ')}`
      : `one of: ${options.join(' or ')}`
  }

  return undefined
}

function requirementList(params: MessageParams, locale: Locale): string | undefined {
  const values = Array.isArray(params.requirements) ? params.requirements : []
  const labels = values
    .map((item) => requirementLabel(item, locale))
    .filter((item): item is string => Boolean(item))
  if (!labels.length) return undefined
  return labels.join(locale === 'zh-TW' ? '；' : '; ')
}

function disabledReason(code: string, params: MessageParams, locale: Locale): string | undefined {
  if (code === 'feat_ability_scores_incomplete') {
    const detail = requirementList(params, locale)
    return locale === 'zh-TW'
      ? detail ? `選擇此專長前請先完成能力值：${detail}。` : '選擇專長前請先完成能力值。'
      : detail ? `Complete ability scores before choosing this feat: ${detail}.` : 'Complete ability scores before choosing this feat.'
  }
  if (code === 'feat_prerequisite_not_met') {
    const detail = requirementList(params, locale)
    return locale === 'zh-TW'
      ? detail ? `此專長需要符合：${detail}。` : '目前不符合此專長的先決條件。'
      : detail ? `Requires ${detail}.` : 'The feat prerequisites are not met.'
  }
  if (code === 'feat_not_repeatable') {
    return locale === 'zh-TW' ? '此專長不能重複取得。' : 'This feat cannot be acquired more than once.'
  }
  if (code === 'unsupported_feat_prerequisite') {
    return locale === 'zh-TW'
      ? '此專長使用目前尚未支援的先決條件格式。'
      : 'This feat uses a prerequisite shape that is not currently supported.'
  }
  if (code === 'feat_spell_source_required') {
    return locale === 'zh-TW'
      ? '請先選擇此專長的施法來源職業。'
      : "Choose the feat's spellcasting source first."
  }
  if (code === 'feat_spell_source_no_attack_cantrip') {
    return locale === 'zh-TW'
      ? '此職業在 5e 2014 規則中沒有需要攻擊擲骰的戲法。'
      : 'This class has no cantrips that require an attack roll in 5e 2014 rules.'
  }
  if (code === 'feat_fighting_style_already_known') {
    return locale === 'zh-TW' ? '已經擁有這個戰鬥風格。' : 'This fighting style is already known.'
  }
  if (code === 'pool_option_granted_by_feat') {
    return locale === 'zh-TW' ? '此選項已由專長授予。' : 'This option is already granted by a feat.'
  }
  if (code === 'feat_invocation_prerequisite_not_met') {
    return locale === 'zh-TW'
      ? '此祈喚有先決條件，只有符合條件的契約師才能選擇。'
      : 'This invocation has a prerequisite that only a qualifying Warlock can meet.'
  }
  if (code === 'skill_already_has_expertise') {
    return locale === 'zh-TW' ? '此技能已經擁有專精。' : 'This skill already has expertise.'
  }
  return undefined
}

function issueMessage(code: string, params: MessageParams, locale: Locale): string | undefined {
  const optionReason = disabledReason(code, params, locale)
  if (optionReason) return optionReason

  if (code === 'illegal_feat_spell_choice') {
    return locale === 'zh-TW'
      ? '法術狙擊手只能選擇來自所選施法來源、且需要法術攻擊骰的戲法。'
      : 'Spell Sniper must select an attack-roll cantrip from the chosen spellcasting source.'
  }
  if (code === 'illegal_feat_nested_choice') {
    return locale === 'zh-TW'
      ? '此專長的附帶選擇不在目前合法的來源或選項池中，請重新選擇。'
      : 'A feat-specific selection is not legal for the current source or option pool.'
  }
  if (code === 'incomplete_feat_choice') {
    return locale === 'zh-TW'
      ? '此專長還有必填的附帶選擇尚未完成。'
      : 'This feat still has a required nested selection to complete.'
  }
  if (code === 'invalid_feat_choice') {
    return locale === 'zh-TW'
      ? '此專長包含不合法的附帶選擇，請重新選擇。'
      : 'This feat contains an invalid nested selection.'
  }
  if (code === 'repeatable_feat_choice_must_differ') {
    return locale === 'zh-TW'
      ? '再次取得此專長時必須選擇不同的專長選項。'
      : 'A repeated acquisition of this feat must use a different feat option.'
  }
  if (code === 'feat_retraining_requires_level_up') {
    return locale === 'zh-TW'
      ? '專長附帶的選項只能在升級時替換，不能透過 Build Edit 更改。'
      : 'Feat-linked options can only be replaced through Level Up, not Build Edit.'
  }
  if (code === 'feat_retraining_not_available') {
    return locale === 'zh-TW'
      ? '此專長選項只能在取得屬性值提升的升級時替換。'
      : 'This feat option can only be replaced at a Level Up that grants an Ability Score Improvement.'
  }
  if (code === 'feat_retraining_limit_exceeded') {
    return locale === 'zh-TW'
      ? '每次升級只能替換此專長的一個選項。'
      : 'Only one option of this feat can be replaced per Level Up.'
  }
  return undefined
}

function paramsOf(value: unknown): MessageParams {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as MessageParams
    : {}
}

function redefine(target: Record<string, unknown>, property: 'message' | 'disabled_reason', formatter: () => string): void {
  Object.defineProperty(target, property, {
    configurable: true,
    enumerable: true,
    get: formatter,
  })
}

/**
 * M01-K adds prerequisite structures that include proficiencies, spellcasting and
 * compound OR branches. The pre-K localization formatter only understands
 * ability requirements, so install a second locale-neutral presentation layer
 * for K codes while leaving every existing message getter untouched.
 */
export function installM01KLocalizedBuilderPayload<T>(value: T): T {
  const visit = (current: unknown): void => {
    if (Array.isArray(current)) {
      current.forEach(visit)
      return
    }
    if (!current || typeof current !== 'object') return
    const record = current as Record<string, unknown>

    if (typeof record.disabled_reason_code === 'string' && typeof record.disabled_reason === 'string') {
      const code = record.disabled_reason_code
      const params = paramsOf(record.disabled_reason_params)
      if (disabledReason(code, params, 'zh-TW') || disabledReason(code, params, 'en')) {
        redefine(record, 'disabled_reason', () =>
          disabledReason(code, params, currentSystemLocale()) ?? String(record.disabled_reason ?? ''),
        )
      }
    }

    if (typeof record.code === 'string' && typeof record.message === 'string') {
      const code = record.code
      const params = paramsOf(record.message_params)
      if (issueMessage(code, params, 'zh-TW') || issueMessage(code, params, 'en')) {
        redefine(record, 'message', () =>
          issueMessage(code, params, currentSystemLocale()) ?? String(record.message ?? ''),
        )
      }
    }

    for (const child of Object.values(record)) visit(child)
  }

  visit(value)
  return value
}
