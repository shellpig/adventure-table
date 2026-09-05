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
  'content:race-variant': '血統變體',
  'content:race-variant-replacement': '血統特徵',
  'content:race-variant-spell': '法術選擇',
  'content:lineage': '血裔',
  'content:lineage-asi-pattern': '屬性值加值方式',
  'content:lineage-asi-ability': '屬性值加值',
  'content:lineage-size': '體型',
  'content:lineage-language': '語言',
  'content:lineage-legacy-skill': '祖源傳承技能',
  'content:lineage-legacy-movement': '祖源傳承移動方式',
  'content:infusion': '已知注法',
  'content:optional-class-feature': '選用職業特性',
  'content:optional-feature:cantrip': '戲法選擇',
  'content:feature:optional-nested': '附帶特性選擇',
  'content:optional-feature:retraining-action': '重訓',
  'content:optional-feature:retraining-from:feature_pool': '要替換的選項',
  'content:optional-feature:retraining-to:feature_pool': '新的選項',
  'content:optional-feature:retraining-from:cantrip': '要替換的戲法',
  'content:optional-feature:retraining-to:cantrip': '新的戲法',
}

const RACE_VARIANT_OPTION_ZH: Record<string, string> = {
  'keep-skill-versatility': '保留多才多藝',
  'wizard-cantrip': '戲法',
  'elf-weapon-training': '精靈武器訓練',
  'keen-senses': '敏銳感官',
  'fleet-of-foot': '輕捷步伐',
  'mask-of-the-wild': '荒野隱蔽',
  'swimming-speed': '游泳',
  'drow-magic': '卓爾魔法',
  'standard-ability-package': '標準屬性組合（智力 +1、魅力 +2）',
  feral: '野性（敏捷 +2、智力 +1）',
  'infernal-legacy': '煉獄傳承',
  'devils-tongue': '魔鬼之舌',
  hellfire: '地獄之火',
  winged: '飛翔之翼',
  baalzebul: '馬拉多米尼之遺贈',
  dispater: '迪斯之遺贈',
  fierna: '福萊格索斯之遺贈',
  glasya: '馬爾伯吉之遺贈',
  levistus: '斯泰吉亞之遺贈',
  mammon: '彌瑙洛斯之遺贈',
  mephistopheles: '卡尼亞之遺贈',
  zariel: '阿弗納斯之遺贈',
}

const ABILITY_NAMES_ZH: Record<string, string> = {
  strength: '力量',
  dexterity: '敏捷',
  constitution: '體質',
  intelligence: '智力',
  wisdom: '睿知',
  charisma: '魅力',
  str: '力量',
  dex: '敏捷',
  con: '體質',
  int: '智力',
  wis: '睿知',
  cha: '魅力',
}

const LINEAGE_SIZE_ZH: Record<string, string> = {
  'lineage-size:medium': '中型',
  'lineage-size:small': '小型',
}

const LINEAGE_MOVEMENT_ZH: Record<string, string> = {
  'lineage-movement:climb': '攀爬',
  'lineage-movement:fly': '飛行',
  'lineage-movement:swim': '游泳',
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
  if (choice.option_source === 'equipment') {
    return '起始裝備選擇'
  }
  if (choice.option_source === 'content:race-variant-replacement') {
    if (choice.choice_id.endsWith(':ability-package')) return '提夫林屬性組合'
    if (choice.choice_id.endsWith(':legacy')) return '提夫林傳承'
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

  if (source.startsWith('content:') && choice.source_ref) {
    const sourceName = localizedSourceName(choice, nameFor)
    return sourceName ? `${sourceName}${CHOICE_SEPARATOR}選擇` : '選擇'
  }

  return choice.label
}

function localizedEquipmentOption(
  option: BuilderChoiceOption,
  nameFor: ContentNameResolver,
): string | null {
  const parts = (option.presentation_items ?? []).map((item) => {
    const name = nameFor(item.reference_id, '裝備')
    return item.count > 1 ? `${item.count} × ${name}` : name
  })
  if (option.presentation_has_choice) parts.push('裝備選擇')
  return parts.length ? parts.join(' + ') : null
}

export function builderChoiceOptionLabel(
  choice: BuilderChoice,
  option: BuilderChoiceOption,
  locale: Locale,
  nameFor: ContentNameResolver,
): string {
  if (locale === 'en') return option.label

  if (choice.option_source === 'equipment') {
    const equipmentLabel = localizedEquipmentOption(option, nameFor)
    if (equipmentLabel) return equipmentLabel
  }

  if (option.reference_id) return nameFor(option.reference_id, option.label)

  if (
    choice.option_source === 'content:optional-feature:retraining-action' &&
    option.branch_key === 'replace'
  ) {
    return '替換一個選項'
  }

  if (choice.option_source === 'content:race-variant-replacement') {
    const label = RACE_VARIANT_OPTION_ZH[option.option_id]
    if (label) return label
  }

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

  if (choice.option_source === 'content:lineage-asi-ability') {
    const parts = option.option_id.split(':')
    const name = ABILITY_NAMES_ZH[parts[1] ?? '']
    const bonus = parts[2]
    if (name && bonus) return `${name} +${bonus}`
  }

  // A feature branch the SRD left undescribed: the server sends how many the
  // branch lets you pick plus the references it bundles in, so zh-TW is built
  // from that structure rather than from the English sentence.
  if (
    (choice.option_source ?? '').startsWith('content:feature:') &&
    (option.presentation_has_choice || (option.presentation_items ?? []).length > 0)
  ) {
    const parts: string[] = []
    if (option.presentation_has_choice) {
      parts.push(option.count ? `選 ${option.count} 項` : '選擇')
    }
    for (const item of option.presentation_items ?? []) {
      const name = nameFor(item.reference_id, option.label)
      parts.push(item.count > 1 ? `${item.count} × ${name}` : name)
    }
    if (parts.length) return parts.join(' + ')
  }

  if (choice.option_source === 'content:lineage-size') {
    return LINEAGE_SIZE_ZH[option.option_id] ?? option.label
  }

  if (choice.option_source === 'content:lineage-legacy-movement') {
    return LINEAGE_MOVEMENT_ZH[option.option_id] ?? option.label
  }

  return option.label
}