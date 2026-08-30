import type { BuilderChoice, BuilderChoiceOption } from '../api/characterBuilder'
import type { Locale } from './locale'
import type { ContentNameResolver } from './useContentPresentations'

const CHOICE_SEPARATOR = ' — '

const CHOICE_SUFFIX_ZH: Record<string, string> = {
  'content:ability_bonus_options': '屬性值加值',
  'content:language_options': '語言',
  'content:starting_proficiency_options': '起始熟練項',
  'content:proficiency_choices': '熟練項',
  'content:spell_options': '法術選擇',
  'content:starting_equipment_options': '起始裝備',
  'content:race-feat': '專長',
  'content:subtraits': '選擇',
  'content:class-proficiency': '熟練項選擇',
  'content:asi-feat': '屬性值提升或專長',
}

const ABILITY_NAMES_ZH: Record<string, string> = {
  strength: '力量',
  dexterity: '敏捷',
  constitution: '體質',
  intelligence: '智力',
  wisdom: '睿知',
  charisma: '魅力',
}

function sourceFallback(choice: BuilderChoice): { name: string; suffix: string } {
  const primary = choice.label.split(CHOICE_SEPARATOR, 1)[0]?.trim() ?? ''
  if (choice.option_source === 'content:asi-feat') {
    const levelMatch = primary.match(/^(.*?)(\s+\d+)$/)
    if (levelMatch) {
      return { name: levelMatch[1].trim(), suffix: levelMatch[2] }
    }
  }
  return { name: primary, suffix: '' }
}

function localizedSourceName(choice: BuilderChoice, nameFor: ContentNameResolver): string {
  const fallback = sourceFallback(choice)
  if (!choice.source_ref) return fallback.name
  return `${nameFor(choice.source_ref, fallback.name)}${fallback.suffix}`
}

/** Localize server-derived Builder labels without using display text as identity. */
export function builderChoiceLabel(
  choice: BuilderChoice,
  locale: Locale,
  nameFor: ContentNameResolver,
): string {
  if (locale === 'en') return choice.label

  if (choice.option_source === 'content:asi-ability') {
    return '分配 2 點屬性值'
  }

  const source = choice.option_source ?? ''
  const suffix = CHOICE_SUFFIX_ZH[source]
  if (suffix) {
    const sourceName = choice.source_ref ? localizedSourceName(choice, nameFor) : ''
    return sourceName ? `${sourceName}${CHOICE_SEPARATOR}${suffix}` : suffix
  }

  if (source.startsWith('content:feature:')) {
    const sourceName = localizedSourceName(choice, nameFor)
    return sourceName ? `${sourceName}${CHOICE_SEPARATOR}選擇` : '特性選擇'
  }

  // Unknown content-derived choice labels should not silently leak an English
  // heading into zh-TW. Preserve the source identity and use a neutral choice
  // label; non-content/system choices retain their existing presentation.
  if (source.startsWith('content:') && choice.source_ref) {
    const sourceName = localizedSourceName(choice, nameFor)
    return sourceName ? `${sourceName}${CHOICE_SEPARATOR}選擇` : '選擇'
  }

  return choice.label
}

export function builderChoiceOptionLabel(
  choice: BuilderChoice,
  option: BuilderChoiceOption,
  locale: Locale,
  nameFor: ContentNameResolver,
): string {
  if (option.reference_id) return nameFor(option.reference_id, option.label)
  if (locale === 'en') return option.label

  if (choice.option_source === 'content:asi-feat' && option.branch_key === 'asi') {
    return '屬性值提升'
  }

  if (choice.option_source === 'content:asi-ability') {
    const ability = option.option_id.startsWith('ability:')
      ? option.option_id.slice('ability:'.length)
      : ''
    const name = ABILITY_NAMES_ZH[ability]
    if (name) return `${name} +1`
  }

  return option.label
}
