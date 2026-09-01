import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

import type { BuilderChoice, BuilderChoiceOption } from '../api/characterBuilder'
import {
  builderChoiceLabel,
  builderChoiceOptionLabel,
} from './builderChoicePresentation'
import type { ContentNameResolver } from './useContentPresentations'

const nameFor: ContentNameResolver = (referenceId, fallback = '') => {
  const names: Record<string, string> = {
    'vrgr:lineage:dhampir': '達姆匹爾',
    'srd5.1:skill:perception': '察覺',
  }
  return referenceId ? (names[referenceId] ?? fallback) : fallback
}

function choice(
  optionSource: string,
  label: string,
  sourceRef: string | null = 'vrgr:lineage:dhampir',
): BuilderChoice {
  return {
    choice_id: `test:${optionSource}`,
    label,
    source_ref: sourceRef,
    required: true,
    choose_count: 1,
    option_source: optionSource,
    options: [],
    selected_option_ids: [],
    allow_duplicates: false,
  }
}

function option(
  optionId: string,
  label: string,
  referenceId: string | null = null,
): BuilderChoiceOption {
  return {
    option_id: optionId,
    label,
    kind: referenceId ? 'reference' : 'branch',
    reference_id: referenceId,
  }
}

describe('M01-F lineage Builder presentation', () => {
  it('localizes lineage choice labels and lineage-specific options', () => {
    const lineage = choice('content:lineage', 'Lineage', null)
    const size = choice('content:lineage-size', 'Dhampir — Size')
    const movement = choice(
      'content:lineage-legacy-movement',
      'Dhampir — Retain Ancestral Movement',
    )
    const asi = choice('content:lineage-asi-ability', 'Dhampir — +1 Ability')
    const skill = choice(
      'content:lineage-legacy-skill',
      'Dhampir — Ancestral Legacy Skills',
    )

    expect(builderChoiceLabel(lineage, 'zh-TW', nameFor)).toBe('血裔')
    expect(builderChoiceLabel(size, 'zh-TW', nameFor)).toBe('達姆匹爾 — 體型')
    expect(builderChoiceOptionLabel(size, option('lineage-size:small', 'Small'), 'zh-TW', nameFor)).toBe('小型')
    expect(
      builderChoiceOptionLabel(
        movement,
        option('lineage-movement:swim', 'Swim'),
        'zh-TW',
        nameFor,
      ),
    ).toBe('游泳')
    expect(
      builderChoiceOptionLabel(
        asi,
        option('lineage-ability:con:1', 'CON +1'),
        'zh-TW',
        nameFor,
      ),
    ).toBe('體質 +1')
    expect(
      builderChoiceOptionLabel(
        skill,
        option('srd5.1:skill:perception', 'Perception', 'srd5.1:skill:perception'),
        'zh-TW',
        nameFor,
      ),
    ).toBe('察覺')
  })

  it('keeps the Origin-step typed lineage selector wired to lineage_selection', () => {
    const source = readFileSync(
      new URL('../features/character-builder/CharacterBuilderPage.tsx', import.meta.url),
      'utf8',
    )

    expect(source).toContain("'content:lineage',")
    expect(source).toContain("const lineageChoice = choicesBySource.get('content:lineage')")
    expect(source).toContain('view.draft.draft_payload.lineage_selection?.reference_id')
    expect(source).toContain("| 'lineage_selection'")
    expect(source).toContain("if (field === 'lineage_selection' && lineageChoice)")
    expect(source).toContain("onChange={(value) => patchReference('lineage_selection', value)}")
  })
})
