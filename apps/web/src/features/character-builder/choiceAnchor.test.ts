import { describe, expect, it } from 'vitest'

import { issueChoiceId, issueStep } from './choiceAnchor'

describe('issueStep', () => {
  it.each([
    ['draft_payload.basic.name', 'basic'],
    ['draft_payload.target_level', 'basic'],
    ['draft_payload.race_selection', 'origin'],
    ['draft_payload.race_selection.reference_id', 'origin'],
    ['draft_payload.subrace_selection', 'origin'],
    ['draft_payload.race_variant_selection.reference_id', 'origin'],
    ['draft_payload.lineage_selection', 'origin'],
    ['draft_payload.background_selection', 'origin'],
    ['draft_payload.alignment_selection.reference_id', 'origin'],
    ['draft_payload.ability_generation', 'abilities'],
    ['draft_payload.ability_generation.scores', 'abilities'],
    ['draft_payload.level_choices', 'class'],
    ['draft_payload.level_choices.2.subclass_ref', 'class'],
    ['draft_payload.choice_selections', 'class'],
    ['draft_payload.spell_choices.profile-1.known_spell_keys', 'spells'],
    ['draft_payload.starting_equipment_choices.eq-1.option.0.choice', 'equipment'],
  ] as const)('maps %s to the %s step', (path, step) => {
    expect(issueStep(path)).toBe(step)
  })

  it.each([
    'draft_payload',
    'draft_payload.numeric_overrides',
    'draft.base_version_id',
    'build.feature_refs',
    'content',
    'state.current_hp',
  ])('leaves %s without a step', (path) => {
    expect(issueStep(path)).toBeNull()
  })
})

describe('issueChoiceId', () => {
  it('reads the choice id after a selection prefix', () => {
    expect(issueChoiceId('draft_payload.choice_selections.level:4:asi-feat:0')).toBe('level:4:asi-feat:0')
    expect(issueChoiceId('draft_payload.starting_equipment_choices.eq-1')).toBe('eq-1')
  })

  it('returns null for group-level and unrelated paths', () => {
    expect(issueChoiceId('draft_payload.choice_selections')).toBeNull()
    expect(issueChoiceId('draft_payload.level_choices')).toBeNull()
  })
})
