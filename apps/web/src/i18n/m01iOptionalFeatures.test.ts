import { describe, expect, it } from 'vitest'

import type { BuilderChoice } from '../api/characterBuilder'
import {
  builderChoiceLabel,
  builderChoiceOptionLabel,
} from './builderChoicePresentation'
import { localizedDisabledReason } from './systemMessages'

const names: Record<string, string> = {
  'tce:feature:blessed-warrior': '祝福戰士',
  'tce:feature:bardic-versatility': '吟遊詩人多才多藝',
  'srd5.1:spell:guidance': '神導術',
}

const nameFor = (reference: string | null | undefined, fallback = '') =>
  (reference ? names[reference] : undefined) ?? fallback ?? reference ?? ''

function choice(overrides: Partial<BuilderChoice>): BuilderChoice {
  return {
    choice_id: 'm01-i:test',
    label: 'Blessed Warrior — Optional Class Feature',
    source_ref: 'tce:feature:blessed-warrior',
    required: false,
    choose_count: 1,
    option_source: 'content:optional-class-feature',
    options: [],
    selected_option_ids: [],
    allow_duplicates: false,
    ...overrides,
  }
}

describe('M01-I optional feature localization', () => {
  it('localizes optional feature and nested cantrip headings by StableKey identity', () => {
    const optional = choice({})
    const nested = choice({
      label: 'Blessed Warrior — Choice',
      required: true,
      choose_count: 2,
      option_source: 'content:optional-feature:cantrip',
    })

    expect(builderChoiceLabel(optional, 'zh-TW', nameFor)).toBe('祝福戰士 — 選用職業特性')
    expect(builderChoiceLabel(nested, 'zh-TW', nameFor)).toBe('祝福戰士 — 戲法選擇')
    expect(builderChoiceLabel(optional, 'en', nameFor)).toBe('Blessed Warrior — Optional Class Feature')
    expect(optional.source_ref).toBe('tce:feature:blessed-warrior')
  })

  it('localizes retraining headings and synthetic Replace branch without changing option identity', () => {
    const retraining = choice({
      label: 'Bardic Versatility — Cantrip Versatility',
      source_ref: 'tce:feature:bardic-versatility',
      option_source: 'content:optional-feature:retraining-action',
    })
    const option = {
      option_id: 'level:4:m01-i:replace',
      label: 'Replace one choice',
      kind: 'branch' as const,
      branch_key: 'replace',
    }

    expect(builderChoiceLabel(retraining, 'zh-TW', nameFor)).toBe('吟遊詩人多才多藝 — 重訓')
    expect(builderChoiceOptionLabel(retraining, option, 'zh-TW', nameFor)).toBe('替換一個選項')
    expect(builderChoiceOptionLabel(retraining, option, 'en', nameFor)).toBe('Replace one choice')
    expect(option.option_id).toBe('level:4:m01-i:replace')
  })

  it('uses localized content names for reference options', () => {
    const nested = choice({
      option_source: 'content:optional-feature:cantrip',
      required: true,
      choose_count: 2,
    })
    const option = {
      option_id: 'srd5.1:spell:guidance',
      label: 'Guidance · SRD 5.1',
      kind: 'reference' as const,
      reference_id: 'srd5.1:spell:guidance',
    }

    expect(builderChoiceOptionLabel(nested, option, 'zh-TW', nameFor)).toBe('神導術')
    expect(option.reference_id).toBe('srd5.1:spell:guidance')
  })

  it('does not leak canonical English disabled reasons into zh-TW when a new code uses fallback copy', () => {
    const english = 'This option requires another class feature.'
    expect(localizedDisabledReason(english, 'zh-TW', 'optional_pool_feature_prerequisite_not_met'))
      .toBe('此選項目前無法選擇；請先完成相關條件。')
    expect(localizedDisabledReason(english, 'en', 'optional_pool_feature_prerequisite_not_met'))
      .toBe(english)
  })
})
