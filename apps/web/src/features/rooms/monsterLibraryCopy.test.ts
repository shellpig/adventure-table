import { describe, expect, it } from 'vitest'

import { MonsterLibraryApiError } from '../../api/monsterLibrary'
import {
  formatAbilityName,
  formatMonsterName,
  formatMonsterRuleField,
  monsterLibraryCopy,
  monsterLibraryErrorMessage,
  SRD_ALIGNMENTS,
  SRD_SIZES,
  SRD_TYPES,
} from './monsterLibraryCopy'

describe('monsterLibraryCopy', () => {
  it('has identical keys for en and zh-TW', () => {
    const enCopy = monsterLibraryCopy('en')
    const zhCopy = monsterLibraryCopy('zh-TW')

    const enKeys = Object.keys(enCopy).sort()
    const zhKeys = Object.keys(zhCopy).sort()

    expect(enKeys).toEqual(zhKeys)
  })

  it('maps all A1 machine error codes correctly in en and zh-TW', () => {
    const enCopy = monsterLibraryCopy('en')
    const zhCopy = monsterLibraryCopy('zh-TW')

    const codes = [
      {
        code: 'monster_template_not_found',
        status: 404,
        expectedEn: enCopy.errMonsterTemplateNotFound,
        expectedZh: zhCopy.errMonsterTemplateNotFound,
      },
      {
        code: 'monster_library_forbidden',
        status: 403,
        expectedEn: enCopy.errMonsterLibraryForbidden,
        expectedZh: zhCopy.errMonsterLibraryForbidden,
      },
      {
        code: 'monster_template_read_only',
        status: 403,
        expectedEn: enCopy.errMonsterTemplateReadOnly,
        expectedZh: zhCopy.errMonsterTemplateReadOnly,
      },
      {
        code: 'monster_template_revision_conflict',
        status: 409,
        expectedEn: enCopy.errMonsterTemplateRevisionConflict,
        expectedZh: zhCopy.errMonsterTemplateRevisionConflict,
      },
      {
        code: 'monster_template_referenced',
        status: 409,
        expectedEn: enCopy.errMonsterTemplateReferenced,
        expectedZh: zhCopy.errMonsterTemplateReferenced,
      },
      {
        code: 'monster_template_archived',
        status: 409,
        expectedEn: enCopy.errMonsterTemplateArchived,
        expectedZh: zhCopy.errMonsterTemplateArchived,
      },
      {
        code: 'invalid_monster_template_ref',
        status: 422,
        expectedEn: enCopy.errInvalidMonsterTemplateRef,
        expectedZh: zhCopy.errInvalidMonsterTemplateRef,
      },
    ]

    for (const { code, status, expectedEn, expectedZh } of codes) {
      const error = new MonsterLibraryApiError(status, code, 'Test error')
      expect(monsterLibraryErrorMessage(error, enCopy)).toBe(expectedEn)
      expect(monsterLibraryErrorMessage(error, zhCopy)).toBe(expectedZh)
    }

    // Fallback for unknown errors
    const unknownError = new Error('Unknown error')
    expect(monsterLibraryErrorMessage(unknownError, enCopy)).toBe(enCopy.requestFailed)
    expect(monsterLibraryErrorMessage(unknownError, zhCopy)).toBe(zhCopy.requestFailed)
  })

  it('formats monster name based on name_is_custom and locale', () => {
    // Built-in or copied without renaming: name_is_custom is false
    const builtin = {
      name: 'Goblin',
      names: { en: 'Goblin', 'zh-TW': '地精' },
      name_is_custom: false,
    }
    expect(formatMonsterName(builtin, 'zh-TW')).toBe('地精')
    expect(formatMonsterName(builtin, 'en')).toBe('Goblin')

    // Custom named monster: name_is_custom is true
    const custom = {
      name: 'Custom Goblin',
      names: { en: 'Goblin', 'zh-TW': '地精' },
      name_is_custom: true,
    }
    expect(formatMonsterName(custom, 'zh-TW')).toBe('Custom Goblin')
    expect(formatMonsterName(custom, 'en')).toBe('Custom Goblin')
  })

  it('formats ability name from presentation data', () => {
    const trait = { name: 'Nimble Escape' }
    const presentation = {
      ability_names: {
        traits: [{ en: 'Nimble Escape', 'zh-TW': '迅捷逃逸' }],
      },
    }
    expect(formatAbilityName(trait, 0, 'traits', presentation, 'zh-TW')).toBe('迅捷逃逸')
    expect(formatAbilityName(trait, 0, 'traits', presentation, 'en')).toBe('Nimble Escape')

    // When presentation missing, fallback to ability name
    expect(formatAbilityName(trait, 0, 'traits', undefined, 'zh-TW')).toBe('Nimble Escape')
  })

  it('has both en and zh-TW labels for every SRD size, type, and alignment', () => {
    for (const size of SRD_SIZES) {
      const en = formatMonsterRuleField('size', size, 'en')
      const zh = formatMonsterRuleField('size', size, 'zh-TW')
      expect(en).toBeTruthy()
      expect(zh).toBeTruthy()
      expect(en).toBe(size)
      expect(zh).not.toBe(size)
    }

    for (const type of SRD_TYPES) {
      const en = formatMonsterRuleField('type', type, 'en')
      const zh = formatMonsterRuleField('type', type, 'zh-TW')
      expect(en).toBeTruthy()
      expect(zh).toBeTruthy()
      expect(en).toBe(type)
      expect(zh).not.toBe(type)
    }

    for (const alignment of SRD_ALIGNMENTS) {
      const en = formatMonsterRuleField('alignment', alignment, 'en')
      const zh = formatMonsterRuleField('alignment', alignment, 'zh-TW')
      expect(en).toBeTruthy()
      expect(zh).toBeTruthy()
      expect(en).toBe(alignment)
      expect(zh).not.toBe(alignment)
    }
  })

  it('preserves custom non-SRD values as typed in both locales', () => {
    expect(formatMonsterRuleField('size', 'Colossal', 'en')).toBe('Colossal')
    expect(formatMonsterRuleField('size', 'Colossal', 'zh-TW')).toBe('Colossal')

    expect(formatMonsterRuleField('type', 'cyber-beast', 'en')).toBe('cyber-beast')
    expect(formatMonsterRuleField('type', 'cyber-beast', 'zh-TW')).toBe('cyber-beast')

    expect(formatMonsterRuleField('alignment', 'chaotic silly', 'en')).toBe('chaotic silly')
    expect(formatMonsterRuleField('alignment', 'chaotic silly', 'zh-TW')).toBe('chaotic silly')

    expect(formatMonsterRuleField('type', null, 'zh-TW')).toBe('')
    expect(formatMonsterRuleField('type', undefined, 'en')).toBe('')
  })
})

