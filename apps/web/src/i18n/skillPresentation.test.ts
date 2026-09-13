import { describe, expect, it } from 'vitest'

import { translateUi } from './uiCopy'
import {
  SKILL_ABILITY_MAP,
  formatSkillWithAbility,
  normalizeSkillIndex,
} from './skillPresentation'

describe('skillPresentation', () => {
  it('maps all 18 standard D&D 5e skills to their expected abilities', () => {
    expect(Object.keys(SKILL_ABILITY_MAP)).toHaveLength(18)
    expect(SKILL_ABILITY_MAP['athletics']).toBe('str')
    expect(SKILL_ABILITY_MAP['acrobatics']).toBe('dex')
    expect(SKILL_ABILITY_MAP['sleight-of-hand']).toBe('dex')
    expect(SKILL_ABILITY_MAP['stealth']).toBe('dex')
    expect(SKILL_ABILITY_MAP['arcana']).toBe('int')
    expect(SKILL_ABILITY_MAP['history']).toBe('int')
    expect(SKILL_ABILITY_MAP['investigation']).toBe('int')
    expect(SKILL_ABILITY_MAP['nature']).toBe('int')
    expect(SKILL_ABILITY_MAP['religion']).toBe('int')
    expect(SKILL_ABILITY_MAP['animal-handling']).toBe('wis')
    expect(SKILL_ABILITY_MAP['insight']).toBe('wis')
    expect(SKILL_ABILITY_MAP['medicine']).toBe('wis')
    expect(SKILL_ABILITY_MAP['perception']).toBe('wis')
    expect(SKILL_ABILITY_MAP['survival']).toBe('wis')
    expect(SKILL_ABILITY_MAP['deception']).toBe('cha')
    expect(SKILL_ABILITY_MAP['intimidation']).toBe('cha')
    expect(SKILL_ABILITY_MAP['performance']).toBe('cha')
    expect(SKILL_ABILITY_MAP['persuasion']).toBe('cha')
  })

  it('normalizes various skill reference formats', () => {
    expect(normalizeSkillIndex('srd5.1:skill:animal-handling')).toBe('animal-handling')
    expect(normalizeSkillIndex('sleight_of_hand')).toBe('sleight-of-hand')
    expect(normalizeSkillIndex('INTIMIDATION')).toBe('intimidation')
  })

  it('formats skill with ability tag in Traditional Chinese (zh-TW)', () => {
    const tZh = (key: Parameters<typeof translateUi>[1], params?: Parameters<typeof translateUi>[2]) =>
      translateUi('zh-TW', key, params)

    expect(formatSkillWithAbility('威嚇', 'intimidation', tZh)).toBe('威嚇 (魅力)')
    expect(formatSkillWithAbility('運動', 'athletics', tZh)).toBe('運動 (力量)')
    expect(formatSkillWithAbility('特技', 'acrobatics', tZh)).toBe('特技 (敏捷)')
    expect(formatSkillWithAbility('巧手', 'srd5.1:skill:sleight-of-hand', tZh)).toBe('巧手 (敏捷)')
    expect(formatSkillWithAbility('隱匿', 'stealth', tZh)).toBe('隱匿 (敏捷)')
    expect(formatSkillWithAbility('奧秘', 'arcana', tZh)).toBe('奧秘 (智力)')
    expect(formatSkillWithAbility('歷史', 'history', tZh)).toBe('歷史 (智力)')
    expect(formatSkillWithAbility('調查', 'investigation', tZh)).toBe('調查 (智力)')
    expect(formatSkillWithAbility('自然', 'nature', tZh)).toBe('自然 (智力)')
    expect(formatSkillWithAbility('宗教', 'religion', tZh)).toBe('宗教 (智力)')
    expect(formatSkillWithAbility('馴獸', 'animal-handling', tZh)).toBe('馴獸 (感知)')
    expect(formatSkillWithAbility('洞悉', 'insight', tZh)).toBe('洞悉 (感知)')
    expect(formatSkillWithAbility('醫藥', 'medicine', tZh)).toBe('醫藥 (感知)')
    expect(formatSkillWithAbility('察覺', 'perception', tZh)).toBe('察覺 (感知)')
    expect(formatSkillWithAbility('求生', 'survival', tZh)).toBe('求生 (感知)')
    expect(formatSkillWithAbility('欺瞞', 'deception', tZh)).toBe('欺瞞 (魅力)')
    expect(formatSkillWithAbility('表演', 'performance', tZh)).toBe('表演 (魅力)')
    expect(formatSkillWithAbility('遊說', 'persuasion', tZh)).toBe('遊說 (魅力)')
  })

  it('formats skill with ability abbreviation in English (en)', () => {
    const tEn = (key: Parameters<typeof translateUi>[1], params?: Parameters<typeof translateUi>[2]) =>
      translateUi('en', key, params)

    expect(formatSkillWithAbility('Intimidation', 'intimidation', tEn)).toBe('Intimidation (CHA)')
    expect(formatSkillWithAbility('Athletics', 'athletics', tEn)).toBe('Athletics (STR)')
    expect(formatSkillWithAbility('Acrobatics', 'acrobatics', tEn)).toBe('Acrobatics (DEX)')
    expect(formatSkillWithAbility('Arcana', 'arcana', tEn)).toBe('Arcana (INT)')
    expect(formatSkillWithAbility('Perception', 'perception', tEn)).toBe('Perception (WIS)')
  })

  it('returns skillName unchanged when skill is unrecognized', () => {
    const tZh = (key: Parameters<typeof translateUi>[1], params?: Parameters<typeof translateUi>[2]) =>
      translateUi('zh-TW', key, params)

    expect(formatSkillWithAbility('自訂技能', 'custom-skill', tZh)).toBe('自訂技能')
  })
})
