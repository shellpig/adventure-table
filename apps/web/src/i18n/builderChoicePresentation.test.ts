import { describe, expect, it } from 'vitest'

import type { BuilderChoice } from '../api/characterBuilder'
import {
  builderChoiceLabel,
  builderChoiceOptionLabel,
} from './builderChoicePresentation'

const nameFor = (reference: string | null | undefined, fallback = '') => {
  if (reference === 'srd5.1:race:human') return '人類'
  if (reference === 'srd5.1:class:fighter') return '戰士'
  if (reference === 'srd5.1:equipment:javelin') return '標槍'
  if (reference === 'srd5.1:equipment:shield') return '盾牌'
  if (reference === 'srd5.1:proficiency:thieves-tools') return '盜賊工具'
  return fallback || reference || ''
}

function choice(overrides: Partial<BuilderChoice>): BuilderChoice {
  return {
    choice_id: 'choice:test',
    label: 'Human — Languages',
    source_ref: 'srd5.1:race:human',
    required: true,
    choose_count: 1,
    option_source: 'content:language_options',
    options: [],
    selected_option_ids: [],
    allow_duplicates: false,
    ...overrides,
  }
}

describe('builderChoicePresentation', () => {
  it('uses option_source rather than English display text for zh-TW headings', () => {
    expect(builderChoiceLabel(choice({}), 'zh-TW', nameFor)).toBe('人類 — 語言')
  })

  it('keeps the server label unchanged in English mode', () => {
    expect(builderChoiceLabel(choice({}), 'en', nameFor)).toBe('Human — Languages')
  })

  it('preserves ASI class level while localizing the class and heading', () => {
    const asi = choice({
      label: 'Fighter 4 — ASI or Feat',
      source_ref: 'srd5.1:class:fighter',
      option_source: 'content:asi-feat',
    })
    expect(builderChoiceLabel(asi, 'zh-TW', nameFor)).toBe('戰士 4 — 屬性值提升或專長')
  })

  it('localizes synthetic ASI ability options without inventing StableKeys', () => {
    const asi = choice({
      label: 'Assign 2 ability score points',
      source_ref: 'srd5.1:class:fighter',
      option_source: 'content:asi-ability',
    })
    expect(
      builderChoiceOptionLabel(
        asi,
        {
          option_id: 'ability:strength',
          label: 'STR +1',
          kind: 'counted_reference',
          count: 1,
        },
        'zh-TW',
        nameFor,
      ),
    ).toBe('力量 +1')
  })

  it('localizes the synthetic ASI branch label by branch identity', () => {
    const asi = choice({
      label: 'Fighter 4 — ASI or Feat',
      source_ref: 'srd5.1:class:fighter',
      option_source: 'content:asi-feat',
    })
    expect(
      builderChoiceOptionLabel(
        asi,
        {
          option_id: 'level:4:fighter:asi',
          label: 'Ability Score Improvement',
          kind: 'branch',
          branch_key: 'asi',
        },
        'zh-TW',
        nameFor,
      ),
    ).toBe('屬性值提升')
  })

  it('rebuilds equipment bundles from StableKey presentation metadata', () => {
    const equipment = choice({
      label: 'Choose a martial weapon or bundle',
      source_ref: 'srd5.1:class:fighter',
      option_source: 'equipment',
    })
    expect(builderChoiceLabel(equipment, 'zh-TW', nameFor)).toBe('起始裝備選擇')
    expect(
      builderChoiceOptionLabel(
        equipment,
        {
          option_id: 'equipment:fighter:bundle:0',
          label: '2 × Javelin + Shield + choose another item',
          kind: 'branch',
          presentation_items: [
            { reference_id: 'srd5.1:equipment:javelin', count: 2 },
            { reference_id: 'srd5.1:equipment:shield', count: 1 },
          ],
          presentation_has_choice: true,
        },
        'zh-TW',
        nameFor,
      ),
    ).toBe('2 × 標槍 + 盾牌 + 裝備選擇')
  })
})

describe('feature branch options the SRD left undescribed', () => {
  const expertise = choice({
    choice_id: 'level:1:srd5.1:feature:rogue-expertise-1:feature-specific-expertise_options',
    label: 'Expertise — choice',
    source_ref: 'srd5.1:feature:rogue-expertise-1',
    option_source: 'content:feature:feature-specific-expertise_options',
  })

  const twoSkills = {
    option_id: 'branch:0',
    label: 'Choose 2',
    kind: 'nested_choice' as const,
    count: 2,
    presentation_has_choice: true,
  }

  const bundle = {
    option_id: 'bundle:1',
    label: "Choose 1 + Thieves' Tools",
    kind: 'branch' as const,
    count: 1,
    presentation_has_choice: true,
    presentation_items: [{ reference_id: 'srd5.1:proficiency:thieves-tools', count: 1 }],
    granted_reference_ids: ['srd5.1:proficiency:thieves-tools'],
  }

  it('builds the zh-TW branch labels from structure, not from the English sentence', () => {
    expect(builderChoiceOptionLabel(expertise, twoSkills, 'zh-TW', nameFor)).toBe('選 2 項')
    expect(builderChoiceOptionLabel(expertise, bundle, 'zh-TW', nameFor)).toBe(
      '選 1 項 + 盜賊工具',
    )
  })

  it('keeps the server labels in English mode', () => {
    expect(builderChoiceOptionLabel(expertise, twoSkills, 'en', nameFor)).toBe('Choose 2')
    expect(builderChoiceOptionLabel(expertise, bundle, 'en', nameFor)).toBe(
      "Choose 1 + Thieves' Tools",
    )
  })
})
