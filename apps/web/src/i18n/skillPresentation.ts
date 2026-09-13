import type { UiTranslator } from './useUiCopy'

export type AbilityIndex = 'str' | 'dex' | 'con' | 'int' | 'wis' | 'cha'

export const SKILL_ABILITY_MAP: Record<string, AbilityIndex> = {
  acrobatics: 'dex',
  'animal-handling': 'wis',
  arcana: 'int',
  athletics: 'str',
  deception: 'cha',
  history: 'int',
  insight: 'wis',
  intimidation: 'cha',
  investigation: 'int',
  medicine: 'wis',
  nature: 'int',
  perception: 'wis',
  performance: 'cha',
  persuasion: 'cha',
  religion: 'int',
  'sleight-of-hand': 'dex',
  stealth: 'dex',
  survival: 'wis',
}

export function normalizeSkillIndex(skillKeyOrIndex: string): string {
  return (
    skillKeyOrIndex
      .replaceAll('_', '-')
      .split(':')
      .pop()
      ?.toLowerCase() ?? ''
  )
}

export function formatSkillWithAbility(
  skillName: string,
  skillKeyOrIndex: string,
  t: UiTranslator,
): string {
  const index = normalizeSkillIndex(skillKeyOrIndex)
  const ability = SKILL_ABILITY_MAP[index]
  if (!ability) return skillName
  const abilityLabel = t(`skill.ability.${ability}` as const)
  return t('skill.withAbility', { skill: skillName, ability: abilityLabel })
}
