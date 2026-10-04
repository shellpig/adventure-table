import { describe, expect, it } from 'vitest'

import type { MonsterLibraryDetailView } from '../../api/monsterLibrary'
import {
  customMonsterFormFromDetail,
  customMonsterScalarPatch,
  monsterSpeedString,
  type CustomMonsterFormValues,
} from './monsterLibraryForm'

function quickEnemyDetail(): MonsterLibraryDetailView {
  // Shape stored by Save as Monster Template from a Quick Enemy: only size,
  // armor_class, max_hp, speed, and possibly actions. No ability_scores,
  // type, alignment, challenge_rating, description, or traits.
  return {
    ref: 'custom:10000000-0000-4000-8000-000000000001',
    name: 'Club Thug',
    names: { en: 'Club Thug', 'zh-TW': 'Club Thug' },
    name_is_custom: true,
    source_kind: 'custom',
    source_key: null,
    rules: {
      name: 'Club Thug',
      size: 'medium',
      armor_class: 12,
      max_hp: 11,
      speed: { walk: '30 ft.' },
      actions: [{ name: 'Club', attack_bonus: 4, damage_dice: '1d6+2' }],
    } as unknown as MonsterLibraryDetailView['rules'],
    presentation: { names: {}, name_is_custom: true },
    revision: 1,
    archived_at: null,
    created_at: null,
    updated_at: null,
  }
}

function fullDetail(): MonsterLibraryDetailView {
  const quick = quickEnemyDetail()
  return {
    ...quick,
    rules: {
      ...(quick.rules as unknown as Record<string, unknown>),
      type: 'humanoid',
      alignment: 'unaligned',
      challenge_rating: 0,
      description: 'A thug.',
      ability_scores: {
        strength: 14,
        dexterity: 10,
        constitution: 12,
        intelligence: 8,
        wisdom: 9,
        charisma: 7,
      },
      traits: [{ name: 'Pack Tactics', desc: 'Advantage.' }],
    } as unknown as MonsterLibraryDetailView['rules'],
  }
}

describe('M07-D F12 quick-enemy template form', () => {
  it('loads a quick-enemy shape without throwing and marks missing fields unset', () => {
    const form = customMonsterFormFromDetail(quickEnemyDetail())
    expect(form.name).toBe('Club Thug')
    expect(form.armorClass).toBe(12)
    expect(form.maxHp).toBe(11)
    expect(form.size).toBe('medium')
    expect(form.type).toBe('')
    expect(form.alignment).toBe('')
    expect(form.speed).toBe('30 ft.')
    expect(form.challengeRating).toBe(0)
    expect(form.description).toBe('')
    for (const score of Object.values(form.abilities)) {
      expect(score).toBeNull()
    }
  })

  it('tolerates non-object ability_scores, type, and alignment without throwing', () => {
    const detail = quickEnemyDetail()
    const rules = detail.rules as unknown as Record<string, unknown>
    rules['ability_scores'] = 'strong'
    rules['type'] = 42
    rules['alignment'] = ['chaotic']
    rules['speed'] = null
    const form = customMonsterFormFromDetail(detail)
    expect(form.type).toBe('')
    expect(form.alignment).toBe('')
    expect(form.speed).toBe('30 ft.')
    for (const score of Object.values(form.abilities)) {
      expect(score).toBeNull()
    }
  })

  it('changing only AC on a quick-enemy template sends only armor_class', () => {
    const baseline = customMonsterFormFromDetail(quickEnemyDetail())
    const current: CustomMonsterFormValues = { ...baseline, armorClass: 16 }
    expect(customMonsterScalarPatch(baseline, current, 1)).toEqual({
      expected_revision: 1,
      armor_class: 16,
    })
  })

  it('leaving a quick-enemy template untouched sends no rule fields', () => {
    const baseline = customMonsterFormFromDetail(quickEnemyDetail())
    expect(customMonsterScalarPatch(baseline, { ...baseline }, 3)).toEqual({
      expected_revision: 3,
    })
  })

  it('setting a previously-unset type is sent; clearing a set type is not', () => {
    const baseline = customMonsterFormFromDetail(quickEnemyDetail())
    const setType: CustomMonsterFormValues = { ...baseline, type: 'humanoid' }
    expect(customMonsterScalarPatch(baseline, setType, 1)).toEqual({
      expected_revision: 1,
      type: 'humanoid',
    })
    const full = customMonsterFormFromDetail(fullDetail())
    const cleared: CustomMonsterFormValues = { ...full, type: '' }
    const patch = customMonsterScalarPatch(full, cleared, 1)
    expect(patch).toEqual({ expected_revision: 1 })
    expect('type' in patch).toBe(false)
  })

  it('sends only the ability scores the DM actually set', () => {
    const baseline = customMonsterFormFromDetail(quickEnemyDetail())
    const current: CustomMonsterFormValues = {
      ...baseline,
      abilities: { ...baseline.abilities, strength: 14 },
    }
    expect(customMonsterScalarPatch(baseline, current, 1)).toEqual({
      expected_revision: 1,
      ability_scores: { strength: 14 },
    })
  })

  it('does not resend an unchanged full-shape template', () => {
    const baseline = customMonsterFormFromDetail(fullDetail())
    expect(customMonsterScalarPatch(baseline, { ...baseline }, 2)).toEqual({
      expected_revision: 2,
    })
  })

  it('monsterSpeedString reads string, walk-object, and missing shapes', () => {
    expect(monsterSpeedString('25 ft.')).toBe('25 ft.')
    expect(monsterSpeedString({ walk: '30 ft.', fly: '40 ft.' })).toBe('30 ft.')
    expect(monsterSpeedString(undefined)).toBe('30 ft.')
    expect(monsterSpeedString(null)).toBe('30 ft.')
    expect(monsterSpeedString({ swim: '20 ft.' })).toBe('30 ft.')
  })
})
