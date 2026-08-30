import { describe, expect, it } from 'vitest'

import type { BuilderChoice } from '../api/characterBuilder'
import {
  builderChoiceLabel,
  builderChoiceOptionLabel,
} from './builderChoicePresentation'

const nameFor = (reference: string | null | undefined, fallback = '') => {
  if (reference === 'srd5.1:race:human') return '人類'
  if (reference === 'srd5.1:class:fighter') return '戰士'
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
})
